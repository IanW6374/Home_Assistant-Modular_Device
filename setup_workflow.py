"""First-boot provisioning workflow independent of the HTTP controller."""

try:
    import uasyncio as asyncio
except ImportError:
    import asyncio
try:
    import network
except ImportError:
    network = None
try:
    import ujson as json
except ImportError:
    import json
try:
    import machine
except ImportError:
    machine = None
try:
    import uos as os
except ImportError:
    import os
try:
    import ussl as ssl
except ImportError:
    import ssl

import app_update
import certificate_manager
import credential_store
import release_update
import wifi_recovery

CERTIFICATE_PATHS = {
    'trust-ca': 'certs/trust/home-rca-root.der',
    'portal-cert': 'certs/web.crt.der',
    'portal-key': 'certs/web.key.der',
}

def _file_exists(path):
    try:
        return os.stat(path)[6] > 0
    except OSError:
        return False

def _preloaded_application_available():
    state = app_update.update_status()
    if state.get('status') == 'ready' and state.get('has_application') is True:
        return True
    slot = app_update.active_slot()
    return bool(slot and app_update.validate_slot_integrity(slot))

def _prepare_available_application():
    state = app_update.update_status()
    if state.get('status') == 'ready' and state.get('has_application') is True:
        return _prepare_setup_application(state)
    slot = app_update.active_slot()
    if slot and app_update.validate_slot_integrity(slot):
        return {
            'status': 'installed',
            'version': app_update.running_version(),
            'has_application': True,
        }
    return None

def _replace_file(source, target):
    try:
        os.remove(target)
    except OSError:
        pass
    os.rename(source, target)

def _write_certificate(kind, payload, suffix=''):
    path = CERTIFICATE_PATHS.get(kind)
    if not path:
        raise ValueError('unknown certificate type')
    payload = bytes(payload)
    if not payload or len(payload) > MAX_CERTIFICATE_BYTES:
        raise ValueError('certificate file size is invalid')
    if b'-----BEGIN' in payload:
        raise ValueError('certificate files must use DER, not PEM')
    try:
        os.mkdir('certs')
    except OSError:
        pass
    try:
        os.mkdir('certs/trust')
    except OSError:
        pass
    path += str(suffix)
    temporary = path + '.setup'
    with open(temporary, 'wb') as stream:
        stream.write(payload)
    _replace_file(temporary, path)
    return path

def _validate_certificates(
    require_trust=True, portal_cert=None, portal_key=None, trust_ca=None
):
    portal_cert = portal_cert or CERTIFICATE_PATHS['portal-cert']
    portal_key = portal_key or CERTIFICATE_PATHS['portal-key']
    trust_ca = trust_ca or CERTIFICATE_PATHS['trust-ca']
    server = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    server.load_cert_chain(portal_cert, portal_key)
    if not require_trust:
        return True
    client = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    try:
        client.load_verify_locations(cafile=trust_ca)
    except TypeError:
        with open(trust_ca, 'rb') as stream:
            client.load_verify_locations(cadata=stream.read())
    return True

def _validate_certificate_files(certificate_mode):
    """Confirm the installed files match the certificate route being completed."""
    certificate_mode = str(certificate_mode or '').strip()
    if certificate_mode not in ('self_signed', 'manual', 'acme'):
        raise ValueError('certificate setup choice is invalid')
    _validate_certificates(require_trust=certificate_mode != 'self_signed')
    portal = certificate_manager.certificate_details(CERTIFICATE_PATHS['portal-cert'])
    if not portal.get('installed'):
        raise ValueError('portal certificate is not installed')
    if portal.get('error'):
        raise ValueError('portal certificate could not be decoded: ' + str(portal['error']))
    subject = str(portal.get('subject', '')).strip()
    issuer = str(portal.get('issuer', '')).strip()
    if not subject or not issuer:
        raise ValueError('portal certificate identity is incomplete')
    if certificate_mode == 'self_signed' and subject != issuer:
        raise ValueError('installed portal certificate is not the self-signed fallback')
    if certificate_mode == 'acme' and subject == issuer:
        raise ValueError('ACME enrollment returned a self-issued portal certificate')
    if certificate_mode != 'self_signed':
        trusted_ca = certificate_manager.certificate_details(CERTIFICATE_PATHS['trust-ca'])
        if not trusted_ca.get('installed'):
            raise ValueError('trusted CA certificate was not preserved')
        if trusted_ca.get('error'):
            raise ValueError(
                'trusted CA certificate could not be decoded: ' + str(trusted_ca['error'])
            )
    return True

def _validate_certificate_selection(config, selected_mode):
    """Reject stale pages or ambiguous completion of a different certificate route."""
    selected_mode = str(selected_mode or '').strip()
    stored_mode = str(config.get('certificate', {}).get('mode', '')).strip()
    if selected_mode != stored_mode:
        raise ValueError(
            'certificate setup changed; return to the certificate page and confirm the installed mode'
        )
    return _validate_certificate_files(selected_mode)

def _prepare_certificate_selection(config, selected_mode):
    """Restore the explicit self-signed fallback after an interrupted replacement."""
    selected_mode = str(selected_mode or '').strip()
    stored_mode = str(config.get('certificate', {}).get('mode', '')).strip()
    if selected_mode == stored_mode == 'self_signed':
        portal = certificate_manager.certificate_details(CERTIFICATE_PATHS['portal-cert'])
        if (
            not portal.get('installed') or portal.get('error') or
            portal.get('subject') != portal.get('issuer')
        ):
            certificate_manager.install_self_signed(
                config.get('certificate', {}).get('hostname', '')
            )
    return _validate_certificate_selection(config, selected_mode)

def _set_rtc_from_browser_time(value):
    """Set UTC from an authenticated setup browser without weakening TLS."""
    value = str(value or '').strip()
    if len(value) < 20 or value[4] != '-' or value[7] != '-' or value[10] != 'T':
        raise ValueError('current UTC time is missing or invalid')
    try:
        year = int(value[0:4])
        month = int(value[5:7])
        day = int(value[8:10])
        hour = int(value[11:13])
        minute = int(value[14:16])
        second = int(value[17:19])
    except Exception:
        raise ValueError('current UTC time is missing or invalid')
    if not (
        2024 <= year <= 2100 and 1 <= month <= 12 and 1 <= day <= 31 and
        0 <= hour <= 23 and 0 <= minute <= 59 and 0 <= second <= 59
    ):
        raise ValueError('current UTC time is outside the supported range')
    if machine is None:
        return (year, month, day, hour, minute, second)
    machine.RTC().datetime((year, month, day, 0, hour, minute, second, 0))
    return (year, month, day, hour, minute, second)

def _form_values(params):
    if params.get('portal_password') != params.get('portal_password_confirm'):
        raise ValueError('portal passwords do not match')
    if params.get('recovery_password') != params.get('recovery_password_confirm'):
        raise ValueError('recovery console passwords do not match')
    if params.get('recovery_ap_password') != params.get('recovery_ap_password_confirm'):
        raise ValueError('recovery AP passwords do not match')
    passwords = (
        params.get('portal_password', ''), params.get('recovery_password', ''),
        params.get('recovery_ap_password', '')
    )
    if len(set(passwords)) != len(passwords):
        raise ValueError('portal, recovery console and recovery AP passwords must all differ')
    hostname = params.get('certificate_hostname', '').strip().lower().rstrip('.')
    if not hostname.endswith('.local') or '.' in hostname[:-6]:
        raise ValueError('portal mDNS hostname must be a single label followed by .local')
    return {
        'device_name': params.get('device_name', ''),
        'wifi_ssid': params.get('wifi_ssid', ''),
        'wifi_password': params.get('wifi_password', ''),
        'wifi_dhcp': str(params.get('wifi_dhcp', '')).lower() in ('1', 'true', 'on'),
        'wifi_ip_address': params.get('wifi_ip_address', '').strip(),
        'wifi_subnet_mask': params.get('wifi_subnet_mask', '').strip(),
        'wifi_gateway': params.get('wifi_gateway', '').strip(),
        'wifi_dns_server': params.get('wifi_dns_server', '').strip(),
        'mqtt_server': '',
        'mqtt_port': 8883,
        'mqtt_username': '',
        'mqtt_password': '',
        'mqtt_ssl': True,
        'portal_username': params.get('portal_username', ''),
        'portal_transport': params.get('portal_transport', 'auto'),
        'recovery_ap_password': params.get('recovery_ap_password', ''),
        'channel': 'stable',
        'install_mode': params.get('install_mode', 'upload'),
        'certificate_mode': 'self_signed',
        'certificate_hostname': hostname,
    }

async def _connect_station(ssid, password, timeout_s=30, hostname='', wifi=None):
    if network is None:
        raise RuntimeError('Wi-Fi is unavailable')
    if hostname:
        certificate_manager.configure_network_hostname(hostname)
    wlan_class = network.WLAN
    interface = getattr(wlan_class, 'IF_STA', getattr(network, 'STA_IF', 0))
    station = wlan_class(interface)
    credential_store.configure_station(station, wifi or {'dhcp': True})
    if station.isconnected():
        return station
    station.connect(ssid, password)
    remaining = int(timeout_s)
    while remaining > 0 and not station.isconnected():
        await asyncio.sleep(1)
        remaining -= 1
    if not station.isconnected():
        raise OSError('could not connect to the selected Wi-Fi network')
    return station

def _prepare_setup_application(state):
    groups = set(state.get('optional_groups', ()))
    return app_update.configure_pending_update({
        'module_settings': 'module_settings' in groups,
    })

async def _download_application(config):
    if not factory_config.SETUP_RELEASE_MANIFEST_URL:
        raise ValueError('factory release service is not configured; upload a signed bundle')
    await _connect_station(
        config['wifi']['ssid'], config['wifi']['password'],
        wifi=config['wifi']
    )
    release = await release_update.check_release(
        factory_config.SETUP_RELEASE_MANIFEST_URL,
        config['release']['channel'],
        factory_config.SETUP_TRUST_CA_CERT_PATH,
    )
    if release.get('type') != 'application':
        raise ValueError('setup release service did not return an application')
    state = await release_update.stage_release(
        release, factory_config.SETUP_TRUST_CA_CERT_PATH,
        app_update.receive_bundle, None, allow_protected=False
    )
    return _prepare_setup_application(state)

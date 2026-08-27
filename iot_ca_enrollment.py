"""One-time IoT CA enrollment with device-local private keys."""

try:
    import uasyncio as asyncio
except ImportError:
    import asyncio
try:
    import ujson as json
except ImportError:
    import json
try:
    import ubinascii as binascii
except ImportError:
    import binascii
try:
    import uos as os
except ImportError:
    import os
try:
    import ussl as ssl
except ImportError:
    import ssl
import time

import certificate_manager
from certificate_codec import (
    _b64decode, _csr, _ec_private_key_der, _iso_epoch, _new_private_key,
)


PROTOCOL = 'iotmd-enrollment-v1'
MAX_PACKAGE_BYTES = 16384
MAX_POLLS = 210
POLL_SECONDS = 2
RENEWAL_CERTIFICATE_PATH = 'certs/iot-ca-renewal.crt.der'
RENEWAL_KEY_PATH = 'certs/iot-ca-renewal.key.der'
STATE_PATH = 'certs/iot-ca-enrollment.json'
DEFAULT_SERVER = 'iot-ca.home.arpa'
DEFAULT_PROVISIONING_PORT = 9010


def _log_failure(source, exc):
    """Log through the application when mounted, otherwise use USB console.

    First-boot enrollment is frozen into the core and runs before the
    application slot is added to ``sys.path``.  It must therefore never import
    an application-only logging module while the setup access point starts.
    """
    message = 'Failed - ' + str(exc)
    try:
        from device_modules.logging import log_output
        log_output(
            'Local', str(source), {'log': message}, 'ERROR'
        )
        return
    except Exception:
        pass
    try:
        print('ERROR ' + str(source) + ': ' + message)
    except Exception:
        pass


def _write(path, payload):
    temporary = path + '.tmp'
    with open(temporary, 'wb') as stream:
        stream.write(bytes(payload))
    try:
        os.remove(path)
    except OSError:
        pass
    os.rename(temporary, path)


def _b64(value):
    return binascii.b2a_base64(bytes(value)).decode().strip()


def _failure_message(exc, endpoint=''):
    """Turn port-specific socket errors into an actionable setup message."""
    detail = str(exc).strip()
    values = getattr(exc, 'args', ())
    code = values[0] if values else None
    if code in (-202, 202) or detail in ('-202', '[Errno -202]'):
        host = str(endpoint or '').split('://')[-1].split('/', 1)[0]
        return (
            'Could not resolve the IoT CA server' +
            ((' (' + host + ')') if host else '') +
            '. Check the CA DNS name and the DNS server supplied to this device.'
        )
    return detail or exc.__class__.__name__


def _auto_server(value):
    server = str(value or DEFAULT_SERVER).strip().lower().rstrip('.')
    if (
        not server or len(server) > 253 or '..' in server or
        any(character not in 'abcdefghijklmnopqrstuvwxyz0123456789-.'
            for character in server) or
        any(not label or label.startswith('-') or label.endswith('-') or len(label) > 63
            for label in server.split('.'))
    ):
        raise ValueError('IoT CA server name is invalid')
    return server


def _auto_port(value):
    if value in (None, ''):
        return DEFAULT_PROVISIONING_PORT
    try:
        port = int(value)
    except (TypeError, ValueError):
        raise ValueError('IoT CA provisioning port is invalid')
    if port < 1 or port > 65535:
        raise ValueError('IoT CA provisioning port must be between 1 and 65535')
    return port


def _bootstrap_tls_context():
    """Create the deliberately unpinned context used only during opt-in LAN pairing.

    The returned authorization embeds the private CA root. Every certificate
    request after this bootstrap exchange is verified against that root.
    """
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    if hasattr(context, 'check_hostname'):
        context.check_hostname = False
    if hasattr(context, 'verify_mode') and hasattr(ssl, 'CERT_NONE'):
        context.verify_mode = ssl.CERT_NONE
    return context


async def automatic_package(
    server, expected_api_hostname, port=DEFAULT_PROVISIONING_PORT
):
    """Request a short-lived host authorization during an enabled CA window."""
    server = _auto_server(server)
    port = _auto_port(port)
    endpoint = 'https://' + server + ':' + str(port)
    body = json.dumps({
        'api_hostname': str(expected_api_hostname).strip().lower().rstrip('.')
    }, separators=(',', ':')).encode()
    status, _headers, payload = await certificate_manager._response(
        endpoint + '/v1/auto-enrollments', 'POST', '', body,
        'application/json', 'application/json', (), _bootstrap_tls_context()
    )
    try:
        value = json.loads(payload.decode()) if payload else {}
    except Exception:
        raise ValueError('IoT CA automatic enrollment returned an invalid response')
    if status < 200 or status >= 300:
        raise ValueError(str(value.get(
            'error', 'IoT CA automatic enrollment failed: HTTP ' + str(status)
        )))
    encoded = json.dumps(value, separators=(',', ':')).encode()
    _package(encoded, expected_api_hostname)
    return encoded


def _package(payload, expected_api_hostname):
    payload = bytes(payload)
    if not payload or len(payload) > MAX_PACKAGE_BYTES:
        raise ValueError('IoT CA enrollment file size is invalid')
    try:
        value = json.loads(payload.decode())
    except Exception:
        raise ValueError('IoT CA enrollment file is not valid JSON')
    required = (
        'protocol', 'enrollment_id', 'endpoint', 'token', 'portal_hostname',
        'api_hostname', 'renewal_name', 'ca_root_der', 'expires_at',
    )
    if not isinstance(value, dict) or any(not value.get(name) for name in required):
        raise ValueError('IoT CA enrollment file is incomplete')
    if value['protocol'] != PROTOCOL:
        raise ValueError('IoT CA enrollment protocol is unsupported')
    endpoint = str(value['endpoint']).rstrip('/')
    if not endpoint.startswith('https://'):
        raise ValueError('IoT CA enrollment endpoint must use HTTPS')
    if str(value['api_hostname']).lower().rstrip('.') != str(
        expected_api_hostname
    ).lower().rstrip('.'):
        raise ValueError('IoT CA enrollment file is authorized for another device hostname')
    now = int(time.time())
    expires = _iso_epoch(value['expires_at'])
    if now >= 1577836800 and (not expires or expires <= now):
        raise ValueError('IoT CA enrollment authorization has expired')
    root = _b64decode(value['ca_root_der'])
    if not root or len(root) > 8192:
        raise ValueError('IoT CA enrollment trust anchor is invalid')
    value['endpoint'] = endpoint
    value['ca_root_der'] = root
    return value


async def _request(url, method, ca_path, token, body=b''):
    status, _headers, payload = await certificate_manager._response(
        url, method, ca_path, body,
        'application/json' if body else '', 'application/json',
        (('Authorization', 'Bearer ' + str(token)),),
    )
    try:
        value = json.loads(payload.decode()) if payload else {}
    except Exception:
        raise ValueError('IoT CA returned an invalid response')
    if status < 200 or status >= 300:
        raise ValueError(str(value.get('error', 'IoT CA request failed: HTTP ' + str(status))))
    return value


async def enroll(payload, expected_api_hostname, paths, progress=None):
    """Request and atomically install a host-bound certificate set."""
    package = _package(payload, expected_api_hostname)

    def report(message):
        if progress:
            progress(message)

    suffix = '.iotca'
    staged = {name: path + suffix for name, path in paths.items()}
    staged_renewal_cert = RENEWAL_CERTIFICATE_PATH + suffix
    staged_renewal_key = RENEWAL_KEY_PATH + suffix
    staged_state = STATE_PATH + suffix
    all_staged = list(staged.values()) + [
        staged_renewal_cert, staged_renewal_key, staged_state,
    ]
    try:
        report('Installing the pinned IoT CA trust anchor')
        _write(staged['trust-ca'], package['ca_root_der'])
        portal_key = _new_private_key()
        api_key = _new_private_key()
        renewal_key = _new_private_key()
        request_value = {
            'portal_csr': _b64(_csr(
                portal_key, package['portal_hostname'], True, False, True
            )),
            'api_csr': _b64(_csr(
                api_key, package['api_hostname'], True, False, True
            )),
            'renewal_csr': _b64(_csr(
                renewal_key, package['renewal_name'], False, True, False
            )),
        }
        url = package['endpoint'] + '/v1/enrollments/' + package['enrollment_id']
        report('Submitting device-generated certificate requests')
        result = await _request(
            url, 'POST', staged['trust-ca'], package['token'],
            json.dumps(request_value, separators=(',', ':')).encode(),
        )
        for _index in range(MAX_POLLS):
            if result.get('status') == 'complete':
                break
            if result.get('status') in ('error', 'expired'):
                raise ValueError(str(result.get('error') or 'IoT CA enrollment failed'))
            report('Waiting for Cloudflare DNS validation and certificate issuance')
            await asyncio.sleep(POLL_SECONDS)
            result = await _request(
                url, 'GET', staged['trust-ca'], package['token']
            )
        if result.get('status') != 'complete' or not isinstance(result.get('result'), dict):
            raise ValueError('IoT CA did not complete enrollment in time')
        issued = result['result']
        if (
            issued.get('protocol') != PROTOCOL or
            issued.get('portal_hostname') != package['portal_hostname'] or
            issued.get('api_hostname') != package['api_hostname']
        ):
            raise ValueError('IoT CA response identity does not match the authorization')
        report('Validating the issued certificate set')
        _write(staged['portal-cert'], _b64decode(issued['portal_certificate_pem']))
        _write(staged['portal-key'], _ec_private_key_der(portal_key))
        _write(staged['api-server-cert'], _b64decode(issued['api_certificate_pem']))
        _write(staged['api-server-key'], _ec_private_key_der(api_key))
        _write(staged_renewal_cert, _b64decode(issued['renewal_certificate_der']))
        _write(staged_renewal_key, _ec_private_key_der(renewal_key))
        state = {
            'protocol': PROTOCOL,
            'endpoint': package['endpoint'],
            'enrollment_id': package['enrollment_id'],
            'portal_hostname': package['portal_hostname'],
            'api_hostname': package['api_hostname'],
            'renewal_name': package['renewal_name'],
            'portal_not_after': issued.get('portal_not_after', ''),
        }
        _write(staged_state, json.dumps(state, separators=(',', ':')).encode())
        return {
            'pairs': tuple(
                (staged[name], paths[name]) for name in (
                    'trust-ca', 'portal-cert', 'portal-key',
                    'api-server-cert', 'api-server-key',
                )
            ) + (
                (staged_renewal_cert, RENEWAL_CERTIFICATE_PATH),
                (staged_renewal_key, RENEWAL_KEY_PATH),
                (staged_state, STATE_PATH),
            ),
            'portal_hostname': package['portal_hostname'],
            'api_hostname': package['api_hostname'],
            'endpoint': package['endpoint'],
            'not_after': issued.get('portal_not_after', ''),
        }
    except Exception:
        for path in all_staged:
            try:
                os.remove(path)
            except OSError:
                pass
        raise


async def install(payload, config, paths, connect_station, validate, status):
    """Run first-boot enrollment and activate the complete identity set."""
    def progress(message):
        status['message'] = str(message)

    try:
        progress('Connecting to the home Wi-Fi')
        hostname = config['certificate']['hostname']
        await connect_station(
            config['wifi']['ssid'], config['wifi']['password'], hostname=hostname,
            wifi=config['wifi']
        )
        result = await enroll(payload, hostname, paths, progress)
        certificate_manager.commit_certificate_files(
            result['pairs'], validator=lambda: validate(
                True, paths['portal-cert'], paths['portal-key'], paths['trust-ca'],
                paths['api-server-cert'], paths['api-server-key'],
            )
        )
        saved = __import__('credential_store').update_certificate_settings(
            'iot_ca', result.get('endpoint', ''), hostname,
            portal_hostname=result['portal_hostname']
        )
        if (
            saved.get('mode') != 'iot_ca' or
            saved.get('portal_hostname') != result['portal_hostname']
        ):
            raise RuntimeError('IoT CA certificate settings were not preserved')
    except Exception as exc:
        _log_failure('IoT CA enrollment', exc)
        status['status'] = 'error'
        endpoint = ''
        try:
            endpoint = _package(payload, config['certificate']['hostname']).get('endpoint', '')
        except Exception:
            pass
        status['message'] = 'Setup failed: ' + _failure_message(exc, endpoint)
    else:
        status['status'] = 'complete'
        status['mode'] = 'iot_ca'
        status['message'] = (
            'IoT CA certificates installed until ' + str(result.get('not_after', ''))
        )


async def automatic_install(
    server, config, paths, connect_station, validate, status,
    port=DEFAULT_PROVISIONING_PORT
):
    """Obtain the one-time authorization and complete enrollment in one operation."""
    payload = b''
    server = _auto_server(server)
    port = _auto_port(port)
    endpoint = 'https://' + server + ':' + str(port)
    try:
        status['message'] = 'Connecting to the home Wi-Fi'
        hostname = config['certificate']['hostname']
        await connect_station(
            config['wifi']['ssid'], config['wifi']['password'], hostname=hostname,
            wifi=config['wifi']
        )
        status['message'] = 'Requesting a host-bound authorization from IoT CA'
        payload = await automatic_package(server, hostname, port)
        result = await enroll(
            payload, hostname, paths,
            lambda message: status.__setitem__('message', str(message))
        )
        certificate_manager.commit_certificate_files(
            result['pairs'], validator=lambda: validate(
                True, paths['portal-cert'], paths['portal-key'], paths['trust-ca'],
                paths['api-server-cert'], paths['api-server-key'],
            )
        )
        saved = __import__('credential_store').update_certificate_settings(
            'iot_ca', result.get('endpoint', ''), hostname,
            portal_hostname=result['portal_hostname']
        )
        if (
            saved.get('mode') != 'iot_ca' or
            saved.get('portal_hostname') != result['portal_hostname']
        ):
            raise RuntimeError('IoT CA certificate settings were not preserved')
    except Exception as exc:
        _log_failure('IoT CA auto enrollment', exc)
        status['status'] = 'error'
        status['message'] = 'Setup failed: ' + _failure_message(exc, endpoint)
    else:
        status['status'] = 'complete'
        status['mode'] = 'iot_ca'
        status['message'] = (
            'IoT CA certificates installed until ' + str(result.get('not_after', ''))
        )


def start_automatic(
    server, config, paths, connect_station, validate, status,
    port=DEFAULT_PROVISIONING_PORT
):
    """Record the operation before scheduling it so concurrent starts are rejected."""
    status.update({
        'status': 'running', 'mode': 'iot_ca',
        'message': 'Requesting automatic IoT CA enrollment',
    })
    return asyncio.create_task(automatic_install(
        server, config, paths, connect_station, validate, status, port
    ))

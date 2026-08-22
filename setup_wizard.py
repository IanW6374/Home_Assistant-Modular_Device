"""First-boot AP wizard for credentials and signed application selection."""

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

import app_update
import credential_store
import certificate_manager
import factory_config
import release_update
import wifi_recovery
import portal_ui
import http_support

try:
    import uos as os
except ImportError:
    import os

try:
    import ussl as ssl
except ImportError:
    import ssl


SETUP_PORT = 80
MAX_FORM_BYTES = 8192
MAX_CERTIFICATE_BYTES = 16384
MAX_CERTIFICATE_FORM_BYTES = MAX_FORM_BYTES + (MAX_CERTIFICATE_BYTES * 3)
CERTIFICATE_PATHS = {
    'trust-ca': 'certs/trust/home-rca-root.der',
    'portal-cert': 'certs/web.crt.der',
    'portal-key': 'certs/web.key.der',
}
HTTPS_PORT = 8443
HTTP_PORT = 8080
SETUP_ASSET_VERSION = '8'
SELF_SIGNED_READY_MESSAGE = (
    'Self-signed HTTPS is ready. Choose ACME, manual certificates, or the explicit fallback.'
)


def _asset(path):
    return str(path) + '?v=' + SETUP_ASSET_VERSION


def _parse_request_line(line):
    parts = str(line).split()
    if len(parts) != 3 or not parts[2].startswith('HTTP/'):
        return '', ''
    return parts[0], parts[1].split('?', 1)[0]


async def _read_body(reader, length, maximum):
    return await http_support.read_exact_body(reader, length, maximum)


def _escape(value):
    value = str(value)
    for old, new in (
        ('&', '&amp;'), ('<', '&lt;'), ('>', '&gt;'),
        ('"', '&quot;'), ("'", '&#39;')
    ):
        value = value.replace(old, new)
    return value


def _setup_header():
    return '<header class="topbar setup-topbar">' + portal_ui.brand() + '</header>'


def _setup_progress(step):
    markers = ''.join(
        '<span class="setup-step' + (' active' if index <= step else '') + '"></span>'
        for index in range(1, 5)
    )
    return '<div class="setup-steps" aria-label="Setup progress">' + markers + '</div>'


def _multipart_form(body, content_type):
    boundary = ''
    for item in str(content_type).split(';')[1:]:
        name, separator, value = item.strip().partition('=')
        if separator and name.lower() == 'boundary':
            boundary = value.strip().strip('"')
            break
    if not boundary or len(boundary) > 70 or '\r' in boundary or '\n' in boundary:
        raise ValueError('multipart form boundary is invalid')
    try:
        delimiter = b'--' + boundary.encode('ascii')
    except Exception:
        raise ValueError('multipart form boundary is invalid')
    values = {}
    for section in bytes(body).split(delimiter)[1:]:
        if section.startswith(b'--'):
            break
        if section.startswith(b'\r\n'):
            section = section[2:]
        header_end = section.find(b'\r\n\r\n')
        if header_end < 0:
            continue
        raw_headers = section[:header_end].decode('utf-8', 'replace')
        payload = section[header_end + 4:]
        if payload.endswith(b'\r\n'):
            payload = payload[:-2]
        field_name = ''
        for header in raw_headers.split('\r\n'):
            if header.lower().startswith('content-disposition:'):
                for parameter in header.split(';')[1:]:
                    name, separator, value = parameter.strip().partition('=')
                    if separator and name.lower() == 'name':
                        field_name = value.strip().strip('"')
        if field_name:
            values[field_name] = payload
    return values


def _page(csrf, message=''):
    notice = '<p class="notice" role="status">' + _escape(message) + '</p>' if message else ''
    if _preloaded_application_available():
        ready_text = (
            'The factory-installed signed application is ready. Upload will only be offered '
            'if its verification fails.'
        )
        application_control = '<input type="hidden" name="install_mode" value="upload">'
        application_status = (
            '<div class="setup-application-status"><span class="badge good tooltip-badge" '
            'tabindex="0" aria-label="' + ready_text + '" title="' + ready_text + '" '
            'data-tooltip="' + ready_text + '">Application ready</span></div>'
        )
    else:
        download_available = bool(factory_config.SETUP_RELEASE_MANIFEST_URL)
        install_options = (
            '<option value="download">Download the latest signed application</option>'
            if download_available else ''
        ) + '<option value="upload">Upload a signed application bundle</option>'
        application_control = (
            '<label class="field">Application fallback<select name="install_mode">' +
            install_options + '</select></label>'
        )
        application_status = ''
    return (
        '<!doctype html><html><head><meta name="viewport" '
        'content="width=device-width,initial-scale=1"><title>HAMD setup</title>'
        '<link rel="stylesheet" href="' + _asset('/assets/portal.css') + '">'
        '</head><body>' + _setup_header() +
        '<main class="setup-main">' + _setup_progress(1) +
        '<div class="page-head"><div><span class="eyebrow">First boot</span>'
        '<h1>Set up HAMD</h1><p class="lead">Secure this device and connect it to the home network.</p>'
        '</div></div>'
        '<p>Credentials are stored in encrypted NVS. Login passwords are stored only as salted verifiers.</p>' +
        notice + '<form id="setup-form" action="/configure" method="post" autocomplete="off">'
        '<input type="hidden" name="csrf" value="' + _escape(csrf) + '">'
        '<section class="card"><div class="section-title"><h2>Device &amp; Application</h2>' +
        application_status + '</div><div class="grid">'
        '<label class="field">Device name<input id="device-name" name="device_name" required maxlength="64"></label>'
        + application_control +
        '<label class="field">Current UTC time<input id="browser-time" name="browser_time" required maxlength="32" '
        'placeholder="2026-07-23T05:30:00Z"></label>'
        '</div></section><section class="card"><div class="section-title"><h2>Wi-Fi</h2>'
        '<button id="wifi-rescan" class="secondary compact" type="button">Scan again</button></div><div class="grid">'
        '<label class="field">Available network<select id="wifi-network-select" required>'
        '<option value="">Select a Wi-Fi network</option>'
        '<option value="__manual__">Enter network name manually…</option></select></label>'
        '<label id="wifi-manual-field" class="field" hidden>Network name (SSID)'
        '<input id="wifi-ssid-input" name="wifi_ssid" maxlength="32"></label>'
        '<label class="field">Network password<input name="wifi_password" type="password" maxlength="64" '
        'autocomplete="new-password"></label>'
        '<label class="field">Portal mDNS hostname<input id="mdns-hostname" name="certificate_hostname" required maxlength="253" '
        'placeholder="whes01.local" pattern="[A-Za-z0-9-]+\\.local"></label></div>'
        '<p id="wifi-scan-status" class="muted">Scanning for nearby networks…</p>'
        '<label class="check"><input id="wifi-dhcp" name="wifi_dhcp" type="checkbox" '
        'value="true" checked>Use DHCP to obtain network settings automatically</label>'
        '<div id="wifi-static-settings" class="grid" hidden>'
        '<label class="field">IP address<input name="wifi_ip_address" inputmode="decimal" maxlength="15" '
        'placeholder="192.168.1.50"></label>'
        '<label class="field">Subnet mask<input name="wifi_subnet_mask" inputmode="decimal" maxlength="15" '
        'placeholder="255.255.255.0"></label>'
        '<label class="field">Default gateway<input name="wifi_gateway" inputmode="decimal" maxlength="15" '
        'placeholder="192.168.1.1"></label>'
        '<label class="field">DNS server<input name="wifi_dns_server" inputmode="decimal" maxlength="15" '
        'placeholder="192.168.1.1"></label></div>'
        '<p class="muted">After Wi-Fi connects, this setup network will close and setup will continue '
        'on the home network using this .local address.</p></section>'
        '<section class="card"><div class="section-title"><h2>Administration</h2></div><div class="grid">'
        '<label class="field">Portal username<input name="portal_username" value="admin" required maxlength="32"></label>'
        '<label class="field">Portal transport<select name="portal_transport">'
        '<option value="auto" selected>Automatic (HTTPS with certificate)</option>'
        '<option value="https">Always HTTPS</option>'
        '<option value="http">HTTP (unencrypted)</option></select></label></div>'
        '<div class="credential-group"><h3>Portal sign-in password</h3>'
        '<p class="muted">Used with the portal username above.</p><div class="credential-pair">'
        '<label class="field">Portal password<input name="portal_password" type="password" minlength="16" '
        'maxlength="256" required autocomplete="new-password"></label>'
        '<label class="field">Confirm portal password<input name="portal_password_confirm" type="password" '
        'minlength="16" maxlength="256" required autocomplete="new-password"></label></div></div>'
        '<p class="muted">Use at least 16 characters with three character types, or a varied '
        'passphrase of at least 20 characters. Automatic transport uses HTTPS whenever a portal '
        'certificate is installed.</p></section>'
        '<section class="card"><div class="section-title"><h2>Emergency recovery</h2></div>'
        '<div class="credential-group"><h3>Recovery Wi-Fi access</h3>'
        '<p class="muted">Used only to join the protected HAMD-Recovery access point.</p>'
        '<div class="credential-pair">'
        '<label class="field">Recovery AP password<input name="recovery_ap_password" type="password" '
        'minlength="16" maxlength="63" required autocomplete="new-password"></label>'
        '<label class="field">Confirm recovery AP password<input name="recovery_ap_password_confirm" type="password" '
        'minlength="16" maxlength="63" required autocomplete="new-password"></label></div></div>'
        '<div class="credential-group"><h3>Recovery console sign-in</h3>'
        '<p class="muted">Used after joining the recovery access point.</p>'
        '<div class="credential-pair">'
        '<label class="field">Recovery console password<input name="recovery_password" type="password" '
        'minlength="16" maxlength="256" required autocomplete="new-password"></label>'
        '<label class="field">Confirm recovery console password<input name="recovery_password_confirm" type="password" '
        'minlength="16" maxlength="256" required autocomplete="new-password"></label></div></div>'
        '<p class="muted">These must be strong and different from each other and from the portal password.</p>'
        '</section><button type="submit">Save and continue</button></form>'
        '<script>document.getElementById("browser-time").value=new Date().toISOString();'
        'var deviceName=document.getElementById("device-name"),mdns=document.getElementById('
        '"mdns-hostname"),mdnsEdited=false;function hostnameFromDevice(){var label=deviceName.value'
        '.toLowerCase().trim().replace(/[^a-z0-9]+/g,"-").replace(/^-+|-+$/g,"").slice(0,63);'
        'if(!mdnsEdited)mdns.value=label?label+".local":"";}mdns.addEventListener("input",'
        'function(){mdnsEdited=true;});deviceName.addEventListener("input",hostnameFromDevice);'
        'var wifiSelect=document.getElementById("wifi-network-select"),wifiInput=document.getElementById('
        '"wifi-ssid-input"),wifiManual=document.getElementById("wifi-manual-field"),wifiStatus='
        'document.getElementById("wifi-scan-status"),wifiRescan=document.getElementById("wifi-rescan");'
        'function syncWifiSelection(){var manual=wifiSelect.value==="__manual__";wifiManual.hidden=!manual;'
        'wifiInput.required=manual;if(!manual&&wifiSelect.value)wifiInput.value=wifiSelect.value;}'
        'function wifiOption(value,text){var option=document.createElement("option");option.value=value;'
        'option.textContent=text;return option;}function scanWifi(){var current=wifiInput.value;wifiRescan.disabled=true;'
        'wifiStatus.textContent="Scanning for nearby networks…";fetch("/wifi-networks",{cache:"no-store",'
        'credentials:"same-origin"}).then(function(response){if(!response.ok)throw new Error("HTTP "+response.status);'
        'return response.json();}).then(function(networks){wifiSelect.textContent="";wifiSelect.appendChild('
        'wifiOption("","Select a Wi-Fi network"));var found=false;for(var i=0;i<networks.length;i++){var network='
        'networks[i],label=network.ssid+(typeof network.rssi==="number"?" ("+network.rssi+" dBm)":"");'
        'wifiSelect.appendChild(wifiOption(network.ssid,label));if(network.ssid===current)found=true;}'
        'wifiSelect.appendChild(wifiOption("__manual__","Enter network name manually…"));if(current){wifiSelect.value='
        'found?current:"__manual__";}else wifiSelect.value="";syncWifiSelection();wifiStatus.textContent=networks.length?'
        'networks.length+" network"+(networks.length===1?"":"s")+" found.":"No visible networks found; use manual entry.";'
        'if(!networks.length){wifiSelect.value="__manual__";syncWifiSelection();}}).catch(function(){wifiSelect.value='
        '"__manual__";syncWifiSelection();wifiStatus.textContent="Network scan unavailable; enter the SSID manually.";'
        '}).finally(function(){wifiRescan.disabled=false;});}wifiSelect.onchange=syncWifiSelection;wifiRescan.onclick=scanWifi;'
        'syncWifiSelection();scanWifi();'
        'var dhcp=document.getElementById("wifi-dhcp"),staticBox=document.getElementById('
        '"wifi-static-settings");function syncNetworkMode(){var manual=!dhcp.checked;'
        'staticBox.hidden=!manual;var fields=staticBox.querySelectorAll("input");for(var i=0;'
        'i<fields.length;i++)fields[i].required=manual;}dhcp.onchange=syncNetworkMode;syncNetworkMode();'
        'document.getElementById("setup-form").addEventListener("submit",function(){'
        'document.getElementById("browser-time").value=new Date().toISOString();});</script>'
        '<script src="' + _asset('/assets/portal.js') + '"></script></main></body></html>'
    )


def _upload_page(csrf, message=''):
    notice = '<p class="notice">' + _escape(message) + '</p>' if message else ''
    body = (
        '<!doctype html><html><head><meta name="viewport" content="width=device-width,initial-scale=1">'
        '<title>Install application</title><link rel="stylesheet" href="' +
        _asset('/assets/portal.css') + '"></head>'
        '<body>' + _setup_header() + '<main class="setup-main">' + _setup_progress(4) +
        portal_ui.page_heading(
            'Signed application', 'Install application',
            'Select the signed application bundle. Unsigned or incompatible bundles are rejected.'
        ) + notice + '<section class="card"><label class="field">Application bundle'
        '<input id="bundle" type="file" accept=".hamd"></label>'
        '<div class="actions"><span id="result" class="muted"></span>'
        '<button id="install">Upload and verify</button></div>' +
        portal_ui.progress('setup-upload-progress', 'Waiting…', True) +
        '</section></main><script src="' + _asset('/assets/portal.js') + '"></script><script>'
        'document.getElementById("install").onclick=function(){var f=document.getElementById("bundle").files[0],'
        'box=document.getElementById("setup-upload-progress"),label=box.querySelector(".status-text"),'
        'result=document.getElementById("result");if(!f)return;box.classList.remove("complete","failed");'
        'box.hidden=false;label.textContent="Uploading 0%";this.disabled=true;'
        'var x=new XMLHttpRequest();x.open("POST","/upload",true);x.setRequestHeader("Content-Type",'
        '"application/octet-stream");x.setRequestHeader("X-CSRF-Token","' + _escape(csrf) + '");'
        'var finished=false,polling=false;function poll(){if(finished)return;fetch("/upload-progress",'
        '{cache:"no-store",credentials:"same-origin"}).then(function(r){return r.json();}).then(function(s){'
        'if(s.phase==="verification")label.textContent="Verifying "+(s.percent||0)+"%";setTimeout(poll,500);}'
        ').catch(function(){setTimeout(poll,900);});}'
        'x.upload.onprogress=function(e){if(!e.lengthComputable)return;var p=Math.round(e.loaded*100/e.total);'
        'label.textContent="Uploading "+p+"%";};x.upload.onload=function(){'
        'label.textContent="Verifying 0%";result.textContent="Completed: upload";'
        'if(!polling){polling=true;poll();}};'
        'x.onload=function(){result.textContent=x.responseText;if(x.status>=200&&x.status<300){'
        'finished=true;box.classList.add("complete");label.textContent="Verified 100%";var target=x.getResponseHeader("X-Portal-URL");if(target){setTimeout(function '
        'retry(){fetch(target,{mode:"no-cors",cache:"no-store"}).then(function(){location.replace(target);})'
        '.catch(function(){setTimeout(retry,2000);});},2500);}}else{finished=true;box.classList.add("failed");label.textContent="Failed";'
        'document.getElementById("install").disabled=false;}};x.onerror=function(){box.classList.add("failed");label.textContent='
        '"Connection lost";finished=true;result.textContent="Upload failed";document.getElementById("install").disabled=false;};'
        'x.send(f);};</script></body></html>'
    )
    return body


def _certificate_page(csrf, hostname='', message='', ready=False):
    self_signed_ready = ready and message == SELF_SIGNED_READY_MESSAGE
    notice = (
        '<p class="notice" role="status">' + _escape(message) + '</p>'
        if message and not self_signed_ready else ''
    )
    heading_badge = (
        '<span class="badge good tooltip-badge" tabindex="0" aria-label="' +
        _escape(message) + '" title="' + _escape(message) + '" data-tooltip="' +
        _escape(message) + '">Self-signed ready</span>'
        if self_signed_ready else ''
    )
    disabled = '' if ready else ' disabled'
    introduction = (
        '<p>A device-generated self-signed certificate is installed for HTTPS. You can '
        'continue with it, replace it automatically through ACME, or manually upload an existing '
        'portal certificate. All certificate material is written only to the flash-encrypted '
        'device filesystem.</p>'
        if ready else
        '<p>Complete automatic ACME enrollment or manually upload an existing portal certificate. '
        'All certificate material is written only to the flash-encrypted device filesystem.</p>'
    )
    return (
        '<!doctype html><html><head><meta name="viewport" content="width=device-width,initial-scale=1">'
        '<title>Device certificates</title><link rel="stylesheet" href="' +
        _asset('/assets/portal.css') + '"></head><body>' +
        _setup_header() + '<main class="setup-main">' + _setup_progress(3) +
        portal_ui.page_heading(
            'Certificate security', 'Install device certificates',
            'Keep the generated HTTPS certificate or replace it using ACME or manual DER files.',
            heading_badge
        ) + notice + introduction +
        '<form class="card" action="/enroll-certificate" method="post" enctype="multipart/form-data">'
        '<div class="section-title"><h2>Automatic enrollment</h2></div>'
        '<input type="hidden" name="csrf" value="' + _escape(csrf) + '">'
        '<p>The device is connected to the home Wi-Fi and is advertising its '
        '<code>.local</code> hostname with mDNS. It will answer the CA HTTP-01 request on port 80. '
        'The CA must be on the same multicast network and able to resolve mDNS.</p>'
        '<label class="field">Home IoT trusted CA certificate<input id="trust-ca" name="trust_ca" '
        'type="file" accept=".der,application/pkix-cert" required></label>'
        '<label class="field">ACME directory URL<input id="acme-directory" name="directory_url" type="url" required '
        'placeholder="https://iot-ca.home.arpa:9000/acme/acme/directory"></label>'
        '<label class="field">Portal DNS hostname<input id="certificate-hostname" name="hostname" '
        'value="' + _escape(hostname) + '" readonly></label>'
        '<button id="enroll" type="submit">Upload root and enroll with ACME</button></form>'
        '<form class="card" action="/manual-certificates" method="post" enctype="multipart/form-data">'
        '<div class="section-title"><h2>Manual fallback</h2></div>'
        '<input type="hidden" name="csrf" value="' + _escape(csrf) + '">'
        '<label class="field">Home IoT trusted CA certificate<input name="trust_ca" type="file" required></label>'
        '<label class="field">Portal certificate<input id="portal-cert" name="portal_cert" type="file" required></label>'
        '<label class="field">Portal private key<input id="portal-key" name="portal_key" type="file" required></label>'
        '<button id="upload" type="submit">Upload and validate certificates</button></form>'
        '<form class="page-load-action" action="/install" method="post">'
        '<input type="hidden" name="csrf" value="' +
        _escape(csrf) + '"><input type="hidden" name="certificate_mode" value="self_signed">'
        '<button id="continue" class="secondary"' + disabled +
        '>Continue with self-signed certificate</button></form></main>'
        '<script src="' + _asset('/assets/portal.js') + '"></script></body></html>'
    )


def _enrollment_page(message):
    return (
        '<!doctype html><html><head><meta name="viewport" content="width=device-width,initial-scale=1">'
        '<meta http-equiv="refresh" content="2;url=/enrollment-status">'
        '<title>Enrolling certificate</title><link rel="stylesheet" href="' +
        _asset('/assets/portal.css') + '">'
        '</head><body>' + _setup_header() + '<main class="setup-main">' + _setup_progress(3) +
        portal_ui.page_heading(
            'Certificate security', 'Enrolling certificate',
            'The device is completing ACME enrollment.'
        ) + '<section class="card">' + portal_ui.progress(
            'enrollment-progress', message
        ) + '<p class="muted">Status updates automatically.</p>'
        '<div class="page-load-action"><a class="button secondary" href="/enrollment-status">'
        'Check status now</a></div></section></main>'
        '<script src="' + _asset('/assets/portal.js') + '"></script></body></html>'
    )


def _certificate_complete_page(csrf, message, certificate_mode):
    return (
        '<!doctype html><html><head><meta name="viewport" content="width=device-width,initial-scale=1">'
        '<title>Certificate installed</title><link rel="stylesheet" href="' +
        _asset('/assets/portal.css') + '">'
        '</head><body>' + _setup_header() + '<main class="setup-main">' + _setup_progress(3) +
        portal_ui.page_heading(
            'Certificate security', 'Certificate installed',
            'Certificate validation succeeded.'
        ) +
        '<p class="notice" role="status">' + _escape(message) + '</p>'
        '<p>Completing device setup and checking the factory-installed application.</p>' +
        portal_ui.progress('setup-complete-progress', 'Preparing application…') +
        '<form class="page-load-action" id="next-step" action="/install" method="post">'
        '<input type="hidden" name="csrf" value="' + _escape(csrf) + '">'
        '<input type="hidden" name="certificate_mode" value="' +
        _escape(certificate_mode) + '">'
        '<button type="submit">Complete device setup</button></form>'
        '</main><script src="' + _asset('/assets/portal.js') + '"></script>'
        '<script>document.getElementById("next-step").submit();</script></body></html>'
    )


def _certificate_resume_page(csrf, config):
    """Resume an interrupted setup from the certificate mode persisted in NVS."""
    certificate = config.get('certificate', {})
    hostname = certificate.get('hostname', '')
    mode = certificate.get('mode', 'self_signed')
    if mode in ('acme', 'manual'):
        try:
            _validate_certificate_selection(config, mode)
        except Exception as exc:
            return _certificate_page(
                csrf, hostname, 'Installed certificate validation failed: ' + str(exc), False
            )
        label = 'ACME' if mode == 'acme' else 'Manually supplied'
        return _certificate_complete_page(
            csrf, label + ' certificate files are installed and validated.', mode
        )
    return _certificate_page(
        csrf, hostname,
        SELF_SIGNED_READY_MESSAGE,
        True
    )


def _handover_page(hostname, session):
    destination = 'http://' + str(hostname) + '/resume/' + str(session)
    escaped = _escape(destination)
    return (
        '<!doctype html><html><head><meta name="viewport" content="width=device-width,initial-scale=1">'
        '<meta name="referrer" content="no-referrer"><title>Joining home Wi-Fi</title>'
        '<link rel="stylesheet" href="' + _asset('/assets/portal.css') + '"></head><body>' + _setup_header() +
        '<main class="setup-main">' + _setup_progress(2) + portal_ui.page_heading(
            'Network handover', 'Home Wi-Fi connected',
            'Reconnect this browser to the home network to continue setup.'
        ) +
        '<p>The device setup access point will now close. Reconnect this browser to the home Wi-Fi, '
        'then continue at <strong>' + _escape(hostname) + '</strong>.</p>' +
        portal_ui.progress('handover-progress', 'Waiting for home Wi-Fi…') +
        '<p>If the browser does not reconnect automatically, join the home Wi-Fi and continue manually.</p>'
        '<div class="page-load-action"><a class="button secondary" href="' + escaped + '">'
        'Continue setup on home Wi-Fi</a></div>'
        '<script>var target="' + escaped + '";async function resume(){try{'
        'await fetch(target,{mode:"no-cors",cache:"no-store"});window.location.href=target;'
        '}catch(e){setTimeout(resume,2000);}}setTimeout(resume,3000);</script>'
        '</main></body></html>'
    )


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


def _portal_url(config):
    transport = config.get('portal', {}).get('transport', 'auto')
    certificates_installed = (
        _file_exists(CERTIFICATE_PATHS['portal-cert']) and
        _file_exists(CERTIFICATE_PATHS['portal-key'])
    )
    https = transport == 'https' or (transport == 'auto' and certificates_installed)
    scheme = 'https' if https else 'http'
    port = config.get('portal', {}).get('port')
    if port is None:
        port = HTTPS_PORT if https else HTTP_PORT
    hostname = config.get('certificate', {}).get('hostname', '')
    if not hostname:
        raise ValueError('portal hostname is unavailable')
    return scheme + '://' + hostname + ':' + str(port) + '/'


def _portal_handoff_page(config, message):
    destination = _portal_url(config)
    return (
        '<!doctype html><html><head><meta name="viewport" content="width=device-width,initial-scale=1">'
        '<meta name="referrer" content="no-referrer"><title>Opening HAMD</title>'
        '<link rel="stylesheet" href="' + _asset('/assets/portal.css') + '"></head><body>' + _setup_header() +
        '<main class="setup-main">' + _setup_progress(4) + portal_ui.page_heading(
            'First boot', 'Device setup complete',
            'The permanent portal will open as soon as the device has restarted.'
        ) +
        '<p class="notice" role="status">' + _escape(message) + '</p>'
        '<p>The device is restarting into its permanent portal. This page will open the login screen '
        'as soon as it is ready.</p>' + portal_ui.progress(
            'portal-progress', 'Waiting for portal…'
        ) + '<div class="page-load-action"><a id="portal-link" class="button secondary" href="' +
        _escape(destination) + 'login">Open the login page</a></div>'
        '<script>var target=document.getElementById("portal-link").href;'
        'var attempts=0;async function openPortal(){try{await fetch(target,{mode:"no-cors",cache:"no-store"});'
        'window.location.replace(target);}catch(e){attempts++;if(attempts>=6){'
        'window.location.replace(target);}else{setTimeout(openPortal,2000);}}}'
        'setTimeout(openPortal,3000);</script></main></body></html>'
    )


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


async def serve(ap_name, ap_password, reset_device, port=SETUP_PORT):
    """Serve first-boot setup until a signed application is ready."""
    if network is None:
        raise RuntimeError('first-boot Wi-Fi setup is unavailable')
    wlan_class = network.WLAN
    station_interface = getattr(wlan_class, 'IF_STA', getattr(network, 'STA_IF', 0))
    station = wlan_class(station_interface)
    try:
        station.disconnect()
    except Exception:
        pass
    station.active(False)
    access_point = wifi_recovery._activate_access_point(ap_name, ap_password)
    wifi_recovery.schedule_wifi_scan()
    session = wifi_recovery._session_id()
    enrollment = {'status': 'idle', 'message': '', 'mode': ''}
    upload_progress = {'phase': 'idle', 'percent': 0}
    enrollment_task = None

    async def send(writer, status, body, content_type='text/html; charset=utf-8', headers=()):
        payload = body.encode() if isinstance(body, str) else body
        cache_control = (
            () if any(name.lower() == 'cache-control' for name, _value in headers)
            else (('Cache-Control', 'no-store'),)
        )
        response_headers = http_support.add_security_headers((
            ('Content-Type', content_type), ('Content-Length', str(len(payload))),
        ) + cache_control + (
            ('Connection', 'close'),
        ) + tuple(headers))
        writer.write(('HTTP/1.1 ' + status + '\r\n' + ''.join(
            name + ': ' + value + '\r\n' for name, value in response_headers
        ) + '\r\n').encode() + payload)
        await writer.drain()

    async def enroll_certificate(directory_url, hostname, config):
        def progress(message):
            enrollment['message'] = str(message)

        staged_trust_ca = CERTIFICATE_PATHS['trust-ca'] + '.acme'
        try:
            progress('Connecting to the home Wi-Fi')
            await _connect_station(
                config['wifi']['ssid'], config['wifi']['password'], hostname=hostname,
                wifi=config['wifi']
            )
            state = await certificate_manager.issue(
                directory_url, hostname, staged_trust_ca,
                shared_port_80=True, progress=progress
            )
            certificate_manager.commit_certificate_files((
                (staged_trust_ca, CERTIFICATE_PATHS['trust-ca']),
            ), validator=lambda: _validate_certificate_files('acme'))
            saved = credential_store.update_certificate_settings(
                'acme', directory_url, hostname
            )
            if saved.get('mode') != 'acme' or saved.get('directory_url') != directory_url:
                raise RuntimeError('ACME certificate settings were not preserved')
        except Exception as exc:
            try:
                os.remove(staged_trust_ca)
            except OSError:
                pass
            enrollment['status'] = 'error'
            enrollment['message'] = 'Setup failed: ' + str(exc)
        else:
            enrollment['status'] = 'complete'
            enrollment['mode'] = 'acme'
            enrollment['message'] = (
                'Certificate enrolled until ' + str(state.get('not_after', ''))
            )

    async def handle(reader, writer):
        nonlocal enrollment_task
        reboot = False
        handover_config = None
        try:
            request_line, headers = await http_support.read_request(reader)
            request_line = request_line.decode().strip()
            method, path = _parse_request_line(request_line)
            authenticated = wifi_recovery._cookies(headers).get('ham_setup') == session
            challenge_response = certificate_manager.http01_response(path)
            if method == 'GET' and path == '/assets/portal.css':
                await send(
                    writer, '200 OK', portal_ui.PORTAL_CSS,
                    'text/css; charset=utf-8'
                )
            elif method == 'GET' and path == '/assets/portal.js':
                await send(
                    writer, '200 OK', portal_ui.PORTAL_JS,
                    'application/javascript; charset=utf-8'
                )
            elif method == 'GET' and challenge_response is not None:
                await send(writer, '200 OK', challenge_response, 'text/plain')
            elif method == 'GET' and path == '/':
                await send(writer, '200 OK', _page(session), headers=(
                    ('Set-Cookie', 'ham_setup=' + session + '; Path=/; HttpOnly; SameSite=Strict'),
                ))
            elif method == 'GET' and path == '/resume/' + session:
                config = credential_store.load()
                await send(writer, '200 OK', _certificate_resume_page(
                    session, config
                ), headers=(
                    ('Set-Cookie', 'ham_setup=' + session + '; Path=/; HttpOnly; SameSite=Strict'),
                ))
            elif not authenticated:
                await send(writer, '401 Unauthorized', 'Reconnect to the setup page.', 'text/plain')
            elif method == 'GET' and path == '/wifi-networks':
                await send(
                    writer, '200 OK', json.dumps(wifi_recovery.cached_wifi_networks()),
                    'application/json'
                )
            elif method == 'GET' and path == '/upload-progress':
                await send(
                    writer, '200 OK', json.dumps(upload_progress),
                    'application/json'
                )
            elif method == 'GET' and path == '/upload':
                config = credential_store.load()
                await send(writer, '200 OK', _upload_page(session))
            elif method == 'POST' and path == '/configure':
                length = int(headers.get('content-length', '0') or 0)
                if length <= 0 or length > MAX_FORM_BYTES:
                    raise ValueError('setup form size is invalid')
                body = await _read_body(reader, length, MAX_FORM_BYTES)
                params = wifi_recovery._form(body.decode())
                if params.get('csrf') != session:
                    await send(writer, '403 Forbidden', 'Invalid CSRF token', 'text/plain')
                    return
                _set_rtc_from_browser_time(params.get('browser_time', ''))
                values = _form_values(params)
                config = credential_store.build_configuration(
                    values, params.get('portal_password', ''),
                    params.get('recovery_password', '')
                )
                credential_store.save(config)
                hostname = config['certificate']['hostname']
                certificate_manager.install_self_signed(hostname)
                await send(writer, '200 OK', _handover_page(hostname, session))
                handover_config = config
            elif method == 'GET' and path == '/certificates':
                config = credential_store.load()
                await send(
                    writer, '200 OK',
                    _certificate_resume_page(session, config)
                )
            elif method == 'GET' and path == '/enrollment-status':
                config = credential_store.load()
                if enrollment['status'] == 'running':
                    await send(writer, '200 OK', _enrollment_page(enrollment['message']))
                elif enrollment['status'] == 'complete':
                    await send(writer, '200 OK', _certificate_complete_page(
                        session, enrollment['message'], enrollment['mode']
                    ))
                elif enrollment['status'] == 'error':
                    await send(writer, '400 Bad Request', _certificate_page(
                        session, config['certificate']['hostname'], enrollment['message'],
                        config['certificate']['mode'] == 'self_signed'
                    ))
                else:
                    await send(writer, '200 OK', _certificate_resume_page(session, config))
            elif method == 'POST' and path == '/certificate':
                if headers.get('x-csrf-token', '') != session:
                    await send(writer, '403 Forbidden', 'Invalid CSRF token', 'text/plain')
                    return
                length = int(headers.get('content-length', '0') or 0)
                payload = await _read_body(reader, length, MAX_CERTIFICATE_BYTES)
                _write_certificate(headers.get('x-certificate-kind', ''), payload)
                await send(writer, '200 OK', 'Stored and encrypted at rest', 'text/plain')
            elif method == 'POST' and path == '/enroll-certificate':
                if enrollment['status'] == 'running':
                    await send(writer, '202 Accepted', _enrollment_page(enrollment['message']))
                    return
                length = int(headers.get('content-length', '0') or 0)
                body = await asyncio.wait_for(
                    _read_body(reader, length, MAX_CERTIFICATE_FORM_BYTES), 20
                )
                parts = _multipart_form(body, headers.get('content-type', ''))
                if parts.get('csrf', b'').decode() != session:
                    await send(writer, '403 Forbidden', 'Invalid CSRF token', 'text/plain')
                    return
                directory_url = parts.get('directory_url', b'').decode().strip()
                hostname = parts.get('hostname', b'').decode().strip()
                config = credential_store.load()
                if hostname != config['certificate']['hostname']:
                    raise ValueError('portal mDNS hostname changed during setup')
                _write_certificate('trust-ca', parts.get('trust_ca', b''), '.acme')
                enrollment['status'] = 'running'
                enrollment['message'] = 'Starting ACME enrollment'
                enrollment['mode'] = 'acme'
                await send(writer, '202 Accepted', _enrollment_page(enrollment['message']))
                enrollment_task = asyncio.create_task(
                    enroll_certificate(directory_url, hostname, config)
                )
            elif method == 'POST' and path == '/manual-certificates':
                length = int(headers.get('content-length', '0') or 0)
                body = await _read_body(reader, length, MAX_CERTIFICATE_FORM_BYTES)
                parts = _multipart_form(body, headers.get('content-type', ''))
                if parts.get('csrf', b'').decode() != session:
                    await send(writer, '403 Forbidden', 'Invalid CSRF token', 'text/plain')
                    return
                config = credential_store.load()
                staged_paths = [
                    CERTIFICATE_PATHS['trust-ca'] + '.manual',
                    CERTIFICATE_PATHS['portal-cert'] + '.manual',
                    CERTIFICATE_PATHS['portal-key'] + '.manual',
                ]
                try:
                    _write_certificate('trust-ca', parts.get('trust_ca', b''), '.manual')
                    _write_certificate('portal-cert', parts.get('portal_cert', b''), '.manual')
                    _write_certificate('portal-key', parts.get('portal_key', b''), '.manual')
                    _validate_certificates(
                        True, staged_paths[1], staged_paths[2], staged_paths[0]
                    )
                except Exception:
                    for staged_path in staged_paths:
                        try:
                            os.remove(staged_path)
                        except OSError:
                            pass
                    raise
                certificate_manager.commit_certificate_files(
                    zip(staged_paths, (
                        CERTIFICATE_PATHS['trust-ca'],
                        CERTIFICATE_PATHS['portal-cert'],
                        CERTIFICATE_PATHS['portal-key'],
                    )),
                    validator=lambda: _validate_certificate_files('manual')
                )
                hostname = config['certificate']['hostname']
                credential_store.update_certificate_settings('manual', '', hostname)
                await send(writer, '200 OK', _certificate_complete_page(
                    session, 'Certificates validated.', 'manual'
                ))
            elif method == 'POST' and path == '/install':
                length = int(headers.get('content-length', '0') or 0)
                body = await _read_body(reader, length, MAX_FORM_BYTES)
                params = wifi_recovery._form(body.decode())
                if params.get('csrf') != session:
                    await send(writer, '403 Forbidden', 'Invalid CSRF token', 'text/plain')
                    return
                config = credential_store.load()
                _prepare_certificate_selection(config, params.get('certificate_mode', ''))
                state = _prepare_available_application()
                if state is None and config['release']['install_mode'] == 'download':
                    state = await _download_application(config)
                if state is None:
                    await send(writer, '303 See Other', 'Upload required', 'text/plain', (
                        ('Location', '/upload'),
                    ))
                else:
                    credential_store.mark_provisioned(config)
                    credential_store.erase_bootstrap_key()
                    await send(
                        writer, '200 OK',
                        _portal_handoff_page(
                            config,
                            'Verified signed application ' +
                            str(state.get('version', '') or 'factory image') + '. Restarting.'
                        )
                    )
                    reboot = True
            elif method == 'POST' and path == '/upload':
                if headers.get('x-csrf-token', '') != session:
                    await send(writer, '403 Forbidden', 'Invalid CSRF token', 'text/plain')
                    return
                config = credential_store.load()
                _validate_certificate_files(config['certificate']['mode'])
                length = int(headers.get('content-length', '0') or 0)

                async def report_upload_progress(phase, completed=0, total=0):
                    total = int(total or 0)
                    upload_progress['phase'] = str(phase)
                    upload_progress['percent'] = (
                        max(0, min(100, int(int(completed or 0) * 100 / total)))
                        if total else 0
                    )

                state = await app_update.receive_bundle(
                    reader, length, False, app_update.DEFAULT_MAX_BUNDLE_BYTES,
                    progress_callback=report_upload_progress
                )
                upload_progress.update({'phase': 'complete', 'percent': 100})
                state = _prepare_setup_application(state)
                credential_store.mark_provisioned(config)
                credential_store.erase_bootstrap_key()
                portal_url = _portal_url(config)
                await send(
                    writer, '200 OK',
                    'Verified ' + str(state.get('version', '')) + '. Rebooting.',
                    'text/plain', (('X-Portal-URL', portal_url),)
                )
                reboot = True
            else:
                await send(writer, '404 Not Found', 'Not found', 'text/plain')
        except Exception as exc:
            try:
                await send(writer, '400 Bad Request', 'Setup failed: ' + str(exc), 'text/plain')
            except Exception:
                pass
        finally:
            try:
                writer.close()
            except Exception:
                pass
        if reboot:
            await asyncio.sleep(1)
            reset_device()
        elif handover_config is not None:
            await asyncio.sleep(2)
            access_point.active(False)
            try:
                await _connect_station(
                    handover_config['wifi']['ssid'],
                    handover_config['wifi']['password'],
                    hostname=handover_config['certificate']['hostname'],
                    wifi=handover_config['wifi']
                )
            except Exception:
                # Restore the setup network so bad Wi-Fi credentials can be
                # corrected without USB recovery.
                access_point.active(True)

    server = await asyncio.start_server(handle, '0.0.0.0', int(port), backlog=2)
    while True:
        await asyncio.sleep(60)
    return {'server': server, 'access_point': access_point}

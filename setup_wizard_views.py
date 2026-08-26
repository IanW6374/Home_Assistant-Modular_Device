"""Pure first-boot wizard page rendering."""

try:
    import ujson as json
except ImportError:
    import json
import app_update
import factory_config
import portal_ui
from setup_workflow import (
    CERTIFICATE_PATHS, _file_exists, _preloaded_application_available,
    _validate_certificate_selection,
)

HTTPS_PORT = 8443
HTTP_PORT = 8080
SETUP_ASSET_VERSION = '8'
SELF_SIGNED_READY_MESSAGE = (
    'Self-signed HTTPS is ready. Choose ACME, manual certificates, or the explicit fallback.'
)

def _asset(path):
    return str(path) + '?v=' + SETUP_ASSET_VERSION

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
        'content="width=device-width,initial-scale=1"><title>IoTMD setup</title>'
        '<link rel="stylesheet" href="' + _asset('/assets/portal.css') + '">'
        '</head><body>' + _setup_header() +
        '<main class="setup-main">' + _setup_progress(1) +
        '<div class="page-head"><div><span class="eyebrow">First boot</span>'
        '<h1>Set up IoTMD</h1><p class="lead">Secure this device and connect it to the home network.</p>'
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
        '<p id="wifi-scan-status" class="portal-status" role="status" aria-live="polite">'
        'Scanning for nearby networks…</p>'
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
        '<p class="muted">Used only to join the protected IoTMD-Recovery access point.</p>'
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
        'function setWifiStatus(state,text){wifiStatus.className="portal-status"+(state?" "+state:"");'
        'wifiStatus.textContent=text;}'
        'function syncWifiSelection(){var manual=wifiSelect.value==="__manual__";wifiManual.hidden=!manual;'
        'wifiInput.required=manual;if(!manual&&wifiSelect.value)wifiInput.value=wifiSelect.value;}'
        'function wifiOption(value,text){var option=document.createElement("option");option.value=value;'
        'option.textContent=text;return option;}function scanWifi(){var current=wifiInput.value;wifiRescan.disabled=true;'
        'setWifiStatus("","Scanning for nearby networks…");fetch("/wifi-networks",{cache:"no-store",'
        'credentials:"same-origin"}).then(function(response){if(!response.ok)throw new Error("HTTP "+response.status);'
        'return response.json();}).then(function(networks){wifiSelect.textContent="";wifiSelect.appendChild('
        'wifiOption("","Select a Wi-Fi network"));var found=false;for(var i=0;i<networks.length;i++){var network='
        'networks[i],label=network.ssid+(typeof network.rssi==="number"?" ("+network.rssi+" dBm)":"");'
        'wifiSelect.appendChild(wifiOption(network.ssid,label));if(network.ssid===current)found=true;}'
        'wifiSelect.appendChild(wifiOption("__manual__","Enter network name manually…"));if(current){wifiSelect.value='
        'found?current:"__manual__";}else wifiSelect.value="";syncWifiSelection();setWifiStatus('
        'networks.length?"success":"warning",networks.length?networks.length+" network"+'
        '(networks.length===1?"":"s")+" found.":"No visible networks found; use manual entry.");'
        'if(!networks.length){wifiSelect.value="__manual__";syncWifiSelection();}}).catch(function(){wifiSelect.value='
        '"__manual__";syncWifiSelection();setWifiStatus("warning",'
        '"Network scan unavailable; enter the SSID manually.");'
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
        '<input id="bundle" type="file" accept=".iotapp"></label>'
        '<div class="actions"><span id="result" class="portal-status" role="status" '
        'aria-live="polite"></span>'
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
        'result.className="portal-status success";'
        'finished=true;box.classList.add("complete");label.textContent="Verified 100%";var target=x.getResponseHeader("X-Portal-URL");if(target){setTimeout(function '
        'retry(){fetch(target,{mode:"no-cors",cache:"no-store"}).then(function(){location.replace(target);})'
        '.catch(function(){setTimeout(retry,2000);});},2500);}}else{result.className="portal-status error";'
        'finished=true;box.classList.add("failed");label.textContent="Failed";'
        'document.getElementById("install").disabled=false;}};x.onerror=function(){box.classList.add("failed");label.textContent='
        '"Connection lost";finished=true;result.className="portal-status error";result.textContent="Upload failed";'
        'document.getElementById("install").disabled=false;};'
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
        'continue with it, provision it from IoT CA, use direct ACME, or manually upload an existing '
        'portal certificate. All certificate material is written only to the flash-encrypted '
        'device filesystem.</p>'
        if ready else
        '<p>Complete IoT CA provisioning, direct ACME enrollment, or manually upload an existing portal certificate. '
        'All certificate material is written only to the flash-encrypted device filesystem.</p>'
    )
    return (
        '<!doctype html><html><head><meta name="viewport" content="width=device-width,initial-scale=1">'
        '<title>Device certificates</title><link rel="stylesheet" href="' +
        _asset('/assets/portal.css') + '"></head><body>' +
        _setup_header() + '<main class="setup-main">' + _setup_progress(3) +
        portal_ui.page_heading(
            'Certificate security', 'Install device certificates',
            'Keep the generated HTTPS certificate or replace it using IoT CA, ACME, or manual files.',
            heading_badge
        ) + notice + introduction +
        '<form class="card" action="/iot-ca-enrollment" method="post" enctype="multipart/form-data">'
        '<div class="section-title"><h2>IoT CA automatic provisioning</h2></div>'
        '<input type="hidden" name="csrf" value="' + _escape(csrf) + '">'
        '<p>Upload the short-lived host authorization downloaded from IoT CA. The device generates '
        'all private keys locally and sends only signed certificate requests. Cloudflare credentials '
        'remain on IoT CA.</p>'
        '<label class="field">IoT CA enrollment file (<code>.iotenroll</code>)'
        '<input id="iot-ca-enrollment" name="enrollment_file" type="file" '
        'accept=".iotenroll,application/vnd.iotmd.enrollment+json" required></label>'
        '<label class="field">Private Device API hostname<input value="' +
        _escape(hostname) + '" readonly></label>'
        '<button id="iot-ca-enroll" type="submit">Provision certificates from IoT CA</button></form>'
        '<form class="card" action="/enroll-certificate" method="post" enctype="multipart/form-data">'
        '<div class="section-title"><h2>Direct private-CA ACME enrollment</h2></div>'
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
        '<div class="section-title"><h2>Manual certificate package</h2></div>'
        '<input type="hidden" name="csrf" value="' + _escape(csrf) + '">'
        '<label class="field">Home IoT trusted CA certificate<input name="trust_ca" type="file" required></label>'
        '<label class="field">Public portal DNS hostname<input id="portal-public-hostname" name="portal_hostname" '
        'required maxlength="253" placeholder="device.example.com"></label>'
        '<label class="field">Public portal certificate chain (<code>web.crt.pem</code>)<input id="portal-cert" name="portal_cert" type="file" accept=".pem,application/x-pem-file" required></label>'
        '<label class="field">Public portal private key (<code>web.key.der</code>)<input id="portal-key" name="portal_key" type="file" required></label>'
        '<label class="field">Private Device API certificate (<code>api-server.crt.der</code>)<input id="api-server-cert" name="api_server_cert" type="file" required></label>'
        '<label class="field">Private Device API key (<code>api-server.key.der</code>)<input id="api-server-key" name="api_server_key" type="file" required></label>'
        '<p class="muted">These files are produced together by the IoT CA public-portal profile. The public portal and private API identities remain independent.</p>'
        '<button id="upload" type="submit">Upload and validate provisioning files</button></form>'
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
            'The device is completing certificate enrollment.'
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
    if mode in ('acme', 'manual', 'iot_ca'):
        try:
            _validate_certificate_selection(config, mode)
        except Exception as exc:
            return _certificate_page(
                csrf, hostname, 'Installed certificate validation failed: ' + str(exc), False
            )
        label = (
            'IoT CA provisioned' if mode == 'iot_ca' else
            ('ACME' if mode == 'acme' else 'Manually supplied')
        )
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
    certificate = config.get('certificate', {})
    hostname = certificate.get('portal_hostname') or certificate.get('hostname', '')
    if not hostname:
        raise ValueError('portal hostname is unavailable')
    return scheme + '://' + hostname + ':' + str(port) + '/'

def _portal_handoff_page(config, message):
    destination = _portal_url(config)
    return (
        '<!doctype html><html><head><meta name="viewport" content="width=device-width,initial-scale=1">'
        '<meta name="referrer" content="no-referrer"><title>Opening IoTMD</title>'
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

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
SETUP_ASSET_VERSION = '14'
SELF_SIGNED_READY_MESSAGE = (
    'A self-signed certificate is ready. Choose a certificate installation method.'
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

def _page(csrf, message='', invalid_fields=(), values=None):
    submitted = values is not None
    values = values or {}
    def field_value(name, default=''):
        return _escape(values.get(name, default))
    def selected(name, option, default=''):
        return ' selected' if str(values.get(name, default)) == option else ''
    dhcp_checked = (
        not submitted or
        str(values.get('wifi_dhcp', '')).lower() in ('1', 'true', 'on')
    )
    wifi_ssid = str(values.get('wifi_ssid', ''))
    invalid_fields = set(str(name) for name in (invalid_fields or ()))
    def invalid(name):
        return ' aria-invalid="true"' if name in invalid_fields else ''
    notice = (
        '<p id="setup-validation" class="portal-status error" role="alert" '
        'aria-live="assertive">' + _escape(message) + '</p>'
        if message else
        '<p id="setup-validation" class="portal-status" role="status" '
        'aria-live="polite"></p>'
    )
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
        default_install = 'download' if download_available else 'upload'
        install_options = (
            '<option value="download"' +
            selected('install_mode', 'download', default_install) +
            '>Download the latest signed application</option>'
            if download_available else ''
        ) + '<option value="upload"' + selected(
            'install_mode', 'upload', default_install
        ) + '>Upload a signed application bundle</option>'
        application_control = (
            '<label class="field">Application fallback<select name="install_mode">' +
            install_options + '</select></label>'
        )
        application_status = ''
    return (
        '<!doctype html><html><head><meta name="viewport" '
        'content="width=device-width,initial-scale=1"><title>IoT-MD setup</title>'
        '<link rel="stylesheet" href="' + _asset('/assets/portal.css') + '">'
        '</head><body>' + _setup_header() +
        '<main class="setup-main">' + _setup_progress(1) +
        '<div class="page-head"><div><span class="eyebrow">First boot</span>'
        '<h1>Set up IoT-MD</h1><p class="lead">Secure this device and connect it to the home network.</p>'
        '</div></div>'
        '<p>Credentials are stored in encrypted NVS. Login passwords are stored only as salted verifiers.</p>' +
        notice + '<form id="setup-form" action="/configure" method="post" autocomplete="off">'
        '<input type="hidden" name="csrf" value="' + _escape(csrf) + '">'
        '<section class="card"><div class="section-title"><h2>Device &amp; Application</h2>' +
        application_status + '</div><div class="grid">'
        '<label class="field">Device name<input id="device-name" name="device_name" required maxlength="64" value="' +
        field_value('device_name') + '"></label>'
        + application_control +
        '<label class="field">Current UTC time<input id="browser-time" name="browser_time" required maxlength="32" '
        'placeholder="2026-07-23T05:30:00Z"></label>'
        '</div></section><section class="card"><div class="section-title"><h2>Wi-Fi</h2>'
        '<button id="wifi-rescan" class="secondary compact" type="button">Scan again</button></div><div class="grid">'
        '<label class="field">Network name (SSID)<input id="wifi-ssid-input" name="wifi_ssid" '
        'list="wifi-network-options" required maxlength="32" value="' + _escape(wifi_ssid) + '" '
        'placeholder="Select or enter a network"><datalist id="wifi-network-options"></datalist></label>'
        '<label class="field">Network password<input name="wifi_password" type="password" maxlength="64" '
        'autocomplete="new-password"></label>'
        '<label class="field">Portal mDNS hostname<input id="mdns-hostname" name="certificate_hostname" required maxlength="253" '
        'placeholder="whes01.local" pattern="[A-Za-z0-9-]+\\.local" value="' +
        field_value('certificate_hostname') + '"></label></div>'
        '<p id="wifi-scan-status" class="portal-status" role="status" aria-live="polite">'
        'Scanning for nearby networks…</p>'
        '<label class="check"><input id="wifi-dhcp" name="wifi_dhcp" type="checkbox" '
        'value="true"' + (' checked' if dhcp_checked else '') +
        '>Use DHCP to obtain network settings automatically</label>'
        '<div id="wifi-static-settings" class="grid"' + (' hidden' if dhcp_checked else '') + '>'
        '<label class="field">IP address<input name="wifi_ip_address" inputmode="decimal" maxlength="15" '
        'placeholder="192.168.1.50" value="' + field_value('wifi_ip_address') + '"></label>'
        '<label class="field">Subnet mask<input name="wifi_subnet_mask" inputmode="decimal" maxlength="15" '
        'placeholder="255.255.255.0" value="' + field_value('wifi_subnet_mask') + '"></label>'
        '<label class="field">Default gateway<input name="wifi_gateway" inputmode="decimal" maxlength="15" '
        'placeholder="192.168.1.1" value="' + field_value('wifi_gateway') + '"></label>'
        '<label class="field">DNS server<input name="wifi_dns_server" inputmode="decimal" maxlength="15" '
        'placeholder="192.168.1.1" value="' + field_value('wifi_dns_server') + '"></label></div>'
        '<p class="muted">After Wi-Fi connects, this setup network will close and setup will continue '
        'on the home network using this .local address.</p></section>'
        '<section class="card"><div class="section-title"><h2>Administration</h2></div><div class="grid">'
        '<label class="field">Portal username<input name="portal_username" value="' +
        field_value('portal_username', 'admin') + '" required maxlength="32"></label>'
        '<label class="field">Portal transport<select name="portal_transport">'
        '<option value="auto"' + selected('portal_transport', 'auto', 'auto') +
        '>Automatic (HTTPS with certificate)</option>'
        '<option value="https"' + selected('portal_transport', 'https', 'auto') +
        '>Always HTTPS</option>'
        '<option value="http"' + selected('portal_transport', 'http', 'auto') +
        '>HTTP (unencrypted)</option></select></label></div>'
        '<div class="credential-group"><h3>Portal sign-in password</h3>'
        '<p class="muted">Used with the portal username above.</p><div class="credential-pair">'
        '<label class="field">Portal password<input id="portal-password" name="portal_password" type="password" minlength="16" '
        'maxlength="256" required autocomplete="new-password"' + invalid('portal_password') + '></label>'
        '<label class="field">Confirm portal password<input id="portal-password-confirm" name="portal_password_confirm" type="password" '
        'minlength="16" maxlength="256" required autocomplete="new-password"' + invalid('portal_password_confirm') + '></label></div></div>'
        '<p class="muted">Use at least 16 characters with three character types, or a varied '
        'passphrase of at least 20 characters. Automatic transport uses HTTPS whenever a portal '
        'certificate is installed.</p></section>'
        '<section class="card"><div class="section-title"><h2>Emergency recovery</h2></div>'
        '<div class="credential-group"><h3>Recovery Wi-Fi access</h3>'
        '<p class="muted">Used only to join the protected IoT-MD-Recovery access point.</p>'
        '<div class="credential-pair">'
        '<label class="field">Recovery AP password<input id="recovery-ap-password" name="recovery_ap_password" type="password" '
        'minlength="16" maxlength="63" required autocomplete="new-password"' + invalid('recovery_ap_password') + '></label>'
        '<label class="field">Confirm recovery AP password<input id="recovery-ap-password-confirm" name="recovery_ap_password_confirm" type="password" '
        'minlength="16" maxlength="63" required autocomplete="new-password"' + invalid('recovery_ap_password_confirm') + '></label></div></div>'
        '<div class="credential-group"><h3>Recovery console sign-in</h3>'
        '<p class="muted">Used after joining the recovery access point.</p>'
        '<div class="credential-pair">'
        '<label class="field">Recovery console password<input id="recovery-password" name="recovery_password" type="password" '
        'minlength="16" maxlength="256" required autocomplete="new-password"' + invalid('recovery_password') + '></label>'
        '<label class="field">Confirm recovery console password<input id="recovery-password-confirm" name="recovery_password_confirm" type="password" '
        'minlength="16" maxlength="256" required autocomplete="new-password"' + invalid('recovery_password_confirm') + '></label></div></div>'
        '<p class="muted">These must be strong and different from each other and from the portal password.</p>'
        '</section><button type="submit">Save and continue</button></form>'
        '<script>document.getElementById("browser-time").value=new Date().toISOString();'
        'var deviceName=document.getElementById("device-name"),mdns=document.getElementById('
        '"mdns-hostname"),mdnsEdited=!!mdns.value;function hostnameFromDevice(){var label=deviceName.value'
        '.toLowerCase().trim().replace(/[^a-z0-9]+/g,"-").replace(/^-+|-+$/g,"").slice(0,63);'
        'if(!mdnsEdited)mdns.value=label?label+".local":"";}mdns.addEventListener("input",'
        'function(){mdnsEdited=true;});deviceName.addEventListener("input",hostnameFromDevice);'
        'var wifiInput=document.getElementById("wifi-ssid-input"),wifiOptions=document.getElementById('
        '"wifi-network-options"),wifiStatus='
        'document.getElementById("wifi-scan-status"),wifiRescan=document.getElementById("wifi-rescan");'
        'function setWifiStatus(state,text){wifiStatus.className="portal-status"+(state?" "+state:"");'
        'wifiStatus.textContent=text;}'
        'function wifiOption(value,text){var option=document.createElement("option");option.value=value;'
        'option.label=text;return option;}function scanWifi(){wifiRescan.disabled=true;'
        'setWifiStatus("","Scanning for nearby networks…");fetch("/wifi-networks",{cache:"no-store",'
        'credentials:"same-origin"}).then(function(response){if(!response.ok)throw new Error("HTTP "+response.status);'
        'return response.json();}).then(function(networks){wifiOptions.textContent="";for(var i=0;i<networks.length;i++){var network='
        'networks[i],label=network.ssid+(typeof network.rssi==="number"?" ("+network.rssi+" dBm)":"");'
        'wifiOptions.appendChild(wifiOption(network.ssid,label));}setWifiStatus('
        'networks.length?"success":"warning",networks.length?networks.length+" network"+'
        '(networks.length===1?"":"s")+" found; select one or enter its name.":'
        '"No visible networks found; enter the network name.");}).catch(function(){setWifiStatus("warning",'
        '"Network scan unavailable; enter the SSID manually.");'
        '}).finally(function(){wifiRescan.disabled=false;});}wifiRescan.onclick=scanWifi;scanWifi();'
        'var dhcp=document.getElementById("wifi-dhcp"),staticBox=document.getElementById('
        '"wifi-static-settings");function syncNetworkMode(){var manual=!dhcp.checked;'
        'staticBox.hidden=!manual;var fields=staticBox.querySelectorAll("input");for(var i=0;'
        'i<fields.length;i++)fields[i].required=manual;}dhcp.onchange=syncNetworkMode;syncNetworkMode();'
        'var setupForm=document.getElementById("setup-form"),setupValidation=document.getElementById('
        '"setup-validation"),pairs=[["portal-password","portal-password-confirm","Portal passwords do not match"],'
        '["recovery-ap-password","recovery-ap-password-confirm","Recovery AP passwords do not match"],'
        '["recovery-password","recovery-password-confirm","Recovery console passwords do not match"]],'
        'passwordInputs=[];for(var p=0;p<pairs.length;p++){passwordInputs.push(document.getElementById('
        'pairs[p][0]),document.getElementById(pairs[p][1]));}function clearPasswordErrors(){for(var i=0;'
        'i<passwordInputs.length;i++)portalClearInvalid(passwordInputs[i]);}for(var i=0;i<passwordInputs.length;'
        'i++)passwordInputs[i].addEventListener("input",clearPasswordErrors);setupForm.addEventListener('
        '"submit",function(event){document.getElementById("browser-time").value=new Date().toISOString();'
        'clearPasswordErrors();var messages=[],invalidGroups={};for(var p=0;p<pairs.length;p++){var first='
        'document.getElementById(pairs[p][0]),confirmation=document.getElementById(pairs[p][1]);if(first.value'
        '!==confirmation.value){invalidGroups[p]=pairs[p][2];messages.push(pairs[p][2]);}}for(var i=0;i<pairs.length;'
        'i++){for(var j=i+1;j<pairs.length;j++){if(document.getElementById(pairs[i][0]).value==='
        'document.getElementById(pairs[j][0]).value){var duplicateMessage="Portal, recovery console and recovery '
        'AP passwords must all differ";invalidGroups[i]=duplicateMessage;invalidGroups[j]=duplicateMessage;if('
        'messages.indexOf(duplicateMessage)<0)messages.push(duplicateMessage);}}}if(messages.length){event.preventDefault();'
        'var firstInvalid=null;for(var group in invalidGroups){var primary=document.getElementById(pairs[group][0]);'
        'if(!firstInvalid)firstInvalid=primary;portalInvalid(primary,invalidGroups[group],false);portalInvalid('
        'document.getElementById(pairs[group][1]),invalidGroups[group],false);}portalStatus(setupValidation,"error",'
        'messages.join(". "));if(firstInvalid)firstInvalid.focus();}});</script>'
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

def _certificate_page(csrf, hostname='', message='', ready=False, error=False):
    self_signed_ready = ready and message == SELF_SIGNED_READY_MESSAGE
    notice = (
        '<p class="' + ('error' if error else 'notice') + '" role="' +
        ('alert' if error else 'status') + '">' + _escape(message) + '</p>'
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
        '<p>A device-generated self-signed certificate is installed for HTTPS. Select how '
        'this device should secure its portal and private services. Only the settings for '
        'the selected method will be shown.</p>'
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
        '<section class="card"><div class="section-title"><h2>Certificate method</h2></div>'
        '<label class="field">Certificate option<select id="certificate-option">'
        '<option value="" selected>Select a certificate option…</option>'
        '<option value="self_signed">Self-signed certificate</option>'
        '<option value="iot_ca_auto">Automatic IoT CA enrollment</option>'
        '<option value="iot_ca_file">IoT CA enrollment file (.iotenroll)</option>'
        '<option value="acme">Private CA ACME enrollment</option>'
        '<option value="manual">Manual certificate package</option>'
        '</select></label><p id="certificate-option-description" class="info" role="status" '
        'aria-live="polite">Choose an option to see its requirements.</p></section>'
        '<section class="card certificate-option-panel" data-certificate-option="self_signed" hidden>'
        '<div class="section-title"><h2>Self-signed certificate</h2></div>'
        '<p>Use the certificate generated by this device. No additional files or services '
        'are required, but browsers will show a trust warning until the certificate is trusted manually.</p>'
        '<p class="info"><strong>Renewal:</strong> The device automatically regenerates this '
        'certificate after two-thirds of its lifetime.</p>'
        '<form class="page-load-action" action="/install" method="post">'
        '<input type="hidden" name="csrf" value="' + _escape(csrf) + '">'
        '<input type="hidden" name="certificate_mode" value="self_signed">'
        '<button id="continue" class="secondary"' + disabled +
        '>Continue with self-signed certificate</button></form></section>'
        '<section class="card certificate-option-panel" data-certificate-option="iot_ca_auto" hidden>'
        '<div class="section-title"><h2>Automatic IoT CA enrollment</h2></div>'
        '<p>When automatic IoT-MD enrollment is enabled in IoT CA, this device can request its '
        'host-bound authorization and complete the whole certificate process. The device generates '
        'all private keys locally; Cloudflare credentials remain on IoT CA. Use automatic '
        'enrollment only on a trusted setup LAN.</p>'
        '<p class="info"><strong>Renewal:</strong> The public portal, private Device API and '
        'renewal identity are installed and automatically rotated together after two-thirds of '
        'the public portal or Device API certificate lifetime.</p>'
        '<form action="/iot-ca-auto-enrollment" method="post">'
        '<input type="hidden" name="csrf" value="' + _escape(csrf) + '">'
        '<div class="grid"><label class="field">IoT CA server name<span class="field-hint">'
        'Leave blank to use <code>iot-ca.home.arpa</code>.</span><input name="ca_server" '
        'maxlength="253" placeholder="iot-ca.home.arpa"></label>'
        '<label class="field">IoT CA provisioning port<span class="field-hint">Leave blank '
        'to use <code>9010</code>.</span><input name="ca_port" type="number" inputmode="numeric" '
        'min="1" max="65535" placeholder="9010"></label></div>'
        '<label class="field">Private Device API hostname<input value="' +
        _escape(hostname) + '" readonly></label>'
        '<button id="iot-ca-auto-enroll" type="submit">Request and install certificates</button>'
        '</form></section>'
        '<section class="card certificate-option-panel" data-certificate-option="iot_ca_file" hidden>'
        '<div class="section-title"><h2>IoT CA enrollment file (.iotenroll)</h2></div>'
        '<p>Use a short-lived, host-bound authorization downloaded from IoT CA. This provides '
        'the same public portal and private Device API identities as Automatic IoT CA enrollment '
        'without opening trusted-LAN automatic enrollment.</p>'
        '<p class="info"><strong>Renewal:</strong> The public portal, private Device API and '
        'renewal identity are installed and automatically rotated together after two-thirds of '
        'the public portal or Device API certificate lifetime.</p>'
        '<form action="/iot-ca-enrollment" method="post" enctype="multipart/form-data">'
        '<input type="hidden" name="csrf" value="' + _escape(csrf) + '">'
        '<label class="field">IoT CA enrollment file'
        '<span class="field-hint">Expected filename: <code>device.iotenroll</code></span>'
        '<input id="iot-ca-enrollment" name="enrollment_file" type="file" '
        'accept=".iotenroll,application/vnd.iotmd.enrollment+json" required></label>'
        '<button id="iot-ca-enroll" type="submit">Provision from authorization file</button>'
        '</form></section>'
        '<section class="card certificate-option-panel" data-certificate-option="acme" hidden>'
        '<form action="/enroll-certificate" method="post" enctype="multipart/form-data">'
        '<div class="section-title"><h2>Private CA ACME enrollment</h2></div>'
        '<input type="hidden" name="csrf" value="' + _escape(csrf) + '">'
        '<p>The device is connected to the home Wi-Fi and is advertising its '
        '<code>.local</code> hostname with mDNS. It will answer the CA HTTP-01 request on port 80. '
        'The CA must be on the same multicast network and able to resolve mDNS.</p>'
        '<p class="info"><strong>Renewal:</strong> The portal certificate renews automatically '
        'through this ACME directory after two-thirds of its lifetime. This route does not install '
        'or renew a separate private Device API identity.</p>'
        '<label class="field">Home IoT trusted CA certificate<input id="trust-ca" name="trust_ca" '
        'type="file" accept=".der,application/pkix-cert" required></label>'
        '<label class="field">ACME directory URL<span class="field-hint">Leave blank to use '
        '<code>https://iot-ca.home.arpa:9000/acme/acme/directory</code>.</span><input '
        'id="acme-directory" name="directory_url" type="url" '
        'placeholder="https://iot-ca.home.arpa:9000/acme/acme/directory"></label>'
        '<label class="field">Portal DNS hostname<input id="certificate-hostname" name="hostname" '
        'value="' + _escape(hostname) + '" readonly></label>'
        '<button id="enroll" type="submit">Upload root and enroll with ACME</button></form></section>'
        '<section class="card certificate-option-panel" data-certificate-option="manual" hidden>'
        '<form action="/manual-certificates" method="post" enctype="multipart/form-data">'
        '<div class="section-title"><h2>Manual certificate package</h2></div>'
        '<input type="hidden" name="csrf" value="' + _escape(csrf) + '">'
        '<label class="field">Home IoT trusted CA certificate<input name="trust_ca" type="file" required></label>'
        '<label class="field">Public portal DNS hostname<input id="portal-public-hostname" name="portal_hostname" '
        'required maxlength="253" placeholder="device.example.com"></label>'
        '<label class="field">Public portal certificate chain<span class="field-hint">Expected filename: <code>web.crt.pem</code></span><input id="portal-cert" name="portal_cert" type="file" accept=".pem,application/x-pem-file" required></label>'
        '<label class="field">Public portal private key<span class="field-hint">Expected filename: <code>web.key.der</code></span><input id="portal-key" name="portal_key" type="file" required></label>'
        '<label class="field">Private Device API certificate<span class="field-hint">Expected filename: <code>api-server.crt.der</code></span><input id="api-server-cert" name="api_server_cert" type="file" required></label>'
        '<label class="field">Private Device API key<span class="field-hint">Expected filename: <code>api-server.key.der</code></span><input id="api-server-key" name="api_server_key" type="file" required></label>'
        '<p class="muted">These files are produced together by the IoT CA public-portal profile. The public portal and private API identities remain independent.</p>'
        '<p class="info"><strong>Renewal:</strong> Manually uploaded public and private '
        'certificates are not renewed automatically. Replace the package before either identity expires.</p>'
        '<button id="upload" type="submit">Upload and validate provisioning files</button>'
        '</form></section></main>'
        '<script src="' + _asset('/assets/portal.js') + '"></script><script>'
        'var certificateOption=document.getElementById("certificate-option"),certificateDescription='
        'document.getElementById("certificate-option-description"),certificateDescriptions={'
        'self_signed:"Use the device-generated certificate and continue immediately. Browsers may show a trust warning.",'
        'iot_ca_auto:"Request a managed public portal and private service identity set during an enabled IoT CA enrollment window.",'
        'iot_ca_file:"Upload a one-time .iotenroll authorization to request the same managed identity set.",'
        'acme:"Use the private CA ACME directory for an automatically renewed local portal certificate.",'
        'manual:"Upload an existing portal certificate, private key, and private service identity package; renewal remains manual."};'
        'function syncCertificateOption(){var selected=certificateOption.value,panels=document.querySelectorAll('
        '"[data-certificate-option]");for(var i=0;i<panels.length;i++){var visible=panels[i].getAttribute('
        '"data-certificate-option")===selected;panels[i].hidden=!visible;var controls=panels[i].querySelectorAll('
        '"input,select,button");for(var j=0;j<controls.length;j++)controls[j].disabled=!visible;}'
        'certificateDescription.textContent=certificateDescriptions[selected]||"Choose an option to see its requirements.";}'
        'certificateOption.addEventListener("change",syncCertificateOption);syncCertificateOption();</script>'
        '</body></html>'
    )

def _enrollment_page(message):
    return (
        '<!doctype html><html><head><meta name="viewport" content="width=device-width,initial-scale=1">'
        '<title>Enrolling certificate</title><link rel="stylesheet" href="' +
        _asset('/assets/portal.css') + '">'
        '</head><body>' + _setup_header() + '<main class="setup-main">' + _setup_progress(3) +
        portal_ui.page_heading(
            'Certificate security', 'Enrolling certificate',
            'The device is completing certificate enrollment.'
        ) + '<section class="card">' + portal_ui.progress(
            'enrollment-progress', message
        ) + '<p class="muted">Status updates automatically.</p>'
        '<div class="page-load-action"><button id="enrollment-check" class="secondary" type="button">'
        'Check status now</button></div></section></main>'
        '<script src="' + _asset('/assets/portal.js') + '"></script><script>'
        'var enrollmentLabel=document.querySelector("#enrollment-progress .status-text"),'
        'enrollmentButton=document.getElementById("enrollment-check"),enrollmentRequestRunning=false;'
        'function pollEnrollment(){if(enrollmentRequestRunning)return;enrollmentRequestRunning=true;'
        'fetch("/enrollment-state",{cache:"no-store",credentials:"same-origin"})'
        '.then(function(response){if(!response.ok)throw new Error("HTTP "+response.status);return response.json();})'
        '.then(function(state){if(state.message&&enrollmentLabel)enrollmentLabel.textContent=state.message;if('
        'state.status!=="running")window.location.replace("/enrollment-status");else setTimeout(pollEnrollment,2000);})'
        '.catch(function(){setTimeout(pollEnrollment,2000);}).finally(function(){enrollmentRequestRunning=false;});}'
        'enrollmentButton.onclick=pollEnrollment;setTimeout(pollEnrollment,1500);</script></body></html>'
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
                csrf, hostname, 'Installed certificate validation failed: ' + str(exc),
                False, True
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
        '<meta name="referrer" content="no-referrer"><title>Opening IoT-MD</title>'
        '<style>' + portal_ui.PORTAL_CSS + '</style></head><body>' + _setup_header() +
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

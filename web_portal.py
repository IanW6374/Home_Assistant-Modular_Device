try:
    import ssl
except ImportError:
    ssl = None

try:
    import asyncio
except ImportError:
    asyncio = None

try:
    import json
except ImportError:
    json = None

try:
    import os
except ImportError:
    os = None

try:
    import ubinascii as binascii
except ImportError:
    import binascii

try:
    import time
except ImportError:
    time = None

import web_portal_ui as portal_ui
import http_support
from device_modules.base import module_diagnostics_need_attention


HTML_ESCAPE = {
    '&': '&amp;',
    '<': '&lt;',
    '>': '&gt;',
    '"': '&quot;',
    "'": '&#39;',
}


JS_ESCAPE = {
    '\\': '\\\\',
    "'": "\\'",
    '\n': '\\n',
    '\r': '\\r',
}


def html_escape(value):
    text = str(value)
    for char, escaped in HTML_ESCAPE.items():
        text = text.replace(char, escaped)
    return text


def js_escape(value):
    text = str(value)
    for char, escaped in JS_ESCAPE.items():
        text = text.replace(char, escaped)
    return text


def parse_query(path):
    params = {}
    if '?' not in path:
        return params

    query = path.split('?', 1)[1]
    for pair in query.split('&'):
        if not pair:
            continue
        if '=' in pair:
            key, value = pair.split('=', 1)
        else:
            key, value = pair, ''
        params[url_decode(key)] = url_decode(value)
    return params


def url_decode(value):
    value = str(value).replace('+', ' ')
    result = bytearray()
    index = 0
    while index < len(value):
        if value[index] == '%' and index + 2 < len(value):
            try:
                result.append(int(value[index + 1:index + 3], 16))
                index += 3
                continue
            except ValueError:
                pass
        result.extend(value[index].encode())
        index += 1
    try:
        return bytes(result).decode()
    except UnicodeError:
        return ''.join(chr(byte) for byte in result)


def parse_request_line(line):
    parts = line.split()
    if len(parts) < 2:
        return None, None
    return parts[0], parts[1]


def constant_time_equal(left, right):
    """Compare short credentials without exiting on the first mismatch."""
    left_bytes = str(left).encode()
    right_bytes = str(right).encode()
    different = len(left_bytes) ^ len(right_bytes)
    longest = max(len(left_bytes), len(right_bytes))
    for index in range(longest):
        left_value = left_bytes[index] if index < len(left_bytes) else 0
        right_value = right_bytes[index] if index < len(right_bytes) else 0
        different |= left_value ^ right_value
    return different == 0


def credentials_match(candidate_username, candidate_password, username, password_verifier):
    import credential_security
    username_matches = constant_time_equal(candidate_username, username)
    password_matches = credential_security.verify_password(
        candidate_password, password_verifier
    )
    return username_matches and password_matches


async def credentials_match_async(
    candidate_username, candidate_password, username, password_verifier
):
    import credential_security
    username_matches = constant_time_equal(candidate_username, username)
    password_matches = await credential_security.verify_password_async(
        candidate_password, password_verifier
    )
    return username_matches and password_matches


def parse_cookies(headers):
    cookies = {}
    for item in (headers or {}).get('cookie', '').split(';'):
        if '=' in item:
            key, value = item.strip().split('=', 1)
            cookies[key] = value
    return cookies


def has_portal_session(headers, session_id):
    return bool(session_id) and parse_cookies(headers).get('ham_session') == session_id


def session_cookie(session_id, secure=False, clear=False):
    cookie = 'ham_session=' + str(session_id) + '; Path=/; HttpOnly; SameSite=Strict'
    if clear:
        cookie += '; Max-Age=0'
    if secure:
        cookie += '; Secure'
    return cookie


PORTAL_SHELL_CSS = portal_ui.PORTAL_CSS


def _notice(message='', error=False):
    if not message:
        return ''
    return (
        '<p class="' + ('error' if error else 'notice') + '" role="status">' +
        html_escape(message) + '</p>'
    )


def render_login_page(username='admin', error=''):
    body = (
        '<section class="auth-card card"><span class="eyebrow">Secure device portal</span>'
        '<h1>Welcome back</h1><p class="lead">Sign in to manage this HAMD device.</p>' +
        _notice(error, True) +
        '<form id="login-form" action="/login" method="post">'
        '<label class="field">Username<input name="username" autocomplete="username" value="' +
        html_escape(username) + '" required maxlength="64"></label>'
        '<label class="field">Password<input name="password" type="password" '
        'autocomplete="current-password" required maxlength="256" autofocus></label>'
        '<button id="login-button" type="submit">Sign in</button>'
        '<p id="auth-status" class="muted" role="status"></p></form></section>'
    )
    script = (
        'document.getElementById("login-form").onsubmit=function(){var b=document.getElementById('
        '"login-button");b.disabled=true;b.textContent="Signing in…";document.getElementById('
        '"auth-status").textContent="Securely verifying your password…";};'
    )
    return portal_ui.shell(
        'HAMD login', '', body, script=script, authenticated=False
    )


def render_password_change_form(csrf, error='', required=False):
    return (
        '<section class="card"><div class="section-title"><h2>' +
        ('Set administrator password' if required else 'Change password') +
        '</h2></div>' + _notice(error, True) +
        '<form method="post" action="/user?action=password">'
        '<input type="hidden" name="csrf" value="' + html_escape(csrf) + '">'
        '<div class="grid"><label class="field">Current password<input type="password" '
        'name="current_password" autocomplete="current-password" maxlength="256" required></label>'
        '<label class="field">New password<input type="password" name="new_password" '
        'autocomplete="new-password" minlength="16" maxlength="256" required></label>'
        '<label class="field">Confirm password<input type="password" name="confirm_password" '
        'autocomplete="new-password" minlength="16" maxlength="256" required></label></div>'
        '<p class="muted">Use at least 16 characters with three character types, or a varied '
        'passphrase of at least 20 characters.</p><div class="actions">'
        '<span></span><button type="submit">Save new password</button></div></form></section>'
    )


def render_password_change_page(csrf, error='', required=False):
    message = (
        'Replace the one-time password before using the portal.'
        if required else 'Manage the administrator identity and password for this device.'
    )
    body = (
        portal_ui.page_heading('User', 'Account', message) +
        render_password_change_form(csrf, error, required)
    )
    return portal_ui.shell('HAMD account', 'user_settings', body, csrf)


def render_operational_hidden_fields(settings, excluded=()):
    settings = settings or {}
    port = settings.get('portal_port')
    values = (
        ('device_name', settings.get('device_name', '')),
        ('portal_username', settings.get('portal_username', 'admin')),
        ('portal_transport', settings.get('portal_transport', 'auto')),
        ('portal_port', '' if port is None else str(port)),
        ('ntp_servers', ', '.join(settings.get('ntp_servers', ()))),
        ('wifi_ssid', settings.get('wifi_ssid', '')),
        ('wifi_dhcp', 'true' if settings.get('wifi_dhcp', True) else 'false'),
        ('wifi_ip_address', settings.get('wifi_ip_address', '')),
        ('wifi_subnet_mask', settings.get('wifi_subnet_mask', '')),
        ('wifi_gateway', settings.get('wifi_gateway', '')),
        ('wifi_dns_server', settings.get('wifi_dns_server', '')),
        ('mqtt_server', settings.get('mqtt_server', '')),
        ('mqtt_port', settings.get('mqtt_port', 8883)),
        ('mqtt_username', settings.get('mqtt_username', '')),
        ('ha_discovery', 'true' if settings.get('ha_discovery') else 'false'),
    )
    parts = []
    for name, value in values:
        if name not in excluded:
            parts.append(
                '<input type="hidden" name="' + html_escape(name) +
                '" value="' + html_escape(value) + '">'
            )
    return ''.join(parts)


def render_settings_page(csrf, settings, message='', error=False):
    settings = settings or {}
    stored = bool(settings.get('wifi_password_set'))
    placeholder = ' placeholder="&#8226;&#8226;&#8226;&#8226;&#8226;&#8226;&#8226;&#8226;"' if stored else ''
    password_hint = (
        'A password is stored. Overtype the masked field to replace it.'
        if stored else 'No Wi-Fi password is stored.'
    )
    body = (
        portal_ui.page_heading(
            'System', 'Network', 'Configure the device identity and wireless network.'
        ) + _notice(message, error) +
        '<form action="/settings" method="post" autocomplete="off">'
        '<input type="hidden" name="csrf" value="' + html_escape(csrf) + '">' +
        render_operational_hidden_fields(settings, (
            'device_name', 'wifi_ssid', 'wifi_dhcp', 'wifi_ip_address',
            'wifi_subnet_mask', 'wifi_gateway', 'wifi_dns_server'
        )) +
        '<section class="card"><div class="section-title"><h2>Device identity</h2></div>'
        '<label class="field">Device name<input name="device_name" required maxlength="64" value="' +
        html_escape(settings.get('device_name', '')) + '"></label></section>'
        '<section class="card"><div class="section-title"><h2>Wi-Fi network</h2></div>'
        '<div class="grid"><label class="field">Network name (SSID)<input name="wifi_ssid" '
        'required maxlength="32" value="' + html_escape(settings.get('wifi_ssid', '')) + '"></label>'
        '<label class="field">Network password<input name="wifi_password" type="password" '
        'maxlength="64" autocomplete="new-password"' + placeholder + '></label></div>'
        '<p class="muted">' + password_hint + '</p>'
        '<label class="check"><input id="wifi-dhcp" name="wifi_dhcp" type="checkbox" value="true"' +
        (' checked' if settings.get('wifi_dhcp', True) else '') +
        '>Use DHCP to obtain network settings automatically</label>'
        '<div id="wifi-static-settings" class="grid"' +
        (' hidden' if settings.get('wifi_dhcp', True) else '') + '>'
        '<label class="field">IP address<input name="wifi_ip_address" inputmode="decimal" '
        'maxlength="15" placeholder="192.168.1.50" value="' +
        html_escape(settings.get('wifi_ip_address', '')) + '"></label>'
        '<label class="field">Subnet mask<input name="wifi_subnet_mask" inputmode="decimal" '
        'maxlength="15" placeholder="255.255.255.0" value="' +
        html_escape(settings.get('wifi_subnet_mask', '')) + '"></label>'
        '<label class="field">Default gateway<input name="wifi_gateway" inputmode="decimal" '
        'maxlength="15" placeholder="192.168.1.1" value="' +
        html_escape(settings.get('wifi_gateway', '')) + '"></label>'
        '<label class="field">DNS server<input name="wifi_dns_server" inputmode="decimal" '
        'maxlength="15" placeholder="192.168.1.1" value="' +
        html_escape(settings.get('wifi_dns_server', '')) + '"></label></div></section>'
        '<div class="actions"><span></span><button type="submit">Save settings and restart</button>'
        '</div></form>'
    )
    script = (
        'var dhcp=document.getElementById("wifi-dhcp"),staticBox='
        'document.getElementById("wifi-static-settings");function syncNetworkMode(){'
        'var manual=!dhcp.checked;staticBox.hidden=!manual;var fields=staticBox.querySelectorAll("input");'
        'for(var i=0;i<fields.length;i++)fields[i].required=manual;}dhcp.onchange=syncNetworkMode;'
        'syncNetworkMode();'
    )
    return portal_ui.shell('HAMD network', 'settings', body, csrf, script)


def render_portal_settings_page(csrf, settings, message='', error=False):
    settings = settings or {}
    transport = settings.get('portal_transport', 'auto')
    port = settings.get('portal_port')
    port_value = '' if port is None else str(port)
    body = (
        portal_ui.page_heading(
            'System', 'Portal', 'Configure portal transport and listening port.'
        ) + _notice(message, error) +
        '<form action="/portal-settings" method="post" autocomplete="off">'
        '<input type="hidden" name="csrf" value="' + html_escape(csrf) + '">' +
        render_operational_hidden_fields(settings, ('portal_transport', 'portal_port')) +
        '<section class="card"><div class="section-title"><h2>Portal access</h2></div>'
        '<div class="grid">'
        '<label class="field">Portal transport<select name="portal_transport">'
        '<option value="auto"' + (' selected' if transport == 'auto' else '') +
        '>Automatic (HTTPS with certificate)</option><option value="https"' +
        (' selected' if transport == 'https' else '') + '>Always HTTPS</option>'
        '<option value="http"' + (' selected' if transport == 'http' else '') +
        '>HTTP (unencrypted)</option></select></label>'
        '<label class="field">Portal port<input name="portal_port" type="number" min="1" max="65535" '
        'placeholder="8443 (default)" value="' + html_escape(port_value) + '"></label></div>'
        '<p class="muted">Leave the port blank to use 8443 for HTTPS. Port 80 is reserved for '
        'certificate enrollment and recovery.</p><div class="actions"><span></span>'
        '<button type="submit">Save settings and restart</button></div></section></form>'
    )
    return portal_ui.shell('HAMD portal settings', 'portal_settings', body, csrf)


def render_wifi_settings_page(csrf, settings, message='', error=False):
    # Keep the former URL working for bookmarks while presenting the merged page.
    return render_settings_page(csrf, settings, message, error)


def render_ntp_settings_page(csrf, settings, message='', error=False):
    settings = settings or {}
    ntp_servers = ', '.join(settings.get('ntp_servers', ()))
    body = (
        portal_ui.page_heading(
            'System', 'NTP', 'Configure the time servers used to set the device clock.'
        ) + _notice(message, error) +
        '<form action="/ntp-settings" method="post" autocomplete="off">'
        '<input type="hidden" name="csrf" value="' + html_escape(csrf) + '">' +
        render_operational_hidden_fields(settings, ('ntp_servers',)) +
        '<section class="card"><div class="section-title"><h2>Time synchronisation</h2></div>'
        '<label class="field">NTP servers (comma separated)<input name="ntp_servers" required '
        'maxlength="1024" value="' + html_escape(ntp_servers) + '"></label>'
        '<div class="actions"><span></span><button type="submit">Save settings and restart</button>'
        '</div></section></form>'
    )
    return portal_ui.shell('HAMD NTP settings', 'ntp_settings', body, csrf)


def render_mqtt_page(csrf, settings, message='', error=False):
    settings = settings or {}
    stored = bool(settings.get('mqtt_password_set'))
    placeholder = ' placeholder="&#8226;&#8226;&#8226;&#8226;&#8226;&#8226;&#8226;&#8226;"' if stored else ''
    mqtt_hint = (
        'A password is stored. Overtype the masked field to replace it.'
        if stored else 'No MQTT password is stored.'
    )
    body = (
        portal_ui.page_heading(
            'System', 'MQTT',
            'Configure the secure MQTT broker connection used for published values.'
        ) + _notice(message, error) +
        '<form action="/mqtt" method="post" autocomplete="off">'
        '<input type="hidden" name="csrf" value="' + html_escape(csrf) + '">' +
        render_operational_hidden_fields(
            settings, ('mqtt_server', 'mqtt_port', 'mqtt_username')
        ) +
        '<section class="card"><div class="section-title"><h2>MQTT connection</h2></div>'
        '<div class="grid"><label class="field">Broker hostname<input name="mqtt_server" maxlength="253" '
        'value="' + html_escape(settings.get('mqtt_server', '')) + '"></label>'
        '<label class="field">Broker port<input name="mqtt_port" type="number" min="1" max="65535" '
        'required value="' + html_escape(settings.get('mqtt_port', 8883)) + '"></label>'
        '<label class="field">MQTT username<input name="mqtt_username" maxlength="128" value="' +
        html_escape(settings.get('mqtt_username', '')) + '"></label>'
        '<label class="field">MQTT password<input name="mqtt_password" type="password" '
        'maxlength="256" autocomplete="new-password"' + placeholder + '></label></div>'
        '<p class="muted">' + mqtt_hint +
        ' MQTT TLS is mandatory. Leave hostname blank to disable MQTT.</p>'
        '<div class="actions"><span></span>'
        '<button type="submit">Save settings and restart</button></div></section></form>'
    )
    return portal_ui.shell('HAMD MQTT', 'mqtt', body, csrf)


def render_home_assistant_page(csrf, settings, message='', error=False):
    settings = settings or {}
    discovery_checked = ' checked' if settings.get('ha_discovery') else ''
    body = (
        portal_ui.page_heading(
            'System', 'Home Assistant',
            'Control discovery and republish entity configuration to Home Assistant.'
        ) + _notice(message, error) +
        '<form action="/home-assistant" method="post" autocomplete="off">'
        '<input type="hidden" name="csrf" value="' + html_escape(csrf) + '">' +
        render_operational_hidden_fields(settings, ('ha_discovery',)) +
        '<section class="card"><div class="section-title"><h2>Home Assistant discovery</h2></div>'
        '<label class="check"><input type="checkbox" name="ha_discovery"' +
        discovery_checked + '>Enable Home Assistant discovery</label>'
        '<p class="muted">Discovery publishes entity configuration to Home Assistant over MQTT.</p>'
        '<div class="actions"><span></span><button type="submit">Save settings and restart</button>'
        '</div></section></form>'
        '<section class="card"><div class="section-title"><h2>Publish configuration</h2></div>'
        '<div class="actions"><p class="muted">Republish discovery configuration for all loaded entities.</p>'
        '<form action="/discover" method="post"><input type="hidden" name="csrf" value="' +
        html_escape(csrf) + '"><button type="submit">Publish discovery</button></form></div></section>'
    )
    return portal_ui.shell('HAMD Home Assistant', 'home_assistant', body, csrf)


def render_user_settings_page(
    csrf, settings, message='', error=False, password_message='', password_error=False
):
    settings = settings or {}
    body = (
        portal_ui.page_heading(
            'User', 'Account',
            'Manage the administrator identity and password used to sign in to this portal.'
        ) + _notice(message, error) +
        '<form action="/user" method="post" autocomplete="off">'
        '<input type="hidden" name="csrf" value="' + html_escape(csrf) + '">' +
        render_operational_hidden_fields(settings, ('portal_username',)) +
        '<section class="card"><div class="section-title"><h2>Administrator identity</h2></div>'
        '<label class="field">Portal username<input name="portal_username" required maxlength="32" '
        'value="' + html_escape(settings.get('portal_username', 'admin')) + '"></label>'
        '<div class="actions"><span></span><button type="submit">Save username and restart</button>'
        '</div></section></form>' + render_password_change_form(
            csrf, password_message if password_error else ''
        )
    )
    return portal_ui.shell('HAMD account', 'user_settings', body, csrf)


def render_module_settings_page(csrf, module_json='{"devices":[]}', message='', error=False):
    body = (
        portal_ui.page_heading(
            'Module', 'Module configuration',
            'Edit the complete module configuration as structured JSON.'
        ) + _notice(message, error) +
        '<section class="card"><form action="/module-settings" method="post">'
        '<input type="hidden" name="csrf" value="' + html_escape(csrf) + '">'
        '<div class="section-title"><div><h2>Module configuration</h2>'
        '<p class="muted">The editor formats and validates JSON before it is applied.</p></div>'
        '<button id="module-format" class="secondary compact" type="button">Format JSON</button></div>'
        '<textarea class="code-editor" id="module-settings-json" name="module_settings_json" '
        'spellcheck="false" required>' + html_escape(module_json or '{"devices":[]}') +
        '</textarea>'
        '<div class="actions"><span><input class="file-input-hidden" '
        'id="module-settings-file" type="file" accept=".json,application/json">'
        '<label class="button secondary file-button" for="module-settings-file">Load JSON file</label> '
        '<span id="module-file-name" class="file-name">No file selected</span></span>'
        '<button id="module-submit" type="submit">Verify and apply configuration</button></div>' +
        portal_ui.progress('module-progress', 'Validating…', True) +
        '</form></section>'
    )
    script = (
        'var raw=document.getElementById("module-settings-json");'
        'function formatJson(report){try{raw.value=JSON.stringify(JSON.parse(raw.value),null,2);return true;}'
        'catch(error){if(report)alert("Invalid JSON: "+error.message);return false;}}'
        'document.getElementById("module-format").onclick=function(){formatJson(true);};'
        'document.getElementById("module-settings-file").onchange=function(){var f=this.files&&this.files[0];'
        'if(!f)return;document.getElementById("module-file-name").textContent=f.name;var r=new FileReader();'
        'r.onload=function(){raw.value=r.result;try{raw.value=JSON.stringify(JSON.parse(raw.value),null,2);'
        '}catch(error){alert("Invalid JSON: "+error.message);}};r.readAsText(f);};'
        'document.querySelector("form[action=\\"/module-settings\\"]").onsubmit=function(e){'
        'if(!formatJson(true)){e.preventDefault();return;}'
        'document.getElementById("module-progress").hidden=false;document.getElementById("module-submit").disabled=true;};'
        'formatJson(false);'
    )
    return portal_ui.shell('HAMD modules', 'modules', body, csrf, script)


def render_certificate_details(certificates):
    certificates = certificates or {}
    def certificate_card(key, label, missing_message='No certificate file is installed.'):
        details = certificates.get(key, {}) or {}
        installed = bool(details.get('installed'))
        badge = render_badge(
            'installed' if installed else 'not installed',
            'good' if installed else 'warn'
        )
        rows = []
        if details.get('error'):
            rows.append(
                '<p class="error-text">Unable to decode: ' +
                html_escape(details.get('error')) + '</p>'
            )
        elif installed:
            for field, field_label in (
                ('subject', 'Subject'), ('issuer', 'Issuer'),
                ('not_before', 'Valid from'), ('not_after', 'Valid until'),
                ('serial_number', 'Serial number'), ('size', 'File size (bytes)')
            ):
                rows.append(
                    '<div class="property-row"><span>' + field_label +
                    '</span><strong>' + html_escape(details.get(field, 'Unknown')) +
                    '</strong></div>'
                )
        else:
            rows.append('<p class="muted">' + html_escape(missing_message) + '</p>')
        return (
            '<article class="module-card"><div class="module-head"><h3>' + label +
            '</h3>' + badge + '</div><div class="property-grid">' +
            ''.join(rows) + '</div></article>'
        )

    groups = (
        (
            'CA Trust',
            'Certificate authorities trusted by this device for secured services.',
            certificate_card(
                'trusted_ca', 'Home IoT trusted CA',
                'No separate CA trust anchor is installed. The generated self-signed portal '
                'certificate is listed under Device Certificates.'
            )
        ),
        (
            'Device Certificates',
            'Certificates that identify the portal or other device services.',
            certificate_card('portal', 'Portal HTTPS certificate')
        ),
    )
    return ''.join(
        '<div class="certificate-group"><div class="certificate-group-head">'
        '<h3>' + title + '</h3><p class="muted">' + description + '</p></div>'
        '<div class="module-grid">' + cards + '</div></div>'
        for title, description, cards in groups
    )


def render_certificate_page(csrf, message='', certificates=None):
    body = (
        portal_ui.page_heading(
            'Maintenance', 'Certificates',
            'Review installed certificate identities and use manual DER upload when renewal is unavailable.'
        ) + _notice(message) +
        '<section class="card"><div class="section-title"><h2>Installed certificates</h2></div>' +
        render_certificate_details(certificates) + '</section>'
        '<section class="card"><div class="section-title"><h2>Manual certificate upload</h2></div>'
        '<p class="muted">The CA, portal certificate and private key are validated together before restart.</p>'
        '<div class="grid"><label class="field">Trusted CA certificate<input id="trust-ca" type="file"></label>'
        '<label class="field">Portal certificate<input id="portal-cert" type="file"></label>'
        '<label class="field">Portal private key<input id="portal-key" type="file"></label></div>'
        '<div class="actions"><span id="result" class="muted"></span>'
        '<button id="upload">Upload, validate and restart</button></div>' +
        portal_ui.progress('certificate-progress', 'Waiting…', True) + '</section>'
    )
    script = (
        'var csrf=' + repr(str(csrf)) + ',kinds=["trust-ca","portal-cert","portal-key"];'
        'document.getElementById("upload").onclick=async function(){var out=document.getElementById("result"),'
        'box=document.getElementById("certificate-progress"),label=box.querySelector(".status-text");'
        'box.classList.remove("complete","failed");box.hidden=false;this.disabled=true;try{for(var i=0;i<kinds.length;i++){'
        'label.textContent="Uploading "+(i+1)+" of 3";var k=kinds[i],'
        'f=document.getElementById(k).files[0];if(!f)throw new Error("Select every certificate file");'
        'var r=await fetch("/certificate-upload",{method:"POST",credentials:"same-origin",headers:{'
        '"Content-Type":"application/octet-stream","X-CSRF-Token":csrf,"X-Certificate-Kind":k},body:f});'
        'if(r.status===401){location.replace("/login");return;}if(!r.ok)throw new Error(await r.text());}'
        'label.textContent="Validating certificates…";var done=await fetch('
        '"/validate-certificates",{method:"POST",credentials:"same-origin",headers:{'
        '"Content-Type":"application/x-www-form-urlencoded"},body:"csrf="+encodeURIComponent(csrf)});'
        'if(done.status===401){location.replace("/login");return;}if(!done.ok)throw new Error(await done.text());'
        'box.classList.add("complete");label.textContent="Validated";document.open();'
        'document.write(await done.text());document.close();}catch(e){out.textContent=e.message;'
        'box.classList.add("failed");label.textContent="Failed";this.disabled=false;}};'
    )
    return portal_ui.shell('HAMD certificates', 'certificates', body, csrf, script)


def render_factory_default_page(csrf, error=''):
    body = (
        portal_ui.page_heading(
            'Maintenance', 'Factory default',
            'Erase user configuration and restart the protected first-boot setup wizard.'
        ) + _notice(error, True) +
        '<section class="card"><div class="section-title"><h2>Reset this device</h2></div>'
        '<p class="warning"><strong>This cannot be undone.</strong> Network, MQTT, portal, '
        'Home Assistant, module, certificate, ACME and log-history data will be erased. '
        'The signed core, active application and update verification key are retained.</p>'
        '<form method="post" action="/factory-default" autocomplete="off">'
        '<input type="hidden" name="csrf" value="' + html_escape(csrf) + '">'
        '<div class="grid"><label class="field">Current administrator password'
        '<input type="password" name="current_password" autocomplete="current-password" '
        'maxlength="256" required></label>'
        '<label class="field">WiFi AP Password<input type="password" '
        'name="setup_password" autocomplete="new-password" minlength="16" maxlength="63" required></label>'
        '<label class="field">Confirm WiFi AP Password<input type="password" '
        'name="confirm_setup_password" autocomplete="new-password" minlength="16" '
        'maxlength="63" required></label>'
        '<label class="field">Type RESET to confirm<input name="reset_confirmation" '
        'autocomplete="off" maxlength="5" pattern="RESET" required></label></div>'
        '<p class="muted">After restart, connect to the HAMD-Setup access point using the new '
        'setup password, then browse to http://192.168.4.1.</p><div class="actions">'
        '<span></span><button class="danger" type="submit">Erase settings and restart</button>'
        '</div></form></section>'
    )
    return portal_ui.shell('HAMD factory default', 'factory_default', body, csrf)


def render_factory_default_complete_page(csrf):
    body = (
        portal_ui.page_heading(
            'Maintenance', 'Factory reset armed',
            'The immutable recovery layer will erase user data and open first-boot setup.'
        ) + '<section class="card"><p class="notice">The device is restarting.</p>'
        '<p>When this network disconnects, join the <strong>HAMD-Setup-xxxxxx</strong> '
        'access point with the setup password you just chose and browse to '
        '<strong>http://192.168.4.1</strong>.</p></section>'
    )
    return portal_ui.shell('HAMD factory reset', 'factory_default', body, csrf)


def new_session_id():
    if os and hasattr(os, 'urandom'):
        return binascii.hexlify(os.urandom(24)).decode()
    try:
        import time
        seed = str(time.ticks_us()) + ':' + str(id(object()))
    except Exception:
        seed = str(id(object()))
    try:
        import uhashlib as hashlib
    except ImportError:
        import hashlib
    return binascii.hexlify(hashlib.sha256(seed.encode()).digest()).decode()[:48]


def monotonic_ms():
    if time and hasattr(time, 'ticks_ms'):
        return time.ticks_ms()
    return int(time.time() * 1000) if time else 0


def elapsed_ms(start):
    if time and hasattr(time, 'ticks_diff'):
        return time.ticks_diff(monotonic_ms(), start)
    return monotonic_ms() - start


def requested_loglevel(path, allowed_levels):
    level = parse_query(path).get('level', '').upper()
    if level in allowed_levels:
        return level
    return None


def apply_loglevel_change(level, loglevel_setter, log_output):
    loglevel_setter(level)
    log_output('Local', 'Web portal', {'log': 'Log level changed to ' + level, 'force': True}, 'INFO')


def apply_portal_action(action, path, action_handler, log_output, params=None):
    result = ''
    if action_handler:
        result = action_handler(
            action, parse_query(path) if params is None else params
        )
    else:
        result = action + ' request ignored'

    notice = result.get('message', '') if isinstance(result, dict) else str(result)
    if notice:
        log_output('Local', 'Web portal', {'log': notice, 'force': True}, 'INFO')
    return result


def query_value(path, key, default=''):
    return parse_query(path).get(key, default)


def is_client_disconnect_error(exc):
    args = getattr(exc, 'args', ())
    if args and args[0] in (-29312, -30592):
        return True
    detail = str(exc)
    return (
        'MBEDTLS_ERR_SSL_CONN_EOF' in detail or
        'MBEDTLS_ERR_SSL_BAD_PROTOCOL_VERSION' in detail or
        'MBEDTLS_ERR_SSL_FATAL_ALERT_MESSAGE' in detail
    )


def response(status, body, content_type='text/html'):
    return (
        'HTTP/1.1 ' + status + '\r\n'
        'Content-Type: ' + content_type + '\r\n'
        'Cache-Control: no-store\r\n'
        'Connection: close\r\n'
        'Content-Length: ' + str(len(body.encode())) + '\r\n'
        '\r\n' +
        body
    )


def download_response(body, filename='ha-device-logs.txt'):
    return (
        'HTTP/1.1 200 OK\r\n'
        'Content-Type: text/plain; charset=utf-8\r\n'
        'Content-Disposition: attachment; filename="' + filename + '"\r\n'
        'Cache-Control: no-store\r\n'
        'Connection: close\r\n'
        'Content-Length: ' + str(len(body.encode())) + '\r\n'
        '\r\n' +
        body
    )


async def write_buffered_response(
    writer,
    status,
    body,
    content_type='text/html; charset=utf-8',
    extra_headers=None
):
    """Send one encoded response, favouring throughput over minimum heap use."""
    body_bytes = str(body).encode()
    extra_headers = http_support.add_security_headers(extra_headers or ())
    supplied_cache_control = any(
        str(name).lower() == 'cache-control'
        for name, _value in extra_headers
    )
    headers = (
        'HTTP/1.1 ' + status + '\r\n'
        'Content-Type: ' + content_type + '\r\n'
        + ('' if supplied_cache_control else 'Cache-Control: no-store\r\n') +
        'Connection: close\r\n'
        'Content-Length: ' + str(len(body_bytes)) + '\r\n'
    )
    for name, value in extra_headers:
        headers += str(name) + ': ' + str(value) + '\r\n'
    writer.write((headers + '\r\n').encode() + body_bytes)
    await writer.drain()


def redirect(location):
    body = 'Redirecting'
    return (
        'HTTP/1.1 303 See Other\r\n'
        'Location: ' + location + '\r\n'
        'Cache-Control: no-store\r\n'
        'Connection: close\r\n'
        'Content-Length: ' + str(len(body.encode())) + '\r\n'
        '\r\n' +
        body
    )


def render_log_text(logs):
    return '\n'.join(str(line) for line in logs)


def render_logs_html(logs):
    return '\n'.join(html_escape(line) for line in logs)


FRIENDLY_LABELS = {
    'device_name': 'Device name',
    'wifi_ip': 'Wi-Fi address',
    'mqtt': 'MQTT status',
    'config': 'Configuration',
    'loglevel': 'Log level',
    'uptime_s': 'Uptime (s)',
    'discovery_count': 'HA discovery count',
    'update_status': 'Update status',
    'update_version': 'Staged version',
    'running_version': 'Application version',
    'base_version': 'MicroPython version',
    'platform': 'Platform',
    'runtime_version': 'MicroPython version',
    'firmware_update_availability': 'OTA firmware availability',
    'heap_free_bytes': 'Free heap (bytes)',
    'heap_allocated_bytes': 'Allocated heap (bytes)',
    'storage_free_bytes': 'Free storage (bytes)',
    'storage_total_bytes': 'Total storage (bytes)',
    'active_slot': 'Active app slot',
    'previous_slot': 'Previous app slot',
    'recovery_api': 'Recovery API',
    'signed_updates': 'Signed updates',
    'release_channel': 'Release channel',
    'release_available_version': 'Available release',
    'release_check_status': 'Release check',
    'module_last_ok': 'Last operation OK',
    'module_last_error': 'Last error',
    'module_last_read_ms': 'Read duration (ms)',
    'module_last_publish_age_s': 'HA publish age (s)',
    'module_consecutive_errors': 'Consecutive errors',
    'rs485_last_ok': 'RS485 last request OK',
    'rs485_last_operation': 'RS485 last operation',
    'rs485_last_address': 'RS485 last address',
    'rs485_last_error': 'RS485 last error',
    'rs485_last_latency_ms': 'RS485 latency (ms)',
    'ems_last_ok': 'EMS last frame OK',
    'ems_last_type': 'EMS last frame type',
    'ems_last_src': 'EMS last source',
    'ems_last_error': 'EMS last error',
    'ems_frames': 'Valid EMS frames',
    'ems_crc_errors': 'EMS CRC errors',
    'ems_breaks': 'Detected EMS breaks',
    'ems_rx_overflows': 'EMS receive overflows',
    'ems_bus_protocol': 'Detected EMS bus protocol',
    'adc_rms': 'ADC RMS',
    'adc_midpoint': 'ADC midpoint',
    'adc_min': 'ADC minimum',
    'adc_max': 'ADC maximum',
    'ac_voltage_error': 'AC voltage error',
    'rtd_raw': 'RTD raw value',
    'fault_code': 'Fault code'
}


def friendly_label(key):
    key = str(key)
    if key in FRIENDLY_LABELS:
        return FRIENDLY_LABELS[key]
    if key.startswith('module_'):
        key = key[len('module_'):]
    return key.replace('_', ' ').replace('.', ' ')


def render_label(key):
    return html_escape(friendly_label(key))


def render_badge(label, tone='neutral'):
    return '<span class="badge ' + html_escape(tone) + '">' + html_escape(label) + '</span>'


DIAGNOSTIC_HELP = {
    'module_last_ok': 'Whether the most recent operation completed successfully.',
    'module_last_error': 'Last operation error. Empty means no current error is recorded.',
    'module_last_read_ms': 'How long the most recent read took, in milliseconds. Some event-driven modules do not use this value.',
    'module_last_publish_age_s': 'Seconds since state was last published to Home Assistant over MQTT.',
    'module_consecutive_errors': 'Number of failed operations since the last successful operation.',
    'rs485_last_ok': 'Whether the most recent RS485 request completed successfully.',
    'rs485_last_operation': 'Operation type for the most recent RS485 request.',
    'rs485_last_address': 'Register address used by the most recent RS485 request.',
    'rs485_last_error': 'Last RS485 request error. Empty means no current error is recorded.',
    'rs485_last_latency_ms': 'How long the most recent RS485 request took, in milliseconds.',
}


def diagnostic_help(key):
    return DIAGNOSTIC_HELP.get(key, 'Diagnostic value for module troubleshooting.')


def render_refresh_controls_html(button_id='refresh-toggle', refresh_scope='log and value'):
    return (
        '<div class="refresh-controls">' +
        '<span class="badge good refresh-status">auto refresh</span>' +
        '<button id="' + html_escape(button_id) + '" class="secondary compact refresh-toggle" type="button" ' +
        'title="Pause or resume ' + html_escape(refresh_scope) + ' auto refresh.">Pause</button>' +
        '</div>'
    )


def staged_version_text(status):
    application = str(status.get('update_version', '') or '')
    firmware = str(status.get('firmware_update_version', '') or '')
    application_ready = status.get('update_status') == 'ready' and application
    firmware_ready = status.get('firmware_update_status') == 'ready' and firmware
    if application_ready and firmware_ready:
        return 'App ' + application + ' / Firmware ' + firmware
    if firmware_ready:
        return firmware
    if application_ready:
        return application
    return 'Not staged'


def combined_update_status_text(status):
    application = str(status.get('update_status', 'idle') or 'idle')
    firmware = str(status.get('firmware_update_status', 'idle') or 'idle')
    active = []
    if application != 'idle':
        active.append(('App', application))
    if firmware != 'idle':
        active.append(('Firmware', firmware))
    if not active:
        return 'idle'
    if len(active) == 1:
        return active[0][1]
    if active[0][1] == active[1][1]:
        return active[0][1]
    return active[0][0] + ' ' + active[0][1] + ' / ' + active[1][0] + ' ' + active[1][1]


def render_status_html(status):
    if not status:
        return ''

    cards = []
    for key in (
        'device_name', 'wifi_ip', 'mqtt', 'config', 'loglevel', 'uptime_s',
        'discovery_count', 'heap_free_bytes', 'heap_allocated_bytes',
        'storage_free_bytes', 'active_slot', 'recovery_api', 'signed_updates'
    ):
        if key in status:
            value = status[key]
            tone = ''
            if key == 'mqtt':
                tone = ' good' if str(value).lower() == 'up' else ' warn'
            if key == 'config':
                tone += ' wide'
            cards.append(
                '<div class="metric' + tone + '"><span>' + render_label(key) +
                '</span><strong title="' + html_escape(value) + '">' + html_escape(value) + '</strong></div>'
            )
    for key in ('running_version', 'base_version'):
        if key in status:
            value = status[key]
            version_class = {
                'running_version': ' version-app',
                'base_version': ' version-base'
            }[key]
            cards.append(
                '<div class="metric' + version_class + '"><span>' + render_label(key) +
                '</span><strong title="' + html_escape(value) + '">' + html_escape(value) + '</strong></div>'
            )
    return (
        '<section class="panel"><div class="section-title"><h2>Status</h2>' +
        render_refresh_controls_html() + '</div><div class="metrics">' +
        ''.join(cards) + '</div></section>'
    )


def render_state_parts(state):
    if not state:
        return ('<p class="muted">No state yet.</p>',)

    parts = ['<div class="state-grid">']
    for key in state:
        parts.append(
            '<div class="state-row"><span>' + render_label(key) +
            '</span><strong>' + html_escape(state[key]) + '</strong></div>'
        )
    parts.append('</div>')
    return parts


def render_state_html(state):
    return ''.join(render_state_parts(state))


def render_diagnostics_parts(diagnostics):
    if not diagnostics:
        return ()

    parts = ['<div class="diag-tile"><div class="diag-title">Diagnostics</div><div class="diag-grid">']
    for key in diagnostics:
        parts.append(
            '<div class="diag-row" title="' + html_escape(diagnostic_help(key)) + '"><span>' + render_label(key) +
            '</span><strong>' + html_escape(diagnostics[key]) + '</strong></div>'
        )
    parts.append('</div></div>')
    return parts


def render_diagnostics_html(diagnostics):
    return ''.join(render_diagnostics_parts(diagnostics))


def render_module_health_badge(diagnostics):
    diagnostics = diagnostics or {}
    healthy = diagnostics.get('module_last_ok', diagnostics.get('last_ok'))
    if module_diagnostics_need_attention(diagnostics):
        return render_badge('attention', 'warn')
    if healthy is True:
        return render_badge('healthy', 'good')
    return render_badge('active', 'neutral')


def render_modules_parts(modules, token):
    if not modules:
        return ('<section class="panel"><div class="section-title"><h2>Modules</h2>' + render_badge('0 loaded') + '</div><p class="muted">No modules loaded.</p></section>',)

    parts = [
        '<section class="panel"><div class="section-title"><h2>Modules</h2>' +
        render_badge(str(len(modules)) + ' loaded') + '</div><div class="module-grid">'
    ]
    for module in modules:
        diagnostics = module.get('diagnostics', module.get('health', {}))
        state = module.get('state', {})
        last_error = diagnostics.get('module_last_error', diagnostics.get('last_error', ''))
        health_badge = render_module_health_badge(diagnostics)
        error_html = ''
        if last_error:
            error_html = '<p class="error-text">' + html_escape(last_error) + '</p>'

        calibration = ''
        if module.get('calibratable'):
            calibration = (
                '<form class="calibration-form" action="/calibrate" method="post">' +
                '<input type="hidden" name="csrf" value="' + html_escape(token) + '">' +
                '<input type="hidden" name="uuid" value="' + html_escape(module.get('uuid', '')) + '">' +
                '<label title="Enter the voltage measured with a trusted meter.">Known voltage ' +
                '<input name="known_voltage" inputmode="decimal" size="6" placeholder="240" title="Voltage currently measured at the sensor input."></label>' +
                '<button type="submit" title="Calculate a new in-memory calibration multiplier for this module.">Calibrate</button></form>'
            )

        debug_frames = ''
        if module.get('debug_frames') is not None:
            enabled = bool(module.get('debug_frames'))
            next_value = 'false' if enabled else 'true'
            label = 'Disable debug frames' if enabled else 'Enable debug frames'
            debug_frames = (
                '<form class="calibration-form" action="/ems-debug" method="post">' +
                '<input type="hidden" name="csrf" value="' + html_escape(token) + '">' +
                '<input type="hidden" name="uuid" value="' + html_escape(module.get('uuid', '')) + '">' +
                '<input type="hidden" name="enabled" value="' + next_value + '">' +
                '<button type="submit" title="Enable or disable verbose EMS UART frame logging.">' +
                label + '</button></form>'
            )

        parts.append(
            '<article class="module-card"><div class="module-head"><div>' +
            '<h3>' + html_escape(module.get('name', '')) + '</h3>' +
            '<p>' + html_escape(module.get('type', '')) + ' / ' + html_escape(module.get('uuid', '')) + '</p>' +
            '</div>' + health_badge + '</div>' +
            error_html
        )
        parts.extend(render_state_parts(state))
        parts.extend(render_diagnostics_parts(diagnostics))
        if calibration:
            parts.append(calibration)
        if debug_frames:
            parts.append(debug_frames)
        parts.append('</article>')

    parts.append('</div></section>')
    return parts


def render_modules_html(modules, token):
    return ''.join(render_modules_parts(modules, token))


def render_live_sections_parts(status, modules, token):
    parts = ['<div id="live-sections">', render_status_html(status or {})]
    parts.extend(render_modules_parts(modules or [], token))
    parts.append('</div>')
    return parts


def render_live_sections_html(status, modules, token):
    return ''.join(render_live_sections_parts(status, modules, token))


def render_update_summary_html(status):
    status = status or {}
    staged = staged_version_text(status)
    update_status = combined_update_status_text(status)
    availability = str(
        status.get('firmware_update_availability', 'Unknown') or 'Unknown'
    )
    availability_tone = ' good' if availability.lower() == 'ready' else ' warn'
    release_status = str(
        status.get('release_check_status', 'Not checked') or 'Not checked'
    )
    release_checked = str(status.get('release_last_checked', '') or '')
    release_text = release_status + (
        ' — ' + release_checked if release_checked else ''
    )
    release_tone = (
        ' warn' if release_status.lower().startswith('check failed') else
        (' good' if release_status not in ('Not checked', 'Checking') else '')
    )
    history = status.get('update_history', [])
    history_html = ''
    if history:
        rows = []
        for entry in list(history)[-5:][::-1]:
            rows.append(
                '<li><strong>' + html_escape(entry.get('event', '')) + '</strong> ' +
                html_escape(entry.get('kind', '')) + ' ' +
                html_escape(entry.get('version', '')) +
                (' — ' + html_escape(entry.get('detail', '')) if entry.get('detail') else '') +
                '</li>'
            )
        history_html = '<details class="update-history"><summary>Recent update history</summary><ul>' + ''.join(rows) + '</ul></details>'
    return (
        '<div id="update-summary" class="update-summary">' +
        '<div class="metric update-staged"><span>' + render_label('update_version') +
        '</span><strong title="' + html_escape(staged) + '">' + html_escape(staged) + '</strong></div>' +
        '<div class="metric update-status"><span>' + render_label('update_status') +
        '</span><strong title="' + html_escape(update_status) + '">' + html_escape(update_status) + '</strong></div>' +
        '<div class="metric ota-availability' + availability_tone + '"><span>' +
        render_label('firmware_update_availability') + '</span><strong title="' +
        html_escape(availability) + '">' + html_escape(availability) + '</strong></div>' +
        '<div class="metric release-check' + release_tone + '"><span>' +
        render_label('release_check_status') + '</span><strong title="' +
        html_escape(release_text) + '">' + html_escape(release_text) + '</strong></div>' +
        history_html +
        ('<p class="muted">Available ' + html_escape(status.get('release_available_type', '')) +
         ' release: ' + html_escape(status.get('release_available_version', '')) + '</p>'
         if status.get('release_available_version') else '') + '</div>'
    )


def render_update_activation_html(status, token):
    if not status or status.get('update_status') != 'ready':
        return ''

    labels = {
        'module_settings': 'Module settings',
        'certificates': 'Certificates'
    }
    option_html = []
    available = status.get('update_options', ())
    for key in ('module_settings', 'certificates'):
        if key in available:
            option_html.append(
                '<label class="update-switch"><input name="' + key +
                '" type="checkbox" value="true"><span>' + labels[key] + '</span></label>'
            )
    options = ''
    if option_html:
        options = (
            '<span class="update-options"><span class="update-options-label">Application update options:</span>' +
            ''.join(option_html) + '</span>'
        )
    return (
        '<form action="/activate-update" method="post" class="update-activate">' +
        '<input type="hidden" name="csrf" value="' + html_escape(token) + '">' +
        options +
        '<button class="secondary" type="submit" title="Apply the selected overwrite options and reboot into the staged update. The previous application is retained for rollback.">Activate and reboot</button>' +
        '</form>'
    )


def render_firmware_update_html(status, token):
    if not status or not status.get('firmware_update_supported'):
        return ''
    update_status = status.get('firmware_update_status', 'idle')
    if update_status == 'ready':
        return (
            '<form action="/activate-firmware" method="post">' +
            '<input type="hidden" name="csrf" value="' + html_escape(token) + '">' +
            '<button class="secondary" type="submit" title="Boot the verified inactive firmware partition and require a healthy startup confirmation.">Activate firmware and reboot</button>' +
            '</form>'
        )
    return ''


def render_application_rollback_html(status, token):
    if not status or not status.get('previous_slot'):
        return ''
    version = status.get('previous_slot_version', '')
    return (
        '<form action="/rollback-application" method="post">' +
        '<input type="hidden" name="csrf" value="' + html_escape(token) + '">' +
        '<button class="secondary" type="submit" title="Select the retained previous application slot and reboot.">Rollback application' +
        (' to ' + html_escape(version) if version else '') + '</button></form>'
    )


def render_release_check_html(status, token):
    if not status or not status.get('release_checks_enabled'):
        return ''
    available = status.get('release_available_version', '')
    download = ''
    if available:
        notes = status.get('release_available_notes', '')
        release_type = str(status.get('release_available_type', ''))
        release_type = release_type[:1].upper() + release_type[1:]
        download = (
            '<div class="release-available"><p><strong>' +
            html_escape(release_type) + ' ' +
            html_escape(available) + '</strong>' +
            (' — ' + html_escape(notes) if notes else '') + '</p>' +
            '<form action="/download-release" method="post">' +
            '<input type="hidden" name="csrf" value="' + html_escape(token) + '">' +
            '<button class="secondary" type="submit" title="Download the signed release, verify its descriptor and bundle, then stage it for activation.">Download and verify</button>' +
            '</form></div>'
        )
    check = (
        '<form action="/check-release" method="post">' +
        '<input type="hidden" name="csrf" value="' + html_escape(token) + '">' +
        '<button class="secondary" type="submit" title="Check the configured signed release channel now.">'
        'Check for updates</button></form>'
    )
    return check + download


def render_update_actions_html(status, token):
    activation = (
        render_update_activation_html(status, token) +
        render_firmware_update_html(status, token)
    )
    return (
        '<div id="update-actions" class="update-actions">' +
        activation + render_release_check_html(status, token) +
        render_application_rollback_html(status, token) +
        '</div>'
    )


def render_overview_status(status):
    status = status or {}
    keys = (
        ('device_name', 'Device'),
        ('wifi_ip', 'Wi-Fi address'),
        ('mqtt', 'MQTT'),
        ('uptime_s', 'Uptime (s)'),
        ('running_version', 'Application version'),
        ('firmware_running_version', 'Core version'),
        ('base_version', 'MicroPython version'),
    )
    values = []
    for key, label in keys:
        value = status.get(key, 'unknown')
        tone = ''
        if key == 'mqtt':
            lowered = str(value).lower()
            tone = ' good' if lowered in ('connected', 'up', 'online') else (
                '' if lowered == 'not configured' else ' warn'
            )
        values.append(
            '<div class="metric' + tone + '"><span>' + label +
            '</span><strong>' + html_escape(value) + '</strong></div>'
        )
    return '<div id="overview-status" class="metrics">' + ''.join(values) + '</div>'


def render_overview_modules(modules):
    cards = []
    for module in modules or []:
        diagnostics = module.get('diagnostics', {})
        error = diagnostics.get('module_last_error', '')
        badge = render_module_health_badge(diagnostics)
        state = module.get('state', {})
        published = []
        for key in state:
            published.append(
                '<div class="published-tile"><span>' + render_label(key) +
                '</span><strong>' + html_escape(state[key]) + '</strong></div>'
            )
        published_html = (
            '<div class="published-title">MQTT-published values</div>'
            '<div class="published-grid">' + ''.join(published) + '</div>'
            if published else '<p class="muted">No MQTT-published values yet.</p>'
        )
        cards.append(
            '<article class="module-card"><div class="module-head"><div><h3>' +
            html_escape(module.get('name', module.get('uuid', 'Module'))) +
            '</h3><p class="muted">' + html_escape(module.get('type', '')) +
            '</p></div>' + badge + '</div>' +
            ('<p class="error-text">' + html_escape(error) + '</p>' if error else '') +
            published_html + '</article>'
        )
    if not cards:
        cards.append(
            '<p class="muted">No modules are configured. Use the Modules page to add them.</p>'
        )
    return '<div id="overview-modules" class="module-grid">' + ''.join(cards) + '</div>'


def render_overview_page(token, status=None, modules=None, value_refresh_ms=5000):
    body = (
        portal_ui.page_heading(
            'Status', 'Overview',
            'Current connectivity, software versions and MQTT-published module values.'
        ) +
        '<section class="card"><div class="section-title"><h2>Device</h2>'
        '<span class="badge good" id="overview-refresh">live</span></div>' +
        render_overview_status(status) + '</section>'
        '<section class="card"><div class="section-title"><h2>Modules</h2>'
        '<a href="/module-settings">Configure modules</a></div>' +
        render_overview_modules(modules) + '</section>'
    )
    interval = max(1000, int(value_refresh_ms or 5000))
    script = (
        'function refreshOverview(){fetch("/api/overview",{cache:"no-store",credentials:"same-origin"})'
        '.then(function(r){if(r.status===401){location.replace("/login");return null;}return r.json();})'
        '.then(function(p){if(!p)return;document.getElementById("overview-status").outerHTML=p.status;'
        'document.getElementById("overview-modules").outerHTML=p.modules;})'
        '.catch(function(){});}setInterval(refreshOverview,' + str(interval) + ');'
    )
    return portal_ui.shell('HAMD overview', 'overview', body, token, script)


def render_logging_page(token, current_loglevel, levels, logs,
                        log_refresh_ms=5000):
    options = ''.join(
        '<option value="' + level + '"' +
        (' selected' if level == current_loglevel else '') + '>' + level + '</option>'
        for level in levels
    )
    body = (
        portal_ui.page_heading(
            'Maintenance', 'Logging',
            'Review live device logs and adjust runtime verbosity.'
        ) +
        '<section class="card"><div class="section-title"><h2>Logs</h2>'
        '<div class="actions"><a class="button secondary compact" href="/download-logs">'
        'Download logs</a>' + render_refresh_controls_html(
            'log-refresh-toggle', 'log'
        ) + '</div></div>'
        '<form action="/set-loglevel" method="post" class="log-toolbar">'
        '<input type="hidden" name="csrf" value="' + html_escape(token) + '">'
        '<label>Log level <select name="level">' + options + '</select></label>'
        '<button class="secondary" type="submit">Apply</button></form>'
        '<pre id="logs" class="log-view">' + render_logs_html(logs or []) + '</pre></section>'
    )
    interval = max(1000, int(log_refresh_ms or 5000))
    script = (
        'var logRefreshPaused=false,logRefreshButton=document.getElementById("log-refresh-toggle"),'
        'logRefreshState=document.querySelector(".refresh-status");'
        'function updateLogRefresh(){logRefreshButton.textContent=logRefreshPaused?"Resume":"Pause";'
        'logRefreshState.textContent=logRefreshPaused?"refresh paused":"auto refresh";'
        'logRefreshState.className=logRefreshPaused?"badge warn refresh-status":"badge good refresh-status";}'
        'logRefreshButton.onclick=function(){logRefreshPaused=!logRefreshPaused;updateLogRefresh();'
        'if(!logRefreshPaused)refreshLogs();};'
        'function nearBottom(e){return e.scrollHeight-e.scrollTop-e.clientHeight<48;}'
        'function refreshLogs(){if(logRefreshPaused)return;var e=document.getElementById("logs"),b=nearBottom(e);'
        'fetch("/logs",{cache:"no-store",credentials:"same-origin"}).then(function(r){'
        'if(r.status===401){location.replace("/login");return null;}return r.text();}).then(function(t){'
        'if(t!==null&&t!==undefined&&e.textContent!==t){e.textContent=t;if(b)e.scrollTop=e.scrollHeight;}})'
        '.catch(function(){});}setInterval(refreshLogs,' + str(interval) + ');updateLogRefresh();'
    )
    return portal_ui.shell('HAMD logging', 'logging', body, token, script)


def render_module_diagnostics_page(token, modules, value_refresh_ms=5000):
    body = (
        portal_ui.page_heading(
            'Module', 'Diagnostics',
            'Review live values, health information and controls for loaded modules.',
            '<a class="button secondary" href="/download-diagnostics">Download diagnostics</a>'
        ) +
        '<div id="module-diagnostics">' +
        render_modules_html(modules or [], token) + '</div>'
    )
    interval = max(1000, int(value_refresh_ms or 5000))
    script = (
        'function refreshModuleDiagnostics(){fetch("/api/module-diagnostics",'
        '{cache:"no-store",credentials:"same-origin"}).then(function(r){'
        'if(r.status===401){location.replace("/login");return null;}return r.json();})'
        '.then(function(p){if(!p)return;document.getElementById("module-diagnostics").innerHTML='
        'p.modules;}).catch(function(){});}setInterval(refreshModuleDiagnostics,' +
        str(interval) + ');'
    )
    return portal_ui.shell(
        'HAMD module diagnostics', 'module_diagnostics', body, token, script
    )


def render_update_preferences(csrf, settings):
    settings = settings or {}
    channel = settings.get('release_channel', 'stable')
    download = ' checked' if settings.get('release_auto_download') else ''
    activate = ' checked' if settings.get('release_auto_activate') else ''
    return (
        '<form action="/update-preferences" method="post"><input type="hidden" name="csrf" value="' +
        html_escape(csrf) + '"><div class="grid"><label class="field">Release channel<select '
        'name="release_channel"><option value="stable"' +
        (' selected' if channel == 'stable' else '') + '>Stable</option><option value="beta"' +
        (' selected' if channel == 'beta' else '') + '>Beta</option></select></label></div>'
        '<label class="check"><input type="checkbox" name="release_auto_download"' + download +
        '>Automatically download applicable signed releases</label>'
        '<label class="check"><input type="checkbox" name="release_auto_activate"' + activate +
        '>Automatically activate verified releases</label>'
        '<div class="actions"><span></span><button class="secondary" type="submit">'
        'Save update preferences</button></div></form>'
    )


def update_upload_script():
    return (
        'var csrfToken=document.getElementById("update-upload-form").dataset.csrf;'
        'document.getElementById("update-bundle").onchange=function(){document.getElementById('
        '"update-file-name").textContent=this.files&&this.files[0]?this.files[0].name:"No file selected";};'
        'document.getElementById("update-upload-form").onsubmit=function(e){e.preventDefault();var input='
        'document.getElementById("update-bundle"),f=input.files&&input.files[0],out=document.getElementById('
        '"update-result"),box=document.getElementById("update-progress"),'
        'label=box.querySelector(".status-text");if(!f)return;var firmware=/\\.hamf$/i.test(f.name),application=/\\.hamd$/i.test(f.name);'
        'if(!firmware&&!application){out.textContent="Choose a .hamd or .hamf update bundle.";return;}'
        'box.classList.remove("complete","failed");box.hidden=false;label.textContent="Uploading 0%";out.textContent="Uploading…";'
        'var id=Date.now().toString(36)+"-"+Math.random().toString(36).slice(2),x=new XMLHttpRequest(),'
        'polling=false,timer=null;function poll(){fetch("/update-progress?id="+encodeURIComponent(id),'
        '{cache:"no-store",credentials:"same-origin"}).then(function(r){if(r.status===401){location.replace('
        '"/login");return null;}return r.json();}).then(function(s){if(!s)return;if(s.phase==="verification"){'
        'label.textContent="Verifying "+(s.percent||0)+"%";out.textContent="Verifying on device…";}'
        'else if(s.phase==="complete"){box.classList.add("complete");label.textContent="Verified";out.textContent=s.message||'
        '"Update staged";setTimeout(function(){location.replace("/updates");},700);return;}else if(s.phase==="failed"){'
        'box.classList.add("failed");label.textContent="Failed";out.textContent=s.message||"Verification failed";return;}'
        'timer=setTimeout(poll,500);}).catch(function(){timer=setTimeout(poll,1000);});}'
        'x.open("POST",firmware?"/firmware-upload":"/update-upload",true);x.setRequestHeader("Content-Type",'
        '"application/octet-stream");x.setRequestHeader("X-CSRF-Token",csrfToken);x.setRequestHeader("X-Update-ID",id);'
        'x.upload.onprogress=function(p){if(!p.lengthComputable)return;var n=Math.round(p.loaded*100/p.total);'
        'label.textContent="Uploading "+n+"%";};x.upload.onload=function(){'
        'label.textContent="Verifying…";out.textContent="Upload complete; verifying…";};x.onload=function(){'
        'if(x.status===401){location.replace("/login");return;}if(x.status===202){polling=true;poll();return;}'
        'if(x.status>=200&&x.status<300){box.classList.add("complete");label.textContent="Verified";out.textContent=x.responseText;'
        'setTimeout(function(){location.replace("/updates");},700);}else{box.classList.add("failed");label.textContent="Failed";'
        'out.textContent=x.responseText||"Upload failed";}};x.onerror=function(){box.classList.add("failed");label.textContent="Failed";'
        'out.textContent="Connection lost during upload";};x.send(f);};'
    )


def render_updates_page(token, status=None, settings=None, message='', error=False):
    status = status or {}
    activation = (
        render_update_activation_html(status, token) +
        render_firmware_update_html(status, token)
    )
    automatic_action = render_release_check_html(status, token) + activation
    if activation:
        manual_content = (
            '<p class="muted">The uploaded or downloaded bundle has been verified and is ready.</p>'
            '<div class="update-actions">' + activation + '</div>'
        )
        script = ''
    else:
        manual_content = (
            '<form id="update-upload-form" data-csrf="' + html_escape(token) + '">'
            '<div class="actions"><span><input id="update-bundle" class="file-input-hidden" type="file" '
            'accept=".hamd,.hamf"><label class="button secondary file-button" for="update-bundle">'
            'Choose update file</label> <span id="update-file-name" class="file-name">No file selected</span></span>'
            '<button type="submit">Upload and verify</button></div></form>' +
            portal_ui.progress('update-progress', '0%', True) +
            '<p id="update-result" class="muted">Application bundles use .hamd; core firmware uses .hamf.</p>'
        )
        script = update_upload_script()
    body = (
        portal_ui.page_heading(
            'Maintenance', 'Upgrades',
            'Check, upload, verify and activate signed application or core firmware releases.'
        ) + _notice(message, error) +
        '<section class="card"><div class="section-title"><h2>Versions and update state</h2></div>' +
        render_update_summary_html(status) + '<div class="update-actions">' +
        render_application_rollback_html(status, token) + '</div></section>'
        '<div class="upgrade-grid"><section class="card"><div class="section-title">'
        '<h2>Automatic upgrade</h2></div><p class="muted">Use the signed release channel and '
        'automatic download and activation preferences.</p>' +
        render_update_preferences(token, settings) + '<div class="update-actions">' +
        automatic_action + '</div></section>'
        '<section class="card"><div class="section-title"><h2>Manual upgrade</h2></div>' +
        manual_content + '</section></div>'
    )
    return portal_ui.shell(
        'HAMD upgrades', 'updates', body, token, script
    )


def render_page_parts(token, current_loglevel, levels, logs=None, log_refresh_ms=5000,
                      status=None, modules=None, notice='', value_refresh_ms=0):
    return [render_overview_page(
        token, status or {}, modules or [], value_refresh_ms or 5000
    )]

def render_page(token, current_loglevel, levels, logs=None, log_refresh_ms=5000, status=None, modules=None, notice='', value_refresh_ms=0):
    return render_overview_page(
        token, status or {}, modules or [], value_refresh_ms or 5000
    )


def make_tls_context(cert_path, key_path):
    if ssl is None:
        raise RuntimeError('ssl module not available')

    for path, label in ((cert_path, 'certificate'), (key_path, 'private key')):
        try:
            with open(path, 'rb'):
                pass
        except Exception as exc:
            raise RuntimeError('HTTPS ' + label + ' file not found or unreadable: ' + str(path) + ' - ' + str(exc))

    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    try:
        context.load_cert_chain(cert_path, key_path)
    except Exception as exc:
        detail = str(exc)
        if 'invalid key' in detail:
            detail += ' - regenerate the HTTPS key as a traditional RSA key or convert the cert/key to DER for this MicroPython build.'
        raise RuntimeError('Could not load HTTPS certificate/key: ' + detail)
    return context


async def start_web_portal(
    settings, log_getter, loglevel_getter, loglevel_setter, log_output,
    status_getter=None, module_getter=None, action_handler=None,
    upload_handler=None, firmware_upload_handler=None, config_backup_getter=None,
    settings_getter=None, settings_setter=None, module_settings_getter=None,
    module_settings_setter=None, certificate_upload_handler=None,
    certificate_validate_handler=None, update_preferences_setter=None,
    task_status_getter=None, certificate_info_getter=None,
    network_trial_confirmer=None, factory_reset_handler=None
):
    if asyncio is None:
        return None

    username = settings.get('username', 'admin') or 'admin'
    password_verifier = settings.get('password_verifier', '')
    password_change_required = bool(settings.get('password_change_required', False))
    password_setter = settings.get('password_setter')
    if not isinstance(username, str):
        raise ValueError('web portal username must be text')
    try:
        import credential_security
        credential_security.parse_password_verifier(password_verifier)
    except ValueError as exc:
        raise ValueError('web portal password verifier is invalid: ' + str(exc))
    levels = settings.get('levels', ('ERROR', 'INFO', 'DEBUG'))
    log_refresh_ms = settings.get('log_refresh_ms', 5000)
    value_refresh_ms = settings.get('value_refresh_ms', 0)
    upload_progress = {'phase': 'idle', 'percent': 0}
    upload_progress_by_id = {}
    session_id = new_session_id()
    session_started = monotonic_ms()
    session_timeout_ms = int(settings.get('session_timeout_s', 28800)) * 1000
    login_failures = 0
    cached_page = {'level': None, 'body': None}
    secure_cookie = settings.get('https', False)
    cookie = session_cookie(session_id, secure_cookie)
    login_url = settings.get('login_url', '/login')

    async def send_response(writer, status, body, content_type='text/html; charset=utf-8', extra_headers=None):
        await write_buffered_response(writer, status, body, content_type, extra_headers)

    async def send_redirect(writer, location, extra_headers=None):
        headers = [('Location', location)]
        if extra_headers:
            headers.extend(extra_headers)
        await send_response(
            writer,
            '303 See Other',
            'Redirecting',
            'text/plain',
            tuple(headers)
        )

    async def handle_client(reader, writer):
        nonlocal session_id, session_started, cookie, login_failures
        nonlocal password_verifier, password_change_required
        path = ''
        upload_state = ''
        progress_response_started = False
        progress_percent = -1
        progress_id = ''
        progress_record = upload_progress

        async def report_upload_progress(phase, completed=0, total=0):
            nonlocal progress_response_started, progress_percent
            if phase != 'verification':
                return
            total = int(total or 0)
            completed = int(completed or 0)
            percent = int(completed * 100 / total) if total > 0 else 0
            percent = max(0, min(100, percent))
            progress_record['phase'] = 'verification'
            progress_record['percent'] = percent
            if percent == progress_percent:
                return
            progress_percent = percent
            if not progress_response_started:
                progress_response_started = True
                try:
                    await send_response(
                        writer,
                        '202 Accepted',
                        json.dumps({'phase': 'verification'}),
                        'application/json'
                    )
                except Exception:
                    # Verification must not fail just because the browser closed
                    # the upload response before receiving the acknowledgement.
                    pass
                finally:
                    try:
                        writer.close()
                    except Exception:
                        pass
                if asyncio:
                    await asyncio.sleep(0)

        async def finish_progress_response(phase, message):
            progress_record['phase'] = phase
            if phase == 'complete':
                progress_record['percent'] = 100
            progress_record['message'] = str(message)
            if not progress_response_started:
                return False
            return True

        async def close_writer():
            try:
                writer.close()
                if hasattr(writer, 'wait_closed'):
                    await writer.wait_closed()
            except Exception:
                pass

        try:
            line, headers = await http_support.read_request(reader)
            if not line:
                await close_writer()
                return

            try:
                request_line = line.decode().strip()
            except Exception:
                request_line = ''

            method, path = parse_request_line(request_line)

            progress_id = headers.get('x-update-id', '')[:64]
            if progress_id:
                progress_record = upload_progress_by_id.setdefault(
                    progress_id, {'phase': 'idle', 'percent': 0}
                )
                if len(upload_progress_by_id) > 8:
                    for old_id in list(upload_progress_by_id)[:-8]:
                        upload_progress_by_id.pop(old_id, None)

            action_path = path or ''
            route = action_path.split('?', 1)[0]
            is_login = route == '/login'
            is_password_change = (
                route == '/user' and
                parse_query(action_path).get('action', '') == 'password'
            )
            is_settings = route == '/settings'
            is_portal_settings = route == '/portal-settings'
            is_wifi_settings = route == '/wifi-settings'
            is_ntp_settings = route == '/ntp-settings'
            is_mqtt = route == '/mqtt'
            is_home_assistant = route == '/home-assistant'
            is_user_settings = route == '/user'
            is_operational_settings = (
                is_settings or is_portal_settings or is_wifi_settings or
                is_ntp_settings or is_mqtt or is_home_assistant or is_user_settings
            )
            is_module_settings = route == '/module-settings'
            is_certificates = route == '/certificates'
            is_updates = route == '/updates'
            is_diagnostics = route == '/diagnostics'
            is_logging = route == '/logging'
            is_factory_default = route == '/factory-default'
            is_asset = route in ('/assets/portal.css', '/assets/portal.js')
            csrf_error = False
            form_params = {}
            is_upload = bool(
                path and (
                    path.startswith('/update-upload') or
                    path.startswith('/firmware-upload') or
                    path.startswith('/certificate-upload')
                )
            )
            if method == 'POST' and not is_upload:
                length = int(headers.get('content-length', '0') or 0)
                is_json_validation = (
                    route == '/validate-configuration' and
                    headers.get('content-type', '').split(';', 1)[0].strip() == 'application/json'
                )
                max_form_size = 65536 if is_module_settings else (8192 if is_operational_settings else (
                    2048 if (is_login or is_password_change or is_factory_default) else 65536
                ))
                if length > max_form_size:
                    raise ValueError('portal form is too large')
                body = (
                    await http_support.read_exact_body(
                        reader, length, max_form_size
                    )
                    if length else b''
                )
                try:
                    encoded = body.decode()
                except Exception:
                    encoded = ''
                if is_json_validation:
                    form_params = {'config_json': encoded}
                elif encoded:
                    form_params = parse_query('?' + encoded)
                form_csrf = form_params.get('csrf', '')
                header_csrf = headers.get('x-csrf-token', '')
                csrf_error = False if is_login else (
                    form_csrf != session_id and header_csrf != session_id
                )
            elif method == 'POST' and is_upload:
                csrf_error = headers.get('x-csrf-token', '') != session_id

            if is_asset and method == 'GET':
                asset = (
                    portal_ui.PORTAL_CSS
                    if route.endswith('.css') else portal_ui.PORTAL_JS
                )
                await send_response(
                    writer, '200 OK', asset,
                    'text/css; charset=utf-8' if route.endswith('.css')
                    else 'application/javascript; charset=utf-8',
                    (('Cache-Control', 'no-store'),)
                )
            elif not path or method not in ('GET', 'POST'):
                body = 'Method not allowed'
                await send_response(writer, '405 Method Not Allowed', body, 'text/plain')
            elif is_login and method == 'GET':
                if (
                    has_portal_session(headers, session_id) and
                    elapsed_ms(session_started) <= session_timeout_ms
                ):
                    await send_redirect(
                        writer,
                        '/user' if password_change_required else '/'
                    )
                else:
                    await send_response(writer, '200 OK', render_login_page(username))
            elif is_login and method == 'POST':
                params = form_params
                if await credentials_match_async(
                    params.get('username', ''), params.get('password', ''),
                    username, password_verifier
                ):
                    session_id = new_session_id()
                    session_started = monotonic_ms()
                    cookie = session_cookie(session_id, secure_cookie)
                    cached_page['body'] = None
                    login_failures = 0
                    if network_trial_confirmer:
                        try:
                            network_trial_confirmer()
                        except Exception as exc:
                            log_output(
                                'Local', 'Network settings',
                                {'log': 'Could not confirm candidate settings - ' + str(exc)},
                                'ERROR'
                            )
                    await send_redirect(
                        writer,
                        '/user' if password_change_required else '/', (
                            ('Set-Cookie', cookie),
                            ('Referrer-Policy', 'no-referrer')
                        )
                    )
                else:
                    login_failures += 1
                    await asyncio.sleep(min(2, login_failures * 0.25))
                    await send_response(
                        writer, '401 Unauthorized',
                        render_login_page(username, 'Invalid username or password.')
                    )
            elif (
                not has_portal_session(headers, session_id) or
                elapsed_ms(session_started) > session_timeout_ms
            ):
                await send_response(
                    writer, '401 Unauthorized', render_login_page(username)
                )
            elif csrf_error:
                await send_response(writer, '403 Forbidden', 'Invalid CSRF token', 'text/plain')
            elif method == 'GET' and route in ('/change-password', '/user/password'):
                await send_response(writer, '404 Not Found', 'Not found', 'text/plain')
            elif method == 'POST' and route == '/logout':
                session_id = new_session_id()
                session_started = monotonic_ms()
                cookie = session_cookie(session_id, secure_cookie)
                cached_page['body'] = None
                await send_redirect(
                    writer, '/login',
                    (('Set-Cookie', session_cookie('', secure_cookie, True)),)
                )
            elif method == 'POST' and is_password_change:
                params = form_params
                current_password = params.get('current_password', '')
                new_password = params.get('new_password', '')
                confirmation = params.get('confirm_password', '')
                if not await credential_security.verify_password_async(
                    current_password, password_verifier
                ):
                    await send_response(writer, '400 Bad Request', (
                        render_password_change_page(
                            session_id, 'Current password is incorrect.', True
                        ) if password_change_required else render_user_settings_page(
                            session_id, settings_getter() if settings_getter else {},
                            password_message='Current password is incorrect.',
                            password_error=True
                        )
                    ))
                elif new_password != confirmation:
                    await send_response(writer, '400 Bad Request', (
                        render_password_change_page(
                            session_id, 'New passwords do not match.', True
                        ) if password_change_required else render_user_settings_page(
                            session_id, settings_getter() if settings_getter else {},
                            password_message='New passwords do not match.',
                            password_error=True
                        )
                    ))
                else:
                    try:
                        if password_setter is None:
                            raise RuntimeError('portal password storage is unavailable')
                        password_verifier = password_setter(new_password)
                    except Exception as exc:
                        await send_response(writer, '400 Bad Request', (
                            render_password_change_page(
                                session_id, str(exc), True
                            ) if password_change_required else render_user_settings_page(
                                session_id, settings_getter() if settings_getter else {},
                                password_message=str(exc), password_error=True
                            )
                        ))
                    else:
                        was_password_change_required = password_change_required
                        password_change_required = False
                        session_id = new_session_id()
                        session_started = monotonic_ms()
                        cookie = session_cookie(session_id, secure_cookie)
                        cached_page['body'] = None
                        log_output(
                            'Local', 'Web portal',
                            {'log': 'Portal password changed', 'force': True},
                            'INFO'
                        )
                        await send_redirect(
                            writer, '/' if was_password_change_required else '/user',
                            (('Set-Cookie', cookie),)
                        )
            elif password_change_required:
                if method == 'GET' and is_user_settings:
                    await send_response(
                        writer, '200 OK',
                        render_password_change_page(session_id, required=True)
                    )
                else:
                    await send_redirect(writer, '/user')
            elif method == 'GET' and is_factory_default:
                await send_response(
                    writer, '200 OK',
                    render_factory_default_page(session_id)
                )
            elif method == 'POST' and is_factory_default:
                current_password = form_params.get('current_password', '')
                setup_password = form_params.get('setup_password', '')
                confirmation = form_params.get('confirm_setup_password', '')
                reset_error = ''
                if not await credential_security.verify_password_async(
                    current_password, password_verifier
                ):
                    reset_error = 'Current administrator password is incorrect.'
                elif form_params.get('reset_confirmation', '') != 'RESET':
                    reset_error = 'Type RESET exactly to confirm the factory reset.'
                elif setup_password != confirmation:
                    reset_error = 'Setup Wi-Fi passwords do not match.'
                if reset_error:
                    await send_response(
                        writer, '400 Bad Request',
                        render_factory_default_page(session_id, reset_error)
                    )
                else:
                    try:
                        if factory_reset_handler is None:
                            raise RuntimeError('factory reset is unavailable')
                        factory_reset_handler(setup_password)
                    except Exception as exc:
                        await send_response(
                            writer, '400 Bad Request',
                            render_factory_default_page(session_id, str(exc))
                        )
                    else:
                        log_output(
                            'Local', 'Factory default',
                            {'log': 'Authenticated factory reset requested', 'force': True},
                            'INFO'
                        )
                        previous_session = session_id
                        session_id = new_session_id()
                        session_started = monotonic_ms()
                        cached_page['body'] = None
                        await send_response(
                            writer, '200 OK',
                            render_factory_default_complete_page(previous_session),
                            extra_headers=((
                                'Set-Cookie', session_cookie('', secure_cookie, True)
                            ),)
                        )
            elif method == 'GET' and is_operational_settings:
                if settings_getter is None:
                    await send_response(writer, '404 Not Found', 'Settings are unavailable', 'text/plain')
                else:
                    renderer = render_settings_page
                    if is_portal_settings:
                        renderer = render_portal_settings_page
                    elif is_wifi_settings:
                        renderer = render_wifi_settings_page
                    elif is_ntp_settings:
                        renderer = render_ntp_settings_page
                    elif is_mqtt:
                        renderer = render_mqtt_page
                    elif is_home_assistant:
                        renderer = render_home_assistant_page
                    elif is_user_settings:
                        renderer = render_user_settings_page
                    await send_response(
                        writer, '200 OK',
                        renderer(session_id, settings_getter())
                    )
            elif method == 'POST' and is_operational_settings:
                try:
                    if settings_setter is None:
                        raise RuntimeError('settings storage is unavailable')
                    message = settings_setter(form_params)
                    current_settings = settings_getter() if settings_getter else {}
                except Exception as exc:
                    current_settings = settings_getter() if settings_getter else {}
                    renderer = render_settings_page
                    if is_portal_settings:
                        renderer = render_portal_settings_page
                    elif is_wifi_settings:
                        renderer = render_wifi_settings_page
                    elif is_ntp_settings:
                        renderer = render_ntp_settings_page
                    elif is_mqtt:
                        renderer = render_mqtt_page
                    elif is_home_assistant:
                        renderer = render_home_assistant_page
                    elif is_user_settings:
                        renderer = render_user_settings_page
                    await send_response(
                        writer, '400 Bad Request',
                        renderer(session_id, current_settings, str(exc), True)
                    )
                else:
                    cached_page['body'] = None
                    log_output(
                        'Local', 'Web portal',
                        {'log': 'Operational settings changed', 'force': True},
                        'INFO'
                    )
                    target = login_url
                    text = message
                    if isinstance(message, dict):
                        target = message.get('login_url', target)
                        text = message.get('message', '')
                    session_id = new_session_id()
                    session_started = monotonic_ms()
                    await send_response(
                        writer, '200 OK',
                        portal_ui.restart_page(target, text),
                        extra_headers=(
                            ('Set-Cookie', session_cookie('', secure_cookie, True)),
                        )
                    )
            elif method == 'GET' and is_module_settings:
                if module_settings_getter is None:
                    await send_response(writer, '404 Not Found', 'Module settings are unavailable', 'text/plain')
                else:
                    await send_response(
                        writer, '200 OK',
                        render_module_settings_page(session_id, module_settings_getter())
                    )
            elif method == 'POST' and is_module_settings:
                submitted = form_params.get('module_settings_json', '')
                try:
                    if module_settings_setter is None:
                        raise RuntimeError('module settings storage is unavailable')
                    message = module_settings_setter(submitted)
                except Exception as exc:
                    await send_response(
                        writer, '400 Bad Request',
                        render_module_settings_page(session_id, submitted, str(exc), True)
                    )
                else:
                    log_output(
                        'Local', 'Web portal',
                        {'log': 'Module settings changed', 'force': True}, 'INFO'
                    )
                    session_id = new_session_id()
                    session_started = monotonic_ms()
                    await send_response(
                        writer, '200 OK',
                        portal_ui.restart_page(login_url, message),
                        extra_headers=(
                            ('Set-Cookie', session_cookie('', secure_cookie, True)),
                        )
                    )
            elif method == 'GET' and is_certificates:
                await send_response(
                    writer, '200 OK', render_certificate_page(
                        session_id,
                        certificates=(
                            certificate_info_getter()
                            if certificate_info_getter else {}
                        )
                    )
                )
            elif method == 'GET' and is_updates:
                automatic_check = str(
                    parse_query(action_path).get('check', '')
                ).lower() in ('1', 'true', 'yes')
                check_result = None
                if automatic_check and action_handler:
                    check_result = apply_portal_action(
                        'check-release', action_path, action_handler, log_output, {}
                    )
                if isinstance(check_result, dict) and check_result.get('task_id'):
                    await send_response(
                        writer, '202 Accepted',
                        portal_ui.task_page(
                            check_result['task_id'],
                            check_result.get('message', 'Checking for updates'),
                            '/updates'
                        )
                    )
                else:
                    await send_response(
                        writer, '200 OK',
                        render_updates_page(
                            session_id,
                            status_getter() if status_getter else {},
                            settings_getter() if settings_getter else {}
                        )
                    )
            elif method == 'GET' and is_diagnostics:
                await send_response(
                    writer, '200 OK',
                    render_module_diagnostics_page(
                        session_id,
                        module_getter() if module_getter else [],
                        value_refresh_ms or 5000
                    )
                )
            elif method == 'GET' and is_logging:
                await send_response(
                    writer, '200 OK',
                    render_logging_page(
                        session_id, loglevel_getter(), levels, log_getter(),
                        log_refresh_ms
                    )
                )
            elif method == 'POST' and route == '/update-preferences':
                try:
                    if update_preferences_setter is None:
                        raise RuntimeError('update preference storage is unavailable')
                    update_preferences_setter(form_params)
                except Exception as exc:
                    await send_response(
                        writer, '400 Bad Request',
                        render_updates_page(
                            session_id,
                            status_getter() if status_getter else {},
                            settings_getter() if settings_getter else {},
                            str(exc), True
                        )
                    )
                else:
                    await send_redirect(writer, '/updates')
            elif method == 'POST' and path.startswith('/certificate-upload'):
                if certificate_upload_handler is None:
                    await send_response(writer, '503 Service Unavailable', 'Certificate upload is unavailable', 'text/plain')
                else:
                    length = int(headers.get('content-length', '0') or 0)
                    if length <= 0 or length > 16384:
                        raise ValueError('certificate file size is invalid')
                    await certificate_upload_handler(
                        headers.get('x-certificate-kind', ''), reader, length
                    )
                    await send_response(writer, '200 OK', 'Certificate file stored', 'text/plain')
            elif method == 'POST' and route == '/validate-certificates':
                try:
                    if certificate_validate_handler is None:
                        raise RuntimeError('certificate validation is unavailable')
                    message = certificate_validate_handler()
                except Exception as exc:
                    await send_response(writer, '400 Bad Request', str(exc), 'text/plain')
                else:
                    session_id = new_session_id()
                    session_started = monotonic_ms()
                    await send_response(
                        writer, '200 OK',
                        portal_ui.restart_page(login_url, str(message)),
                        extra_headers=(
                            ('Set-Cookie', session_cookie('', secure_cookie, True)),
                        )
                    )
            elif method == 'POST' and path.startswith('/update-upload'):
                login_failures = 0
                if upload_handler is None:
                    await send_response(writer, '503 Service Unavailable', 'Application updates are unavailable', 'text/plain')
                else:
                    try:
                        length = int(headers.get('content-length', '0'))
                        upload_state = 'receiving'
                        if not progress_id:
                            raise ValueError('missing update progress identifier')
                        progress_record.clear()
                        progress_record.update({'phase': 'receiving', 'percent': 0})
                        log_output(
                            'Local', 'Application update',
                            {'log': 'Upload started - ' + str(length) + ' bytes', 'force': True},
                            'INFO'
                        )
                        params = parse_query(action_path)
                        params['_progress'] = report_upload_progress
                        result = await upload_handler(reader, length, params)
                    except Exception as exc:
                        upload_state = 'rejected'
                        try:
                            log_output(
                                'Local', 'Application update',
                                {'log': 'Upload rejected - ' + str(exc), 'force': True},
                                'ERROR'
                            )
                        except Exception:
                            pass
                        message = 'Update rejected: ' + str(exc)
                        if not await finish_progress_response('failed', message):
                            await send_response(writer, '400 Bad Request', message, 'text/plain')
                    else:
                        upload_state = 'staged'
                        log_output(
                            'Local', 'Application update',
                            {'log': 'Upload completed and staged', 'force': True},
                            'INFO'
                        )
                        if not await finish_progress_response('complete', result):
                            await send_response(writer, '200 OK', str(result), 'text/plain')
                        upload_state = 'responded'
            elif method == 'POST' and path.startswith('/firmware-upload'):
                if firmware_upload_handler is None:
                    await send_response(writer, '503 Service Unavailable', 'Base firmware updates are unavailable', 'text/plain')
                else:
                    try:
                        length = int(headers.get('content-length', '0'))
                        if not progress_id:
                            raise ValueError('missing update progress identifier')
                        progress_record.clear()
                        progress_record.update({'phase': 'receiving', 'percent': 0})
                        log_output('Local', 'Base firmware', {'log': 'Upload started - ' + str(length) + ' bytes', 'force': True}, 'INFO')
                        params = parse_query(action_path)
                        params['_progress'] = report_upload_progress
                        result = await firmware_upload_handler(reader, length, params)
                    except Exception as exc:
                        try:
                            log_output('Local', 'Base firmware', {'log': 'Upload rejected - ' + str(exc), 'force': True}, 'ERROR')
                        except Exception:
                            pass
                        message = 'Firmware rejected: ' + str(exc)
                        if not await finish_progress_response('failed', message):
                            await send_response(writer, '400 Bad Request', message, 'text/plain')
                    else:
                        log_output('Local', 'Base firmware', {'log': 'Upload completed and verified', 'force': True}, 'INFO')
                        if not await finish_progress_response('complete', result):
                            await send_response(writer, '200 OK', str(result), 'text/plain')
            elif method == 'POST' and path.startswith('/set-loglevel'):
                level = str(form_params.get('level', '')).upper()
                if level not in levels:
                    level = None
                if level:
                    apply_loglevel_change(level, loglevel_setter, log_output)
                    await send_redirect(writer, '/logging')
                else:
                    body = 'Invalid log level'
                    await send_response(writer, '400 Bad Request', body, 'text/plain')
            elif path.startswith('/update-progress'):
                requested_id = parse_query(path).get('id', '')
                current_progress = upload_progress_by_id.get(
                    requested_id, {'phase': 'idle', 'percent': 0}
                )
                await send_response(
                    writer, '200 OK', json.dumps(current_progress), 'application/json'
                )
            elif path.startswith('/task-status'):
                requested_id = parse_query(path).get('id', '')
                current_task = (
                    task_status_getter(requested_id)
                    if task_status_getter else
                    {'phase': 'failed', 'message': 'Task status is unavailable'}
                )
                await send_response(
                    writer, '200 OK', json.dumps(current_task), 'application/json'
                )
            elif path.startswith('/logs'):
                body = render_log_text(log_getter())
                await send_response(writer, '200 OK', body, 'text/plain')
            elif path.startswith('/download-logs'):
                body = render_log_text(log_getter())
                await send_response(
                    writer,
                    '200 OK',
                    body,
                    'text/plain; charset=utf-8',
                    (('Content-Disposition', 'attachment; filename="ha-device-logs.txt"'),)
                )
            elif path.startswith('/download-diagnostics'):
                safe_logs = []
                for line in list(log_getter())[-100:]:
                    safe_logs.append(str(line))
                diagnostic_payload = {
                    'status': status_getter() if status_getter else {},
                    'modules': module_getter() if module_getter else [],
                    'logs': safe_logs
                }
                await send_response(
                    writer,
                    '200 OK',
                    json.dumps(diagnostic_payload),
                    'application/json; charset=utf-8',
                    (('Content-Disposition', 'attachment; filename="ha-device-diagnostics.json"'),)
                )
            elif path.startswith('/download-configuration'):
                if config_backup_getter is None:
                    await send_response(writer, '404 Not Found', 'Configuration backup unavailable', 'text/plain')
                else:
                    await send_response(
                        writer,
                        '200 OK',
                        json.dumps(config_backup_getter()),
                        'application/json; charset=utf-8',
                        (('Content-Disposition', 'attachment; filename="ha-device-configuration.json"'),)
                    )
            elif path.startswith('/api/status'):
                payload = {
                    'status': status_getter() if status_getter else {},
                    'modules': module_getter() if module_getter else []
                }
                body = json.dumps(payload) if json else '{}'
                await send_response(writer, '200 OK', body, 'application/json')
            elif path.startswith('/api/overview'):
                body = json.dumps({
                    'status': render_overview_status(
                        status_getter() if status_getter else {}
                    ),
                    'modules': render_overview_modules(
                        module_getter() if module_getter else []
                    )
                })
                await send_response(writer, '200 OK', body, 'application/json')
            elif path.startswith('/api/module-diagnostics'):
                body = json.dumps({
                    'modules': render_modules_html(
                        module_getter() if module_getter else [], session_id
                    )
                })
                await send_response(writer, '200 OK', body, 'application/json')
            elif path.startswith('/partials'):
                current_status = status_getter() if status_getter else {}
                payload = {
                    'live_sections': render_live_sections_html(
                        current_status,
                        module_getter() if module_getter else [],
                        session_id
                    ),
                    'update_summary': render_update_summary_html(current_status),
                    'update_actions': render_update_actions_html(
                        current_status, session_id
                    )
                }
                body = json.dumps(payload)
                await send_response(writer, '200 OK', body, 'application/json')
            elif method == 'POST' and path.startswith('/discover'):
                apply_portal_action('discover', action_path, action_handler, log_output, form_params)
                await send_redirect(writer, '/')
            elif method == 'POST' and path.startswith('/calibrate'):
                apply_portal_action('calibrate', action_path, action_handler, log_output, form_params)
                await send_redirect(writer, '/')
            elif method == 'POST' and path.startswith('/ems-debug'):
                apply_portal_action('ems-debug', action_path, action_handler, log_output, form_params)
                await send_redirect(writer, '/diagnostics')
            elif method == 'POST' and path.startswith('/activate-update'):
                result = apply_portal_action(
                    'activate-update', action_path, action_handler, log_output, form_params
                )
                session_id = new_session_id()
                session_started = monotonic_ms()
                await send_response(
                    writer, '200 OK',
                    portal_ui.restart_page(
                        login_url,
                        result.get('message', '') if isinstance(result, dict) else result
                    ),
                    extra_headers=(
                        ('Set-Cookie', session_cookie('', secure_cookie, True)),
                    )
                )
            elif method == 'POST' and path.startswith('/activate-firmware'):
                result = apply_portal_action(
                    'activate-firmware', action_path, action_handler, log_output, form_params
                )
                session_id = new_session_id()
                session_started = monotonic_ms()
                await send_response(
                    writer, '200 OK',
                    portal_ui.restart_page(
                        login_url,
                        result.get('message', '') if isinstance(result, dict) else result
                    ),
                    extra_headers=(
                        ('Set-Cookie', session_cookie('', secure_cookie, True)),
                    )
                )
            elif method == 'POST' and path.startswith('/rollback-application'):
                result = apply_portal_action(
                    'rollback-application', action_path, action_handler, log_output, form_params
                )
                session_id = new_session_id()
                session_started = monotonic_ms()
                await send_response(
                    writer, '200 OK',
                    portal_ui.restart_page(
                        login_url,
                        result.get('message', '') if isinstance(result, dict) else result
                    ),
                    extra_headers=(
                        ('Set-Cookie', session_cookie('', secure_cookie, True)),
                    )
                )
            elif method == 'POST' and path.startswith('/check-release'):
                result = apply_portal_action(
                    'check-release', action_path, action_handler, log_output, form_params
                )
                if isinstance(result, dict) and result.get('task_id'):
                    await send_response(
                        writer, '202 Accepted',
                        portal_ui.task_page(
                            result['task_id'], result.get('message', 'Checking for updates'),
                            '/updates'
                        )
                    )
                else:
                    await send_redirect(writer, '/updates')
            elif method == 'POST' and path.startswith('/download-release'):
                result = apply_portal_action(
                    'download-release', action_path, action_handler, log_output, form_params
                )
                if isinstance(result, dict) and result.get('task_id'):
                    await send_response(
                        writer, '202 Accepted',
                        portal_ui.task_page(
                            result['task_id'], result.get('message', 'Downloading release'),
                            '/updates'
                        )
                    )
                else:
                    await send_redirect(writer, '/updates')
            elif method == 'POST' and path.startswith('/validate-configuration'):
                result = apply_portal_action(
                    'validate-configuration', action_path, action_handler, log_output,
                    form_params
                )
                if is_json_validation:
                    await send_response(writer, '200 OK', result, 'text/plain')
                else:
                    await send_response(
                        writer,
                        '200 OK',
                        '<!doctype html><meta name="viewport" content="width=device-width">'
                        '<h1>Configuration validation</h1><pre>' + html_escape(result) +
                        '</pre><p><a href="/">Return to portal</a></p>'
                    )
            elif method != 'GET':
                await send_response(writer, '405 Method Not Allowed', 'Method not allowed', 'text/plain')
            else:
                body = render_overview_page(
                    session_id,
                    status_getter() if status_getter else {},
                    module_getter() if module_getter else [],
                    value_refresh_ms or 5000
                )
                await send_response(writer, '200 OK', body)

        except Exception as exc:
            if is_client_disconnect_error(exc):
                if path.startswith('/update-upload') or path.startswith('/firmware-upload'):
                    try:
                        source = 'Base firmware' if path.startswith('/firmware-upload') else 'Application update'
                        detail = ' after staging' if upload_state == 'staged' else ''
                        log_output(
                            'Local', source,
                            {'log': 'Upload connection closed' + detail, 'force': True},
                            'ERROR'
                        )
                    except Exception:
                        pass
                return
            try:
                log_output('Local', 'Web portal', {'log': 'Request failed - ' + str(exc)}, 'ERROR')
            except Exception:
                pass
        finally:
            await close_writer()

    ssl_context = None
    if settings.get('https', False):
        ssl_context = make_tls_context(settings.get('cert_path'), settings.get('key_path'))

    return await asyncio.start_server(
        handle_client,
        settings.get('host', '0.0.0.0'),
        settings.get('port', 8443 if settings.get('https', False) else 8080),
        backlog=4,
        ssl=ssl_context
    )

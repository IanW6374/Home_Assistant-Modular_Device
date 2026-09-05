"""Settings, maintenance, and security page renderers."""

try:
    import json
except ImportError:
    json = None

import web_portal_ui as portal_ui
import timezone_rules
from portal_http import html_escape, js_escape, configuration_backup_filename
from portal_presenters import render_badge, render_label

def _notice(message='', error=False):
    if not message:
        return ''
    return (
        '<p class="' + ('error' if error else 'notice') + '" role="status">' +
        html_escape(message) + '</p>'
    )


def operational_renderer(route, logging_renderer=None):
    return {
        '/settings': render_settings_page,
        '/portal-settings': render_portal_settings_page,
        '/wifi-settings': render_wifi_settings_page,
        '/ntp-settings': render_ntp_settings_page,
        '/messaging': render_messaging_page,
        '/device-api': render_device_api_page,
        '/logging-settings': logging_renderer or render_settings_page,
        '/user': render_user_settings_page,
    }.get(route, render_settings_page)


def render_operational(route, token, current_settings, message='', error=False,
                       current_user='', portal_user_getter=None,
                       logging_renderer=None):
    renderer = operational_renderer(route, logging_renderer)
    if route == '/user':
        return renderer(
            token, current_settings, message, error,
            users=portal_user_getter() if portal_user_getter else (),
            current_user=current_user
        )
    return renderer(token, current_settings, message, error)

def render_login_page(username='', error=''):
    body = (
        '<section class="auth-card card"><span class="eyebrow">Secure device portal</span>'
        '<h1>Welcome back</h1><p class="lead">Sign in to manage this IoT-MD device.</p>' +
        _notice(error, True) +
        '<form id="login-form" action="/login" method="post">'
        '<label class="field">Username<input name="username" autocomplete="username" value="' +
        html_escape(username) + '" required maxlength="64" autofocus></label>'
        '<label class="field">Password<input name="password" type="password" '
        'autocomplete="current-password" required maxlength="256"></label>'
        '<button id="login-button" type="submit">Sign in</button>'
        '<p id="auth-status" class="portal-status" role="status" aria-live="polite"></p>'
        '</form></section>'
    )
    script = (
        'var f=document.getElementById("login-form");f.onsubmit=function(e){'
        'if(f.getAttribute("data-submitting")==="1")return false;'
        'if(e&&e.preventDefault)e.preventDefault();f.setAttribute("data-submitting","1");'
        'var b=document.getElementById("login-button");b.disabled=true;'
        'b.textContent="Signing in…";document.getElementById("auth-status").textContent='
        '"Securely verifying your password…";setTimeout(function(){f.submit();},80);'
        'return false;};'
    )
    return portal_ui.shell(
        'IoT-MD login', '', body, script=script, authenticated=False
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
    return portal_ui.shell('IoT-MD account', 'user_settings', body, csrf)

def render_operational_hidden_fields(settings, excluded=()):
    settings = settings or {}
    port = settings.get('portal_port')
    values = (
        ('device_name', settings.get('device_name', '')),
        ('portal_username', settings.get('portal_username', 'admin')),
        ('portal_transport', settings.get('portal_transport', 'auto')),
        ('portal_port', '' if port is None else str(port)),
        ('portal_session_timeout_s', settings.get('portal_session_timeout_s', 3600)),
        ('ntp_servers', ', '.join(settings.get('ntp_servers', ()))),
        ('timezone_offset_minutes', settings.get('timezone_offset_minutes', 0)),
        ('timezone_name', settings.get('timezone_name', 'UTC')),
        ('wifi_ssid', settings.get('wifi_ssid', '')),
        ('wifi_dhcp', 'true' if settings.get('wifi_dhcp', True) else 'false'),
        ('wifi_ip_address', settings.get('wifi_ip_address', '')),
        ('wifi_subnet_mask', settings.get('wifi_subnet_mask', '')),
        ('wifi_gateway', settings.get('wifi_gateway', '')),
        ('wifi_dns_server', settings.get('wifi_dns_server', '')),
        ('mqtt_server', settings.get('mqtt_server', '')),
        ('mqtt_port', settings.get('mqtt_port', 8883)),
        ('mqtt_username', settings.get('mqtt_username', '')),
        ('mqtt_enabled', 'true' if settings.get('mqtt_enabled') else 'false'),
        ('mqtt_base_topic', settings.get('mqtt_base_topic', 'iotmd')),
        ('mqtt_state_topic', settings.get(
            'mqtt_state_topic', '{base}/{device_id}/{module_id}/state'
        )),
        ('mqtt_command_topic', settings.get(
            'mqtt_command_topic', '{base}/{device_id}/{module_id}/set'
        )),
        ('mqtt_response_topic', settings.get(
            'mqtt_response_topic', '{base}/{device_id}/{module_id}/response'
        )),
        ('mqtt_availability_topic', settings.get(
            'mqtt_availability_topic', '{base}/{device_id}/availability'
        )),
        ('mqtt_qos', settings.get('mqtt_qos', 0)),
        ('mqtt_retain_state', 'true' if settings.get('mqtt_retain_state') else 'false'),
        ('mqtt_command_subscriptions', 'true' if settings.get(
            'mqtt_command_subscriptions', True
        ) else 'false'),
        ('ha_discovery', 'true' if settings.get('ha_discovery') else 'false'),
        ('ha_discovery_prefix', settings.get(
            'ha_discovery_prefix', 'homeassistant'
        )),
        ('log_buffer_lines', settings.get('log_buffer_lines', 200)),
        ('syslog_enabled', 'true' if settings.get('syslog_enabled') else 'false'),
        ('syslog_audit_enabled', 'true' if settings.get(
            'syslog_audit_enabled', settings.get('syslog_enabled', False)
        ) else 'false'),
        ('syslog_host', settings.get('syslog_host', '')),
        ('syslog_port', settings.get('syslog_port', 514)),
        ('syslog_transport', settings.get('syslog_transport', 'udp')),
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
            'Device', 'Network', 'Configure the device identity and wireless network.'
        ) + _notice(message, error) +
        '<form action="/settings" method="post" autocomplete="off">'
        '<input type="hidden" name="csrf" value="' + html_escape(csrf) + '">' +
        render_operational_hidden_fields(settings, (
            'device_name', 'wifi_dhcp', 'wifi_ip_address',
            'wifi_subnet_mask', 'wifi_gateway', 'wifi_dns_server'
        )) +
        '<section class="card"><div class="section-title"><h2>Device identity</h2></div>'
        '<label class="field">Device name<input name="device_name" required maxlength="64" value="' +
        html_escape(settings.get('device_name', '')) + '"></label></section>'
        '<section class="card"><div class="section-title"><h2>Wi-Fi network</h2>'
        '<button id="wifi-rescan" class="secondary compact" type="button">Scan again</button></div>'
        '<div class="grid"><label class="field">Network name (SSID)<input id="wifi-ssid-input" '
        'name="wifi_ssid" list="wifi-network-options" required maxlength="32" value="' +
        html_escape(settings.get('wifi_ssid', '')) + '" placeholder="Select or enter a network">'
        '<datalist id="wifi-network-options"></datalist></label>'
        '<label class="field">Network password<input name="wifi_password" type="password" '
        'maxlength="64" autocomplete="new-password"' + placeholder + '></label></div>'
        '<p id="wifi-scan-status" class="portal-status" role="status" aria-live="polite">'
        'Scanning for nearby networks…</p>'
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
        '<div class="actions"><span></span><button type="submit">Save changes</button>'
        '</div></form>'
    )
    script = (
        'var wifiInput=document.getElementById("wifi-ssid-input"),wifiOptions=document.getElementById('
        '"wifi-network-options"),wifiStatus='
        'document.getElementById("wifi-scan-status"),wifiRescan=document.getElementById("wifi-rescan");'
        'function wifiOption(value,text){var option=document.createElement("option");option.value=value;'
        'option.label=text;return option;}function scanWifi(){wifiRescan.disabled=true;'
        'portalStatus(wifiStatus,"","Scanning for nearby networks…");fetch("/api/wifi-networks",{cache:"no-store",'
        'credentials:"same-origin"}).then(function(response){if(!response.ok)throw new Error("HTTP "+response.status);'
        'return response.json();}).then(function(networks){wifiOptions.textContent="";for(var i=0;i<networks.length;i++){var network='
        'networks[i],label=network.ssid+(typeof network.rssi==="number"?" ("+network.rssi+" dBm)":"");'
        'wifiOptions.appendChild(wifiOption(network.ssid,label));}portalStatus(wifiStatus,'
        'networks.length?"success":"warning",networks.length?networks.length+" network"+'
        '(networks.length===1?"":"s")+" found; select one or enter its name.":'
        '"No visible networks found; enter the network name.");}).catch(function(){portalStatus(wifiStatus,"warning",'
        '"Network scan unavailable; enter the SSID manually.");'
        '}).finally(function(){wifiRescan.disabled=false;});}wifiRescan.onclick=scanWifi;scanWifi();'
        'var dhcp=document.getElementById("wifi-dhcp"),staticBox='
        'document.getElementById("wifi-static-settings");function syncNetworkMode(){'
        'var manual=!dhcp.checked;staticBox.hidden=!manual;var fields=staticBox.querySelectorAll("input");'
        'for(var i=0;i<fields.length;i++)fields[i].required=manual;}dhcp.onchange=syncNetworkMode;'
        'syncNetworkMode();'
    )
    return portal_ui.shell('IoT-MD network', 'settings', body, csrf, script)

def render_portal_settings_page(csrf, settings, message='', error=False):
    settings = settings or {}
    transport = settings.get('portal_transport', 'auto')
    port = settings.get('portal_port')
    port_value = '' if port is None else str(port)
    session_timeout_s = int(settings.get('portal_session_timeout_s', 3600) or 3600)
    session_timeout_minutes = max(5, min(1440, (session_timeout_s + 59) // 60))
    body = (
        portal_ui.page_heading(
            'Device', 'Portal', 'Configure portal transport and listening port.'
        ) + _notice(message, error) +
        '<form action="/portal-settings" method="post" autocomplete="off">'
        '<input type="hidden" name="csrf" value="' + html_escape(csrf) + '">' +
        render_operational_hidden_fields(settings, (
            'portal_transport', 'portal_port', 'portal_session_timeout_s'
        )) +
        '<section class="card"><div class="section-title"><h2>Portal access</h2></div>'
        '<div class="grid">'
        '<label class="field">Portal transport<select name="portal_transport">'
        '<option value="auto"' + (' selected' if transport == 'auto' else '') +
        '>Automatic (HTTPS with certificate)</option><option value="https"' +
        (' selected' if transport == 'https' else '') + '>Always HTTPS</option>'
        '<option value="http"' + (' selected' if transport == 'http' else '') +
        '>HTTP (unencrypted)</option></select></label>'
        '<label class="field">Portal port<input name="portal_port" type="number" min="1" max="65535" '
        'required value="' + html_escape(port_value) + '"></label>'
        '<label class="field">Inactive session timeout (minutes)<input '
        'name="portal_session_timeout_minutes" type="number" min="5" max="1440" required value="' +
        html_escape(session_timeout_minutes) + '"></label></div>'
        '<p class="muted">HTTPS defaults to port 8443 and explicit HTTP defaults to 8080. Port 80 is reserved for '
        'certificate enrollment and recovery.</p><div class="actions"><span></span>'
        '<button type="submit">Save changes</button></div></section></form>'
    )
    return portal_ui.shell('IoT-MD portal settings', 'portal_settings', body, csrf)

def render_wifi_settings_page(csrf, settings, message='', error=False):
    # Keep the former URL working for bookmarks while presenting the merged page.
    return render_settings_page(csrf, settings, message, error)

def render_ntp_settings_page(csrf, settings, message='', error=False):
    settings = settings or {}
    ntp_servers = ', '.join(settings.get('ntp_servers', ()))
    timezone_name = str(settings.get('timezone_name', 'UTC'))
    timezone_options = ''.join(
        '<option value="' + html_escape(name) + '"' +
        (' selected' if name == timezone_name else '') + '>' +
        html_escape(label) + '</option>'
        for name, label in timezone_rules.choices()
    )
    current_offset = timezone_rules.offset_minutes(timezone_name)
    offset_text = ('+' if current_offset >= 0 else '−') + (
        '{:02}:{:02}'.format(abs(current_offset) // 60, abs(current_offset) % 60)
    )
    body = (
        portal_ui.page_heading(
            'Device', 'Time / Date',
            'Configure UTC time synchronisation and automatic local daylight-saving rules.'
        ) + _notice(message, error) +
        '<form action="/ntp-settings" method="post" autocomplete="off">'
        '<input type="hidden" name="csrf" value="' + html_escape(csrf) + '">' +
        render_operational_hidden_fields(settings, (
            'ntp_servers', 'timezone_offset_minutes', 'timezone_name'
        )) +
        '<section class="card"><div class="section-title"><h2>Time synchronisation</h2></div>'
        '<label class="field">NTP servers (comma separated)<input name="ntp_servers" required '
        'maxlength="1024" value="' + html_escape(ntp_servers) + '"></label>'
        '<label class="field">Time zone<select name="timezone_name">' +
        timezone_options + '</select></label>'
        '<p class="muted">Current UTC offset for this zone: UTC' + offset_text +
        '. Daylight-saving changes are applied automatically using the selected city’s current regional rules. '
        'The RTC and NTP protocol remain in UTC.</p>'
        '<div class="actions"><span></span><button type="submit">Save changes</button>'
        '</div></section></form>'
    )
    return portal_ui.shell('IoT-MD time and date settings', 'ntp_settings', body, csrf)

def render_messaging_page(csrf, settings, message='', error=False):
    settings = settings or {}
    stored = bool(settings.get('mqtt_password_set'))
    enabled = ' checked' if settings.get('mqtt_enabled') else ''
    commands = ' checked' if settings.get('mqtt_command_subscriptions', True) else ''
    retained = ' checked' if settings.get('mqtt_retain_state') else ''
    discovery = ' checked' if settings.get('ha_discovery') else ''
    placeholder = ' placeholder="&#8226;&#8226;&#8226;&#8226;&#8226;&#8226;&#8226;&#8226;"' if stored else ''
    mqtt_hint = (
        'A password is stored. Overtype the masked field to replace it.'
        if stored else 'No MQTT password is stored.'
    )
    body = (
        portal_ui.page_heading(
            'Device', 'MQTT',
            'Configure platform-neutral MQTT messaging and the optional Home Assistant integration.'
        ) + _notice(message, error) +
        '<form action="/messaging" method="post" autocomplete="off">'
        '<input type="hidden" name="csrf" value="' + html_escape(csrf) + '">' +
        render_operational_hidden_fields(
            settings, (
                'mqtt_server', 'mqtt_port', 'mqtt_username', 'mqtt_enabled',
                'mqtt_base_topic', 'mqtt_state_topic', 'mqtt_command_topic',
                'mqtt_response_topic', 'mqtt_availability_topic', 'mqtt_qos',
                'mqtt_retain_state', 'mqtt_command_subscriptions',
                'ha_discovery', 'ha_discovery_prefix'
            )
        ) +
        '<section class="card"><div class="section-title"><h2>MQTT connection</h2></div>'
        '<label class="check"><input type="checkbox" name="mqtt_enabled"' + enabled +
        '>Enable MQTT messaging</label>'
        '<div class="grid"><label class="field">Broker hostname<input name="mqtt_server" maxlength="253" '
        'value="' + html_escape(settings.get('mqtt_server', '')) + '"></label>'
        '<label class="field">Broker port<input name="mqtt_port" type="number" min="1" max="65535" '
        'required value="' + html_escape(settings.get('mqtt_port', 8883)) + '"></label>'
        '<label class="field">MQTT username<input name="mqtt_username" maxlength="128" value="' +
        html_escape(settings.get('mqtt_username', '')) + '"></label>'
        '<label class="field">MQTT password<input name="mqtt_password" type="password" '
        'maxlength="256" autocomplete="new-password"' + placeholder + '></label></div>'
        '<p class="muted">' + mqtt_hint +
        ' MQTT TLS is mandatory.</p></section>'
        '<section class="card"><div class="section-title"><h2>Topic contract</h2></div>'
        '<label class="field">Base topic<input name="mqtt_base_topic" maxlength="256" value="' +
        html_escape(settings.get('mqtt_base_topic', 'iotmd')) + '"></label>'
        '<div class="grid"><label class="field">State topic template<input name="mqtt_state_topic" maxlength="256" value="' +
        html_escape(settings.get('mqtt_state_topic', '{base}/{device_id}/{module_id}/state')) + '"></label>'
        '<label class="field">Command topic template<input name="mqtt_command_topic" maxlength="256" value="' +
        html_escape(settings.get('mqtt_command_topic', '{base}/{device_id}/{module_id}/set')) + '"></label>'
        '<label class="field">Response topic template<input name="mqtt_response_topic" maxlength="256" value="' +
        html_escape(settings.get('mqtt_response_topic', '{base}/{device_id}/{module_id}/response')) + '"></label>'
        '<label class="field">Availability topic template<input name="mqtt_availability_topic" maxlength="256" value="' +
        html_escape(settings.get('mqtt_availability_topic', '{base}/{device_id}/availability')) + '"></label>'
        '<label class="field">QoS<select name="mqtt_qos"><option value="0"' +
        (' selected' if int(settings.get('mqtt_qos', 0)) == 0 else '') + '>0 — at most once</option><option value="1"' +
        (' selected' if int(settings.get('mqtt_qos', 0)) == 1 else '') + '>1 — at least once</option></select></label></div>'
        '<p class="muted">Templates support {base}, {device_id}, {module_id} and {component}. The resolved topics are independent of Home Assistant.</p>'
        '<label class="check"><input type="checkbox" name="mqtt_command_subscriptions"' + commands +
        '>Enable MQTT command subscriptions</label>'
        '<label class="check"><input type="checkbox" name="mqtt_retain_state"' + retained +
        '>Retain module state by default</label></section>'
        '<section class="card"><div class="section-title"><h2>Home Assistant integration</h2></div>'
        '<label class="check"><input type="checkbox" name="ha_discovery"' + discovery +
        '>Enable Home Assistant Discovery Integration</label>'
        '<label class="field">Discovery prefix<input name="ha_discovery_prefix" maxlength="256" value="' +
        html_escape(settings.get('ha_discovery_prefix', 'homeassistant')) + '"></label>'
        '<p class="muted">Home Assistant discovery points to the operational MQTT topics above. Disabling it does not disable MQTT.</p>'
        '<div class="section-title"><h3>Discovery publishing</h3></div>'
        '<div class="actions"><p class="muted">Republish discovery configuration for all loaded entities.</p>'
        '<button type="submit" form="discovery-publish-form">Publish discovery</button></div></section>'
        '<div class="actions"><span></span><button type="submit">Save changes</button></div></form>'
        '<form id="discovery-publish-form" action="/discover" method="post">'
        '<input type="hidden" name="csrf" value="' + html_escape(csrf) + '"></form>'
    )
    return portal_ui.shell('IoT-MD MQTT', 'messaging', body, csrf)

def render_device_api_page(csrf, settings, message='', error=False):
    enabled = ' checked' if settings.get('api_enabled') else ''
    clients = settings.get('api_clients', []) or []
    rows = []
    for client in clients:
        fingerprint = str(client.get('fingerprint', ''))
        expiry_level = client.get('expiry_level', 'unknown')
        badge_text = (
            'expired' if expiry_level == 'expired' else
            (str(client.get('days_remaining')) + ' days'
             if expiry_level in ('warning', 'critical') else 'enrolled')
        )
        rows.append(
            '<article class="module-card"><div class="module-head"><div><h3>' +
            html_escape(client.get('label', 'API client')) + '</h3><p class="muted">' +
            html_escape(', '.join(client.get('scopes', []))) + '</p></div>' +
            render_badge(
                badge_text,
                'good' if expiry_level in ('ok', 'unknown') else 'warn'
            ) + '</div><div class="property-grid">'
            '<div class="property-row"><span>Subject</span><strong>' +
            html_escape(client.get('subject', '')) + '</strong></div>'
            '<div class="property-row"><span>Fingerprint</span><strong>' +
            html_escape(fingerprint) + '</strong></div>'
            '<div class="property-row"><span>Expires</span><strong>' +
            html_escape(client.get('not_after', 'unknown')) + '</strong></div></div>'
            '<form method="post" action="/revoke-api-client"><input type="hidden" '
            'name="csrf" value="' + html_escape(csrf) + '"><input type="hidden" '
            'name="fingerprint" value="' + html_escape(fingerprint) + '">'
            '<div class="actions"><span></span><button class="danger compact" type="submit">'
            'Revoke client</button></div></form></article>'
        )
    if not rows:
        rows.append('<p class="muted">No API client certificates are enrolled.</p>')
    body = (
        portal_ui.page_heading(
            'Device', 'Device API',
            'Expose module state and commands over a versioned HTTPS API secured with mutual TLS.'
        ) + _notice(message, error) +
        '<section class="card"><div class="section-title"><h2>API listener</h2></div>'
        '<form action="/device-api" method="post"><input type="hidden" name="csrf" value="' +
        html_escape(csrf) + '">' + render_operational_hidden_fields(settings) +
        '<label class="check"><input name="api_enabled" type="checkbox" '
        'value="true"' + enabled + '>Enable the mTLS device API</label><div class="grid">'
        '<label class="field">API port<input name="api_port" type="number" min="1" max="65535" '
        'required value="' + html_escape(settings.get('api_port', 8444)) + '"></label>'
        '<div class="property-row"><span>Authentication</span><strong>Mutual TLS (required)</strong></div>'
        '</div><p class="muted">A dedicated API client CA and at least one enrolled client '
        'certificate are required. Configure these under Maintenance / Certificates.</p>'
        '<div class="actions"><span></span><button type="submit">Save changes</button>'
        '</div></form></section><section class="card"><div class="section-title">'
        '<h2>Enrolled clients</h2></div><div class="module-grid">' + ''.join(rows) +
        '</div></section>'
    )
    return portal_ui.shell('IoT-MD Device API', 'device_api', body, csrf)

def render_user_settings_page(
    csrf, settings, message='', error=False, password_message='', password_error=False,
    users=None, current_user=''
):
    settings = settings or {}
    user_rows = []
    for user in users or ():
        name = str(user.get('username', ''))
        enabled = bool(user.get('enabled'))
        role = str(user.get('role', 'viewer'))
        role_labels = {
            'viewer': 'Viewer', 'operator': 'Operator',
            'administrator': 'Administrator'
        }
        options = ''.join(
            '<option value="' + value + '"' + (' selected' if role == value else '') +
            '>' + role_labels.get(value, value) + '</option>'
            for value in ('viewer', 'operator', 'administrator')
        )
        user_rows.append(
            '<article class="module-card portal-user-card"><div class="module-card-title"><strong>' +
            html_escape(name) + '</strong><span class="badge">' + html_escape(role) +
            '</span></div><form action="/user/update" method="post">'
            '<input type="hidden" name="csrf" value="' + html_escape(csrf) + '">'
            '<input type="hidden" name="username" value="' + html_escape(name) + '">'
            '<label class="field">Username<input name="new_username" required maxlength="32" value="' +
            html_escape(name) + '"></label>'
            '<label class="field">Role<select name="role">' + options + '</select></label>'
            '<label class="check"><input type="checkbox" name="enabled" value="true"' +
            (' checked' if enabled else '') + '>Enabled</label><div class="actions"><span></span>'
            '<button class="secondary" type="submit">Update user</button></div></form>' +
            ('' if name == current_user else (
                '<form action="/user/remove" method="post"><input type="hidden" name="csrf" value="' +
                html_escape(csrf) + '"><input type="hidden" name="username" value="' +
                html_escape(name) + '"><div class="actions"><span></span>'
                '<button class="danger" type="submit">Remove user</button></div></form>'
            )) + '</article>'
        )
    body = (
        portal_ui.page_heading(
            'User', 'Portal users',
            'Manage portal usernames, roles and access. Change your own password from the avatar menu.'
        ) + _notice(message, error) + _notice(password_message, password_error) +
        '<section class="card"><div class="section-title"><h2>Existing portal users</h2>'
        '<span class="badge">Maximum 8</span></div><div class="module-grid portal-user-grid">' +
        ''.join(user_rows) + '</div></section>'
        '<section class="card"><div class="section-title"><h2>New portal user</h2></div>'
        '<form action="/user/add" method="post" autocomplete="off">'
        '<input type="hidden" name="csrf" value="' + html_escape(csrf) + '"><div class="grid">'
        '<label class="field">Username<input name="username" required maxlength="32"></label>'
        '<label class="field">Role<select name="role"><option value="viewer">Viewer</option>'
        '<option value="operator">Operator</option><option value="administrator">Administrator</option>'
        '</select></label><label class="field">Initial password<input type="password" name="password" '
        'minlength="16" maxlength="256" required autocomplete="new-password"></label></div>'
        '<div class="actions"><span></span><button type="submit">Add portal user</button></div>'
        '</form></section>'
    )
    return portal_ui.shell('IoT-MD portal users', 'user_settings', body, csrf)

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
    return portal_ui.shell('IoT-MD modules', 'modules', body, csrf, script)

def render_certificate_details(certificates):
    certificates = certificates or {}
    mqtt_key = 'mqtt_ca' if 'mqtt_ca' in certificates else 'trusted_ca'
    def certificate_card(key, label, missing_message='No certificate file is installed.'):
        details = certificates.get(key, {}) or {}
        installed = bool(details.get('installed'))
        expiry_level = details.get('expiry_level', 'ok' if installed else 'missing')
        badge = render_badge(
            (
                'expired' if expiry_level == 'expired' else
                (str(details.get('days_remaining')) + ' days'
                 if expiry_level in ('warning', 'critical') else
                 ('installed' if installed else 'not installed'))
            ),
            'good' if installed and expiry_level == 'ok' else 'warn'
        )
        rows = []
        if details.get('error'):
            rows.append(
                '<p class="error-text">Unable to decode: ' +
                html_escape(details.get('error')) + '</p>'
            )
        elif installed:
            if details.get('migration_pending'):
                rows.append(
                    '<p class="warning-text">Upgrade identity only: replace this with a '
                    'private-CA Device API and fleet server certificate.</p>'
                )
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

    api_ca_cards = ''
    for index, details in enumerate(certificates.get('api_client_cas', ()) or ()):
        key = '_api_client_ca_' + str(index)
        certificates[key] = details
        api_ca_cards += certificate_card(
            key, 'API client CA ' + str(index + 1)
        )
    if not api_ca_cards:
        api_ca_cards = certificate_card('api_client_ca', 'API client CA')

    groups = (
        (
            'CA Trust',
            'Certificate authorities trusted by this device for secured services.',
            certificate_card(
                mqtt_key, 'MQTT trusted CA',
                'No separate CA trust anchor is installed. The generated self-signed portal '
                'certificate is listed under Device Certificates.'
            ) +
            certificate_card('release_ca', 'Release-server trusted CA') +
            certificate_card('syslog_ca', 'Syslog trusted CA') +
            api_ca_cards
        ),
        (
            'Device Certificates',
            'Certificates that identify the portal or other device services.',
            certificate_card('portal', 'Portal HTTPS certificate') +
            certificate_card(
                'api_server', 'Device API and fleet server certificate',
                'No independent Device API/fleet server identity is installed.'
            )
        ),
    )
    return ''.join(
        '<div class="certificate-group"><div class="certificate-group-head">'
        '<h3>' + title + '</h3><p class="muted">' + description + '</p></div>'
        '<div class="module-grid">' + cards + '</div></div>'
        for title, description, cards in groups
    )

def render_certificate_page(csrf, message='', certificates=None):
    certificates = certificates or {}
    acme = certificates.get('acme_settings', {}) or {}
    certificate_mode = str(acme.get('mode', 'manual'))
    certificate_method = str(acme.get(
        'method', 'iot_ca_auto' if certificate_mode == 'iot_ca' else certificate_mode
    ))
    acme_enabled = certificate_mode == 'acme'
    renewal = {
        'iot_ca_auto': (
            'success', 'Automatic IoT CA enrollment',
            'The public portal, private Device API/fleet and renewal identities are '
            'automatically rotated together after two-thirds of the public portal '
            'or Device API certificate lifetime.'
        ),
        'iot_ca_file': (
            'success', 'IoT CA enrollment authorization (.iotenroll)',
            'The public portal, private Device API/fleet and renewal identities are '
            'automatically rotated together after two-thirds of the public portal '
            'or Device API certificate lifetime.'
        ),
        'acme': (
            'success', 'Private CA ACME enrollment',
            'The local portal certificate is automatically renewed after two-thirds '
            'of its lifetime. This method does not manage a separate Device API/fleet identity.'
        ),
        'self_signed': (
            'info', 'Self-signed device certificate',
            'The device automatically regenerates its local self-signed certificate '
            'after two-thirds of its lifetime.'
        ),
        'manual': (
            'warning', 'Manual certificate package',
            'Automatic renewal is unavailable. Replace the public portal and private '
            'Device API/fleet certificates before either identity expires.'
        ),
    }.get(certificate_method, (
        'warning', 'Unknown certificate method',
        'Certificate renewal status is unavailable for this configuration.'
    ))
    renewal_notice = (
        '<section class="portal-status ' + renewal[0] + '" role="status">'
        '<strong>Certificate method: ' + html_escape(renewal[1]) + '</strong><br>' +
        html_escape(renewal[2]) + '</section>'
    )
    body = (
        portal_ui.page_heading(
            'Maintenance', 'Certificates',
            'Review installed certificate identities and use manual DER upload when renewal is unavailable.'
        ) + _notice(message) + renewal_notice +
        '<section class="card"><div class="section-title"><h2>Installed certificates</h2></div>' +
        render_certificate_details(certificates) + '</section>'
        '<section class="card"><div class="section-title"><h2>Private CA ACME enrollment</h2></div>'
        '<form action="/acme-settings" method="post"><input type="hidden" name="csrf" value="' +
        html_escape(csrf) + '"><input type="hidden" name="acme_enabled" value="false">'
        '<label class="check"><input id="acme-enabled" name="acme_enabled" type="checkbox" value="true"' +
        (' checked' if acme_enabled else '') + '>Enable automatic Private CA ACME renewal for the portal certificate</label>'
        '<fieldset id="acme-fields" class="conditional-fields"' +
        ('' if acme_enabled else ' disabled') + '><div class="grid"><label class="field">ACME directory URL'
        '<input name="directory_url" type="url" maxlength="512" required value="' +
        html_escape(acme.get('directory_url', '')) + '"></label>'
        '<label class="field">Certificate hostname<input name="hostname" maxlength="253" '
        'required value="' + html_escape(acme.get('hostname', '')) + '"></label></div></fieldset>'
        '<p class="muted">This changes the certificate method to Private CA ACME enrollment. '
        'When disabled, the installed portal certificate remains in use but this ACME renewal '
        'service stops.</p><div class="actions"><span></span>'
        '<button type="submit">Save Private CA ACME settings</button></div></form></section>'
        '<section class="card"><div class="section-title"><h2>Import certificate</h2></div>'
        '<p class="muted">Choose the certificate purpose, select the DER file or files, then '
        'validate and install them as one operation.</p><label class="field">Certificate type'
        '<select id="certificate-type"><option value="portal">Portal certificate and private key</option>'
        '<option value="api-server">Device API and fleet server certificate and private key</option>'
        '<option value="mqtt-ca">MQTT trusted CA</option><option value="release-ca">Release-server trusted CA</option>'
        '<option value="management-suite-key">Management Suite verification key</option>'
        '<option value="syslog-ca">Syslog trusted CA</option><option value="api-client-ca">API client CA trust</option>'
        '<option value="api-client-cert">Module API client certificate</option>'
        '<option value="fleet-client-cert">Fleet manager client certificate</option></select></label>'
        '<div class="grid"><label id="certificate-primary-label" class="field">Portal certificate'
        '<input id="certificate-primary" type="file" accept=".der,.pem,application/pkix-cert,application/x-pem-file" required></label>'
        '<label id="certificate-secondary-label" class="field">Portal private key'
        '<input id="certificate-secondary" type="file" accept=".der,application/octet-stream" required></label></div>'
        '<p id="certificate-help" class="muted"></p><div class="actions">'
        '<span id="certificate-result" class="portal-status" role="status" aria-live="polite"></span>'
        '<button id="certificate-upload" type="button">Upload and validate</button></div>' +
        portal_ui.progress('certificate-progress', 'Waiting…', True) + '</section>'
    )
    script = (
        'var csrf=' + repr(str(csrf)) + ',type=document.getElementById("certificate-type"),'
        'primary=document.getElementById("certificate-primary"),secondary=document.getElementById('
        '"certificate-secondary"),secondaryLabel=document.getElementById("certificate-secondary-label"),'
        'primaryLabel=document.getElementById("certificate-primary-label"),help=document.getElementById('
        '"certificate-help");var descriptions={portal:["Portal certificate","Portal private key",'
        '"Both files are validated together; installation restarts the portal."],"api-server":["Device API and fleet server certificate",'
        '"Device API and fleet server private key","Both private-CA files are validated together; the mTLS API reloads without a device restart."],"mqtt-ca":["MQTT trusted CA","",'
        '"Authenticates the MQTT broker."],"release-ca":["Release-server trusted CA","",'
        '"Authenticates the signed release server."],"management-suite-key":["Management Suite verification key","",'
        '"Verifies fleet policy and format-3 release catalogs; bundle signatures remain independently verified."],"syslog-ca":["Syslog trusted CA","",'
        '"Authenticates an encrypted syslog server."],"api-client-ca":["API client CA files","",'
        '"Install one or more issuing CAs; the device restarts once."],"api-client-cert":['
        '"API client certificates","","Enrol module API identities with read/write scopes without a restart."],'
        '"fleet-client-cert":["Fleet client certificates","","Enrol Home Assistant fleet identities with fleet read/write scopes."]};'
        'function configureCertificateImport(){var d=descriptions[type.value];primaryLabel.firstChild.nodeValue=d[0];'
        'secondaryLabel.firstChild.nodeValue=d[1];secondaryLabel.hidden=!d[1];primary.multiple='
        'type.value==="api-client-ca"||type.value==="api-client-cert"||type.value==="fleet-client-cert";'
        'secondary.disabled=!d[1];secondary.required=!!d[1];if(!d[1])secondary.value="";help.textContent=d[2];}'
        'type.onchange=configureCertificateImport;configureCertificateImport();'
        'document.getElementById("acme-enabled").onchange=function(){document.getElementById('
        '"acme-fields").disabled=!this.checked;};'
        'function uploadCertificate(file,kind,index,total,label){return new Promise(function(resolve,reject){'
        'var x=new XMLHttpRequest();x.open("POST","/certificate-upload",true);x.setRequestHeader('
        '"Content-Type","application/octet-stream");x.setRequestHeader("X-CSRF-Token",csrf);'
        'x.setRequestHeader("X-Certificate-Kind",kind);x.upload.onprogress=function(p){if(p.lengthComputable){'
        'label.textContent="Uploading "+index+" of "+total+" · "+Math.round(p.loaded*100/p.total)+"%";}};'
        'x.onload=function(){if(x.status>=200&&x.status<300)resolve(x.responseText);else reject(new Error('
        'x.responseText||"Certificate upload failed"));};x.onerror=function(){reject(new Error('
        '"Connection lost during certificate upload"));};x.send(file);});}'
        'document.getElementById("certificate-upload").onclick=async function(){var out=document.getElementById('
        '"certificate-result"),box=document.getElementById("certificate-progress"),label=box.querySelector('
        '".status-text"),files=[],kind=type.value;if(!portalRequire(primary,'
        '"Select at least one certificate file")){portalStatus(out,"error",'
        '"Select at least one certificate file");return;}'
        'for(var i=0;i<primary.files.length;i++)files.push('
        '[kind==="portal"?"portal-cert":kind==="api-server"?"api-server-cert":kind,primary.files[i]]);'
        'if(kind==="portal"||kind==="api-server"){if(!secondary.files[0]){var keyLabel=kind==="portal"?'
        '"portal private key":"Device API server private key";portalStatus(out,"error","Select the "+keyLabel);'
        'portalRequire(secondary,"Select the "+keyLabel);return;}files.push(['
        'kind==="portal"?"portal-key":"api-server-key",secondary.files[0]]);}'
        'this.disabled=true;portalStatus(out,"","");box.hidden=false;box.classList.remove("complete","failed");'
        'try{for(var j=0;j<files.length;j++){'
        'await uploadCertificate(files[j][1],files[j][0],j+1,files.length,label);}'
        'label.textContent="Validating certificate set…";var done=await fetch('
        '"/validate-certificates",{method:"POST",credentials:"same-origin",headers:{'
        '"Content-Type":"application/x-www-form-urlencoded"},body:"csrf="+encodeURIComponent(csrf)});'
        'if(!done.ok)throw new Error(await done.text());box.classList.add("complete");label.textContent='
        '"Certificate installation complete";document.open();document.write(await done.text());document.close();}'
        'catch(e){portalStatus(out,"error",e.message);box.classList.add("failed");'
        'label.textContent="Installation failed";'
        'this.disabled=false;}};'
    )
    return portal_ui.shell('IoT-MD certificates', 'certificates', body, csrf, script)

def render_device_control_page(csrf, error=''):
    body = (
        portal_ui.page_heading(
            'Maintenance', 'Power & reset',
            'Restart, shut down, or return this device to factory defaults.'
        ) + _notice(error, True) +
        '<section class="card"><div class="section-title"><h2>Power controls</h2></div>'
        '<p class="muted">Restart and shutdown retain all settings, certificates, logs and '
        'installed software.</p><div class="actions power-actions">'
        '<form action="/restart-device" method="post"><input type="hidden" name="csrf" value="' +
        html_escape(csrf) + '"><button class="secondary" type="submit">Restart device</button></form>'
        '<form action="/shutdown-device" method="post"><input type="hidden" name="csrf" value="' +
        html_escape(csrf) + '"><button class="danger" type="submit">Shut down device</button></form>'
        '</div><p class="muted">Shutdown enters deep sleep. Power-cycle or externally reset '
        'the device to start it again.</p></section>'
        '<section class="card"><div class="section-title"><h2>Factory default</h2></div>'
        '<p class="warning"><strong>This cannot be undone.</strong> Network, MQTT, portal, '
        'Home Assistant, module, certificate, ACME and log-history data will be erased. '
        'The signed core, active application and upgrade verification key are retained.</p>'
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
        '<p class="muted">After restart, connect to the IoT-MD-Setup access point using the new '
        'setup password, then browse to http://192.168.4.1.</p><div class="actions">'
        '<span></span><button class="danger" type="submit">Erase settings and restart</button>'
        '</div></form></section>'
    )
    return portal_ui.shell('IoT-MD power and reset', 'device_control', body, csrf)


def render_factory_default_page(csrf, error=''):
    """Compatibility alias for callers using the former page name."""
    return render_device_control_page(csrf, error)

def render_configuration_backup_page(csrf, message=''):
    body = (
        portal_ui.page_heading(
            'Maintenance', 'Configuration backup',
            'Export or restore configuration, optionally including secrets in a password-encrypted file.'
        ) + _notice(message) +
        '<section class="card"><div class="section-title"><h2>Export</h2></div>'
        '<p class="muted">A standard backup contains operational and module settings. Enable '
        'encryption to also include credentials, login verifiers, private keys, certificates, '
        'ACME state and API clients. Encrypted backup is available only over HTTPS.</p>'
        '<form id="backup-export-form" action="/download-secure-configuration" method="post" '
        'autocomplete="off"><input type="hidden" name="csrf" value="' + html_escape(csrf) + '">'
        '<label class="check"><input id="encrypt-backup" type="checkbox">Encrypt backup and include secrets</label>'
        '<fieldset id="export-encryption" class="conditional-fields" disabled><div class="grid">'
        '<label class="field">Encryption password<input name="backup_password" '
        'type="password" minlength="16" maxlength="256" required></label>'
        '<label class="field">Confirm encryption password<input name="confirm_backup_password" '
        'type="password" minlength="16" maxlength="256" required></label></div></fieldset>'
        '<div class="actions"><span id="backup-export-result" class="portal-status" role="status" '
        'aria-live="polite"></span>'
        '<button id="backup-export" type="button">Download backup</button></div></form></section>'
        '<section class="card"><div class="section-title"><h2>Import</h2></div>'
        '<p class="muted">Every import is validated and previewed before anything is changed.</p>'
        '<label class="check"><input id="encrypted-import" type="checkbox">This is an encrypted complete backup</label>'
        '<label class="field">Backup file<input id="configuration-import-file" '
        'type="file" accept="application/json,.json" required></label>'
        '<fieldset id="import-encryption" class="conditional-fields" disabled>'
        '<label class="field">Encryption password<input id="configuration-import-password" '
        'type="password" minlength="16" maxlength="256"></label>'
        '<fieldset><legend>Restore sections</legend><div class="grid">'
        '<label class="check"><input class="restore-section" type="checkbox" value="credentials" checked>'
        'Operational settings and credentials</label>'
        '<label class="check"><input class="restore-section" type="checkbox" value="module_settings" checked>'
        'Module configuration</label>'
        '<label class="check"><input class="restore-section" type="checkbox" value="certificates_and_trust" checked>'
        'Certificates, keys and trust</label></div></fieldset></fieldset>'
        '<div class="actions"><span id="configuration-import-result" class="portal-status" role="status" '
        'aria-live="polite"></span>'
        '<button id="configuration-action" type="button">Upload and preview</button></div>'
        '<div id="configuration-preview-panel" hidden><div class="section-title">'
        '<h3>Restore preview</h3><span class="badge">Secret values hidden</span></div>'
        '<div id="configuration-diff" class="restore-grid"></div></div>' +
        portal_ui.progress('configuration-progress', 'Waiting…', True) + '</section>'
    )
    script = (
        'var importToken="",importEncrypted=false,csrf=' + repr(str(csrf)) + ';'
        'var encrypt=document.getElementById("encrypt-backup"),exportFields='
        'document.getElementById("export-encryption"),encryptedImport='
        'document.getElementById("encrypted-import"),importFields='
        'document.getElementById("import-encryption"),importFile=document.getElementById('
        '"configuration-import-file"),importPassword=document.getElementById('
        '"configuration-import-password"),actionButton=document.getElementById('
        '"configuration-action");'
        'function toggleExport(){exportFields.disabled=!encrypt.checked;}'
        'function toggleImport(){importFields.disabled=!encryptedImport.checked;document.getElementById('
        '"configuration-import-password").required=encryptedImport.checked;}'
        'function resetImportPreview(){importToken="";actionButton.disabled=false;'
        'actionButton.textContent="Upload and preview";document.getElementById('
        '"configuration-diff").innerHTML="";document.getElementById("configuration-preview-panel").hidden=true;'
        'document.getElementById("configuration-progress").hidden=true;}'
        'function readBackup(file,label){return new Promise(function(resolve,reject){var reader=new FileReader();'
        'reader.onprogress=function(p){if(p.lengthComputable)label.textContent="Reading backup "+Math.round('
        'p.loaded*100/p.total)+"%";};reader.onload=function(){resolve(reader.result);};reader.onerror=function(){'
        'reject(new Error("Could not read the backup file"));};reader.readAsText(file);});}'
        'var validationTimer=null;function startValidationProgress(label){var percent=40;'
        'label.textContent="Validating configuration · "+percent+"% (estimated)";clearInterval(validationTimer);'
        'validationTimer=setInterval(function(){if(percent<95){percent+=percent<70?3:1;label.textContent='
        '"Validating configuration · "+percent+"% (estimated)";}},700);}function stopValidationProgress(){'
        'if(validationTimer){clearInterval(validationTimer);validationTimer=null;}}'
        'function uploadBackup(url,type,body,label){return new Promise(function(resolve,reject){var x='
        'new XMLHttpRequest();x.open("POST",url,true);x.timeout=180000;x.setRequestHeader("Content-Type",type);x.setRequestHeader('
        '"X-CSRF-Token",csrf);x.upload.onprogress=function(p){if(p.lengthComputable)label.textContent='
        '"Uploading backup "+Math.round(p.loaded*100/p.total)+"%";};x.upload.onload=function(){'
        'startValidationProgress(label);};x.onload=function(){stopValidationProgress();label.textContent='
        '"Validating configuration · 100%";if(x.status>=200&&x.status<300)resolve(x.responseText);'
        'else reject(new Error(x.responseText||"Configuration validation failed"));};x.onerror=function(){'
        'stopValidationProgress();reject('
        'new Error("Connection lost during configuration upload"));};x.ontimeout=function(){'
        'stopValidationProgress();reject(new Error("Configuration validation timed out after 3 minutes"));};'
        'x.send(body);});}'
        'encrypt.onchange=toggleExport;encryptedImport.onchange=function(){toggleImport();resetImportPreview();};'
        'importFile.onchange=resetImportPreview;importPassword.oninput=resetImportPreview;toggleExport();toggleImport();'
        'document.getElementById("backup-export").onclick=function(){var out=document.getElementById('
        '"backup-export-result");if(!encrypt.checked){location.assign("/download-configuration");return;}'
        'var form=document.getElementById("backup-export-form"),passwordField=form.elements.backup_password,'
        'confirmField=form.elements.confirm_backup_password,a=passwordField.value,b=confirmField.value;'
        'if(!form.reportValidity())return;if(a.length<16){portalStatus(out,"error",'
        '"Encryption password must contain at least 16 characters");portalInvalid(passwordField,'
        '"Encryption password must contain at least 16 characters");return;}if(a!==b){portalStatus(out,"error",'
        '"Encryption passwords do not match");portalInvalid(confirmField,"Encryption passwords do not match");'
        'return;}form.submit();};'
        'async function previewImport(){var f=importFile.files[0],out='
        'document.getElementById("configuration-import-result"),diff='
        'document.getElementById("configuration-diff"),box='
        'document.getElementById("configuration-progress"),label=box.querySelector(".status-text");'
        'if(!f){portalStatus(out,"error","Select a configuration backup");portalRequire(importFile,'
        '"Select a configuration backup");return;}portalStatus(out,"","");box.hidden=false;'
        'box.classList.remove("complete","failed");label.textContent="Preparing upload…";'
        'this.disabled=true;importEncrypted=encryptedImport.checked;try{var r,p,diffRows=[];if(importEncrypted){'
        'var password=document.getElementById("configuration-import-password").value;if(!password){'
        'portalRequire(importPassword,"Enter the encryption password");throw new Error("Enter the encryption password");}'
        'var sections=[],sectionBoxes=document.querySelectorAll(".restore-section");for(var s=0;s<sectionBoxes.length;s++)'
        'if(sectionBoxes[s].checked)sections.push(sectionBoxes[s].value);if(!sections.length)throw new Error('
        '"Select at least one restore section");'
        'var backup=JSON.parse(await readBackup(f,label));r=await uploadBackup('
        '"/secure-configuration-import-preview","application/json",JSON.stringify({password:password,'
        'backup:backup,sections:sections}),label);p=JSON.parse(r);importToken=p.token;diffRows=p.changes||[];'
        'portalStatus(out,"success","Encrypted backup verified. Review the restore preview below.");}else{'
        'r=await uploadBackup('
        '"/configuration-import-preview","application/json",f,label);p=JSON.parse(r);importToken=p.token;'
        'diffRows=p.changes;portalStatus(out,"success",p.change_count+" change(s) validated");}'
        'diff.innerHTML="";for(var i=0;i<diffRows.length;i++){var c=diffRows[i],'
        'before=typeof c.before==="string"?c.before:JSON.stringify(c.before),after=typeof c.after==="string"?'
        'c.after:JSON.stringify(c.after),missing=after==null||after===""||after==="null"||after==="undefined",'
        'state=c.state||(missing?"missing":before===after?"same":"changed"),row=document.createElement("div");'
        'row.className="restore-card "+state;var head=document.createElement("div"),name=document.createElement('
        '"strong"),badge=document.createElement("span");head.className="restore-card-head";name.textContent=c.path;'
        'badge.className="restore-state";badge.textContent=state;head.appendChild(name);head.appendChild(badge);'
        'row.appendChild(head);if(state==="same"){var value=document.createElement("div");value.className='
        '"restore-value";value.textContent=after;row.appendChild(value);}else{var compare=document.createElement("div");'
        'compare.className="restore-compare";function pane(labelText,text){var box=document.createElement("div"),'
        'labelNode=document.createElement("span"),strong=document.createElement("strong");box.className="restore-pane";'
        'labelNode.textContent=labelText;strong.textContent=text||"Missing";box.appendChild(labelNode);box.appendChild('
        'strong);return box;}compare.appendChild(pane("Current",before));compare.appendChild(pane("Backup",after));'
        'row.appendChild(compare);}diff.appendChild(row);}'
        'document.getElementById("configuration-preview-panel").hidden=false;'
        'this.disabled=!importEncrypted&&p.change_count===0;this.textContent="Apply configuration";'
        'box.classList.add("complete");label.textContent="Preview ready";'
        '}catch(e){portalStatus(out,"error",e.message);box.classList.add("failed");'
        'label.textContent="Validation failed";'
        'this.disabled=false;this.textContent="Upload and preview";}};'
        'async function applyImport(){var box='
        'document.getElementById("configuration-progress"),label=box.querySelector(".status-text");'
        'this.disabled=true;box.classList.remove("complete","failed");box.hidden=false;label.textContent='
        '"Applying configuration…";try{var endpoint=importEncrypted?'
        '"/secure-configuration-import-apply":"/configuration-import-apply",r=await fetch(endpoint,{method:"POST",'
        'credentials:"same-origin",headers:{"Content-Type":"application/json","X-CSRF-Token":csrf},'
        'body:JSON.stringify({token:importToken})});if(!r.ok)throw new Error(await r.text());document.open();'
        'document.write(await r.text());document.close();}catch(e){portalStatus(document.getElementById('
        '"configuration-import-result"),"error",e.message);box.classList.add("failed");'
        'label.textContent="Import failed";this.disabled=false;}}'
        'actionButton.onclick=function(){return importToken?applyImport.call(actionButton):'
        'previewImport.call(actionButton);};'
    )
    return portal_ui.shell(
        'IoT-MD configuration backup', 'configuration_backup', body, csrf, script
    )

def _health_time_text(epoch, timezone_name='UTC'):
    try:
        value = int(epoch or 0)
        if value <= 0:
            return 'Time unavailable'
        current = timezone_rules.localtime(value, timezone_name)
        return '{:04}-{:02}-{:02} {:02}:{:02}:{:02}'.format(
            current[0], current[1], current[2], current[3], current[4], current[5]
        )
    except Exception:
        return 'Time unavailable'

def _health_value(value, timezone_name='UTC'):
    if isinstance(value, dict):
        return ', '.join(
            render_label(key) + ': ' + (
                _health_time_text(value[key], timezone_name)
                if key == 'time' else str(value[key])
            ) for key in value
        )
    return str(value)


def _latest_health_time(health):
    """Return the newest persisted health timestamp available."""
    candidates = [health.get('updated_at', 0)]
    observations = health.get('observations', {}) or {}
    candidates.append(observations.get('last_heap_observed_at', 0))
    for value in observations.values():
        if isinstance(value, dict):
            candidates.append(value.get('time', 0))
    for event in health.get('events', ()) or ():
        if isinstance(event, dict):
            candidates.append(event.get('time', 0))
    valid = []
    for value in candidates:
        try:
            value = int(value or 0)
        except (TypeError, ValueError):
            continue
        if value > 0:
            valid.append(value)
    return max(valid) if valid else 0

def render_health_history_page(csrf, status):
    health = (status or {}).get('health_history', {}) or {}
    counters = health.get('counters', {}) or {}
    observations = health.get('observations', {}) or {}
    timezone_name = (status or {}).get('timezone_name', 'UTC')
    data_groups = (
        ('Device',
         ('boots', 'watchdog_resets'),
         ('last_reset_cause', 'last_startup_exception', 'current_free_heap',
          'current_allocated_heap', 'minimum_free_heap',
          'last_heap_observed_at')),
        ('Network',
         ('wifi_reconnects',),
         ('last_wifi_rssi', 'minimum_wifi_rssi')),
        ('MQTT',
         ('mqtt_publish_drops', 'mqtt_publish_failures'),
         ()),
        ('API',
         ('api_requests', 'api_commands', 'api_failures'),
         ()),
        ('Upgrades', (), ('last_update_result',)),
    )
    grouped = []
    shown_counters = set()
    # Scheduler persistence is shown on Upgrades, not duplicated as health data.
    shown_observations = {'last_release_check'}

    def health_item(key, value, label=None):
        return (
            '<div class="health-item"><span>' + html_escape(
                label if label is not None else render_label(key)
            ) + '</span><strong>' +
            html_escape(value) + '</strong></div>'
        )

    def update_result_items(value):
        if not isinstance(value, dict) or not value:
            return health_item('last_update_result', 'No upgrade recorded')
        rows = []
        for key, label in (
            ('kind', 'Type'), ('result', 'Result'), ('version', 'Version'),
            ('time', 'Completed at'), ('detail', 'Detail')
        ):
            item = value.get(key)
            if item in (None, ''):
                continue
            rows.append(health_item(
                key,
                _health_time_text(item, timezone_name) if key == 'time' else item,
                label
            ))
        return ''.join(rows) or health_item(
            'last_update_result', 'No upgrade recorded'
        )

    for title, counter_keys, observation_keys in data_groups:
        rows = []
        for key in counter_keys:
            if key in counters:
                shown_counters.add(key)
                rows.append(health_item(key, counters[key]))
        for key in observation_keys:
            if key in observations:
                shown_observations.add(key)
                rows.append(
                    update_result_items(observations[key])
                    if key == 'last_update_result' else health_item(
                        key, (
                            _health_time_text(observations[key], timezone_name)
                            if key == 'last_heap_observed_at' else
                            _health_value(observations[key], timezone_name)
                        )
                    )
                )
        if rows:
            grouped.append(
                '<section class="health-group"><h3>' + title +
                '</h3><div class="health-items">' + ''.join(rows) + '</div></section>'
            )

    remaining = []
    for key in counters:
        if key not in shown_counters:
            remaining.append(health_item(key, counters[key]))
    for key in observations:
        if key not in shown_observations:
            remaining.append(health_item(
                key, _health_value(observations[key], timezone_name)
            ))
    if remaining:
        grouped.append(
            '<section class="health-group"><h3>Other</h3><div class="health-items">' +
            ''.join(remaining) + '</div></section>'
        )
    feature_state = ((status or {}).get('feature_flags', {}) or {}).get('features', {}) or {}
    enabled_features = ', '.join(
        render_label(key) for key in sorted(feature_state)
        if (feature_state.get(key, {}) or {}).get('enabled') is True
    ) or 'None'
    runtime_rows = ''.join((
        health_item('device_state', (status or {}).get('device_state', 'unknown')),
        health_item('boot_stage', (status or {}).get('boot_stage', 'unknown')),
        health_item('network_transport', (status or {}).get('network_transport', 'Wi-Fi')),
        health_item('hardware_resources', (status or {}).get('hardware_resources', 0), 'Allocated hardware resources'),
        health_item('usb_ncm_available', 'Yes' if (status or {}).get('usb_ncm_available') else 'No'),
        health_item('feature_flags', enabled_features, 'Enabled runtime features'),
    ))
    events = []
    for event in list(health.get('events', []))[-24:][::-1]:
        events.append(
            '<li><time>' + html_escape(_health_time_text(event.get('time'), timezone_name)) +
            '</time> — <strong>' + html_escape(event.get('kind', '')) + '</strong> ' +
            html_escape(event.get('detail', '')) + '</li>'
        )
    body = (
        portal_ui.page_heading(
            'Maintenance', 'Health history',
            'Persistent reset, connectivity, memory, MQTT, API and upgrade health information.'
        ) + '<section class="card"><div class="section-title"><h2>Health data</h2>'
        '<span class="badge">Updated ' + html_escape(_health_time_text(
            _latest_health_time(health), timezone_name
        )) + '</span></div>' +
        '<div class="health-groups">' + ''.join(grouped) + '</div></section>'
        '<section class="card"><div class="section-title"><h2>Current runtime health</h2></div>'
        '<div class="health-items">' + runtime_rows + '</div></section>'
        '<section class="card"><div class="section-title"><h2>Recent significant events</h2></div>'
        + ('<ul>' + ''.join(events) + '</ul>' if events else '<p class="muted">No events recorded.</p>') +
        '</section><section class="card"><div class="section-title"><h2>Reset history</h2></div>'
        '<p class="muted">Clear all persistent health counters, observations and events.</p>'
        '<form action="/reset-health-history" method="post"><input type="hidden" name="csrf" value="' +
        html_escape(csrf) + '"><div class="actions"><span></span><button class="danger" '
        'type="submit">Reset health history</button></div></form></section>'
    )
    return portal_ui.shell('IoT-MD health history', 'health_history', body, csrf)

def render_factory_default_complete_page(csrf):
    body = (
        portal_ui.page_heading(
            'Maintenance', 'Factory reset armed',
            'The immutable recovery layer will erase user data and open first-boot setup.'
        ) + '<section class="card"><p class="notice">The device is restarting.</p>'
        '<p>When this network disconnects, join the <strong>IoT-MD-Setup-xxxxxx</strong> '
        'access point with the setup password you just chose and browse to '
        '<a href="http://192.168.4.1/"><strong>http://192.168.4.1</strong></a>.</p>'
        '<div class="page-load-action"><a class="button" href="http://192.168.4.1/">'
        'Open device setup</a></div></section>'
    )
    return portal_ui.shell('IoT-MD factory reset', 'device_control', body, csrf)


def render_shutdown_complete_page(message):
    body = (
        portal_ui.page_heading(
            'Maintenance', 'Device shutting down',
            'The device will stop network and application services.'
        ) + '<section class="card"><p class="notice">' + html_escape(message) +
        '</p><p>No configuration or installed software is erased.</p></section>'
    )
    return portal_ui.shell(
        'IoT-MD device shutdown', 'device_control', body, authenticated=False
    )


# Certificate pages are separated from general settings so enrollment, trust,
# API callers, and presented identities can evolve independently.  Retain these
# compatibility exports as lazy wrappers: importing all general settings during
# boot must not also allocate the certificate-administration view module.
def render_certificate_page(*args, **kwargs):
    from certificate_portal_views import render_certificate_page as render
    return render(*args, **kwargs)


def render_certificate_route(*args, **kwargs):
    from certificate_portal_views import render_certificate_route as render
    return render(*args, **kwargs)

"""Focused certificate enrollment, trust, and identity portal pages."""

import web_portal_ui as portal_ui
from portal_http import html_escape
from portal_presenters import render_badge


METHODS = {
    'self_signed': (
        'Self-signed device certificate',
        'Generated and automatically renewed by this device. Browsers will not trust it by default.'
    ),
    'iot_ca_auto': (
        'Automatic IoT CA enrollment',
        'Requests a managed public portal and private Device API identity during an enabled IoT CA window.'
    ),
    'iot_ca_file': (
        'IoT CA enrollment authorization (.iotenroll)',
        'Uses a one-time IoT CA authorization file; the resulting identities renew automatically.'
    ),
    'acme': (
        'Private CA ACME enrollment',
        'Enrolls and automatically renews the local portal identity using a private ACME directory.'
    ),
    'manual': (
        'Manual certificate package',
        'Installs administrator-supplied identities. Automatic renewal is unavailable.'
    ),
}


def _notice(message='', error=False):
    if not message:
        return ''
    return '<p class="' + ('error' if error else 'notice') + '">' + html_escape(message) + '</p>'


def _method(certificates):
    settings = (certificates or {}).get('acme_settings', {}) or {}
    mode = str(settings.get('mode', 'manual'))
    return str(settings.get('method', 'iot_ca_auto' if mode == 'iot_ca' else mode))


def _card(details, label, actions=''):
    details = details or {}
    installed = bool(details.get('installed'))
    level = details.get('expiry_level', 'ok' if installed else 'missing')
    badge = render_badge(
        'expired' if level == 'expired' else (
            str(details.get('days_remaining')) + ' days'
            if level in ('warning', 'critical') else ('installed' if installed else 'not installed')
        ), 'good' if installed and level == 'ok' else 'warn'
    )
    rows = []
    if details.get('error'):
        rows.append('<p class="error-text">Unable to decode: ' + html_escape(details['error']) + '</p>')
    elif installed:
        for key, title in (
            ('subject', 'Subject'), ('issuer', 'Issuer'), ('not_after', 'Valid until'),
            ('serial_number', 'Serial number'), ('fingerprint', 'SHA-256 fingerprint'),
            ('size', 'File size (bytes)')
        ):
            if details.get(key) not in (None, ''):
                rows.append('<div class="property-row"><span>' + title + '</span><strong>' +
                            html_escape(details[key]) + '</strong></div>')
    else:
        rows.append('<p class="muted">No file is installed.</p>')
    return ('<article class="module-card"><div class="module-head"><h3>' + label + '</h3>' + badge +
            '</div><div class="property-grid">' + ''.join(rows) + '</div>' + actions + '</article>')


def _remove_form(csrf, kind, fingerprint='', return_to='/certificate-authorities'):
    return ('<form method="post" action="/remove-certificate-trust">'
            '<input type="hidden" name="csrf" value="' + html_escape(csrf) + '">'
            '<input type="hidden" name="kind" value="' + html_escape(kind) + '">'
            '<input type="hidden" name="fingerprint" value="' + html_escape(fingerprint) + '">'
            '<input type="hidden" name="return_to" value="' + html_escape(return_to) + '">'
            '<div class="actions"><span></span><button class="danger compact" type="submit">Remove trust</button></div></form>')


def _upload_widget(csrf, choices, return_label):
    options = ''.join('<option value="' + value + '">' + label + '</option>' for value, label, _help in choices)
    descriptions = ','.join('"' + value + '":["' + label + '","' + help_text + '"]'
                            for value, label, help_text in choices)
    body = ('<label class="field">Certificate or trust type<select id="certificate-type">' + options +
            '</select></label><label id="certificate-primary-label" class="field">File'
            '<input id="certificate-primary" type="file" required></label>'
            '<p id="certificate-help" class="muted"></p><div class="actions">'
            '<span id="certificate-result" class="portal-status"></span>'
            '<button id="certificate-upload" type="button">Upload and validate</button></div>' +
            portal_ui.progress('certificate-progress', 'Waiting…', True))
    script = ('var csrf=' + repr(str(csrf)) + ',type=document.getElementById("certificate-type"),'
              'file=document.getElementById("certificate-primary"),help=document.getElementById("certificate-help"),'
              'descriptions={' + descriptions + '};function configure(){help.textContent=descriptions[type.value][1];'
              'file.multiple=type.value==="api-client-ca"||type.value==="api-client-cert"||type.value==="fleet-client-cert";'
              'file.accept=type.value==="management-suite-key"?".bin,.hex,application/octet-stream":'
              '(type.value==="portal-cert"?".der,.pem,application/pkix-cert,application/x-pem-file":'
              '".der,application/pkix-cert,application/octet-stream");}type.onchange=configure;configure();'
              'function upload(f,k){return fetch("/certificate-upload",{method:"POST",credentials:"same-origin",headers:{'
              '"Content-Type":"application/octet-stream","X-CSRF-Token":csrf,"X-Certificate-Kind":k},body:f});}'
              'document.getElementById("certificate-upload").onclick=async function(){var out=document.getElementById('
              '"certificate-result"),box=document.getElementById("certificate-progress"),label=box.querySelector(".status-text");'
              'if(!portalRequire(file,"Select at least one file"))return;this.disabled=true;box.hidden=false;'
              'try{for(var i=0;i<file.files.length;i++){label.textContent="Uploading "+(i+1)+" of "+file.files.length;'
              'var response=await upload(file.files[i],type.value);if(!response.ok)throw new Error(await response.text());}'
              'label.textContent="Validating…";var done=await fetch("/validate-certificates",{method:"POST",credentials:'
              '"same-origin",headers:{"Content-Type":"application/x-www-form-urlencoded"},body:"csrf="+encodeURIComponent(csrf)+'
              '"&return_to="+encodeURIComponent(' + repr(return_label) + ')});if(!done.ok)throw new Error(await done.text());'
              'document.open();document.write(await done.text());document.close();}catch(error){portalStatus(out,"error",error.message);'
              'box.classList.add("failed");label.textContent="Installation failed";this.disabled=false;}};')
    return body, script


def _identity_upload_widget(csrf, return_to='/device-certificates'):
    body = ('<label class="field">Device identity<select id="identity-type">'
            '<option value="portal">Portal HTTPS identity</option>'
            '<option value="api-server">Device API server identity</option></select></label>'
            '<div class="grid"><label id="identity-cert-label" class="field">Certificate chain'
            '<input id="identity-cert" type="file" accept=".der,.pem,application/pkix-cert,application/x-pem-file" required></label>'
            '<label class="field">Matching private key<input id="identity-key" type="file" accept=".der,application/octet-stream" required></label></div>'
            '<p class="muted">The matching certificate and private key are validated and committed atomically.</p>'
            '<div class="actions"><span id="identity-result" class="portal-status"></span>'
            '<button id="identity-upload" type="button">Upload and validate</button></div>' +
            portal_ui.progress('identity-progress', 'Waiting…', True))
    script = ('var identityType=document.getElementById("identity-type"),identityCert=document.getElementById('
              '"identity-cert"),identityKey=document.getElementById("identity-key"),identityCsrf=' + repr(str(csrf)) + ';'
              'identityType.onchange=function(){document.getElementById("identity-cert-label").firstChild.nodeValue='
              'this.value==="portal"?"Portal certificate chain":"Device API server certificate";};'
              'function uploadIdentity(file,kind){return fetch("/certificate-upload",{method:"POST",credentials:"same-origin",headers:{'
              '"Content-Type":"application/octet-stream","X-CSRF-Token":identityCsrf,"X-Certificate-Kind":kind},body:file});}'
              'document.getElementById("identity-upload").onclick=async function(){var out=document.getElementById("identity-result"),'
              'box=document.getElementById("identity-progress"),label=box.querySelector(".status-text"),kind=identityType.value;'
              'if(!portalRequire(identityCert,"Select the certificate")||!portalRequire(identityKey,"Select the matching private key"))return;'
              'this.disabled=true;box.hidden=false;try{label.textContent="Uploading certificate…";var first=await uploadIdentity('
              'identityCert.files[0],kind+"-cert");if(!first.ok)throw new Error(await first.text());label.textContent="Uploading private key…";'
              'var second=await uploadIdentity(identityKey.files[0],kind+"-key");if(!second.ok)throw new Error(await second.text());'
              'label.textContent="Validating identity…";var done=await fetch("/validate-certificates",{method:"POST",credentials:"same-origin",'
              'headers:{"Content-Type":"application/x-www-form-urlencoded"},body:"csrf="+encodeURIComponent(identityCsrf)+'
              '"&return_to="+encodeURIComponent(' + repr(str(return_to)) + ')});if(!done.ok)throw new Error(await done.text());document.open();document.write('
              'await done.text());document.close();}catch(error){portalStatus(out,"error",error.message);box.classList.add("failed");'
              'label.textContent="Installation failed";this.disabled=false;}};')
    return body, script


def render_certificate_page(csrf, message='', certificates=None):
    certificates = certificates or {}
    settings = certificates.get('acme_settings', {}) or {}
    method = _method(certificates)
    label, description = METHODS.get(method, ('Unknown certificate method', 'Review and select a supported method.'))
    operation = certificates.get('enrollment_operation', {}) or {}
    operation_notice = ''
    if operation.get('status', 'idle') not in ('', 'idle'):
        tone = 'error' if operation.get('status') == 'error' else ('success' if operation.get('status') == 'complete' else 'info')
        operation_notice = '<section class="portal-status ' + tone + '"><strong>' + html_escape(operation.get('message', '')) + '</strong></section>'
    options = ''.join('<option value="' + key + '"' + (' selected' if key == method else '') + '>' + value[0] + '</option>'
                      for key, value in METHODS.items())
    manual_upload, manual_script = _identity_upload_widget(csrf, '/certificates')
    body = (portal_ui.page_heading('Maintenance', 'Certificate enrollment',
            'Review the active enrollment method and change how device identities are issued and renewed.') +
            _notice(message) + operation_notice +
            '<section class="card"><div class="section-title"><h2>Current enrollment</h2>' +
            render_badge(label, 'good' if method != 'manual' else 'warn') + '</div><p>' + html_escape(description) + '</p></section>'
            '<section class="card"><div class="section-title"><h2>Change enrollment method</h2></div>'
            '<label class="field">Enrollment method<select id="enrollment-method">' + options + '</select></label>'
            '<div class="certificate-option-panel" data-method="self_signed"><p>' + html_escape(METHODS['self_signed'][1]) + '</p>'
            '<form action="/certificate-method" method="post"><input type="hidden" name="csrf" value="' + html_escape(csrf) + '">'
            '<input type="hidden" name="method" value="self_signed"><button type="submit">Install self-signed identity</button></form></div>'
            '<div class="certificate-option-panel" data-method="iot_ca_auto"><p>' + html_escape(METHODS['iot_ca_auto'][1]) + '</p>'
            '<form action="/certificate-method" method="post"><input type="hidden" name="csrf" value="' + html_escape(csrf) + '">'
            '<input type="hidden" name="method" value="iot_ca_auto"><div class="grid">'
            '<label class="field">IoT CA server<input name="ca_server" placeholder="iot-ca.home.arpa"></label>'
            '<label class="field">Provisioning port<input name="ca_port" type="number" min="1" max="65535" placeholder="9010"></label></div>'
            '<button type="submit">Start automatic enrollment</button></form></div>'
            '<div class="certificate-option-panel" data-method="iot_ca_file"><p>' + html_escape(METHODS['iot_ca_file'][1]) + '</p>'
            '<label class="field">IoT CA enrollment authorization<input id="iotenroll-file" type="file" accept=".iotenroll,application/json"></label>'
            '<button id="iotenroll-start" type="button">Upload and enroll</button></div>'
            '<div class="certificate-option-panel" data-method="acme"><p>' + html_escape(METHODS['acme'][1]) + '</p>'
            '<form action="/acme-settings" method="post"><input type="hidden" name="csrf" value="' + html_escape(csrf) + '">'
            '<input type="hidden" name="acme_enabled" value="true"><div class="grid">'
            '<label class="field">ACME directory URL<input name="directory_url" type="url" required value="' + html_escape(settings.get('directory_url', '')) + '"></label>'
            '<label class="field">Certificate hostname<input name="hostname" required value="' + html_escape(settings.get('hostname', '')) + '"></label></div>'
            '<button type="submit">Enable Private CA ACME enrollment</button></form></div>'
            '<div class="certificate-option-panel" data-method="manual"><p>' + html_escape(METHODS['manual'][1]) + '</p>'
            '<p class="warning-text">Manual identities are not automatically renewed. The portal and Device log warn before expiry.</p>' +
            manual_upload + '</div></section>')
    script = ('var chooser=document.getElementById("enrollment-method"),csrf=' + repr(str(csrf)) + ';function showMethod(){'
              'document.querySelectorAll("[data-method]").forEach(function(p){p.hidden=p.dataset.method!==chooser.value;});}'
              'chooser.onchange=showMethod;showMethod();document.getElementById("iotenroll-start").onclick=async function(){'
              'var input=document.getElementById("iotenroll-file");if(!portalRequire(input,"Select an .iotenroll file"))return;'
              'this.disabled=true;try{var uploaded=await fetch("/certificate-upload",{method:"POST",credentials:"same-origin",headers:{'
              '"Content-Type":"application/octet-stream","X-CSRF-Token":csrf,"X-Certificate-Kind":"iot-ca-enrollment"},body:input.files[0]});'
              'if(!uploaded.ok)throw new Error(await uploaded.text());var done=await fetch("/certificate-method",{method:"POST",credentials:'
              '"same-origin",headers:{"Content-Type":"application/x-www-form-urlencoded"},body:"csrf="+encodeURIComponent(csrf)+'
              '"&method=iot_ca_file"});document.open();document.write(await done.text());document.close();}catch(error){alert(error.message);this.disabled=false;}};')
    return portal_ui.shell(
        'IoT-MD certificate enrollment', 'certificates', body, csrf,
        script + manual_script
    )


def render_certificate_authorities_page(csrf, message='', certificates=None):
    certificates = certificates or {}
    cards = []
    for key, detail_key, label in (
        ('mqtt-ca', 'mqtt_ca', 'MQTT broker CA'),
        ('release-ca', 'release_ca', 'Release server CA'),
        ('syslog-ca', 'syslog_ca', 'Syslog server CA'),
        ('management-suite-key', 'management_suite_key', 'Management Suite signing key'),
    ):
        details = certificates.get(detail_key, {}) or {}
        cards.append(_card(details, label, _remove_form(csrf, key) if details.get('installed') else ''))
    upload, script = _upload_widget(csrf, (
        ('mqtt-ca', 'MQTT broker CA', 'Authenticates the configured MQTT broker.'),
        ('release-ca', 'Release server CA', 'Authenticates the release and Management Suite endpoint.'),
        ('syslog-ca', 'Syslog server CA', 'Authenticates the encrypted remote syslog server.'),
        ('management-suite-key', 'Management Suite signing key', 'Verifies fleet policy and format-3 release catalogs.'),
    ), '/certificate-authorities')
    body = (portal_ui.page_heading('Maintenance', 'CA & signing trust',
            'Manage outbound service trust anchors and the Management Suite signing key.') + _notice(message) +
            '<section class="card"><div class="module-grid">' + ''.join(cards) + '</div></section>'
            '<section class="card"><div class="section-title"><h2>Install trust</h2></div>' + upload + '</section>')
    return portal_ui.shell('IoT-MD CA and signing trust', 'certificate_authorities', body, csrf, script)


def render_api_client_trust_page(csrf, message='', certificates=None):
    certificates = certificates or {}
    ca_cards = []
    for index, details in enumerate(certificates.get('api_client_cas', ()) or ()):
        ca_cards.append(_card(details, 'Device API client issuer CA ' + str(index + 1),
                              _remove_form(csrf, 'api-client-ca', details.get('fingerprint', ''), '/api-client-trust')))
    clients = []
    for details in certificates.get('api_clients', ()) or ():
        action = ('<form method="post" action="/revoke-api-client"><input type="hidden" name="csrf" value="' + html_escape(csrf) +
                  '"><input type="hidden" name="fingerprint" value="' + html_escape(details.get('fingerprint', '')) +
                  '"><input type="hidden" name="return_to" value="/api-client-trust"' +
                  '"><div class="actions"><span></span><button class="danger compact">Revoke client</button></div></form>')
        clients.append(_card(dict(details, installed=True), details.get('label', 'Device API caller'), action))
    upload, script = _upload_widget(csrf, (
        ('api-client-ca', 'Device API client issuer CA', 'Trusts certificates presented by approved Device API callers.'),
        ('api-client-cert', 'Device API caller certificate', 'Enrolls a client identity with Device API read/write scopes.'),
        ('fleet-client-cert', 'Management Suite Device API caller certificate', 'Enrolls the Management Suite identity with fleet scopes.'),
    ), '/api-client-trust')
    body = (portal_ui.page_heading('Maintenance', 'API client trust',
            'Manage who may authenticate to the mutual-TLS Device API.') + _notice(message) +
            '<section class="card"><div class="section-title"><h2>Trusted client issuers</h2></div><div class="module-grid">' +
            (''.join(ca_cards) or '<p class="muted">No Device API client issuer CA is installed.</p>') + '</div></section>'
            '<section class="card"><div class="section-title"><h2>Enrolled API callers</h2></div><div class="module-grid">' +
            (''.join(clients) or '<p class="muted">No Device API caller certificate is enrolled.</p>') + '</div></section>'
            '<section class="card"><div class="section-title"><h2>Install API trust</h2></div>' + upload + '</section>')
    return portal_ui.shell('IoT-MD API client trust', 'api_client_trust', body, csrf, script)


def render_device_certificates_page(csrf, message='', certificates=None):
    certificates = certificates or {}
    upload, script = _identity_upload_widget(csrf)
    body = (portal_ui.page_heading('Maintenance', 'Device certificates',
            'Inspect identities presented by this device. Managed identities are replaced through Certificate enrollment.') + _notice(message) +
            '<section class="card"><div class="module-grid">' +
            _card(certificates.get('portal'), 'Portal HTTPS identity') +
            _card(certificates.get('api_server'), 'Device API server identity') + '</div></section>'
            '<section class="card"><div class="section-title"><h2>Manual identity installation</h2></div>'
            '<p class="warning-text">Manual identities are not automatically renewed. The portal and Device log warn before expiry.</p>' +
            upload + '</section>')
    return portal_ui.shell('IoT-MD device certificates', 'device_certificates', body, csrf, script)


def render_certificate_route(route, csrf, message='', certificates=None):
    return {
        '/certificates': render_certificate_page,
        '/certificate-authorities': render_certificate_authorities_page,
        '/api-client-trust': render_api_client_trust_page,
        '/device-certificates': render_device_certificates_page,
    }.get(route, render_certificate_page)(csrf, message, certificates)

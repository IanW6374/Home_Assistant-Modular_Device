"""Live status, diagnostics, logging, and update page renderers."""

try:
    import json
except ImportError:
    json = None

import web_portal_ui as portal_ui
from portal_http import html_escape, js_escape, render_logs_html
from portal_settings_views import _notice, render_operational_hidden_fields
from portal_view_models import overview_metrics, update_check_summary
from device_modules.base import module_diagnostics_need_attention
from portal_presenters import (
    diagnostic_help, friendly_label, render_badge, render_label,
)

def render_refresh_controls_html(button_id='refresh-toggle', refresh_scope='log and value'):
    return (
        '<div class="refresh-controls">' +
        '<span class="badge good refresh-status">auto refresh</span>' +
        '<button id="' + html_escape(button_id) + '" class="secondary compact refresh-toggle" type="button" ' +
        'title="Pause or resume ' + html_escape(refresh_scope) + ' auto refresh.">Pause</button>' +
        '</div>'
    )

def display_release_version(value):
    """Remove internal core and MicroPython decoration from a release label."""
    value = str(value or '')
    for prefix in ('iotmd-core-', 'core-'):
        if value.startswith(prefix):
            value = value[len(prefix):]
            break
    marker = value.find('-mpy')
    if marker > 0:
        value = value[:marker]
    return value

def staged_version_text(status):
    application = str(status.get('update_version', '') or '')
    firmware = display_release_version(status.get('firmware_update_version', ''))
    universal = str(status.get('universal_update_version', '') or '')
    application_ready = status.get('update_status') == 'ready' and application
    firmware_ready = status.get('firmware_update_status') == 'ready' and firmware
    universal_ready = (
        status.get('universal_update_status') == 'ready' and universal
    )
    if universal_ready:
        return 'Universal — ' + universal
    if application_ready and firmware_ready:
        return (
            'Application — ' + application +
            ' / Core firmware — ' + firmware
        )
    if firmware_ready:
        return 'Core firmware — ' + firmware
    if application_ready:
        return 'Application — ' + application
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

def update_status_tone(value):
    value = str(value or '').lower()
    if any(marker in value for marker in ('failed', 'error', 'rejected', 'rollback')):
        return 'bad'
    if value and all(part in ('ready', 'complete') for part in value.replace('/', ' ').split() if part not in ('app', 'firmware')):
        return 'good'
    if any(marker in value for marker in ('checking', 'download', 'upload', 'writing', 'verif', 'staging')):
        return 'info'
    return '' if value in ('', 'idle') else 'warn'

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

def render_modules_html(modules, token, role='administrator'):
    return portal_ui.restrict_actions(
        ''.join(render_modules_parts(modules, token)), role
    )

def render_live_sections_parts(status, modules, token):
    parts = ['<div id="live-sections">', render_status_html(status or {})]
    parts.extend(render_modules_parts(modules or [], token))
    parts.append('</div>')
    return parts

def render_live_sections_html(status, modules, token, role='administrator'):
    return portal_ui.restrict_actions(
        ''.join(render_live_sections_parts(status, modules, token)), role
    )

def render_update_summary_html(status):
    status = status or {}
    staged = staged_version_text(status)
    update_status = combined_update_status_text(status)
    update_tone = update_status_tone(update_status)
    availability = str(
        status.get('firmware_update_availability', 'Unknown') or 'Unknown'
    )
    availability_tone = ' good' if availability.lower() == 'ready' else ' warn'
    release_check = update_check_summary(status)
    release_status = release_check['status']
    release_text = release_check['text']
    release_tone = (' ' + release_check['tone']) if release_check['tone'] else ''
    paired = status.get('paired_update', {}) or {}
    paired_html = ''
    if int(paired.get('total_steps', 0) or 0) > 1:
        paired_html = (
            '<p class="portal-status" role="status" aria-live="polite"><strong>' +
            html_escape(portal_ui.capitalized(paired.get('active_type', ''))) +
            ' step ' + html_escape(paired.get('step', 0)) + ' of ' +
            html_escape(paired.get('total_steps', 0)) + '</strong> — ' +
            html_escape(paired.get('status', '')) + '</p>'
        )
    history = status.get('update_history', [])
    history_html = ''
    if history:
        rows = []
        for entry in list(history)[-5:][::-1]:
            entry_version = entry.get('version', '')
            if entry.get('kind') == 'firmware':
                entry_version = display_release_version(entry_version)
            rows.append(
                '<li><strong>' + html_escape(entry.get('event', '')) + '</strong> ' +
                html_escape(entry.get('kind', '')) + ' ' +
                html_escape(entry_version) +
                (' — ' + html_escape(entry.get('detail', '')) if entry.get('detail') else '') +
                '</li>'
            )
        history_html = '<details class="update-history"><summary>Recent update history</summary><ul>' + ''.join(rows) + '</ul></details>'
    return (
        '<div id="update-summary" class="update-summary">' +
        '<div class="metric update-staged"><span>' + render_label('update_version') +
        '</span><strong title="' + html_escape(staged) + '">' + html_escape(staged) + '</strong></div>' +
        '<div class="metric update-status' + ((' ' + update_tone) if update_tone else '') + '"><span>' +
        render_label('update_status') +
        '</span><strong title="' + html_escape(update_status) + '">' + html_escape(update_status) + '</strong></div>' +
        '<div class="metric ota-availability' + availability_tone + '"><span>' +
        render_label('firmware_update_availability') + '</span><strong title="' +
        html_escape(availability) + '">' + html_escape(availability) + '</strong></div>' +
        '<div class="metric release-check' + release_tone + '"><span>' +
        render_label('release_check_status') + '</span><strong title="' +
        html_escape(release_text) + '">' + html_escape(release_text) + '</strong></div>' +
        paired_html + history_html +
        ('<p class="portal-status warning" role="status">Available ' +
         html_escape(status.get('release_available_type', '')) +
         ' release: ' + html_escape(
             display_release_version(status.get('release_available_version', ''))
             if status.get('release_available_type') == 'firmware' else
             status.get('release_available_version', '')
         ) + '</p>'
         if status.get('release_available_version') else '') + '</div>'
    )

def render_update_activation_html(status, token):
    if (
        not status or status.get('update_status') != 'ready' or
        status.get('universal_update_status') == 'ready'
    ):
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
    if update_status == 'ready' and status.get('universal_update_status') != 'ready':
        return (
            '<form action="/activate-firmware" method="post">' +
            '<input type="hidden" name="csrf" value="' + html_escape(token) + '">' +
            '<button class="secondary" type="submit" title="Boot the verified inactive firmware partition and require a healthy startup confirmation.">Activate firmware and reboot</button>' +
            '</form>'
        )
    return ''

def render_universal_update_html(status, token):
    if not status or status.get('universal_update_status') != 'ready':
        return ''
    version = str(status.get('universal_update_version', ''))
    return (
        '<form action="/activate-universal" method="post">'
        '<input type="hidden" name="csrf" value="' + html_escape(token) + '">'
        '<button class="secondary" type="submit" title="Boot the staged core and application '
        'together and confirm both after the portal health check.">Activate universal update' +
        ((' ' + html_escape(version)) if version else '') + ' and reboot</button></form>'
    )

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
        if release_type == 'firmware':
            available = display_release_version(available)
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
    values = []
    for metric in overview_metrics(status):
        key = metric['key']
        label = metric['label']
        value = metric['value']
        if key == 'firmware_running_version':
            value = display_release_version(value)
        tone = ''
        if key in ('mqtt', 'api'):
            lowered = str(value).lower()
            tone = ' good' if lowered in ('connected', 'up', 'online') else (
                '' if lowered in ('not configured', 'disabled') else ' warn'
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
    return portal_ui.shell('IoTMD overview', 'overview', body, token, script)

def render_logging_page(token, current_loglevel, levels, logs,
                        log_refresh_ms=5000, settings=None, message=''):
    settings = settings or {}
    options = ''.join(
        '<option value="' + level + '"' +
        (' selected' if level == current_loglevel else '') + '>' + level + '</option>'
        for level in levels
    )
    body = (
        portal_ui.page_heading(
            'Maintenance', 'Device log',
            'Review live device logs and adjust runtime verbosity.'
        ) + _notice(message) +
        '<section class="card"><div class="section-title"><h2>Logs</h2>'
        '<div class="actions"><a class="button secondary compact" href="/download-logs">'
        'Download logs</a>' + render_refresh_controls_html(
            'log-refresh-toggle', 'log'
        ) + '</div></div>'
        '<form action="/set-loglevel" method="post" class="log-toolbar">'
        '<input type="hidden" name="csrf" value="' + html_escape(token) + '">'
        '<label>Log level <select name="level">' + options + '</select></label>'
        '<label>Stored lines <input name="log_buffer_lines" type="number" min="0" max="500" '
        'required value="' + html_escape(settings.get('log_buffer_lines', 200)) + '"></label>'
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
    return portal_ui.shell('IoTMD device log', 'logging', body, token, script)

def render_audit_logging_page(token, logs, log_refresh_ms=5000):
    body = (
        portal_ui.page_heading(
            'Maintenance', 'Audit log',
            'Review security-relevant portal authentication and API connection events.'
        ) +
        '<section class="card"><div class="section-title"><h2>Audit events</h2>'
        '<div class="actions"><a class="button secondary compact" '
        'href="/download-audit-logs">Download audit log</a>' +
        render_refresh_controls_html('audit-refresh-toggle', 'audit') +
        '</div></div><pre id="audit-logs" class="log-view">' +
        render_logs_html(logs or []) + '</pre></section>'
    )
    interval = max(1000, int(log_refresh_ms or 5000))
    script = (
        'var auditRefreshPaused=false,auditRefreshButton=document.getElementById("audit-refresh-toggle"),'
        'auditRefreshState=document.querySelector(".refresh-status");'
        'function updateAuditRefresh(){auditRefreshButton.textContent=auditRefreshPaused?"Resume":"Pause";'
        'auditRefreshState.textContent=auditRefreshPaused?"refresh paused":"auto refresh";'
        'auditRefreshState.className=auditRefreshPaused?"badge warn refresh-status":"badge good refresh-status";}'
        'auditRefreshButton.onclick=function(){auditRefreshPaused=!auditRefreshPaused;updateAuditRefresh();'
        'if(!auditRefreshPaused)refreshAuditLogs();};'
        'function auditNearBottom(e){return e.scrollHeight-e.scrollTop-e.clientHeight<48;}'
        'function refreshAuditLogs(){if(auditRefreshPaused)return;var e=document.getElementById("audit-logs"),'
        'b=auditNearBottom(e);fetch("/audit-logs",{cache:"no-store",credentials:"same-origin"}).then(function(r){'
        'if(r.status===401){location.replace("/login");return null;}return r.text();}).then(function(t){'
        'if(t!==null&&t!==undefined&&e.textContent!==t){e.textContent=t;if(b)e.scrollTop=e.scrollHeight;}})'
        '.catch(function(){});}setInterval(refreshAuditLogs,' + str(interval) + ');updateAuditRefresh();'
    )
    return portal_ui.shell(
        'IoTMD audit log', 'audit_logging', body, token, script
    )

def render_logging_settings_page(token, settings, message='', error=False):
    settings = settings or {}
    syslog_transport = settings.get('syslog_transport', 'udp')
    syslog_port = settings.get(
        'syslog_port', 6514 if syslog_transport == 'tls' else 514
    )
    body = (
        portal_ui.page_heading(
            'System', 'Logging',
            'Configure Device log and Audit log retention and remote syslog forwarding.'
        ) + _notice(message, error) +
        '<section class="card"><div class="section-title"><h2>Retention and forwarding</h2></div>'
        '<form action="/logging-settings" method="post"><input type="hidden" name="csrf" value="' +
        html_escape(token) + '">' + render_operational_hidden_fields(
            settings, ('log_buffer_lines', 'syslog_enabled',
                       'syslog_audit_enabled', 'syslog_host', 'syslog_port',
                       'syslog_transport')
        ) + '<input type="hidden" name="syslog_enabled" value="false">'
        '<input type="hidden" name="syslog_audit_enabled" value="false">'
        '<label class="field">Device log entries retained locally (0–500)<input name="log_buffer_lines" '
        'type="number" min="0" max="500" required value="' +
        html_escape(settings.get('log_buffer_lines', 200)) + '"></label>'
        '<label class="check"><input name="syslog_enabled" type="checkbox" value="true"' +
        (' checked' if settings.get('syslog_enabled') else '') +
        '>Forward device logs to the remote syslog server</label>'
        '<label class="check"><input name="syslog_audit_enabled" type="checkbox" value="true"' +
        (' checked' if settings.get(
            'syslog_audit_enabled', settings.get('syslog_enabled', False)
        ) else '') +
        '>Forward audit log events to the remote syslog server</label><div class="grid">'
        '<label class="field">Syslog server<input name="syslog_host" maxlength="253" value="' +
        html_escape(settings.get('syslog_host', '')) + '"></label>'
        '<label class="field">Transport<select id="syslog-transport" name="syslog_transport">'
        '<option value="udp"' + (' selected' if syslog_transport == 'udp' else '') +
        '>UDP (standard)</option><option value="tls"' +
        (' selected' if syslog_transport == 'tls' else '') +
        '>TLS (encrypted)</option></select></label>'
        '<label class="field">Port<input id="syslog-port" name="syslog_port" type="number" min="1" max="65535" '
        'required value="' + html_escape(syslog_port) + '"></label></div>'
        '<p class="muted">TLS uses the dedicated Syslog CA installed under Certificates. '
        'Changes take effect after the pending device restart.</p><div class="actions"><span></span>'
        '<button type="submit">Save logging settings</button></div></form></section>'
    )
    script = (
        'var syslogTransport=document.getElementById("syslog-transport"),'
        'syslogPort=document.getElementById("syslog-port");'
        'syslogTransport.onchange=function(){syslogPort.value=this.value==="tls"?"6514":"514";};'
    )
    return portal_ui.shell(
        'IoTMD logging settings', 'logging_settings', body, token, script
    )

def render_module_diagnostics_page(token, modules, value_refresh_ms=5000,
                                   role='administrator'):
    body = (
        portal_ui.page_heading(
            'Module', 'Diagnostics',
            'Review live values, health information and controls for loaded modules.'
        ) +
        '<div id="module-diagnostics">' +
        render_modules_html(modules or [], token, role) + '</div>'
        '<div class="actions"><span></span><a class="button secondary" '
        'href="/download-diagnostics">Download diagnostics</a></div>'
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
        'IoTMD module diagnostics', 'module_diagnostics', body, token, script
    )

def render_update_preferences(csrf, settings):
    settings = settings or {}
    channel = settings.get('release_channel', 'stable')
    download = ' checked' if settings.get('release_auto_download') else ''
    activate = ' checked' if settings.get('release_auto_activate') else ''
    schedule = str(settings.get('release_check_schedule', 'disabled'))
    check_time = str(settings.get('release_check_time', '03:00'))
    weekday = int(settings.get('release_check_weekday', 0))
    weekdays = ('Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday')
    weekday_options = ''.join(
        '<option value="' + str(index) + '"' +
        (' selected' if index == weekday else '') + '>' + day + '</option>'
        for index, day in enumerate(weekdays)
    )
    schedule_disabled = schedule == 'disabled'
    weekly = schedule == 'weekly'
    return (
        '<form action="/update-preferences" method="post"><input type="hidden" name="csrf" value="' +
        html_escape(csrf) + '"><div class="grid"><label class="field">Release channel<select '
        'name="release_channel"><option value="stable"' +
        (' selected' if channel == 'stable' else '') + '>Stable</option><option value="beta"' +
        (' selected' if channel == 'beta' else '') + '>Beta</option></select></label>'
        '<label class="field">Automatic check schedule<select id="release-check-schedule" '
        'name="release_check_schedule"><option value="disabled"' +
        (' selected' if schedule == 'disabled' else '') + '>Disabled</option>'
        '<option value="daily"' + (' selected' if schedule == 'daily' else '') +
        '>Daily</option><option value="weekly"' +
        (' selected' if schedule == 'weekly' else '') + '>Weekly</option></select></label>'
        '<fieldset id="release-check-fields" class="conditional-fields"' +
        (' hidden disabled' if schedule_disabled else '') + '><div class="grid">'
        '<label class="field">Check time (device local time)<input id="release-check-time" '
        'name="release_check_time" type="time"' +
        (' required' if not schedule_disabled else '') + ' value="' + html_escape(check_time) + '"></label>'
        '<label id="release-weekday-field" class="field"' +
        ('' if weekly else ' hidden') + '>Weekly check day<select id="release-check-weekday" '
        'name="release_check_weekday"' + ('' if weekly else ' disabled') + '>' +
        weekday_options + '</select></label></div></fieldset></div>'
        '<p class="muted">Scheduled checks use the device time zone configured under Time / Date. '
        'Opening this page does not initiate a check.</p>'
        '<label class="check"><input type="checkbox" name="release_auto_download"' + download +
        '>Automatically download applicable signed releases</label>'
        '<label class="check"><input type="checkbox" name="release_auto_activate"' + activate +
        '>Automatically activate verified releases</label>'
        '<div class="actions"><span></span><button class="secondary" type="submit">'
        'Save update preferences</button></div></form>'
    )

def update_preferences_script():
    return (
        'var releaseSchedule=document.getElementById("release-check-schedule"),releaseTime='
        'document.getElementById("release-check-time"),releaseWeekday=document.getElementById('
        '"release-check-weekday"),releaseFields=document.getElementById("release-check-fields"),'
        'releaseWeekdayField=document.getElementById("release-weekday-field");'
        'function syncReleaseSchedule(){if(!releaseSchedule)return;var disabled='
        'releaseSchedule.value==="disabled",weekly=releaseSchedule.value==="weekly";'
        'releaseFields.hidden=disabled;releaseFields.disabled=disabled;releaseTime.disabled=disabled;'
        'releaseTime.required=!disabled;releaseWeekdayField.hidden=!weekly;releaseWeekday.disabled=!weekly;}'
        'if(releaseSchedule){releaseSchedule.onchange='
        'syncReleaseSchedule;syncReleaseSchedule();}'
    )

def update_upload_script():
    return (
        'var csrfToken=document.getElementById("update-upload-form").dataset.csrf;'
        'document.getElementById("update-bundle").onchange=function(){document.getElementById('
        '"update-file-name").textContent=this.files&&this.files[0]?this.files[0].name:"No file selected";};'
        'document.getElementById("update-upload-form").onsubmit=function(e){e.preventDefault();var input='
        'document.getElementById("update-bundle"),f=input.files&&input.files[0],out=document.getElementById('
        '"update-result"),box=document.getElementById("update-progress"),'
        'label=box.querySelector(".status-text");if(!f){portalRequire(input,'
        '"Choose a .iotapp, .iotcore or .iotuni update bundle");return;}var firmware=/\\.iotcore$/i.test(f.name),'
        'application=/\\.iotapp$/i.test(f.name),universal=/\\.iotuni$/i.test(f.name);'
        'function previous(text){out.className="status-history complete";out.textContent=text;}'
        'function failure(text){out.className="status-history failed";out.textContent=text;}'
        'if(!firmware&&!application&&!universal){failure("Choose a .iotapp, .iotcore or .iotuni update bundle.");return;}'
        'box.classList.remove("complete","failed");box.hidden=false;label.textContent="Uploading 0%";'
        'out.className="status-history";out.textContent="";'
        'var id="",polling=false,finished=false,timer=null;function schedulePoll(){if(!finished)timer=setTimeout(poll,1000);}'
        'function startPolling(){if(polling)return;polling=true;poll();}function poll(){fetch("/update-progress?id="+encodeURIComponent(id),'
        '{cache:"no-store",credentials:"same-origin"}).then(function(r){if(r.status===401){location.replace('
        '"/login");return null;}return r.json();}).then(function(s){if(!s)return;if(s.phase==="writing"){'
        'label.textContent="Writing firmware "+(s.percent||0)+"%";previous("Completed: upload");}'
        'else if(s.phase==="verification"){label.textContent="Verifying "+(s.percent||0)+"%";'
        'previous(firmware?"Completed: upload · firmware write":"Completed: upload · application staging");}'
        'else if(s.phase==="firmware_writing"){label.textContent="Writing core firmware "+(s.percent||0)+"%";'
        'previous("Completed: universal upload");}else if(s.phase==="firmware_verification"){'
        'label.textContent="Verifying core firmware "+(s.percent||0)+"%";previous("Completed: universal upload · core write");}'
        'else if(s.phase==="application_verification"){label.textContent="Verifying application "+(s.percent||0)+"%";'
        'previous("Completed: universal upload · core write and verification · application staging");}'
        'else if(s.phase==="complete"){finished=true;box.classList.add("complete");label.textContent="Verification complete";'
        'setTimeout(function(){location.replace("/updates");},900);return;}else if(s.phase==="failed"){'
        'finished=true;box.classList.add("failed");label.textContent="Failed";failure(s.message||"Verification failed");return;}'
        'schedulePoll();}).catch(function(){schedulePoll();});}'
        'function jsonPost(url,value){return fetch(url,{method:"POST",credentials:"same-origin",headers:{'
        '"Content-Type":"application/json","X-CSRF-Token":csrfToken},body:JSON.stringify(value)}).then(function(r){'
        'if(r.status===401){location.replace("/login");throw new Error("Session expired");}if(!r.ok)return r.text().then(function(t){'
        'throw new Error(t||"Request failed");});return r.json();});}'
        'function sendChunk(offset){if(offset>=f.size){label.textContent=firmware?"Writing firmware 0%":"Verifying application 0%";'
        'previous("Completed: upload");startPolling();'
        'return fetch("/resumable-upload-complete",{method:"POST",credentials:"same-origin",headers:{'
        '"Content-Type":"application/json","X-CSRF-Token":csrfToken},body:JSON.stringify({id:id})}).then(function(r){'
        'if(r.status===401){location.replace("/login");return;}if(r.status===202||r.ok){startPolling();return;}return r.text().then(function(t){'
        'throw new Error(t||"Verification failed");});});}var end=Math.min(offset+65536,f.size);return fetch('
        '"/resumable-upload-chunk?id="+encodeURIComponent(id)+"&offset="+offset,{method:"POST",credentials:"same-origin",'
        'headers:{"Content-Type":"application/octet-stream","X-CSRF-Token":csrfToken},body:f.slice(offset,end)}).then(function(r){'
        'if(!r.ok)return r.text().then(function(t){throw new Error(t||"Chunk upload failed");});return r.json();}).then(function(s){'
        'var received=Number(s.received_bytes||end),n=Math.round(received*100/f.size);label.textContent="Uploading "+n+"%";return sendChunk(received);});}'
        'function waitForComponent(uploadId){return new Promise(function(resolve,reject){function check(){fetch('
        '"/update-progress?id="+encodeURIComponent(uploadId),{cache:"no-store",credentials:"same-origin"}).then(function(r){'
        'if(!r.ok)throw new Error("Unable to read component progress");return r.json();}).then(function(s){if(s.phase==="complete")'
        '{resolve(s);return;}if(s.phase==="failed"){reject(new Error(s.message||"Component verification failed"));return;}'
        'setTimeout(check,500);}).catch(reject);}check();});}'
        'function uploadUniversalComponent(blob,kind,digest,planId){var uploadId=digest.slice(0,20)+"-"+kind.charAt(0)+"-"+blob.size;'
        'return jsonPost("/resumable-upload-begin",{id:uploadId,kind:kind,total_bytes:blob.size,sha256:digest,'
        'universal_plan:planId}).then(function(s){function chunk(offset){if(offset>=blob.size){label.textContent="Verifying "+kind+" 0%";'
        'return fetch("/resumable-upload-complete",{method:"POST",credentials:"same-origin",headers:{'
        '"Content-Type":"application/json","X-CSRF-Token":csrfToken},body:JSON.stringify({id:uploadId})}).then(function(r){'
        'if(r.status===401){location.replace("/login");throw new Error("Session expired");}if(r.status!==202&&!r.ok)'
        'return r.text().then(function(t){throw new Error(t||"Component verification failed");});return waitForComponent(uploadId);});}'
        'var end=Math.min(offset+65536,blob.size);return fetch("/resumable-upload-chunk?id="+encodeURIComponent(uploadId)+'
        '"&offset="+offset,{method:"POST",credentials:"same-origin",headers:{"Content-Type":"application/octet-stream",'
        '"X-CSRF-Token":csrfToken},body:blob.slice(offset,end)}).then(function(r){if(!r.ok)return r.text().then(function(t){'
        'throw new Error(t||"Component upload failed");});return r.json();}).then(function(progress){var received=Number('
        'progress.received_bytes||end),percent=Math.round(received*100/blob.size);label.textContent="Uploading "+kind+" "+percent+"%";'
        'return chunk(received);});}return chunk(Number(s.received_bytes||0));});}'
        'function startUniversalUpload(){return f.slice(0,10).arrayBuffer().then(function(header){var bytes=new Uint8Array(header),'
        'magic=String.fromCharCode.apply(null,bytes.slice(0,6));if(magic!=="IOTU1\\n")throw new Error("Invalid universal update header");'
        'var manifestLength=new DataView(header).getUint32(6,false);if(manifestLength<2||manifestLength>4096)'
        'throw new Error("Invalid universal update manifest size");return f.slice(10,10+manifestLength).text().then(function(text){'
        'var manifest=JSON.parse(text),firmwareSize=Number(manifest.firmware&&manifest.firmware.size||0),applicationSize='
        'Number(manifest.application&&manifest.application.size||0),prefix=10+manifestLength;if(!firmwareSize||!applicationSize||'
        'prefix+firmwareSize+applicationSize!==f.size)throw new Error("Universal update length does not match its manifest");'
        'return jsonPost("/universal-upload-prepare",{manifest:manifest}).then(function(plan){var sequence=Promise.resolve();'
        'if(plan.firmware&&plan.firmware.required){sequence=sequence.then(function(){previous("Universal manifest verified");'
        'return uploadUniversalComponent(f.slice(prefix,prefix+firmwareSize),"firmware",String(manifest.firmware.sha256),plan.id);});}'
        'if(plan.application&&plan.application.required){sequence=sequence.then(function(){previous("Core component verified");'
        'return uploadUniversalComponent(f.slice(prefix+firmwareSize),"application",String(manifest.application.sha256),plan.id);});}'
        'return sequence.then(function(){label.textContent="Pairing verified components";return jsonPost('
        '"/universal-upload-finalize",{id:plan.id});});});});});}'
        'if(universal){startUniversalUpload().then(function(){finished=true;box.classList.add("complete");label.textContent='
        '"Universal verification complete";previous("Core and application paired for activation");setTimeout(function(){location.replace('
        '"/updates");},900);}).catch(function(err){finished=true;box.classList.add("failed");label.textContent="Failed";failure('
        'err&&err.message?err.message:"Universal upload failed");});return;}'
        'f.arrayBuffer().then(function(data){return crypto.subtle.digest("SHA-256",data);}).then(function(hash){var hex=Array.from(new Uint8Array(hash)).map(function(b){'
        'return b.toString(16).padStart(2,"0");}).join("");id=hex.slice(0,24)+"-"+f.size;var kind=universal?"universal":'
        '(firmware?"firmware":"application");return jsonPost("/resumable-upload-begin",'
        '{id:id,kind:kind,total_bytes:f.size,sha256:hex});'
        '}).then(function(s){startPolling();return sendChunk(Number(s.received_bytes||0));}).catch(function(err){finished=true;box.classList.add("failed");'
        'label.textContent="Failed";failure(err&&err.message?err.message:"Upload failed");});};'
    )

def render_updates_page(token, status=None, settings=None, message='', error=False):
    status = status or {}
    activation = (
        render_universal_update_html(status, token) +
        render_update_activation_html(status, token) +
        render_firmware_update_html(status, token)
    )
    automatic_action = render_release_check_html(status, token)
    script = update_preferences_script()
    if activation:
        completed = []
        if status.get('update_status') == 'ready':
            completed.append('Application uploaded and verified')
        if status.get('firmware_update_status') == 'ready':
            completed.append('Firmware written and verified')
        manual_content = (
            portal_ui.progress(
                'update-ready', '; '.join(completed) + '. Ready for activation.',
                False, 'complete'
            ) + '<div class="update-actions next-stage">' + activation + '</div>'
        )
    else:
        manual_content = (
            '<form id="update-upload-form" data-csrf="' + html_escape(token) + '">'
            '<div class="actions"><span><input id="update-bundle" class="file-input-hidden" type="file" required '
            'accept=".iotapp,.iotcore,.iotuni"><label class="button secondary file-button" for="update-bundle">'
            'Choose update file</label> <span id="update-file-name" class="file-name">No file selected</span></span>'
            '<button type="submit">Upload and verify</button></div></form>' +
            portal_ui.progress('update-progress', '0%', True) +
        '<p id="update-result" class="status-history" role="status" aria-live="polite">'
        'Application bundles use .iotapp; core firmware uses .iotcore; universal bundles use .iotuni.</p>'
        )
        script += update_upload_script()
    body = (
        portal_ui.page_heading(
            'Maintenance', 'Upgrades',
            'Check, upload, verify and activate signed application or core firmware releases.'
        ) + _notice(message, error) +
        '<section class="card"><div class="section-title"><h2>Versions and update state</h2></div>' +
        render_update_summary_html(status) + '<div class="update-actions">' +
        render_application_rollback_html(status, token) + '</div></section>'
        '<div class="upgrade-grid"><section class="card"><div class="section-title">'
        '<h2>Automatic upgrade</h2></div>'
        '<div class="settings-subsection"><h3>Manual upgrade check</h3>'
        '<p class="muted">Check the signed release channel now without changing the automatic schedule.</p>'
        '<div class="update-actions">' + automatic_action + '</div></div>'
        '<div class="settings-subsection"><h3>Settings</h3>'
        '<p class="muted">Configure the release channel, schedule, download and activation preferences.</p>' +
        render_update_preferences(token, settings) + '</div></section>'
        '<section class="card"><div class="section-title"><h2>Manual upgrade</h2></div>' +
        manual_content + '</section></div>'
    )
    return portal_ui.shell(
        'IoTMD upgrades', 'updates', body, token, script
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

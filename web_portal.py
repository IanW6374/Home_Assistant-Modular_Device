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
    result = []
    index = 0
    while index < len(value):
        if value[index] == '%' and index + 2 < len(value):
            try:
                result.append(chr(int(value[index + 1:index + 3], 16)))
                index += 3
                continue
            except ValueError:
                pass
        result.append(value[index])
        index += 1
    return ''.join(result)


def parse_request_line(line):
    parts = line.split()
    if len(parts) < 2:
        return None, None
    return parts[0], parts[1]


async def read_exact_body(reader, size):
    result = bytearray()
    while len(result) < int(size):
        chunk = await reader.read(int(size) - len(result))
        if not chunk:
            raise ValueError('request body ended early')
        result.extend(chunk)
    return bytes(result)


def is_authenticated(path, token):
    if not token:
        return False
    return parse_query(path).get('token') == token


def parse_cookies(headers):
    cookies = {}
    for item in (headers or {}).get('cookie', '').split(';'):
        if '=' in item:
            key, value = item.strip().split('=', 1)
            cookies[key] = value
    return cookies


def has_portal_session(headers, session_id):
    return bool(session_id) and parse_cookies(headers).get('ham_session') == session_id


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


def apply_portal_action(action, path, action_handler, log_output):
    notice = ''
    if action_handler:
        notice = str(action_handler(action, parse_query(path)))
    else:
        notice = action + ' request ignored'

    if notice:
        log_output('Local', 'Web portal', {'log': notice, 'force': True}, 'INFO')
    return notice


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
    headers = (
        'HTTP/1.1 ' + status + '\r\n'
        'Content-Type: ' + content_type + '\r\n'
        'Cache-Control: no-store\r\n'
        'Connection: close\r\n'
        'Content-Length: ' + str(len(body_bytes)) + '\r\n'
    )
    if extra_headers:
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
    'running_version': 'App version',
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


def render_refresh_controls_html(button_id='refresh-toggle'):
    return (
        '<div class="refresh-controls">' +
        '<span class="badge good refresh-status">auto refresh</span>' +
        '<button id="' + html_escape(button_id) + '" class="secondary compact refresh-toggle" type="button" ' +
        'title="Pause or resume log and value auto refresh.">Pause</button>' +
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
        ok = bool(diagnostics.get('module_last_ok', diagnostics.get('last_ok')))
        last_error = diagnostics.get('module_last_error', diagnostics.get('last_error', ''))
        health_badge = render_badge('ok' if ok else 'check', 'good' if ok else 'warn')
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
        history_html +
        ('<p class="muted">Available ' + html_escape(status.get('release_available_type', '')) +
         ' release: ' + html_escape(status.get('release_available_version', '')) + '</p>'
         if status.get('release_available_version') else '') + '</div>'
    )


def render_update_activation_html(status, token):
    if not status or status.get('update_status') != 'ready':
        return ''

    labels = {
        'device_settings': 'Device settings',
        'module_settings': 'Module settings',
        'secrets': 'Secrets',
        'certificates': 'Certificates'
    }
    option_html = []
    available = status.get('update_options', ())
    for key in ('device_settings', 'module_settings', 'secrets', 'certificates'):
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
    return (
        '<form action="/check-release" method="post">' +
        '<input type="hidden" name="csrf" value="' + html_escape(token) + '">' +
        '<button class="secondary" type="submit" title="Check the configured signed release channel now.">Check for updates</button></form>'
    )


def render_update_actions_html(status, token):
    return (
        '<div id="update-actions" class="update-actions">' +
        render_update_activation_html(status, token) +
        render_firmware_update_html(status, token) +
        render_application_rollback_html(status, token) +
        render_release_check_html(status, token) +
        '</div>'
    )


def render_page_parts(token, current_loglevel, levels, logs=None, log_refresh_ms=5000, status=None, modules=None, notice='', value_refresh_ms=0):
    options = []
    for level in levels:
        selected = ' selected' if level == current_loglevel else ''
        options.append('<option value="' + level + '"' + selected + '>' + level + '</option>')
    update_actions = render_update_actions_html(status or {}, token)
    update_summary = render_update_summary_html(status or {})
    live_parts = render_live_sections_parts(status or {}, modules or [], token)

    parts = ("""<!doctype html>
<html>
<head>
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Device Portal</title>
<style>
:root{color-scheme:light;--bg:#f4f6f8;--panel:#fff;--ink:#171b22;--muted:#687384;--line:#d9e0e8;--accent:#1769aa;--good:#147a4b;--warn:#9a5b00;--bad:#ad2f2f}
*{box-sizing:border-box}
body{font-family:system-ui,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;margin:0;line-height:1.4;background:var(--bg);color:var(--ink)}
main{max-width:78rem;margin:0 auto;padding:1rem}
.topbar{display:flex;align-items:flex-end;justify-content:space-between;gap:1rem;margin:.25rem 0 1rem}
h1{font-size:1.45rem;margin:0}
h2{font-size:1rem;margin:0}
h3{font-size:.95rem;margin:0}
.topbar p,.module-head p,.muted{color:var(--muted);margin:.15rem 0 0}
.panel{background:var(--panel);border:1px solid var(--line);border-radius:8px;padding:1rem;margin:1rem 0;box-shadow:0 1px 2px rgba(20,28,38,.05)}
.section-title{display:flex;align-items:center;justify-content:space-between;gap:1rem;margin-bottom:.8rem}
.metrics{display:grid;grid-template-columns:repeat(6,minmax(0,1fr));gap:.65rem}
.metric{border:1px solid var(--line);border-radius:7px;padding:.65rem;background:#fbfcfd;min-width:0}
.metric.version-app{grid-column:5;grid-row:2}
.metric.version-base{grid-column:6;grid-row:2}
.metric span,.state-row span{display:block;color:var(--muted);font-size:.76rem;text-transform:uppercase;letter-spacing:.04em}
.metric span{white-space:nowrap;font-size:.72rem}
.metric strong{display:block;font-size:1rem;margin-top:.15rem;overflow-wrap:anywhere}
.metric.wide{grid-column:span 2}
.metric.wide strong{white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.metric.ota-availability{grid-column:1/-1}
.metric.ota-availability strong{white-space:normal;overflow:visible;text-overflow:clip}
.update-summary{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:.65rem;margin-bottom:1rem}
.update-history,.update-summary>p{grid-column:1/-1}
.metric.good{border-color:#9ed6bd;background:#f1fbf6}
.metric.warn{border-color:#efcf92;background:#fff8eb}
.badge{display:inline-flex;align-items:center;border-radius:999px;border:1px solid var(--line);padding:.15rem .55rem;font-size:.76rem;font-weight:650;color:var(--muted);background:#f8fafc;white-space:nowrap}
.badge.good{color:var(--good);border-color:#9ed6bd;background:#f1fbf6}
.badge.warn{color:var(--warn);border-color:#efcf92;background:#fff8eb}
.module-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(18rem,1fr));gap:.8rem}
.module-card{border:1px solid var(--line);border-radius:8px;padding:.85rem;background:#fbfcfd;min-width:0}
.module-head{display:flex;align-items:flex-start;justify-content:space-between;gap:.8rem;margin-bottom:.7rem}
""", """
.state-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(8rem,1fr));gap:.45rem}
.state-row{border-top:1px solid var(--line);padding:.45rem 0;min-width:0}
.state-row strong{display:block;overflow-wrap:anywhere;font-size:.9rem}
.diag-tile{border:1px solid #dfe6ee;border-radius:7px;background:#f4f7fa;margin-top:.75rem;padding:.65rem}
.diag-title{color:var(--muted);font-size:.76rem;text-transform:uppercase;letter-spacing:.04em;font-weight:700;margin-bottom:.25rem}
.diag-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(7.5rem,1fr));gap:.35rem .65rem}
.diag-row{min-width:0;border-top:1px solid #e5ebf1;padding:.3rem 0}
.diag-row span{display:block;color:var(--muted);font-size:.72rem;overflow-wrap:anywhere}
.diag-row strong{display:block;font-size:.82rem;overflow-wrap:anywhere}
.error-text{color:var(--bad);margin:.4rem 0 .7rem;overflow-wrap:anywhere}
form{display:flex;gap:.5rem;align-items:center;flex-wrap:wrap;margin:0}
.controls{display:flex;gap:.75rem;align-items:center;justify-content:space-between;flex-wrap:wrap}
.control-group{display:flex;gap:.5rem;align-items:center;flex-wrap:wrap}
.config-validator{width:100%;margin-top:.75rem}.config-validator textarea{width:100%;min-height:8rem;font-family:ui-monospace,monospace}
.refresh-controls{display:grid;grid-template-columns:8rem 5rem;column-gap:.75rem;align-items:center;width:13.75rem;margin-left:auto}
select,button,input{font:inherit;padding:.45rem .6rem;border:1px solid var(--line);border-radius:7px;background:white;color:var(--ink)}
input[type="checkbox"]{padding:0;width:1rem;height:1rem;border-radius:3px;vertical-align:middle}
button{background:var(--accent);border-color:var(--accent);color:white;font-weight:650;cursor:pointer}
button.secondary{background:white;color:var(--accent)}
button.compact{padding:.25rem .55rem;font-size:.78rem}
.file-input-hidden{position:absolute;width:1px;height:1px;padding:0;margin:-1px;overflow:hidden;clip:rect(0,0,0,0);white-space:nowrap;border:0}
.file-button{display:inline-flex;align-items:center;font-weight:650;padding:.45rem .65rem;border:1px solid var(--accent);border-radius:7px;background:white;color:var(--accent);cursor:pointer;white-space:nowrap}
.file-name{color:var(--ink);overflow-wrap:anywhere;min-width:7rem}
.update-layout{display:grid;grid-template-columns:minmax(0,1fr) auto;gap:1rem;align-items:center}
.update-actions{display:flex;flex-wrap:wrap;gap:.75rem;align-items:center}
.update-upload{display:flex;gap:.75rem 1rem;align-items:center;flex-wrap:wrap;min-width:0}
.update-file{display:flex;gap:.6rem;align-items:center;min-width:0}
.update-options{display:flex;gap:.45rem 1rem;align-items:center;flex-wrap:wrap;padding:.4rem .55rem;border:1px solid var(--line);border-radius:7px;background:#f8fafc}
.update-options-label{color:var(--muted);font-size:.78rem;font-weight:650}
.update-options label{font-size:.86rem;white-space:nowrap}
.update-switch{display:inline-flex;align-items:center;gap:.4rem;cursor:pointer}
.update-switch input[type="checkbox"]{appearance:none;-webkit-appearance:none;position:relative;width:2.15rem;height:1.2rem;margin:0;border:1px solid #aab4c0;border-radius:999px;background:#dfe5eb;transition:background .15s,border-color .15s}
.update-switch input[type="checkbox"]:after{content:"";position:absolute;top:.12rem;left:.12rem;width:.82rem;height:.82rem;border-radius:50%;background:white;box-shadow:0 1px 2px rgba(20,28,38,.25);transition:left .15s}
.update-switch input[type="checkbox"]:checked{background:var(--accent);border-color:var(--accent)}
.update-switch input[type="checkbox"]:checked:after{left:1.08rem}
.update-switch input[type="checkbox"]:focus-visible{outline:2px solid var(--accent);outline-offset:2px}
.update-result{margin:.7rem 0 0;min-height:1.4em}
.update-progress{display:flex;align-items:center;gap:.7rem;margin-top:.7rem;max-width:32rem}
.update-progress[hidden]{display:none}
.update-progress progress{width:100%;height:1rem;accent-color:var(--accent)}
.update-progress span{min-width:8.5rem;text-align:right;font-variant-numeric:tabular-nums}
.log-header-actions{display:flex;align-items:center;gap:.75rem;margin-left:auto}
.log-header-actions form{flex-wrap:nowrap}
.refresh-controls .badge,.refresh-toggle{box-sizing:border-box;width:100%}
.refresh-status{justify-content:center}
.refresh-toggle{text-align:center}
.calibration-form{border-top:1px solid var(--line);margin-top:.7rem;padding-top:.7rem}
.notice{background:#eef8f0;border:1px solid #a9d8b4;color:#175c2c;border-radius:8px;padding:.65rem .8rem;margin:1rem 0}
#logs{white-space:pre-wrap;overflow-wrap:anywhere;background:#111820;color:#dce7ef;padding:1rem;border-radius:8px;height:38vh;overflow-y:auto;border:1px solid #26313d}
@media(max-width:1000px){.metrics{grid-template-columns:repeat(auto-fit,minmax(10.5rem,1fr))}.metric.version-app,.metric.version-base{grid-column:auto;grid-row:auto}}
@media(max-width:700px){.update-layout{grid-template-columns:1fr}.update-layout>form{justify-self:start}.log-header-actions{gap:.4rem}.metrics{grid-template-columns:repeat(auto-fit,minmax(9.5rem,1fr))}.metric.wide{grid-column:span 1}}
@media(max-width:560px){main{padding:.7rem}.topbar{align-items:flex-start;flex-direction:column}.module-grid,.update-summary{grid-template-columns:1fr}.controls{align-items:stretch}.control-group,form{width:100%}button,select,input{max-width:100%}.log-header-actions{align-items:flex-end;flex-direction:column}.log-header-actions form{width:auto}}
</style>
</head>
<body>
<main>
<div class="topbar"><div><h1>Device Portal</h1></div></div>
""", ('<p class="notice">' + html_escape(notice) + '</p>' if notice else ''), """
""", live_parts, """
<section class="panel"><div class="section-title"><h2>Controls</h2></div>
<div class="controls"><form action="/discover" method="post">
<input type="hidden" name="csrf" value=\"""", html_escape(token), """\">
<button type="submit" title="Republish Home Assistant MQTT discovery config for all loaded entities.">Publish Discovery</button>
</form>
<form action="/set-loglevel" method="post" class="control-group">
<input type="hidden" name="csrf" value=\"""", html_escape(token), """\">
<label for="level" title="Controls how much firmware logging is shown and published.">Debug level</label>
<select id="level" name="level" title="ERROR is quiet, INFO is normal, DEBUG includes MQTT detail.">""", ''.join(options), """</select>
<button class="secondary" type="submit" title="Apply the selected runtime log level until the device restarts.">Apply</button>
</form>
</div>
<details class="config-validator"><summary>Module configuration validator</summary>
<form action="/validate-configuration" method="post">
<input type="hidden" name="csrf" value=\"""", html_escape(token), """\">
<textarea name="config_json" placeholder='Paste module_settings.json here' required></textarea>
<button class="secondary" type="submit" title="Check JSON structure, module types, pins, and shared-bus conflicts without saving.">Validate configuration</button>
</form></details>
</section>
<section class="panel"><div class="section-title"><h2>Software update</h2></div>
""", update_summary, """
<div class="update-layout"><form id="update-upload-form" class="update-upload">
<span class="update-file"><input id="update-bundle" class="file-input-hidden" type="file" required>
<label class="file-button" for="update-bundle" title="Choose an application (.hamd) or base firmware (.hamf) update bundle.">Choose update file</label>
<span id="update-file-name" class="file-name">No file selected</span></span>
<button type="submit" title="Upload, verify, and stage the selected update bundle.">Upload and verify</button>
</form>
""", update_actions, """</div>
<p class="muted update-result">Select an application (.hamd) or base firmware (.hamf) bundle.</p>
<div id="update-progress" class="update-progress" hidden><progress id="update-progress-bar" max="100" value="0"></progress><span id="update-progress-label">0%</span></div>
<p id="update-result" class="muted update-result"></p>
</section>
<section class="panel"><div class="section-title"><h2>Logs</h2><div class="log-header-actions"><form action="/download-logs" method="get">
<button class="secondary compact" type="submit" title="Download the current in-memory device log as a text file.">Download logs</button>
</form><form action="/download-diagnostics" method="get">
<button class="secondary compact" type="submit" title="Download sanitised device status, module diagnostics, update history, and recent logs.">Download diagnostics</button>
</form><form action="/download-configuration" method="get">
<button class="secondary compact" type="submit" title="Download device and module settings without passwords or private keys.">Download configuration</button>
</form>""", render_refresh_controls_html('log-refresh-toggle'), """</div></div>
<pre id="logs"></pre>
</section>
</main>
<script>
var csrfToken='""", js_escape(token), """';
var logRefreshMs=""", str(log_refresh_ms), """;
var valueRefreshMs=""", str(value_refresh_ms), """;
var autoRefreshPaused=false;
var refreshTimer=null;
var lastLogRefresh=0;
var lastValueRefresh=0;
var uploadInProgress=false;
var refreshBusy=false;
var refreshInProgress=Promise.resolve();
function nearBottom(el){return el.scrollHeight-el.scrollTop-el.clientHeight<48;}
function refreshLogs(){
  if(autoRefreshPaused){return Promise.resolve();}
  var el=document.getElementById('logs');
  var keepBottom=nearBottom(el);
  return fetch('/logs',{cache:'no-store',credentials:'same-origin'})
    .then(function(r){if(r.ok){return r.text();}})
    .then(function(text){
      if(text!==undefined&&el.textContent!==text){
        el.textContent=text;
        if(keepBottom){el.scrollTop=el.scrollHeight;}
      }
    });
}
function refreshValues(){
  if(autoRefreshPaused){return Promise.resolve();}
  return fetch('/partials',{cache:'no-store',credentials:'same-origin'})
    .then(function(r){if(r.ok){return r.json();}})
    .then(function(payload){
      if(!payload){return;}
      var html=payload.live_sections;
      var el=document.getElementById('live-sections');
      if(html!==undefined&&el&&el.outerHTML!==html){
        el.outerHTML=html;
      }
      var updateHtml=payload.update_summary;
      var updateEl=document.getElementById('update-summary');
      if(updateHtml!==undefined&&updateEl&&updateEl.outerHTML!==updateHtml){updateEl.outerHTML=updateHtml;}
      var actionHtml=payload.update_actions;
      var actionEl=document.getElementById('update-actions');
      if(actionHtml!==undefined&&actionEl&&actionEl.outerHTML!==actionHtml){actionEl.outerHTML=actionHtml;}
      updateRefreshControls();
    });
}
function refreshAll(){
  if(autoRefreshPaused||uploadInProgress||refreshBusy){return refreshInProgress;}
  var now=Date.now();
  var requests=[];
  if(logRefreshMs>0&&(lastLogRefresh===0||now-lastLogRefresh>=logRefreshMs)){
    lastLogRefresh=now;requests.push(refreshLogs());
  }
  if(valueRefreshMs>0&&(lastValueRefresh===0||now-lastValueRefresh>=valueRefreshMs)){
    lastValueRefresh=now;requests.push(refreshValues());
  }
  refreshBusy=true;
  refreshInProgress=Promise.all(requests).then(
    function(){refreshBusy=false;},
    function(){refreshBusy=false;}
  );
  return refreshInProgress;
}
""", """
function scheduleRefresh(){
  if(refreshTimer!==null){clearInterval(refreshTimer);refreshTimer=null;}
  if(autoRefreshPaused){return;}
  var intervals=[];
  if(logRefreshMs>0){intervals.push(logRefreshMs);}
  if(valueRefreshMs>0){intervals.push(valueRefreshMs);}
  if(intervals.length){refreshTimer=setInterval(refreshAll,Math.min.apply(Math,intervals));}
}
function setRefreshPaused(paused){
  autoRefreshPaused=paused;
  updateRefreshControls();
  scheduleRefresh();
  if(!paused){lastLogRefresh=0;lastValueRefresh=0;refreshAll();}
}
function updateRefreshControls(){
  var buttons=document.getElementsByClassName('refresh-toggle');
  var statuses=document.getElementsByClassName('refresh-status');
  for(var b=0;b<buttons.length;b++){buttons[b].textContent=autoRefreshPaused?'Resume':'Pause';}
  for(var i=0;i<statuses.length;i++){
    statuses[i].textContent=autoRefreshPaused?'refresh paused':'auto refresh';
    statuses[i].className=autoRefreshPaused?'badge warn refresh-status':'badge good refresh-status';
  }
}
window.addEventListener('load',function(){
  scheduleRefresh();
  updateRefreshControls();
  setTimeout(refreshAll,100);
});
document.addEventListener('click',function(event){
  if(event.target&&event.target.classList&&event.target.classList.contains('refresh-toggle')){setRefreshPaused(!autoRefreshPaused);}
});
document.addEventListener('change',function(event){
  if(!event.target){return;}
  var name=null;
  if(event.target.id==='update-bundle'){name=document.getElementById('update-file-name');}
  if(!name){return;}
  if(name){name.textContent=event.target.files&&event.target.files.length?event.target.files[0].name:'No file selected';}
});
document.addEventListener('submit',function(event){
  if(!event.target||event.target.id!=='update-upload-form'){return;}
  event.preventDefault();
  var input=document.getElementById('update-bundle');
  var result=document.getElementById('update-result');
  var progress=document.getElementById('update-progress');
  var progressBar=document.getElementById('update-progress-bar');
  var progressLabel=document.getElementById('update-progress-label');
  if(!input||!input.files||!input.files.length){return;}
  var file=input.files[0];
  var isApplication=/\\.hamd$/i.test(file.name);
  var isFirmware=/\\.hamf$/i.test(file.name);
  if(!isApplication&&!isFirmware){
    result.textContent='Choose a .hamd or .hamf update bundle.';
    return;
  }
  var resumeRefresh=!autoRefreshPaused;
  uploadInProgress=true;
  setRefreshPaused(true);
  progress.hidden=false;
  progressBar.value=0;
  progressLabel.textContent='0%';
  result.textContent='Waiting for current portal request...';
  var updateUrl=isFirmware?'/firmware-upload':'/update-upload';
  var updateId=Date.now().toString(36)+'-'+Math.random().toString(36).slice(2);
  refreshInProgress.then(function(){
    setTimeout(function(){
      result.textContent=isFirmware?'Uploading and verifying base firmware...':'Uploading and verifying application update...';
      var request=new XMLHttpRequest();
      var verificationPolling=false;
      var verificationPollTimer=null;
      function stopVerificationPolling(){
        verificationPolling=false;
        if(verificationPollTimer!==null){clearTimeout(verificationPollTimer);verificationPollTimer=null;}
      }
      function scheduleVerificationPoll(delay){
        if(!verificationPolling){return;}
        verificationPollTimer=setTimeout(pollVerificationProgress,delay);
      }
      function pollVerificationProgress(){
        if(!verificationPolling){return;}
        fetch('/update-progress?id='+encodeURIComponent(updateId),{cache:'no-store',credentials:'same-origin'})
          .then(function(response){if(response.ok){return response.json();}})
          .then(function(state){
            if(state&&state.phase==='verification'){
              var percent=Math.max(0,Math.min(100,Number(state.percent)||0));
              progressBar.value=percent;
              progressLabel.textContent='Verifying '+percent+'%';
              result.textContent='Verifying update on device...';
            }else if(state&&state.phase==='complete'){
              stopVerificationPolling();
              progressBar.value=100;
              progressLabel.textContent='Verified 100%';
              result.textContent=state.message||'Update verified and staged';
              uploadInProgress=false;
              setTimeout(function(){window.location.replace('/');},750);
              return;
            }else if(state&&state.phase==='failed'){
              stopVerificationPolling();
              progressBar.value=0;
              progressLabel.textContent='Rejected';
              result.textContent=state.message||'Update verification failed';
              uploadInProgress=false;
              if(resumeRefresh){setRefreshPaused(false);}
              return;
            }
            scheduleVerificationPoll(500);
          },function(){scheduleVerificationPoll(1000);});
      }
      function startVerificationPolling(){
        if(verificationPolling){return;}
        verificationPolling=true;
        pollVerificationProgress();
      }
      function showVerificationWaiting(){
        progressBar.removeAttribute('value');
        progressLabel.textContent='Verifying...';
        result.textContent='Upload complete; verifying update...';
      }
      request.open('POST',updateUrl,true);
      request.setRequestHeader('Content-Type','application/octet-stream');
      request.setRequestHeader('X-CSRF-Token',csrfToken);
      request.setRequestHeader('X-Update-ID',updateId);
      request.upload.onprogress=function(progressEvent){
        if(!progressEvent.lengthComputable){return;}
        var percent=Math.min(100,Math.round(progressEvent.loaded*100/progressEvent.total));
        progressBar.value=percent;
        progressLabel.textContent='Uploading '+percent+'%';
        if(percent===100){showVerificationWaiting();}
      };
      request.upload.onload=showVerificationWaiting;
      request.onload=function(){
        if(request.status===202){
          showVerificationWaiting();
          startVerificationPolling();
          return;
        }
        stopVerificationPolling();
        if(request.status>=200&&request.status<300){
          progressBar.value=100;
          progressLabel.textContent='100%';
          result.textContent=request.responseText;
          uploadInProgress=false;
          window.location.replace('/');
          return;
        }
        result.textContent=request.responseText||('Upload failed: HTTP '+request.status);
        progressBar.value=0;
        progressLabel.textContent='Rejected';
        uploadInProgress=false;
        if(resumeRefresh){setRefreshPaused(false);}
      };
      request.onerror=function(){
        stopVerificationPolling();
        result.textContent='Upload failed: connection lost';
        progressBar.value=0;
        progressLabel.textContent='Failed';
        uploadInProgress=false;
        if(resumeRefresh){setRefreshPaused(false);}
      };
      request.send(file);
    },0);
  });
});
</script>
</body>
</html>""")
    flattened = []
    for part in parts:
        if isinstance(part, list):
            flattened.extend(part)
        else:
            flattened.append(part)
    return flattened


def render_page(token, current_loglevel, levels, logs=None, log_refresh_ms=5000, status=None, modules=None, notice='', value_refresh_ms=0):
    return ''.join(render_page_parts(
        token,
        current_loglevel,
        levels,
        logs,
        log_refresh_ms,
        status,
        modules,
        notice,
        value_refresh_ms
    ))


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


async def start_web_portal(settings, log_getter, loglevel_getter, loglevel_setter, log_output, status_getter=None, module_getter=None, action_handler=None, upload_handler=None, firmware_upload_handler=None, config_backup_getter=None):
    if asyncio is None:
        return None

    token = settings.get('token', '')
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
    cookie = 'ham_session=' + session_id + '; Path=/; HttpOnly; SameSite=Strict'
    if settings.get('https', False):
        cookie += '; Secure'

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
            line = await reader.readline()
            if not line:
                await close_writer()
                return

            try:
                request_line = line.decode().strip()
            except Exception:
                request_line = ''

            method, path = parse_request_line(request_line)

            headers = {}
            while True:
                header = await reader.readline()
                if not header or header == b'\r\n':
                    break
                try:
                    header_text = header.decode().strip()
                    if ':' in header_text:
                        name, value = header_text.split(':', 1)
                        headers[name.lower()] = value.strip()
                except Exception:
                    pass

            progress_id = headers.get('x-update-id', '')[:64]
            if progress_id:
                progress_record = upload_progress_by_id.setdefault(
                    progress_id, {'phase': 'idle', 'percent': 0}
                )
                if len(upload_progress_by_id) > 8:
                    for old_id in list(upload_progress_by_id)[:-8]:
                        upload_progress_by_id.pop(old_id, None)

            action_path = path or ''
            csrf_error = False
            is_upload = bool(
                path and (
                    path.startswith('/update-upload') or
                    path.startswith('/firmware-upload')
                )
            )
            if method == 'POST' and not is_upload:
                length = int(headers.get('content-length', '0') or 0)
                if length > 65536:
                    raise ValueError('portal form exceeds 65536 bytes')
                body = await read_exact_body(reader, length) if length else b''
                try:
                    encoded = body.decode()
                except Exception:
                    encoded = ''
                if encoded:
                    action_path += ('&' if '?' in action_path else '?') + encoded
                form_csrf = parse_query(action_path).get('csrf', '')
                header_csrf = headers.get('x-csrf-token', '')
                csrf_error = (
                    form_csrf != session_id and header_csrf != session_id
                )
            elif method == 'POST' and is_upload:
                csrf_error = headers.get('x-csrf-token', '') != session_id

            if not path or method not in ('GET', 'POST'):
                body = 'Method not allowed'
                await send_response(writer, '405 Method Not Allowed', body, 'text/plain')
            elif method == 'GET' and is_authenticated(path, token):
                session_id = new_session_id()
                session_started = monotonic_ms()
                cookie = 'ham_session=' + session_id + '; Path=/; HttpOnly; SameSite=Strict'
                if settings.get('https', False):
                    cookie += '; Secure'
                cached_page['body'] = None
                login_failures = 0
                await send_redirect(
                    writer, '/', (('Set-Cookie', cookie), ('Referrer-Policy', 'no-referrer'))
                )
            elif (
                not has_portal_session(headers, session_id) or
                elapsed_ms(session_started) > session_timeout_ms
            ):
                login_failures += 1
                await asyncio.sleep(min(2, login_failures * 0.25))
                body = 'Unauthorized'
                await send_response(writer, '401 Unauthorized', body, 'text/plain')
            elif csrf_error:
                await send_response(writer, '403 Forbidden', 'Invalid CSRF token', 'text/plain')
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
                level = requested_loglevel(action_path, levels)
                if level:
                    apply_loglevel_change(level, loglevel_setter, log_output)
                    await send_redirect(writer, '/')
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
                    safe_logs.append(str(line).replace(token, '<redacted>'))
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
                apply_portal_action('discover', action_path, action_handler, log_output)
                await send_redirect(writer, '/')
            elif method == 'POST' and path.startswith('/calibrate'):
                apply_portal_action('calibrate', action_path, action_handler, log_output)
                await send_redirect(writer, '/')
            elif method == 'POST' and path.startswith('/ems-debug'):
                apply_portal_action('ems-debug', action_path, action_handler, log_output)
                await send_redirect(writer, '/')
            elif method == 'POST' and path.startswith('/activate-update'):
                apply_portal_action('activate-update', action_path, action_handler, log_output)
                await send_redirect(writer, '/')
            elif method == 'POST' and path.startswith('/activate-firmware'):
                apply_portal_action('activate-firmware', action_path, action_handler, log_output)
                await send_redirect(writer, '/')
            elif method == 'POST' and path.startswith('/rollback-application'):
                apply_portal_action('rollback-application', action_path, action_handler, log_output)
                await send_redirect(writer, '/')
            elif method == 'POST' and path.startswith('/check-release'):
                apply_portal_action('check-release', action_path, action_handler, log_output)
                await send_redirect(writer, '/')
            elif method == 'POST' and path.startswith('/validate-configuration'):
                result = apply_portal_action(
                    'validate-configuration', action_path, action_handler, log_output
                )
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
                current_level = loglevel_getter()
                if cached_page['body'] is None or cached_page['level'] != current_level:
                    cached_page['level'] = current_level
                    cached_page['body'] = render_page(
                        session_id, current_level, levels, [], log_refresh_ms,
                        {}, [], '', value_refresh_ms
                    )
                body = cached_page['body']
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

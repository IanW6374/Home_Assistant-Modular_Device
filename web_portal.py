try:
    import ssl
except ImportError:
    ssl = None

try:
    import asyncio
except ImportError:
    asyncio = None

try:
    import gc
except ImportError:
    gc = None

try:
    import json
except ImportError:
    json = None


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
        params[key] = value.replace('+', ' ')
    return params


def parse_request_line(line):
    parts = line.split()
    if len(parts) < 2:
        return None, None
    return parts[0], parts[1]


def is_authenticated(path, token):
    if not token:
        return False
    return parse_query(path).get('token') == token


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


def encoded_length(value, chunk_size=512):
    text = str(value)
    total = 0
    for offset in range(0, len(text), chunk_size):
        total += len(text[offset:offset + chunk_size].encode())
    return total


async def write_streamed_response(
    writer,
    status,
    body,
    content_type='text/html; charset=utf-8',
    extra_headers=None,
    chunk_size=1024
):
    body = str(body)
    headers = (
        'HTTP/1.1 ' + status + '\r\n'
        'Content-Type: ' + content_type + '\r\n'
        'Cache-Control: no-store\r\n'
        'Connection: close\r\n'
        'Content-Length: ' + str(encoded_length(body, chunk_size)) + '\r\n'
    )
    if extra_headers:
        for name, value in extra_headers:
            headers += str(name) + ': ' + str(value) + '\r\n'
    writer.write((headers + '\r\n').encode())
    await writer.drain()
    for offset in range(0, len(body), chunk_size):
        writer.write(body[offset:offset + chunk_size].encode())
        await writer.drain()


async def write_streamed_parts(
    writer,
    status,
    parts,
    content_type='text/html; charset=utf-8',
    chunk_size=1024
):
    content_length = 0
    for part in parts:
        content_length += encoded_length(part, chunk_size)
    headers = (
        'HTTP/1.1 ' + status + '\r\n'
        'Content-Type: ' + content_type + '\r\n'
        'Cache-Control: no-store\r\n'
        'Connection: close\r\n'
        'Content-Length: ' + str(content_length) + '\r\n\r\n'
    )
    writer.write(headers.encode())
    await writer.drain()
    for part in parts:
        text = str(part)
        for offset in range(0, len(text), chunk_size):
            writer.write(text[offset:offset + chunk_size].encode())
            await writer.drain()
        if gc:
            gc.collect()


async def write_streamed_redirect(writer, location):
    await write_streamed_response(
        writer,
        '303 See Other',
        'Redirecting',
        'text/plain',
        (('Location', location),)
    )


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
    'base_version': 'Base version',
    'platform': 'Platform',
    'runtime_version': 'MicroPython version',
    'heap_free_bytes': 'Free heap (bytes)',
    'heap_allocated_bytes': 'Allocated heap (bytes)',
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


def render_status_html(status):
    if not status:
        return ''

    cards = []
    for key in ('device_name', 'wifi_ip', 'mqtt', 'config', 'loglevel', 'uptime_s', 'discovery_count', 'heap_free_bytes', 'heap_allocated_bytes'):
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
    for key in ('running_version', 'base_version', 'update_version', 'update_status'):
        if key in status:
            value = status[key]
            if key == 'update_version' and not value:
                value = 'Not staged'
            version_class = {
                'running_version': ' version-app',
                'base_version': ' version-base',
                'update_version': ' version-staged',
                'update_status': ' version-status'
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
                '<form class="calibration-form" action="/calibrate" method="get">' +
                '<input type="hidden" name="token" value="' + html_escape(token) + '">' +
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
                '<form class="calibration-form" action="/ems-debug" method="get">' +
                '<input type="hidden" name="token" value="' + html_escape(token) + '">' +
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
                '<label><input name="' + key + '" type="checkbox" value="true"> ' +
                labels[key] + '</label>'
            )
    options = ''
    if option_html:
        options = (
            '<span class="update-options"><span class="update-options-label">Optional overwrite:</span>' +
            ''.join(option_html) + '</span>'
        )
    return (
        '<form action="/activate-update" method="get" class="update-activate">' +
        '<input type="hidden" name="token" value="' + html_escape(token) + '">' +
        options +
        '<button class="secondary" type="submit" title="Apply the selected overwrite options and reboot into the staged update. The previous application is retained for rollback.">Activate and reboot</button>' +
        '</form>'
    )


def render_firmware_update_html(status, token):
    if not status or not status.get('firmware_update_supported'):
        return ''
    staged = status.get('firmware_update_version', '') or 'Not staged'
    running = status.get('firmware_running_version', '') or 'Unknown'
    update_status = status.get('firmware_update_status', 'idle')
    activation = ''
    if update_status == 'ready':
        activation = (
            '<form action="/activate-firmware" method="get">' +
            '<input type="hidden" name="token" value="' + html_escape(token) + '">' +
            '<button class="secondary" type="submit" title="Boot the verified inactive firmware partition and require a healthy startup confirmation.">Activate firmware and reboot</button>' +
            '</form>'
        )
    return (
        '<section class="panel"><div class="section-title"><h2>Base firmware update</h2></div>' +
        '<div class="update-layout"><form id="firmware-upload-form" class="update-upload">' +
        '<span class="update-file"><input id="firmware-bundle" class="file-input-hidden" type="file" accept=".hamf,application/octet-stream" required>' +
        '<label class="file-button" for="firmware-bundle" title="Upload a bundle created by tools/build_firmware_update.py.">Choose firmware file</label>' +
        '<span id="firmware-file-name" class="file-name">No file selected</span></span>' +
        '<button type="submit" title="Write and verify the image in the inactive ESP32 OTA partition.">Upload and verify</button>' +
        '</form>' + activation + '</div>' +
        '<p class="muted update-result">Running firmware: <strong>' + html_escape(running) +
        '</strong> &middot; Staged firmware: <strong>' + html_escape(staged) +
        '</strong> &middot; Status: <strong>' + html_escape(update_status) + '</strong></p>' +
        '<p id="firmware-update-result" class="muted update-result"></p></section>'
    )


def render_page_parts(token, current_loglevel, levels, logs=None, log_refresh_ms=5000, status=None, modules=None, notice='', value_refresh_ms=0):
    options = []
    for level in levels:
        selected = ' selected' if level == current_loglevel else ''
        options.append('<option value="' + level + '"' + selected + '>' + level + '</option>')
    update_activation = render_update_activation_html(status or {}, token)
    firmware_update = render_firmware_update_html(status or {}, token)
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
.metric.version-staged{grid-column:5;grid-row:3}
.metric.version-status{grid-column:6;grid-row:3}
.metric span,.state-row span{display:block;color:var(--muted);font-size:.76rem;text-transform:uppercase;letter-spacing:.04em}
.metric span{white-space:nowrap;font-size:.72rem}
.metric strong{display:block;font-size:1rem;margin-top:.15rem;overflow-wrap:anywhere}
.metric.wide{grid-column:span 2}
.metric.wide strong{white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
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
.update-upload{display:flex;gap:.75rem 1rem;align-items:center;flex-wrap:wrap;min-width:0}
.update-file{display:flex;gap:.6rem;align-items:center;min-width:0}
.update-options{display:flex;gap:.45rem 1rem;align-items:center;flex-wrap:wrap;padding:.4rem .55rem;border:1px solid var(--line);border-radius:7px;background:#f8fafc}
.update-options-label{color:var(--muted);font-size:.78rem;font-weight:650}
.update-options label{font-size:.86rem;white-space:nowrap}
.update-result{margin:.7rem 0 0;min-height:1.4em}
.log-header-actions{display:flex;align-items:center;gap:.75rem;margin-left:auto}
.log-header-actions form{flex-wrap:nowrap}
.refresh-controls .badge,.refresh-toggle{box-sizing:border-box;width:100%}
.refresh-status{justify-content:center}
.refresh-toggle{text-align:center}
.calibration-form{border-top:1px solid var(--line);margin-top:.7rem;padding-top:.7rem}
.notice{background:#eef8f0;border:1px solid #a9d8b4;color:#175c2c;border-radius:8px;padding:.65rem .8rem;margin:1rem 0}
#logs{white-space:pre-wrap;overflow-wrap:anywhere;background:#111820;color:#dce7ef;padding:1rem;border-radius:8px;height:38vh;overflow-y:auto;border:1px solid #26313d}
@media(max-width:1000px){.metrics{grid-template-columns:repeat(auto-fit,minmax(10.5rem,1fr))}.metric.version-app,.metric.version-base,.metric.version-staged,.metric.version-status{grid-column:auto;grid-row:auto}}
@media(max-width:700px){.update-layout{grid-template-columns:1fr}.update-layout>form{justify-self:start}.log-header-actions{gap:.4rem}.metrics{grid-template-columns:repeat(auto-fit,minmax(9.5rem,1fr))}.metric.wide{grid-column:span 1}}
@media(max-width:560px){main{padding:.7rem}.topbar{align-items:flex-start;flex-direction:column}.module-grid{grid-template-columns:1fr}.controls{align-items:stretch}.control-group,form{width:100%}button,select,input{max-width:100%}.log-header-actions{align-items:flex-end;flex-direction:column}.log-header-actions form{width:auto}}
</style>
</head>
<body>
<main>
<div class="topbar"><div><h1>Device Portal</h1></div></div>
""", ('<p class="notice">' + html_escape(notice) + '</p>' if notice else ''), """
""", live_parts, """
<section class="panel"><div class="section-title"><h2>Controls</h2></div>
<div class="controls"><form action="/discover" method="get">
<input type="hidden" name="token" value=\"""", html_escape(token), """\">
<button type="submit" title="Republish Home Assistant MQTT discovery config for all loaded entities.">Publish Discovery</button>
</form>
<form action="/set-loglevel" method="get" class="control-group">
<input type="hidden" name="token" value=\"""", html_escape(token), """\">
<label for="level" title="Controls how much firmware logging is shown and published.">Debug level</label>
<select id="level" name="level" title="ERROR is quiet, INFO is normal, DEBUG includes MQTT detail.">""", ''.join(options), """</select>
<button class="secondary" type="submit" title="Apply the selected runtime log level until the device restarts.">Apply</button>
</form>
</div>
</section>
<section class="panel"><div class="section-title"><h2>Application update</h2></div>
<div class="update-layout"><form id="update-upload-form" class="update-upload">
<span class="update-file"><input id="update-bundle" class="file-input-hidden" type="file" accept=".hamd,application/octet-stream" required>
<label class="file-button" for="update-bundle" title="Upload a bundle created by tools/build_update.py. Application files are staged and verified before reboot.">Choose update file</label>
<span id="update-file-name" class="file-name">No file selected</span></span>
<button type="submit" title="Upload, verify, and stage this application bundle.">Upload and stage</button>
</form>
""", update_activation, """</div>
<p id="update-result" class="muted update-result"></p>
</section>
""", firmware_update, """
<section class="panel"><div class="section-title"><h2>Logs</h2><div class="log-header-actions"><form action="/download-logs" method="get">
<input type="hidden" name="token" value=\"""", html_escape(token), """\">
<button class="secondary compact" type="submit" title="Download the current in-memory device log as a text file.">Download logs</button>
</form>""", render_refresh_controls_html('log-refresh-toggle'), """</div></div>
<pre id="logs"></pre>
</section>
</main>
<script>
var token='""", js_escape(token), """';
var logRefreshMs=""", str(log_refresh_ms), """;
var valueRefreshMs=""", str(value_refresh_ms), """;
var autoRefreshPaused=false;
var refreshTimer=null;
var lastLogRefresh=0;
var lastValueRefresh=0;
var uploadInProgress=false;
var refreshBusy=false;
var refreshInProgress=Promise.resolve();
var tlsSettleMs=750;
function nearBottom(el){return el.scrollHeight-el.scrollTop-el.clientHeight<48;}
function settleConnection(){return new Promise(function(resolve){setTimeout(resolve,tlsSettleMs);});}
function refreshLogs(){
  if(autoRefreshPaused){return Promise.resolve();}
  var el=document.getElementById('logs');
  var keepBottom=nearBottom(el);
  return fetch('/logs?token='+encodeURIComponent(token),{cache:'no-store'})
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
  return fetch('/partials?token='+encodeURIComponent(token),{cache:'no-store'})
    .then(function(r){if(r.ok){return r.text();}})
    .then(function(html){
      var el=document.getElementById('live-sections');
      if(html!==undefined&&el&&el.outerHTML!==html){
        el.outerHTML=html;
        updateRefreshControls();
      }
    });
}
function refreshAll(){
  if(autoRefreshPaused||uploadInProgress||refreshBusy){return refreshInProgress;}
  var now=Date.now();
  var chain=Promise.resolve();
  var refreshedLogs=false;
  if(logRefreshMs>0&&(lastLogRefresh===0||now-lastLogRefresh>=logRefreshMs)){
    lastLogRefresh=now;
    chain=chain.then(refreshLogs);
    refreshedLogs=true;
  }
  if(valueRefreshMs>0&&(lastValueRefresh===0||now-lastValueRefresh>=valueRefreshMs)){
    lastValueRefresh=now;
    if(refreshedLogs){chain=chain.then(settleConnection);}
    chain=chain.then(refreshValues);
  }
  refreshBusy=true;
  refreshInProgress=chain.then(
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
  setTimeout(refreshAll,1200);
});
document.addEventListener('click',function(event){
  if(event.target&&event.target.classList&&event.target.classList.contains('refresh-toggle')){setRefreshPaused(!autoRefreshPaused);}
});
document.addEventListener('change',function(event){
  if(!event.target){return;}
  var name=null;
  if(event.target.id==='update-bundle'){name=document.getElementById('update-file-name');}
  if(event.target.id==='firmware-bundle'){name=document.getElementById('firmware-file-name');}
  if(!name){return;}
  if(name){name.textContent=event.target.files&&event.target.files.length?event.target.files[0].name:'No file selected';}
});
document.addEventListener('submit',function(event){
  if(!event.target||event.target.id!=='update-upload-form'){return;}
  event.preventDefault();
  var input=document.getElementById('update-bundle');
  var result=document.getElementById('update-result');
  if(!input||!input.files||!input.files.length){return;}
  var resumeRefresh=!autoRefreshPaused;
  uploadInProgress=true;
  setRefreshPaused(true);
  result.textContent='Waiting for current portal request...';
  var updateUrl='/update-upload?token='+encodeURIComponent(token);
  refreshInProgress.then(function(){
    setTimeout(function(){
      result.textContent='Uploading and verifying...';
      fetch(updateUrl,{
        method:'POST',headers:{'Content-Type':'application/octet-stream'},body:input.files[0]
      }).then(function(r){return r.text().then(function(t){if(!r.ok){throw new Error(t);}return t;});})
        .then(function(text){result.textContent=text;uploadInProgress=false;window.location.replace('/?token='+encodeURIComponent(token));})
        .catch(function(error){result.textContent=error.message;uploadInProgress=false;if(resumeRefresh){setRefreshPaused(false);}});
    },400);
  });
});
document.addEventListener('submit',function(event){
  if(!event.target||event.target.id!=='firmware-upload-form'){return;}
  event.preventDefault();
  var input=document.getElementById('firmware-bundle');
  var result=document.getElementById('firmware-update-result');
  if(!input||!input.files||!input.files.length){return;}
  var resumeRefresh=!autoRefreshPaused;
  uploadInProgress=true;
  setRefreshPaused(true);
  result.textContent='Waiting for current portal request...';
  refreshInProgress.then(function(){
    setTimeout(function(){
      result.textContent='Uploading and verifying base firmware...';
      fetch('/firmware-upload?token='+encodeURIComponent(token),{
        method:'POST',headers:{'Content-Type':'application/octet-stream'},body:input.files[0]
      }).then(function(r){return r.text().then(function(t){if(!r.ok){throw new Error(t);}return t;});})
        .then(function(text){result.textContent=text;uploadInProgress=false;window.location.replace('/?token='+encodeURIComponent(token));})
        .catch(function(error){result.textContent=error.message;uploadInProgress=false;if(resumeRefresh){setRefreshPaused(false);}});
    },400);
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

    if gc:
        gc.collect()

    for path, label in ((cert_path, 'certificate'), (key_path, 'private key')):
        try:
            with open(path, 'rb'):
                pass
        except Exception as exc:
            raise RuntimeError('HTTPS ' + label + ' file not found or unreadable: ' + str(path) + ' - ' + str(exc))

    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    if gc:
        gc.collect()
    try:
        context.load_cert_chain(cert_path, key_path)
    except Exception as exc:
        detail = str(exc)
        if 'invalid key' in detail:
            detail += ' - regenerate the HTTPS key as a traditional RSA key or convert the cert/key to DER for this MicroPython build.'
        raise RuntimeError('Could not load HTTPS certificate/key: ' + detail)
    if gc:
        gc.collect()
    return context


async def start_web_portal(settings, log_getter, loglevel_getter, loglevel_setter, log_output, status_getter=None, module_getter=None, action_handler=None, upload_handler=None, firmware_upload_handler=None):
    if asyncio is None:
        return None

    token = settings.get('token', '')
    levels = settings.get('levels', ('ERROR', 'INFO', 'DEBUG'))
    log_refresh_ms = settings.get('log_refresh_ms', 5000)
    value_refresh_ms = settings.get('value_refresh_ms', 0)

    async def handle_client(reader, writer):
        path = ''
        upload_state = ''
        if gc:
            gc.collect()

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

            if not path or method not in ('GET', 'POST'):
                body = 'Method not allowed'
                await write_streamed_response(writer, '405 Method Not Allowed', body, 'text/plain')
            elif not is_authenticated(path, token):
                body = 'Unauthorized'
                await write_streamed_response(writer, '401 Unauthorized', body, 'text/plain')
            elif method == 'POST' and path.startswith('/update-upload'):
                if upload_handler is None:
                    await write_streamed_response(writer, '503 Service Unavailable', 'Application updates are unavailable', 'text/plain')
                else:
                    try:
                        length = int(headers.get('content-length', '0'))
                        upload_state = 'receiving'
                        log_output(
                            'Local', 'Application update',
                            {'log': 'Upload started - ' + str(length) + ' bytes', 'force': True},
                            'INFO'
                        )
                        if gc:
                            gc.collect()
                        result = await upload_handler(reader, length, parse_query(path))
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
                        await write_streamed_response(writer, '400 Bad Request', 'Update rejected: ' + str(exc), 'text/plain')
                    else:
                        upload_state = 'staged'
                        log_output(
                            'Local', 'Application update',
                            {'log': 'Upload completed and staged', 'force': True},
                            'INFO'
                        )
                        await write_streamed_response(writer, '200 OK', str(result), 'text/plain')
                        upload_state = 'responded'
            elif method == 'POST' and path.startswith('/firmware-upload'):
                if firmware_upload_handler is None:
                    await write_streamed_response(writer, '503 Service Unavailable', 'Base firmware updates are unavailable', 'text/plain')
                else:
                    try:
                        length = int(headers.get('content-length', '0'))
                        log_output('Local', 'Base firmware', {'log': 'Upload started - ' + str(length) + ' bytes', 'force': True}, 'INFO')
                        if gc:
                            gc.collect()
                        result = await firmware_upload_handler(reader, length, parse_query(path))
                    except Exception as exc:
                        try:
                            log_output('Local', 'Base firmware', {'log': 'Upload rejected - ' + str(exc), 'force': True}, 'ERROR')
                        except Exception:
                            pass
                        await write_streamed_response(writer, '400 Bad Request', 'Firmware rejected: ' + str(exc), 'text/plain')
                    else:
                        log_output('Local', 'Base firmware', {'log': 'Upload completed and verified', 'force': True}, 'INFO')
                        await write_streamed_response(writer, '200 OK', str(result), 'text/plain')
            elif method != 'GET':
                await write_streamed_response(writer, '405 Method Not Allowed', 'Method not allowed', 'text/plain')
            elif path.startswith('/set-loglevel'):
                level = requested_loglevel(path, levels)
                if level:
                    apply_loglevel_change(level, loglevel_setter, log_output)
                    await write_streamed_redirect(writer, '/?token=' + token)
                else:
                    body = 'Invalid log level'
                    await write_streamed_response(writer, '400 Bad Request', body, 'text/plain')
            elif path.startswith('/logs'):
                body = render_log_text(log_getter())
                await write_streamed_response(writer, '200 OK', body, 'text/plain')
            elif path.startswith('/download-logs'):
                body = render_log_text(log_getter())
                await write_streamed_response(
                    writer,
                    '200 OK',
                    body,
                    'text/plain; charset=utf-8',
                    (('Content-Disposition', 'attachment; filename="ha-device-logs.txt"'),)
                )
            elif path.startswith('/api/status'):
                payload = {
                    'status': status_getter() if status_getter else {},
                    'modules': module_getter() if module_getter else []
                }
                body = json.dumps(payload) if json else '{}'
                await write_streamed_response(writer, '200 OK', body, 'application/json')
            elif path.startswith('/partials'):
                if gc:
                    gc.collect()
                parts = render_live_sections_parts(
                    status_getter() if status_getter else {},
                    module_getter() if module_getter else [],
                    token
                )
                await write_streamed_parts(writer, '200 OK', parts)
            elif path.startswith('/discover'):
                apply_portal_action('discover', path, action_handler, log_output)
                await write_streamed_redirect(writer, '/?token=' + token)
            elif path.startswith('/calibrate'):
                apply_portal_action('calibrate', path, action_handler, log_output)
                await write_streamed_redirect(writer, '/?token=' + token)
            elif path.startswith('/ems-debug'):
                apply_portal_action('ems-debug', path, action_handler, log_output)
                await write_streamed_redirect(writer, '/?token=' + token)
            elif path.startswith('/activate-update'):
                apply_portal_action('activate-update', path, action_handler, log_output)
                await write_streamed_redirect(writer, '/?token=' + token)
            elif path.startswith('/activate-firmware'):
                apply_portal_action('activate-firmware', path, action_handler, log_output)
                await write_streamed_redirect(writer, '/?token=' + token)
            else:
                parts = render_page_parts(
                    token,
                    loglevel_getter(),
                    levels,
                    log_getter(),
                    log_refresh_ms,
                    status_getter() if status_getter else {},
                    module_getter() if module_getter else [],
                    '',
                    value_refresh_ms
                )
                await write_streamed_parts(writer, '200 OK', parts)

            await writer.drain()
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
            if gc:
                gc.collect()

    if gc:
        gc.collect()

    ssl_context = None
    if settings.get('https', False):
        ssl_context = make_tls_context(settings.get('cert_path'), settings.get('key_path'))

    if gc:
        gc.collect()

    return await asyncio.start_server(
        handle_client,
        settings.get('host', '0.0.0.0'),
        settings.get('port', 8443 if settings.get('https', False) else 8080),
        backlog=1,
        ssl=ssl_context
    )

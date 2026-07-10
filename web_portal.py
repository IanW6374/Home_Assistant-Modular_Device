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


def query_value(path, key, default=''):
    return parse_query(path).get(key, default)


def is_client_disconnect_error(exc):
    args = getattr(exc, 'args', ())
    if args and args[0] == -29312:
        return True
    return 'MBEDTLS_ERR_SSL_CONN_EOF' in str(exc)


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


def render_label(key):
    return html_escape(str(key).replace('_', ' '))


def render_badge(label, tone='neutral'):
    return '<span class="badge ' + html_escape(tone) + '">' + html_escape(label) + '</span>'


DIAGNOSTIC_HELP = {
    'module_last_ok': 'Whether the most recent module read completed successfully.',
    'module_last_error': 'Last module read error. Empty means no current error is recorded.',
    'module_last_read_ms': 'How long the most recent module read took, in milliseconds.',
    'module_last_publish_age_s': 'Seconds since this module last published state. In HA this is updated only when MQTT state is published.',
    'module_consecutive_errors': 'Number of failed module reads since the last successful read.',
    'rs485_last_ok': 'Whether the most recent RS485 request completed successfully.',
    'rs485_last_operation': 'Operation type for the most recent RS485 request.',
    'rs485_last_address': 'Register address used by the most recent RS485 request.',
    'rs485_last_error': 'Last RS485 request error. Empty means no current error is recorded.',
    'rs485_last_latency_ms': 'How long the most recent RS485 request took, in milliseconds.',
}


def diagnostic_help(key):
    return DIAGNOSTIC_HELP.get(key, 'Diagnostic value for module troubleshooting.')


def render_status_html(status):
    if not status:
        return ''

    cards = []
    for key in ('device_name', 'wifi_ip', 'mqtt', 'config', 'loglevel', 'uptime_s', 'discovery_count'):
        if key in status:
            value = status[key]
            tone = ''
            if key == 'mqtt':
                tone = ' good' if str(value).lower() == 'up' else ' warn'
            cards.append(
                '<div class="metric' + tone + '"><span>' + render_label(key) +
                '</span><strong>' + html_escape(value) + '</strong></div>'
            )
    return (
        '<section class="panel"><div class="section-title"><h2>Status</h2>' +
        render_badge('live', 'good') + '</div><div class="metrics">' +
        ''.join(cards) + '</div></section>'
    )


def render_state_html(state):
    if not state:
        return '<p class="muted">No state yet.</p>'

    rows = []
    for key in state:
        rows.append(
            '<div class="state-row"><span>' + render_label(key) +
            '</span><strong>' + html_escape(state[key]) + '</strong></div>'
        )
    return '<div class="state-grid">' + ''.join(rows) + '</div>'


def render_diagnostics_html(diagnostics):
    if not diagnostics:
        return ''

    rows = []
    for key in diagnostics:
        rows.append(
            '<div class="diag-row" title="' + html_escape(diagnostic_help(key)) + '"><span>' + render_label(key) +
            '</span><strong>' + html_escape(diagnostics[key]) + '</strong></div>'
        )
    return (
        '<div class="diag-tile"><div class="diag-title">Diagnostics</div>' +
        '<div class="diag-grid">' + ''.join(rows) + '</div></div>'
    )


def render_modules_html(modules, token):
    if not modules:
        return '<section class="panel"><div class="section-title"><h2>Modules</h2>' + render_badge('0 loaded') + '</div><p class="muted">No modules loaded.</p></section>'

    cards = []
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

        cards.append(
            '<article class="module-card"><div class="module-head"><div>' +
            '<h3>' + html_escape(module.get('name', '')) + '</h3>' +
            '<p>' + html_escape(module.get('type', '')) + ' / ' + html_escape(module.get('uuid', '')) + '</p>' +
            '</div>' + health_badge + '</div>' +
            error_html + render_state_html(state) + render_diagnostics_html(diagnostics) +
            calibration + '</article>'
        )

    return (
        '<section class="panel"><div class="section-title"><h2>Modules</h2>' +
        render_badge(str(len(modules)) + ' loaded') + '</div><div class="module-grid">' +
        ''.join(cards) + '</div></section>'
    )


def render_page(token, current_loglevel, levels, logs=None, refresh_ms=5000, status=None, modules=None, notice=''):
    options = []
    for level in levels:
        selected = ' selected' if level == current_loglevel else ''
        options.append('<option value="' + level + '"' + selected + '>' + level + '</option>')

    return """<!doctype html>
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
.metrics{display:grid;grid-template-columns:repeat(auto-fit,minmax(9rem,1fr));gap:.65rem}
.metric{border:1px solid var(--line);border-radius:7px;padding:.65rem;background:#fbfcfd;min-width:0}
.metric span,.state-row span{display:block;color:var(--muted);font-size:.76rem;text-transform:uppercase;letter-spacing:.04em}
.metric strong{display:block;font-size:1rem;margin-top:.15rem;overflow-wrap:anywhere}
.metric.good{border-color:#9ed6bd;background:#f1fbf6}
.metric.warn{border-color:#efcf92;background:#fff8eb}
.badge{display:inline-flex;align-items:center;border-radius:999px;border:1px solid var(--line);padding:.15rem .55rem;font-size:.76rem;font-weight:650;color:var(--muted);background:#f8fafc;white-space:nowrap}
.badge.good{color:var(--good);border-color:#9ed6bd;background:#f1fbf6}
.badge.warn{color:var(--warn);border-color:#efcf92;background:#fff8eb}
.module-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(18rem,1fr));gap:.8rem}
.module-card{border:1px solid var(--line);border-radius:8px;padding:.85rem;background:#fbfcfd;min-width:0}
.module-head{display:flex;align-items:flex-start;justify-content:space-between;gap:.8rem;margin-bottom:.7rem}
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
select,button,input{font:inherit;padding:.45rem .6rem;border:1px solid var(--line);border-radius:7px;background:white;color:var(--ink)}
button{background:var(--accent);border-color:var(--accent);color:white;font-weight:650;cursor:pointer}
button.secondary{background:white;color:var(--accent)}
.calibration-form{border-top:1px solid var(--line);margin-top:.7rem;padding-top:.7rem}
.notice{background:#eef8f0;border:1px solid #a9d8b4;color:#175c2c;border-radius:8px;padding:.65rem .8rem;margin:1rem 0}
#logs{white-space:pre-wrap;overflow-wrap:anywhere;background:#111820;color:#dce7ef;padding:1rem;border-radius:8px;height:38vh;overflow-y:auto;border:1px solid #26313d}
@media(max-width:560px){main{padding:.7rem}.topbar{align-items:flex-start;flex-direction:column}.module-grid{grid-template-columns:1fr}.controls{align-items:stretch}.control-group,form{width:100%}button,select,input{max-width:100%}}
</style>
</head>
<body>
<main>
<div class="topbar"><div><h1>Device Portal</h1><p>""" + html_escape((status or {}).get('device_name', 'Pico device')) + """</p></div></div>
""" + ('<p class="notice">' + html_escape(notice) + '</p>' if notice else '') + """
""" + render_status_html(status or {}) + """
""" + render_modules_html(modules or [], token) + """
<section class="panel"><div class="section-title"><h2>Controls</h2></div>
<div class="controls"><form action="/discover" method="get">
<input type="hidden" name="token" value=\"""" + html_escape(token) + """\">
<button type="submit" title="Republish Home Assistant MQTT discovery config for all loaded entities.">Publish Discovery</button>
</form>
<form action="/set-loglevel" method="get" class="control-group">
<input type="hidden" name="token" value=\"""" + html_escape(token) + """\">
<label for="level" title="Controls how much firmware logging is shown and published.">Debug level</label>
<select id="level" name="level" title="ERROR is quiet, INFO is normal, DEBUG includes MQTT detail.">""" + ''.join(options) + """</select>
<button class="secondary" type="submit" title="Apply the selected runtime log level until the device restarts.">Apply</button>
</form></div>
</section>
<section class="panel"><div class="section-title"><h2>Logs</h2>""" + render_badge('auto refresh') + """</div>
<pre id="logs"></pre>
</section>
</main>
<script>
var token='""" + js_escape(token) + """';
var refreshMs=""" + str(refresh_ms) + """;
function nearBottom(el){return el.scrollHeight-el.scrollTop-el.clientHeight<48;}
function refreshLogs(){
  var el=document.getElementById('logs');
  var keepBottom=nearBottom(el);
  fetch('/logs?token='+encodeURIComponent(token),{cache:'no-store'})
    .then(function(r){if(r.ok){return r.text();}})
    .then(function(text){
      if(text!==undefined&&el.textContent!==text){
        el.textContent=text;
        if(keepBottom){el.scrollTop=el.scrollHeight;}
      }
    });
}
window.addEventListener('load',function(){
  refreshLogs();
  if(refreshMs>0){setInterval(refreshLogs,refreshMs);}
});
</script>
</body>
</html>"""


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


async def start_web_portal(settings, log_getter, loglevel_getter, loglevel_setter, log_output, status_getter=None, module_getter=None, action_handler=None):
    if asyncio is None:
        return None

    token = settings.get('token', '')
    levels = settings.get('levels', ('ERROR', 'INFO', 'DEBUG'))
    refresh_ms = settings.get('refresh_ms', 5000)

    async def handle_client(reader, writer):
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

            while True:
                header = await reader.readline()
                if not header or header == b'\r\n':
                    break

            if method != 'GET' or not path:
                body = 'Method not allowed'
                writer.write(response('405 Method Not Allowed', body, 'text/plain').encode())
            elif not is_authenticated(path, token):
                body = 'Unauthorized'
                writer.write(response('401 Unauthorized', body, 'text/plain').encode())
            elif path.startswith('/set-loglevel'):
                level = requested_loglevel(path, levels)
                if level:
                    loglevel_setter(level)
                    log_output('Local', 'Web portal', {'log': 'Log level changed to ' + level}, 'INFO')
                    writer.write(redirect('/?token=' + token).encode())
                else:
                    body = 'Invalid log level'
                    writer.write(response('400 Bad Request', body, 'text/plain').encode())
            elif path.startswith('/logs'):
                body = render_log_text(log_getter())
                writer.write(response('200 OK', body, 'text/plain').encode())
            elif path.startswith('/api/status'):
                payload = {
                    'status': status_getter() if status_getter else {},
                    'modules': module_getter() if module_getter else []
                }
                body = json.dumps(payload) if json else '{}'
                writer.write(response('200 OK', body, 'application/json').encode())
            elif path.startswith('/discover'):
                notice = 'Discovery requested'
                if action_handler:
                    notice = str(action_handler('discover', parse_query(path)))
                body = render_page(token, loglevel_getter(), levels, log_getter(), refresh_ms, status_getter() if status_getter else {}, module_getter() if module_getter else [], notice)
                writer.write(response('200 OK', body).encode())
            elif path.startswith('/calibrate'):
                notice = 'Calibration request ignored'
                if action_handler:
                    notice = str(action_handler('calibrate', parse_query(path)))
                body = render_page(token, loglevel_getter(), levels, log_getter(), refresh_ms, status_getter() if status_getter else {}, module_getter() if module_getter else [], notice)
                writer.write(response('200 OK', body).encode())
            else:
                body = render_page(token, loglevel_getter(), levels, log_getter(), refresh_ms, status_getter() if status_getter else {}, module_getter() if module_getter else [])
                writer.write(response('200 OK', body).encode())

            await writer.drain()
        except Exception as exc:
            if is_client_disconnect_error(exc):
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

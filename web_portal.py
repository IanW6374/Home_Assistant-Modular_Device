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


def render_page(token, current_loglevel, levels, logs=None, refresh_ms=5000):
    options = []
    for level in levels:
        selected = ' selected' if level == current_loglevel else ''
        options.append('<option value="' + level + '"' + selected + '>' + level + '</option>')

    return """<!doctype html>
<html>
<head>
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Device Logs</title>
<style>
body{font-family:system-ui,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;margin:1rem;line-height:1.4;background:#f6f7f9;color:#171b22}
main{max-width:64rem;margin:0 auto}
form{display:flex;gap:.5rem;align-items:center;margin:1rem 0}
select,button{font:inherit;padding:.45rem .6rem}
#logs{white-space:pre-wrap;overflow-wrap:anywhere;background:#111820;color:#dce7ef;padding:1rem;border-radius:6px;height:70vh;overflow-y:auto}
</style>
</head>
<body>
<main>
<h1>Device Logs</h1>
<form action="/set-loglevel" method="get">
<input type="hidden" name="token" value=\"""" + html_escape(token) + """\">
<label for="level">Debug level</label>
<select id="level" name="level">""" + ''.join(options) + """</select>
<button type="submit">Apply</button>
</form>
<pre id="logs"></pre>
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


async def start_web_portal(settings, log_getter, loglevel_getter, loglevel_setter, log_output):
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
            else:
                body = render_page(token, loglevel_getter(), levels, log_getter(), refresh_ms)
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

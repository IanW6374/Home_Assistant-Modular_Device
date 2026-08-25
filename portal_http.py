"""HTTP, authentication, and response primitives for the device portal."""

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
    import time
except ImportError:
    time = None
try:
    import ubinascii as binascii
except ImportError:
    import binascii
try:
    import uos as os
except ImportError:
    import os

import http_support

HTML_ESCAPE = {
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
}
JS_ESCAPE = {'\\': '\\\\', "'": "\\'", '\n': '\\n', '\r': '\\r'}

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

def parse_portal_body(route, headers, body):
    """Parse a small form body without duplicating JSON upload payloads."""
    content_type = str(headers.get('content-type', '')).split(';', 1)[0].strip()
    if content_type == 'application/json':
        if route == '/validate-configuration':
            try:
                return {'config_json': body.decode()}
            except Exception:
                return {'config_json': ''}
        # JSON API endpoints consume body directly. Avoid retaining another
        # full copy as URL-decoded form fields on memory-constrained devices.
        return {}
    try:
        encoded = body.decode()
    except Exception:
        encoded = ''
    return parse_query('?' + encoded) if encoded else {}

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
    return bool(session_id) and parse_cookies(headers).get('iotmd_session') == session_id

def session_cookie(session_id, secure=False, clear=False):
    cookie = 'iotmd_session=' + str(session_id) + '; Path=/; HttpOnly; SameSite=Strict'
    if clear:
        cookie += '; Max-Age=0'
    if secure:
        cookie += '; Secure'
    return cookie

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


class TimedSnapshot:
    """Briefly reuse expensive read-only portal view models."""
    def __init__(self, getter, ttl_ms=1000, fallback=None):
        self.getter = getter
        self.ttl_ms = int(ttl_ms)
        self.fallback = fallback
        self.value = None
        self.started = None

    def get(self):
        if (
            self.started is None or
            elapsed_ms(self.started) >= self.ttl_ms
        ):
            self.value = self.getter() if self.getter else self.fallback
            self.started = monotonic_ms()
        return self.value

    def invalidate(self):
        self.started = None

def requested_loglevel(path, allowed_levels):
    level = parse_query(path).get('level', '').upper()
    if level in allowed_levels:
        return level
    return None

def apply_loglevel_change(level, loglevel_setter, log_output):
    loglevel_setter(level)
    log_output('Local', 'Web portal', {'log': 'Log level changed to ' + level, 'force': True}, 'INFO')

def apply_logging_change(
    level, line_count, allowed_levels, loglevel_setter,
    log_buffer_lines_setter, log_output
):
    level = str(level or '').upper()
    try:
        line_count = int(line_count)
    except (TypeError, ValueError):
        raise ValueError('retained-line limit must be a number')
    if level not in allowed_levels:
        raise ValueError('invalid log level')
    if not 0 <= line_count <= 500:
        raise ValueError('retained-line limit must be between 0 and 500')
    if log_buffer_lines_setter is None:
        raise RuntimeError('runtime log retention control is unavailable')
    loglevel_setter(level)
    log_buffer_lines_setter(line_count)
    log_output(
        'Local', 'Web portal',
        {'log': 'Logging changed to ' + level + ' with ' +
         str(line_count) + ' retained lines', 'force': True}, 'INFO'
    )
    return level, line_count

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
        failed = 'failed' in notice.lower()
        log_output(
            'Local', 'Web portal', {'log': notice, 'force': True},
            'ERROR' if failed else 'INFO'
        )
    return result

def log_upgrade_upload_failure(log_output, phase, exc):
    log_output(
        'Local', 'Upgrade',
        {'log': 'Upload ' + str(phase) + ' failed - ' + str(exc), 'force': True},
        'ERROR'
    )

def query_value(path, key, default=''):
    return parse_query(path).get(key, default)

def is_client_disconnect_error(exc):
    args = getattr(exc, 'args', ())
    if args and args[0] in (-29312, -30592, 32, 54, 103, 104, 113):
        return True
    detail = str(exc)
    return (
        'ECONNABORTED' in detail or
        'ECONNRESET' in detail or
        'Broken pipe' in detail or
        'MBEDTLS_ERR_SSL_CONN_EOF' in detail or
        'MBEDTLS_ERR_SSL_BAD_PROTOCOL_VERSION' in detail or
        'MBEDTLS_ERR_SSL_FATAL_ALERT_MESSAGE' in detail
    )


def compatible_http_reader(reader):
    """Use buffered core reads when available, retaining older-core startup."""
    buffer_reader = getattr(http_support, 'buffered', None)
    buffered_api = int(getattr(http_support, 'BUFFERED_READER_API', 0) or 0)
    return buffer_reader(reader) if buffer_reader and buffered_api >= 2 else reader


def is_http_timeout_error(exc):
    checker = getattr(http_support, 'is_timeout_error', None)
    return checker(exc) if checker else exc.__class__.__name__ == 'TimeoutError'

def request_peer_address(reader, writer=None):
    """Return a useful audit address across CPython and MicroPython streams."""
    for stream in (reader, writer):
        if stream is None:
            continue
        getter = getattr(stream, 'get_extra_info', None)
        if getter:
            try:
                value = getter('peername')
                if value:
                    return str(value[0] if isinstance(value, tuple) else value)
            except Exception:
                pass
        socket_value = getattr(stream, 's', None)
        if socket_value is not None and hasattr(socket_value, 'getpeername'):
            try:
                value = socket_value.getpeername()
                return str(value[0] if isinstance(value, tuple) else value)
            except Exception:
                pass
    return 'unknown'

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

def download_response(body, filename='iotmd-logs.txt'):
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

def configuration_backup_filename(complete=False, epoch=None):
    """Return a filesystem-safe UTC timestamped configuration filename."""
    try:
        value = time.time() if epoch is None else int(epoch)
        converter = getattr(time, 'gmtime', None) or time.localtime
        current = converter(value)
        stamp = '{:04}{:02}{:02}-{:02}{:02}{:02}Z'.format(
            current[0], current[1], current[2],
            current[3], current[4], current[5]
        )
    except Exception:
        stamp = 'time-unavailable'
    return (
        'iotmd-complete-' + stamp + '.encrypted.json'
        if complete else
        'iotmd-configuration-' + stamp + '.json'
    )

async def write_buffered_response(
    writer,
    status,
    body,
    content_type='text/html; charset=utf-8',
    extra_headers=None,
    keep_alive=False
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
        'Connection: ' + ('keep-alive' if keep_alive else 'close') + '\r\n'
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

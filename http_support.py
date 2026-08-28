"""Bounded HTTP parsing and common browser security headers."""

try:
    import uasyncio as asyncio
except ImportError:
    import asyncio


MAX_REQUEST_LINE_BYTES = 2048
MAX_HEADER_LINE_BYTES = 2048
MAX_HEADER_BYTES = 8192
MAX_HEADER_COUNT = 40
REQUEST_TIMEOUT_SECONDS = 10
BODY_TIMEOUT_SECONDS = 20
READ_BUFFER_BYTES = 512
BUFFERED_READER_API = 2

SECURITY_HEADERS = (
    ('Referrer-Policy', 'no-referrer'),
    ('X-Content-Type-Options', 'nosniff'),
    ('X-Frame-Options', 'DENY'),
    ('Content-Security-Policy', "frame-ancestors 'none'; base-uri 'self'; form-action 'self'"),
    ('Permissions-Policy', 'camera=(), microphone=(), geolocation=()'),
)


class BufferedReader:
    """Preserve over-read bytes while reducing encrypted socket read calls."""
    def __init__(self, reader, chunk_size=READ_BUFFER_BYTES):
        self.reader = reader
        self.chunk_size = max(64, int(chunk_size))
        self.buffer = bytearray()
        # TLS peer-certificate helpers inspect the stream's underlying socket.
        self.s = getattr(reader, 's', None)

    def get_extra_info(self, name):
        getter = getattr(self.reader, 'get_extra_info', None)
        return getter(name) if getter else None

    async def read(self, size):
        size = int(size)
        if size <= 0:
            return b''
        while len(self.buffer) < size:
            chunk = await self.reader.read(max(self.chunk_size, size - len(self.buffer)))
            if not chunk:
                break
            self.buffer.extend(chunk)
        count = min(size, len(self.buffer))
        result = bytes(self.buffer[:count])
        self.buffer = self.buffer[count:]
        return result

    async def read_bounded_line(self, maximum):
        maximum = int(maximum)
        while True:
            newline = self.buffer.find(b'\n')
            if newline >= 0:
                count = newline + 1
                if count > maximum:
                    raise ValueError('HTTP line exceeds the configured limit')
                result = bytes(self.buffer[:count])
                self.buffer = self.buffer[count:]
                return result
            if len(self.buffer) > maximum:
                raise ValueError('HTTP line exceeds the configured limit')
            chunk = await self.reader.read(self.chunk_size)
            if not chunk:
                result = bytes(self.buffer)
                self.buffer = bytearray()
                if len(result) > maximum:
                    raise ValueError('HTTP line exceeds the configured limit')
                return result
            self.buffer.extend(chunk)


def buffered(reader):
    return reader if isinstance(reader, BufferedReader) else BufferedReader(reader)


def is_timeout_error(exc):
    """Recognise CPython and MicroPython async idle timeouts."""
    return exc.__class__.__name__ == 'TimeoutError'


async def close_writer(writer):
    """Close an asyncio stream on CPython and MicroPython without leaking it."""
    try:
        writer.close()
    except Exception:
        pass
    try:
        wait_closed = getattr(writer, 'wait_closed', None)
        if wait_closed is not None:
            await wait_closed()
    except Exception:
        pass


async def _line(reader, maximum):
    bounded = getattr(reader, 'read_bounded_line', None)
    if bounded:
        return await bounded(maximum)
    byte_reader = getattr(reader, 'read', None)
    if not byte_reader:
        line_reader = getattr(reader, 'readline', None)
        if not line_reader:
            raise ValueError('HTTP stream does not support bounded reads')
        value = await line_reader()
        if len(value) > int(maximum):
            raise ValueError('HTTP line exceeds the configured limit')
        return value
    value = bytearray()
    while len(value) <= int(maximum):
        character = await byte_reader(1)
        if not character:
            break
        value.extend(character)
        if character == b'\n':
            break
    if len(value) > int(maximum):
        raise ValueError('HTTP line exceeds the configured limit')
    return bytes(value)


async def _with_timeout(coroutine, timeout_s):
    wait_for = getattr(asyncio, 'wait_for', None)
    if wait_for:
        return await wait_for(coroutine, timeout_s)
    return await coroutine


async def read_request(reader, timeout_s=REQUEST_TIMEOUT_SECONDS):
    request_line = await _with_timeout(
        _line(reader, MAX_REQUEST_LINE_BYTES), timeout_s
    )
    if not request_line:
        return b'', {}
    headers = {}
    total = 0
    count = 0
    while True:
        line = await _with_timeout(
            _line(reader, MAX_HEADER_LINE_BYTES), timeout_s
        )
        if not line or line in (b'\r\n', b'\n'):
            break
        total += len(line)
        count += 1
        if total > MAX_HEADER_BYTES or count > MAX_HEADER_COUNT:
            raise ValueError('HTTP headers exceed the configured limit')
        try:
            text = line.decode().strip()
        except Exception:
            raise ValueError('HTTP header is not valid text')
        if ':' not in text:
            raise ValueError('HTTP header is malformed')
        name, value = text.split(':', 1)
        name = name.strip().lower()
        if not name or any(character in name for character in ' \t\r\n'):
            raise ValueError('HTTP header name is invalid')
        if name in headers and name in ('content-length', 'transfer-encoding', 'host'):
            raise ValueError('duplicate security-sensitive HTTP header')
        headers[name] = value.strip()
    if headers.get('transfer-encoding'):
        raise ValueError('chunked request bodies are not supported')
    return request_line, headers


async def read_exact_body(
    reader, length, maximum, timeout_s=BODY_TIMEOUT_SECONDS
):
    length = int(length)
    if length < 0 or length > int(maximum):
        raise ValueError('HTTP body exceeds the configured limit')

    async def receive():
        body = bytearray()
        while len(body) < length:
            chunk = await reader.read(min(1024, length - len(body)))
            if not chunk:
                raise ValueError('HTTP body ended early')
            body.extend(chunk)
        return bytes(body)

    return await _with_timeout(receive(), timeout_s)


def add_security_headers(headers=()):
    supplied = {str(name).lower() for name, _value in headers}
    defaults = tuple(
        (name, value) for name, value in SECURITY_HEADERS
        if name.lower() not in supplied
    )
    return defaults + tuple(headers)

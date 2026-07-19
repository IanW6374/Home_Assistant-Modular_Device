"""Optional HTTPS release-channel checks and signed bundle staging."""

try:
    import uasyncio as asyncio
except ImportError:
    import asyncio

try:
    import ujson as json
except ImportError:
    import json

try:
    import ussl as ssl
except ImportError:
    import ssl


STATE_PATH = '.release-update-state.json'


def _parse_https_url(url):
    url = str(url)
    if not url.startswith('https://'):
        raise ValueError('release URLs must use HTTPS')
    remainder = url[8:]
    host_port, separator, path = remainder.partition('/')
    host, colon, port = host_port.partition(':')
    if not host:
        raise ValueError('release URL has no host')
    return host, int(port) if colon else 443, '/' + path if separator else '/'


def _tls_context(ca_path):
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    if hasattr(context, 'verify_mode') and hasattr(ssl, 'CERT_REQUIRED'):
        context.verify_mode = ssl.CERT_REQUIRED
    try:
        context.load_verify_locations(cafile=ca_path)
    except TypeError:
        with open(ca_path, 'rb') as stream:
            context.load_verify_locations(cadata=stream.read())
    return context


async def _open_response(url, ca_path):
    host, port, path = _parse_https_url(url)
    context = _tls_context(ca_path)
    try:
        reader, writer = await asyncio.open_connection(
            host, port, ssl=context, server_hostname=host
        )
    except TypeError:
        reader, writer = await asyncio.open_connection(host, port, ssl=context)
    writer.write(
        ('GET ' + path + ' HTTP/1.1\r\nHost: ' + host +
         '\r\nUser-Agent: HAM-Device/1\r\nAccept: application/json,application/octet-stream\r\n'
         'Connection: close\r\n\r\n').encode()
    )
    await writer.drain()
    status_line = (await reader.readline()).decode().strip()
    parts = status_line.split()
    if len(parts) < 2 or parts[1] != '200':
        writer.close()
        raise OSError('release server returned ' + status_line)
    headers = {}
    while True:
        line = await reader.readline()
        if not line or line == b'\r\n':
            break
        text = line.decode().strip()
        if ':' in text:
            name, value = text.split(':', 1)
            headers[name.lower()] = value.strip()
    if headers.get('transfer-encoding', '').lower() == 'chunked':
        writer.close()
        raise ValueError('release server must provide Content-Length, not chunked encoding')
    length = int(headers.get('content-length', '0') or 0)
    if length <= 0:
        writer.close()
        raise ValueError('release response has no Content-Length')
    return reader, writer, length


async def check_release(manifest_url, channel, ca_path):
    separator = '&' if '?' in manifest_url else '?'
    url = manifest_url + separator + 'channel=' + str(channel)
    reader, writer, length = await _open_response(url, ca_path)
    try:
        if length > 16384:
            raise ValueError('release manifest exceeds 16384 bytes')
        payload = bytearray()
        while len(payload) < length:
            chunk = await reader.read(length - len(payload))
            if not chunk:
                raise ValueError('release manifest ended early')
            payload.extend(chunk)
        release = json.loads(payload.decode())
        if not isinstance(release, dict):
            raise ValueError('release manifest must be an object')
        if release.get('type') not in ('application', 'firmware'):
            raise ValueError('release type must be application or firmware')
        _parse_https_url(release.get('url', ''))
        return release
    finally:
        writer.close()


async def stage_release(
    release, ca_path, application_receiver, firmware_receiver,
    allow_protected=False, application_max_bytes=4194304,
    firmware_max_bytes=4194304, progress_callback=None
):
    reader, writer, length = await _open_response(release['url'], ca_path)
    try:
        if release['type'] == 'application':
            return await application_receiver(
                reader, length, allow_protected, application_max_bytes,
                progress_callback=progress_callback
            )
        return await firmware_receiver(
            reader, length, firmware_max_bytes,
            progress_callback=progress_callback
        )
    finally:
        writer.close()

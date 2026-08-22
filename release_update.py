"""Signed HTTPS release discovery and verified remote bundle staging."""

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

try:
    import uhashlib as hashlib
except ImportError:
    import hashlib

try:
    import ubinascii as binascii
except ImportError:
    import binascii

import update_security


MAX_DESCRIPTOR_BYTES = 16384
MAX_REDIRECTS = 4


def application_release_applicable(
    components, configured_modules, runtime_version, module_versions
):
    """Return whether signed component versions affect this device."""
    update_security.validate_components(components)
    if int(components.get('runtime', 0)) > int(runtime_version):
        return True
    offered = components.get('modules', {})
    for name in configured_modules or ():
        if int(offered.get(name, 0)) > int(module_versions.get(name, 0)):
            return True
    return False


def automatic_check_slot(schedule, check_time, weekday, current):
    """Return the local-date slot when an automatic release check is due."""
    schedule = str(schedule or 'disabled').lower()
    if schedule not in ('daily', 'weekly') or len(current) < 7:
        return ''
    try:
        hour_text, minute_text = str(check_time).split(':', 1)
        hour, minute = int(hour_text), int(minute_text)
        configured_weekday = int(weekday)
    except (TypeError, ValueError):
        return ''
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        return ''
    if current[3] != hour or current[4] != minute:
        return ''
    if schedule == 'weekly' and current[6] != configured_weekday:
        return ''
    return '{:04}{:02}{:02}'.format(current[0], current[1], current[2])


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


def _close(writer):
    try:
        writer.close()
    except Exception:
        pass


async def _read_exact(reader, size):
    result = bytearray()
    while len(result) < size:
        chunk = await reader.read(size - len(result))
        if not chunk:
            raise ValueError('release response ended early')
        result.extend(chunk)
    return bytes(result)


class _ChunkedReader:
    def __init__(self, reader):
        self.reader = reader
        self.remaining = 0
        self.finished = False

    async def read(self, size):
        if self.finished or size <= 0:
            return b''
        result = bytearray()
        while len(result) < size and not self.finished:
            if self.remaining == 0:
                line = await self.reader.readline()
                if not line:
                    raise ValueError('chunked release response ended early')
                token = line.decode().strip().split(';', 1)[0]
                try:
                    self.remaining = int(token, 16)
                except ValueError:
                    raise ValueError('release response has an invalid chunk size')
                if self.remaining == 0:
                    while True:
                        trailer = await self.reader.readline()
                        if not trailer or trailer == b'\r\n':
                            break
                    self.finished = True
                    break
            count = min(size - len(result), self.remaining)
            result.extend(await _read_exact(self.reader, count))
            self.remaining -= count
            if self.remaining == 0:
                if await _read_exact(self.reader, 2) != b'\r\n':
                    raise ValueError('release response chunk terminator is invalid')
        return bytes(result)


class _VerifiedReader:
    def __init__(self, reader, maximum):
        self.reader = reader
        self.maximum = int(maximum)
        self.count = 0
        self.hasher = hashlib.sha256()

    async def read(self, size):
        chunk = await self.reader.read(size)
        if chunk:
            self.count += len(chunk)
            if self.count > self.maximum:
                raise ValueError('release bundle exceeds its signed size')
            self.hasher.update(chunk)
        return chunk

    def hexdigest(self):
        return binascii.hexlify(self.hasher.digest()).decode()


async def _open_response(url, ca_path, redirects=MAX_REDIRECTS):
    host, port, path = _parse_https_url(url)
    context = _tls_context(ca_path)
    try:
        reader, writer = await asyncio.open_connection(
            host, port, ssl=context, server_hostname=host
        )
    except TypeError:
        reader, writer = await asyncio.open_connection(host, port, ssl=context)
    host_header = host if port == 443 else host + ':' + str(port)
    writer.write(
        ('GET ' + path + ' HTTP/1.1\r\nHost: ' + host_header +
         '\r\nUser-Agent: HAMD-Device/2\r\n'
         'Accept: application/json,application/octet-stream\r\n'
         'Connection: close\r\n\r\n').encode()
    )
    await writer.drain()
    status_line = (await reader.readline()).decode().strip()
    parts = status_line.split()
    if len(parts) < 2:
        _close(writer)
        raise OSError('release server returned an invalid status line')
    try:
        status = int(parts[1])
    except ValueError:
        _close(writer)
        raise OSError('release server returned an invalid status code')
    headers = {}
    while True:
        line = await reader.readline()
        if not line or line == b'\r\n':
            break
        text = line.decode().strip()
        if ':' in text:
            name, value = text.split(':', 1)
            headers[name.lower()] = value.strip()

    if status in (301, 302, 303, 307, 308):
        location = headers.get('location', '')
        _close(writer)
        if redirects <= 0:
            raise ValueError('release URL exceeded the redirect limit')
        _parse_https_url(location)
        return await _open_response(location, ca_path, redirects - 1)
    if status != 200:
        _close(writer)
        raise OSError('release server returned ' + status_line)

    chunked = 'chunked' in headers.get('transfer-encoding', '').lower()
    length = None
    if not chunked:
        try:
            length = int(headers.get('content-length', '0') or 0)
        except ValueError:
            length = 0
        if length <= 0:
            _close(writer)
            raise ValueError('release response has no valid length')
    return (_ChunkedReader(reader) if chunked else reader), writer, length


def _query_value(value):
    value = str(value)
    allowed = 'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-._~'
    if not value or any(character not in allowed for character in value):
        raise ValueError('release query value contains invalid characters')
    return value


def release_manifest_request_url(manifest_url, channel):
    """Return the exact channel URL used for a release check."""
    channel = _query_value(channel)
    if '{channel}' in manifest_url:
        return manifest_url.replace('{channel}', channel)
    separator = '&' if '?' in manifest_url else '?'
    return manifest_url + separator + 'channel=' + channel


def _release_manifest_request_url(manifest_url, channel):
    """Compatibility wrapper for integrations using the earlier private helper."""
    return release_manifest_request_url(manifest_url, channel)


async def _read_body(reader, length, maximum):
    payload = bytearray()
    if length is not None and length > maximum:
        raise ValueError('release descriptor exceeds ' + str(maximum) + ' bytes')
    while length is None or len(payload) < length:
        remaining = maximum + 1 - len(payload)
        if remaining <= 0:
            raise ValueError('release descriptor exceeds ' + str(maximum) + ' bytes')
        count = min(1024, remaining)
        if length is not None:
            count = min(count, length - len(payload))
        chunk = await reader.read(count)
        if not chunk:
            break
        payload.extend(chunk)
    if length is not None and len(payload) != length:
        raise ValueError('release descriptor ended early')
    return bytes(payload)


async def fetch_releases(manifest_url, channel, ca_path):
    url = release_manifest_request_url(manifest_url, channel)
    reader, writer, length = await _open_response(url, ca_path)
    try:
        payload = await _read_body(reader, length, MAX_DESCRIPTOR_BYTES)
        document = json.loads(payload.decode())
        return release_descriptors(document, channel)
    finally:
        _close(writer)


async def check_release(manifest_url, channel, ca_path):
    releases = await fetch_releases(manifest_url, channel, ca_path)
    try:
        import app_update
        import firmware_update
        import hardware_platform
        selected = select_release(
            releases,
            app_update.running_release_sequence(),
            firmware_update.running_release_sequence(),
            app_update.running_version(''),
            firmware_update.running_version(hardware_platform.runtime_version()),
        )
    except Exception:
        selected = None
    return selected or {}


def release_descriptors(document, channel=''):
    """Validate a channel index and return its independently signed releases."""
    update_security.validate_release_descriptor(
        document, channel, check_compatibility=False
    )
    fallback = dict(document)
    listed = fallback.pop('releases', None)
    if listed is None:
        _parse_https_url(fallback.get('url', ''))
        return (fallback,)
    if not isinstance(listed, list) or not 1 <= len(listed) <= 2:
        raise ValueError('release channel must contain one or two releases')
    releases = []
    types = set()
    for release in listed:
        if not isinstance(release, dict) or 'releases' in release:
            raise ValueError('release channel contains an invalid release')
        update_security.validate_release_descriptor(
            release, channel, check_compatibility=False
        )
        _parse_https_url(release.get('url', ''))
        release_type = release.get('type')
        if release_type in types:
            raise ValueError('release channel contains a duplicate release type')
        types.add(release_type)
        releases.append(release)
    if fallback not in releases:
        raise ValueError('release channel fallback is not in the signed release list')
    return tuple(releases)


def select_release(
    releases, application_sequence=0, firmware_sequence=0,
    application_version='', firmware_version=''
):
    """Choose the next component this device still needs, firmware first."""
    applicable = {}
    for release in releases:
        if not update_security.release_is_compatible(release):
            continue
        release_type = release.get('type')
        installed_sequence = (
            application_sequence
            if release_type == 'application' else firmware_sequence
        )
        installed_version = (
            application_version
            if release_type == 'application' else firmware_version
        )
        offered_sequence = int(release.get('release_sequence', 0))
        newer = (
            offered_sequence > int(installed_sequence)
            if int(installed_sequence) > 0 else
            str(release.get('version', '')) != str(installed_version)
        )
        if newer:
            applicable[release_type] = release
    return applicable.get('firmware') or applicable.get('application')


def _discard_staged(release_type):
    try:
        if release_type == 'application':
            import app_update
            app_update.discard_pending_update()
        else:
            import firmware_update
            firmware_update.discard_pending_update()
    except Exception:
        pass


async def stage_release(
    release, ca_path, application_receiver, firmware_receiver,
    allow_protected=False, application_max_bytes=4194304,
    firmware_max_bytes=4194304, progress_callback=None
):
    update_security.validate_release_descriptor(release, release.get('channel', ''))
    expected_size = int(release['size'])
    maximum = application_max_bytes if release['type'] == 'application' else firmware_max_bytes
    if expected_size > int(maximum):
        raise ValueError('release bundle exceeds the configured maximum size')
    reader, writer, response_length = await _open_response(release['url'], ca_path)
    verified_reader = _VerifiedReader(reader, expected_size)
    staged = False
    try:
        if response_length is not None and response_length != expected_size:
            raise ValueError('release response length does not match signed metadata')
        if release['type'] == 'application':
            if application_receiver is None:
                raise ValueError('application update receiver is unavailable')
            state = await application_receiver(
                verified_reader, expected_size, allow_protected,
                application_max_bytes, progress_callback=progress_callback
            )
        else:
            if firmware_receiver is None:
                raise ValueError('firmware update receiver is unavailable')
            state = await firmware_receiver(
                verified_reader, expected_size, firmware_max_bytes,
                progress_callback=progress_callback
            )
        staged = True
        if response_length is None and await verified_reader.read(1):
            raise ValueError('release response contains data beyond its signed size')
        if verified_reader.count != expected_size:
            raise ValueError('release response size does not match signed metadata')
        if verified_reader.hexdigest() != str(release['sha256']).lower():
            raise ValueError('release bundle SHA-256 does not match signed metadata')
        if int(state.get('release_sequence', 0)) != int(release['release_sequence']):
            raise ValueError('release descriptor and bundle sequences do not match')
        return state
    except Exception:
        if staged:
            _discard_staged(release.get('type'))
        raise
    finally:
        _close(writer)

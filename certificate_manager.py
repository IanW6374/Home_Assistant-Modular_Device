"""Small ACME client for automated portal-certificate enrollment and renewal.

TLS trust is bootstrapped with an explicitly uploaded CA root. The ACME
account key and portal private key are stored only on the flash-encrypted
filesystem. Secure-boot and update-signing keys are deliberately unrelated.
"""

try:
    import uasyncio as asyncio
except ImportError:
    import asyncio
try:
    import ujson as json
except ImportError:
    import json
try:
    import ubinascii as binascii
except ImportError:
    import binascii
try:
    import uhashlib as hashlib
except ImportError:
    import hashlib
try:
    import uos as os
except ImportError:
    import os
try:
    import ussl as ssl
except ImportError:
    import ssl
try:
    import usocket as socket
except ImportError:
    import socket
try:
    import network
except ImportError:
    network = None
import time

import update_security
from release_update import _ChunkedReader, _parse_https_url, _tls_context


ACCOUNT_KEY_PATH = 'certs/acme-account.key'
CERTIFICATE_PATH = 'certs/web.crt.der'
PRIVATE_KEY_PATH = 'certs/web.key.der'
STATE_PATH = 'certs/acme-state.json'
TRANSACTION_PATH = 'certs/.certificate-transaction.json'
MAX_RESPONSE_BYTES = 65536
REQUEST_TIMEOUT_SECONDS = 20
_http01_token = ''
_http01_authorization = ''


def configure_network_hostname(hostname):
    """Set the short DHCP hostname before the station interface connects."""
    label = str(hostname).strip().rstrip('.').split('.', 1)[0]
    if not label:
        raise ValueError('certificate hostname is empty')
    if network is None:
        return label
    setter = getattr(network, 'hostname', None)
    if setter:
        setter(label)
        return label
    wlan_class = network.WLAN
    interface = getattr(wlan_class, 'IF_STA', getattr(network, 'STA_IF', 0))
    wlan_class(interface).config(dhcp_hostname=label)
    return label


def _station_address():
    if network is None:
        return ''
    try:
        wlan_class = network.WLAN
        interface = getattr(wlan_class, 'IF_STA', getattr(network, 'STA_IF', 0))
        station = wlan_class(interface)
        if not station.isconnected():
            return ''
        return str(station.ifconfig()[0])
    except Exception:
        return ''


async def wait_for_http01_mdns(hostname, timeout_s=30):
    """Confirm the station is ready before the CA resolves the advertised name.

    ESP-IDF's mDNS responder advertises ``network.hostname()``, but its normal
    ``getaddrinfo`` resolver does not reliably resolve the device's own mDNS
    advertisement.  Requiring that self-lookup can therefore block even while
    other hosts resolve and reach the device correctly.
    """
    hostname = str(hostname).strip().rstrip('.')
    if not hostname.lower().endswith('.local'):
        raise ValueError(
            'mDNS portal hostname must end in .local; use ' +
            hostname.split('.', 1)[0] + '.local instead of a home.arpa name'
        )
    for _index in range(max(1, int(timeout_s))):
        station_address = _station_address()
        if station_address and station_address != '0.0.0.0':
            # Give the mDNS responder a scheduling turn after STA association.
            await asyncio.sleep(1)
            return station_address
        await asyncio.sleep(1)
    raise ValueError('ACME enrollment requires a connection to the home Wi-Fi')


def _b64url(value):
    encoded = binascii.b2a_base64(bytes(value)).decode().strip()
    return encoded.replace('+', '-').replace('/', '_').rstrip('=')


def _b64decode(value):
    value = str(value).replace('-', '+').replace('_', '/')
    value += '=' * ((4 - len(value) % 4) % 4)
    return binascii.a2b_base64(value)


_X509_NAME_LABELS = {
    '2.5.4.3': 'CN',
    '2.5.4.6': 'C',
    '2.5.4.7': 'L',
    '2.5.4.8': 'ST',
    '2.5.4.10': 'O',
    '2.5.4.11': 'OU',
    '1.2.840.113549.1.9.1': 'emailAddress',
}


def _asn1_item(payload, offset=0, limit=None):
    """Return one definite-length DER item without building an ASN.1 tree."""
    if not isinstance(payload, (bytes, bytearray)):
        payload = bytes(payload)
    limit = len(payload) if limit is None else int(limit)
    if offset < 0 or offset + 2 > limit:
        raise ValueError('certificate DER item is truncated')
    tag = payload[offset]
    first_length = payload[offset + 1]
    cursor = offset + 2
    if first_length & 0x80:
        count = first_length & 0x7f
        if count == 0 or count > 4 or cursor + count > limit:
            raise ValueError('certificate DER length is invalid')
        length = 0
        for value in payload[cursor:cursor + count]:
            length = (length << 8) | value
        cursor += count
    else:
        length = first_length
    end = cursor + length
    if end > limit:
        raise ValueError('certificate DER value is truncated')
    return tag, cursor, end, end


def _asn1_items(payload, start, end):
    cursor = start
    while cursor < end:
        tag, value_start, value_end, cursor = _asn1_item(payload, cursor, end)
        yield tag, value_start, value_end
    if cursor != end:
        raise ValueError('certificate DER container is invalid')


def _decode_oid(payload):
    payload = bytes(payload)
    if not payload:
        return ''
    first = payload[0]
    if first < 40:
        parts = [0, first]
    elif first < 80:
        parts = [1, first - 40]
    else:
        parts = [2, first - 80]
    value = 0
    for byte in payload[1:]:
        value = (value << 7) | (byte & 0x7f)
        if not byte & 0x80:
            parts.append(value)
            value = 0
    if value:
        raise ValueError('certificate OID is truncated')
    return '.'.join(str(part) for part in parts)


def _decode_x509_text(payload, tag):
    payload = bytes(payload)
    try:
        if tag == 0x1e:
            return payload.decode('utf-16-be')
        return payload.decode('utf-8')
    except Exception:
        try:
            return payload.decode('latin-1')
        except Exception:
            return binascii.hexlify(payload).decode()


def _decode_x509_name(payload, start, end):
    attributes = []
    for rdn_tag, rdn_start, rdn_end in _asn1_items(payload, start, end):
        if rdn_tag != 0x31:
            continue
        for attr_tag, attr_start, attr_end in _asn1_items(
            payload, rdn_start, rdn_end
        ):
            if attr_tag != 0x30:
                continue
            fields = list(_asn1_items(payload, attr_start, attr_end))
            if len(fields) < 2 or fields[0][0] != 0x06:
                continue
            oid = _decode_oid(payload[fields[0][1]:fields[0][2]])
            value_tag, value_start, value_end = fields[1]
            value = _decode_x509_text(payload[value_start:value_end], value_tag)
            attributes.append(_X509_NAME_LABELS.get(oid, oid) + '=' + value)
    return ', '.join(attributes) or 'Unknown'


def _decode_x509_time(payload, tag):
    text = _decode_x509_text(payload, tag).rstrip('Z')
    try:
        if tag == 0x17 and len(text) >= 12:
            year = int(text[:2])
            year += 2000 if year < 50 else 1900
            text = str(year) + text[2:]
        if len(text) >= 14:
            return (
                text[0:4] + '-' + text[4:6] + '-' + text[6:8] + ' ' +
                text[8:10] + ':' + text[10:12] + ':' + text[12:14] + ' UTC'
            )
    except Exception:
        pass
    return text or 'Unknown'


def decode_certificate(payload):
    """Decode the safe identity fields needed by the local certificate page."""
    payload = bytes(payload)
    outer_tag, outer_start, outer_end, outer_next = _asn1_item(payload)
    if outer_tag != 0x30 or outer_next != len(payload):
        raise ValueError('certificate is not a single DER sequence')
    certificate_fields = list(_asn1_items(payload, outer_start, outer_end))
    if not certificate_fields or certificate_fields[0][0] != 0x30:
        raise ValueError('certificate has no TBSCertificate sequence')
    _tag, tbs_start, tbs_end = certificate_fields[0]
    fields = list(_asn1_items(payload, tbs_start, tbs_end))
    cursor = 1 if fields and fields[0][0] == 0xa0 else 0
    if len(fields) < cursor + 6:
        raise ValueError('certificate identity fields are incomplete')
    serial = fields[cursor]
    issuer = fields[cursor + 2]
    validity = fields[cursor + 3]
    subject = fields[cursor + 4]
    if serial[0] != 0x02 or issuer[0] != 0x30 or validity[0] != 0x30 or subject[0] != 0x30:
        raise ValueError('certificate identity fields have invalid DER tags')
    validity_fields = list(_asn1_items(payload, validity[1], validity[2]))
    if len(validity_fields) != 2:
        raise ValueError('certificate validity period is invalid')
    serial_hex = binascii.hexlify(payload[serial[1]:serial[2]]).decode().upper()
    return {
        'subject': _decode_x509_name(payload, subject[1], subject[2]),
        'issuer': _decode_x509_name(payload, issuer[1], issuer[2]),
        'not_before': _decode_x509_time(
            payload[validity_fields[0][1]:validity_fields[0][2]], validity_fields[0][0]
        ),
        'not_after': _decode_x509_time(
            payload[validity_fields[1][1]:validity_fields[1][2]], validity_fields[1][0]
        ),
        'serial_number': serial_hex or 'Unknown',
    }


def certificate_details(path):
    """Return display-safe details for one installed DER certificate."""
    try:
        size = int(os.stat(path)[6])
        if size <= 0 or size > MAX_RESPONSE_BYTES:
            raise ValueError('certificate file size is invalid')
        with open(path, 'rb') as stream:
            payload = stream.read(MAX_RESPONSE_BYTES + 1)
        if len(payload) != size:
            raise ValueError('certificate file could not be read completely')
        details = decode_certificate(payload)
        details.update({'installed': True, 'size': size})
        return details
    except OSError:
        return {'installed': False}
    except Exception as exc:
        return {'installed': True, 'error': str(exc)}


def _json_bytes(value):
    return json.dumps(value, separators=(',', ':')).encode()


def _der_length(length):
    if length < 128:
        return bytes((length,))
    value = b''
    while length:
        value = bytes((length & 255,)) + value
        length >>= 8
    return bytes((0x80 | len(value),)) + value


def _der(tag, value):
    value = bytes(value)
    return bytes((tag,)) + _der_length(len(value)) + value


def _seq(*values):
    return _der(0x30, b''.join(values))


def _set(*values):
    return _der(0x31, b''.join(values))


def _integer(value):
    if isinstance(value, int):
        raw = b'\x00' if value == 0 else update_security._int_to_bytes(value).lstrip(b'\x00')
    else:
        raw = bytes(value).lstrip(b'\x00') or b'\x00'
    if raw[0] & 0x80:
        raw = b'\x00' + raw
    return _der(0x02, raw)


def _oid(value):
    parts = [int(part) for part in value.split('.')]
    encoded = bytearray((parts[0] * 40 + parts[1],))
    for part in parts[2:]:
        groups = [part & 0x7f]
        part >>= 7
        while part:
            groups.insert(0, 0x80 | (part & 0x7f))
            part >>= 7
        encoded.extend(groups)
    return _der(0x06, encoded)


def _new_private_key():
    while True:
        value = os.urandom(32)
        scalar = update_security._bytes_to_int(value)
        if 1 <= scalar < update_security._N:
            return value


def _public_key(private_key):
    return b'\x04' + update_security.public_key_bytes(private_key)


def _ec_private_key_der(private_key):
    return _seq(
        _integer(1), _der(0x04, private_key),
        _der(0xa0, _oid('1.2.840.10045.3.1.7')),
        _der(0xa1, _der(0x03, b'\x00' + _public_key(private_key)))
    )


def _signature_der(raw_signature):
    raw = bytes(raw_signature)
    return _seq(_integer(raw[:32]), _integer(raw[32:]))


def _csr(private_key, hostname):
    hostname = str(hostname).encode()
    if not hostname or len(hostname) > 253:
        raise ValueError('certificate hostname is invalid')
    subject = _seq(_set(_seq(_oid('2.5.4.3'), _der(0x0c, hostname))))
    public_info = _seq(
        _seq(_oid('1.2.840.10045.2.1'), _oid('1.2.840.10045.3.1.7')),
        _der(0x03, b'\x00' + _public_key(private_key))
    )
    general_names = _seq(_der(0x82, hostname))
    extensions = _seq(_seq(_oid('2.5.29.17'), _der(0x04, general_names)))
    attribute = _seq(_oid('1.2.840.113549.1.9.14'), _set(extensions))
    request_info = _seq(_integer(0), subject, public_info, _der(0xa0, attribute))
    raw = binascii.unhexlify(update_security.sign_message(request_info, private_key))
    return _seq(
        request_info, _seq(_oid('1.2.840.10045.4.3.2')),
        _der(0x03, b'\x00' + _signature_der(raw))
    )


def _name(hostname):
    return _seq(_set(_seq(_oid('2.5.4.3'), _der(0x0c, str(hostname).encode()))))


def _signature_algorithm():
    return _seq(_oid('1.2.840.10045.4.3.2'))


def _generalized_time(year, month, day, hour, minute, second):
    value = '{:04}{:02}{:02}{:02}{:02}{:02}Z'.format(
        year, month, day, hour, minute, second
    )
    return _der(0x18, value.encode())


def _self_signed_certificate(private_key, hostname, current_time=None):
    """Build a device-local HTTPS certificate for the selected mDNS hostname."""
    hostname = str(hostname).strip().lower().rstrip('.')
    if (
        not hostname.endswith('.local') or '.' in hostname[:-6] or
        any(character not in 'abcdefghijklmnopqrstuvwxyz0123456789-.' for character in hostname)
    ):
        raise ValueError('self-signed certificate hostname must be a single .local name')
    current = current_time or time.localtime()
    year = int(current[0])
    if year < 2024 or year > 2100:
        raise ValueError('current time is required to create the HTTPS certificate')
    subject = _name(hostname)
    public_info = _seq(
        _seq(_oid('1.2.840.10045.2.1'), _oid('1.2.840.10045.3.1.7')),
        _der(0x03, b'\x00' + _public_key(private_key))
    )
    extensions = _seq(
        _seq(_oid('2.5.29.19'), _der(0x01, b'\xff'), _der(0x04, _seq())),
        _seq(_oid('2.5.29.15'), _der(0x01, b'\xff'), _der(0x04, _der(0x03, b'\x07\x80'))),
        _seq(_oid('2.5.29.37'), _der(0x04, _seq(_oid('1.3.6.1.5.5.7.3.1')))),
        _seq(_oid('2.5.29.17'), _der(0x04, _seq(_der(0x82, hostname.encode())))),
    )
    tbs = _seq(
        _der(0xa0, _integer(2)),
        _integer(os.urandom(16)),
        _signature_algorithm(),
        subject,
        _seq(
            _generalized_time(year, 1, 1, 0, 0, 0),
            _generalized_time(year + 10, 12, 31, 23, 59, 59),
        ),
        subject,
        public_info,
        _der(0xa3, extensions),
    )
    raw_signature = binascii.unhexlify(
        update_security.sign_message(tbs, private_key)
    )
    return _seq(
        tbs, _signature_algorithm(),
        _der(0x03, b'\x00' + _signature_der(raw_signature))
    )


def _jwk(private_key):
    public = update_security.public_key_bytes(private_key)
    return {
        'crv': 'P-256', 'kty': 'EC',
        'x': _b64url(public[:32]), 'y': _b64url(public[32:]),
    }


def _thumbprint(private_key):
    jwk = _jwk(private_key)
    canonical = (
        '{"crv":"P-256","kty":"EC","x":"' + jwk['x'] +
        '","y":"' + jwk['y'] + '"}'
    ).encode()
    return _b64url(hashlib.sha256(canonical).digest())


async def _response_unbounded(url, method, ca_path, body=b'', content_type='', accept=''):
    host, port, path = _parse_https_url(url)
    context = _tls_context(ca_path)
    try:
        reader, writer = await asyncio.open_connection(
            host, port, ssl=context, server_hostname=host
        )
    except TypeError:
        reader, writer = await asyncio.open_connection(host, port, ssl=context)
    host_header = host if port == 443 else host + ':' + str(port)
    headers = (
        method + ' ' + path + ' HTTP/1.1\r\nHost: ' + host_header +
        '\r\nUser-Agent: HAMD-ACME/1\r\nConnection: close\r\n'
    )
    if content_type:
        headers += 'Content-Type: ' + content_type + '\r\n'
    if accept:
        headers += 'Accept: ' + accept + '\r\n'
    headers += 'Content-Length: ' + str(len(body)) + '\r\n\r\n'
    writer.write(headers.encode() + body)
    await writer.drain()
    status_line = (await reader.readline()).decode().strip()
    parts = status_line.split()
    if len(parts) < 2:
        writer.close()
        raise OSError('ACME server returned an invalid response')
    status = int(parts[1])
    response_headers = {}
    while True:
        line = await reader.readline()
        if not line or line == b'\r\n':
            break
        text = line.decode().strip()
        if ':' in text:
            name, value = text.split(':', 1)
            response_headers[name.lower()] = value.strip()
    payload = bytearray()
    if method != 'HEAD':
        source = reader
        length = int(response_headers.get('content-length', '0') or 0)
        if 'chunked' in response_headers.get('transfer-encoding', '').lower():
            source = _ChunkedReader(reader)
            length = None
        while length is None or len(payload) < length:
            size = min(1024, MAX_RESPONSE_BYTES + 1 - len(payload))
            if length is not None:
                size = min(size, length - len(payload))
            if size <= 0:
                break
            chunk = await source.read(size)
            if not chunk:
                break
            payload.extend(chunk)
        if len(payload) > MAX_RESPONSE_BYTES:
            writer.close()
            raise ValueError('ACME response is too large')
    writer.close()
    return status, response_headers, bytes(payload)


async def _response(url, method, ca_path, body=b'', content_type='', accept=''):
    """Perform one ACME HTTPS exchange without allowing setup to hang forever."""
    host, _port, _path = _parse_https_url(url)
    try:
        return await asyncio.wait_for(
            _response_unbounded(url, method, ca_path, body, content_type, accept),
            REQUEST_TIMEOUT_SECONDS
        )
    except asyncio.TimeoutError:
        raise ValueError(
            'ACME ' + str(method) + ' request to ' + str(host) + ' timed out after ' +
            str(REQUEST_TIMEOUT_SECONDS) + ' seconds'
        )


async def _json_request(url, method, ca_path, body=b''):
    status, headers, payload = await _response(url, method, ca_path, body)
    value = json.loads(payload.decode()) if payload else {}
    if status < 200 or status >= 300:
        raise ValueError(str(value.get('detail', 'ACME request failed: HTTP ' + str(status))))
    return headers, value


async def _signed(url, payload, account_key, ca_path, nonce, kid=''):
    protected = {'alg': 'ES256', 'nonce': nonce, 'url': url}
    if kid:
        protected['kid'] = kid
    else:
        protected['jwk'] = _jwk(account_key)
    protected64 = _b64url(_json_bytes(protected))
    payload64 = '' if payload is None else _b64url(_json_bytes(payload))
    signing_input = (protected64 + '.' + payload64).encode()
    signature = binascii.unhexlify(update_security.sign_message(signing_input, account_key))
    body = _json_bytes({
        'protected': protected64, 'payload': payload64,
        'signature': _b64url(signature),
    })
    status, headers, response = await _response(
        url, 'POST', ca_path, body, 'application/jose+json'
    )
    value = json.loads(response.decode()) if response else {}
    if status < 200 or status >= 300:
        raise ValueError(str(value.get('detail', 'ACME request failed: HTTP ' + str(status))))
    next_nonce = headers.get('replay-nonce', '')
    if not next_nonce:
        raise ValueError('ACME server response has no replay nonce')
    return headers, value, next_nonce


async def _poll(url, account_key, ca_path, nonce, kid, wanted, attempts=30):
    for _index in range(attempts):
        headers, value, nonce = await _signed(
            url, None, account_key, ca_path, nonce, kid
        )
        status = value.get('status')
        if status in wanted:
            return headers, value, nonce
        if status == 'invalid':
            error = value.get('error', {})
            if not error:
                for challenge in value.get('challenges', ()):
                    if challenge.get('error'):
                        error = challenge['error']
                        break
            detail = error.get('detail', '') if isinstance(error, dict) else str(error)
            raise ValueError(
                'ACME authorization or order became invalid' +
                (': ' + str(detail) if detail else '')
            )
        await asyncio.sleep(1)
    raise ValueError('ACME server did not complete the request in time')


def http01_response(path):
    expected = '/.well-known/acme-challenge/' + _http01_token
    return _http01_authorization if _http01_token and path == expected else None


async def _challenge_server():
    async def handle(reader, writer):
        try:
            line = (await reader.readline()).decode().strip().split()
            path = line[1] if len(line) >= 2 else ''
            value = http01_response(path)
            status = '200 OK' if value is not None else '404 Not Found'
            body = (value or 'Not found').encode()
            writer.write(
                ('HTTP/1.1 ' + status + '\r\nContent-Type: text/plain\r\nContent-Length: ' +
                 str(len(body)) + '\r\nConnection: close\r\n\r\n').encode() + body
            )
            await writer.drain()
        finally:
            writer.close()
    return await asyncio.start_server(handle, '0.0.0.0', 80, backlog=2)


def _first_pem_certificate(payload):
    text = payload.decode()
    begin = '-----BEGIN CERTIFICATE-----'
    end = '-----END CERTIFICATE-----'
    start = text.find(begin)
    finish = text.find(end, start + len(begin))
    if start < 0 or finish < 0:
        raise ValueError('ACME certificate response is not a PEM certificate chain')
    encoded = ''.join(text[start + len(begin):finish].split())
    return _b64decode(encoded)


def _replace(source, target):
    try:
        os.remove(target)
    except OSError:
        pass
    os.rename(source, target)


def _remove(path):
    try:
        os.remove(path)
        return True
    except OSError:
        return False


def _exists(path):
    try:
        return os.stat(path)[6] >= 0
    except OSError:
        return False


def _remove_tree(path):
    try:
        names = os.listdir(path)
    except OSError:
        if _exists(path) and not _remove(path):
            raise OSError('could not remove certificate file: ' + str(path))
        return
    for name in names:
        _remove_tree(str(path).rstrip('/') + '/' + str(name))
    try:
        os.rmdir(path)
    except OSError:
        if _exists(path):
            raise OSError('could not remove certificate directory: ' + str(path))


def clear_certificate_state():
    """Idempotently remove all user-installed certificate and ACME state."""
    _remove_tree('certs')
    return not _exists('certs')


def _certificate_path(path):
    value = str(path).replace('\\', '/')
    relative = value.lstrip('/')
    if not relative.startswith('certs/') or '..' in relative.split('/'):
        raise ValueError('certificate transaction path is invalid')
    return value


def _copy(source, target):
    temporary = target + '.copying'
    with open(source, 'rb') as input_stream:
        with open(temporary, 'wb') as output_stream:
            while True:
                chunk = input_stream.read(1024)
                if not chunk:
                    break
                output_stream.write(chunk)
    _replace(temporary, target)


def recover_certificate_transaction():
    """Restore the complete previous certificate generation after interruption."""
    try:
        with open(TRANSACTION_PATH, 'r') as stream:
            transaction = json.load(stream)
    except OSError:
        return False
    if not isinstance(transaction, dict) or transaction.get('version') != 1:
        raise RuntimeError('certificate transaction marker is invalid')
    entries = transaction.get('entries')
    if not isinstance(entries, list) or not 1 <= len(entries) <= 32:
        raise RuntimeError('certificate transaction entries are invalid')
    for entry in entries:
        if not isinstance(entry, dict):
            raise RuntimeError('certificate transaction entry is invalid')
        target = _certificate_path(entry.get('target', ''))
        backup = _certificate_path(entry.get('backup', ''))
        if entry.get('existed') is True:
            if not _exists(backup):
                raise RuntimeError('certificate rollback generation is missing')
            _copy(backup, target)
        else:
            _remove(target)
    _remove(TRANSACTION_PATH)
    for entry in entries:
        _remove(entry.get('backup', ''))
    return True


def commit_certificate_files(pairs, validator=None):
    """Atomically activate a certificate set with boot-time rollback support."""
    recover_certificate_transaction()
    entries = []
    prepared = []
    for source, target in pairs:
        source = _certificate_path(source)
        target = _certificate_path(target)
        if not _exists(source):
            raise ValueError('staged certificate file is missing: ' + source)
        backup = target + '.previous'
        _remove(backup)
        existed = _exists(target)
        if existed:
            _copy(target, backup)
        entries.append({
            'target': target, 'backup': backup, 'existed': existed,
        })
        prepared.append((source, target))
    _write(TRANSACTION_PATH, _json_bytes({'version': 1, 'entries': entries}))
    try:
        for source, target in prepared:
            _replace(source, target)
        if validator:
            validator()
    except Exception:
        recover_certificate_transaction()
        raise
    _remove(TRANSACTION_PATH)
    for entry in entries:
        _remove(entry['backup'])
    return True


def _write(path, value):
    temporary = path + '.tmp'
    with open(temporary, 'wb') as stream:
        stream.write(value)
    _replace(temporary, path)


def install_self_signed(hostname):
    """Install an atomic device-generated HTTPS identity as the local fallback."""
    for directory in ('certs', 'certs/trust'):
        try:
            os.mkdir(directory)
        except OSError:
            pass
    private_key = _new_private_key()
    key_der = _ec_private_key_der(private_key)
    certificate = _self_signed_certificate(private_key, hostname)
    _write(CERTIFICATE_PATH + '.new', certificate)
    _write(PRIVATE_KEY_PATH + '.new', key_der)
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(CERTIFICATE_PATH + '.new', PRIVATE_KEY_PATH + '.new')
    current = time.localtime()
    state = {
        'hostname': str(hostname).strip().lower().rstrip('.'),
        'not_before': '{:04}-01-01T00:00:00Z'.format(int(current[0])),
        'not_after': '{:04}-12-31T23:59:59Z'.format(int(current[0]) + 10),
        'issuer': 'self-signed',
    }
    _write(STATE_PATH + '.new', _json_bytes(state))
    commit_certificate_files((
        (CERTIFICATE_PATH + '.new', CERTIFICATE_PATH),
        (PRIVATE_KEY_PATH + '.new', PRIVATE_KEY_PATH),
        (STATE_PATH + '.new', STATE_PATH),
    ))
    return state


def _load_or_create_account_key():
    try:
        with open(ACCOUNT_KEY_PATH, 'rb') as stream:
            value = stream.read()
        if len(value) == 32:
            return value
    except OSError:
        pass
    value = _new_private_key()
    _write(ACCOUNT_KEY_PATH, value)
    return value


def _iso_epoch(value):
    value = str(value)
    if len(value) < 19:
        return 0
    try:
        parts = (
            int(value[0:4]), int(value[5:7]), int(value[8:10]),
            int(value[11:13]), int(value[14:16]), int(value[17:19]), 0, 0, -1
        )
        try:
            return int(time.mktime(parts))
        except TypeError:
            return int(time.mktime(parts[:8]))
    except Exception:
        return 0


def certificate_expiry_status(not_after, now=None, warning_days=30,
                              critical_days=7):
    """Return the lifecycle classification for an ISO certificate expiry."""
    current = int(time.time() if now is None else now)
    expiry = _iso_epoch(not_after)
    if current < 1577836800 or not expiry:
        return {'expiry_level': 'unknown', 'days_remaining': None}
    remaining = int((expiry - current) // 86400)
    if remaining < 0:
        level = 'expired'
    elif remaining <= int(critical_days):
        level = 'critical'
    elif remaining <= int(warning_days):
        level = 'warning'
    else:
        level = 'ok'
    return {'expiry_level': level, 'days_remaining': remaining}


def certificate_lifecycle(path, now=None, warning_days=30, critical_days=7):
    """Return decoded identity plus 30/7-day certificate expiry state."""
    details = certificate_details(path)
    if not details.get('installed') or details.get('error'):
        details['expiry_level'] = 'missing'
        details['days_remaining'] = None
        return details
    details.update(certificate_expiry_status(
        details.get('not_after', ''), now, warning_days, critical_days
    ))
    return details


def renewal_due(now=None):
    try:
        with open(STATE_PATH, 'r') as stream:
            state = json.load(stream)
    except Exception:
        return True
    start = _iso_epoch(state.get('not_before', ''))
    end = _iso_epoch(state.get('not_after', ''))
    current = int(time.time() if now is None else now)
    if not start or end <= start:
        return True
    return current >= start + ((end - start) * 2 // 3)


async def issue(directory_url, hostname, ca_path, shared_port_80=False, progress=None):
    """Obtain a new certificate through RFC 8555 ACME HTTP-01."""
    global _http01_token, _http01_authorization
    def report(message):
        if progress:
            progress(message)

    report('Checking the mDNS hostname on the home Wi-Fi')
    await wait_for_http01_mdns(hostname)
    report('Loading the ACME directory')
    account_key = _load_or_create_account_key()
    _headers, directory = await _json_request(directory_url, 'GET', ca_path)
    for field in ('newNonce', 'newAccount', 'newOrder'):
        if not str(directory.get(field, '')).startswith('https://'):
            raise ValueError('ACME directory has no valid ' + field + ' URL')
    report('Creating or loading the ACME account')
    _status, nonce_headers, _body = await _response(
        directory['newNonce'], 'HEAD', ca_path
    )
    nonce = nonce_headers.get('replay-nonce', '')
    if not nonce:
        raise ValueError('ACME server did not provide a nonce')
    account_headers, _account, nonce = await _signed(
        directory['newAccount'], {'termsOfServiceAgreed': True},
        account_key, ca_path, nonce
    )
    kid = account_headers.get('location', '')
    if not kid:
        raise ValueError('ACME server did not return an account URL')
    report('Creating the certificate order')
    order_headers, order, nonce = await _signed(
        directory['newOrder'], {'identifiers': [{'type': 'dns', 'value': hostname}]},
        account_key, ca_path, nonce, kid
    )
    order_url = order_headers.get('location', '')
    if not order_url:
        raise ValueError('ACME server did not return an order URL')
    authorization_urls = order.get('authorizations', ())
    if len(authorization_urls) != 1:
        raise ValueError('ACME order did not return one authorization')
    _headers, authorization, nonce = await _signed(
        authorization_urls[0], None, account_key, ca_path, nonce, kid
    )
    challenge = next(
        (item for item in authorization.get('challenges', ()) if item.get('type') == 'http-01'),
        None
    )
    if not challenge:
        raise ValueError('ACME server does not offer the HTTP-01 challenge')
    _http01_token = str(challenge.get('token', ''))
    _http01_authorization = _http01_token + '.' + _thumbprint(account_key)
    server = None
    try:
        if not shared_port_80:
            server = await _challenge_server()
        report('Waiting for the CA to verify the HTTP-01 challenge')
        _headers, _challenge, nonce = await _signed(
            challenge['url'], {}, account_key, ca_path, nonce, kid
        )
        _headers, _authorization, nonce = await _poll(
            authorization_urls[0], account_key, ca_path, nonce, kid, ('valid',)
        )
        _headers, order, nonce = await _poll(
            order_url, account_key, ca_path, nonce, kid, ('ready', 'valid')
        )
        portal_key = _new_private_key()
        if order.get('status') != 'valid':
            report('Finalizing the certificate order')
            _headers, order, nonce = await _signed(
                order['finalize'], {'csr': _b64url(_csr(portal_key, hostname))},
                account_key, ca_path, nonce, kid
            )
            if order.get('status') != 'valid':
                _headers, order, nonce = await _poll(
                    order_url, account_key, ca_path, nonce, kid, ('valid',)
                )
        certificate_url = order.get('certificate', '')
        if not certificate_url:
            raise ValueError('ACME order has no certificate URL')
        report('Downloading and validating the issued certificate')
        protected = {'alg': 'ES256', 'kid': kid, 'nonce': nonce, 'url': certificate_url}
        protected64 = _b64url(_json_bytes(protected))
        signing_input = (protected64 + '.').encode()
        signature = binascii.unhexlify(update_security.sign_message(signing_input, account_key))
        body = _json_bytes({
            'protected': protected64, 'payload': '', 'signature': _b64url(signature)
        })
        status, _cert_headers, pem = await _response(
            certificate_url, 'POST', ca_path, body,
            'application/jose+json', 'application/pem-certificate-chain'
        )
        if status < 200 or status >= 300:
            raise ValueError('ACME certificate download failed: HTTP ' + str(status))
        certificate = _first_pem_certificate(pem)
        key_der = _ec_private_key_der(portal_key)
        _write(CERTIFICATE_PATH + '.new', certificate)
        _write(PRIVATE_KEY_PATH + '.new', key_der)
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.load_cert_chain(CERTIFICATE_PATH + '.new', PRIVATE_KEY_PATH + '.new')
        state = {
            'hostname': hostname,
            'not_before': order.get('notBefore', ''),
            'not_after': order.get('notAfter', ''),
        }
        _write(STATE_PATH + '.new', _json_bytes(state))
        commit_certificate_files((
            (CERTIFICATE_PATH + '.new', CERTIFICATE_PATH),
            (PRIVATE_KEY_PATH + '.new', PRIVATE_KEY_PATH),
            (STATE_PATH + '.new', STATE_PATH),
        ))
        return state
    finally:
        _http01_token = ''
        _http01_authorization = ''
        if server:
            server.close()
            if hasattr(server, 'wait_closed'):
                await server.wait_closed()


async def renewal_monitor(config, ca_path, log_output, reset_device, interval_s=900):
    while True:
        if renewal_due():
            try:
                state = await issue(
                    config.get('directory_url', ''), config.get('hostname', ''), ca_path
                )
            except Exception as exc:
                log_output('Local', 'Certificate renewal', {'log': 'Failed - ' + str(exc)}, 'ERROR')
            else:
                log_output(
                    'Local', 'Certificate renewal',
                    {'log': 'Renewed until ' + str(state.get('not_after', ''))}, 'INFO'
                )
                await asyncio.sleep(2)
                reset_device()
                return
        await asyncio.sleep(interval_s)

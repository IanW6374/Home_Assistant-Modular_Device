"""X.509/DER and P-256 certificate codec primitives."""

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
import time
import update_security

MAX_RESPONSE_BYTES = 65536

_X509_NAME_LABELS = {
    '2.5.4.3': 'CN',
    '2.5.4.6': 'C',
    '2.5.4.7': 'L',
    '2.5.4.8': 'ST',
    '2.5.4.10': 'O',
    '2.5.4.11': 'OU',
    '1.2.840.113549.1.9.1': 'emailAddress',
}

def _b64url(value):
    encoded = binascii.b2a_base64(bytes(value)).decode().strip()
    return encoded.replace('+', '-').replace('/', '_').rstrip('=')

def _b64decode(value):
    value = str(value).replace('-', '+').replace('_', '/')
    value += '=' * ((4 - len(value) % 4) % 4)
    return binascii.a2b_base64(value)

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
    if b'-----BEGIN CERTIFICATE-----' in payload:
        payload = _first_pem_certificate(payload)
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
    """Return display-safe details for one installed DER or PEM-chain certificate."""
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

def _csr(private_key, hostname, server_auth=True, client_auth=False,
         include_san=True):
    hostname = str(hostname).encode()
    if not hostname or len(hostname) > 253:
        raise ValueError('certificate hostname is invalid')
    subject = _seq(_set(_seq(_oid('2.5.4.3'), _der(0x0c, hostname))))
    public_info = _seq(
        _seq(_oid('1.2.840.10045.2.1'), _oid('1.2.840.10045.3.1.7')),
        _der(0x03, b'\x00' + _public_key(private_key))
    )
    if not server_auth and not client_auth:
        raise ValueError('certificate request requires a key usage')
    extension_values = []
    usages = []
    if server_auth:
        usages.append(_oid('1.3.6.1.5.5.7.3.1'))
    if client_auth:
        usages.append(_oid('1.3.6.1.5.5.7.3.2'))
    extension_values.append(
        _seq(_oid('2.5.29.37'), _der(0x04, _seq(*usages)))
    )
    if include_san:
        general_names = _seq(_der(0x82, hostname))
        extension_values.append(
            _seq(_oid('2.5.29.17'), _der(0x04, general_names))
        )
    extensions = _seq(*extension_values)
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

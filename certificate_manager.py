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
import http_support

import update_security
from certificate_codec import (
    _b64url, _csr, _ec_private_key_der, _first_pem_certificate, _iso_epoch,
    _der_length, _json_bytes, _jwk, _new_private_key, _self_signed_certificate,
    _thumbprint, certificate_details, decode_certificate,
)
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
    raise ValueError('Private CA ACME enrollment requires a connection to the home Wi-Fi')

async def _response_unbounded(url, method, ca_path, body=b'', content_type='', accept='',
                              extra_headers=(), tls_context=None):
    host, port, path = _parse_https_url(url)
    context = _tls_context(ca_path) if tls_context is None else tls_context
    try:
        reader, writer = await asyncio.open_connection(
            host, port, ssl=context, server_hostname=host
        )
    except TypeError:
        reader, writer = await asyncio.open_connection(host, port, ssl=context)
    host_header = host if port == 443 else host + ':' + str(port)
    headers = (
        method + ' ' + path + ' HTTP/1.1\r\nHost: ' + host_header +
        '\r\nUser-Agent: IoTMD-ACME/1\r\nConnection: close\r\n'
    )
    if content_type:
        headers += 'Content-Type: ' + content_type + '\r\n'
    if accept:
        headers += 'Accept: ' + accept + '\r\n'
    for name, value in extra_headers:
        name = str(name)
        value = str(value)
        if '\r' in name or '\n' in name or ':' in name or '\r' in value or '\n' in value:
            raise ValueError('HTTPS request header is invalid')
        headers += name + ': ' + value + '\r\n'
    headers += 'Content-Length: ' + str(len(body)) + '\r\n\r\n'
    writer.write(headers.encode() + body)
    await writer.drain()
    status_line = (await reader.readline()).decode().strip()
    parts = status_line.split()
    if len(parts) < 2:
        await http_support.close_writer(writer)
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
            await http_support.close_writer(writer)
            raise ValueError('ACME response is too large')
    await http_support.close_writer(writer)
    return status, response_headers, bytes(payload)


async def _response(url, method, ca_path, body=b'', content_type='', accept='',
                    extra_headers=(), tls_context=None):
    """Perform one ACME HTTPS exchange without allowing setup to hang forever."""
    host, _port, _path = _parse_https_url(url)
    try:
        return await asyncio.wait_for(
            _response_unbounded(
                url, method, ca_path, body, content_type, accept, extra_headers,
                tls_context
            ),
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
            await http_support.close_writer(writer)
    return await asyncio.start_server(handle, '0.0.0.0', 80, backlog=2)

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


def ensure_server_identity(cert_path, key_path, fallback_cert, fallback_key, marker):
    """Copy a legacy server pair once, then keep both identities independent."""
    installed = (_exists(cert_path), _exists(key_path))
    if all(installed):
        return False
    if any(installed):
        raise ValueError('server certificate identity is incomplete')
    if not all((_exists(fallback_cert), _exists(fallback_key))):
        raise ValueError('server certificate identity is not installed')
    staged_cert = cert_path + '.migration'
    staged_key = key_path + '.migration'
    _copy(fallback_cert, staged_cert)
    _copy(fallback_key, staged_key)
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(staged_cert, staged_key)
    commit_certificate_files(((staged_cert, cert_path), (staged_key, key_path)))
    with open(marker, 'w') as stream:
        stream.write('replace-with-private-ca-identity\n')
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


async def self_signed_renewal_monitor(
    config, log_output, reset_device, interval_s=900
):
    """Regenerate the managed local fallback after two-thirds of its lifetime."""
    while True:
        if renewal_due():
            try:
                state = install_self_signed(config.get('hostname', ''))
            except Exception as exc:
                log_output(
                    'Local', 'Self-signed device certificate renewal',
                    {'log': 'Failed - ' + str(exc)}, 'ERROR'
                )
            else:
                log_output(
                    'Local', 'Self-signed device certificate renewal',
                    {'log': 'Renewed until ' + str(state.get('not_after', ''))},
                    'INFO'
                )
                await asyncio.sleep(2)
                reset_device()
                return
        await asyncio.sleep(interval_s)

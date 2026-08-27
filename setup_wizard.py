"""First-boot AP wizard for credentials and signed application selection."""

try:
    import uasyncio as asyncio
except ImportError:
    import asyncio
try:
    import network
except ImportError:
    network = None
try:
    import ujson as json
except ImportError:
    import json
try:
    import machine
except ImportError:
    machine = None
import app_update
import credential_store
import certificate_manager
import factory_config
import release_update
import wifi_recovery
import portal_ui
import http_support
import iot_ca_enrollment
from setup_wizard_views import (
    SELF_SIGNED_READY_MESSAGE, SETUP_ASSET_VERSION,
    _certificate_complete_page, _certificate_page, _certificate_resume_page,
    _enrollment_page, _handover_page, _page, _portal_handoff_page, _portal_url,
    _upload_page,
)
from setup_workflow import (
    CERTIFICATE_PATHS, DEFAULT_ACME_DIRECTORY_URL,
    _configure_device, _connect_station, _download_application, _form_values,
    _enroll_acme_certificate,
    _file_exists, _preloaded_application_available,
    _install_manual_certificates,
    _prepare_available_application, _prepare_certificate_selection,
    _prepare_setup_application, _set_rtc_from_browser_time, _setup_error_fields,
    _validate_certificate_files, _validate_certificate_selection,
    _validate_certificates, _write_certificate,
)
try:
    import uos as os
except ImportError:
    import os
try:
    import ussl as ssl
except ImportError:
    import ssl
SETUP_PORT = 80
MAX_FORM_BYTES = 8192
MAX_CERTIFICATE_BYTES = 16384
MAX_CERTIFICATE_FORM_BYTES = MAX_FORM_BYTES + (MAX_CERTIFICATE_BYTES * 5)

def _parse_request_line(line):
    parts = str(line).split()
    if len(parts) != 3 or not parts[2].startswith('HTTP/'):
        return '', ''
    return parts[0], parts[1].split('?', 1)[0]
async def _read_body(reader, length, maximum):
    return await http_support.read_exact_body(reader, length, maximum)

def _multipart_form(body, content_type):
    boundary = ''
    for item in str(content_type).split(';')[1:]:
        name, separator, value = item.strip().partition('=')
        if separator and name.lower() == 'boundary':
            boundary = value.strip().strip('"')
            break
    if not boundary or len(boundary) > 70 or '\r' in boundary or '\n' in boundary:
        raise ValueError('multipart form boundary is invalid')
    try:
        delimiter = b'--' + boundary.encode('ascii')
    except Exception:
        raise ValueError('multipart form boundary is invalid')
    values = {}
    for section in bytes(body).split(delimiter)[1:]:
        if section.startswith(b'--'):
            break
        if section.startswith(b'\r\n'):
            section = section[2:]
        header_end = section.find(b'\r\n\r\n')
        if header_end < 0:
            continue
        raw_headers = section[:header_end].decode('utf-8', 'replace')
        payload = section[header_end + 4:]
        if payload.endswith(b'\r\n'):
            payload = payload[:-2]
        field_name = ''
        for header in raw_headers.split('\r\n'):
            if header.lower().startswith('content-disposition:'):
                for parameter in header.split(';')[1:]:
                    name, separator, value = parameter.strip().partition('=')
                    if separator and name.lower() == 'name':
                        field_name = value.strip().strip('"')
        if field_name:
            values[field_name] = payload
    return values

async def serve(ap_name, ap_password, reset_device, port=SETUP_PORT):
    """Serve first-boot setup until a signed application is ready."""
    if network is None:
        raise RuntimeError('first-boot Wi-Fi setup is unavailable')
    wlan_class = network.WLAN
    station_interface = getattr(wlan_class, 'IF_STA', getattr(network, 'STA_IF', 0))
    station = wlan_class(station_interface)
    try:
        station.disconnect()
    except Exception:
        pass
    station.active(False)
    access_point = wifi_recovery._activate_access_point(ap_name, ap_password)
    wifi_recovery.schedule_wifi_scan()
    session = wifi_recovery._session_id()
    enrollment = {'status': 'idle', 'message': '', 'mode': ''}
    upload_progress = {'phase': 'idle', 'percent': 0}
    enrollment_task = None
    async def after_ui_ready(operation):
        await asyncio.sleep(2)
        return await operation
    async def send(writer, status, body, content_type='text/html; charset=utf-8', headers=()):
        payload = body.encode() if isinstance(body, str) else body
        cache_control = (
            () if any(name.lower() == 'cache-control' for name, _value in headers)
            else (('Cache-Control', 'no-store'),)
        )
        response_headers = http_support.add_security_headers((
            ('Content-Type', content_type), ('Content-Length', str(len(payload))),
        ) + cache_control + (
            ('Connection', 'close'),
        ) + tuple(headers))
        writer.write(('HTTP/1.1 ' + status + '\r\n' + ''.join(
            name + ': ' + value + '\r\n' for name, value in response_headers
        ) + '\r\n').encode() + payload)
        await writer.drain()
    async def handle(reader, writer):
        nonlocal enrollment_task
        reboot = False
        handover_config = None
        try:
            request_line, headers = await http_support.read_request(reader)
            request_line = request_line.decode().strip()
            method, path = _parse_request_line(request_line)
            authenticated = wifi_recovery._cookies(headers).get('iotmd_setup') == session
            challenge_response = certificate_manager.http01_response(path)
            if method == 'GET' and path == '/assets/portal.css':
                await send(
                    writer, '200 OK', portal_ui.PORTAL_CSS,
                    'text/css; charset=utf-8'
                )
            elif method == 'GET' and path == '/assets/portal.js':
                await send(
                    writer, '200 OK', portal_ui.PORTAL_JS,
                    'application/javascript; charset=utf-8'
                )
            elif method == 'GET' and challenge_response is not None:
                await send(writer, '200 OK', challenge_response, 'text/plain')
            elif method == 'GET' and path == '/':
                await send(writer, '200 OK', _page(session), headers=(
                    ('Set-Cookie', 'iotmd_setup=' + session + '; Path=/; HttpOnly; SameSite=Strict'),
                ))
            elif method == 'GET' and path == '/resume/' + session:
                config = credential_store.load()
                await send(writer, '200 OK', _certificate_resume_page(
                    session, config
                ), headers=(
                    ('Set-Cookie', 'iotmd_setup=' + session + '; Path=/; HttpOnly; SameSite=Strict'),
                ))
            elif not authenticated:
                await send(writer, '401 Unauthorized', 'Reconnect to the setup page.', 'text/plain')
            elif method == 'GET' and path == '/wifi-networks':
                await send(
                    writer, '200 OK', json.dumps(wifi_recovery.cached_wifi_networks()),
                    'application/json'
                )
            elif method == 'GET' and path == '/upload-progress':
                await send(
                    writer, '200 OK', json.dumps(upload_progress),
                    'application/json'
                )
            elif method == 'GET' and path == '/upload':
                config = credential_store.load()
                await send(writer, '200 OK', _upload_page(session))
            elif method == 'POST' and path == '/configure':
                length = int(headers.get('content-length', '0') or 0)
                if length <= 0 or length > MAX_FORM_BYTES:
                    raise ValueError('setup form size is invalid')
                body = await _read_body(reader, length, MAX_FORM_BYTES)
                params = wifi_recovery._form(body.decode())
                if params.get('csrf') != session:
                    await send(writer, '403 Forbidden', 'Invalid CSRF token', 'text/plain')
                    return
                try:
                    config = _configure_device(params)
                    hostname = config['certificate']['hostname']
                    await _connect_station(
                        config['wifi']['ssid'], config['wifi']['password'],
                        hostname=hostname, wifi=config['wifi']
                    )
                except Exception as exc:
                    await send(
                        writer, '400 Bad Request',
                        _page(
                            session, 'Setup failed: ' + str(exc),
                            _setup_error_fields(exc)
                        )
                    )
                    return
                await send(writer, '200 OK', _handover_page(hostname, session))
                handover_config = config
            elif method == 'GET' and path == '/certificates':
                config = credential_store.load()
                await send(
                    writer, '200 OK',
                    _certificate_resume_page(session, config)
                )
            elif method == 'GET' and path == '/enrollment-status':
                config = credential_store.load()
                if enrollment['status'] == 'running':
                    await send(writer, '200 OK', _enrollment_page(enrollment['message']))
                elif enrollment['status'] == 'complete':
                    await send(writer, '200 OK', _certificate_complete_page(
                        session, enrollment['message'], enrollment['mode']
                    ))
                elif enrollment['status'] == 'error':
                    await send(writer, '400 Bad Request', _certificate_page(
                        session, config['certificate']['hostname'], enrollment['message'],
                        config['certificate']['mode'] == 'self_signed', True
                    ))
                else:
                    await send(writer, '200 OK', _certificate_resume_page(session, config))
            elif method == 'GET' and path == '/enrollment-state':
                await send(
                    writer, '200 OK', json.dumps({
                        'status': enrollment['status'],
                        'message': enrollment['message'],
                        'mode': enrollment['mode'],
                    }), 'application/json'
                )
            elif method == 'POST' and path == '/certificate':
                if headers.get('x-csrf-token', '') != session:
                    await send(writer, '403 Forbidden', 'Invalid CSRF token', 'text/plain')
                    return
                length = int(headers.get('content-length', '0') or 0)
                payload = await _read_body(reader, length, MAX_CERTIFICATE_BYTES)
                _write_certificate(headers.get('x-certificate-kind', ''), payload)
                await send(writer, '200 OK', 'Stored and encrypted at rest', 'text/plain')
            elif method == 'POST' and path == '/enroll-certificate':
                if enrollment['status'] == 'running':
                    await send(writer, '202 Accepted', _enrollment_page(enrollment['message']))
                    return
                length = int(headers.get('content-length', '0') or 0)
                body = await asyncio.wait_for(
                    _read_body(reader, length, MAX_CERTIFICATE_FORM_BYTES), 20
                )
                parts = _multipart_form(body, headers.get('content-type', ''))
                if parts.get('csrf', b'').decode() != session:
                    await send(writer, '403 Forbidden', 'Invalid CSRF token', 'text/plain')
                    return
                directory_url = (
                    parts.get('directory_url', b'').decode().strip() or
                    DEFAULT_ACME_DIRECTORY_URL
                )
                hostname = parts.get('hostname', b'').decode().strip()
                config = credential_store.load()
                if hostname != config['certificate']['hostname']:
                    raise ValueError('portal mDNS hostname changed during setup')
                _write_certificate('trust-ca', parts.get('trust_ca', b''), '.acme')
                enrollment['status'] = 'running'
                enrollment['message'] = 'Starting ACME enrollment'
                enrollment['mode'] = 'acme'
                await send(writer, '202 Accepted', _enrollment_page(enrollment['message']))
                enrollment_task = asyncio.create_task(after_ui_ready(
                    _enroll_acme_certificate(
                        directory_url, hostname, config, enrollment
                    )
                ))
            elif method == 'POST' and path == '/iot-ca-enrollment':
                if enrollment['status'] == 'running':
                    await send(writer, '202 Accepted', _enrollment_page(enrollment['message']))
                    return
                length = int(headers.get('content-length', '0') or 0)
                body = await _read_body(reader, length, MAX_CERTIFICATE_FORM_BYTES)
                parts = _multipart_form(body, headers.get('content-type', ''))
                if parts.get('csrf', b'').decode() != session:
                    await send(writer, '403 Forbidden', 'Invalid CSRF token', 'text/plain')
                    return
                package = parts.get('enrollment_file', b'')
                if not package or len(package) > iot_ca_enrollment.MAX_PACKAGE_BYTES:
                    raise ValueError('IoT CA enrollment file size is invalid')
                config = credential_store.load()
                enrollment['status'] = 'running'
                enrollment['message'] = 'Starting IoT CA enrollment'
                enrollment['mode'] = 'iot_ca'
                await send(writer, '202 Accepted', _enrollment_page(enrollment['message']))
                enrollment_task = asyncio.create_task(after_ui_ready(
                    iot_ca_enrollment.install(
                        package, config, CERTIFICATE_PATHS, _connect_station,
                        _validate_certificates, enrollment
                    )
                ))
            elif method == 'POST' and path == '/iot-ca-auto-enrollment':
                if enrollment['status'] == 'running':
                    await send(writer, '202 Accepted', _enrollment_page(enrollment['message']))
                    return
                length = int(headers.get('content-length', '0') or 0)
                body = await _read_body(reader, length, MAX_FORM_BYTES)
                params = wifi_recovery._form(body.decode())
                if params.get('csrf') != session:
                    await send(writer, '403 Forbidden', 'Invalid CSRF token', 'text/plain')
                    return
                server = iot_ca_enrollment._auto_server(params.get('ca_server', ''))
                port = iot_ca_enrollment._auto_port(params.get('ca_port', ''))
                config = credential_store.load()
                enrollment.update({
                    'status': 'running', 'mode': 'iot_ca',
                    'message': 'Requesting automatic IoT CA enrollment',
                })
                await send(writer, '202 Accepted', _enrollment_page(enrollment['message']))
                enrollment_task = asyncio.create_task(after_ui_ready(
                    iot_ca_enrollment.automatic_install(
                        server, config, CERTIFICATE_PATHS, _connect_station,
                        _validate_certificates, enrollment, port
                    )
                ))
            elif method == 'POST' and path == '/manual-certificates':
                length = int(headers.get('content-length', '0') or 0)
                body = await _read_body(reader, length, MAX_CERTIFICATE_FORM_BYTES)
                parts = _multipart_form(body, headers.get('content-type', ''))
                if parts.get('csrf', b'').decode() != session:
                    await send(writer, '403 Forbidden', 'Invalid CSRF token', 'text/plain')
                    return
                config = _install_manual_certificates(parts)
                hostname = config['certificate']['hostname']
                await send(writer, '200 OK', _certificate_complete_page(
                    session, 'Certificates validated.', 'manual'
                ))
            elif method == 'POST' and path == '/install':
                length = int(headers.get('content-length', '0') or 0)
                body = await _read_body(reader, length, MAX_FORM_BYTES)
                params = wifi_recovery._form(body.decode())
                if params.get('csrf') != session:
                    await send(writer, '403 Forbidden', 'Invalid CSRF token', 'text/plain')
                    return
                config = credential_store.load()
                _prepare_certificate_selection(config, params.get('certificate_mode', ''))
                state = _prepare_available_application()
                if state is None and config['release']['install_mode'] == 'download':
                    state = await _download_application(config)
                if state is None:
                    await send(writer, '303 See Other', 'Upload required', 'text/plain', (
                        ('Location', '/upload'),
                    ))
                else:
                    credential_store.mark_provisioned(config)
                    credential_store.erase_bootstrap_key()
                    await send(
                        writer, '200 OK',
                        _portal_handoff_page(
                            config,
                            'Verified signed application ' +
                            str(state.get('version', '') or 'factory image') + '. Restarting.'
                        )
                    )
                    reboot = True
            elif method == 'POST' and path == '/upload':
                if headers.get('x-csrf-token', '') != session:
                    await send(writer, '403 Forbidden', 'Invalid CSRF token', 'text/plain')
                    return
                config = credential_store.load()
                _validate_certificate_files(config['certificate']['mode'])
                length = int(headers.get('content-length', '0') or 0)
                async def report_upload_progress(phase, completed=0, total=0):
                    total = int(total or 0)
                    upload_progress['phase'] = str(phase)
                    upload_progress['percent'] = (
                        max(0, min(100, int(int(completed or 0) * 100 / total)))
                        if total else 0
                    )
                state = await app_update.receive_bundle(
                    reader, length, False, app_update.DEFAULT_MAX_BUNDLE_BYTES,
                    progress_callback=report_upload_progress
                )
                upload_progress.update({'phase': 'complete', 'percent': 100})
                state = _prepare_setup_application(state)
                credential_store.mark_provisioned(config)
                credential_store.erase_bootstrap_key()
                portal_url = _portal_url(config)
                await send(
                    writer, '200 OK',
                    'Verified ' + str(state.get('version', '')) + '. Rebooting.',
                    'text/plain', (('X-Portal-URL', portal_url),)
                )
                reboot = True
            else:
                await send(writer, '404 Not Found', 'Not found', 'text/plain')
        except Exception as exc:
            try:
                await send(writer, '400 Bad Request', 'Setup failed: ' + str(exc), 'text/plain')
            except Exception:
                pass
        finally:
            try:
                writer.close()
            except Exception:
                pass
        if reboot:
            await asyncio.sleep(1)
            reset_device()
        elif handover_config is not None:
            await asyncio.sleep(5)
            access_point.active(False)
    server = await asyncio.start_server(handle, '0.0.0.0', int(port), backlog=2)
    while True:
        await asyncio.sleep(60)
    return {'server': server, 'access_point': access_point}

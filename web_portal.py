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
    import os
except ImportError:
    os = None

try:
    import ubinascii as binascii
except ImportError:
    import binascii

try:
    import time
except ImportError:
    time = None

import web_portal_ui as portal_ui
import http_support
import timezone_rules
import portal_auth
from portal_view_models import overview_metrics, update_check_summary
from portal_sessions import PortalSessions
from device_modules.base import module_diagnostics_need_attention
from portal_http import *
from portal_settings_views import *
from portal_live_views import *
from portal_presenters import *

async def start_web_portal(portal):
    """Start the portal transport from one explicit application contract."""
    if asyncio is None:
        return None

    settings = portal.settings
    log_getter = portal.require('logs.get')
    audit_log_getter = portal.get('audit.get') or (lambda: [])
    loglevel_getter = portal.require('logs.level.get')
    loglevel_setter = portal.require('logs.level.set')
    log_output = portal.require('events.log')
    status_getter = portal.get('status.get')
    module_getter = portal.get('modules.list')
    action_handler = portal.get('actions.apply')
    config_backup_getter = portal.get('configuration.backup')
    config_import_preview_handler = portal.get('configuration.preview')
    config_import_apply_handler = portal.get('configuration.apply')
    settings_getter = portal.get('settings.get')
    settings_setter = portal.get('settings.apply')
    module_settings_getter = portal.get('module_configuration.get')
    module_settings_setter = portal.get('module_configuration.apply')
    certificate_upload_handler = portal.get('certificates.upload')
    certificate_validate_handler = portal.get('certificates.apply')
    update_preferences_setter = portal.get('updates.preferences.apply')
    task_status_getter = portal.get('tasks.status')
    certificate_info_getter = portal.get('certificates.get')
    network_trial_confirmer = portal.get('network.confirm')
    factory_reset_handler = portal.get('factory_reset.request')
    secure_config_backup_getter = portal.get('configuration.secure.backup')
    secure_config_import_preview_handler = portal.get('configuration.secure.preview')
    secure_config_import_apply_handler = portal.get('configuration.secure.apply')
    log_buffer_lines_setter = portal.get('logs.limit.set')
    wifi_scan_getter = portal.get('network.scan')
    portal_user_getter = portal.get('users.list')
    portal_user_add = portal.get('users.add')
    portal_user_update = portal.get('users.update')
    portal_user_remove = portal.get('users.remove')
    resumable_begin = portal.get('updates.upload.begin')
    resumable_status = portal.get('updates.upload.status')
    resumable_append = portal.get('updates.upload.append')
    resumable_complete = portal.get('updates.upload.complete')
    restart_status_getter = portal.get('restart.status')
    restart_request_handler = portal.get('restart.request')
    shutdown_request_handler = portal.get('shutdown.request')

    username = settings.get('username', 'admin') or 'admin'
    password_verifier = settings.get('password_verifier', '')
    authenticator = settings.get('authenticator')
    password_change_required = bool(settings.get('password_change_required', False))
    password_setter = settings.get('password_setter')
    user_password_setter = settings.get('user_password_setter')
    if not isinstance(username, str):
        raise ValueError('web portal username must be text')
    import credential_security
    if authenticator is None:
        try:
            credential_security.parse_password_verifier(password_verifier)
        except ValueError as exc:
            raise ValueError('web portal password verifier is invalid: ' + str(exc))
    levels = settings.get('levels', ('ERROR', 'INFO', 'DEBUG'))
    log_refresh_ms = settings.get('log_refresh_ms', 5000)
    value_refresh_ms = settings.get('value_refresh_ms', 0)
    upload_progress = {'phase': 'idle', 'percent': 0}
    upload_progress_by_id = {}
    session_timeout_ms = int(settings.get('session_timeout_s', 3600)) * 1000
    sessions = PortalSessions(
        new_session_id, monotonic_ms, session_timeout_ms,
        int(settings.get('maximum_sessions', 8))
    )
    login_failures = 0
    cached_page = {'level': None, 'body': None}
    status_snapshot = TimedSnapshot(status_getter, 1000, {})
    module_snapshot = TimedSnapshot(module_getter, 1000, [])
    secure_cookie = settings.get('https', False)
    login_url = settings.get('login_url', '/login')

    async def send_raw_response(
        writer, status, body, content_type='text/html; charset=utf-8',
        extra_headers=None, keep_alive=False
    ):
        await write_buffered_response(
            writer, status, body, content_type, extra_headers, keep_alive
        )

    async def send_log_download(writer, lines, filename):
        await send_raw_response(
            writer, '200 OK', render_log_text(lines), 'text/plain; charset=utf-8',
            (('Content-Disposition', 'attachment; filename="' + filename + '"'),)
        )

    async def send_redirect(writer, location, extra_headers=None):
        headers = [('Location', location)]
        if extra_headers:
            headers.extend(extra_headers)
        await send_raw_response(
            writer,
            '303 See Other',
            'Redirecting',
            'text/plain',
            tuple(headers)
        )

    async def handle_client(reader, writer, remaining_requests=32):
        nonlocal login_failures
        nonlocal password_verifier, password_change_required
        reader = http_support.buffered(reader)
        path = ''
        upload_state = ''
        progress_response_started = False
        progress_percent = -1
        progress_phase = ''
        progress_id = ''
        progress_record = upload_progress
        peer_address = request_peer_address(reader, writer)
        session_role = ''
        session_username = ''
        request_keep_alive = False
        response_keep_alive = False
        handed_off = False

        async def send_response(writer, status, body,
                                content_type='text/html; charset=utf-8',
                                extra_headers=None):
            nonlocal response_keep_alive
            if content_type.startswith('text/html') and session_username:
                body = portal_ui.personalise_page(
                    body, session_username, session_role
                )
            response_keep_alive = request_keep_alive
            await send_raw_response(
                writer, status, body, content_type, extra_headers,
                response_keep_alive
            )

        async def report_upload_progress(phase, completed=0, total=0):
            nonlocal progress_response_started, progress_percent, progress_phase
            if phase not in (
                'writing', 'verification', 'firmware_writing',
                'firmware_verification', 'application_verification'
            ):
                return
            total = int(total or 0)
            completed = int(completed or 0)
            percent = int(completed * 100 / total) if total > 0 else 0
            percent = max(0, min(100, percent))
            progress_record['phase'] = phase
            progress_record['percent'] = percent
            if phase == progress_phase and percent == progress_percent:
                return
            progress_phase = phase
            progress_percent = percent
            # The request body still contains firmware while the inactive
            # partition is being written.  Do not close the upload connection
            # until the body has been fully consumed and read-back verification
            # begins.  The browser polls the shared progress record meanwhile.
            if phase in ('verification', 'application_verification') and not progress_response_started:
                progress_response_started = True
                try:
                    await send_response(
                        writer,
                        '202 Accepted',
                        json.dumps({'phase': 'verification'}),
                        'application/json'
                    )
                except Exception:
                    # Verification must not fail just because the browser closed
                    # the upload response before receiving the acknowledgement.
                    pass
                finally:
                    try:
                        writer.close()
                    except Exception:
                        pass
                if asyncio:
                    await asyncio.sleep(0)

        async def finish_progress_response(phase, message):
            progress_record['phase'] = phase
            if phase == 'complete':
                progress_record['percent'] = 100
            progress_record['message'] = str(message)
            if not progress_response_started:
                return False
            return True

        async def close_writer():
            try:
                writer.close()
                if hasattr(writer, 'wait_closed'):
                    await writer.wait_closed()
            except Exception:
                pass

        try:
            line, headers = await http_support.read_request(reader)
            if not line:
                await close_writer()
                return

            try:
                request_line = line.decode().strip()
            except Exception:
                request_line = ''

            method, path = parse_request_line(request_line)
            if method == 'POST':
                status_snapshot.invalidate()
                module_snapshot.invalidate()
            request_parts = request_line.split()
            request_version = request_parts[2] if len(request_parts) == 3 else ''
            request_keep_alive = (
                remaining_requests > 1 and
                headers.get('connection', '').lower() != 'close' and
                (request_version == 'HTTP/1.1' or
                 headers.get('connection', '').lower() == 'keep-alive')
            )

            progress_id = headers.get('x-update-id', '')[:64]
            if progress_id:
                progress_record = upload_progress_by_id.setdefault(
                    progress_id, {'phase': 'idle', 'percent': 0}
                )
                if len(upload_progress_by_id) > 8:
                    for old_id in list(upload_progress_by_id)[:-8]:
                        upload_progress_by_id.pop(old_id, None)

            action_path = path or ''
            route = action_path.split('?', 1)[0]
            cookie_session_id = parse_cookies(headers).get('ham_session', '')
            session = sessions.get(cookie_session_id)
            session_id = cookie_session_id
            csrf_token = session.get('csrf', '') if session else ''
            session_role = session.get('role', '') if session else ''
            session_username = session.get('username', '') if session else ''
            is_login = route == '/login'
            is_password_change = (
                route == '/user' and
                parse_query(action_path).get('action', '') == 'password'
            )
            is_settings = route == '/settings'
            is_portal_settings = route == '/portal-settings'
            is_wifi_settings = route == '/wifi-settings'
            is_ntp_settings = route == '/ntp-settings'
            is_mqtt = route == '/mqtt'
            is_home_assistant = route == '/home-assistant'
            is_device_api = route == '/device-api'
            is_logging_settings = route == '/logging-settings'
            is_user_settings = route == '/user'
            is_user_management = route in ('/user/add', '/user/update', '/user/remove')
            is_operational_settings = (
                is_settings or is_portal_settings or is_wifi_settings or
                is_ntp_settings or is_mqtt or is_home_assistant or is_device_api or
                is_logging_settings or is_user_settings
            )
            is_module_settings = route == '/module-settings'
            is_certificates = route == '/certificates'
            is_updates = route == '/updates'
            is_diagnostics = route == '/diagnostics'
            is_logging = route == '/logging'
            is_audit_logging = route == '/audit-log'
            is_device_control = route in ('/device-control', '/factory-default')
            is_factory_default = route == '/factory-default'
            is_configuration_backup = route == '/configuration-backup'
            is_health_history = route == '/health-history'
            is_configuration_import = route in (
                '/configuration-import-preview', '/configuration-import-apply',
                '/secure-configuration-import-preview',
                '/secure-configuration-import-apply'
            )
            is_asset = route in ('/assets/portal.css', '/assets/portal.js')
            csrf_error = False
            form_params = {}
            is_upload = bool(
                path and (
                    path.startswith('/resumable-upload-chunk') or
                    path.startswith('/certificate-upload')
                )
            )
            if is_upload:
                request_keep_alive = False
            if method == 'POST' and not is_upload:
                length = int(headers.get('content-length', '0') or 0)
                is_json_validation = (
                    route == '/validate-configuration' and
                    headers.get('content-type', '').split(';', 1)[0].strip() == 'application/json'
                )
                max_form_size = 393216 if is_configuration_import else (65536 if is_module_settings else (8192 if is_operational_settings else (
                    2048 if (is_login or is_password_change or is_factory_default or is_user_management) else 65536
                )))
                if length > max_form_size:
                    raise ValueError('portal form is too large')
                body = (
                    await http_support.read_exact_body(
                        reader, length, max_form_size
                    )
                    if length else b''
                )
                form_params = parse_portal_body(route, headers, body)
                form_csrf = form_params.get('csrf', '')
                header_csrf = headers.get('x-csrf-token', '')
                csrf_error = False if is_login else (
                    form_csrf != csrf_token and header_csrf != csrf_token
                )
            elif method == 'POST' and is_upload:
                csrf_error = headers.get('x-csrf-token', '') != csrf_token

            quiet_audit_routes = (
                '/assets/portal.css', '/assets/portal.js', '/logs', '/partials',
                '/api/status', '/api/overview', '/api/module-diagnostics',
                '/update-progress', '/task-status', '/resumable-upload-status',
                '/audit-logs',
                '/api/restart-required'
            )
            session_valid = session is not None
            if (
                route not in quiet_audit_routes and not is_login and
                session_valid
            ):
                log_output(
                    'Local', 'Web portal request',
                    {'log': (
                        session_username + ' (' + session_role + ') from ' +
                        peer_address + ' ' + str(method) + ' ' + str(route)
                    )},
                    'DEBUG'
                )

            if is_asset and method == 'GET':
                asset = (
                    portal_ui.PORTAL_CSS
                    if route.endswith('.css') else portal_ui.PORTAL_JS
                )
                await send_response(
                    writer, '200 OK', asset,
                    'text/css; charset=utf-8' if route.endswith('.css')
                    else 'application/javascript; charset=utf-8',
                    (('Cache-Control', 'public, max-age=31536000, immutable'),)
                )
            elif not path or method not in ('GET', 'POST'):
                body = 'Method not allowed'
                await send_response(writer, '405 Method Not Allowed', body, 'text/plain')
            elif is_login and method == 'GET':
                if session_valid:
                    await send_redirect(
                        writer,
                        '/user' if password_change_required else '/'
                    )
                else:
                    await send_response(writer, '200 OK', render_login_page())
            elif is_login and method == 'POST':
                params = form_params
                identity = (
                    await authenticator(
                        params.get('username', ''), params.get('password', '')
                    ) if authenticator else (
                        {'username': username, 'role': 'administrator'}
                        if await credentials_match_async(
                            params.get('username', ''), params.get('password', ''),
                            username, password_verifier
                        ) else None
                    )
                )
                if identity:
                    session = sessions.create(identity)
                    session_id = session['id']
                    csrf_token = session['csrf']
                    session_role = session['role']
                    session_username = session['username']
                    cookie = session_cookie(session_id, secure_cookie)
                    cached_page['body'] = None
                    login_failures = 0
                    log_output(
                        'Local', 'Portal authentication',
                        {'log': 'Successful login for ' + str(session_username) +
                         ' (' + str(session_role) + ') from ' + peer_address,
                         'force': True, 'audit': True},
                        'INFO'
                    )
                    if network_trial_confirmer:
                        try:
                            network_trial_confirmer()
                        except Exception as exc:
                            log_output(
                                'Local', 'Network settings',
                                {'log': 'Could not confirm candidate settings - ' + str(exc)},
                                'ERROR'
                            )
                    await send_redirect(
                        writer,
                        '/user' if password_change_required else '/', (
                            ('Set-Cookie', cookie),
                            ('Referrer-Policy', 'no-referrer')
                        )
                    )
                else:
                    login_failures += 1
                    log_output(
                        'Local', 'Portal authentication',
                        {'log': 'Rejected login for ' + str(params.get('username', '')) +
                         ' from ' + peer_address, 'force': True, 'audit': True},
                        'ERROR'
                    )
                    await asyncio.sleep(min(2, login_failures * 0.25))
                    await send_response(
                        writer, '401 Unauthorized',
                        render_login_page(
                            params.get('username', ''),
                            'Invalid username or password.'
                        )
                    )
            elif not session_valid:
                await send_response(
                    writer, '401 Unauthorized', render_login_page()
                )
            elif csrf_error:
                log_output(
                    'Local', 'Portal authorization',
                    {'log': (
                        'Rejected invalid CSRF token for ' + session_username +
                        ' from ' + peer_address + ' on ' + method + ' ' + route
                    ), 'force': True, 'audit': True},
                    'ERROR'
                )
                await send_response(writer, '403 Forbidden', 'Invalid CSRF token', 'text/plain')
            elif not portal_auth.role_allows(
                session_role, portal_auth.required_role(method, route)
            ):
                log_output(
                    'Local', 'Portal authorization',
                    {'log': 'Denied ' + session_username + ' ' + method + ' ' + route,
                     'force': True, 'audit': True}, 'ERROR'
                )
                await send_response(
                    writer, '403 Forbidden', 'Your portal role cannot perform this action.',
                    'text/plain'
                )
            elif method == 'GET' and route in ('/change-password', '/user/password'):
                await send_response(writer, '404 Not Found', 'Not found', 'text/plain')
            elif method == 'POST' and route == '/logout':
                log_output(
                    'Local', 'Portal authentication',
                    {'log': (
                        'Logout for ' + session_username + ' (' + session_role +
                        ') from ' + peer_address
                    ), 'force': True, 'audit': True}, 'INFO'
                )
                sessions.revoke(session_id)
                cached_page['body'] = None
                await send_redirect(
                    writer, '/login',
                    (('Set-Cookie', session_cookie('', secure_cookie, True)),)
                )
            elif method == 'GET' and route == '/api/restart-required':
                status = (
                    restart_status_getter() if restart_status_getter else
                    {'required': False, 'reason_count': 0, 'reasons': []}
                )
                await send_response(
                    writer, '200 OK', json.dumps(status), 'application/json'
                )
            elif method == 'POST' and route in ('/restart-device', '/shutdown-device'):
                shutting_down = route == '/shutdown-device'
                transition_handler = shutdown_request_handler if shutting_down else restart_request_handler
                if transition_handler is None:
                    await send_response(
                        writer, '503 Service Unavailable', ('Shutdown' if shutting_down else 'Restart') +
                        ' control is unavailable', 'text/plain'
                    )
                else:
                    result = transition_handler()
                    message = result.get('message', 'The device is shutting down.' if shutting_down else 'The device is restarting.')
                    sessions.revoke(session_id)
                    await send_response(
                        writer, '200 OK', render_shutdown_complete_page(message)
                        if shutting_down else portal_ui.restart_page(
                            result.get('login_url', login_url), message
                        ),
                        extra_headers=(('Set-Cookie', session_cookie('', secure_cookie, True)),)
                    )
            elif method == 'POST' and is_password_change:
                params = form_params
                current_password = params.get('current_password', '')
                new_password = params.get('new_password', '')
                confirmation = params.get('confirm_password', '')
                current_identity = (
                    await authenticator(session_username, current_password)
                    if authenticator else (
                        {'username': username, 'role': 'administrator'}
                        if await credential_security.verify_password_async(
                            current_password, password_verifier
                        ) else None
                    )
                )
                if not current_identity:
                    await send_response(writer, '400 Bad Request', (
                        render_password_change_page(
                            csrf_token, 'Current password is incorrect.', True
                        ) if password_change_required else render_user_settings_page(
                            csrf_token, settings_getter() if settings_getter else {},
                            password_message='Current password is incorrect.',
                            password_error=True
                        )
                    ))
                elif new_password != confirmation:
                    await send_response(writer, '400 Bad Request', (
                        render_password_change_page(
                            csrf_token, 'New passwords do not match.', True
                        ) if password_change_required else render_user_settings_page(
                            csrf_token, settings_getter() if settings_getter else {},
                            password_message='New passwords do not match.',
                            password_error=True
                        )
                    ))
                else:
                    try:
                        if password_setter is None:
                            raise RuntimeError('portal password storage is unavailable')
                        if user_password_setter:
                            user_password_setter(session_username, new_password)
                        else:
                            password_verifier = password_setter(new_password)
                    except Exception as exc:
                        await send_response(writer, '400 Bad Request', (
                            render_password_change_page(
                                csrf_token, str(exc), True
                            ) if password_change_required else render_user_settings_page(
                                csrf_token, settings_getter() if settings_getter else {},
                                password_message=str(exc), password_error=True
                            )
                        ))
                    else:
                        was_password_change_required = password_change_required
                        password_change_required = False
                        sessions.revoke_user(session_username)
                        session = sessions.create({
                            'username': session_username, 'role': session_role
                        })
                        cookie = session_cookie(session['id'], secure_cookie)
                        cached_page['body'] = None
                        log_output(
                            'Local', 'Web portal',
                            {'log': 'Portal password changed', 'force': True},
                            'INFO'
                        )
                        await send_redirect(
                            writer, '/' if was_password_change_required else '/user',
                            (('Set-Cookie', cookie),)
                        )
            elif password_change_required:
                if method == 'GET' and is_user_settings:
                    await send_response(
                        writer, '200 OK',
                        render_password_change_page(csrf_token, required=True)
                    )
                else:
                    await send_redirect(writer, '/user')
            elif method == 'GET' and is_device_control:
                await send_response(
                    writer, '200 OK',
                    render_device_control_page(csrf_token)
                )
            elif method == 'POST' and is_factory_default:
                current_password = form_params.get('current_password', '')
                setup_password = form_params.get('setup_password', '')
                confirmation = form_params.get('confirm_setup_password', '')
                reset_error = ''
                if not (
                    await authenticator(session_username, current_password)
                    if authenticator else await credential_security.verify_password_async(
                        current_password, password_verifier
                    )
                ):
                    reset_error = 'Current administrator password is incorrect.'
                elif form_params.get('reset_confirmation', '') != 'RESET':
                    reset_error = 'Type RESET exactly to confirm the factory reset.'
                elif setup_password != confirmation:
                    reset_error = 'Setup Wi-Fi passwords do not match.'
                if reset_error:
                    await send_response(
                        writer, '400 Bad Request',
                        render_device_control_page(csrf_token, reset_error)
                    )
                else:
                    try:
                        if factory_reset_handler is None:
                            raise RuntimeError('factory reset is unavailable')
                        factory_reset_handler(setup_password)
                    except Exception as exc:
                        await send_response(
                            writer, '400 Bad Request',
                            render_device_control_page(csrf_token, str(exc))
                        )
                    else:
                        log_output(
                            'Local', 'Factory default',
                            {'log': 'Authenticated factory reset requested', 'force': True},
                            'INFO'
                        )
                        previous_session = csrf_token
                        sessions.revoke(session_id)
                        cached_page['body'] = None
                        await send_response(
                            writer, '200 OK',
                            render_factory_default_complete_page(previous_session),
                            extra_headers=((
                                'Set-Cookie', session_cookie('', secure_cookie, True)
                            ),)
                        )
            elif method == 'GET' and is_operational_settings:
                if settings_getter is None:
                    await send_response(writer, '404 Not Found', 'Settings are unavailable', 'text/plain')
                else:
                    await send_response(
                        writer, '200 OK',
                        render_operational(
                            route, csrf_token, settings_getter(),
                            current_user=session_username,
                            portal_user_getter=portal_user_getter,
                            logging_renderer=render_logging_settings_page
                        )
                    )
            elif method == 'POST' and is_user_management:
                try:
                    if route == '/user/add':
                        if portal_user_add is None:
                            raise RuntimeError('portal user management is unavailable')
                        portal_user_add(
                            form_params.get('username', ''),
                            form_params.get('password', ''),
                            form_params.get('role', 'viewer')
                        )
                    elif route == '/user/update':
                        if portal_user_update is None:
                            raise RuntimeError('portal user management is unavailable')
                        portal_user_update(
                            form_params.get('username', ''),
                            role=form_params.get('role', 'viewer'),
                            enabled=form_params.get('enabled') == 'true'
                        )
                    else:
                        if portal_user_remove is None:
                            raise RuntimeError('portal user management is unavailable')
                        portal_user_remove(form_params.get('username', ''))
                except Exception as exc:
                    await send_response(
                        writer, '400 Bad Request', render_user_settings_page(
                            csrf_token, settings_getter() if settings_getter else {},
                            str(exc), True,
                            users=portal_user_getter() if portal_user_getter else (),
                            current_user=session_username
                        )
                    )
                else:
                    await send_redirect(writer, '/user')
            elif method == 'POST' and is_operational_settings:
                try:
                    if settings_setter is None:
                        raise RuntimeError('settings storage is unavailable')
                    message = settings_setter(form_params)
                    current_settings = settings_getter() if settings_getter else {}
                except Exception as exc:
                    current_settings = settings_getter() if settings_getter else {}
                    await send_response(
                        writer, '400 Bad Request',
                        render_operational(
                            route, csrf_token, current_settings, str(exc), True,
                            session_username, portal_user_getter,
                            render_logging_settings_page
                        )
                    )
                else:
                    cached_page['body'] = None
                    log_output(
                        'Local', 'Web portal',
                        {'log': 'Operational settings changed', 'force': True},
                        'INFO'
                    )
                    text = message
                    if isinstance(message, dict):
                        text = message.get('message', '')
                    await send_response(
                        writer, '200 OK',
                        render_operational(
                            route, csrf_token, current_settings, text, False,
                            session_username, portal_user_getter,
                            render_logging_settings_page
                        )
                    )
            elif method == 'GET' and is_module_settings:
                if module_settings_getter is None:
                    await send_response(writer, '404 Not Found', 'Module settings are unavailable', 'text/plain')
                else:
                    await send_response(
                        writer, '200 OK',
                        render_module_settings_page(csrf_token, module_settings_getter())
                    )
            elif method == 'POST' and is_module_settings:
                submitted = form_params.get('module_settings_json', '')
                try:
                    if module_settings_setter is None:
                        raise RuntimeError('module settings storage is unavailable')
                    message = module_settings_setter(submitted)
                except Exception as exc:
                    await send_response(
                        writer, '400 Bad Request',
                        render_module_settings_page(csrf_token, submitted, str(exc), True)
                    )
                else:
                    log_output(
                        'Local', 'Web portal',
                        {'log': 'Module settings changed', 'force': True}, 'INFO'
                    )
                    await send_response(
                        writer, '200 OK',
                        render_module_settings_page(
                            csrf_token,
                            module_settings_getter() if module_settings_getter else submitted,
                            message
                        )
                    )
            elif method == 'GET' and is_certificates:
                await send_response(
                    writer, '200 OK', render_certificate_page(
                        csrf_token,
                        certificates=(
                            certificate_info_getter()
                            if certificate_info_getter else {}
                        )
                    )
                )
            elif method == 'GET' and is_updates:
                await send_response(
                    writer, '200 OK',
                    render_updates_page(
                        csrf_token,
                        status_snapshot.get(),
                        settings_getter() if settings_getter else {}
                    )
                )
            elif method == 'GET' and is_diagnostics:
                await send_response(
                    writer, '200 OK',
                    render_module_diagnostics_page(
                        csrf_token,
                        module_snapshot.get(),
                        value_refresh_ms or 5000,
                        session_role
                    )
                )
            elif method == 'GET' and is_logging:
                await send_response(
                    writer, '200 OK',
                    render_logging_page(
                        csrf_token, loglevel_getter(), levels, log_getter(),
                        log_refresh_ms, settings_getter() if settings_getter else {}
                    )
                )
            elif method == 'GET' and is_audit_logging:
                await send_response(
                    writer, '200 OK',
                    render_audit_logging_page(
                        csrf_token, audit_log_getter(), log_refresh_ms
                    )
                )
            elif method == 'POST' and is_logging:
                try:
                    if settings_setter is None:
                        raise RuntimeError('settings storage is unavailable')
                    message = settings_setter(form_params)
                except Exception as exc:
                    await send_response(
                        writer, '400 Bad Request', render_logging_page(
                            csrf_token, loglevel_getter(), levels, log_getter(),
                            log_refresh_ms, settings_getter() if settings_getter else {}
                        ) + '<p>' + html_escape(exc) + '</p>'
                    )
                else:
                    await send_response(
                        writer, '200 OK', render_logging_page(
                            csrf_token, loglevel_getter(), levels, log_getter(),
                            log_refresh_ms, settings_getter() if settings_getter else {},
                            message.get('message', '') if isinstance(message, dict) else message
                        )
                    )
            elif method == 'GET' and is_configuration_backup:
                await send_response(
                    writer, '200 OK', render_configuration_backup_page(csrf_token)
                )
            elif method == 'GET' and is_health_history:
                await send_response(
                    writer, '200 OK', render_health_history_page(
                        csrf_token, status_snapshot.get()
                    )
                )
            elif method == 'POST' and route == '/reset-health-history':
                apply_portal_action(
                    'reset-health-history', action_path, action_handler, log_output,
                    form_params
                )
                await send_redirect(writer, '/health-history')
            elif method == 'POST' and route == '/configuration-import-preview':
                if config_import_preview_handler is None:
                    await send_response(writer, '503 Service Unavailable', 'Configuration import unavailable', 'text/plain')
                else:
                    result = config_import_preview_handler(body)
                    await send_response(writer, '200 OK', json.dumps(result), 'application/json')
            elif method == 'POST' and route == '/download-secure-configuration':
                if not secure_cookie:
                    await send_response(writer, '403 Forbidden', 'Encrypted backup requires HTTPS', 'text/plain')
                elif secure_config_backup_getter is None:
                    await send_response(writer, '503 Service Unavailable', 'Encrypted backup unavailable', 'text/plain')
                elif form_params.get('backup_password', '') != form_params.get('confirm_backup_password', ''):
                    await send_response(writer, '400 Bad Request', 'Backup passwords do not match', 'text/plain')
                else:
                    payload = secure_config_backup_getter(form_params.get('backup_password', ''))
                    await send_response(
                        writer, '200 OK', json.dumps(payload),
                        'application/json; charset=utf-8',
                        (('Content-Disposition', 'attachment; filename="' +
                          configuration_backup_filename(True) + '"'),)
                    )
            elif method == 'POST' and route == '/secure-configuration-import-preview':
                if not secure_cookie:
                    await send_response(writer, '403 Forbidden', 'Encrypted restore requires HTTPS', 'text/plain')
                elif secure_config_import_preview_handler is None:
                    await send_response(writer, '503 Service Unavailable', 'Encrypted restore unavailable', 'text/plain')
                else:
                    result = secure_config_import_preview_handler(json.loads(body.decode()))
                    await send_response(writer, '200 OK', json.dumps(result), 'application/json')
            elif method == 'POST' and route == '/secure-configuration-import-apply':
                if not secure_cookie:
                    await send_response(writer, '403 Forbidden', 'Encrypted restore requires HTTPS', 'text/plain')
                elif secure_config_import_apply_handler is None:
                    await send_response(writer, '503 Service Unavailable', 'Encrypted restore unavailable', 'text/plain')
                else:
                    request = json.loads(body.decode())
                    message = secure_config_import_apply_handler(request.get('token', ''))
                    await send_response(
                        writer, '200 OK',
                        render_configuration_backup_page(csrf_token, message)
                    )
            elif method == 'POST' and route == '/configuration-import-apply':
                if config_import_apply_handler is None:
                    await send_response(writer, '503 Service Unavailable', 'Configuration import unavailable', 'text/plain')
                else:
                    request = json.loads(body.decode())
                    message = config_import_apply_handler(request.get('token', ''))
                    await send_response(
                        writer, '200 OK',
                        render_configuration_backup_page(csrf_token, message)
                    )
            elif method == 'POST' and route == '/update-preferences':
                try:
                    if update_preferences_setter is None:
                        raise RuntimeError('update preference storage is unavailable')
                    update_preferences_setter(form_params)
                except Exception as exc:
                    await send_response(
                        writer, '400 Bad Request',
                        render_updates_page(
                            csrf_token,
                            status_snapshot.get(),
                            settings_getter() if settings_getter else {},
                            str(exc), True
                        )
                    )
                else:
                    await send_redirect(writer, '/updates')
            elif method == 'POST' and route == '/revoke-api-client':
                result = apply_portal_action(
                    'revoke-api-client', action_path, action_handler, log_output,
                    form_params
                )
                await send_redirect(writer, '/device-api')
            elif method == 'POST' and route == '/acme-settings':
                result = apply_portal_action(
                    'update-acme-settings', action_path, action_handler, log_output,
                    form_params
                )
                await send_response(
                    writer, '200 OK', render_certificate_page(
                        csrf_token,
                        result.get('message', '') if isinstance(result, dict) else result,
                        certificate_info_getter() if certificate_info_getter else {}
                    )
                )
            elif method == 'POST' and route == '/resumable-upload-begin':
                if resumable_begin is None:
                    await send_response(writer, '503 Service Unavailable', 'Resumable uploads are unavailable', 'text/plain')
                else:
                    request = json.loads(body.decode())
                    identifier = str(request.get('id', ''))[:64]
                    try:
                        result = resumable_begin(request)
                    except Exception as exc:
                        upload_progress_by_id[identifier] = {
                            'phase': 'failed', 'percent': 0,
                            'message': 'Upload rejected: ' + str(exc)
                        }
                        await send_response(
                            writer, '400 Bad Request', str(exc), 'text/plain'
                        )
                    else:
                        await send_response(writer, '200 OK', json.dumps(result), 'application/json')
            elif method == 'GET' and route == '/resumable-upload-status':
                if resumable_status is None:
                    await send_response(writer, '503 Service Unavailable', 'Resumable uploads are unavailable', 'text/plain')
                else:
                    identifier = parse_query(action_path).get('id', '')
                    await send_response(
                        writer, '200 OK', json.dumps(resumable_status(identifier)),
                        'application/json'
                    )
            elif method == 'POST' and route == '/resumable-upload-chunk':
                if resumable_append is None:
                    await send_response(writer, '503 Service Unavailable', 'Resumable uploads are unavailable', 'text/plain')
                else:
                    params = parse_query(action_path)
                    identifier = str(params.get('id', ''))[:64]
                    try:
                        result = await resumable_append(
                            identifier, params.get('offset', 0), reader,
                            int(headers.get('content-length', '0') or 0)
                        )
                    except Exception as exc:
                        upload_progress_by_id[identifier] = {
                            'phase': 'failed', 'percent': 0,
                            'message': 'Upload rejected: ' + str(exc)
                        }
                        await send_response(
                            writer, '400 Bad Request', str(exc), 'text/plain'
                        )
                    else:
                        await send_response(writer, '200 OK', json.dumps(result), 'application/json')
            elif method == 'POST' and route == '/resumable-upload-complete':
                if resumable_complete is None:
                    await send_response(writer, '503 Service Unavailable', 'Resumable uploads are unavailable', 'text/plain')
                else:
                    request = json.loads(body.decode())
                    progress_id = str(request.get('id', ''))[:64]
                    progress_record = upload_progress_by_id.setdefault(
                        progress_id, {'phase': 'receiving', 'percent': 100}
                    )
                    try:
                        result = await resumable_complete(
                            progress_id, report_upload_progress
                        )
                    except Exception as exc:
                        message = 'Update rejected: ' + str(exc)
                        if not await finish_progress_response('failed', message):
                            await send_response(writer, '400 Bad Request', message, 'text/plain')
                    else:
                        if not await finish_progress_response('complete', result):
                            await send_response(writer, '200 OK', str(result), 'text/plain')
            elif method == 'POST' and path.startswith('/certificate-upload'):
                if certificate_upload_handler is None:
                    await send_response(writer, '503 Service Unavailable', 'Certificate upload is unavailable', 'text/plain')
                else:
                    length = int(headers.get('content-length', '0') or 0)
                    if length <= 0 or length > 16384:
                        raise ValueError('certificate file size is invalid')
                    await certificate_upload_handler(
                        headers.get('x-certificate-kind', ''), reader, length
                    )
                    await send_response(writer, '200 OK', 'Certificate file stored', 'text/plain')
            elif method == 'POST' and route == '/validate-certificates':
                try:
                    if certificate_validate_handler is None:
                        raise RuntimeError('certificate validation is unavailable')
                    result = certificate_validate_handler()
                except Exception as exc:
                    await send_response(writer, '400 Bad Request', str(exc), 'text/plain')
                else:
                    message = (
                        result.get('message', '') if isinstance(result, dict) else str(result)
                    )
                    await send_response(
                        writer, '200 OK', render_certificate_page(
                            csrf_token, message,
                            certificate_info_getter() if certificate_info_getter else {}
                        )
                    )
            elif method == 'POST' and path.startswith('/set-loglevel'):
                try:
                    apply_logging_change(
                        form_params.get('level', ''),
                        form_params.get('log_buffer_lines', 200), levels,
                        loglevel_setter, log_buffer_lines_setter, log_output
                    )
                except (ValueError, RuntimeError) as exc:
                    await send_response(
                        writer, '400 Bad Request', str(exc), 'text/plain'
                    )
                else:
                    await send_redirect(writer, '/logging')
            elif path.startswith('/update-progress'):
                requested_id = parse_query(path).get('id', '')
                current_progress = upload_progress_by_id.get(
                    requested_id, {'phase': 'idle', 'percent': 0}
                )
                await send_response(
                    writer, '200 OK', json.dumps(current_progress), 'application/json'
                )
            elif path.startswith('/task-status'):
                requested_id = parse_query(path).get('id', '')
                current_task = (
                    task_status_getter(requested_id)
                    if task_status_getter else
                    {'phase': 'failed', 'message': 'Task status is unavailable'}
                )
                await send_response(
                    writer, '200 OK', json.dumps(current_task), 'application/json'
                )
            elif path.startswith('/api/wifi-networks'):
                if wifi_scan_getter is None:
                    await send_response(
                        writer, '503 Service Unavailable',
                        json.dumps({'error': 'Wi-Fi scanning is unavailable'}),
                        'application/json'
                    )
                else:
                    await send_response(
                        writer, '200 OK', json.dumps(wifi_scan_getter()),
                        'application/json'
                    )
            elif path.startswith('/audit-logs'):
                body = render_log_text(audit_log_getter())
                await send_response(writer, '200 OK', body, 'text/plain')
            elif path.startswith('/logs'):
                body = render_log_text(log_getter())
                await send_response(writer, '200 OK', body, 'text/plain')
            elif path.startswith('/download-audit-logs'):
                await send_log_download(
                    writer, audit_log_getter(), 'ha-device-audit-logs.txt'
                )
            elif path.startswith('/download-logs'):
                await send_log_download(writer, log_getter(), 'ha-device-logs.txt')
            elif path.startswith('/download-diagnostics'):
                safe_logs = []
                for line in list(log_getter())[-100:]:
                    safe_logs.append(str(line))
                diagnostic_payload = {
                    'status': status_snapshot.get(),
                    'modules': module_snapshot.get(),
                    'logs': safe_logs
                }
                await send_response(
                    writer,
                    '200 OK',
                    json.dumps(diagnostic_payload),
                    'application/json; charset=utf-8',
                    (('Content-Disposition', 'attachment; filename="ha-device-diagnostics.json"'),)
                )
            elif path.startswith('/download-configuration'):
                if config_backup_getter is None:
                    await send_response(writer, '404 Not Found', 'Configuration backup unavailable', 'text/plain')
                else:
                    payload = config_backup_getter()
                    await send_response(
                        writer,
                        '200 OK',
                        json.dumps(payload),
                        'application/json; charset=utf-8',
                        (('Content-Disposition', 'attachment; filename="' +
                          configuration_backup_filename(
                              False, payload.get('created_at')
                              if isinstance(payload, dict) else None
                          ) + '"'),)
                    )
            elif path.startswith('/api/status'):
                payload = {
                    'status': status_snapshot.get(),
                    'modules': module_snapshot.get()
                }
                body = json.dumps(payload) if json else '{}'
                await send_response(writer, '200 OK', body, 'application/json')
            elif path.startswith('/api/overview'):
                body = json.dumps({
                    'status': render_overview_status(
                        status_snapshot.get()
                    ),
                    'modules': render_overview_modules(
                        module_snapshot.get()
                    )
                })
                await send_response(writer, '200 OK', body, 'application/json')
            elif path.startswith('/api/module-diagnostics'):
                body = json.dumps({
                    'modules': render_modules_html(
                        module_snapshot.get(), csrf_token,
                        session_role
                    )
                })
                await send_response(writer, '200 OK', body, 'application/json')
            elif path.startswith('/partials'):
                current_status = status_snapshot.get()
                payload = {
                    'live_sections': render_live_sections_html(
                        current_status,
                        module_snapshot.get(),
                        csrf_token,
                        session_role
                    ),
                    'update_summary': render_update_summary_html(current_status),
                    'update_actions': portal_ui.restrict_actions(
                        render_update_actions_html(
                            current_status, csrf_token
                        ),
                        session_role
                    )
                }
                body = json.dumps(payload)
                await send_response(writer, '200 OK', body, 'application/json')
            elif method == 'POST' and path.startswith('/discover'):
                apply_portal_action('discover', action_path, action_handler, log_output, form_params)
                await send_redirect(writer, '/')
            elif method == 'POST' and path.startswith('/calibrate'):
                apply_portal_action('calibrate', action_path, action_handler, log_output, form_params)
                await send_redirect(writer, '/diagnostics')
            elif method == 'POST' and path.startswith('/ems-debug'):
                apply_portal_action('ems-debug', action_path, action_handler, log_output, form_params)
                await send_redirect(writer, '/diagnostics')
            elif method == 'POST' and path.startswith('/activate-update'):
                result = apply_portal_action(
                    'activate-update', action_path, action_handler, log_output, form_params
                )
                sessions.revoke(session_id)
                await send_response(
                    writer, '200 OK',
                    portal_ui.restart_page(
                        login_url,
                        result.get('message', '') if isinstance(result, dict) else result
                    ),
                    extra_headers=(
                        ('Set-Cookie', session_cookie('', secure_cookie, True)),
                    )
                )
            elif method == 'POST' and path.startswith('/activate-universal'):
                result = apply_portal_action(
                    'activate-universal', action_path, action_handler, log_output, form_params
                )
                sessions.revoke(session_id)
                await send_response(
                    writer, '200 OK',
                    portal_ui.restart_page(
                        login_url,
                        result.get('message', '') if isinstance(result, dict) else result
                    ),
                    extra_headers=(
                        ('Set-Cookie', session_cookie('', secure_cookie, True)),
                    )
                )
            elif method == 'POST' and path.startswith('/activate-firmware'):
                result = apply_portal_action(
                    'activate-firmware', action_path, action_handler, log_output, form_params
                )
                sessions.revoke(session_id)
                await send_response(
                    writer, '200 OK',
                    portal_ui.restart_page(
                        login_url,
                        result.get('message', '') if isinstance(result, dict) else result
                    ),
                    extra_headers=(
                        ('Set-Cookie', session_cookie('', secure_cookie, True)),
                    )
                )
            elif method == 'POST' and path.startswith('/rollback-application'):
                result = apply_portal_action(
                    'rollback-application', action_path, action_handler, log_output, form_params
                )
                sessions.revoke(session_id)
                await send_response(
                    writer, '200 OK',
                    portal_ui.restart_page(
                        login_url,
                        result.get('message', '') if isinstance(result, dict) else result
                    ),
                    extra_headers=(
                        ('Set-Cookie', session_cookie('', secure_cookie, True)),
                    )
                )
            elif method == 'POST' and path.startswith('/check-release'):
                result = apply_portal_action(
                    'check-release', action_path, action_handler, log_output, form_params
                )
                if isinstance(result, dict) and result.get('task_id'):
                    await send_response(
                        writer, '202 Accepted',
                        portal_ui.task_page(
                            result['task_id'], result.get('message', 'Checking for updates'),
                            '/updates'
                        )
                    )
                else:
                    await send_redirect(writer, '/updates')
            elif method == 'POST' and path.startswith('/download-release'):
                result = apply_portal_action(
                    'download-release', action_path, action_handler, log_output, form_params
                )
                if isinstance(result, dict) and result.get('task_id'):
                    await send_response(
                        writer, '202 Accepted',
                        portal_ui.task_page(
                            result['task_id'], result.get('message', 'Downloading release'),
                            '/updates'
                        )
                    )
                else:
                    await send_redirect(writer, '/updates')
            elif method == 'POST' and path.startswith('/validate-configuration'):
                result = apply_portal_action(
                    'validate-configuration', action_path, action_handler, log_output,
                    form_params
                )
                if is_json_validation:
                    await send_response(writer, '200 OK', result, 'text/plain')
                else:
                    await send_response(
                        writer,
                        '200 OK',
                        '<!doctype html><meta name="viewport" content="width=device-width">'
                        '<h1>Configuration validation</h1><pre>' + html_escape(result) +
                        '</pre><p><a href="/">Return to portal</a></p>'
                    )
            elif method != 'GET':
                await send_response(writer, '405 Method Not Allowed', 'Method not allowed', 'text/plain')
            else:
                body = render_overview_page(
                    csrf_token,
                    status_snapshot.get(),
                    module_snapshot.get(),
                    value_refresh_ms or 5000
                )
                await send_response(writer, '200 OK', body)

            if response_keep_alive and remaining_requests > 1:
                handed_off = True
                asyncio.create_task(handle_client(
                    reader, writer, remaining_requests - 1
                ))
                await asyncio.sleep(0)

        except Exception as exc:
            if (
                is_client_disconnect_error(exc) or
                http_support.is_timeout_error(exc)
            ):
                return
            try:
                log_output('Local', 'Web portal', {'log': 'Request failed - ' + str(exc)}, 'ERROR')
            except Exception:
                pass
            try:
                request_keep_alive = False
                await send_response(
                    writer, '500 Internal Server Error',
                    'Portal request failed. See Maintenance > Device log for details.',
                    'text/plain'
                )
            except Exception:
                pass
        finally:
            if not handed_off:
                await close_writer()

    ssl_context = None
    if settings.get('https', False):
        ssl_context = make_tls_context(settings.get('cert_path'), settings.get('key_path'))

    return await asyncio.start_server(
        handle_client,
        settings.get('host', '0.0.0.0'),
        settings.get('port', 8443 if settings.get('https', False) else 8080),
        backlog=4,
        ssl=ssl_context
    )

"""Password-protected local Wi-Fi credential recovery portal."""

try:
    import uasyncio as asyncio
except ImportError:
    try:
        import asyncio
    except ImportError:
        asyncio = None

try:
    import network
except ImportError:
    network = None

try:
    import uos as os
except ImportError:
    import os

try:
    import ubinascii as binascii
except ImportError:
    import binascii

import time

import http_support


RECOVERY_PORT = 80
RECOVERY_TIMEOUT_S = 900
WIFI_SCAN_CACHE_S = 300
_wifi_scan_cache = []
_wifi_scan_updated_ms = None
_wifi_scan_task = None


def scan_wifi_networks(limit=32):
    """Return visible SSIDs once each, strongest signal first."""
    if network is None:
        raise RuntimeError('Wi-Fi scanning is unavailable')
    wlan_class = network.WLAN
    interface_id = getattr(wlan_class, 'IF_STA', getattr(network, 'STA_IF', 0))
    station = wlan_class(interface_id)
    station.active(True)
    strongest = {}
    for entry in station.scan() or ():
        if not entry:
            continue
        raw_ssid = entry[0]
        if isinstance(raw_ssid, bytes):
            try:
                ssid = raw_ssid.decode('utf-8')
            except Exception:
                ssid = raw_ssid.decode('utf-8', 'replace')
        else:
            ssid = str(raw_ssid)
        if not ssid or len(ssid.encode('utf-8')) > 32:
            continue
        try:
            rssi = int(entry[3])
        except Exception:
            rssi = -100
        previous = strongest.get(ssid)
        if previous is None or rssi > previous:
            strongest[ssid] = rssi
    ordered = sorted(strongest.items(), key=lambda item: (-item[1], item[0].lower()))
    return [
        {'ssid': ssid, 'rssi': rssi}
        for ssid, rssi in ordered[:max(1, int(limit))]
    ]


def _ticks_ms():
    getter = getattr(time, 'ticks_ms', None)
    return int(getter() if getter else time.monotonic() * 1000)


def _ticks_diff(left, right):
    differ = getattr(time, 'ticks_diff', None)
    return int(differ(left, right) if differ else left - right)


async def _refresh_wifi_scan(limit=32):
    global _wifi_scan_cache, _wifi_scan_updated_ms, _wifi_scan_task
    try:
        if hasattr(asyncio, 'sleep_ms'):
            await asyncio.sleep_ms(0)
        else:
            await asyncio.sleep(0)
        _wifi_scan_cache = list(scan_wifi_networks(limit))
        _wifi_scan_updated_ms = _ticks_ms()
    finally:
        _wifi_scan_task = None


def schedule_wifi_scan(limit=32):
    """Start one background scan without making an HTTP request wait for it."""
    global _wifi_scan_task
    if asyncio is None or _wifi_scan_task is not None:
        return False
    try:
        _wifi_scan_task = asyncio.create_task(_refresh_wifi_scan(limit))
    except (AttributeError, RuntimeError):
        _wifi_scan_task = None
        return False
    return True


def cached_wifi_networks(limit=32, refresh=True):
    """Return the last scan immediately and refresh it in the background."""
    stale = (
        _wifi_scan_updated_ms is None or
        _ticks_diff(_ticks_ms(), _wifi_scan_updated_ms) >= WIFI_SCAN_CACHE_S * 1000
    )
    if refresh or stale:
        schedule_wifi_scan(limit)
    return list(_wifi_scan_cache[:max(1, int(limit))])


def _decode(value):
    value = str(value).replace('+', ' ')
    result = []
    index = 0
    while index < len(value):
        if value[index] == '%' and index + 2 < len(value):
            try:
                result.append(chr(int(value[index + 1:index + 3], 16)))
                index += 3
                continue
            except ValueError:
                pass
        result.append(value[index])
        index += 1
    return ''.join(result)


def _form(body):
    values = {}
    for item in str(body).split('&'):
        if '=' in item:
            key, value = item.split('=', 1)
            values[_decode(key)] = _decode(value)
    return values


def _replace_file(source, target):
    try:
        os.remove(target)
    except OSError:
        pass
    os.rename(source, target)


def recovery_key():
    try:
        import credential_store
        value = credential_store.load(require_provisioned=True)['recovery']['ap_password']
        if credential_store.MIN_PASSWORD_LENGTH <= len(value) <= 63:
            return value
    except Exception:
        pass
    return ''


def recovery_password_verifier():
    try:
        import credential_store
        return credential_store.load(require_provisioned=True)['recovery']['password_verifier']
    except Exception:
        return ''


def recovery_enabled():
    try:
        import credential_store
        import device_config
        return (
            device_config.WIFI_RECOVERY_ENABLED and
            credential_store.is_provisioned()
        )
    except Exception:
        return False


def recovery_timeout():
    try:
        import device_config
        return max(60, int(device_config.WIFI_RECOVERY_TIMEOUT_S))
    except Exception:
        return RECOVERY_TIMEOUT_S


def _activate_access_point(ap_name, ap_password):
    if network is None:
        raise RuntimeError('Wi-Fi recovery is unavailable')
    if len(str(ap_password)) < 16 or len(str(ap_password)) > 63:
        raise ValueError('recovery access point password must contain 16 to 63 characters')
    wlan_class = network.WLAN
    interface_id = getattr(wlan_class, 'IF_AP', getattr(network, 'AP_IF', 1))
    access_point = wlan_class(interface_id)
    access_point.active(True)
    try:
        access_point.config(
            ssid=str(ap_name), security=3, key=str(ap_password)
        )
    except Exception:
        access_point.config(
            essid=str(ap_name),
            authmode=getattr(network, 'AUTH_WPA_WPA2_PSK', 3),
            password=str(ap_password)
        )
    return access_point


def _escape(value):
    value = str(value)
    for old, new in (
        ('&', '&amp;'), ('<', '&lt;'), ('>', '&gt;'),
        ('"', '&quot;'), ("'", '&#39;')
    ):
        value = value.replace(old, new)
    return value


def _constant_time_equal(left, right):
    left = str(left).encode()
    right = str(right).encode()
    different = len(left) ^ len(right)
    longest = max(len(left), len(right))
    for index in range(longest):
        left_value = left[index] if index < len(left) else 0
        right_value = right[index] if index < len(right) else 0
        different |= left_value ^ right_value
    return different == 0


def _session_id():
    try:
        return binascii.hexlify(os.urandom(24)).decode()
    except Exception:
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


def _cookies(headers):
    values = {}
    for item in headers.get('cookie', '').split(';'):
        if '=' in item:
            key, value = item.strip().split('=', 1)
            values[key] = value
    return values


def _login_page(message=''):
    notice = (
        '<p class="error" role="alert">' + _escape(message) + '</p>'
        if message else ''
    )
    return (
        '<!doctype html><html><head><meta name="viewport" '
        'content="width=device-width,initial-scale=1"><title>IoTMD recovery</title>'
        '<style>body{font-family:system-ui;margin:0;background:#f3f5f7;color:#17202a;'
        'min-height:100vh;display:grid;place-items:center;padding:1rem}main{width:min(25rem,100%);'
        'background:white;border:1px solid #d7dde5;border-radius:10px;padding:1.3rem;'
        'box-sizing:border-box}form,label{display:grid;gap:.5rem}input,button{font:inherit;'
        'padding:.65rem;border:1px solid #b9c2ce;border-radius:7px}button{background:#1769aa;'
        'color:white;font-weight:700}.error{color:#a32222}</style></head><body><main>'
        '<h1>IoTMD recovery</h1><p>IoT Modular Device</p>'
        '<p>Enter the dedicated recovery password.</p>' +
        notice + '<form action="/login" method="post"><label>Password'
        '<input name="password" type="password" autocomplete="current-password" '
        'required maxlength="63" autofocus></label><button>Sign in</button></form>'
        '</main></body></html>'
    )


def _recovery_page(reason, csrf, message=''):
    import app_update
    import firmware_update
    import universal_update
    import update_security

    app_state = app_update.update_status()
    firmware_state = firmware_update.update_status()
    universal_state = universal_update.update_status()
    previous = app_update.previous_slot()
    signing = update_security.signing_status()
    signed_ready = signing == 'required'
    app_action = ''
    app_status = app_state.get('status', 'idle')
    if app_status == 'ready':
        app_action = (
            '<form action="/activate-application" method="post"><input type="hidden" '
            'name="csrf" value="' + _escape(csrf) + '"><button>Activate staged application</button></form>'
            '<form action="/rollback-application" method="post"><input type="hidden" '
            'name="csrf" value="' + _escape(csrf) + '"><button class="secondary">Discard staged application</button></form>'
        )
    elif app_status in ('activating', 'trial', 'committing') or previous:
        label = 'Rollback pending application' if app_status != 'idle' else 'Boot previous application slot'
        app_action = (
            '<form action="/rollback-application" method="post"><input type="hidden" '
            'name="csrf" value="' + _escape(csrf) + '"><button>' + label + '</button></form>'
        )

    firmware_action = ''
    if universal_state.get('status') == 'ready':
        firmware_action = (
            '<form action="/activate-universal" method="post"><input type="hidden" '
            'name="csrf" value="' + _escape(csrf) + '"><button>Activate staged universal update</button></form>'
        )
        app_action = ''
    elif firmware_state.get('status') == 'ready':
        firmware_action = (
            '<form action="/activate-firmware" method="post"><input type="hidden" '
            'name="csrf" value="' + _escape(csrf) + '"><button>Activate staged core firmware</button></form>'
        )

    upload_controls = (
        '<p class="muted">Signed updates: ' + _escape(signing) + '</p>'
    )
    if signed_ready:
        upload_controls += (
            '<div class="upload"><input id="bundle" type="file" accept=".iotapp,.iotcore,.iotuni">'
            '<button id="upload" type="button">Upload and verify</button></div>'
            '<p id="upload-result" class="muted"></p>'
        )
    else:
        upload_controls += '<p class="error">USB recovery is required until an update signing key is provisioned.</p>'

    notice = (
        '<p class="notice" role="status">' + _escape(message) + '</p>'
        if message else ''
    )
    return (
        '<!doctype html><html><head><meta name="viewport" '
        'content="width=device-width,initial-scale=1"><title>IoTMD recovery</title>'
        '<style>:root{--line:#d7dde5;--blue:#1769aa;--red:#a32222}*{box-sizing:border-box}'
        'body{font-family:system-ui;margin:0;background:#f3f5f7;color:#17202a;padding:1rem}'
        'main{max-width:48rem;margin:auto}section{background:white;border:1px solid var(--line);'
        'border-radius:10px;padding:1rem;margin:1rem 0}h1{margin:.2rem 0}h2{font-size:1.05rem}'
        'form,.upload{display:flex;gap:.6rem;align-items:end;flex-wrap:wrap;margin:.6rem 0}'
        'label{display:grid;gap:.25rem;flex:1;min-width:12rem}input,button{font:inherit;padding:.6rem;'
        'border:1px solid #b9c2ce;border-radius:7px}button{background:var(--blue);color:white;'
        'font-weight:700;cursor:pointer}.secondary{background:white;color:var(--blue)}'
        '.muted{color:#667384}.error{color:var(--red)}.notice{padding:.6rem;background:#edf7ef;'
        'border:1px solid #a8d2b0;border-radius:7px}code{overflow-wrap:anywhere}</style></head>'
        '<body><main><h1>IoTMD core recovery</h1><p>IoT Modular Device</p>'
        '<p class="error">Normal application startup failed.</p>'
        '<section><h2>Failure</h2><code>' + _escape(reason) + '</code>' + notice + '</section>'
        '<section><h2>Wi-Fi credentials</h2><form action="/wifi" method="post">'
        '<input type="hidden" name="csrf" value="' + _escape(csrf) + '">'
        '<label>Network name<input name="ssid" required maxlength="32"></label>'
        '<label>Password<input name="password" type="password" required maxlength="64"></label>'
        '<button>Save and reboot</button></form></section>'
        '<section><h2>Application recovery</h2><p>Status: <strong>' + _escape(app_status) +
        '</strong>; previous slot: <strong>' + _escape(previous or 'none') + '</strong></p>' +
        app_action + '</section><section><h2>Core firmware recovery</h2><p>Status: <strong>' +
        _escape(firmware_state.get('status', 'idle')) + '</strong></p>' + firmware_action +
        upload_controls + '</section><section><h2>Restart</h2>'
        '<form action="/retry" method="post"><input type="hidden" name="csrf" value="' +
        _escape(csrf) + '"><button class="secondary">Retry normal application</button></form>'
        '</section></main><script>var csrf=' + repr(str(csrf)) + ';'
        'var button=document.getElementById("upload");if(button){button.onclick=function(){'
        'var input=document.getElementById("bundle"),out=document.getElementById("upload-result");'
        'if(!input.files.length){return;}var file=input.files[0],firmware=/\\.iotcore$/i.test(file.name),'
        'application=/\\.iotapp$/i.test(file.name),universal=/\\.iotuni$/i.test(file.name);'
        'if(!firmware&&!application&&!universal){out.textContent="Choose a .iotapp, .iotcore or .iotuni bundle.";return;}'
        'button.disabled=true;out.textContent="Uploading and verifying...";var request=new XMLHttpRequest();'
        'request.open("POST",universal?"/upload-universal":(firmware?"/upload-firmware":"/upload-application"),true);'
        'request.setRequestHeader("X-CSRF-Token",csrf);request.onload=function(){button.disabled=false;'
        'out.textContent=request.responseText||("HTTP "+request.status);if(request.status>=200&&request.status<300){location.reload();}};'
        'request.onerror=function(){button.disabled=false;out.textContent="Upload failed";};request.send(file);};}'
        '</script></body></html>'
    )


async def serve_core_recovery(
    ap_name,
    ap_password,
    portal_password_verifier,
    reason,
    clear_recovery,
    reset_device,
    port=RECOVERY_PORT,
    timeout_s=RECOVERY_TIMEOUT_S
):
    """Run a frozen, signed-update-only recovery console on a WPA access point."""
    if asyncio is None or network is None:
        raise RuntimeError('core recovery is unavailable')
    import app_update
    import firmware_update
    import universal_update
    import update_security

    access_point = _activate_access_point(ap_name, ap_password)
    session = _session_id()
    failures = 0

    async def send(writer, status, body, content_type='text/html; charset=utf-8', headers=()):
        payload = str(body).encode()
        head = (
            'HTTP/1.1 ' + status + '\r\nContent-Type: ' + content_type +
            '\r\nCache-Control: no-store\r\nConnection: close\r\n'
        )
        for name, value in http_support.add_security_headers(headers):
            head += str(name) + ': ' + str(value) + '\r\n'
        writer.write((head + 'Content-Length: ' + str(len(payload)) + '\r\n\r\n').encode() + payload)
        await writer.drain()

    async def read_form(reader, headers, maximum=4096):
        length = int(headers.get('content-length', '0') or 0)
        body = await http_support.read_exact_body(reader, length, maximum)
        return _form(body.decode())

    async def handle(reader, writer):
        nonlocal session, failures
        reboot = False
        clear_before_reboot = False
        try:
            line, headers = await http_support.read_request(reader)
            parts = line.decode().strip().split() if line else []
            method = parts[0] if len(parts) > 0 else ''
            path = parts[1].split('?', 1)[0] if len(parts) > 1 else ''

            authenticated = _cookies(headers).get('iotmd_recovery') == session
            if path == '/login' and method == 'GET':
                await send(writer, '200 OK', _login_page())
            elif path == '/login' and method == 'POST':
                values = await read_form(reader, headers, 1024)
                import credential_security
                if await credential_security.verify_password_async(
                    values.get('password', ''), portal_password_verifier
                ):
                    session = _session_id()
                    failures = 0
                    await send(
                        writer, '303 See Other', 'Redirecting', 'text/plain',
                        (('Location', '/'), ('Set-Cookie', 'iotmd_recovery=' + session + '; Path=/; HttpOnly; SameSite=Strict'))
                    )
                else:
                    failures += 1
                    await asyncio.sleep(min(2, failures * 0.25))
                    await send(writer, '401 Unauthorized', _login_page('Invalid recovery password.'))
            elif not authenticated:
                await send(writer, '401 Unauthorized', _login_page())
            elif method == 'GET':
                await send(writer, '200 OK', _recovery_page(reason, session))
            elif headers.get('x-csrf-token', '') != session:
                values = await read_form(reader, headers)
                if values.get('csrf', '') != session:
                    await send(writer, '403 Forbidden', 'Invalid CSRF token', 'text/plain')
                    return
                if path == '/wifi':
                    ssid = values.get('ssid', '')
                    password = values.get('password', '')
                    if not ssid or len(ssid) > 32 or len(password) > 64:
                        raise ValueError('invalid Wi-Fi credentials')
                    import credential_store
                    config = credential_store.load(require_provisioned=True)
                    config['wifi']['ssid'] = ssid
                    config['wifi']['password'] = password
                    credential_store.save(config)
                    reboot = True
                    clear_before_reboot = True
                    await send(writer, '200 OK', 'Wi-Fi credentials saved; rebooting', 'text/plain')
                elif path == '/activate-application':
                    app_update.configure_pending_update({})
                    reboot = True
                    clear_before_reboot = True
                    await send(writer, '200 OK', 'Application activation selected; rebooting', 'text/plain')
                elif path == '/rollback-application':
                    status = app_update.update_status().get('status', 'idle')
                    if status == 'ready':
                        app_update.discard_pending_update()
                    elif status in ('activating', 'trial', 'committing'):
                        app_update.rollback_update()
                    else:
                        app_update.rollback_to_previous()
                    reboot = True
                    clear_before_reboot = True
                    await send(writer, '200 OK', 'Application recovery selected; rebooting', 'text/plain')
                elif path == '/activate-firmware':
                    firmware_update.activate_pending()
                    reboot = True
                    clear_before_reboot = True
                    await send(writer, '200 OK', 'Core firmware activation selected; rebooting', 'text/plain')
                elif path == '/activate-universal':
                    universal_update.activate_pending()
                    reboot = True
                    clear_before_reboot = True
                    await send(writer, '200 OK', 'Universal update activation selected; rebooting', 'text/plain')
                elif path == '/retry':
                    reboot = True
                    clear_before_reboot = True
                    await send(writer, '200 OK', 'Retrying normal application', 'text/plain')
                else:
                    await send(writer, '404 Not Found', 'Not found', 'text/plain')
            elif path in ('/upload-application', '/upload-firmware', '/upload-universal'):
                if not update_security.signing_enabled():
                    await send(writer, '503 Service Unavailable', 'Signed recovery is not provisioned', 'text/plain')
                else:
                    length = int(headers.get('content-length', '0') or 0)
                    if path == '/upload-application':
                        state = await app_update.receive_bundle(reader, length, allow_protected=False)
                    elif path == '/upload-firmware':
                        state = await firmware_update.receive_bundle(reader, length)
                    else:
                        state = await universal_update.receive_bundle(reader, length)
                    await send(writer, '200 OK', 'Staged ' + str(state.get('version', '')), 'text/plain')
            else:
                await send(writer, '404 Not Found', 'Not found', 'text/plain')
        except Exception as exc:
            try:
                await send(writer, '400 Bad Request', 'Recovery request failed: ' + str(exc), 'text/plain')
            except Exception:
                pass
        finally:
            try:
                writer.close()
            except Exception:
                pass
        if reboot:
            await asyncio.sleep(1)
            if clear_before_reboot:
                clear_recovery()
            reset_device()

    server = await asyncio.start_server(handle, '0.0.0.0', int(port), backlog=2)
    remaining = max(60, int(timeout_s))
    while remaining > 0:
        await asyncio.sleep(1)
        remaining -= 1
    try:
        server.close()
    except Exception:
        pass
    clear_recovery()
    reset_device()
    return {'server': server, 'access_point': access_point, 'ip': access_point.ifconfig()[0]}

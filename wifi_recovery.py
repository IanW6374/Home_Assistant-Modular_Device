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


def _replace_secret_assignments(path, ssid, password):
    with open(path, 'r') as stream:
        lines = stream.readlines()
    replacements = {
        'wifi_ssid': repr(str(ssid)),
        'wifi_password': repr(str(password)),
    }
    found = set()
    output = []
    for line in lines:
        stripped = line.lstrip()
        replaced = False
        for name, value in replacements.items():
            if stripped.startswith(name) and '=' in stripped:
                indent = line[:len(line) - len(stripped)]
                output.append(indent + name + ' = ' + value + '\n')
                found.add(name)
                replaced = True
                break
        if not replaced:
            output.append(line)
    for name, value in replacements.items():
        if name not in found:
            output.append(name + ' = ' + value + '\n')
    temp = path + '.wifi-recovery-tmp'
    with open(temp, 'w') as stream:
        for line in output:
            stream.write(line)
    try:
        os.remove(path)
    except OSError:
        pass
    os.rename(temp, path)


def _page(message=''):
    notice = '<p>' + str(message) + '</p>' if message else ''
    return (
        '<!doctype html><html><head><meta name="viewport" content="width=device-width,initial-scale=1">'
        '<title>Device Wi-Fi recovery</title></head><body><main><h1>Wi-Fi recovery</h1>' +
        notice + '<form method="post"><label>Wi-Fi name <input name="ssid" required></label><br>'
        '<label>Password <input name="password" type="password" required></label><br>'
        '<button type="submit">Save and reboot</button></form></main></body></html>'
    )


async def start(ap_name, ap_password, secrets_path='secrets.py', port=80):
    if asyncio is None or network is None:
        raise RuntimeError('Wi-Fi recovery is unavailable')
    if len(str(ap_password)) < 8:
        raise ValueError('recovery access point password must be at least 8 characters')
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

    async def handle(reader, writer):
        try:
            line = await reader.readline()
            method = line.decode().split(' ', 1)[0] if line else ''
            headers = {}
            while True:
                line = await reader.readline()
                if not line or line == b'\r\n':
                    break
                text = line.decode().strip()
                if ':' in text:
                    key, value = text.split(':', 1)
                    headers[key.lower()] = value.strip()
            body = b''
            if method == 'POST':
                length = int(headers.get('content-length', '0') or 0)
                body = bytearray()
                while len(body) < length:
                    chunk = await reader.read(length - len(body))
                    if not chunk:
                        raise ValueError('credential form ended early')
                    body.extend(chunk)
                values = _form(body.decode())
                if (
                    values.get('ssid') and values.get('password') and
                    len(values['ssid']) <= 32 and len(values['password']) <= 64
                ):
                    _replace_secret_assignments(
                        secrets_path, values['ssid'], values['password']
                    )
                    page = _page('Credentials saved. Rebooting…')
                    status = '200 OK'
                else:
                    page = _page('Enter an SSID up to 32 characters and a password up to 64 characters.')
                    status = '400 Bad Request'
            else:
                page = _page()
                status = '200 OK'
            payload = page.encode()
            writer.write(
                ('HTTP/1.1 ' + status + '\r\nContent-Type: text/html; charset=utf-8\r\n'
                 'Connection: close\r\nContent-Length: ' + str(len(payload)) + '\r\n\r\n').encode() + payload
            )
            await writer.drain()
            if method == 'POST' and status == '200 OK':
                await asyncio.sleep(1)
                try:
                    import machine
                    machine.reset()
                except Exception:
                    pass
        finally:
            try:
                writer.close()
            except Exception:
                pass

    server = await asyncio.start_server(handle, '0.0.0.0', int(port), backlog=2)
    return {'server': server, 'access_point': access_point, 'ip': access_point.ifconfig()[0]}

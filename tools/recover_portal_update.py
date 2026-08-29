#!/usr/bin/env python3
"""Recover an IoT-MD portal whose authenticated HTML renderer is broken.

Affected portals can still authenticate and serve JSON endpoints even though
personalising an HTML response raises on MicroPython.  This utility reuses
those authenticated endpoints to stage and activate a signed IoT-MD bundle.
"""

import argparse
import getpass
import hashlib
import http.cookiejar
import json
import re
import ssl
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path


CHUNK_BYTES = 64 * 1024
CSRF_PATTERN = re.compile(r'name="csrf"\s+value="([^"]+)"')


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, file_pointer, code, message, headers,
                         new_url):
        return None


def response(opener, request, timeout=30):
    try:
        with opener.open(request, timeout=timeout) as result:
            return result.status, result.read()
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read()


def request(url, data=None, headers=None, method=None):
    return urllib.request.Request(
        url, data=data, headers=headers or {}, method=method
    )


def find_csrf(value):
    if isinstance(value, dict):
        values = value.values()
    elif isinstance(value, list):
        values = value
    else:
        match = CSRF_PATTERN.search(str(value))
        return match.group(1) if match else ''
    for item in values:
        token = find_csrf(item)
        if token:
            return token
    return ''


def json_request(opener, base_url, path, csrf='', payload=None, timeout=30):
    headers = {'Accept': 'application/json'}
    data = None
    method = 'GET'
    if payload is not None:
        data = json.dumps(payload, separators=(',', ':')).encode()
        headers['Content-Type'] = 'application/json'
        headers['X-CSRF-Token'] = csrf
        method = 'POST'
    status, body = response(
        opener, request(base_url + path, data, headers, method), timeout
    )
    if status < 200 or status >= 300:
        raise RuntimeError(
            path + ' returned HTTP ' + str(status) + ': ' +
            body.decode(errors='replace')[:300]
        )
    return json.loads(body.decode()) if body else {}


def upload(opener, base_url, bundle, csrf):
    digest = hashlib.sha256(bundle.read_bytes()).hexdigest()
    total = bundle.stat().st_size
    identifier = digest[:24] + '-' + str(total)
    state = json_request(
        opener, base_url, '/resumable-upload-begin', csrf, {
            'id': identifier,
            'kind': 'application',
            'total_bytes': total,
            'sha256': digest,
        }
    )
    offset = int(state.get('received_bytes', 0))
    with bundle.open('rb') as stream:
        stream.seek(offset)
        while offset < total:
            chunk = stream.read(min(CHUNK_BYTES, total - offset))
            status, body = response(opener, request(
                base_url + '/resumable-upload-chunk?' + urllib.parse.urlencode({
                    'id': identifier, 'offset': offset
                }),
                chunk,
                {
                    'Content-Type': 'application/octet-stream',
                    'X-CSRF-Token': csrf,
                },
                'POST'
            ), 60)
            if status < 200 or status >= 300:
                raise RuntimeError(
                    'chunk upload returned HTTP ' + str(status) + ': ' +
                    body.decode(errors='replace')[:300]
                )
            state = json.loads(body.decode())
            offset = int(state.get('received_bytes', offset + len(chunk)))
            print('\rUploading: {:3d}%'.format(int(offset * 100 / total)), end='', flush=True)
    print()
    status, body = response(opener, request(
        base_url + '/resumable-upload-complete',
        json.dumps({'id': identifier}).encode(),
        {'Content-Type': 'application/json', 'X-CSRF-Token': csrf},
        'POST'
    ), 180)
    if status not in (200, 202):
        raise RuntimeError(
            'verification returned HTTP ' + str(status) + ': ' +
            body.decode(errors='replace')[:300]
        )
    return identifier


def wait_for_verification(opener, base_url, identifier):
    deadline = time.monotonic() + 180
    while time.monotonic() < deadline:
        state = json_request(
            opener, base_url,
            '/update-progress?' + urllib.parse.urlencode({'id': identifier})
        )
        phase = str(state.get('phase', ''))
        percent = int(state.get('percent', 0) or 0)
        print('\rVerification: {} {}%'.format(phase or 'waiting', percent),
              end='', flush=True)
        if phase == 'complete':
            print()
            return
        if phase == 'failed':
            print()
            raise RuntimeError(str(state.get('message', 'verification failed')))
        time.sleep(1)
    raise RuntimeError('timed out waiting for update verification')


def main():
    parser = argparse.ArgumentParser(
        description='Install an IoT-MD update through the authenticated portal recovery endpoints'
    )
    parser.add_argument('portal_url', help='for example https://iot-md-001.local:8443')
    parser.add_argument('bundle', type=Path, help='signed .iotapp bundle')
    parser.add_argument('--username', default='admin')
    args = parser.parse_args()

    base_url = args.portal_url.rstrip('/')
    parsed = urllib.parse.urlsplit(base_url)
    if parsed.scheme not in ('http', 'https') or not parsed.hostname:
        parser.error('portal_url must be an http(s) device URL')
    if args.bundle.suffix.lower() != '.iotapp' or not args.bundle.is_file():
        parser.error('bundle must be an existing .iotapp file')

    context = ssl.create_default_context()
    if parsed.scheme == 'https':
        # Devices commonly use a private or self-signed local certificate.
        context.check_hostname = False
        context.verify_mode = ssl.CERT_NONE
    cookies = http.cookiejar.CookieJar()
    opener = urllib.request.build_opener(
        urllib.request.HTTPSHandler(context=context),
        urllib.request.HTTPCookieProcessor(cookies),
        NoRedirect(),
    )

    password = getpass.getpass('Portal password for ' + args.username + ': ')
    login = urllib.parse.urlencode({
        'username': args.username, 'password': password
    }).encode()
    password = ''
    status, body = response(opener, request(
        base_url + '/login', login,
        {'Content-Type': 'application/x-www-form-urlencoded'}, 'POST'
    ))
    if status not in (302, 303):
        raise RuntimeError(
            'login failed with HTTP ' + str(status) + ': ' +
            body.decode(errors='replace')[:200]
        )

    csrf = ''
    for path in ('/partials', '/api/module-diagnostics'):
        try:
            csrf = find_csrf(json_request(opener, base_url, path))
        except (RuntimeError, ValueError, json.JSONDecodeError):
            continue
        if csrf:
            break
    if not csrf:
        raise RuntimeError('authenticated JSON endpoints did not expose a CSRF token')

    identifier = upload(opener, base_url, args.bundle, csrf)
    wait_for_verification(opener, base_url, identifier)
    activation = urllib.parse.urlencode({'csrf': csrf}).encode()
    status, body = response(opener, request(
        base_url + '/activate-update', activation,
        {'Content-Type': 'application/x-www-form-urlencoded'}, 'POST'
    ), 30)
    # Affected versions schedule activation before broken personalisation runs,
    # so HTTP 500 is expected and safe at this final step.
    if status not in (200, 202, 302, 303, 500):
        raise RuntimeError(
            'activation returned HTTP ' + str(status) + ': ' +
            body.decode(errors='replace')[:300]
        )
    print('Update staged and activation requested. Wait 30 seconds, then reload the portal.')


if __name__ == '__main__':
    try:
        main()
    except (OSError, RuntimeError, ValueError) as exc:
        raise SystemExit('Recovery failed: ' + str(exc))

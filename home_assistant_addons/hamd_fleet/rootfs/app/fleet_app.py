#!/usr/bin/env python3
"""Small ingress-ready Home Assistant add-on for managing HAMD v2 devices."""

import hashlib
import json
import os
import ssl
import threading
import time
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric.utils import decode_dss_signature


DATA_DIRECTORY = Path(os.environ.get('HAMD_FLEET_DATA', '/data'))
OPTIONS_PATH = DATA_DIRECTORY / 'options.json'
STATE_PATH = DATA_DIRECTORY / 'fleet.json'
SIGNING_KEY_PATH = DATA_DIRECTORY / 'fleet-signing-key.pem'
PUBLIC_KEY_PATH = DATA_DIRECTORY / 'fleet-verification-key.bin'
P256_ORDER = int(
    'ffffffff00000000ffffffffffffffffbce6faada7179e84f3b9cac2fc632551', 16
)


def atomic_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + '.tmp')
    temporary.write_text(json.dumps(value, separators=(',', ':')))
    os.replace(temporary, path)


def bounded_text(value, maximum=256):
    return str(value or '')[:maximum]


def policy_message(policy):
    maintenance = policy.get('maintenance', {}) or {}
    updates = policy.get('updates', {}) or {}
    telemetry = policy.get('telemetry', {}) or {}
    fields = [
        'fleet-policy', str(policy.get('format_version', 1)), 'esp32-s3',
        str(policy.get('policy_sequence', '')), str(policy.get('issued_at', '')),
        str(policy.get('not_before', '')), str(policy.get('expires_at', '')),
        str(policy.get('target_device', '')), str(policy.get('target_cohort', '')),
        ','.join(str(value) for value in maintenance.get('weekdays', ()) or ()),
        str(maintenance.get('start_minute', '')),
        str(maintenance.get('duration_minutes', '')),
        str(updates.get('channel', '')),
        str(bool(updates.get('automatic_download', False))),
        str(bool(updates.get('automatic_activation', False))),
        str(updates.get('maximum_consecutive_failures', '')),
        str(bool(telemetry.get('enabled', False))),
        str(telemetry.get('minimum_interval_s', '')),
        ','.join(str(value) for value in telemetry.get('severities', ()) or ()),
    ]
    commands = policy.get('commands', ()) or ()
    fields.append(str(len(commands)))
    for command in commands:
        fields.extend((
            str(command.get('id', '')), str(command.get('action', '')),
            str(command.get('release_sequence', '')),
        ))
    return ('\n'.join(fields) + '\n').encode()


class PolicySigner:
    def __init__(self, private_path=SIGNING_KEY_PATH, public_path=PUBLIC_KEY_PATH):
        self.private_path = Path(private_path)
        self.public_path = Path(public_path)
        self.private_key = self._load_or_create()

    def _load_or_create(self):
        if self.private_path.exists():
            return serialization.load_pem_private_key(
                self.private_path.read_bytes(), password=None
            )
        self.private_path.parent.mkdir(parents=True, exist_ok=True)
        private = ec.generate_private_key(ec.SECP256R1())
        self.private_path.write_bytes(private.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        ))
        os.chmod(self.private_path, 0o600)
        numbers = private.public_key().public_numbers()
        self.public_path.write_bytes(
            numbers.x.to_bytes(32, 'big') + numbers.y.to_bytes(32, 'big')
        )
        os.chmod(self.public_path, 0o644)
        return private

    def sign(self, policy):
        value = json.loads(json.dumps(policy))
        value.pop('signature', None)
        value['target_board'] = 'esp32-s3'
        value['signature_scheme'] = 'ecdsa-p256-sha256'
        der = self.private_key.sign(policy_message(value), ec.ECDSA(hashes.SHA256()))
        r, s = decode_dss_signature(der)
        if s > P256_ORDER // 2:
            s = P256_ORDER - s
        value['signature'] = (r.to_bytes(32, 'big') + s.to_bytes(32, 'big')).hex()
        return value


class FleetStore:
    def __init__(self, path=STATE_PATH, event_retention=5000):
        self.path = Path(path)
        self.event_retention = max(100, int(event_retention))
        self.lock = threading.RLock()
        self.data = self._load()

    def _empty(self):
        return {
            'format_version': 1, 'devices': {}, 'events': [], 'rollouts': {},
            'next_policy_sequence': 1,
        }

    def _load(self):
        try:
            value = json.loads(self.path.read_text())
            return value if value.get('format_version') == 1 else self._empty()
        except Exception:
            return self._empty()

    def save(self):
        with self.lock:
            self.data['events'] = self.data['events'][-self.event_retention:]
            atomic_json(self.path, self.data)

    def register(self, record):
        identifier = bounded_text(record.get('id'), 64)
        if not identifier:
            raise ValueError('device id is required')
        host = bounded_text(record.get('host'), 253)
        if not host:
            raise ValueError('device host is required')
        port = int(record.get('port', 8444))
        if not 1 <= port <= 65535:
            raise ValueError('device port is invalid')
        value = {
            'id': identifier, 'name': bounded_text(record.get('name') or identifier, 64),
            'host': host, 'port': port,
            'ca_path': bounded_text(record.get('ca_path'), 512),
            'cert_path': bounded_text(record.get('cert_path'), 512),
            'key_path': bounded_text(record.get('key_path'), 512),
            'cohort': bounded_text(record.get('cohort') or 'default', 64),
            'enabled': bool(record.get('enabled', True)),
            'inventory': {}, 'health': {}, 'fleet': {}, 'last_error': '',
            'last_seen': 0, 'event_cursor': 0,
        }
        with self.lock:
            previous = self.data['devices'].get(identifier, {})
            for key in ('inventory', 'health', 'fleet', 'last_seen', 'event_cursor'):
                value[key] = previous.get(key, value[key])
            self.data['devices'][identifier] = value
            self.save()
        return self.public_device(value)

    def public_device(self, value):
        return {
            key: item for key, item in value.items()
            if key not in ('ca_path', 'cert_path', 'key_path')
        }

    def list_devices(self):
        with self.lock:
            return [
                self.public_device(value)
                for _, value in sorted(self.data['devices'].items())
            ]

    def next_policy_sequence(self):
        with self.lock:
            value = int(self.data.get('next_policy_sequence', 1))
            self.data['next_policy_sequence'] = value + 1
            self.save()
            return value

    def create_rollout(self, request):
        identifier = bounded_text(
            request.get('id') or ('rollout-' + os.urandom(6).hex()), 64
        )
        if any(character not in 'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_' for character in identifier):
            raise ValueError('rollout id contains unsupported characters')
        cohorts = [bounded_text(value, 64) for value in request.get('cohorts', ())]
        cohorts = [value for value in cohorts if value]
        if not cohorts or len(cohorts) > 16:
            raise ValueError('rollout requires 1 to 16 ordered cohorts')
        maximum_failures = int(request.get('maximum_failures', 1))
        if not 1 <= maximum_failures <= 100:
            raise ValueError('rollout failure threshold is invalid')
        rollout = {
            'id': identifier, 'release_sequence': int(request.get('release_sequence', 0)),
            'channel': bounded_text(request.get('channel') or 'alpha', 16),
            'cohorts': cohorts, 'cohort_index': 0, 'status': 'active',
            'maximum_failures': maximum_failures, 'successes': 0, 'failures': 0,
            'results': {}, 'created_at': int(time.time()),
        }
        if rollout['release_sequence'] <= 0:
            raise ValueError('rollout release sequence must be positive')
        with self.lock:
            if identifier in self.data['rollouts']:
                raise ValueError('rollout id already exists')
            self.data['rollouts'][identifier] = rollout
            self.save()
        return dict(rollout)

    def record_rollout_result(self, identifier, device_id, result, detail=''):
        with self.lock:
            rollout = self.data['rollouts'].get(str(identifier))
            if not rollout:
                raise ValueError('rollout does not exist')
            if rollout['status'] not in ('active', 'stopped'):
                raise ValueError('rollout is already complete')
            device = self.data['devices'].get(str(device_id))
            if not device:
                raise ValueError('device is not registered')
            expected = rollout['cohorts'][rollout['cohort_index']]
            if device.get('cohort') != expected:
                raise ValueError('device is not in the active rollout cohort')
            normalized = 'complete' if str(result) == 'complete' else 'failed'
            previous = rollout['results'].get(str(device_id))
            if previous:
                rollout[
                    'successes' if previous['result'] == 'complete' else 'failures'
                ] -= 1
            rollout['results'][str(device_id)] = {
                'result': normalized, 'detail': bounded_text(detail, 256),
                'recorded_at': int(time.time()),
            }
            rollout[('successes' if normalized == 'complete' else 'failures')] += 1
            if rollout['failures'] >= rollout['maximum_failures']:
                rollout['status'] = 'stopped'
            self.save()
            return dict(rollout)

    def advance_rollout(self, identifier):
        with self.lock:
            rollout = self.data['rollouts'].get(str(identifier))
            if not rollout:
                raise ValueError('rollout does not exist')
            if rollout['status'] == 'stopped':
                raise ValueError('rollout is stopped at its failure threshold')
            cohort = rollout['cohorts'][rollout['cohort_index']]
            targets = [
                value['id'] for value in self.data['devices'].values()
                if value.get('enabled') and value.get('cohort') == cohort
            ]
            incomplete = [value for value in targets if value not in rollout['results']]
            failed = [
                value for value in targets
                if rollout['results'].get(value, {}).get('result') == 'failed'
            ]
            if incomplete:
                raise ValueError('active cohort still has incomplete devices')
            if failed:
                raise ValueError('active cohort contains failed devices')
            if rollout['cohort_index'] + 1 >= len(rollout['cohorts']):
                rollout['status'] = 'complete'
            else:
                rollout['cohort_index'] += 1
            self.save()
            return dict(rollout)


class DeviceClient:
    def __init__(self, record, timeout=10):
        self.record = record
        self.timeout = int(timeout)

    def _context(self):
        context = ssl.create_default_context(cafile=self.record['ca_path'])
        context.load_cert_chain(self.record['cert_path'], self.record['key_path'])
        context.minimum_version = ssl.TLSVersion.TLSv1_2
        return context

    def request(self, path, method='GET', payload=None):
        body = None if payload is None else json.dumps(payload).encode()
        request = urllib.request.Request(
            'https://' + self.record['host'] + ':' + str(self.record['port']) + path,
            data=body, method=method,
            headers={'Content-Type': 'application/json', 'Accept': 'application/json'},
        )
        with urllib.request.urlopen(
            request, context=self._context(), timeout=self.timeout
        ) as response:
            return json.loads(response.read())


class FleetController:
    def __init__(self, store, signer, timeout=10):
        self.store = store
        self.signer = signer
        self.timeout = int(timeout)

    def poll_device(self, identifier):
        with self.store.lock:
            record = self.store.data['devices'][identifier]
            if not record.get('enabled'):
                return
            cursor = int(record.get('event_cursor', 0))
        client = DeviceClient(record, self.timeout)
        try:
            inventory = client.request('/api/v2/device/inventory')
            health = client.request('/api/v2/health')
            events = client.request('/api/v2/events?cursor=' + str(cursor) + '&limit=64')
        except Exception as exc:
            with self.store.lock:
                record['last_error'] = bounded_text(exc, 256)
                self.store.save()
            return
        with self.store.lock:
            record['inventory'] = inventory
            record['health'] = health
            record['fleet'] = inventory.get('fleet') or {}
            record['last_seen'] = int(time.time())
            record['last_error'] = ''
            record['event_cursor'] = int(events.get('cursor', cursor))
            for event in events.get('events', ()):
                self.store.data['events'].append({
                    'device_id': identifier, 'event': event,
                    'received_at': int(time.time()),
                })
            self.store.save()

    def apply_policy(self, request):
        now = int(time.time())
        target = bounded_text(request.get('device_id'), 64)
        with self.store.lock:
            record = self.store.data['devices'].get(target)
        if not record:
            raise ValueError('device is not registered')
        command = request.get('command') or None
        commands = [] if not command else [{
            'id': bounded_text(command.get('id') or os.urandom(8).hex(), 64),
            'action': command.get('action', 'check-update'),
            'release_sequence': int(command.get('release_sequence', 0)),
        }]
        policy = {
            'format_version': 1,
            'target_board': 'esp32-s3',
            'policy_sequence': self.store.next_policy_sequence(),
            'issued_at': now - 5, 'not_before': now - 5,
            'expires_at': now + int(request.get('valid_for_s', 86400)),
            'target_device': target, 'target_cohort': '',
            'maintenance': {
                'weekdays': request.get('weekdays', [0, 1, 2, 3, 4, 5, 6]),
                'start_minute': int(request.get('start_minute', 120)),
                'duration_minutes': int(request.get('duration_minutes', 120)),
            },
            'updates': {
                'channel': request.get('channel', 'alpha'),
                'automatic_download': bool(request.get('automatic_download', False)),
                'automatic_activation': bool(request.get('automatic_activation', False)),
                'maximum_consecutive_failures': int(request.get('maximum_failures', 2)),
            },
            'telemetry': {
                'enabled': bool(request.get('telemetry_enabled', True)),
                'minimum_interval_s': int(request.get('telemetry_interval_s', 60)),
                'severities': request.get(
                    'severities', ['warning', 'error', 'critical']
                ),
            },
            'commands': commands,
        }
        signed = self.signer.sign(policy)
        result = DeviceClient(record, self.timeout).request(
            '/api/v2/fleet/policy', 'POST', signed
        )
        self.poll_device(target)
        return result

    def dispatch_rollout(self, identifier):
        with self.store.lock:
            rollout = self.store.data['rollouts'].get(str(identifier))
            if not rollout:
                raise ValueError('rollout does not exist')
            if rollout['status'] != 'active':
                raise ValueError('rollout is not active')
            cohort = rollout['cohorts'][rollout['cohort_index']]
            targets = [
                value['id'] for value in self.store.data['devices'].values()
                if value.get('enabled') and value.get('cohort') == cohort
            ]
        results = {}
        for device_id in targets:
            try:
                results[device_id] = self.apply_policy({
                    'device_id': device_id, 'channel': rollout['channel'],
                    'automatic_download': True, 'automatic_activation': True,
                    'maximum_failures': rollout['maximum_failures'],
                    'command': {
                        'action': 'download-update',
                        'release_sequence': rollout['release_sequence'],
                    },
                })
            except Exception as exc:
                results[device_id] = {'error': bounded_text(exc)}
                self.store.record_rollout_result(
                    identifier, device_id, 'failed', str(exc)
                )
                if self.store.data['rollouts'][identifier]['status'] == 'stopped':
                    break
        return {'rollout': self.store.data['rollouts'][identifier], 'dispatch': results}


HTML = '''<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width">
<title>HAMD Fleet</title><style>
:root{font-family:system-ui;color:#172830;background:#edf3f5}body{margin:0;padding:24px}main{max-width:1400px;margin:auto}
h1{font-size:2.4rem}.cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(280px,1fr));gap:16px}.card{background:white;border:1px solid #cedde2;border-radius:16px;padding:18px;box-shadow:0 5px 18px #17313b12}
.ok{color:#14864a}.bad{color:#b82b2b}.muted{color:#60727b}button{background:#087f8c;color:white;border:0;border-radius:9px;padding:10px 14px;font-weight:700}input,select{width:100%;box-sizing:border-box;padding:9px;margin:4px 0 10px;border:1px solid #b9cbd1;border-radius:8px}label{font-weight:650}.row{display:flex;gap:12px;align-items:center;justify-content:space-between}.events{max-height:300px;overflow:auto}code{font-size:.82rem}@media(max-width:600px){body{padding:12px}.row{align-items:stretch;flex-direction:column}}
</style></head><body><main><div class="row"><div><p class="muted">HOME ASSISTANT ADD-ON</p><h1>HAMD Fleet</h1></div><button onclick="refresh()">Refresh</button></div>
<section><h2>Devices</h2><div id="devices" class="cards"></div></section>
<section class="card"><h2>Register device</h2><form id="register"><div class="cards"><label>ID<input name="id" required></label><label>Name<input name="name"></label><label>Host<input name="host" required></label><label>Port<input name="port" type="number" value="8444"></label><label>CA path<input name="ca_path" value="/ssl/hamd-ca.pem" required></label><label>Client certificate path<input name="cert_path" value="/ssl/hamd-fleet.pem" required></label><label>Client key path<input name="key_path" value="/ssl/hamd-fleet-key.pem" required></label><label>Cohort<input name="cohort" value="default"></label></div><button>Register</button></form></section>
<section class="card"><h2>Policy / command</h2><form id="policy"><div class="cards"><label>Device<select id="policy-device" name="device_id"></select></label><label>Channel<select name="channel"><option>alpha</option><option>beta</option><option>stable</option></select></label><label>Command<select name="action"><option value="">No command</option><option>check-update</option><option>download-update</option><option>activate-update</option><option>rollback</option></select></label><label>Start minute<input name="start_minute" type="number" value="120"></label><label>Duration minutes<input name="duration_minutes" type="number" value="120"></label><label>Maximum failures<input name="maximum_failures" type="number" value="2"></label></div><button>Sign and apply policy</button></form><pre id="result"></pre></section>
<section class="card"><h2>Staged rollout</h2><form id="rollout"><div class="cards"><label>Release sequence<input name="release_sequence" type="number" min="1" required></label><label>Ordered cohorts<input name="cohorts" value="canary,main" required></label><label>Failure stop threshold<input name="maximum_failures" type="number" min="1" value="1"></label><label>Channel<select name="channel"><option>alpha</option><option>beta</option><option>stable</option></select></label></div><button>Create rollout</button></form><div id="rollouts" class="cards"></div></section>
<section class="card"><h2>Fleet verification key</h2><p>Provision this public key on each enrolled device. It is independent from update signing.</p><a href="api/fleet-public-key">Download raw public key</a></section>
</main><script>
async function api(path,options){let r=await fetch(path,options);if(!r.ok)throw new Error(await r.text());return r.json()}function esc(v){return String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]))}
async function refresh(){let data=await api('api/devices'),rolloutData=await api('api/rollouts'),box=document.getElementById('devices'),select=document.getElementById('policy-device'),rollouts=document.getElementById('rollouts');box.innerHTML='';select.innerHTML='';rollouts.innerHTML='';for(let d of data.devices){let seen=d.last_seen?new Date(d.last_seen*1000).toLocaleString():'Never',healthy=!d.last_error;box.innerHTML+=`<article class="card"><div class="row"><strong>${esc(d.name)}</strong><span class="${healthy?'ok':'bad'}">${healthy?'Healthy':'Unavailable'}</span></div><p><code>${esc(d.id)}</code></p><p>${esc(d.host)}:${d.port}</p><p class="muted">Last seen: ${esc(seen)}</p><p class="bad">${esc(d.last_error)}</p><p>Application: ${esc(d.inventory?.device?.application_version||'unknown')}</p><p>Cohort: ${esc(d.cohort)}</p></article>`;select.innerHTML+=`<option value="${esc(d.id)}">${esc(d.name)}</option>`}for(let r of rolloutData.rollouts){let cohort=r.cohorts[r.cohort_index]||'complete';rollouts.innerHTML+=`<article class="card"><div class="row"><strong>${esc(r.id)}</strong><span class="${r.status==='stopped'?'bad':'ok'}">${esc(r.status)}</span></div><p>Release ${esc(r.release_sequence)} · ${esc(cohort)}</p><p>${esc(r.successes)} complete / ${esc(r.failures)} failed</p><button onclick="rolloutAction('${esc(r.id)}','dispatch')">Dispatch active cohort</button> <button onclick="rolloutAction('${esc(r.id)}','advance')">Advance</button></article>`}}document.getElementById('register').onsubmit=async e=>{e.preventDefault();let o=Object.fromEntries(new FormData(e.target));o.port=Number(o.port);await api('api/devices',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(o)});refresh()};document.getElementById('policy').onsubmit=async e=>{e.preventDefault();let o=Object.fromEntries(new FormData(e.target));o.start_minute=Number(o.start_minute);o.duration_minutes=Number(o.duration_minutes);o.maximum_failures=Number(o.maximum_failures);if(o.action)o.command={action:o.action,release_sequence:0};delete o.action;try{document.getElementById('result').textContent=JSON.stringify(await api('api/policy',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(o)}),null,2)}catch(x){document.getElementById('result').textContent=x.message}};document.getElementById('rollout').onsubmit=async e=>{e.preventDefault();let o=Object.fromEntries(new FormData(e.target));o.release_sequence=Number(o.release_sequence);o.maximum_failures=Number(o.maximum_failures);o.cohorts=o.cohorts.split(',').map(x=>x.trim()).filter(Boolean);await api('api/rollouts',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(o)});refresh()};async function rolloutAction(id,action){try{await api('api/rollouts/'+action,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({id:id})});refresh()}catch(x){document.getElementById('result').textContent=x.message}}refresh();setInterval(refresh,60000)
</script></body></html>'''


def read_options():
    try:
        return json.loads(OPTIONS_PATH.read_text())
    except Exception:
        return {}


OPTIONS = read_options()
STORE = FleetStore(event_retention=int(OPTIONS.get('event_retention', 5000)))
SIGNER = PolicySigner()
CONTROLLER = FleetController(
    STORE, SIGNER, timeout=int(OPTIONS.get('request_timeout_s', 10))
)


class Handler(BaseHTTPRequestHandler):
    server_version = 'HAMDFleet/2-alpha'

    def _json(self, status, value):
        body = json.dumps(value).encode()
        self.send_response(status)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Cache-Control', 'no-store')
        self.end_headers()
        self.wfile.write(body)

    def _body(self):
        length = int(self.headers.get('Content-Length', '0') or 0)
        if length <= 0 or length > 131072:
            raise ValueError('request body size is invalid')
        value = json.loads(self.rfile.read(length))
        if not isinstance(value, dict):
            raise ValueError('request body must be an object')
        return value

    def do_GET(self):
        path = urlparse(self.path).path.rstrip('/') or '/'
        try:
            if path == '/':
                body = HTML.encode()
                self.send_response(200)
                self.send_header('Content-Type', 'text/html; charset=utf-8')
                self.send_header('Content-Length', str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            elif path == '/api/devices':
                self._json(200, {'devices': STORE.list_devices()})
            elif path == '/api/events':
                self._json(200, {'events': STORE.data['events'][-500:]})
            elif path == '/api/rollouts':
                self._json(200, {'rollouts': list(STORE.data['rollouts'].values())})
            elif path == '/api/fleet-public-key':
                body = PUBLIC_KEY_PATH.read_bytes()
                self.send_response(200)
                self.send_header('Content-Type', 'application/octet-stream')
                self.send_header('Content-Disposition', 'attachment; filename="fleet-verification-key.bin"')
                self.send_header('Content-Length', str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            elif path == '/health':
                self._json(200, {'status': 'ok', 'devices': len(STORE.data['devices'])})
            else:
                self._json(404, {'error': 'not found'})
        except Exception as exc:
            self._json(500, {'error': bounded_text(exc)})

    def do_POST(self):
        path = urlparse(self.path).path.rstrip('/')
        try:
            request = self._body()
            if path == '/api/devices':
                result = STORE.register(request)
                threading.Thread(
                    target=CONTROLLER.poll_device, args=(result['id'],), daemon=True
                ).start()
                self._json(201, result)
            elif path == '/api/policy':
                self._json(202, CONTROLLER.apply_policy(request))
            elif path == '/api/poll':
                CONTROLLER.poll_device(request.get('device_id', ''))
                self._json(200, {'status': 'complete'})
            elif path == '/api/rollouts':
                self._json(201, STORE.create_rollout(request))
            elif path == '/api/rollouts/dispatch':
                self._json(202, CONTROLLER.dispatch_rollout(request.get('id', '')))
            elif path == '/api/rollouts/result':
                self._json(200, STORE.record_rollout_result(
                    request.get('id', ''), request.get('device_id', ''),
                    request.get('result', ''), request.get('detail', '')
                ))
            elif path == '/api/rollouts/advance':
                self._json(200, STORE.advance_rollout(request.get('id', '')))
            else:
                self._json(404, {'error': 'not found'})
        except (ValueError, KeyError) as exc:
            self._json(400, {'error': bounded_text(exc)})
        except urllib.error.HTTPError as exc:
            self._json(exc.code, {'error': bounded_text(exc.read().decode())})
        except Exception as exc:
            self._json(502, {'error': bounded_text(exc)})

    def log_message(self, pattern, *args):
        print('%s - %s' % (self.address_string(), pattern % args), flush=True)


def poll_loop():
    interval = max(10, int(OPTIONS.get('poll_interval_s', 60)))
    while True:
        for identifier in list(STORE.data['devices']):
            CONTROLLER.poll_device(identifier)
        time.sleep(interval)


def main():
    threading.Thread(target=poll_loop, daemon=True).start()
    ThreadingHTTPServer(('0.0.0.0', 8099), Handler).serve_forever()


if __name__ == '__main__':
    main()

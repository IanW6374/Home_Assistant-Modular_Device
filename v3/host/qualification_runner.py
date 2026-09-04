#!/usr/bin/env python3
"""Run and persist an honest v3 operational qualification campaign."""

import argparse
import json
import os
from pathlib import Path
import ssl
import sys
import time
import urllib.request

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from v3.runtime.iotmd_next.qualification import OperationalQualification


class FileNamespace:
    """Host equivalent of a transactional namespace for qualification state."""

    def __init__(self, path):
        self.path = Path(path)
        self.generation = 0
        self.payload = b''
        if self.path.exists():
            value = json.loads(self.path.read_text())
            if set(value) != {'generation', 'payload'}:
                raise ValueError('qualification state file is invalid')
            self.generation = int(value['generation'])
            self.payload = str(value['payload']).encode()

    def snapshot(self):
        return self.generation, self.payload

    def commit(self, generation, payload):
        if generation != self.generation:
            raise RuntimeError('qualification state generation changed')
        value = {
            'generation': generation + 1,
            'payload': bytes(payload).decode(),
        }
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(self.path.suffix + '.tmp')
        temporary.write_text(json.dumps(value, sort_keys=True) + '\n')
        os.replace(temporary, self.path)
        self.generation += 1
        self.payload = bytes(payload)
        return self.generation


def _nested(value, path, default=None):
    for part in str(path).split('.'):
        if not isinstance(value, dict) or part not in value:
            return default
        value = value[part]
    return value


class HTTPProbe:
    def __init__(self, url, ca_file, cert_file, key_file, timeout=10,
                 health_path='health.state',
                 storage_path='health.storage_free_bytes'):
        context = ssl.create_default_context(cafile=ca_file)
        if cert_file or key_file:
            if not cert_file or not key_file:
                raise ValueError('both client certificate and key are required')
            context.load_cert_chain(cert_file, key_file)
        self._url = str(url)
        self._context = context
        self._timeout = int(timeout)
        self._health_path = health_path
        self._storage_path = storage_path

    def __call__(self):
        request = urllib.request.Request(
            self._url, headers={'Accept': 'application/json'}
        )
        with urllib.request.urlopen(
                request, context=self._context,
                timeout=self._timeout) as response:
            if response.status != 200:
                raise RuntimeError('qualification probe returned HTTP ' +
                                   str(response.status))
            value = json.loads(response.read(65537))
        state = _nested(value, self._health_path)
        storage = _nested(value, self._storage_path)
        if state not in ('healthy', 'degraded', 'failed'):
            raise ValueError('qualification probe health is unavailable')
        if storage is not None:
            storage = int(storage)
        return {'health_state': state, 'storage_free_bytes': storage}


class QualificationCampaign:
    def __init__(self, recorder, clock=time.time, sleeper=time.sleep):
        self.recorder = recorder
        self.clock = clock
        self.sleeper = sleeper

    def observe(self, probe, canary_paused=False):
        try:
            value = probe()
            return self.recorder.sample(
                value.get('health_state'), value.get('storage_free_bytes'),
                True, canary_paused
            )
        except Exception:
            # Unreachable is a network observation, not fabricated evidence of
            # unhealthy services or low storage.
            return self.recorder.sample(None, None, False, canary_paused)

    def monitor(self, probe, duration_s, interval_s, canary_paused=False):
        deadline = self.clock() + int(duration_s)
        result = self.recorder.snapshot()
        while self.clock() < deadline:
            result = self.observe(probe, canary_paused)
            remaining = deadline - self.clock()
            if remaining > 0:
                self.sleeper(min(int(interval_s), remaining))
        return result


def _write_evidence(path, value):
    encoded = json.dumps(value, indent=2, sort_keys=True) + '\n'
    if path == '-':
        sys.stdout.write(encoded)
    else:
        Path(path).write_text(encoded)


def _parser():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--state', required=True,
                        help='Persistent campaign state file')
    parser.add_argument('--evidence', default='-',
                        help='Evidence JSON output, or - for stdout')
    parser.add_argument('--device-id', required=True)
    parser.add_argument('--version', required=True)
    parser.add_argument('--sequence', required=True, type=int)
    parser.add_argument('--unconfirmed', action='store_true')
    subparsers = parser.add_subparsers(dest='command', required=True)
    subparsers.add_parser('status')
    subparsers.add_parser('reset')
    sample = subparsers.add_parser('sample')
    sample.add_argument('--health', choices=('healthy', 'degraded', 'failed'))
    sample.add_argument('--storage-free', type=int)
    sample.add_argument('--network', choices=('up', 'down'), required=True)
    sample.add_argument('--canary-paused', action='store_true')
    for command in ('renewal', 'power'):
        event = subparsers.add_parser(command)
        event.add_argument('--outcome', choices=('success', 'failure'), required=True)
    update = subparsers.add_parser('update')
    update.add_argument(
        '--outcome', choices=('confirmed', 'failed', 'rolled-back'), required=True
    )
    validation = subparsers.add_parser('validation')
    validation.add_argument('--gate', choices=(
        'native-recovery', 'watchdog-recovery',
        'identity-interoperability', 'fleet-interoperability',
        'migration-rollback', 'driver-hardware',
    ), required=True)
    validation.add_argument(
        '--outcome', choices=('success', 'failure'), required=True
    )
    monitor = subparsers.add_parser('monitor')
    monitor.add_argument('--url', required=True)
    monitor.add_argument('--ca-file', required=True)
    monitor.add_argument('--cert-file')
    monitor.add_argument('--key-file')
    monitor.add_argument('--duration', type=int, required=True)
    monitor.add_argument('--interval', type=int, default=60)
    monitor.add_argument('--timeout', type=int, default=10)
    monitor.add_argument('--health-path', default='health.state')
    monitor.add_argument(
        '--storage-path', default='health.storage_free_bytes'
    )
    monitor.add_argument('--canary-paused', action='store_true')
    return parser


def main(argv=None):
    arguments = _parser().parse_args(argv)
    namespace = FileNamespace(arguments.state)
    release = {
        'version': arguments.version,
        'sequence': arguments.sequence,
        'confirmed': not arguments.unconfirmed,
    }
    recorder = OperationalQualification(
        namespace, lambda: int(time.time()), arguments.device_id,
        lambda: release
    )
    recorder.start()
    command = arguments.command
    if command == 'reset':
        result = recorder.reset()
    elif command == 'sample':
        result = recorder.sample(
            arguments.health, arguments.storage_free,
            arguments.network == 'up', arguments.canary_paused
        )
    elif command == 'renewal':
        recorder.record_renewal(arguments.outcome == 'success')
        result = recorder.snapshot()
    elif command == 'power':
        recorder.record_power_recovery(arguments.outcome == 'success')
        result = recorder.snapshot()
    elif command == 'update':
        recorder.record_update(arguments.outcome)
        result = recorder.snapshot()
    elif command == 'validation':
        recorder.record_validation(
            arguments.gate, arguments.outcome == 'success'
        )
        result = recorder.snapshot()
    elif command == 'monitor':
        if arguments.duration < 1 or arguments.interval < 1:
            raise SystemExit('duration and interval must be positive')
        probe = HTTPProbe(
            arguments.url, arguments.ca_file, arguments.cert_file,
            arguments.key_file, arguments.timeout,
            arguments.health_path, arguments.storage_path
        )
        result = QualificationCampaign(recorder).monitor(
            probe, arguments.duration, arguments.interval,
            arguments.canary_paused
        )
    else:
        result = recorder.snapshot()
    _write_evidence(arguments.evidence, result)
    return 0 if result['promotion_ready'] else 2


if __name__ == '__main__':
    raise SystemExit(main())

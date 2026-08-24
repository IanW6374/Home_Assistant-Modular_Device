#!/usr/bin/env python3
"""Record the reproducible HAMD v2 hardware qualification."""

import argparse
import json
import ssl
import time
import urllib.request
from pathlib import Path


def fetch(base, path, context):
    started = time.monotonic()
    with urllib.request.urlopen(base + path, context=context, timeout=15) as response:
        value = json.loads(response.read())
    return value, round((time.monotonic() - started) * 1000, 2)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--host', required=True)
    parser.add_argument('--port', type=int, default=8444)
    parser.add_argument('--ca', required=True)
    parser.add_argument('--cert', required=True)
    parser.add_argument('--key', required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    context = ssl.create_default_context(cafile=args.ca)
    context.load_cert_chain(args.cert, args.key)
    base = 'https://' + args.host + ':' + str(args.port)
    report = {'format_version': 1, 'device': args.host, 'checks': {}}
    for name, path in (
        ('inventory', '/api/v2/device/inventory'),
        ('health', '/api/v2/health'),
        ('events', '/api/v2/events?cursor=0&limit=8'),
        ('support', '/api/v2/support'),
        ('fleet', '/api/v2/fleet'),
    ):
        value, latency = fetch(base, path, context)
        report['checks'][name] = {'passed': isinstance(value, dict), 'latency_ms': latency}
    report['passed'] = all(item['passed'] for item in report['checks'].values())
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + '\n')
    if not report['passed']:
        raise SystemExit('hardware qualification failed')


if __name__ == '__main__':
    main()

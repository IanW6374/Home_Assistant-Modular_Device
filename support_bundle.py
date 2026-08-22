"""Generate a bounded, secret-free v2 support document on the device."""

try:
    import time
except ImportError:
    time = None

try:
    import gc
except ImportError:
    gc = None


FORMAT_VERSION = 1
MAX_MODULES = 64
MAX_LOG_LINES = 200
SECRET_FRAGMENTS = (
    'password', 'private', 'secret', 'token', 'verifier', 'credential',
    'certificate', 'key',
)


def _safe_key(name):
    lowered = str(name).lower()
    return not any(fragment in lowered for fragment in SECRET_FRAGMENTS)


def redact(value, depth=0):
    if depth > 8:
        return '[depth limit]'
    if isinstance(value, dict):
        return {
            str(key): redact(item, depth + 1)
            for key, item in value.items() if _safe_key(key)
        }
    if isinstance(value, (list, tuple)):
        return [redact(item, depth + 1) for item in value[:128]]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value if not isinstance(value, str) else value[:512]
    return str(value)[:512]


def build_support_bundle(device, health, modules=(), versions=None, fleet=None,
                         logs=()):
    free_heap = None
    if gc and hasattr(gc, 'mem_free'):
        try:
            free_heap = int(gc.mem_free())
        except Exception:
            pass
    return {
        'format_version': FORMAT_VERSION,
        'created_at': int(time.time()) if time else 0,
        'device': redact(device or {}),
        'versions': redact(versions or {}),
        'runtime': {'free_heap': free_heap},
        'health': redact(health.snapshot() if health else {}),
        'modules': redact(list(modules or ())[:MAX_MODULES]),
        'fleet': redact(fleet.snapshot() if fleet else {}),
        'logs': [str(line)[:512] for line in list(logs or ())[-MAX_LOG_LINES:]],
        'redaction': 'secret-named fields omitted; values bounded',
    }

"""Small cross-platform hardware capability layer for MicroPython targets."""

try:
    import sys
except ImportError:
    sys = None

try:
    import machine
except ImportError:
    machine = None


PLATFORM = getattr(sys, 'platform', '') if sys else ''
MACHINE_NAME = str(getattr(getattr(sys, 'implementation', None), '_machine', ''))
IS_RP2 = PLATFORM == 'rp2'
IS_ESP32 = PLATFORM == 'esp32'
IS_ESP32_S3 = IS_ESP32 and 'ESP32S3' in MACHINE_NAME.upper().replace('-', '')


class NullOutput:
    """Pin-compatible no-op output for boards without a simple status LED."""

    def __init__(self):
        self.value = 0

    def __call__(self, value=None):
        if value is not None:
            self.value = 1 if value else 0
        return self.value

    def toggle(self):
        self.value = 0 if self.value else 1
        return self.value


def platform_id():
    if IS_ESP32_S3:
        return 'esp32-s3'
    if IS_ESP32:
        return 'esp32'
    if IS_RP2:
        return 'rp2'
    return PLATFORM or 'unknown'


def status_output(configured_pin=None):
    if not machine or not hasattr(machine, 'Pin'):
        return NullOutput()
    pin = configured_pin
    if pin is None and IS_RP2:
        pin = 'LED'
    if pin is None:
        return NullOutput()
    try:
        return machine.Pin(pin, machine.Pin.OUT)
    except Exception:
        return NullOutput()


def unique_id():
    if machine and hasattr(machine, 'unique_id'):
        return machine.unique_id()
    return b'host'


def reset():
    if machine and hasattr(machine, 'reset'):
        machine.reset()


def watchdog_timeout(requested_ms):
    requested_ms = int(requested_ms or 0)
    if requested_ms <= 0:
        return 0
    if IS_RP2:
        return min(requested_ms, 8000)
    return requested_ms


def firmware_ota_supported():
    if not IS_ESP32:
        return False
    try:
        import esp32
        running = esp32.Partition(esp32.Partition.RUNNING)
        target = running.get_next_update()
        return target is not None and target.info()[3] > 0
    except Exception:
        return False


def runtime_version():
    implementation = getattr(sys, 'implementation', None) if sys else None
    version = getattr(implementation, 'version', ())
    if version and len(version) >= 3:
        return '.'.join(str(value) for value in version[:3])
    return ''


def diagnostics():
    return {
        'platform': platform_id(),
        'machine': MACHINE_NAME,
        'firmware_ota': firmware_ota_supported(),
        'runtime_version': runtime_version()
    }

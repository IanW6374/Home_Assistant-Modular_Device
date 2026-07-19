"""ESP32-S3 hardware capability layer for the supported MicroPython target."""

try:
    import sys
except ImportError:
    sys = None

try:
    import machine
except ImportError:
    machine = None

try:
    import esp32
except ImportError:
    esp32 = None


PLATFORM = getattr(sys, 'platform', '') if sys else ''
MACHINE_NAME = str(getattr(getattr(sys, 'implementation', None), '_machine', ''))
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


class NeoPixelOutput:
    """Boolean output adapter for a single addressable status LED."""

    def __init__(self, pixel, colour=(16, 0, 0)):
        # DevKitC-1 onboard RGB ordering combined with MicroPython's NeoPixel
        # byte mapping requires the first logical channel for physical green.
        self.pixel = pixel
        self.colour = colour
        self.value = 0
        self(0)

    def __call__(self, value=None):
        if value is not None:
            self.value = 1 if value else 0
            self.pixel[0] = self.colour if self.value else (0, 0, 0)
            self.pixel.write()
        return self.value

    def toggle(self):
        return self(0 if self.value else 1)

    def set_colour(self, colour):
        self.colour = tuple(colour)
        if self.value:
            self.pixel[0] = self.colour
            self.pixel.write()


# DevKitC-1 NeoPixel logical ordering: first channel is physical green and the
# second channel is physical red. Combining them produces amber.
STATUS_COLOUR_OK = (16, 0, 0)
STATUS_COLOUR_WARNING = (16, 16, 0)
STATUS_COLOUR_ERROR = (0, 16, 0)


def status_led_mode(main_error=False, module_fault=False):
    """Return (colour, solid) with main-device errors taking priority."""
    if main_error:
        return STATUS_COLOUR_ERROR, True
    if module_fault:
        return STATUS_COLOUR_WARNING, False
    return STATUS_COLOUR_OK, False


def platform_id():
    if IS_ESP32_S3:
        return 'esp32-s3'
    return 'unsupported'


def status_output(configured_pin=None, output_type='auto'):
    if not machine or not hasattr(machine, 'Pin'):
        return NullOutput()
    pin = configured_pin
    if pin is None:
        return NullOutput()
    try:
        if output_type == 'neopixel' or (output_type == 'auto' and IS_ESP32_S3):
            import neopixel
            return NeoPixelOutput(neopixel.NeoPixel(machine.Pin(pin), 1))
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
    return requested_ms if requested_ms > 0 else 0


def firmware_ota_capability():
    if not IS_ESP32_S3:
        return {
            'supported': False,
            'reason': 'base firmware OTA requires the supported ESP32-S3 runtime'
        }
    if esp32 is None or not hasattr(esp32, 'Partition'):
        return {
            'supported': False,
            'reason': 'ESP32 partition API is unavailable in this MicroPython build'
        }
    try:
        running = esp32.Partition(esp32.Partition.RUNNING)
        running_info = running.info()
        try:
            target = running.get_next_update()
        except OSError as exc:
            if exc.args and exc.args[0] in (2, -2):
                return {
                    'supported': False,
                    'reason': (
                        'no inactive OTA partition; install the OTA partition table '
                        'and rollback-enabled firmware over USB first'
                    ),
                    'running_partition': str(running_info[4])
                }
            raise
        if target is None:
            return {
                'supported': False,
                'reason': (
                    'no inactive OTA partition; install the OTA partition table '
                    'and rollback-enabled firmware over USB first'
                ),
                'running_partition': str(running_info[4])
            }
        target_info = target.info()
        target_size = int(target_info[3])
        if target_size <= 0:
            return {
                'supported': False,
                'reason': 'inactive OTA partition has an invalid size',
                'running_partition': str(running_info[4]),
                'target_partition': str(target_info[4])
            }
        return {
            'supported': True,
            'reason': 'ready',
            'running_partition': str(running_info[4]),
            'target_partition': str(target_info[4]),
            'target_size': target_size
        }
    except Exception as exc:
        return {
            'supported': False,
            'reason': 'could not inspect ESP32 OTA partitions: ' + str(exc)
        }


def firmware_ota_supported():
    return bool(firmware_ota_capability().get('supported'))


def runtime_version():
    implementation = getattr(sys, 'implementation', None) if sys else None
    version = getattr(implementation, 'version', ())
    if version and len(version) >= 3:
        return '.'.join(str(value) for value in version[:3])
    return ''


def diagnostics():
    ota = firmware_ota_capability()
    return {
        'platform': platform_id(),
        'machine': MACHINE_NAME,
        'firmware_ota': ota.get('supported', False),
        'firmware_ota_reason': ota.get('reason', ''),
        'runtime_version': runtime_version()
    }

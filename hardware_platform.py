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

try:
    import gc
except ImportError:
    gc = None


PLATFORM = getattr(sys, 'platform', '') if sys else ''
MACHINE_NAME = str(getattr(getattr(sys, 'implementation', None), '_machine', ''))
IS_ESP32 = PLATFORM == 'esp32'
IS_ESP32_S3 = IS_ESP32 and 'ESP32S3' in MACHINE_NAME.upper().replace('-', '')
SPIRAM_HEAP_CAPABILITY = 1 << 10


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
STATUS_COLOUR_ACTIVITY = (0, 0, 16)


def set_status_led_state(output, state):
    """Apply a user-visible state to the single onboard status pixel."""
    colour = {
        'boot': STATUS_COLOUR_ACTIVITY,
        'wifi': STATUS_COLOUR_ACTIVITY,
        'setup': STATUS_COLOUR_ACTIVITY,
        'recovery': STATUS_COLOUR_WARNING,
        'warning': STATUS_COLOUR_WARNING,
        'error': STATUS_COLOUR_ERROR,
        'ok': STATUS_COLOUR_OK,
    }.get(str(state), STATUS_COLOUR_WARNING)
    if hasattr(output, 'set_colour'):
        output.set_colour(colour)
    output(1)
    return colour


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


def shutdown():
    """Enter deep sleep until an external wake, reset, or power cycle."""
    if machine and hasattr(machine, 'deepsleep'):
        machine.deepsleep()
        return
    raise RuntimeError('hardware shutdown is unavailable')


def reset_cause():
    if not machine or not hasattr(machine, 'reset_cause'):
        return 'unknown'
    try:
        value = machine.reset_cause()
    except Exception:
        return 'unknown'
    names = {}
    for name in (
        'PWRON_RESET', 'HARD_RESET', 'WDT_RESET', 'DEEPSLEEP_RESET',
        'SOFT_RESET', 'BROWN_OUT_RESET'
    ):
        if hasattr(machine, name):
            names[getattr(machine, name)] = name.lower()
    return names.get(value, str(value))


def watchdog_timeout(requested_ms):
    requested_ms = int(requested_ms or 0)
    return requested_ms if requested_ms > 0 else 0


def heap_capability():
    """Describe the MicroPython and ESP-IDF heaps without version guessing."""
    result = {
        'gc_free_bytes': None,
        'gc_allocated_bytes': None,
        'psram_detected': False,
        'psram_total_bytes': 0,
        'psram_free_bytes': 0,
        'psram_largest_free_block': 0,
        'psram_minimum_free_bytes': 0,
    }
    if gc is not None:
        try:
            if hasattr(gc, 'mem_free'):
                result['gc_free_bytes'] = int(gc.mem_free())
            if hasattr(gc, 'mem_alloc'):
                result['gc_allocated_bytes'] = int(gc.mem_alloc())
        except Exception:
            pass
    if esp32 is None or not hasattr(esp32, 'idf_heap_info'):
        return result
    try:
        heaps = esp32.idf_heap_info(SPIRAM_HEAP_CAPABILITY)
        for heap in heaps or ():
            if not isinstance(heap, (tuple, list)) or len(heap) < 4:
                continue
            result['psram_total_bytes'] += int(heap[0])
            result['psram_free_bytes'] += int(heap[1])
            result['psram_largest_free_block'] = max(
                result['psram_largest_free_block'], int(heap[2])
            )
            result['psram_minimum_free_bytes'] += int(heap[3])
        result['psram_detected'] = result['psram_total_bytes'] > 0
    except Exception:
        pass
    return result


def _backup_provider():
    """Return the reset-persistent memory provider supported by this build."""
    if machine is None:
        return None, 'backup memory is unavailable outside the device runtime'
    direct = getattr(machine, 'mem_backup', None)
    if callable(direct):
        return ('mem_backup', direct), 'machine.mem_backup'
    rtc_factory = getattr(machine, 'RTC', None)
    if callable(rtc_factory):
        try:
            rtc = rtc_factory()
            memory = getattr(rtc, 'memory', None)
            if callable(memory):
                return ('rtc_memory', memory), 'machine.RTC().memory'
        except Exception:
            pass
    try:
        import _iotmd_platform
        memory = getattr(_iotmd_platform, 'backup_memory', None)
        if callable(memory):
            return ('native_rtc_memory', memory), '_iotmd_platform.backup_memory'
    except ImportError:
        pass
    return None, 'no reset-persistent memory API is exposed by this firmware'


def backup_memory_capability():
    provider, detail = _backup_provider()
    return {'supported': provider is not None, 'provider': detail}


def backup_memory_read():
    """Read the optional reset-persistent byte record.

    MicroPython ports expose this facility either as ``mem_backup([data])`` or
    ``RTC().memory([data])``.  The adapter deliberately returns an empty byte
    string when neither API exists so boot can fall back to atomic flash state.
    """
    provider, _detail = _backup_provider()
    if provider is None:
        return b''
    try:
        value = provider[1]()
        return bytes(value or b'')
    except Exception:
        return b''


def backup_memory_write(data):
    provider, _detail = _backup_provider()
    if provider is None:
        return False
    try:
        provider[1](bytes(data))
        return True
    except Exception:
        return False


def backup_memory_clear():
    return backup_memory_write(b'')


def capabilities():
    """Return a serialisable feature matrix for boot policy and diagnostics."""
    heap = heap_capability()
    backup = backup_memory_capability()
    ota = firmware_ota_capability()
    return {
        'platform': platform_id(),
        'machine': MACHINE_NAME,
        'runtime_version': runtime_version(),
        'features': {
            'firmware_ota': bool(ota.get('supported')),
            'reset_persistent_memory': bool(backup.get('supported')),
            'psram': bool(heap.get('psram_detected')),
            'watchdog': bool(machine and hasattr(machine, 'WDT')),
            'status_led': bool(machine and hasattr(machine, 'Pin')),
        },
        'heap': heap,
        'backup_memory': backup,
        'firmware_ota': ota,
    }


def required_capability_failures(minimum_heap_bytes=0,
                                 minimum_psram_bytes=0):
    """Return hard boot-gate failures for the supported production target."""
    if not IS_ESP32_S3:
        return []
    values = capabilities()
    heap = values['heap']
    failures = []
    if minimum_psram_bytes and int(heap.get('psram_total_bytes', 0) or 0) < int(minimum_psram_bytes):
        failures.append(
            'PSRAM unavailable or below the required ' +
            str(int(minimum_psram_bytes)) + ' bytes'
        )
    free_heap = heap.get('gc_free_bytes')
    if minimum_heap_bytes and (
        free_heap is None or int(free_heap) < int(minimum_heap_bytes)
    ):
        failures.append(
            'free MicroPython heap is below the required ' +
            str(int(minimum_heap_bytes)) + ' bytes'
        )
    return failures


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
    values = capabilities()
    ota = values['firmware_ota']
    values['firmware_ota_supported'] = ota.get('supported', False)
    values['firmware_ota_reason'] = ota.get('reason', '')
    return values

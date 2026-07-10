import importlib
import sys
import types
import unittest


class FakePin:
    OUT = 1
    IN = 0
    PULL_UP = 2
    PULL_DOWN = 3

    def __init__(self, value=None, mode=None, pull=None):
        self.value_arg = value
        self.mode = mode
        self.pull = pull
        self.state = 1

    def value(self, state=None):
        if state is None:
            return self.state
        self.state = state


class FakeSPI:
    def __init__(self, *args, **kwargs):
        self.writes = []

    def write(self, data):
        self.writes.append(bytes(data))


class FakeDisplay:
    width = 128
    height = 64

    def __init__(self):
        self.lines = []
        self.power_state = True

    def fill(self, color):
        self.lines = []

    def text(self, text, x, y, color=1):
        self.lines.append((text, x, y, color))

    def show(self):
        pass

    def power(self, on):
        self.power_state = on


def load_module():
    machine = types.ModuleType('machine')
    machine.Pin = FakePin
    machine.SPI = FakeSPI
    sys.modules['machine'] = machine

    framebuf = types.ModuleType('framebuf')
    framebuf.MONO_HLSB = 1

    class FrameBuffer:
        def __init__(self, *args, **kwargs):
            pass

        def fill(self, color):
            pass

        def text(self, text, x, y, color):
            pass

    framebuf.FrameBuffer = FrameBuffer
    sys.modules['framebuf'] = framebuf

    sys.modules.pop('local_display', None)
    return importlib.import_module('local_display')


class LocalDisplayTests(unittest.TestCase):
    def setUp(self):
        self.module = load_module()

    def test_format_status_page_uses_key_status_fields(self):
        page = self.module.format_status_page({
            'device_name': 'Boiler Pico',
            'wifi_ip': '192.168.1.50',
            'mqtt': 'up',
            'config': 'examples/module_settings.ems.example.json',
            'loglevel': 'INFO',
            'web_portal': True
        })

        self.assertEqual(page[0], 'Boiler Pico')
        self.assertIn('192.168.1.50', page[1])
        self.assertEqual(page[2], 'MQTT up')
        self.assertEqual(page[5], 'Portal on')

    def test_device_pages_are_chunked_and_sanitised(self):
        pages = self.module.format_device_pages({
            'name': 'AC Voltage',
            'payload': {
                'voltage': 241.2,
                'ac_present': True,
                'empty': None
            }
        })

        self.assertEqual(pages[0][0], 'AC Voltage')
        self.assertIn('voltage 241.2', pages[0])
        self.assertIn('ac present True', pages[0])
        self.assertNotIn('empty None', pages[0])

    def test_service_renders_status_and_device_pages(self):
        display = FakeDisplay()
        service = self.module.LocalDisplayService(
            {'enabled': True},
            lambda: {'device_name': 'Pico', 'mqtt': 'up'},
            lambda: [{'name': 'Temp', 'payload': {'temperature': 21.5}}],
            display=display
        )

        service.render()

        rendered_text = [line[0] for line in display.lines]
        self.assertIn('Pico', rendered_text)
        self.assertIn('MQTT up', rendered_text)

    def test_next_previous_and_toggle_display_actions(self):
        display = FakeDisplay()
        service = self.module.LocalDisplayService(
            {'enabled': True},
            lambda: {'device_name': 'Pico'},
            lambda: [{'name': 'Temp', 'payload': {'temperature': 21.5}}],
            display=display
        )

        service.handle_action('next_page')
        self.assertEqual(service.page_index, 1)
        service.handle_action('previous_page')
        self.assertEqual(service.page_index, 0)
        service.handle_action('toggle_display')
        self.assertFalse(service.display_on)
        self.assertFalse(display.power_state)

    def test_custom_action_callback_is_called(self):
        calls = []
        service = self.module.LocalDisplayService(
            {'enabled': True},
            lambda: {},
            lambda: [],
            actions={'refresh_discovery': lambda: calls.append('discover')},
            display=FakeDisplay()
        )

        service.handle_action('refresh_discovery')

        self.assertEqual(calls, ['discover'])


if __name__ == '__main__':
    unittest.main()

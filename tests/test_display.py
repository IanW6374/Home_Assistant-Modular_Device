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
    instances = []

    def __init__(self, *args, **kwargs):
        self.args = args
        self.kwargs = kwargs
        self.writes = []
        FakeSPI.instances.append(self)

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
    FakeSPI.instances = []
    machine = types.ModuleType('machine')
    machine.Pin = FakePin
    machine.SPI = FakeSPI
    sys.modules['machine'] = machine

    framebuf = types.ModuleType('framebuf')
    framebuf.MONO_HLSB = 1
    framebuf.MONO_HMSB = 2

    class FrameBuffer:
        instances = []

        def __init__(self, *args, **kwargs):
            self.args = args
            self.kwargs = kwargs
            FrameBuffer.instances.append(self)

        def fill(self, color):
            pass

        def text(self, text, x, y, color):
            pass

    framebuf.FrameBuffer = FrameBuffer
    sys.modules['framebuf'] = framebuf

    sys.modules.pop('display', None)
    return importlib.import_module('display')


class DisplayTests(unittest.TestCase):
    def setUp(self):
        self.module = load_module()

    def test_format_status_page_uses_key_status_fields(self):
        page = self.module.format_status_page({
            'device_name': 'Boiler Controller',
            'wifi_ip': '192.168.1.50',
            'mqtt': 'up',
            'config': 'examples/module_settings.ems.example.json',
            'loglevel': 'INFO',
            'web_portal': True,
            'uptime_s': 3661,
            'alerts': ['one']
        })

        self.assertEqual(page[0], 'Boiler Controller')
        self.assertIn('192.168.1.50', page[1])
        self.assertEqual(page[2], 'MQTT up')
        self.assertEqual(page[3], 'Up 1h')
        self.assertEqual(page[4], 'Alerts 1')
        self.assertNotIn('Log INFO', page)
        self.assertFalse(any(line.startswith('Cfg ') for line in page))

    def test_device_pages_are_chunked_and_sanitised(self):
        pages = self.module.format_device_pages({
            'name': 'AC Voltage',
            'payload': {
                'voltage': 241.2,
                'ac_present': True,
                'empty': None,
                'module_last_ok': True,
                'module_last_read_ms': 5,
                'error': ''
            }
        })

        self.assertEqual(pages[0][0], 'AC Voltage')
        self.assertIn('voltage 241.2', pages[0])
        self.assertIn('ac present True', pages[0])
        self.assertNotIn('empty None', pages[0])
        self.assertIn('module last ok True', pages[0])

    def test_device_pages_use_five_values_per_screen(self):
        pages = self.module.format_device_pages({
            'name': 'Probe',
            'payload': {
                'a': 1,
                'b': 2,
                'c': 3,
                'd': 4,
                'e': 5,
                'f': 6
            }
        })

        self.assertEqual(len(pages), 2)
        self.assertEqual(len(pages[0]), 6)
        self.assertEqual(pages[1], ['Probe', 'f 6'])

    def test_service_renders_status_and_device_pages(self):
        display = FakeDisplay()
        service = self.module.LocalDisplayService(
            {'enabled': True},
            lambda: {'device_name': 'Controller', 'mqtt': 'up'},
            lambda: [{'name': 'Temp', 'payload': {'temperature': 21.5}}],
            display=display
        )

        service.render()

        rendered_text = [line[0] for line in display.lines]
        self.assertIn('Controller', rendered_text)
        self.assertIn('MQTT up', rendered_text)

    def test_service_scrolls_long_status_lines(self):
        display = FakeDisplay()
        service = self.module.LocalDisplayService(
            {'enabled': True},
            lambda: {
                'device_name': 'Controller',
                'wifi_ip': '192.168.100.123',
                'mqtt': 'up'
            },
            lambda: [],
            display=display
        )

        service.render()
        first_wifi_line = display.lines[1][0]
        service.render()
        second_wifi_line = display.lines[1][0]

        self.assertEqual(first_wifi_line, 'WiFi 192.168.100')
        self.assertEqual(second_wifi_line, 'WiFi 92.168.100.')
        self.assertTrue(first_wifi_line.startswith('WiFi '))
        self.assertTrue(second_wifi_line.startswith('WiFi '))

    def test_scrolled_text_wraps_long_lines(self):
        self.assertEqual(self.module.scrolled_text('abcdef', 4, 0), 'abcd')
        self.assertEqual(self.module.scrolled_text('abcdef', 4, 2), 'cdef')
        self.assertEqual(self.module.scrolled_text('abc', 4, 10), 'abc')

    def test_display_line_text_keeps_wifi_label_fixed(self):
        self.assertEqual(
            self.module.display_line_text('WiFi 192.168.100.123', 16, 2),
            'WiFi 2.168.100.1'
        )
        self.assertEqual(
            self.module.display_line_text('MQTT connected-long', 16, 2),
            'TT connected-lon'
        )

    def test_sh1107_display_uses_controller_buffer_layout(self):
        display = self.module.SH1107SPIDisplay({'enabled': True})

        self.assertEqual(display.width, 128)
        self.assertEqual(display.height, 64)
        self.assertEqual(len(display.buffer), 1024)
        self.assertEqual(display.framebuf.args[3], self.module.framebuf.MONO_HMSB)

        spi = FakeSPI.instances[0]
        self.assertEqual(spi.kwargs['polarity'], 0)
        self.assertEqual(spi.kwargs['phase'], 0)
        self.assertIn(bytes([0xAD]), spi.writes)
        self.assertIn(bytes([0x8A]), spi.writes)

    def test_sh1107_show_writes_64_columns_of_16_bytes(self):
        display = self.module.SH1107SPIDisplay({'enabled': True})
        spi = FakeSPI.instances[0]
        spi.writes = []

        display.show()

        data_writes = [write for write in spi.writes if len(write) == 16]
        self.assertEqual(len(data_writes), 64)

    def test_next_previous_and_toggle_display_actions(self):
        display = FakeDisplay()
        service = self.module.LocalDisplayService(
            {'enabled': True},
            lambda: {'device_name': 'Controller'},
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

    def test_display_factory_selects_configured_driver(self):
        display = self.module.create_display({'type': 'SH1107-SPI'})

        self.assertIsInstance(display, self.module.SH1107SPIDisplay)

    def test_display_factory_rejects_unknown_driver(self):
        with self.assertRaisesRegex(ValueError, 'unsupported display type'):
            self.module.create_display({'type': 'unknown'})


if __name__ == '__main__':
    unittest.main()

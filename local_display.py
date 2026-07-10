"""Local OLED status display for Pico-OLED-1.3 style SH1107 modules."""

try:
    import framebuf
except ImportError:
    framebuf = None

from machine import Pin, SPI
import asyncio
import time


DEFAULT_CONFIG = {
    'enabled': False,
    'type': 'Waveshare-Pico-OLED-1.3',
    'width': 128,
    'height': 64,
    'spi': 1,
    'sck': 10,
    'mosi': 11,
    'cs': 9,
    'dc': 8,
    'rst': 12,
    'baudrate': 10000000,
    'refresh_ms': 1000,
    'button_poll_ms': 50,
    'long_press_ms': 900,
    'button_a': 15,
    'button_b': 17,
    'button_active_low': True,
    'button_a_short': 'next_page',
    'button_a_long': 'refresh_discovery',
    'button_b_short': 'previous_page',
    'button_b_long': 'toggle_loglevel'
}


class SH1107Display:
    def __init__(self, cfg):
        if framebuf is None:
            raise RuntimeError('framebuf module not available')

        self.width = int(cfg.get('width', DEFAULT_CONFIG['width']))
        self.height = int(cfg.get('height', DEFAULT_CONFIG['height']))
        self.spi = SPI(
            cfg.get('spi', DEFAULT_CONFIG['spi']),
            baudrate=cfg.get('baudrate', DEFAULT_CONFIG['baudrate']),
            polarity=0,
            phase=0,
            sck=Pin(cfg.get('sck', DEFAULT_CONFIG['sck'])),
            mosi=Pin(cfg.get('mosi', DEFAULT_CONFIG['mosi']))
        )
        self.cs = Pin(cfg.get('cs', DEFAULT_CONFIG['cs']), Pin.OUT)
        self.dc = Pin(cfg.get('dc', DEFAULT_CONFIG['dc']), Pin.OUT)
        self.rst = Pin(cfg.get('rst', DEFAULT_CONFIG['rst']), Pin.OUT)
        self.pages = self.height // 8
        self.buffer = bytearray(self.width * self.pages)
        self.framebuf = framebuf.FrameBuffer(self.buffer, self.width, self.height, framebuf.MONO_HLSB)
        self._reset()
        self._init_display()
        self.fill(0)
        self.show()

    def fill(self, color):
        self.framebuf.fill(color)

    def text(self, text, x, y, color=1):
        self.framebuf.text(str(text), x, y, color)

    def show(self):
        for page in range(self.pages):
            self._command(0xB0 + page)
            self._command(0x00)
            self._command(0x10)
            start = page * self.width
            self._data(self.buffer[start:start + self.width])

    def power(self, on):
        self._command(0xAF if on else 0xAE)

    def _reset(self):
        self.rst.value(1)
        self._sleep_ms(1)
        self.rst.value(0)
        self._sleep_ms(20)
        self.rst.value(1)
        self._sleep_ms(20)

    def _init_display(self):
        for command in (
            0xAE,       # display off
            0xD5, 0x50, # clock divide
            0xA8, 0x3F, # multiplex for 64 visible rows
            0xD3, 0x00, # display offset
            0x40,       # display start line
            0xA1,       # segment remap
            0xC8,       # COM scan direction
            0xDA, 0x12, # COM pins
            0x81, 0x7F, # contrast
            0xA4,       # display follows RAM
            0xA6,       # normal display
            0xD9, 0x22, # pre-charge
            0xDB, 0x35, # vcomh
            0xAF        # display on
        ):
            self._command(command)

    def _command(self, command):
        self.dc.value(0)
        self.cs.value(0)
        self.spi.write(bytes([command]))
        self.cs.value(1)

    def _data(self, data):
        self.dc.value(1)
        self.cs.value(0)
        self.spi.write(data)
        self.cs.value(1)

    def _sleep_ms(self, ms):
        if hasattr(time, 'sleep_ms'):
            time.sleep_ms(ms)
        else:
            time.sleep(ms / 1000)


class ButtonState:
    def __init__(self, pin, active_low=True):
        self.pin = Pin(pin, Pin.IN, Pin.PULL_UP if active_low else Pin.PULL_DOWN)
        self.active_low = active_low
        self.was_pressed = False
        self.pressed_at = 0

    def is_pressed(self):
        value = self.pin.value()
        return value == 0 if self.active_low else value == 1


class LocalDisplayService:
    def __init__(self, cfg, status_provider, snapshot_provider, actions=None, log_callable=None, display=None):
        self.cfg = merged_config(cfg)
        self.status_provider = status_provider
        self.snapshot_provider = snapshot_provider
        self.actions = actions or {}
        self.log_callable = log_callable
        self.display = display
        self.page_index = 0
        self.display_on = True
        self._running = False
        self._buttons = {}
        self._last_render = 0

    def start(self):
        if not self.cfg.get('enabled'):
            return False

        if self.display is None:
            self.display = SH1107Display(self.cfg)

        self._setup_buttons()
        self.render()
        self._running = True
        asyncio.create_task(self._loop())
        return True

    async def _loop(self):
        refresh_ms = int(self.cfg.get('refresh_ms', DEFAULT_CONFIG['refresh_ms']))
        poll_ms = int(self.cfg.get('button_poll_ms', DEFAULT_CONFIG['button_poll_ms']))

        while self._running:
            self.poll_buttons()
            if self._ticks_diff(self._ticks_ms(), self._last_render) >= refresh_ms:
                self.render()
            await asyncio.sleep_ms(poll_ms)

    def render(self):
        if not self.display_on:
            return

        pages = self.build_pages()
        if not pages:
            pages = [['Pico Device', 'No data']]

        if self.page_index >= len(pages):
            self.page_index = 0

        lines = pages[self.page_index]
        max_lines = self.display.height // 8
        max_chars = self.display.width // 8
        self.display.fill(0)
        for index, line in enumerate(lines[:max_lines]):
            self.display.text(str(line)[:max_chars], 0, index * 8, 1)
        self.display.show()
        self._last_render = self._ticks_ms()

    def build_pages(self):
        pages = []
        status = self.status_provider() if self.status_provider else {}
        pages.append(format_status_page(status))

        alerts = format_alerts_page(status)
        if alerts:
            pages.append(alerts)

        snapshots = self.snapshot_provider() if self.snapshot_provider else []
        for snapshot in snapshots:
            pages.extend(format_device_pages(snapshot))

        pages.append(format_actions_page(self.page_index, len(pages) + 1))
        return pages

    def poll_buttons(self):
        now = self._ticks_ms()
        for name in self._buttons:
            button = self._buttons[name]
            pressed = button.is_pressed()

            if pressed and not button.was_pressed:
                button.was_pressed = True
                button.pressed_at = now
            elif not pressed and button.was_pressed:
                duration = self._ticks_diff(now, button.pressed_at)
                button.was_pressed = False
                if duration >= int(self.cfg.get('long_press_ms', DEFAULT_CONFIG['long_press_ms'])):
                    self.handle_action(self.cfg.get(name + '_long'))
                else:
                    self.handle_action(self.cfg.get(name + '_short'))

    def handle_action(self, action):
        if not action:
            return

        if action == 'next_page':
            self.page_index += 1
        elif action == 'previous_page':
            self.page_index = max(0, self.page_index - 1)
        elif action == 'toggle_display':
            self.display_on = not self.display_on
            self.display.power(self.display_on)
        else:
            callback = self.actions.get(action)
            if callback:
                callback()

        self.render()

    def _setup_buttons(self):
        active_low = bool(self.cfg.get('button_active_low', True))
        for name in ('button_a', 'button_b'):
            pin = self.cfg.get(name)
            if pin is not None:
                self._buttons[name] = ButtonState(pin, active_low)

    def _ticks_ms(self):
        if hasattr(time, 'ticks_ms'):
            return time.ticks_ms()
        return int(time.time() * 1000)

    def _ticks_diff(self, end, start):
        if hasattr(time, 'ticks_diff'):
            return time.ticks_diff(end, start)
        return end - start


def merged_config(cfg):
    merged = DEFAULT_CONFIG.copy()
    if cfg:
        merged.update(cfg)
    return merged


def format_status_page(status):
    return [
        status.get('device_name', 'Pico Device'),
        'WiFi ' + status.get('wifi_ip', '-'),
        'MQTT ' + status.get('mqtt', 'unknown'),
        'Cfg ' + status.get('config', '-'),
        'Log ' + status.get('loglevel', '-'),
        'Portal ' + ('on' if status.get('web_portal') else 'off'),
        'Up ' + str(status.get('uptime_s', '-')) + 's',
        'Disc ' + str(status.get('discovery_count', '-'))
    ]


def format_alerts_page(status):
    alerts = status.get('alerts', [])
    if not alerts:
        return None
    return ['Alerts'] + [str(item) for item in alerts[:7]]


def format_device_pages(snapshot):
    name = snapshot.get('name', 'Device')
    payload = snapshot.get('payload', {})
    items = []
    for key in payload:
        value = payload[key]
        if value is not None and value != '':
            items.append((key, value))

    if not items:
        return [[name, 'No values']]

    pages = []
    for start in range(0, len(items), 6):
        lines = [name]
        for key, value in items[start:start + 6]:
            lines.append(short_line(key, value))
        pages.append(lines)
    return pages


def format_actions_page(page_index, page_count):
    return [
        'Controls',
        'A next',
        'B previous',
        'A long discover',
        'B long debug',
        'Page ' + str(page_index + 1) + '/' + str(page_count)
    ]


def short_line(key, value):
    text = str(key) + ' ' + str(value)
    return text.replace('_', ' ')

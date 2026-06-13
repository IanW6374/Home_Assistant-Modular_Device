"""Read RS485 Modbus entities from device.json and print values.

Copy/run this on the Pico instead of main.py when you want a direct RS485
terminal test without WiFi, MQTT, or Home Assistant discovery.
"""

try:
    import ujson as json
except ImportError:
    import json

try:
    from ustruct import unpack
except ImportError:
    from struct import unpack

from machine import UART, Pin
import time


DEVICE_CONFIG_FILE = "device.json"
DEVICE_NAME = "WHES"
DEFAULT_PORT = "ch0"
DEFAULT_TIMEOUT_MS = 500


def as_pin(value):
    if value is None:
        return None
    return Pin(value)


def setup_ports(device):
    rs485 = device.get("rs485", {})
    ports = rs485.get("ports")

    if not ports:
        ports = {
            DEFAULT_PORT: {
                "uart": device.get("uart", 1),
                "tx": device.get("tx", 8),
                "rx": device.get("rx", 9),
                "baudrate": device.get("baudrate", 9600),
            }
        }

    ready = {}
    for name in ports:
        cfg = ports[name]
        uart = UART(
            cfg.get("uart", 1),
            baudrate=cfg.get("baudrate", 9600),
            bits=cfg.get("bits", 8),
            parity=cfg.get("parity", None),
            stop=cfg.get("stop", 1),
            tx=as_pin(cfg.get("tx")),
            rx=as_pin(cfg.get("rx")),
        )

        tx_enable = None
        if "de" in cfg:
            tx_enable = Pin(cfg["de"], Pin.OUT)
            tx_enable.value(0 if cfg.get("tx_enable_active", 1) else 1)

        ready[name] = {
            "uart": uart,
            "tx_enable": tx_enable,
            "tx_enable_active": cfg.get("tx_enable_active", 1),
            "turnaround_ms": cfg.get("turnaround_ms", 5),
            "timeout_ms": cfg.get("timeout_ms", rs485.get("timeout_ms", DEFAULT_TIMEOUT_MS)),
        }

    return ready


def crc(payload):
    value = 0xFFFF
    for byte in payload:
        value ^= byte
        for _ in range(8):
            if value & 1:
                value = (value >> 1) ^ 0xA001
            else:
                value >>= 1
    return value


def crc_bytes(payload):
    value = crc(payload)
    return bytes([value & 0xFF, (value >> 8) & 0xFF])


def drain(uart):
    while uart.any():
        uart.read()


def set_tx(port, enabled):
    pin = port.get("tx_enable")
    if pin:
        active = port.get("tx_enable_active", 1)
        pin.value(active if enabled else 1 - active)


def ticks_add(ms, delta):
    if hasattr(time, "ticks_add"):
        return time.ticks_add(ms, delta)
    return ms + delta


def ticks_diff(a, b):
    if hasattr(time, "ticks_diff"):
        return time.ticks_diff(a, b)
    return a - b


def ticks_ms():
    if hasattr(time, "ticks_ms"):
        return time.ticks_ms()
    return int(time.time() * 1000)


def sleep_ms(ms):
    if hasattr(time, "sleep_ms"):
        time.sleep_ms(ms)
    else:
        time.sleep(ms / 1000)


def read_exact(uart, size, timeout_ms):
    deadline = ticks_add(ticks_ms(), timeout_ms)
    data = b""

    while len(data) < size and ticks_diff(deadline, ticks_ms()) > 0:
        if uart.any():
            chunk = uart.read(size - len(data))
            if chunk:
                data += chunk
        else:
            sleep_ms(5)

    return data


def modbus_read(ports, port_name, slave, function, address, count):
    port = ports.get(port_name)
    if not port:
        raise ValueError("unknown port " + str(port_name))

    uart = port["uart"]
    request = bytes([
        slave & 0xFF,
        function & 0xFF,
        (address >> 8) & 0xFF,
        address & 0xFF,
        (count >> 8) & 0xFF,
        count & 0xFF,
    ])
    request += crc_bytes(request)

    drain(uart)
    set_tx(port, True)
    uart.write(request)
    if hasattr(uart, "flush"):
        uart.flush()
    sleep_ms(port.get("turnaround_ms", 5))
    set_tx(port, False)

    expected = 5 + (count * 2)
    reply = read_exact(uart, expected, port.get("timeout_ms", DEFAULT_TIMEOUT_MS))
    if len(reply) < 5:
        raise ValueError("timeout")
    if crc(reply[:-2]) != (reply[-2] | (reply[-1] << 8)):
        raise ValueError("crc mismatch")
    if reply[0] != slave:
        raise ValueError("unexpected slave")
    if reply[1] == (function | 0x80):
        raise ValueError("modbus exception " + str(reply[2]))
    if reply[1] != function:
        raise ValueError("unexpected function")
    if reply[2] != count * 2:
        raise ValueError("unexpected byte count")

    return reply[3:3 + reply[2]]


def decode_registers(raw, data_type, byte_order, word_order):
    if data_type == "ascii":
        return "".join(chr(byte) for byte in raw if 32 <= byte <= 126).rstrip()

    if byte_order == "little":
        words = []
        for i in range(0, len(raw), 2):
            words.append(bytes([raw[i + 1], raw[i]]))
        raw = b"".join(words)

    if len(raw) == 4 and word_order == "little":
        raw = raw[2:4] + raw[0:2]

    if data_type == "int16":
        value = (raw[0] << 8) | raw[1]
        return value - 65536 if value & 0x8000 else value
    if data_type == "uint32":
        return (raw[0] << 24) | (raw[1] << 16) | (raw[2] << 8) | raw[3]
    if data_type == "int32":
        value = (raw[0] << 24) | (raw[1] << 16) | (raw[2] << 8) | raw[3]
        return value - 4294967296 if value & 0x80000000 else value
    if data_type == "float32":
        return unpack(">f", raw)[0]

    return (raw[0] << 8) | raw[1]


def read_entity(ports, device, entity):
    raw = modbus_read(
        ports,
        entity.get("port", DEFAULT_PORT),
        int(entity.get("slave", device.get("slave", 1))),
        int(entity.get("function", entity.get("function_code", 3))),
        int(entity.get("address", entity.get("memory_address"))),
        int(entity.get("count", 1)),
    )
    value = decode_registers(
        raw,
        entity.get("data_type", entity.get("type", "uint16")),
        entity.get("byte_order", "big"),
        entity.get("word_order", "big"),
    )
    if not isinstance(value, str):
        value = (value * entity.get("scale", 1)) + entity.get("offset", 0)
    return value


def find_device(config):
    for device in config.get("devices", []):
        if device.get("name") == DEVICE_NAME:
            return device
    for device in config.get("devices", []):
        if device.get("type", {}).get("subclass") in ("WHES", "Pico-2CH-RS485"):
            return device
    raise ValueError("no WHES or Pico-2CH-RS485 device found in " + DEVICE_CONFIG_FILE)


def main():
    with open(DEVICE_CONFIG_FILE, "rb") as file:
        config = json.loads(file.read())

    device = find_device(config)
    ports = setup_ports(device)
    entities = device.get("entities", {})

    print("RS485 memory test:", device.get("name", device.get("uuid", "")))
    print("key,address,value")

    for index in sorted(entities, key=lambda item: int(item)):
        entity = entities[index]
        key = entity.get("key", entity.get("class", index))
        address = entity.get("address", entity.get("memory_address"))

        try:
            value = read_entity(ports, device, entity)
            print("{},{},{}".format(key, address, value))
        except Exception as exc:
            print("{},{},ERROR: {}".format(key, address, exc))


main()

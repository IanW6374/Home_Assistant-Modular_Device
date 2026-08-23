"""Pure Modbus register encoding, decoding, CRC, and diagnostics formatting."""

try:
    from ustruct import unpack
except ImportError:
    from struct import unpack


def decode_registers(raw, data_type, byte_order, word_order):
    if data_type == 'ascii':
        return ''.join(chr(byte) for byte in raw if 32 <= byte <= 126).rstrip()
    if byte_order == 'little':
        raw = b''.join(
            bytes([raw[index + 1], raw[index]])
            for index in range(0, len(raw), 2)
        )
    if len(raw) == 4 and word_order == 'little':
        raw = raw[2:4] + raw[0:2]
    if data_type == 'int16':
        value = (raw[0] << 8) | raw[1]
        return value - 65536 if value & 0x8000 else value
    if data_type == 'uint32':
        return (raw[0] << 24) | (raw[1] << 16) | (raw[2] << 8) | raw[3]
    if data_type == 'int32':
        value = (raw[0] << 24) | (raw[1] << 16) | (raw[2] << 8) | raw[3]
        return value - 4294967296 if value & 0x80000000 else value
    if data_type == 'float32':
        return unpack('>f', raw)[0]
    return (raw[0] << 8) | raw[1]


def encode_value(value, data_type, scale, offset):
    if data_type == 'ascii':
        raise ValueError('ascii writes are not supported')
    scale = scale or 1
    value = int(round((float(value) - offset) / scale))
    if data_type == 'int16':
        if value < 0:
            value += 65536
        return bytes([(value >> 8) & 0xff, value & 0xff])
    if data_type in ('uint32', 'int32'):
        if value < 0:
            value += 4294967296
        return bytes([
            (value >> 24) & 0xff, (value >> 16) & 0xff,
            (value >> 8) & 0xff, value & 0xff,
        ])
    if data_type == 'float32':
        raise ValueError('float32 writes are not supported')
    return bytes([(value >> 8) & 0xff, value & 0xff])


def encode_registers(values, data_type, scale, offset, byte_order, word_order):
    raw = b''.join(
        encode_value(value, data_type, scale, offset) for value in values
    )
    if len(raw) == 4 and word_order == 'little':
        raw = raw[2:4] + raw[0:2]
    if byte_order == 'little':
        raw = b''.join(
            bytes([raw[index + 1], raw[index]])
            for index in range(0, len(raw), 2)
        )
    return raw


def crc(payload):
    value = 0xffff
    for byte in payload:
        value ^= byte
        for _ in range(8):
            value = (value >> 1) ^ 0xa001 if value & 1 else value >> 1
    return value


def crc_bytes(payload):
    value = crc(payload)
    return bytes([value & 0xff, (value >> 8) & 0xff])


def hex_bytes(payload):
    chars = '0123456789abcdef'
    return ''.join(
        chars[(byte >> 4) & 0x0f] + chars[byte & 0x0f] for byte in payload
    )

"""Shared SPI bus registry for module drivers."""

from machine import Pin, SPI


_BUSES = {}


def _as_pin(value):
    if value is None:
        return None
    return Pin(value)


def get_spi(cfg, defaults):
    bus_id = cfg.get('spi', defaults.get('spi', 0))
    spec = (
        bus_id,
        cfg.get('sck', defaults.get('sck')),
        cfg.get('mosi', defaults.get('mosi')),
        cfg.get('miso', defaults.get('miso')),
        cfg.get('polarity', defaults.get('polarity', 0)),
        cfg.get('phase', defaults.get('phase', 0)),
        cfg.get('bits', defaults.get('bits', 8)),
        cfg.get('firstbit', defaults.get('firstbit', SPI.MSB))
    )
    baudrate = cfg.get('baudrate', defaults.get('baudrate', 1000000))

    if bus_id in _BUSES:
        existing_spec, existing_spi = _BUSES[bus_id]
        if existing_spec != spec:
            raise RuntimeError('SPI' + str(bus_id) + ' already configured with different pins or mode')
        return existing_spi

    spi = SPI(
        bus_id,
        baudrate=baudrate,
        polarity=spec[4],
        phase=spec[5],
        bits=spec[6],
        firstbit=spec[7],
        sck=_as_pin(spec[1]),
        mosi=_as_pin(spec[2]),
        miso=_as_pin(spec[3])
    )
    _BUSES[bus_id] = (spec, spi)
    return spi


def reset():
    _BUSES.clear()

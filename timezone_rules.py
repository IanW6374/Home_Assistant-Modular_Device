"""Small ESP32-friendly timezone and daylight-saving rule table.

The device RTC remains in UTC.  This module provides the current display
offset without carrying the full IANA tz database in firmware.
"""

try:
    import time
except ImportError:
    time = None


# name, user-facing label, standard offset minutes, daylight offset minutes,
# rule family.  Rule families follow the current regional rules represented by
# the selected city; historic rule changes are intentionally out of scope.
ZONES = (
    ('UTC', 'UTC', 0, 0, ''),
    ('Europe/London', 'Europe — London', 0, 60, 'eu'),
    ('Europe/Paris', 'Europe — Paris / Central Europe', 60, 120, 'eu'),
    ('Europe/Athens', 'Europe — Athens / Eastern Europe', 120, 180, 'eu'),
    ('America/New_York', 'North America — New York / Toronto', -300, -240, 'us'),
    ('America/Chicago', 'North America — Chicago', -360, -300, 'us'),
    ('America/Denver', 'North America — Denver', -420, -360, 'us'),
    ('America/Los_Angeles', 'North America — Los Angeles / Vancouver', -480, -420, 'us'),
    ('America/Phoenix', 'North America — Phoenix (no DST)', -420, -420, ''),
    ('America/Sao_Paulo', 'South America — São Paulo', -180, -180, ''),
    ('Africa/Johannesburg', 'Africa — Johannesburg', 120, 120, ''),
    ('Asia/Dubai', 'Asia — Dubai', 240, 240, ''),
    ('Asia/Kolkata', 'Asia — Kolkata', 330, 330, ''),
    ('Asia/Shanghai', 'Asia — Shanghai / Hong Kong', 480, 480, ''),
    ('Asia/Singapore', 'Asia — Singapore', 480, 480, ''),
    ('Asia/Tokyo', 'Asia — Tokyo', 540, 540, ''),
    ('Australia/Perth', 'Australia — Perth', 480, 480, ''),
    ('Australia/Adelaide', 'Australia — Adelaide', 570, 630, 'au'),
    ('Australia/Sydney', 'Australia — Sydney / Melbourne', 600, 660, 'au'),
    ('Pacific/Auckland', 'Pacific — Auckland', 720, 780, 'nz'),
)

ZONE_NAMES = tuple(item[0] for item in ZONES)
_BY_NAME = {item[0]: item for item in ZONES}
_MONTH_DAYS = (31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31)
_default_zone = 'UTC'


def choices():
    return tuple((item[0], item[1]) for item in ZONES)


def configure(name='UTC'):
    """Select the zone used by components that need the device-local date."""
    global _default_zone
    _default_zone = str(name) if str(name) in _BY_NAME else 'UTC'
    return _default_zone


def _leap(year):
    return year % 4 == 0 and (year % 100 != 0 or year % 400 == 0)


def _month_days(year, month):
    return 29 if month == 2 and _leap(year) else _MONTH_DAYS[month - 1]


def _days_before_year(year):
    previous = year - 1
    return (
        365 * (year - 1970) + previous // 4 - 1969 // 4 -
        (previous // 100 - 1969 // 100) +
        (previous // 400 - 1969 // 400)
    )


def _days_before_month(year, month):
    total = sum(_MONTH_DAYS[:month - 1])
    return total + (1 if month > 2 and _leap(year) else 0)


def _epoch(year, month, day, hour=0, minute=0):
    days = _days_before_year(year) + _days_before_month(year, month) + day - 1
    return days * 86400 + hour * 3600 + minute * 60


def _runtime_epoch_offset():
    """Return the runtime epoch's position in Unix-epoch seconds.

    CPython uses 1970 while bare-metal MicroPython ports commonly use 2000.
    Asking the runtime what timestamp zero means avoids encoding either
    assumption into persisted timestamps, DST rules, or scheduled operations.
    """
    try:
        epoch_year = int(time.gmtime(0)[0])
    except Exception:
        epoch_year = 1970
    if epoch_year < 1900 or epoch_year > 2200:
        epoch_year = 1970
    return _epoch(epoch_year, 1, 1)


def _runtime_to_unix(epoch):
    return int(epoch or 0) + _runtime_epoch_offset()


def _weekday(year, month, day):
    # Monday=0, matching time.localtime().  1970-01-01 was Thursday.
    days = _days_before_year(year) + _days_before_month(year, month) + day - 1
    return (days + 3) % 7


def _nth_sunday(year, month, occurrence):
    first = 1 + ((6 - _weekday(year, month, 1)) % 7)
    return first + (occurrence - 1) * 7


def _last_sunday(year, month):
    last = _month_days(year, month)
    return last - ((_weekday(year, month, last) - 6) % 7)


def _local_transition_utc(year, month, day, hour, minute, prior_offset):
    return _epoch(year, month, day, hour, minute) - int(prior_offset) * 60


def _year(epoch):
    return _utc_tuple(epoch)[0]


def _utc_tuple(epoch):
    """Convert an epoch without inheriting the host process timezone."""
    year = 1970
    days, seconds = divmod(int(epoch), 86400)
    absolute_days = days
    while days >= (366 if _leap(year) else 365):
        days -= 366 if _leap(year) else 365
        year += 1
    while days < 0:
        year -= 1
        days += 366 if _leap(year) else 365
    year_day = days + 1
    month = 1
    while days >= _month_days(year, month):
        days -= _month_days(year, month)
        month += 1
    day = days + 1
    hour, seconds = divmod(seconds, 3600)
    minute, second = divmod(seconds, 60)
    return (
        year, month, day, hour, minute, second,
        (absolute_days + 3) % 7, year_day
    )


def _offset_minutes_unix(name, epoch):
    zone = _BY_NAME.get(str(name), _BY_NAME['UTC'])
    standard, daylight, rule = zone[2], zone[3], zone[4]
    if not rule or standard == daylight:
        return standard
    year = _year(epoch)
    if rule == 'eu':
        start = _epoch(year, 3, _last_sunday(year, 3), 1)
        end = _epoch(year, 10, _last_sunday(year, 10), 1)
        active = start <= epoch < end
    elif rule == 'us':
        start = _local_transition_utc(
            year, 3, _nth_sunday(year, 3, 2), 2, 0, standard
        )
        end = _local_transition_utc(
            year, 11, _nth_sunday(year, 11, 1), 2, 0, daylight
        )
        active = start <= epoch < end
    elif rule == 'au':
        start = _local_transition_utc(
            year, 10, _nth_sunday(year, 10, 1), 2, 0, standard
        )
        end = _local_transition_utc(
            year, 4, _nth_sunday(year, 4, 1), 3, 0, daylight
        )
        active = epoch >= start or epoch < end
    elif rule == 'nz':
        start = _local_transition_utc(
            year, 9, _last_sunday(year, 9), 2, 0, standard
        )
        end = _local_transition_utc(
            year, 4, _nth_sunday(year, 4, 1), 3, 0, daylight
        )
        active = epoch >= start or epoch < end
    else:
        active = False
    return daylight if active else standard


def offset_minutes(name=None, epoch=None):
    if name is None:
        name = _default_zone
    if epoch is None:
        try:
            epoch = time.time()
        except Exception:
            epoch = 0
    return _offset_minutes_unix(name, _runtime_to_unix(epoch))


def localtime(epoch=None, name=None):
    if name is None:
        name = _default_zone
    if epoch is None:
        epoch = time.time()
    unix_epoch = _runtime_to_unix(epoch)
    return _utc_tuple(unix_epoch + _offset_minutes_unix(name, unix_epoch) * 60)

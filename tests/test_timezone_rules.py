import unittest
from unittest.mock import patch

import timezone_rules


class TimezoneRuleTests(unittest.TestCase):
    def setUp(self):
        timezone_rules.configure('UTC')

    def test_london_uses_current_european_daylight_saving_rules(self):
        before = timezone_rules._epoch(2026, 3, 29, 0, 59)
        after = timezone_rules._epoch(2026, 3, 29, 1, 0)
        autumn = timezone_rules._epoch(2026, 10, 25, 1, 0)

        self.assertEqual(timezone_rules.offset_minutes('Europe/London', before), 0)
        self.assertEqual(timezone_rules.offset_minutes('Europe/London', after), 60)
        self.assertEqual(timezone_rules.offset_minutes('Europe/London', autumn), 0)
        self.assertEqual(timezone_rules.localtime(after, 'Europe/London')[3:5], (2, 0))

    def test_new_york_and_sydney_apply_hemisphere_rules(self):
        january = timezone_rules._epoch(2026, 1, 15, 12)
        june = timezone_rules._epoch(2026, 6, 15, 12)

        self.assertEqual(timezone_rules.offset_minutes('America/New_York', january), -300)
        self.assertEqual(timezone_rules.offset_minutes('America/New_York', june), -240)
        self.assertEqual(timezone_rules.offset_minutes('Australia/Sydney', january), 660)
        self.assertEqual(timezone_rules.offset_minutes('Australia/Sydney', june), 600)

    def test_fractional_offset_and_unknown_zone_are_deterministic(self):
        epoch = timezone_rules._epoch(2026, 6, 1, 0)
        self.assertEqual(timezone_rules.offset_minutes('Asia/Kolkata', epoch), 330)
        self.assertEqual(timezone_rules.localtime(epoch, 'Asia/Kolkata')[3:5], (5, 30))
        self.assertEqual(timezone_rules.offset_minutes('Unknown/Zone', epoch), 0)

    def test_esp32_2000_epoch_is_normalised_before_timezone_conversion(self):
        expected = timezone_rules._epoch(2026, 8, 22, 10, 39) + 37
        esp32_epoch = expected - timezone_rules._epoch(2000, 1, 1)

        class Esp32Time:
            @staticmethod
            def time():
                return esp32_epoch

            @staticmethod
            def gmtime(value):
                return (2000, 1, 1, 0, 0, 0, 5, 1) if value == 0 else ()

        with patch.object(timezone_rules, 'time', Esp32Time):
            self.assertEqual(
                timezone_rules.localtime(name='Europe/London')[:6],
                (2026, 8, 22, 11, 39, 37)
            )
            self.assertEqual(
                timezone_rules.localtime(name='Europe/London')[6], 5
            )

    def test_configured_zone_is_used_when_name_is_omitted(self):
        timezone_rules.configure('Asia/Kolkata')
        epoch = timezone_rules._epoch(2026, 6, 1, 0)
        self.assertEqual(timezone_rules.localtime(epoch)[3:5], (5, 30))


if __name__ == '__main__':
    unittest.main()

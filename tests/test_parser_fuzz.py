import json
import random
import unittest

import configuration_manager
import update_security
import web_portal


class ParserFuzzTests(unittest.TestCase):
    def test_bounded_random_inputs_fail_closed(self):
        randomizer = random.Random(0x48414D44)
        alphabet = '{}[],:"\\abcdefghijklmnopqrstuvwxyz0123456789-._?=&%'
        for _ in range(1500):
            value = ''.join(
                randomizer.choice(alphabet) for _ in range(randomizer.randrange(0, 768))
            )
            # Parser rejection must be a normal validation outcome, never an
            # interpreter/system exception or a successful non-object import.
            try:
                parsed = configuration_manager.parse_import(value.encode())
                self.assertIsInstance(parsed, dict)
            except (ValueError, TypeError, UnicodeError, json.JSONDecodeError):
                pass
            web_portal.parse_query('/fuzz?' + value)
            method, path = web_portal.parse_request_line(value)
            self.assertTrue(
                (method is None and path is None) or
                (isinstance(method, str) and isinstance(path, str))
            )

    def test_manifest_shape_mutations_are_rejected(self):
        candidates = [None, [], '', 1, {}, {'format_version': 999}]
        for value in candidates:
            with self.assertRaises((ValueError, TypeError, KeyError)):
                update_security.validate_universal_manifest(value)


if __name__ == '__main__':
    unittest.main()

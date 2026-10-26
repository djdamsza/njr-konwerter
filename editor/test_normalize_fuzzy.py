import time
import unittest

from app import _levenshtein_within, _merge_fuzzy_name_groups


def _group(name):
    return {'variants': {name}, 'items': [{'before': name}]}


class TestFuzzyNames(unittest.TestCase):
    def test_typo_joins_the_same_prefix(self):
        groups = _merge_fuzzy_name_groups({
            'wojciechgasowski': _group('Wojciech Gąsowski'),
            'wojceichgasowski': _group('Wojceich Gasowski'),
            'abba': _group('ABBA'),
        })
        joined = [data for data in groups.values() if len(data['variants']) > 1]
        self.assertEqual(len(joined), 1)
        self.assertEqual(joined[0]['variants'], {'Wojciech Gąsowski', 'Wojceich Gasowski'})

    def test_distant_chain_stays_apart(self):
        self.assertTrue(_levenshtein_within('wojciech', 'wojceich'))
        self.assertFalse(_levenshtein_within('wojciechgasowski', 'kult'))

    def test_thousands_of_names_finish_quickly(self):
        groups = {f'art{i:05d}name': _group(f'Art {i}') for i in range(4000)}
        groups['art00001name'] = _group('Art 1')
        groups['art00001nam'] = _group('Art 1 typo')
        started = time.perf_counter()
        merged = _merge_fuzzy_name_groups(groups)
        elapsed = time.perf_counter() - started
        self.assertLess(elapsed, 1.5)
        self.assertGreaterEqual(len(merged), 4000)


if __name__ == '__main__':
    unittest.main()

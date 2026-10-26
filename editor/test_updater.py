#!/usr/bin/env python3
"""Aktualizacje idą ze strony, nie z GitHuba. Testy: test_update_offer.py."""
from __future__ import annotations

import unittest

import test_update_offer


if __name__ == "__main__":
    suite = unittest.defaultTestLoader.loadTestsFromModule(test_update_offer)
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    raise SystemExit(0 if result.wasSuccessful() else 1)

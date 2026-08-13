from __future__ import annotations

import sys
import unittest


def main() -> int:
    loader = unittest.defaultTestLoader
    suite = loader.discover(start_dir="tests", pattern="test*.py", top_level_dir=".")
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    raise SystemExit(main())

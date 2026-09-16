"""
Run all tests with: python tests/run_tests.py
"""

from pathlib import Path
import sys
import unittest


def main() -> int:
    """
    Discover the full test suite and return a nonzero status on failure.
    """
    tests_dir = Path(__file__).resolve().parent
    sys.path.insert(0, str(tests_dir.parent))
    suite = unittest.defaultTestLoader.discover(
        start_dir=str(tests_dir),
        pattern="test_*.py",
    )
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    sys.exit(main())

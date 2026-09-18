import unittest

def main():
    print("Running comprehensive data leakage audit suite...")
    suite = unittest.defaultTestLoader.discover("tests/leakage", pattern="test_*.py")
    runner = unittest.TextTestRunner(verbosity=2)
    res = runner.run(suite)
    if not res.wasSuccessful():
        raise SystemExit("LEAKAGE AUDIT FAILED!")
    print("LEAKAGE AUDIT: 100% PASS (Zero lookahead detected)")

if __name__ == "__main__":
    main()

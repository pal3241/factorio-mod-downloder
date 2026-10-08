import unittest

from manager import factorio_branch, factorio_version_compatible


class FactorioCompatibilityTests(unittest.TestCase):
    def test_branch(self):
        self.assertEqual(factorio_branch("2.1.21"), "2.1")
        self.assertEqual(factorio_branch("2.0"), "2.0")

    def test_exact_branch(self):
        self.assertTrue(factorio_version_compatible("2.1", "2.1.21"))
        self.assertFalse(factorio_version_compatible("2.0", "2.1.21"))

    def test_explicit_range(self):
        self.assertTrue(factorio_version_compatible("2.0 - 2.1", "2.1.21"))
        self.assertTrue(factorio_version_compatible("1.1 - 2.1", "2.0.77"))
        self.assertFalse(factorio_version_compatible("1.1 - 2.0", "2.1.21"))


if __name__ == "__main__":
    unittest.main()

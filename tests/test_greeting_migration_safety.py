import unittest
from unittest.mock import patch
from tools.replace_yo_greeting import replacement, proposal

class GreetingMigrationSafetyTests(unittest.TestCase):
    def test_replaces_only_initial_word(self):
        self.assertEqual(replacement("Yo Luke, saw your fight. Want the details?"),"Hey Luke, saw your fight. Want the details?")
        self.assertEqual(replacement("M1: Yo Luke, saw your fight.\nM2: Pitch\nM3: Want the details?"),"M1: Hey Luke, saw your fight.\nM2: Pitch\nM3: Want the details?")
        self.assertEqual(replacement("Hey Luke, saw your fight."),"Hey Luke, saw your fight.")

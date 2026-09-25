import unittest
from decimal import Decimal
from types import SimpleNamespace

from app.services.assessment import complete, flag, ratio


class AssessmentTest(unittest.TestCase):
    def test_decimal_financial_inputs_are_assessed(self):
        rows = [SimpleNamespace(cash=Decimal('90.00'), billed=Decimal('100.00'))]
        self.assertEqual(ratio(rows, 'cash', 'billed'), 90)

    def test_missing_is_not_zero(self):
        rows = [SimpleNamespace(nrw=None, vol_produced=100)]
        self.assertIsNone(ratio(rows, "nrw", "vol_produced"))
        self.assertEqual(flag(None, 27, 35, lower=True), "NOT ASSESSED")

    def test_measured_zero_is_assessed(self):
        rows = [SimpleNamespace(nrw=0, vol_produced=100)]
        self.assertEqual(ratio(rows, "nrw", "vol_produced"), 0.0)
        self.assertEqual(flag(0, 27, 35, lower=True), "GOOD")

    def test_zero_denominator_is_not_assessed(self):
        rows = [SimpleNamespace(nrw=0, vol_produced=0)]
        self.assertIsNone(ratio(rows, "nrw", "vol_produced"))

    def test_explicit_missing_marker_is_preserved(self):
        row = SimpleNamespace(nrw=0, vol_produced=100, _missing_metrics={"nrw"})
        self.assertFalse(complete([row], "nrw", "vol_produced"))
        self.assertIsNone(ratio([row], "nrw", "vol_produced"))

"""Every published threshold, including the points where bands touch."""

from django.test import SimpleTestCase

from planner.risk import (
    HIGH,
    LOW,
    MODERATE,
    NO_TRAVEL,
    SEVERE,
    classify,
    classify_rain,
    classify_snow,
    classify_wind,
)


class WindBandTests(SimpleTestCase):
    def test_below_25_is_low(self):
        self.assertEqual(classify_wind(0), LOW)
        self.assertEqual(classify_wind(24.999), LOW)

    def test_25_starts_moderate(self):
        self.assertEqual(classify_wind(25), MODERATE)
        self.assertEqual(classify_wind(34.999), MODERATE)

    def test_35_starts_high(self):
        self.assertEqual(classify_wind(35), HIGH)
        self.assertEqual(classify_wind(44.999), HIGH)

    def test_45_starts_severe(self):
        self.assertEqual(classify_wind(45), SEVERE)
        self.assertEqual(classify_wind(54.999), SEVERE)

    def test_55_starts_no_travel(self):
        self.assertEqual(classify_wind(55), NO_TRAVEL)
        self.assertEqual(classify_wind(100), NO_TRAVEL)

    def test_negative_wind_is_treated_as_zero(self):
        self.assertEqual(classify_wind(-5), LOW)


class RainBandTests(SimpleTestCase):
    def test_below_0_10_is_low(self):
        self.assertEqual(classify_rain(0), LOW)
        self.assertEqual(classify_rain(0.0999), LOW)

    def test_0_10_starts_moderate_until_shared_0_25(self):
        self.assertEqual(classify_rain(0.10), MODERATE)
        self.assertEqual(classify_rain(0.2499), MODERATE)

    def test_shared_0_25_takes_the_worse_band(self):
        self.assertEqual(classify_rain(0.25), HIGH)
        self.assertEqual(classify_rain(0.4999), HIGH)

    def test_shared_0_50_takes_severe_and_1_00_stays_severe(self):
        self.assertEqual(classify_rain(0.50), SEVERE)
        self.assertEqual(classify_rain(1.00), SEVERE)

    def test_above_1_00_is_no_travel(self):
        self.assertEqual(classify_rain(1.0001), NO_TRAVEL)
        self.assertEqual(classify_rain(2), NO_TRAVEL)


class SnowBandTests(SimpleTestCase):
    def test_below_0_5_is_low(self):
        self.assertEqual(classify_snow(0), LOW)
        self.assertEqual(classify_snow(0.4999), LOW)

    def test_0_5_starts_moderate_until_shared_1(self):
        self.assertEqual(classify_snow(0.5), MODERATE)
        self.assertEqual(classify_snow(0.9999), MODERATE)

    def test_shared_1_takes_the_worse_band(self):
        self.assertEqual(classify_snow(1.0), HIGH)
        self.assertEqual(classify_snow(1.9999), HIGH)

    def test_shared_2_takes_severe_and_3_stays_severe(self):
        self.assertEqual(classify_snow(2.0), SEVERE)
        self.assertEqual(classify_snow(3.0), SEVERE)

    def test_above_3_is_no_travel(self):
        self.assertEqual(classify_snow(3.0001), NO_TRAVEL)
        self.assertEqual(classify_snow(4), NO_TRAVEL)


class LoadRuleTests(SimpleTestCase):
    def test_55_mph_is_no_travel_for_any_load(self):
        for load in (0, 1, 30000, 80000):
            self.assertEqual(classify(55, 0, 0, load).level, NO_TRAVEL)

    def test_45_to_54_and_load_over_30000_is_no_travel(self):
        self.assertEqual(classify(45, 0, 0, 30000.01).level, NO_TRAVEL)
        self.assertEqual(classify(54.999, 0, 0, 40000).level, NO_TRAVEL)
        self.assertEqual(classify(50, 0, 0, 30001).wind_after_load, NO_TRAVEL)

    def test_exactly_30000_does_not_escalate_45_to_54(self):
        result = classify(45, 0, 0, 30000)
        self.assertEqual(result.level, SEVERE)
        self.assertEqual(classify(54.999, 0, 0, 30000).level, SEVERE)

    def test_35_to_44_and_load_over_40000_is_severe(self):
        self.assertEqual(classify(35, 0, 0, 40000.01).level, SEVERE)
        self.assertEqual(classify(44.999, 0, 0, 50000).level, SEVERE)

    def test_exactly_40000_does_not_escalate_35_to_44(self):
        self.assertEqual(classify(35, 0, 0, 40000).level, HIGH)
        self.assertEqual(classify(44.999, 0, 0, 40000).level, HIGH)

    def test_34_999_does_not_use_the_35_mph_load_rule(self):
        self.assertEqual(classify(34.999, 0, 0, 80000).level, MODERATE)

    def test_44_999_with_a_heavy_load_is_severe_not_no_travel(self):
        self.assertEqual(classify(44.999, 0, 0, 80000).level, SEVERE)

    def test_45_with_a_heavy_load_is_no_travel(self):
        self.assertEqual(classify(45, 0, 0, 80000).level, NO_TRAVEL)

    def test_load_does_not_reclassify_rain_or_snow(self):
        result = classify(10, 0.60, 0, 80000)
        self.assertEqual(result.level, SEVERE)
        self.assertEqual(result.wind_after_load, LOW)
        self.assertIn("rain", result.reason)
        self.assertNotIn("load", result.reason)


class CombinedLevelTests(SimpleTestCase):
    def test_worst_condition_wins(self):
        self.assertEqual(classify(10, 0.05, 1.5, 1000).level, HIGH)
        self.assertEqual(classify(10, 1.2, 0, 1000).level, NO_TRAVEL)
        self.assertEqual(classify(10, 1.0, 3.0, 1000).level, SEVERE)
        self.assertEqual(classify(10, 0.2, 3.1, 1000).level, NO_TRAVEL)

    def test_calm_weather_is_low(self):
        result = classify(0, 0, 0, 0)
        self.assertEqual(result.level, LOW)
        self.assertEqual(result.score, 0)
        self.assertEqual(result.reason, "Low from wind, rain, snow")

    def test_load_escalation_is_named_in_the_reason(self):
        result = classify(40, 0, 0, 45000)
        self.assertEqual(result.level, SEVERE)
        self.assertEqual(result.wind_level, HIGH)
        self.assertIn("wind + load", result.reason)

    def test_rain_no_travel_beats_a_load_escalated_wind(self):
        self.assertEqual(classify(40, 1.5, 0, 50000).level, NO_TRAVEL)

    def test_no_travel_score_is_worse_than_severe(self):
        self.assertGreater(classify(55, 0, 0, 0).score, classify(50, 0, 0, 0).score)

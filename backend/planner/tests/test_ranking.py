"""Recommendation order: No Travel, Severe, High, average risk, time."""

from django.test import SimpleTestCase

from planner.ranking import RouteScore, SegmentRisk, best_index, rank_order, score_segments


def score(**overrides) -> RouteScore:
    base = dict(
        no_travel_miles=0,
        severe_miles=0,
        high_miles=0,
        moderate_miles=0,
        low_miles=100,
        average_risk=0,
        duration_seconds=3600,
    )
    base.update(overrides)
    return RouteScore(**base)


class RankingOrderTests(SimpleTestCase):
    def test_fewer_severe_miles_win_over_high_miles_and_time(self):
        scores = [
            score(severe_miles=40, high_miles=0, duration_seconds=1000),
            score(severe_miles=10, high_miles=200, duration_seconds=9000),
        ]
        self.assertEqual(best_index(scores), 1)

    def test_fewer_high_miles_win_when_severe_miles_tie(self):
        scores = [
            score(severe_miles=5, high_miles=80),
            score(severe_miles=5, high_miles=20),
        ]
        self.assertEqual(best_index(scores), 1)

    def test_lower_average_risk_wins_when_severe_and_high_tie(self):
        scores = [
            score(average_risk=0.8, moderate_miles=80),
            score(average_risk=0.2, moderate_miles=20),
        ]
        self.assertEqual(best_index(scores), 1)

    def test_shorter_time_wins_when_every_risk_field_ties(self):
        scores = [
            score(duration_seconds=4000),
            score(duration_seconds=2500),
        ]
        self.assertEqual(best_index(scores), 1)

    def test_no_travel_miles_outrank_a_large_severe_total(self):
        scores = [
            score(no_travel_miles=10, severe_miles=0, average_risk=4, duration_seconds=100),
            score(no_travel_miles=0, severe_miles=500, average_risk=3, duration_seconds=20000),
        ]
        self.assertEqual(best_index(scores), 1)

    def test_complete_tie_keeps_the_earlier_route(self):
        scores = [score(), score(), score()]
        self.assertEqual(best_index(scores), 0)

    def test_full_preference_order(self):
        scores = [
            score(no_travel_miles=5, severe_miles=0, high_miles=0, duration_seconds=1000),
            score(severe_miles=30, high_miles=0, average_risk=3, duration_seconds=1000),
            score(severe_miles=30, high_miles=10, average_risk=2, duration_seconds=1000),
            score(severe_miles=0, high_miles=40, average_risk=2, duration_seconds=8000),
            score(severe_miles=0, high_miles=40, average_risk=1, duration_seconds=9000),
            score(severe_miles=0, high_miles=0, average_risk=0.4, duration_seconds=5000),
            score(severe_miles=0, high_miles=0, average_risk=0.4, duration_seconds=3000),
        ]
        # 6 then 5 (same risk, 6 is shorter), 4 then 3 (fewer average at the
        # same High miles), 1 then 2 (fewer High miles at the same Severe),
        # and 0 last because No Travel miles outrank Severe miles.
        self.assertEqual(rank_order(scores), [6, 5, 4, 3, 1, 2, 0])


class ScoreSegmentTests(SimpleTestCase):
    def test_miles_stay_in_one_bucket_and_average_is_weighted(self):
        result = score_segments(
            [
                SegmentRisk("low", 0),
                SegmentRisk("severe", 25),
                SegmentRisk("high", 25),
                SegmentRisk("low", 50),
            ],
            duration_seconds=1000,
        )
        self.assertEqual(result.severe_miles, 25)
        self.assertEqual(result.high_miles, 25)
        self.assertEqual(result.low_miles, 50)
        self.assertEqual(result.no_travel_miles, 0)
        self.assertAlmostEqual(result.average_risk, 1.25)

    def test_no_travel_miles_are_not_also_counted_as_severe(self):
        result = score_segments([SegmentRisk("no_travel", 40), SegmentRisk("severe", 10)], 100)
        self.assertEqual(result.no_travel_miles, 40)
        self.assertEqual(result.severe_miles, 10)

    def test_moderate_miles_change_the_average_only(self):
        lighter = score_segments([SegmentRisk("moderate", 10), SegmentRisk("low", 90)], 100)
        heavier = score_segments([SegmentRisk("moderate", 50), SegmentRisk("low", 50)], 100)
        self.assertEqual(lighter.severe_miles, heavier.severe_miles)
        self.assertEqual(lighter.high_miles, heavier.high_miles)
        self.assertAlmostEqual(lighter.average_risk, 0.1)
        self.assertAlmostEqual(heavier.average_risk, 0.5)
        self.assertEqual(best_index([heavier, lighter]), 1)

"""The dual-axis presentation must not merge units or invent readings."""

from copy import deepcopy
import unittest

from trend import history_chart


class TrendTests(unittest.TestCase):
    def setUp(self):
        self.history = {
            "temperature": [{"time": 1791676800000, "value": 25.1}, {"time": 1791676805000, "value": 26.2}],
            "humidity": [{"time": 1791676802000, "value": 63}],
        }

    def test_independent_units_and_timestamps_are_retained(self):
        before = deepcopy(self.history)
        spec = history_chart(self.history).to_dict()
        self.assertEqual(self.history, before)
        self.assertEqual(spec["resolve"]["scale"]["y"], "independent")
        temp = spec["layer"][0]["layer"][0]["encoding"]["y"]
        humidity = spec["layer"][1]["layer"][0]["encoding"]["y"]
        self.assertEqual(temp["axis"]["orient"], "left")
        self.assertEqual(temp["axis"]["title"], "温度 / °C")
        self.assertEqual(humidity["axis"]["orient"], "right")
        self.assertEqual(humidity["axis"]["title"], "湿度 / %RH")
        self.assertEqual(humidity["scale"]["domain"], [0, 100])
        temperature_tooltip = spec["layer"][0]["layer"][0]["encoding"]["tooltip"][-1]
        humidity_tooltip = spec["layer"][1]["layer"][0]["encoding"]["tooltip"][-1]
        self.assertEqual(temperature_tooltip["format"], ".1f")
        self.assertEqual(humidity_tooltip["format"], ".0f")
        points = [point for dataset in spec["datasets"].values() for point in dataset]
        self.assertEqual(len(points), 3)
        self.assertEqual(sorted(point["数值"] for point in points), [25.1, 26.2, 63])
        self.assertTrue(any("2026-10-11T08:00:02" == point["时间"] for point in points))

    def test_temperature_axis_does_not_clip_extremes(self):
        self.history["temperature"] = [{"time": 1791676800000, "value": -40}, {"time": 1791676805000, "value": 125}]
        spec = history_chart(self.history).to_dict()
        domain = spec["layer"][0]["layer"][0]["encoding"]["y"]["scale"]["domain"]
        self.assertLessEqual(domain[0], -40)
        self.assertGreaterEqual(domain[1], 125)

    def test_one_missing_series_has_no_synthetic_points(self):
        self.history["temperature"] = []
        spec = history_chart(self.history).to_dict()
        points = [point for dataset in spec["datasets"].values() for point in dataset]
        self.assertEqual([point["数值"] for point in points], [63])
        self.assertEqual(spec["layer"][1]["layer"][1]["mark"]["type"], "point")

    def test_temperature_zero_and_negative_decimals_are_preserved(self):
        self.history["temperature"] = [{"time": 1791676800000, "value": -5.2}, {"time": 1791676805000, "value": 0.0}]
        spec = history_chart(self.history).to_dict()
        points = [point for dataset in spec["datasets"].values() for point in dataset]
        self.assertEqual(sorted(point["数值"] for point in points), [-5.2, 0.0, 63])


if __name__ == "__main__":
    unittest.main()

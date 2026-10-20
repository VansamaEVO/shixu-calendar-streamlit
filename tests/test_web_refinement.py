"""Presentation and bounded observation-history tests; no network or hardware."""
import unittest
from base64 import b64decode
import re

from ui import alcohol_trend_html, expansion_html, motor_controls_heading_html, record_alcohol_sample


NOW = 1_791_610_000_000


def state(raw=1933, at=NOW - 1000, **changes):
    return dict(online=True, alcohol_raw=raw, alcohol_valid=True, alcohol_at=at,
                motor_level=2, motor_pwm=50, motor_valid=True, motor_at=at, **changes)


def chart_source(html):
    return b64decode(re.search(r'data:image/svg\+xml;base64,([^" ]+)', html).group(1)).decode('utf-8')


class WebRefinementTests(unittest.TestCase):
    def test_observations_use_original_timestamps_and_no_cached_duplicates(self):
        original = state()
        history = record_alcohol_sample([], original, True, NOW)
        self.assertEqual(history, [{"time": NOW - 1000, "raw": 1933}])
        self.assertEqual(record_alcohol_sample(history, original, True, NOW + 5000), history)
        self.assertEqual(history[0]["time"], original["alcohol_at"])

    def test_invalid_or_offline_samples_add_one_gap_not_fake_zero(self):
        history = record_alcohol_sample([], state(), True, NOW)
        for online, update in ((False, state()), (True, dict(state(), alcohol_valid=False)),
                               (True, dict(state(), alcohol_raw=None)), (True, state(at=NOW-20000))):
            with self.subTest(online=online, update=update):
                stopped = record_alcohol_sample(history, update, online, NOW)
                self.assertIsNone(stopped[-1]["raw"])
                self.assertEqual(record_alcohol_sample(stopped, update, online, NOW+1000), stopped)
                self.assertNotIn(0, [p["raw"] for p in stopped])

    def test_recovery_cannot_reinsert_older_pre_disconnect_sample(self):
        history = record_alcohol_sample([], state(), True, NOW)
        history = record_alcohol_sample(history, {}, False, NOW)
        self.assertEqual(record_alcohol_sample(history, state(), True, NOW+1000), history)
        newer = record_alcohol_sample(history, state(raw=2000, at=NOW+1000), True, NOW+2000)
        self.assertEqual(newer[-1], dict(time=NOW+1000, raw=2000))

    def test_history_is_bounded_and_only_contains_recent_safe_values(self):
        history = [{"time": NOW-i*5000, "raw": i} for i in range(150)]
        history += [{"time": NOW-3_600_001, "raw": 1000}, {"time": NOW+5001, "raw": 1000},
                    {"time": NOW-1, "raw": True}, {"time": NOW-2, "raw": "<script>"},
                    {"time": NOW-3, "raw": 4096}, {"time": "bad", "raw": 100}, None]
        result = record_alcohol_sample(history, state(at=NOW), True, NOW)
        self.assertEqual(len(result), 120)
        self.assertEqual(result[0]["time"], NOW-119*5000)
        self.assertEqual(result[-1]["time"], NOW)
        self.assertTrue(all(type(p["raw"]) is int and 0 <= p["raw"] <= 4095 for p in result))

    def test_single_sample_is_dot_empty_is_not_a_fake_flat_line(self):
        empty = alcohol_trend_html([], NOW, True)
        self.assertIn("收到有效采样后显示趋势", empty)
        self.assertNotIn("<polyline", empty)
        self.assertNotIn("<circle", empty)
        one_html = alcohol_trend_html([dict(time=NOW-1000, raw=0)], NOW, True)
        one = chart_source(one_html)
        self.assertIn("<circle", one)
        self.assertNotIn("<polyline", one)
        self.assertIn('cy="91.00"', one)
        self.assertIn("纵轴0至5V", one_html)

    def test_gap_is_visible_for_missing_and_explicit_invalid_periods(self):
        for second, expected_lines in ((NOW-1000, 1), (NOW+10000, 0)):
            html = alcohol_trend_html([dict(time=NOW-10000, raw=1000), dict(time=second, raw=2000)], NOW+10000, True)
            self.assertEqual(chart_source(html).count("<polyline"), expected_lines)
        interrupted = alcohol_trend_html([dict(time=NOW-10000, raw=1000), dict(time=NOW-5000, raw=None), dict(time=NOW-1000, raw=2000)], NOW, True)
        self.assertEqual(chart_source(interrupted).count("<circle"), 2)
        self.assertNotIn("<polyline", chart_source(interrupted))

    def test_offline_can_show_labelled_history_not_current_measurement(self):
        html = expansion_html(state(), False, NOW, [dict(time=NOW-1000, raw=1933)])
        self.assertIn("历史片段", html)
        self.assertIn("等待设备", html)
        self.assertNotIn('>2.35<small>', html)
        self.assertNotIn('>中档</strong>', html)
        self.assertNotIn('is-selected', html)

    def test_actual_motor_only_target_is_never_used_for_highlight(self):
        for level, pwm in enumerate((0, 40, 50, 60)):
            current = dict(state(), motor_level=level, motor_pwm=pwm, MotorTarget=3-level)
            html = expansion_html(current, True, NOW)
            self.assertEqual(html.count('class="is-selected"'), 1)
            self.assertIn(f'class="is-selected"><b>{("停", "低", "中", "高")[level]}</b><small>{pwm}%</small>', html)
            self.assertIn(f'{pwm}%', motor_controls_heading_html(current, True, NOW).replace('<small>', '').replace('</small>', ''))
        expired = motor_controls_heading_html(state(), False, NOW+20000)
        self.assertIn('>--</strong>', expired)
        self.assertNotIn('>中档</strong>', expired)

    def test_relative_readings_no_calibrated_claim_or_control_in_overview(self):
        html = expansion_html(state(), True, NOW)
        self.assertIn("拓展功能", html)
        self.assertIn("相对响应指数", html)
        self.assertIn("1933 / 4095", html)
        self.assertIn('href="#calendar-motor-settings"', html)
        self.assertIn("未标定", html)
        self.assertIn("非实测转速", html)
        self.assertNotIn("ppm", html.lower())
        self.assertNotIn("<button", html)
        self.assertNotIn("<script", html)

    def test_icons_and_chart_are_self_contained_streamlit_compatible_images(self):
        html = expansion_html(state(), True, NOW, [dict(time=NOW-1000, raw=1933)])
        encoded = re.findall(r'data:image/svg\+xml;base64,([^" ]+)', html)
        self.assertEqual(len(encoded), 3)
        self.assertNotIn('<svg', html)
        for source in encoded:
            svg = b64decode(source).decode('utf-8')
            self.assertIn('xmlns="http://www.w3.org/2000/svg"', svg)
            self.assertNotIn('<script', svg)
            self.assertNotIn('href=', svg)
        self.assertIn('纵轴0至5V', html)


if __name__ == "__main__":
    unittest.main()

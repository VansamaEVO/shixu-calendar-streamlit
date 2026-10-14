"""Presentation regressions; pure stdlib tests, no Streamlit/network access."""

from datetime import date, datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
import unittest

import ui


class MonthParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.cell_count = 0
        self.selected_count = 0
        self.selected_cell = False
        self.selected_day = None

    def handle_starttag(self, tag, attrs):
        if tag == "td":
            self.cell_count += 1
            self.selected_cell = "calendar-selected" in dict(attrs).get("class", "").split()
            self.selected_count += int(self.selected_cell)

    def handle_endtag(self, tag):
        if tag == "td":
            self.selected_cell = False

    def handle_data(self, data):
        if self.selected_cell and data.strip():
            self.selected_day = data.strip()


class CalendarUiTests(unittest.TestCase):
    def setUp(self):
        self.now = int(datetime(2026, 10, 10, 15, 45, tzinfo=timezone.utc).timestamp() * 1000)
        self.snapshot = {
            "online": True, "ready": True,
            "temperature": 25.1, "humidity": 69,
            "time": datetime(2026, 10, 10, 23, 45),
            "last_time": datetime(2026, 10, 10, 23, 45),
            "low": 5, "high": 45, "humidity_low": 30, "humidity_high": 80,
            "humidity_ready": True, "alarm": False, "muted": False,
            "updated_at": self.now, "time_at": self.now,
        }

    def render(self, **changes):
        return ui.dashboard_html(dict(self.snapshot, **changes), 1, self.now)

    def test_live_snapshot_shows_device_not_browser_clock(self):
        page = self.render()
        self.assertIn("设备在线", page)
        self.assertIn("23:45:00", page)
        self.assertIn("2026 年 10 月 10 日", page)
        self.assertIn("星期六", page)
        self.assertIn("不是手机时间", page)
        self.assertIn(">25.1<small> °C", page)
        self.assertIn(">69<small> %", page)
        self.assertIn("当前无报警", page)
        self.assertNotIn("calendar-clock-frozen", page)

    def test_missing_alarm_is_unknown_not_clear(self):
        page = self.render(alarm=None, muted=False)
        self.assertIn("等待报警状态", page)
        self.assertIn("calendar-unknown", page)
        self.assertIn("不判断是否正在报警", page)
        self.assertNotIn("当前无报警", page)

    def test_missing_muted_flag_does_not_imply_audible_alarm(self):
        page = self.render(alarm=True, muted=None)
        self.assertIn("温湿度越限（声音状态待更新）", page)
        self.assertIn("不能判断当前声音", page)
        self.assertIn("calendar-alarming", page)
        self.assertNotIn("当前提醒已静音", page)
        self.assertNotIn("可在日历设置中临时消音约10秒", page)

    def test_false_alarm_remains_clear_when_muted_unknown(self):
        page = self.render(alarm=False, muted=None)
        self.assertIn("当前无报警", page)
        self.assertNotIn("等待报警状态", page)

    def test_known_muted_alarm(self):
        page = self.render(alarm=True, muted=True)
        self.assertIn("当前提醒已静音", page)
        self.assertIn("calendar-muted", page)
        self.assertIn("临时消音约10秒，仍超限将自动再次报警", page)

    def test_known_unmuted_alarm(self):
        page = self.render(alarm=True, muted=False)
        self.assertIn("温湿度超出提醒范围", page)
        self.assertIn("可在日历设置中临时消音约10秒", page)
        self.assertNotIn("当前提醒已静音", page)

    def test_invalid_boolean_is_unknown(self):
        for bad in ("maybe", "", 2, -1, None):
            with self.subTest(value=bad):
                self.assertIn("等待报警状态", self.render(alarm=bad))

    def test_string_boolean_false_does_not_become_truthy(self):
        self.assertIn("当前无报警", self.render(alarm="false", muted="false"))
        self.assertIn("当前提醒已静音", self.render(alarm="true", muted="1"))

    def test_stale_at_exact_twenty_seconds_freezes_clock_and_clears_sensor(self):
        page = ui.dashboard_html(self.snapshot, 1, self.now + 20_000)
        self.assertIn("等待 51 数据", page)
        self.assertIn("calendar-clock-frozen", page)
        self.assertIn("23:45:00", page)
        self.assertIn("最后记录已冻结", page)
        self.assertIn(">--<small> °C", page)
        self.assertIn(">--<small> %", page)
        self.assertIn("等待报警状态", page)
        self.assertNotIn("当前无报警", page)

    def test_just_before_stale_boundary_is_current(self):
        page = ui.dashboard_html(self.snapshot, 1, self.now + 19_999)
        self.assertIn("设备在线", page)
        self.assertNotIn("calendar-clock-frozen", page)

    def test_future_timestamp_tolerance_matches_backend(self):
        page = self.render(updated_at=self.now + 5_000, time_at=self.now + 5_000)
        self.assertIn("设备在线", page)
        self.assertNotIn("calendar-clock-frozen", page)
        page = self.render(updated_at=self.now + 5_001, time_at=self.now + 5_001)
        self.assertIn("等待 51 数据", page)
        self.assertIn("calendar-clock-frozen", page)
        self.assertIn(">--<small> °C", page)

    def test_gateway_offline_overrides_fresh_mcu_flag(self):
        page = ui.dashboard_html(self.snapshot, 0, self.now)
        self.assertIn("设备离线", page)
        self.assertIn("calendar-clock-frozen", page)
        self.assertIn("最后收到的设备日期", page)
        self.assertIn("等待报警状态", page)
        self.assertNotIn("当前无报警", page)

    def test_stale_time_only_keeps_other_current_values(self):
        page = self.render(time_at=self.now - 20_000)
        self.assertIn("calendar-clock-frozen", page)
        self.assertIn(">25.1<small> °C", page)
        self.assertIn("最后收到的设备日期", page)

    def test_no_device_date_is_explicit_browser_date(self):
        page = ui.dashboard_html({}, 0, self.now)
        self.assertIn("--:--:--", page)
        self.assertIn("浏览日期，非设备时间", page)
        self.assertIn("2026年10月月历", page)
        self.assertNotIn("2026 年 10 月 10 日", page)

    def test_leap_day_has_one_selected_cell_and_correct_weekday(self):
        instant = datetime(2024, 2, 29, 23, 59, 58)
        page = self.render(time=instant, last_time=instant)
        self.assertIn("2024 年 02 月 29 日", page)
        self.assertIn("星期四", page)
        parser = MonthParser()
        parser.feed(page)
        self.assertEqual(parser.selected_count, 1)
        self.assertEqual(parser.selected_day, "29")
        self.assertEqual(parser.cell_count % 7, 0)

    def test_html_escaping_and_invalid_sensor_numbers(self):
        dangerous = '<img src=x onerror="alert(1)">'
        label = ui._month_html(date(2026, 10, 10), dangerous)
        self.assertIn("&lt;img", label)
        self.assertNotIn(dangerous, label)
        self.assertNotIn('<img src=x', label)
        self.assertIn("&quot;", label)
        page = self.render(temperature=dangerous, humidity="Infinity")
        self.assertNotIn("onerror", page)
        self.assertIn(">--<small> °C", page)
        self.assertIn(">--<small> %", page)

    def test_temperature_display_has_one_decimal_including_zero_and_negative(self):
        for value, shown in ((25.1, "25.1"), (25, "25.0"), (0.0, "0.0"), (-12.3, "-12.3")):
            with self.subTest(value=value):
                self.assertIn(f">{shown}<small> °C", self.render(temperature=value))
        self.assertIn(">69<small> %", self.render())
        self.assertNotIn(">69.0<small> %", self.render())

    def test_invalid_temperature_has_no_synthetic_zero(self):
        for value in (None, True, float("nan"), float("inf"), -40.1, 125.1):
            with self.subTest(value=value):
                page = self.render(temperature=value)
                self.assertIn(">--<small> °C", page)
                self.assertNotIn(">0.0<small> °C", page)

    def test_malformed_timestamp_and_out_of_rtc_year_do_not_crash(self):
        self.assertEqual(ui._timestamp_label(1e300), "--")
        self.assertIsNone(ui._instant("9999-12-01"))
        page = self.render(updated_at=1e300)
        self.assertIn("最近上报 --", page)
        self.assertIn("等待 51 数据", page)

    def test_local_mobile_styles_have_small_width_and_accessible_controls(self):
        css = (Path(__file__).resolve().parents[1] / "assets" / "theme.css").read_text(encoding="utf-8")
        self.assertIn("@media (max-width: 359px)", css)
        self.assertIn("font-size: 47px", css)
        self.assertIn("min-height: 44px", css)
        self.assertIn("font-size: 16px", css)
        self.assertIn("focus-visible", css)
        self.assertNotIn("@import", css)
        self.assertNotIn("url(https://", css)

    def test_branding_and_no_remote_assets_or_executable_html(self):
        self.assertIn("时序日历", ui.header_html())
        self.assertIn("设备设置", ui.navigation_html())
        for page in (self.render(), ui.header_html(), ui.navigation_html(), ui.settings_heading_html(True), ui.footer_html()):
            self.assertNotIn("<script", page)
            self.assertNotIn("<iframe", page)
            self.assertNotIn("https://", page)

    def test_settings_are_prominent_and_have_anchor_navigation(self):
        navigation = ui.navigation_html()
        self.assertIn('href="#calendar-settings"', navigation)
        self.assertIn('href="#calendar-monitor"', navigation)
        self.assertIn('href="#calendar-history"', navigation)
        self.assertIn('id="calendar-settings"', ui.settings_heading_html(True))
        self.assertIn("可以调整设备", ui.settings_heading_html(True))
        self.assertIn("等待设备上线", ui.settings_heading_html(False))
        self.assertLess(navigation.index('href="#calendar-history"'), navigation.index('href="#calendar-settings"'))

    def test_settings_summary_is_device_state_not_draft(self):
        page = ui.settings_summary_html(self.snapshot)
        self.assertIn("5 °C", page)
        self.assertIn("45 °C", page)
        self.assertIn("30%", page)
        self.assertIn("80%", page)
        self.assertIn("当前无报警", page)
        self.assertIn('left:5%;width:40%', page)
        offline = ui.settings_summary_html(dict(self.snapshot, online=False))
        self.assertIn("-- °C", offline)
        self.assertIn("等待信息", offline)
        self.assertNotIn("当前无报警", offline)
        self.assertNotIn('style="left:', offline)

    def test_summary_unknown_flags_do_not_claim_silence(self):
        page = ui.settings_summary_html(dict(self.snapshot, alarm=True, muted=None))
        self.assertIn("声音状态待更新", page)
        self.assertNotIn("临时消音中", page)
        page = ui.settings_summary_html(dict(self.snapshot, alarm=True, muted=True))
        self.assertIn("临时消音中", page)
        self.assertIn("约10秒后仍超限会再次报警", page)

    def test_trend_empty_grid_and_safe_text(self):
        heading = ui.trend_heading_html()
        self.assertIn('id="calendar-history"', heading)
        self.assertIn("温湿度变化", heading)
        self.assertIn("最多120次采样", heading)
        page = ui.empty_trend_html("<script>not-a-reading</script>")
        self.assertEqual(page.count('class="calendar-grid-row"'), 5)
        self.assertIn("网格仅为坐标参考", page)
        self.assertIn("温度 °C", page)
        self.assertIn("湿度 %RH", page)
        self.assertIn("&lt;script&gt;", page)
        self.assertNotIn("<script>", page)


if __name__ == "__main__":
    unittest.main()

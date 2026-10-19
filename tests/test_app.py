"""真实 Streamlit AppTest：所有网络入口封闭，使用虚构授权与设备。"""

from copy import deepcopy
from pathlib import Path
import os
import sys
import time
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import streamlit as st
from streamlit.testing.v1 import AppTest

from onenet import OneNetClient, OneNetError, validate_params


TEST_SECRETS = {
    "ONENET_TOKEN": "unit-test-token",
    "ONENET_PRODUCT_ID": "test-product",
    "ONENET_DEVICE_NAME": "test-device",
}


def properties(*, age=0, online=True, ready=True, temperature=27.1, humidity=61):
    now = int(time.time() * 1000) - age
    values = {
        "CurrentTemperature": temperature,
        "CurrentHumidity": humidity,
        "DeviceTime": "2026-10-10 13:45:22",
        "TemperatureLow": 5,
        "TemperatureHigh": 45,
        "HumidityLow": 30,
        "HumidityHigh": 80,
        "AlarmActive": False,
        "AlarmMuted": False,
        "McuOnline": online,
        "ControlReady": ready,
        "TemperatureValid": True,
        "HumidityValid": True,
    }
    return [{"identifier": key, "value": value, "time": now} for key, value in values.items()]


def by_label(elements, label):
    return next(item for item in elements if item.label == label)


def html_text(app):
    return "\n".join(item.proto.body for item in app.get("html"))


class AppTests(unittest.TestCase):
    def setUp(self):
        st.cache_data.clear()
        st.cache_resource.clear()
        self.environment = patch.dict(os.environ, {key: "" for key in TEST_SECRETS})
        self.environment.start()
        self.addCleanup(self.environment.stop)
        # 意外遗漏任何假接口时立即失败，不允许读取/控制真实设备。
        self.network = patch("requests.sessions.Session.request", side_effect=AssertionError("test network is blocked"))
        self.network_mock = self.network.start()
        self.addCleanup(self.network.stop)
        self.live_payload = {"properties": properties(), "gateway_status": 1}
        self.read_patch = patch.object(OneNetClient, "read_data", side_effect=lambda: deepcopy(self.live_payload))
        self.read_mock = self.read_patch.start()
        self.addCleanup(self.read_patch.stop)
        self.history_patch = patch.object(OneNetClient, "read_history", return_value={"temperature": [], "humidity": []})
        self.history_mock = self.history_patch.start()
        self.addCleanup(self.history_patch.stop)
        self.control_patch = patch.object(OneNetClient, "control", side_effect=self.confirm_control)
        self.control_mock = self.control_patch.start()
        self.addCleanup(self.control_patch.stop)

    def tearDown(self):
        self.network_mock.assert_not_called()
        st.cache_data.clear()
        st.cache_resource.clear()

    def confirm_control(self, params):
        params = validate_params(params)
        updated = deepcopy(self.live_payload["properties"])
        for item in updated:
            item["time"] = int(time.time() * 1000)
            if item["identifier"] in params:
                item["value"] = params[item["identifier"]]
        self.live_payload = {"properties": updated, "gateway_status": 1}
        return {"confirmed": True, "properties": deepcopy(updated)}

    def app(self, secrets=True):
        result = AppTest.from_file(ROOT / "app.py", default_timeout=15)
        # 即使测试“未配置”，也显式隔离机器上可能存在的真实 secrets.toml。
        result.secrets.update(TEST_SECRETS if secrets else {key: "" for key in TEST_SECRETS})
        result.run()
        self.assertEqual(len(result.exception), 0)
        return result

    def test_missing_secrets_fail_closed(self):
        app = self.app(secrets=False)
        self.assertTrue(any("尚未配置" in warning.value for warning in app.warning))
        self.assertEqual(len(app.text_input), 0)
        self.read_mock.assert_not_called()
        self.history_mock.assert_not_called()
        self.control_mock.assert_not_called()

    def test_public_page_reads_without_any_login(self):
        app = self.app()
        self.assertNotIn("网页访问密码", [item.label for item in app.text_input])
        self.assertNotIn("进入时序日历", [item.label for item in app.button])
        self.assertNotIn("退出登录", [item.label for item in app.button])
        self.read_mock.assert_called()
        self.history_mock.assert_called()
        self.control_mock.assert_not_called()

    def test_expansion_actual_app_reads_without_adding_motor_controls(self):
        now = int(time.time() * 1000)
        additions = dict(AlcoholRaw=1933, AlcoholValid=True, MotorLevel=2, MotorPWM=55, MotorValid=True)
        self.live_payload['properties'] += [dict(identifier=k, value=v, time=now) for k, v in additions.items()]
        app = self.app()
        html = html_text(app)
        self.assertIn('酒精检测', html)
        self.assertIn('2.35', html)
        self.assertIn('>中档<', html)
        self.assertIn('55%', html)
        self.assertNotIn('MotorLevel', [item.key for item in app.button])
        self.control_mock.assert_not_called()

    def test_expansion_api_error_does_not_keep_live_motor_or_alcohol(self):
        self.read_mock.side_effect = OneNetError('离线测试异常')
        app = self.app()
        html = html_text(app)
        self.assertIn('酒精检测', html)
        self.assertNotIn('>停止<', html)
        self.assertNotIn('>0.00<', html)
        self.assertIn('等待设备', html)
        self.control_mock.assert_not_called()

    def test_cloud_motor_buttons_disabled_until_model_and_state_are_ready(self):
        app = self.app()
        for level in range(4):
            self.assertTrue(app.button(key=f'cloud_motor_{level}').disabled)
        self.control_mock.assert_not_called()

    def test_cloud_motor_click_uses_target_but_displays_actual_return(self):
        now = int(time.time() * 1000)
        self.live_payload['properties'] += [dict(identifier=k, value=v, time=now) for k, v in
            dict(MotorTarget=0, MotorLevel=0, MotorPWM=0, MotorValid=True).items()]
        def motor_confirm(params):
            validate_params(params)
            self.assertEqual(params, {'MotorTarget': 2})
            for item in self.live_payload['properties']:
                item['time'] = int(time.time() * 1000)
                if item['identifier'] in ('MotorTarget', 'MotorLevel'): item['value'] = 2
                if item['identifier'] == 'MotorPWM': item['value'] = 55
            return dict(confirmed=True, properties=deepcopy(self.live_payload['properties']))
        self.control_mock.side_effect = motor_confirm
        app = self.app()
        self.assertFalse(app.button(key='cloud_motor_2').disabled)
        app.button(key='cloud_motor_2').click().run()
        self.assertEqual(len(app.exception), 0)
        self.control_mock.assert_called_once_with({'MotorTarget': 2})
        self.assertIn('>中档<', html_text(app))
        self.assertTrue(any('已核对' in item.value for item in app.success))

    def test_history_precedes_visible_segmented_settings(self):
        app = self.app()
        self.assertEqual([item.label for item in app.expander], ["连接信息与操作记录"])
        page = html_text(app)
        self.assertIn('href="#calendar-settings"', page)
        self.assertLess(page.index('id="calendar-monitor"'), page.index('id="calendar-history"'))
        self.assertLess(page.index('id="calendar-history"'), page.index('id="calendar-settings"'))
        self.assertEqual([item.label for item in app.tabs], ["日期时间", "温度提醒", "湿度提醒", "蜂鸣器"])
        self.assertIn("温湿度变化", page)
        self.assertIn("当前温度范围", page)
        self.assertIn("当前湿度范围", page)
        self.assertIn("连接设备后，温湿度变化会显示在这里", page)
        self.control_mock.assert_not_called()

    def test_history_error_keeps_empty_grid_and_settings(self):
        self.history_mock.side_effect = RuntimeError("fake transport failure")
        app = self.app()
        self.assertIn("历史曲线暂不可用", html_text(app))
        self.assertIn('<div class="calendar-empty-grid">', html_text(app))
        self.assertFalse(by_label(app.button, "保存温度范围").disabled)
        self.control_mock.assert_not_called()

    def test_both_series_render_one_dual_axis_chart(self):
        now = int(time.time() * 1000)
        self.history_mock.return_value = {
            "temperature": [{"time": now - 5000, "value": 25}, {"time": now, "value": 26}],
            "humidity": [{"time": now - 5000, "value": 63}, {"time": now, "value": 64}],
        }
        app = self.app()
        self.assertEqual(len(app.get("vega_lite_chart")), 1)
        self.assertEqual(len(app.radio), 0)
        self.assertTrue(any("温度 2 点 / 湿度 2 点" in caption.value for caption in app.caption))
        self.assertNotIn('<div class="calendar-empty-grid">', html_text(app))
        self.control_mock.assert_not_called()

    def test_setting_tabs_preserve_drafts_when_switched(self):
        app = self.app()
        app.session_state["draft_time"] = "11:12:13"
        app.session_state["draft_low"] = 8
        app.session_state["draft_humidity_low"] = 25
        app.session_state["draft_humidity_high"] = 85
        app.session_state["settings_sections"] = "温度提醒"
        app.run()
        self.assertEqual(len(app.exception), 0)
        self.assertEqual(app.text_input(key="draft_time").value, "11:12:13")
        self.assertEqual(app.number_input(key="draft_low").value, 8)
        self.assertEqual(app.number_input(key="draft_humidity_low").value, 25)
        self.assertEqual(app.number_input(key="draft_humidity_high").value, 85)
        self.control_mock.assert_not_called()

    def test_current_limits_summary_does_not_replace_editing_drafts(self):
        app = self.app()
        app.session_state["draft_low"] = 7
        app.session_state["draft_high"] = 39
        updated = properties()
        for item in updated:
            if item["identifier"] == "TemperatureLow":
                item["value"] = 9
            if item["identifier"] == "TemperatureHigh":
                item["value"] = 41
        self.live_payload = {"properties": updated, "gateway_status": 1}
        st.cache_data.clear()
        app.run()
        self.assertEqual(len(app.exception), 0)
        self.assertEqual(app.number_input(key="draft_low").value, 7)
        self.assertEqual(app.number_input(key="draft_high").value, 39)
        self.assertIn("9 °C", html_text(app))
        self.assertIn("41 °C", html_text(app))
        self.control_mock.assert_not_called()

    def test_unknown_sound_state_is_not_claimed_as_playing(self):
        changed = properties()
        for item in changed:
            if item["identifier"] == "AlarmActive":
                item["value"] = True
            if item["identifier"] == "AlarmMuted":
                item["value"] = "unknown"
        self.live_payload = {"properties": changed, "gateway_status": 1}
        app = self.app()
        captions = [item.value for item in app.caption]
        self.assertIn("报警已触发，声音状态待更新。", captions)
        self.assertNotIn("当前温度报警正在发声。", captions)
        self.assertTrue(by_label(app.button, "消音约10秒").disabled)
        self.assertTrue(by_label(app.button, "恢复声音").disabled)
        self.control_mock.assert_not_called()

    def test_public_dashboard_renders_real_values_and_controls(self):
        app = self.app()
        self.assertIn(">27.1<small> °C", html_text(app))
        self.assertIn("61", html_text(app))
        self.assertFalse(by_label(app.button, "保存温度范围").disabled)
        self.assertEqual(app.number_input(key="draft_low").value, 5)
        self.assertEqual(app.number_input(key="draft_high").value, 45)
        self.assertEqual(app.number_input(key="draft_humidity_low").value, 30)
        self.assertEqual(app.number_input(key="draft_humidity_high").value, 80)
        self.assertFalse(by_label(app.button, "保存湿度范围").disabled)
        self.read_mock.assert_called()
        self.history_mock.assert_called()
        self.control_mock.assert_not_called()

    def test_gateway_offline_hides_sensor_values_and_disables_controls(self):
        self.live_payload = {"properties": properties(temperature=113, humidity=97), "gateway_status": 0}
        app = self.app()
        self.assertTrue(by_label(app.button, "保存温度范围").disabled)
        self.assertTrue(by_label(app.button, "写入设备时间").disabled)
        self.assertTrue(by_label(app.button, "一键同步北京时间").disabled)
        self.assertTrue(by_label(app.button, "保存湿度范围").disabled)
        self.assertNotIn('>113<', html_text(app))
        self.assertNotIn('>97<', html_text(app))
        self.control_mock.assert_not_called()

    def test_stale_data_hides_sensor_values_and_disables_controls(self):
        self.live_payload = {"properties": properties(age=30_000, temperature=113, humidity=97), "gateway_status": 1}
        app = self.app()
        self.assertTrue(by_label(app.button, "保存温度范围").disabled)
        self.assertTrue(app.number_input(key="draft_low").disabled)
        self.assertTrue(app.number_input(key="draft_humidity_low").disabled)
        self.assertNotIn('>113<', html_text(app))
        self.assertNotIn('>97<', html_text(app))
        self.control_mock.assert_not_called()

    def test_drafts_survive_poll_rerun(self):
        app = self.app()
        # AppTest 与浏览器一样不发送未提交表单的值。这里验证服务端
        # 已持有的编辑草稿不被监测刷新覆盖，前端未提交输入需真机验证。
        app.session_state["draft_low"] = 9
        app.session_state["draft_high"] = 38
        app.session_state["draft_humidity_low"] = 20
        app.session_state["draft_humidity_high"] = 90
        app.session_state["draft_time"] = "11:12:13"
        st.cache_data.clear()
        self.live_payload = {"properties": properties(temperature=28), "gateway_status": 1}
        app.run()
        self.assertEqual(len(app.exception), 0)
        self.assertEqual(app.number_input(key="draft_low").value, 9)
        self.assertEqual(app.number_input(key="draft_high").value, 38)
        self.assertEqual(app.number_input(key="draft_humidity_low").value, 20)
        self.assertEqual(app.number_input(key="draft_humidity_high").value, 90)
        self.assertEqual(app.text_input(key="draft_time").value, "11:12:13")
        self.control_mock.assert_not_called()

    def test_poll_read_error_hides_last_values_and_disables_control(self):
        app = self.app()
        st.cache_data.clear()
        self.read_mock.side_effect = RuntimeError("unit-test transport failure")
        app.run()
        self.assertEqual(len(app.exception), 0)
        self.assertTrue(by_label(app.button, "保存温度范围").disabled)
        self.assertTrue(by_label(app.button, "保存湿度范围").disabled)
        self.assertTrue(any("暂时无法访问" in item.value for item in app.warning))
        self.assertIn('>--<', html_text(app))
        self.control_mock.assert_not_called()

    def test_invalid_clock_never_calls_control(self):
        app = self.app()
        app.text_input(key="draft_time").input("bad-time")
        by_label(app.button, "写入设备时间").click()
        app.run()
        self.assertEqual(len(app.exception), 0)
        self.assertTrue(any("时:分:秒" in item.value for item in app.warning))
        self.control_mock.assert_not_called()

    def test_unconfirmed_control_never_reports_success(self):
        app = self.app()
        self.control_mock.side_effect = None
        self.control_mock.return_value = {"confirmed": False}
        by_label(app.button, "保存温度范围").click()
        app.run()
        self.assertEqual(len(app.exception), 0)
        self.assertEqual(len(app.success), 0)
        self.assertTrue(any("尚未确认" in item.value for item in app.warning))

    def test_legacy_expired_login_does_not_gate_the_public_page(self):
        app = self.app()
        app.session_state["login_until"] = time.time() - 1
        self.read_mock.reset_mock()
        self.history_mock.reset_mock()
        st.cache_data.clear()
        app.run()
        self.assertEqual(len(app.exception), 0)
        self.assertNotIn("网页访问密码", [item.label for item in app.text_input])
        self.read_mock.assert_called()
        self.history_mock.assert_called()
        self.control_mock.assert_not_called()

    def test_invalid_threshold_never_posts(self):
        app = self.app()
        # 这里特意使用真实 control 的参数校验；网络仍被完全封闭。
        self.control_patch.stop()
        app.number_input(key="draft_low").set_value(55)
        app.number_input(key="draft_high").set_value(45)
        by_label(app.button, "保存温度范围").click()
        app.run()
        self.assertEqual(len(app.exception), 0)
        self.assertTrue(any("下限小于上限" in item.value for item in app.warning))
        self.network_mock.assert_not_called()

    def test_confirmed_command_has_notice_and_updated_values(self):
        app = self.app()
        app.number_input(key="draft_low").set_value(8)
        app.number_input(key="draft_high").set_value(42)
        by_label(app.button, "保存温度范围").click()
        app.run()
        self.assertEqual(len(app.exception), 0)
        self.control_mock.assert_called_once_with({"TemperatureLow": 8, "TemperatureHigh": 42})
        self.assertTrue(any("已核对51回传状态" in item.value for item in app.success))

    def test_public_control_keeps_the_command_cooldown(self):
        app = self.app()
        app.session_state["last_command_at"] = time.monotonic()
        by_label(app.button, "保存温度范围").click()
        app.run()
        self.assertEqual(len(app.exception), 0)
        self.assertTrue(any("上一条操作" in item.value for item in app.warning))
        self.control_mock.assert_not_called()

    def test_only_cloud_settings_are_required_no_password(self):
        from settings import load_settings
        settings = load_settings(TEST_SECRETS)
        self.assertFalse(hasattr(settings, "password"))
        self.assertEqual(settings.cloud.product, "test-product")
        self.assertNotIn("unit-test-token", repr(settings))

    def test_decimal_zero_negative_and_invalid_temperature_render(self):
        for value, expected in ((25.1, "25.1"), (0.0, "0.0"), (-5.2, "-5.2"), (None, "--")):
            with self.subTest(value=value):
                st.cache_data.clear()
                self.live_payload = {"properties": properties(temperature=value), "gateway_status": 1}
                app = self.app()
                self.assertIn(f">{expected}<small> °C", html_text(app))
                self.assertIn(">61<small> %", html_text(app))
                self.assertNotIn(">61.0<small> %", html_text(app))
        self.control_mock.assert_not_called()

    def test_humidity_drafts_survive_live_limits_changes(self):
        app = self.app()
        app.session_state["draft_humidity_low"] = 22
        app.session_state["draft_humidity_high"] = 88
        changed = properties()
        for item in changed:
            if item["identifier"] == "HumidityLow":
                item["value"] = 25
            elif item["identifier"] == "HumidityHigh":
                item["value"] = 85
        self.live_payload = {"properties": changed, "gateway_status": 1}
        st.cache_data.clear()
        app.run()
        self.assertEqual(len(app.exception), 0)
        self.assertEqual(app.number_input(key="draft_humidity_low").value, 22)
        self.assertEqual(app.number_input(key="draft_humidity_high").value, 88)
        self.assertIn("25%", html_text(app))
        self.assertIn("85%", html_text(app))
        self.control_mock.assert_not_called()

    def test_humidity_submit_uses_paired_integer_bounds(self):
        app = self.app()
        app.number_input(key="draft_humidity_low").set_value(0)
        app.number_input(key="draft_humidity_high").set_value(100)
        by_label(app.button, "保存湿度范围").click()
        app.run()
        self.assertEqual(len(app.exception), 0)
        self.control_mock.assert_called_once_with({"HumidityLow": 0, "HumidityHigh": 100})
        self.assertTrue(any("已核对51回传状态" in item.value for item in app.success))

    def test_invalid_humidity_range_never_posts(self):
        app = self.app()
        self.control_patch.stop()
        app.number_input(key="draft_humidity_low").set_value(90)
        app.number_input(key="draft_humidity_high").set_value(80)
        by_label(app.button, "保存湿度范围").click()
        app.run()
        self.assertEqual(len(app.exception), 0)
        self.assertTrue(any("下限小于上限" in item.value for item in app.warning))
        self.network_mock.assert_not_called()

    def test_legacy_firmware_disables_only_humidity_controls(self):
        legacy = [item for item in properties() if item["identifier"] not in ("HumidityLow", "HumidityHigh")]
        self.live_payload = {"properties": legacy, "gateway_status": 1}
        app = self.app()
        self.assertTrue(by_label(app.button, "保存湿度范围").disabled)
        self.assertTrue(app.number_input(key="draft_humidity_low").disabled)
        self.assertTrue(app.number_input(key="draft_humidity_high").disabled)
        self.assertFalse(by_label(app.button, "保存温度范围").disabled)
        self.assertFalse(by_label(app.button, "写入设备时间").disabled)
        self.assertTrue(any("等待HumidityLow、HumidityHigh最新上报" in item.value for item in app.caption))
        self.control_mock.assert_not_called()

    def test_temp_mute_control_describes_realarm_then_reads_true_state(self):
        for item in self.live_payload["properties"]:
            if item["identifier"] == "AlarmActive":
                item["value"] = True
        app = self.app()
        self.assertFalse(by_label(app.button, "消音约10秒").disabled)
        by_label(app.button, "消音约10秒").click()
        app.run()
        self.assertEqual(len(app.exception), 0)
        self.control_mock.assert_called_once_with({"AlarmMuted": True})
        self.assertIn("约10秒后51复检：仍超限会再次报警", html_text(app))
        self.assertTrue(any("临时消音中" in item.value for item in app.caption))
        self.assertTrue(by_label(app.button, "消音约10秒").disabled)
        self.assertFalse(by_label(app.button, "恢复声音").disabled)
        # 重新报警由51决定：网页仅根据新的真实状态回报恢复声音按钮，
        # 不在浏览器生成自己的倒计时，更不假装已执行恢复声音命令。
        for item in self.live_payload["properties"]:
            if item["identifier"] == "AlarmMuted":
                item["value"] = False
        st.cache_data.clear()
        app.run()
        self.assertEqual(len(app.exception), 0)
        self.assertFalse(by_label(app.button, "消音约10秒").disabled)
        self.assertTrue(by_label(app.button, "恢复声音").disabled)
        self.assertTrue(any("蜂鸣器正在报警" in item.value for item in app.caption))
        self.assertEqual(self.control_mock.call_count, 1)

    def test_reload_settings_resets_both_threshold_drafts_without_control(self):
        app = self.app()
        app.session_state["draft_low"] = 7
        app.session_state["draft_high"] = 39
        app.session_state["draft_humidity_low"] = 20
        app.session_state["draft_humidity_high"] = 90
        by_label(app.button, "重新载入设备设置").click()
        app.run()
        self.assertEqual(len(app.exception), 0)
        self.assertEqual(app.number_input(key="draft_low").value, 5)
        self.assertEqual(app.number_input(key="draft_high").value, 45)
        self.assertEqual(app.number_input(key="draft_humidity_low").value, 30)
        self.assertEqual(app.number_input(key="draft_humidity_high").value, 80)
        self.control_mock.assert_not_called()


if __name__ == "__main__":
    unittest.main()

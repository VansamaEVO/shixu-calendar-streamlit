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

from onenet import OneNetClient, validate_params


TEST_SECRETS = {
    "ONENET_TOKEN": "unit-test-token",
    "ONENET_PRODUCT_ID": "test-product",
    "ONENET_DEVICE_NAME": "test-device",
}


def properties(*, age=0, online=True, ready=True, temperature=27, humidity=61):
    now = int(time.time() * 1000) - age
    values = {
        "CurrentTemperature": temperature,
        "CurrentHumidity": humidity,
        "DeviceTime": "2026-10-10 13:45:22",
        "TemperatureLow": 5,
        "TemperatureHigh": 45,
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
        updated = properties()
        for item in updated:
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

    def test_settings_are_visible_before_history_not_an_expander(self):
        app = self.app()
        self.assertEqual(len(app.expander), 0)
        page = html_text(app)
        self.assertIn('href="#calendar-settings"', page)
        self.assertLess(page.index('id="calendar-monitor"'), page.index('id="calendar-settings"'))
        self.assertLess(page.index('id="calendar-settings"'), page.index('id="calendar-history"'))
        self.assertIn("DATE &amp; TIME", page)
        self.assertIn("TEMPERATURE", page)
        self.assertIn("ALARM SOUND", page)
        self.control_mock.assert_not_called()

    def test_public_dashboard_renders_real_values_and_controls(self):
        app = self.app()
        self.assertIn("27", html_text(app))
        self.assertIn("61", html_text(app))
        self.assertFalse(by_label(app.button, "保存温度范围").disabled)
        self.assertEqual(app.number_input(key="draft_low").value, 5)
        self.assertEqual(app.number_input(key="draft_high").value, 45)
        self.read_mock.assert_called()
        self.history_mock.assert_called()
        self.control_mock.assert_not_called()

    def test_gateway_offline_hides_sensor_values_and_disables_controls(self):
        self.live_payload = {"properties": properties(temperature=113, humidity=97), "gateway_status": 0}
        app = self.app()
        self.assertTrue(by_label(app.button, "保存温度范围").disabled)
        self.assertTrue(by_label(app.button, "写入设备时间").disabled)
        self.assertTrue(by_label(app.button, "一键同步北京时间").disabled)
        self.assertNotIn('>113<', html_text(app))
        self.assertNotIn('>97<', html_text(app))
        self.control_mock.assert_not_called()

    def test_stale_data_hides_sensor_values_and_disables_controls(self):
        self.live_payload = {"properties": properties(age=30_000, temperature=113, humidity=97), "gateway_status": 1}
        app = self.app()
        self.assertTrue(by_label(app.button, "保存温度范围").disabled)
        self.assertTrue(app.number_input(key="draft_low").disabled)
        self.assertNotIn('>113<', html_text(app))
        self.assertNotIn('>97<', html_text(app))
        self.control_mock.assert_not_called()

    def test_drafts_survive_poll_rerun(self):
        app = self.app()
        # AppTest 与浏览器一样不发送未提交表单的值。这里验证服务端
        # 已持有的编辑草稿不被监测刷新覆盖，前端未提交输入需真机验证。
        app.session_state["draft_low"] = 9
        app.session_state["draft_high"] = 38
        app.session_state["draft_time"] = "11:12:13"
        st.cache_data.clear()
        self.live_payload = {"properties": properties(temperature=28), "gateway_status": 1}
        app.run()
        self.assertEqual(len(app.exception), 0)
        self.assertEqual(app.number_input(key="draft_low").value, 9)
        self.assertEqual(app.number_input(key="draft_high").value, 38)
        self.assertEqual(app.text_input(key="draft_time").value, "11:12:13")
        self.control_mock.assert_not_called()

    def test_poll_read_error_hides_last_values_and_disables_control(self):
        app = self.app()
        st.cache_data.clear()
        self.read_mock.side_effect = RuntimeError("unit-test transport failure")
        app.run()
        self.assertEqual(len(app.exception), 0)
        self.assertTrue(by_label(app.button, "保存温度范围").disabled)
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


if __name__ == "__main__":
    unittest.main()

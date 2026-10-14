"""离线测试：不访问 OneNet，不向真实设备发送任何控制。"""

from datetime import datetime
import unittest

from onenet import OneNetClient, OneNetError, OneNetSettings, snapshot, validate_params


NOW = 1_791_610_000_000


def properties(at=NOW - 1000, **overrides):
    values = {
        "CurrentTemperature": "25.1", "CurrentHumidity": "66",
        "DeviceTime": "2026-10-10 12:56:28", "TemperatureLow": 5,
        "TemperatureHigh": 45, "HumidityLow": 30, "HumidityHigh": 80,
        "AlarmActive": False, "AlarmMuted": False,
        "McuOnline": True, "ControlReady": True,
        "TemperatureValid": True, "HumidityValid": True,
    }
    values.update(overrides)
    return [{"identifier": key, "value": value, "time": at} for key, value in values.items()]


def ok(data):
    return {"code": 0, "data": data}


class Clock:
    def __init__(self):
        self.ms = NOW

    def now(self):
        return self.ms / 1000

    def sleep(self, seconds):
        self.ms += int(round(seconds * 1000))


class Response:
    def __init__(self, value, status=200):
        self.value = value
        self.status_code = status

    def json(self):
        if isinstance(self.value, Exception):
            raise self.value
        return self.value


class Session:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def request(self, method, url, **kwargs):
        self.calls.append({"method": method, "url": url, **kwargs})
        # 最后一份响应可重复，用于模拟设备始终没更新的轮询。
        value = self.responses.pop(0) if len(self.responses) > 1 else self.responses[0]
        if isinstance(value, Exception):
            raise value
        return value if isinstance(value, Response) else Response(value)

    def close(self):
        pass


def client(responses):
    clock = Clock()
    session = Session(responses)
    settings = OneNetSettings("test-token-not-real", "test-product", "test-device")
    return OneNetClient(settings, session=session, clock=clock.now, sleep=clock.sleep), session, clock


class SnapshotTests(unittest.TestCase):
    def test_fresh_valid_state(self):
        value = snapshot(properties(), NOW)
        self.assertTrue(value["online"])
        self.assertTrue(value["ready"])
        self.assertEqual(value["temperature"], 25.1)
        self.assertEqual(value["humidity"], 66)
        self.assertEqual(value["time"], datetime(2026, 10, 10, 12, 56, 28))
        self.assertEqual(value["time_at"], NOW - 1000)
        self.assertEqual(value["updated_at"], NOW - 1000)

    def test_stale_state_keeps_only_last_clock(self):
        value = snapshot(properties(at=NOW - 20_000), NOW)
        self.assertFalse(value["online"])
        self.assertFalse(value["ready"])
        for key in ("temperature", "humidity", "time", "low", "high", "humidity_low", "humidity_high", "alarm", "muted"):
            self.assertIsNone(value[key])
        self.assertIsNotNone(value["last_time"])

    def test_future_boundary(self):
        self.assertTrue(snapshot(properties(at=NOW + 5000), NOW)["online"])
        self.assertFalse(snapshot(properties(at=NOW + 5001), NOW)["online"])

    def test_validity_flags_required(self):
        value = snapshot(properties(TemperatureValid=False, HumidityValid="false"), NOW)
        self.assertIsNone(value["temperature"])
        self.assertIsNone(value["humidity"])

    def test_cloud_temperature_accepts_real_decimals_and_zero(self):
        for raw, expected in ((25.1, 25.1), ("25.1", 25.1), (-12.3, -12.3), ("-12.3", -12.3), (0.0, 0.0), ("0.0", 0.0), (25, 25.0)):
            with self.subTest(value=raw):
                self.assertEqual(snapshot(properties(CurrentTemperature=raw), NOW)["temperature"], expected)

    def test_cloud_temperature_rejects_invalid_or_out_of_range(self):
        for bad in (True, False, "", None, "nan", "inf", float("nan"), float("inf"), -40.1, 125.1, "25x", "25.1°C", [], {}):
            with self.subTest(value=bad):
                self.assertIsNone(snapshot(properties(CurrentTemperature=bad), NOW)["temperature"])

    def test_humidity_remains_integer_not_decimal(self):
        for bad in (True, False, 66.1, "66.1", -1, 101, "nan", None):
            with self.subTest(value=bad):
                self.assertIsNone(snapshot(properties(CurrentHumidity=bad), NOW)["humidity"])
        self.assertEqual(snapshot(properties(CurrentHumidity=0), NOW)["humidity"], 0)
        self.assertEqual(snapshot(properties(CurrentHumidity=100), NOW)["humidity"], 100)

    def test_humidity_threshold_pair_controls_only_humidity_readiness(self):
        for low, high in ((0, 100), (30, 80)):
            value = snapshot(properties(HumidityLow=low, HumidityHigh=high), NOW)
            self.assertTrue(value["humidity_ready"])
            self.assertEqual((value["humidity_low"], value["humidity_high"]), (low, high))
        for changes in ({"HumidityLow": None}, {"HumidityHigh": None}, {"HumidityLow": 80}, {"HumidityHigh": 101}, {"HumidityLow": -1}, {"HumidityLow": 30.5}):
            with self.subTest(changes=changes):
                value = snapshot(properties(**changes), NOW)
                self.assertTrue(value["ready"])
                self.assertFalse(value["humidity_ready"])
                self.assertIsNone(value["humidity_low"])
                self.assertIsNone(value["humidity_high"])

    def test_legacy_firmware_has_no_humidity_control_but_other_controls_work(self):
        legacy = [item for item in properties() if not item["identifier"].startswith("HumidityL") and item["identifier"] != "HumidityHigh"]
        value = snapshot(legacy, NOW)
        self.assertTrue(value["ready"])
        self.assertFalse(value["humidity_ready"])
        self.assertEqual(value["humidity"], 66)

    def test_humidity_threshold_freshness_is_checked_individually(self):
        for identifier in ("HumidityLow", "HumidityHigh"):
            for at in (NOW - 20_000, NOW + 5001):
                with self.subTest(identifier=identifier, at=at):
                    data = properties()
                    next(item for item in data if item["identifier"] == identifier)["time"] = at
                    value = snapshot(data, NOW)
                    self.assertTrue(value["ready"])
                    self.assertFalse(value["humidity_ready"])

    def test_threshold_pair_is_required_for_ready(self):
        for bad in (properties(TemperatureLow=45), properties(TemperatureHigh=None)):
            value = snapshot(bad, NOW)
            self.assertFalse(value["ready"])
            self.assertIsNone(value["low"])
            self.assertIsNone(value["high"])

    def test_stale_command_relevant_field_disables_control(self):
        for identifier in ("ControlReady", "DeviceTime", "TemperatureLow", "TemperatureHigh", "AlarmActive", "AlarmMuted"):
            with self.subTest(identifier=identifier):
                data = properties()
                next(item for item in data if item["identifier"] == identifier)["time"] = NOW - 20_000
                self.assertFalse(snapshot(data, NOW)["ready"])

    def test_invalid_calendar_time(self):
        value = snapshot(properties(DeviceTime="2026-02-29 12:00:00"), NOW)
        self.assertIsNone(value["time"])
        self.assertFalse(value["ready"])

    def test_second_timestamps_supported(self):
        self.assertTrue(snapshot(properties(at=(NOW - 1000) // 1000), NOW)["ready"])


class ValidationTests(unittest.TestCase):
    def test_supported_commands(self):
        for params in (
            {"TemperatureLow": 0, "TemperatureHigh": 99},
            {"HumidityLow": 0, "HumidityHigh": 100},
            {"HumidityLow": 30, "HumidityHigh": 80},
            {"DeviceTime": "2024-02-29 23:59:59"},
            {"AlarmMuted": True}, {"AlarmMuted": False},
        ):
            self.assertEqual(validate_params(params), params)

    def test_invalid_commands(self):
        for params in (
            None, [], {}, {"TemperatureLow": True, "TemperatureHigh": 45},
            {"TemperatureLow": 3.0, "TemperatureHigh": 45},
            {"TemperatureLow": "3", "TemperatureHigh": 45},
            {"TemperatureLow": -1, "TemperatureHigh": 45},
            {"TemperatureLow": 45, "TemperatureHigh": 45},
            {"TemperatureLow": 3, "TemperatureHigh": 100},
            {"TemperatureLow": 3}, {"AlarmMuted": 1}, {"AlarmMuted": "true"},
            {"HumidityLow": 30}, {"HumidityHigh": 80},
            {"HumidityLow": -1, "HumidityHigh": 80},
            {"HumidityLow": 30, "HumidityHigh": 101},
            {"HumidityLow": 80, "HumidityHigh": 80},
            {"HumidityLow": 81, "HumidityHigh": 80},
            {"HumidityLow": True, "HumidityHigh": 80},
            {"HumidityLow": 30.0, "HumidityHigh": 80},
            {"HumidityLow": "30", "HumidityHigh": 80},
            {"HumidityLow": 30, "HumidityHigh": 80, "AlarmMuted": True},
            {"HumidityLow": 30, "HumidityHigh": 80, "TemperatureLow": 5, "TemperatureHigh": 45},
            {"DeviceTime": "2026-02-29 12:00:00"},
            {"DeviceTime": "1999-12-31 23:59:59"},
            {"DeviceTime": "2100-01-01 00:00:00"},
            {"DeviceTime": "2026-10-10 24:00:00"},
            {"DeviceTime": "2026-10-10T12:00:00"},
            {"AlarmMuted": True, "DeviceTime": "2026-10-10 12:00:00"},
            {"unexpected": True},
        ):
            with self.subTest(params=params), self.assertRaises(OneNetError):
                validate_params(params)

    def test_settings_repr_redacts_token(self):
        settings = OneNetSettings("SUPER-SECRET", "p", "d")
        self.assertNotIn("SUPER-SECRET", repr(settings))

    def test_settings_reject_empty_and_header_injection(self):
        for token in ("", " ", "secret\r\nInjected: yes"):
            with self.subTest(token=token), self.assertRaises(OneNetError):
                OneNetClient(OneNetSettings(token, "p", "d"))


class ReadTests(unittest.TestCase):
    def test_read_data_filters_fields_and_uses_raw_auth(self):
        data = properties() + [{"identifier": "private-field", "value": "hidden", "time": NOW}]
        api, session, _ = client([ok(data), ok({"status": 1})])
        result = api.read_data()
        self.assertEqual(result["gateway_status"], 1)
        self.assertEqual(result["server_time"], NOW)
        self.assertEqual(len(result["properties"]), 13)
        for call in session.calls:
            self.assertEqual(call["headers"]["authorization"], "test-token-not-real")
            self.assertFalse(call["allow_redirects"])
            self.assertEqual(call["timeout"], (3, 5))

    def test_missing_or_invalid_outer_code_rejected(self):
        for response in ({"data": []}, {"code": None, "data": []}, {"code": False, "data": []}, {"code": 200, "data": []}):
            api, _, _ = client([response])
            with self.subTest(response=response), self.assertRaises(OneNetError):
                api.read_data()

    def test_string_code_and_status_supported(self):
        api, _, _ = client([{"code": "0", "data": properties()}, ok({"status": "1"})])
        self.assertEqual(api.read_data()["gateway_status"], 1)

    def test_malformed_device_state_rejected(self):
        for device in ({}, {"status": False}, {"status": 3}, None):
            api, _, _ = client([ok(properties()), ok(device)])
            with self.subTest(device=device), self.assertRaises(OneNetError):
                api.read_data()

    def test_history_filters_sorts_and_deduplicates(self):
        history = {"list": [
            {"time": NOW - 1000, "value": "25"},
            {"time": NOW - 2000, "value": 24},
            {"time": NOW - 1000, "value": 26},
            {"time": NOW - 3_600_001, "value": 20},
            {"time": NOW + 5001, "value": 30},
            {"time": NOW - 3000, "value": True},
            {"time": NOW - 4000, "value": 25.1},
            {"time": NOW - 5000, "value": 200},
        ]}
        api, session, _ = client([ok(history), ok({"list": []})])
        result = api.read_history()
        self.assertEqual(result["temperature"], [
            {"time": NOW - 4000, "value": 25.1},
            {"time": NOW - 2000, "value": 24}, {"time": NOW - 1000, "value": 26},
        ])
        self.assertEqual(result["humidity"], [])
        self.assertEqual(session.calls[0]["params"]["limit"], 120)

    def test_history_retains_negative_and_zero_decimal_temperature_but_integer_humidity(self):
        api, _, _ = client([ok({"list": [
            {"time": NOW - 3000, "value": "-5.2"},
            {"time": NOW - 2000, "value": "0.0"},
            {"time": NOW - 1000, "value": "25.1"},
            {"time": NOW, "value": "NaN"},
        ]}), ok({"list": [
            {"time": NOW - 1000, "value": 66},
            {"time": NOW, "value": 66.1},
        ]})])
        history = api.read_history()
        self.assertEqual([point["value"] for point in history["temperature"]], [-5.2, 0.0, 25.1])
        self.assertEqual([point["value"] for point in history["humidity"]], [66])

    def test_raw_error_is_not_exposed(self):
        for response in (RuntimeError("test-token-not-real private body"), Response(ValueError("test-token-not-real json")), Response({}, 403)):
            api, _, _ = client([response])
            with self.subTest(response=type(response).__name__):
                with self.assertRaises(OneNetError) as error:
                    api.read_data()
                self.assertNotIn("test-token-not-real", str(error.exception))


class ControlTests(unittest.TestCase):
    def test_confirmed_humidity_range_requires_real_updated_pair(self):
        newer = properties(at=NOW + 1000, HumidityLow=0, HumidityHigh=100)
        api, session, _ = client([ok(properties()), ok({"status": 1}), ok({"code": 200}), ok(newer)])
        self.assertTrue(api.control({"HumidityLow": 0, "HumidityHigh": 100})["confirmed"])
        posts = [call for call in session.calls if call["method"] == "POST"]
        self.assertEqual(len(posts), 1)
        self.assertEqual(posts[0]["json"]["params"], {"HumidityLow": 0, "HumidityHigh": 100})

    def test_humidity_old_matching_values_do_not_confirm_execution(self):
        baseline = properties(HumidityLow=20, HumidityHigh=90)
        api, session, clock = client([ok(baseline), ok({"status": 1}), ok({"code": 200}), ok(baseline)])
        with self.assertRaisesRegex(OneNetError, "最新状态未核对"):
            api.control({"HumidityLow": 20, "HumidityHigh": 90})
        self.assertGreaterEqual(clock.ms - NOW, 8000)
        self.assertEqual(len([call for call in session.calls if call["method"] == "POST"]), 1)

    def test_humidity_partial_changed_or_unfresh_pair_does_not_confirm(self):
        for changed in ("old_high_stamp", "wrong_high_value", "far_future_pair"):
            with self.subTest(changed=changed):
                newer = properties(at=NOW + 1000, HumidityLow=20, HumidityHigh=90)
                high = next(item for item in newer if item["identifier"] == "HumidityHigh")
                if changed == "old_high_stamp":
                    high["time"] = NOW - 1000
                elif changed == "wrong_high_value":
                    high["value"] = 80
                else:
                    for item in newer:
                        if item["identifier"] in ("HumidityLow", "HumidityHigh"):
                            item["time"] = NOW + 60_000
                api, session, _ = client([ok(properties()), ok({"status": 1}), ok({"code": 200}), ok(newer)])
                with self.assertRaisesRegex(OneNetError, "最新状态未核对"):
                    api.control({"HumidityLow": 20, "HumidityHigh": 90})
                self.assertEqual(len([call for call in session.calls if call["method"] == "POST"]), 1)

    def test_humidity_unknown_stale_or_invalid_pair_never_posts(self):
        legacy = [item for item in properties() if item["identifier"] not in ("HumidityLow", "HumidityHigh")]
        stale = properties()
        next(item for item in stale if item["identifier"] == "HumidityHigh")["time"] = NOW - 20_000
        for baseline in (legacy, stale, properties(HumidityLow=80, HumidityHigh=80)):
            with self.subTest(baseline=baseline):
                api, session, _ = client([ok(baseline), ok({"status": 1})])
                with self.assertRaisesRegex(OneNetError, "湿度阈值"):
                    api.control({"HumidityLow": 20, "HumidityHigh": 90})
                self.assertFalse(any(call["method"] == "POST" for call in session.calls))

    def test_humidity_expiring_during_gateway_query_never_posts(self):
        clock = Clock()

        class SlowSession(Session):
            def request(self, method, url, **kwargs):
                response = super().request(method, url, **kwargs)
                if url.endswith("/device/detail"):
                    clock.sleep(2)
                return response

        baseline = properties()
        next(item for item in baseline if item["identifier"] == "HumidityHigh")["time"] = NOW - 19_000
        session = SlowSession([ok(baseline), ok({"status": 1})])
        api = OneNetClient(OneNetSettings("test-token-not-real", "p", "d"), session=session, clock=clock.now, sleep=clock.sleep)
        with self.assertRaisesRegex(OneNetError, "湿度阈值"):
            api.control({"HumidityLow": 20, "HumidityHigh": 90})
        self.assertFalse(any(call["method"] == "POST" for call in session.calls))

    def test_confirmed_thresholds_require_new_property_timestamps(self):
        newer = properties(at=NOW + 1000, TemperatureLow=10, TemperatureHigh=50)
        api, session, _ = client([ok(properties()), ok({"status": 1}), ok({"code": 200}), ok(newer)])
        result = api.control({"TemperatureLow": 10, "TemperatureHigh": 50})
        self.assertTrue(result["confirmed"])
        posts = [call for call in session.calls if call["method"] == "POST"]
        self.assertEqual(len(posts), 1)
        self.assertEqual(posts[0]["json"]["params"], {"TemperatureLow": 10, "TemperatureHigh": 50})
        self.assertEqual(posts[0]["timeout"], (3, 10))

    def test_old_matching_value_does_not_count_as_execution(self):
        baseline = properties(TemperatureLow=10, TemperatureHigh=50)
        api, session, clock = client([ok(baseline), ok({"status": 1}), ok({"code": 200}), ok(baseline)])
        with self.assertRaisesRegex(OneNetError, "最新状态未核对"):
            api.control({"TemperatureLow": 10, "TemperatureHigh": 50})
        self.assertEqual(len([call for call in session.calls if call["method"] == "POST"]), 1)
        self.assertGreaterEqual(clock.ms - NOW, 8000)

    def test_missing_device_success_code_rejected(self):
        for reply in ({}, {"code": None}, {"code": 0}, {"code": True}):
            api, session, _ = client([ok(properties()), ok({"status": 1}), ok(reply)])
            with self.subTest(reply=reply), self.assertRaisesRegex(OneNetError, "设备未确认"):
                api.control({"TemperatureLow": 10, "TemperatureHigh": 50})
            self.assertEqual(len([call for call in session.calls if call["method"] == "POST"]), 1)

    def test_offline_stale_or_not_ready_never_posts(self):
        for baseline, device in (
            (properties(McuOnline=False), {"status": 1}),
            (properties(at=NOW - 20_000), {"status": 1}),
            (properties(ControlReady=False), {"status": 1}),
            (properties(), {"status": 0}),
        ):
            api, session, _ = client([ok(baseline), ok(device)])
            with self.subTest(device=device), self.assertRaisesRegex(OneNetError, "未发送"):
                api.control({"TemperatureLow": 10, "TemperatureHigh": 50})
            self.assertFalse(any(call["method"] == "POST" for call in session.calls))

    def test_mute_requires_active_alarm(self):
        api, session, _ = client([ok(properties()), ok({"status": 1})])
        with self.assertRaisesRegex(OneNetError, "没有有效温湿度报警"):
            api.control({"AlarmMuted": True})
        self.assertFalse(any(call["method"] == "POST" for call in session.calls))

    def test_mute_confirmed_as_real_boolean(self):
        baseline = properties(AlarmActive=True)
        newer = properties(at=NOW + 1000, AlarmActive=True, AlarmMuted="true")
        api, _, _ = client([ok(baseline), ok({"status": 1}), ok({"code": "200"}), ok(newer)])
        self.assertTrue(api.control({"AlarmMuted": True})["confirmed"])

    def test_time_confirmation_accepts_normal_clock_progress(self):
        newer = properties(at=NOW + 1000, DeviceTime="2026-10-11 10:00:02")
        api, _, _ = client([ok(properties()), ok({"status": 1}), ok({"code": 200}), ok(newer)])
        self.assertTrue(api.control({"DeviceTime": "2026-10-11 10:00:00"})["confirmed"])

    def test_time_confirmation_rejects_wrong_day(self):
        newer = properties(at=NOW + 1000, DeviceTime="2026-10-12 10:00:00")
        api, _, _ = client([ok(properties()), ok({"status": 1}), ok({"code": 200}), ok(newer)])
        with self.assertRaisesRegex(OneNetError, "最新状态未核对"):
            api.control({"DeviceTime": "2026-10-11 10:00:00"})

    def test_post_network_failure_never_retries_or_leaks(self):
        api, session, _ = client([ok(properties()), ok({"status": 1}), RuntimeError("test-token-not-real request")])
        with self.assertRaisesRegex(OneNetError, "不要立即重复") as error:
            api.control({"TemperatureLow": 10, "TemperatureHigh": 50})
        self.assertNotIn("test-token-not-real", str(error.exception))
        self.assertEqual(len([call for call in session.calls if call["method"] == "POST"]), 1)

    def test_confirm_poll_failure_reports_execution_uncertainty(self):
        api, session, _ = client([
            ok(properties()), ok({"status": 1}), ok({"code": 200}),
            RuntimeError("test-token-not-real confirmation request"),
        ])
        with self.assertRaisesRegex(OneNetError, "设备已回复.*不要立即重复") as error:
            api.control({"TemperatureLow": 10, "TemperatureHigh": 50})
        self.assertNotIn("test-token-not-real", str(error.exception))
        self.assertEqual(len([call for call in session.calls if call["method"] == "POST"]), 1)

    def test_rate_limit_prevents_immediate_second_post(self):
        newer = properties(at=NOW + 1000, TemperatureLow=10, TemperatureHigh=50)
        api, session, _ = client([ok(properties()), ok({"status": 1}), ok({"code": 200}), ok(newer)])
        api.control({"TemperatureLow": 10, "TemperatureHigh": 50})
        with self.assertRaisesRegex(OneNetError, "等待上一条"):
            api.control({"TemperatureLow": 11, "TemperatureHigh": 51})
        self.assertEqual(len([call for call in session.calls if call["method"] == "POST"]), 1)

    def test_baseline_expiring_during_device_query_never_posts(self):
        clock = Clock()

        class SlowSession(Session):
            def request(self, method, url, **kwargs):
                response = super().request(method, url, **kwargs)
                if url.endswith("/device/detail"):
                    clock.sleep(2)
                return response

        session = SlowSession([ok(properties(at=NOW - 19_000)), ok({"status": 1})])
        api = OneNetClient(
            OneNetSettings("test-token-not-real", "p", "d"),
            session=session, clock=clock.now, sleep=clock.sleep,
        )
        with self.assertRaisesRegex(OneNetError, "未发送"):
            api.control({"TemperatureLow": 10, "TemperatureHigh": 50})
        self.assertFalse(any(call["method"] == "POST" for call in session.calls))

    def test_in_progress_command_never_starts_second_request(self):
        api, session, _ = client([ok(properties())])
        api._control_lock.acquire()
        try:
            with self.assertRaisesRegex(OneNetError, "等待上一条"):
                api.control({"TemperatureLow": 10, "TemperatureHigh": 50})
            self.assertEqual(session.calls, [])
        finally:
            api._control_lock.release()


if __name__ == "__main__":
    unittest.main()

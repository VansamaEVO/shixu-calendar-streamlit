"""OneNet 数据与控制接口。授权仅在服务端使用，不输出响应原文或密钥。"""

from dataclasses import dataclass, field
from datetime import datetime
import math
import re
import threading
import time
from typing import Any

import requests


FIELDS = (
    "CurrentTemperature", "CurrentHumidity", "DeviceTime", "TemperatureLow",
    "TemperatureHigh", "HumidityLow", "HumidityHigh", "AlarmActive", "AlarmMuted", "McuOnline",
    "ControlReady", "TemperatureValid", "HumidityValid",
    "TemperatureAlarm", "HumidityAlarm",
)
FRESH_MS = 20_000
FUTURE_TOLERANCE_MS = 5_000
BASE_URL = "https://iot-api.heclouds.com"


class OneNetError(Exception):
    """可直接展示给用户的错误，不带 HTTP 响应或授权信息。"""


@dataclass(frozen=True)
class OneNetSettings:
    token: str = field(repr=False)
    product: str
    device: str


def _stamp(value: Any) -> int:
    if isinstance(value, bool) or value is None or value == "":
        return 0
    try:
        number = float(value)
        if not math.isfinite(number) or number <= 0:
            return 0
        return int(number * 1000 if number < 1_000_000_000_000 else number)
    except (TypeError, ValueError, OverflowError):
        return 0


def _boolean(value: Any):
    if value is True or value == "true" or value == "1":
        return True
    if value is False or value == "false" or value == "0":
        return False
    if type(value) in (int, float) and value == 1:
        return True
    if type(value) in (int, float) and value == 0:
        return False
    return None


def _integer(value: Any, minimum: int, maximum: int):
    if isinstance(value, bool) or value is None or value == "":
        return None
    if type(value) not in (int, float, str):
        return None
    if isinstance(value, str) and not re.fullmatch(r"-?[0-9]+", value):
        return None
    try:
        number = float(value)
        if not math.isfinite(number) or not number.is_integer():
            return None
        result = int(number)
        return result if minimum <= result <= maximum else None
    except (ValueError, OverflowError):
        return None


def _decimal(value: Any, minimum: float, maximum: float):
    if isinstance(value, bool) or type(value) not in (int, float, str):
        return None
    if isinstance(value, str) and not re.fullmatch(r"-?[0-9]+(?:\.[0-9]+)?", value):
        return None
    try:
        number = float(value)
        return number if math.isfinite(number) and minimum <= number <= maximum else None
    except (ValueError, OverflowError):
        return None


def _parse_time(value: Any):
    if not isinstance(value, str) or not re.fullmatch(
        r"20[0-9]{2}-[0-9]{2}-[0-9]{2} [0-9]{2}:[0-9]{2}:[0-9]{2}", value
    ):
        return None
    try:
        return datetime.strptime(value, "%Y-%m-%d %H:%M:%S")
    except ValueError:
        return None


def _property_map(properties: Any) -> dict:
    if not isinstance(properties, (list, tuple)):
        return {}
    return {
        item["identifier"]: item for item in properties
        if isinstance(item, dict) and item.get("identifier") in FIELDS
    }


def snapshot(properties, now_ms=None) -> dict:
    """只用最近 20 秒内、至多超前 5 秒的状态；离线不显示旧传感器值。"""
    now = int(time.time() * 1000) if now_ms is None else int(now_ms)
    entries = _property_map(properties)

    def fresh(identifier):
        item = entries.get(identifier)
        at = _stamp(item.get("time")) if item else 0
        return item if at > 0 and -FUTURE_TOLERANCE_MS <= now - at < FRESH_MS else None

    def flag(identifier):
        item = fresh(identifier)
        return _boolean(item.get("value")) if item else None

    def number(identifier, minimum, maximum):
        item = fresh(identifier)
        parser = _decimal if identifier == "CurrentTemperature" else _integer
        return parser(item.get("value"), minimum, maximum) if item else None

    online = flag("McuOnline") is True
    time_prop = entries.get("DeviceTime", {})
    last_time = _parse_time(time_prop.get("value"))
    device_time = last_time if online and fresh("DeviceTime") else None
    low = number("TemperatureLow", 0, 99)
    high = number("TemperatureHigh", 0, 99)
    limits_valid = low is not None and high is not None and low < high
    humidity_low = number("HumidityLow", 0, 100)
    humidity_high = number("HumidityHigh", 0, 100)
    humidity_limits_valid = humidity_low is not None and humidity_high is not None and humidity_low < humidity_high
    alarm = flag("AlarmActive") if online else None
    muted = flag("AlarmMuted") if online else None
    temperature_alarm = flag("TemperatureAlarm") if online else None
    humidity_alarm = flag("HumidityAlarm") if online else None
    alarm_times = [_stamp(entries.get(key, {}).get("time"))
                   for key in ("AlarmActive", "TemperatureAlarm", "HumidityAlarm")]
    # 分项必须与总报警来自同一轮上报；旧值/缺项/矛盾不冒充当前报警来源。
    alarm_details_valid = (alarm is not None and temperature_alarm is not None
                           and humidity_alarm is not None
                           and alarm == (temperature_alarm or humidity_alarm)
                           and max(alarm_times) - min(alarm_times) <= 1000)
    if not alarm_details_valid:
        temperature_alarm = humidity_alarm = None
    # 时间、阈值和报警状态也要有效，不能只凭一个旧的 ready 标志打开控制。
    ready = (
        online and flag("ControlReady") is True and device_time is not None
        and limits_valid and alarm is not None and muted is not None
    )
    return {
        "online": online,
        "ready": bool(ready),
        "temperature": number("CurrentTemperature", -40, 125)
        if online and flag("TemperatureValid") is True else None,
        "humidity": number("CurrentHumidity", 0, 100)
        if online and flag("HumidityValid") is True else None,
        "time": device_time,
        "last_time": last_time,
        "low": low if online and limits_valid else None,
        "high": high if online and limits_valid else None,
        "humidity_low": humidity_low if online and humidity_limits_valid else None,
        "humidity_high": humidity_high if online and humidity_limits_valid else None,
        "humidity_ready": bool(ready and humidity_limits_valid),
        "alarm": alarm,
        "muted": muted,
        "temperature_alarm": temperature_alarm,
        "humidity_alarm": humidity_alarm,
        "time_at": _stamp(time_prop.get("time")),
        "updated_at": max([0] + [_stamp(item.get("time")) for item in entries.values()]),
    }


def validate_params(params) -> dict:
    if not isinstance(params, dict) or not params:
        raise OneNetError("控制参数无效")
    keys = set(params)
    if keys == {"TemperatureLow", "TemperatureHigh"}:
        low, high = params["TemperatureLow"], params["TemperatureHigh"]
        if type(low) is not int or type(high) is not int or not 0 <= low < high <= 99:
            raise OneNetError("温度范围须为 0–99 之间的整数，且下限小于上限")
    elif keys == {"DeviceTime"}:
        if _parse_time(params["DeviceTime"]) is None:
            raise OneNetError("日期时间无效，仅支持 2000–2099 年")
    elif keys == {"HumidityLow", "HumidityHigh"}:
        low, high = params["HumidityLow"], params["HumidityHigh"]
        if type(low) is not int or type(high) is not int or not 0 <= low < high <= 100:
            raise OneNetError("湿度范围须为 0–100 之间的整数，且下限小于上限")
    elif keys == {"AlarmMuted"}:
        if type(params["AlarmMuted"]) is not bool:
            raise OneNetError("静音参数须为布尔值")
    else:
        raise OneNetError("一次只能修改日期时间、温度范围、湿度范围或临时消音")
    return dict(params)


def _code_matches(value: Any, expected: int) -> bool:
    # None、False 和缺失字段都不能误判成成功；平台可能把 code 写成字符串。
    return type(value) is int and value == expected or (
        isinstance(value, str) and value == str(expected)
    )


def _state_matches(properties, params, sent_at, now_ms, baseline) -> bool:
    state = snapshot(properties, now_ms)
    if not state["ready"] or ("HumidityLow" in params and not state["humidity_ready"]):
        return False
    current, previous = _property_map(properties), _property_map(baseline)
    for identifier, expected in params.items():
        item, old = current.get(identifier), previous.get(identifier)
        if not item or not old:
            return False
        at = _stamp(item.get("time"))
        if at < sent_at - 1000 or at <= _stamp(old.get("time")):
            return False
        if identifier == "AlarmMuted":
            if _boolean(item.get("value")) is not expected:
                return False
        elif identifier == "DeviceTime":
            actual_time, requested_time = _parse_time(item.get("value")), _parse_time(expected)
            if actual_time is None or requested_time is None:
                return False
            elapsed = (actual_time - requested_time).total_seconds() * 1000
            if not -1000 <= elapsed <= now_ms - sent_at + 5000:
                return False
        elif _integer(item.get("value"), 0, 100 if identifier.startswith("Humidity") else 99) != expected:
            return False
    return True


class OneNetClient:
    def __init__(self, settings: OneNetSettings, *, session=None, clock=None, sleep=None):
        if not isinstance(settings, OneNetSettings) or any(
            not isinstance(value, str) or not value.strip() or "\r" in value or "\n" in value
            for value in (settings.token, settings.product, settings.device)
        ):
            raise OneNetError("网页服务配置尚未完成，请联系设备主人")
        self.settings = settings
        self._session = session if session is not None else requests.Session()
        self._clock = clock if clock is not None else time.time
        self._sleep = sleep if sleep is not None else time.sleep
        self._control_lock = threading.Lock()
        self._last_command_at = None

    def close(self):
        self._session.close()

    def _now(self):
        return int(self._clock() * 1000)

    def _query(self):
        return {"product_id": self.settings.product, "device_name": self.settings.device}

    def _request(self, path, *, method="GET", params=None, payload=None):
        try:
            response = self._session.request(
                method, BASE_URL + path,
                headers={"authorization": self.settings.token, "Content-Type": "application/json"},
                params=params, json=payload,
                timeout=(3, 10) if method == "POST" else (3, 5),
                allow_redirects=False,
            )
            if not 200 <= response.status_code < 300:
                raise OneNetError("OneNet 暂时无法访问，请稍后刷新")
            result = response.json()
            if not isinstance(result, dict) or not _code_matches(result.get("code"), 0):
                raise OneNetError("OneNet 请求未通过，请联系设备主人检查授权与物模型")
            if "data" not in result:
                raise OneNetError("OneNet 数据格式异常")
            return result["data"]
        except OneNetError:
            raise
        except Exception:
            # 不把 requests 异常 / 响应正文交给前端，避免间接暴露授权头。
            if method == "POST":
                raise OneNetError("控制请求未能确认；请刷新查看设备状态，不要立即重复操作") from None
            raise OneNetError("OneNet 连接超时或网络不可用") from None

    def _read_properties(self):
        data = self._request("/thingmodel/query-device-property", params=self._query())
        if not isinstance(data, list):
            raise OneNetError("OneNet 数据格式异常")
        result = []
        for item in data:
            if not isinstance(item, dict) or item.get("identifier") not in FIELDS:
                continue
            value = item.get("value")
            if type(value) not in (str, int, float, bool, type(None)):
                value = None
            result.append({"identifier": item["identifier"], "value": value, "time": _stamp(item.get("time"))})
        return result

    def read_data(self) -> dict:
        properties = self._read_properties()
        device = self._request("/device/detail", params=self._query())
        status = _integer(device.get("status"), 0, 2) if isinstance(device, dict) else None
        if status is None:
            raise OneNetError("OneNet 设备状态格式异常")
        return {"properties": properties, "gateway_status": status, "server_time": self._now()}

    def read_history(self) -> dict:
        end = self._now()
        start = end - 3_600_000
        result = {}
        for name, identifier, minimum, maximum in (
            ("temperature", "CurrentTemperature", -40, 125),
            ("humidity", "CurrentHumidity", 0, 100),
        ):
            query = {
                **self._query(), "identifier": identifier, "start_time": start,
                "end_time": end, "sort": 2, "limit": 120,
            }
            data = self._request("/thingmodel/query-device-property-history", params=query)
            if not isinstance(data, dict) or not isinstance(data.get("list"), list):
                raise OneNetError("OneNet 历史数据格式异常")
            points = {}
            for item in data["list"]:
                if not isinstance(item, dict):
                    continue
                at = _stamp(item.get("time"))
                parser = _decimal if identifier == "CurrentTemperature" else _integer
                value = parser(item.get("value"), minimum, maximum)
                if start <= at <= end + FUTURE_TOLERANCE_MS and value is not None:
                    points[at] = value
            result[name] = [{"time": at, "value": points[at]} for at in sorted(points)[-120:]]
        return result

    def control(self, params) -> dict:
        params = validate_params(params)
        if not self._control_lock.acquire(blocking=False):
            raise OneNetError("请等待上一条操作完成后再试")
        try:
            now = self._now()
            if self._last_command_at is not None and now - self._last_command_at < 2000:
                raise OneNetError("请等待上一条操作完成后再试")
            baseline_data = self.read_data()
            baseline = baseline_data["properties"]
            before = snapshot(baseline, self._now())
            if baseline_data["gateway_status"] != 1 or not before["online"] or not before["ready"]:
                raise OneNetError("设备离线、状态过期或双向串口未就绪，未发送控制命令")
            if "AlarmMuted" in params and before["alarm"] is not True:
                raise OneNetError("当前没有有效温湿度报警，无需修改临时消音")
            if "HumidityLow" in params and not before["humidity_ready"]:
                raise OneNetError("尚无新鲜湿度阈值，请发布物模型并更新51与ESP固件")
            sent_at = self._now()
            self._last_command_at = sent_at
            # POST 只发一次。超时并不证明设备没有执行，不能自动重发。
            reply = self._request(
                "/thingmodel/set-device-property", method="POST",
                payload={**self._query(), "params": params},
            )
            if not isinstance(reply, dict) or not _code_matches(reply.get("code"), 200):
                raise OneNetError("设备未确认执行，请检查 51 通信与设备当前状态")
            deadline = self._now() + 8000
            while True:
                try:
                    properties = self._read_properties()
                except OneNetError:
                    raise OneNetError("设备已回复，但读取最新状态失败；请刷新查看，不要立即重复操作") from None
                now = self._now()
                if _state_matches(properties, params, sent_at, now, baseline):
                    return {"confirmed": True, "properties": properties, "server_time": now}
                if now >= deadline:
                    break
                self._sleep(min(0.7, (deadline - now) / 1000))
            raise OneNetError("设备已回复，但最新状态未核对成功；请刷新查看，不要立即重复操作")
        finally:
            self._control_lock.release()

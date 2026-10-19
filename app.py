"""时序日历 · Streamlit 在线版。OneNet 请求与控制都在服务器执行。"""

from datetime import datetime, timedelta, timezone
from pathlib import Path
from threading import Lock
import hashlib
import re
import time

import streamlit as st

from onenet import OneNetClient, OneNetError, snapshot
from settings import SettingsError, load_settings
from trend import history_chart
from ui import dashboard_html, empty_trend_html, footer_html, header_html, navigation_html, settings_heading_html, settings_summary_html, trend_heading_html, record_alcohol_sample, motor_controls_heading_html

BASE = Path(__file__).resolve().parent
CHINA = timezone(timedelta(hours=8))

st.set_page_config(page_title="时序日历 · 多功能电子万年历", page_icon="📅", layout="wide")
st.html("<style>" + (BASE / "assets" / "theme.css").read_text(encoding="utf-8") + "</style>")


@st.cache_resource
def command_lock():
    return Lock()


@st.cache_data(ttl=4, max_entries=6, show_spinner=False)
def read_live(identity, _client):
    return _client.read_data()


@st.cache_data(ttl=60, max_entries=6, show_spinner=False)
def read_history(identity, _client):
    return _client.read_history()


def china_now():
    return datetime.now(CHINA).replace(tzinfo=None, microsecond=0)


def reset_drafts():
    for key in ("draft_low", "draft_high", "draft_humidity_low", "draft_humidity_high", "draft_date", "draft_time"):
        st.session_state.pop(key, None)


def add_log(text, good):
    records = st.session_state.get("operation_log", [])
    records.insert(0, {"时间": china_now().strftime("%H:%M:%S"), "操作结果": text, "状态": "已确认" if good else "未确认"})
    st.session_state["operation_log"] = records[:10]


def send_command(client, params, label):
    # 公开演示版不验证访问密码；设备在线检查与参数校验仍由后端执行。
    if time.monotonic() - st.session_state.get("last_command_at", -100) < 3:
        st.session_state["command_notice"] = (False, "请稍等上一条操作完成后再试。")
        return
    lock = command_lock()
    if not lock.acquire(blocking=False):
        st.session_state["command_notice"] = (False, "设备正在处理另一条操作，请稍后再试。")
        return
    try:
        st.session_state["last_command_at"] = time.monotonic()
        with st.spinner("正在等待51执行，并核对回传状态…"):
            result = client.control(params)
        if not result.get("confirmed"):
            raise OneNetError("设备状态尚未确认，请刷新查看。")
        st.session_state["last_properties"] = result["properties"]
        st.session_state["command_notice"] = (True, label + "，已核对51回传状态。")
        add_log(label, True)
    except OneNetError as error:
        st.session_state["command_notice"] = (False, str(error))
        add_log(str(error), False)
    except Exception:
        # 不将含请求头/Token的异常堆栈输出到浏览器或公开日志。
        st.session_state["command_notice"] = (False, "操作未确认，请刷新状态后再试。")
        add_log("操作未确认", False)
    finally:
        read_live.clear()
        lock.release()


def render_controls(client, state):
    ready = state["ready"]
    # 只初始化一次草稿。定时刷新只更新监测区，不覆盖正在输入的设置。
    defaults = state.get("time") or state.get("last_time") or china_now()
    for key, value in {
        "draft_low": state["low"] if state["low"] is not None else 5,
        "draft_high": state["high"] if state["high"] is not None else 45,
        "draft_humidity_low": state.get("humidity_low") if state.get("humidity_low") is not None else 30,
        "draft_humidity_high": state.get("humidity_high") if state.get("humidity_high") is not None else 80,
        "draft_date": defaults.date(),
        "draft_time": defaults.strftime("%H:%M:%S"),
    }.items():
        if key not in st.session_state:
            st.session_state[key] = value

    clock_tab, limits_tab, humidity_tab, sound_tab = st.tabs(["日期时间", "温度提醒", "湿度提醒", "蜂鸣器"], key="settings_sections")
    with clock_tab:
        st.caption("设置日历的日期和时间，星期会自动更新。")
        with st.form("clock_form", clear_on_submit=False, border=False):
            date_column, time_column = st.columns(2, gap="medium")
            with date_column:
                date_value = st.date_input("日期", min_value=datetime(2000, 1, 1).date(), max_value=datetime(2099, 12, 31).date(), key="draft_date", disabled=not ready)
            with time_column:
                clock_value = st.text_input("时间（时:分:秒）", key="draft_time", max_chars=8, placeholder="13:45:22", disabled=not ready)
            if st.form_submit_button("写入设备时间", type="primary", disabled=not ready, use_container_width=True):
                if not re.fullmatch(r"\d{2}:\d{2}:\d{2}", clock_value):
                    st.session_state["command_notice"] = (False, "时间请按 时:分:秒 填写，例如13:45:22。")
                else:
                    send_command(client, {"DeviceTime": date_value.isoformat() + " " + clock_value}, "日期时间已更新")
                st.rerun()
        if st.button("一键同步北京时间", key="sync_clock", disabled=not ready, use_container_width=True):
            # Cloud 主机可能使用UTC，这里明确转换UTC+8，避免写入晚8小时的RTC。
            send_command(client, {"DeviceTime": china_now().strftime("%Y-%m-%d %H:%M:%S")}, "北京时间已同步")
            st.rerun()
        st.caption("一键同步使用北京时间（UTC+8），不读取手机系统时钟。")

    with limits_tab:
        st.caption("温度超出这个范围，蜂鸣器会提醒。")
        with st.form("limits_form", clear_on_submit=False, border=False):
            low_column, high_column = st.columns(2, gap="medium")
            with low_column:
                low = st.number_input("下限 / ℃", min_value=0, max_value=99, step=1, key="draft_low", disabled=not ready)
            with high_column:
                high = st.number_input("上限 / ℃", min_value=0, max_value=99, step=1, key="draft_high", disabled=not ready)
            st.caption("0–99℃，下限必须小于上限。")
            if st.form_submit_button("保存温度范围", type="primary", disabled=not ready, use_container_width=True):
                send_command(client, {"TemperatureLow": int(low), "TemperatureHigh": int(high)}, "温度范围已更新")
                st.rerun()

    with humidity_tab:
        humidity_ready = state.get("humidity_ready", False)
        st.caption("湿度超出范围也会报警，温湿度共用蜂鸣器，范围保存到51的EEPROM。")
        with st.form("humidity_limits_form", clear_on_submit=False, border=False):
            low_column, high_column = st.columns(2, gap="medium")
            with low_column:
                humidity_low = st.number_input("湿度下限 / %RH", min_value=0, max_value=100, step=1, key="draft_humidity_low", disabled=not humidity_ready)
            with high_column:
                humidity_high = st.number_input("湿度上限 / %RH", min_value=0, max_value=100, step=1, key="draft_humidity_high", disabled=not humidity_ready)
            st.caption("0–100%RH，下限必须小于上限；等于上下限不报警。")
            if st.form_submit_button("保存湿度范围", type="primary", disabled=not humidity_ready, use_container_width=True):
                send_command(client, {"HumidityLow": int(humidity_low), "HumidityHigh": int(humidity_high)}, "湿度范围已更新")
                st.rerun()
        if not humidity_ready:
            st.caption("等待HumidityLow、HumidityHigh最新上报；请先发布物模型，并更新51与ESP固件。")

    with sound_tab:
        alarm = state.get("alarm") is True
        muted = state.get("muted")
        if state.get("alarm") is None:
            st.caption("等待设备回传报警状态，暂不能判断蜂鸣器声音。")
        elif not alarm:
            st.caption("当前没有有效温湿度报警，无需消音。")
        elif muted is True:
            st.caption("临时消音中，约10秒后仍超限会再次报警。")
        elif muted is False:
            st.caption("温度或湿度越限，蜂鸣器正在报警。")
        else:
            st.caption("报警已触发，声音状态待更新。")
        st.html('<p class="calendar-sound-note">消音不会关闭监测。约10秒后51复检：仍超限会再次报警，恢复范围内则解除报警。</p>')
        mute_column, unmute_column = st.columns(2, gap="medium")
        with mute_column:
            if st.button("消音约10秒", key="mute", disabled=not (ready and alarm and muted is False), use_container_width=True):
                send_command(client, {"AlarmMuted": True}, "临时消音已开启（仍超限将再次报警）")
                st.rerun()
        with unmute_column:
            if st.button("恢复声音", key="unmute", disabled=not (ready and alarm and muted is True), use_container_width=True):
                send_command(client, {"AlarmMuted": False}, "本次报警声音已恢复")
                st.rerun()

    motor_ready = state.get("motor_control_ready", False) and ready
    motor_labels = ("停止电机", "低档 · 40%", "中档 · 55%", "高档 · 70%")
    with st.container(key="calendar-motor-controls"):
        now_ms = int(time.time() * 1000)
        st.html('<div id="calendar-motor-settings"></div>' + motor_controls_heading_html(state, motor_ready, now_ms))
        # Selection reflects an actual fresh report, never the clicked target.
        actual_level = state.get("motor_level") if (state.get("online") and state.get("motor_valid")
            and -5_000 <= now_ms - state.get("motor_at", 0) < 20_000) else None
        for level, column in enumerate(st.columns(4, gap="small")):
            with column:
                if st.button(motor_labels[level], key=f"cloud_motor_{level}", disabled=not motor_ready,
                             type="primary" if actual_level == level else "secondary", use_container_width=True):
                    send_command(client, {"MotorTarget": level}, "电机档位已核对为" + motor_labels[level])
                    st.rerun()
        if motor_ready:
            st.caption("选择一个档位，仅下发一次；收到51确认与新档位回报后才算成功。")
        elif not state.get("online"):
            st.caption("设备离线或数据过期，暂停云端调速；离线不代表电机已经停止。")
        elif not ready:
            st.caption("双向控制尚未就绪，等待设备最新回报后再操作。")
        else:
            st.caption("等待电机有效回报或MotorTarget物模型，暂不能下发。")
        st.html('<p class="calendar-motor-caution">请勿与按键或蓝牙同时调速。断网不会自动停机，云端停止不能替代板上停止。</p>')

    st.html(settings_summary_html(state))
    if not ready:
        st.caption("连接设备后可操作；离线、数据过期或双向通信未就绪时暂停修改。")
    note, reset = st.columns([2, 1], gap="medium")
    with note:
        st.caption("编辑草稿不会被自动刷新覆盖。重新载入可放弃草稿，恢复设备最新设置。")
    with reset:
        st.button("重新载入设备设置", key="reset_drafts", on_click=reset_drafts, disabled=not ready, use_container_width=True, help="放弃当前编辑草稿，以设备最新回传值填入设置。")


def render_history(client, identity):
    st.html(trend_heading_html())
    try:
        history = read_history(identity, client)
    except Exception:
        st.html(empty_trend_html("历史曲线暂不可用，实时监测不受影响"))
        return
    temperature, humidity = history["temperature"], history["humidity"]
    if not temperature and not humidity:
        st.html(empty_trend_html())
        st.caption("这一小时暂无有效历史记录，等待设备上报。")
        return
    st.altair_chart(history_chart(history), width="stretch", theme=None, alt="OneNet真实温湿度历史：温度使用左轴，湿度使用右轴，时间为北京时间。")
    st.caption(f"OneNet真实记录 · 温度 {len(temperature)} 点 / 湿度 {len(humidity)} 点 · 左轴 °C，右轴 %RH")


def main():
    try:
        try:
            secret_values = st.secrets.to_dict()
        except FileNotFoundError:
            secret_values = {}
        settings = load_settings(secret_values)
    except (SettingsError, FileNotFoundError):
        st.html(header_html())
        st.warning("在线服务尚未配置。请在 Streamlit Cloud 的 Secrets 中填写OneNet设备授权。")
        st.caption("需要的配置名：ONENET_TOKEN、ONENET_PRODUCT_ID、ONENET_DEVICE_NAME。不要把真实值上传GitHub。")
        st.stop()
    except Exception:
        st.error("配置读取失败，请检查 Secrets 的TOML格式。")
        st.stop()

    st.html(header_html())
    st.html(navigation_html())
    st.caption("OneNet在线版 · 公开查看与控制 · 手机与电脑共用")
    client = OneNetClient(settings.cloud)
    identity = (settings.cloud.product, settings.cloud.device, hashlib.sha256(settings.cloud.token.encode()).hexdigest())

    @st.fragment(run_every="5s")
    def live_dashboard():
        error = None
        try:
            data = read_live(identity, client)
            properties = data["properties"]
            gateway = data["gateway_status"]
            st.session_state["last_properties"] = properties
        except OneNetError as problem:
            error = str(problem)
            properties = st.session_state.get("last_properties", [])
            gateway = 0
        except Exception:
            error = "OneNet暂时无法访问，请稍后刷新。"
            properties = st.session_state.get("last_properties", [])
            gateway = 0
        now_ms = int(time.time() * 1000)
        state = snapshot(properties, now_ms)
        if gateway != 1 or error:
            state.update(online=False, ready=False, humidity_ready=False, temperature=None, humidity=None, time=None, alarm=None, muted=None,
                         temperature_alarm=None, humidity_alarm=None, motor_control_ready=False)
        st.session_state["current_snapshot"] = state
        st.session_state["current_gateway"] = gateway
        if st.session_state.get("alcohol_history_identity") != identity:
            st.session_state["alcohol_history_identity"] = identity
            st.session_state["alcohol_samples"] = []
        st.session_state["alcohol_samples"] = record_alcohol_sample(
            st.session_state.get("alcohol_samples", []), state, gateway == 1 and state["online"], now_ms)
        signature = (gateway, state["ready"], state["alarm"], state["muted"], state["low"], state["high"],
                     state["humidity_ready"], state["humidity_low"], state["humidity_high"],
                     state["temperature_alarm"], state["humidity_alarm"], state["motor_control_ready"],
                     state["motor_level"], state["motor_pwm"])
        previous = st.session_state.get("controls_signature")
        if previous is not None and previous != signature:
            # 仅在控制状态/已生效阈值变化时重绘，草稿不会被常规轮询覆盖。
            st.session_state["controls_signature"] = signature
            st.rerun()
        st.session_state["controls_signature"] = signature
        if error:
            st.warning(error)
        st.html(dashboard_html(state, gateway, now_ms, st.session_state["alcohol_samples"]))
        notice = st.session_state.get("command_notice")
        if notice:
            (st.success if notice[0] else st.warning)(notice[1])
        if st.button("立即刷新", key="refresh_now", use_container_width=True):
            read_live.clear()
            read_history.clear()
            st.rerun()

    live_dashboard()
    @st.fragment(run_every="5s")
    def history_dashboard():
        state = st.session_state["current_snapshot"]
        gateway = st.session_state["current_gateway"]
        with st.container(key="calendar-trend-panel"):
            render_history(client, identity)
        with st.expander("连接信息与操作记录", expanded=False):
            st.write("ESP网关：" + ("在线" if gateway == 1 else "离线或不可访问"))
            st.write("51采集：" + ("在线，状态新鲜" if state["online"] else "离线或数据超过20秒"))
            st.write("双向控制：" + ("就绪" if state["ready"] else "未就绪"))
            st.caption("产品ID：" + settings.cloud.product + "　设备名称：" + settings.cloud.device)
            if state.get("updated_at"):
                last = datetime.fromtimestamp(state["updated_at"] / 1000, CHINA)
                st.caption("最近上报：" + last.strftime("%Y-%m-%d %H:%M:%S") + "（北京时间）")
            records = st.session_state.get("operation_log", [])
            if records:
                st.dataframe(records, hide_index=True, use_container_width=True)
            else:
                st.caption("本次浏览尚无控制记录。")
            st.caption("这里只显示本次浏览会话的操作记录，不是永久审计日志。")

    history_dashboard()
    with st.container(key="calendar-settings-panel"):
        state = st.session_state["current_snapshot"]
        st.html(settings_heading_html(state["ready"]))
        render_controls(client, state)
    st.html(footer_html())


if __name__ == "__main__":
    main()

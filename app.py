"""时序日历 · Streamlit 在线版。OneNet 请求与控制都在服务器执行。"""

from datetime import datetime, timedelta, timezone
from pathlib import Path
from threading import Lock
import hashlib
import re
import time
import uuid

import altair as alt
import pandas as pd
import streamlit as st

from auth import LoginGuard, authenticated, sign_out
from onenet import OneNetClient, OneNetError, snapshot
from settings import SettingsError, load_settings
from ui import dashboard_html, footer_html, header_html, login_html

BASE = Path(__file__).resolve().parent
CHINA = timezone(timedelta(hours=8))

st.set_page_config(page_title="时序日历 · 多功能电子万年历", page_icon="📅", layout="wide")
st.html("<style>" + (BASE / "assets" / "theme.css").read_text(encoding="utf-8") + "</style>")


@st.cache_resource
def login_guard():
    return LoginGuard()


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
    for key in ("draft_low", "draft_high", "draft_date", "draft_time"):
        st.session_state.pop(key, None)


def add_log(text, good):
    records = st.session_state.get("operation_log", [])
    records.insert(0, {"时间": china_now().strftime("%H:%M:%S"), "操作结果": text, "状态": "已确认" if good else "未确认"})
    st.session_state["operation_log"] = records[:10]


def send_command(client, settings, params, label):
    # 每一次提交都再次检查登录，不能仅依赖控件是否为灰色。
    if not authenticated(st.session_state, settings.password):
        sign_out(st.session_state)
        st.rerun()
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


def render_controls(client, settings, state):
    ready = state["ready"]
    if not ready:
        st.info("设备离线、数据过期或双向通信未就绪，暂不允许修改设置。")

    # 只初始化一次草稿。定时刷新只更新监测区，不覆盖正在输入的设置。
    defaults = state.get("time") or state.get("last_time") or china_now()
    for key, value in {
        "draft_low": state["low"] if state["low"] is not None else 5,
        "draft_high": state["high"] if state["high"] is not None else 45,
        "draft_date": defaults.date(),
        "draft_time": defaults.strftime("%H:%M:%S"),
    }.items():
        if key not in st.session_state:
            st.session_state[key] = value

    with st.container(border=True):
        st.subheader("温度提醒范围")
        st.caption("下限与上限一起写入51；数值范围为0–99℃。")
        with st.form("limits_form", clear_on_submit=False):
            cols = st.columns(2)
            with cols[0]:
                low = st.number_input("下限 / ℃", min_value=0, max_value=99, step=1, key="draft_low", disabled=not ready)
            with cols[1]:
                high = st.number_input("上限 / ℃", min_value=0, max_value=99, step=1, key="draft_high", disabled=not ready)
            if st.form_submit_button("保存温度范围", type="primary", disabled=not ready, use_container_width=True):
                send_command(client, settings, {"TemperatureLow": int(low), "TemperatureHigh": int(high)}, "温度范围已更新")
                st.rerun()

    with st.container(border=True):
        st.subheader("设备日期与时间")
        st.caption("显示和写入的均为51的DS1302时间，不是手机时钟。")
        with st.form("clock_form", clear_on_submit=False):
            date_value = st.date_input("日期", min_value=datetime(2000, 1, 1).date(), max_value=datetime(2099, 12, 31).date(), key="draft_date", disabled=not ready)
            clock_value = st.text_input("时间（时:分:秒）", key="draft_time", max_chars=8, placeholder="13:45:22", disabled=not ready)
            if st.form_submit_button("写入设备时间", type="primary", disabled=not ready, use_container_width=True):
                if not re.fullmatch(r"\d{2}:\d{2}:\d{2}", clock_value):
                    st.session_state["command_notice"] = (False, "时间请按 时:分:秒 填写，例如13:45:22。")
                else:
                    send_command(client, settings, {"DeviceTime": date_value.isoformat() + " " + clock_value}, "日期时间已更新")
                st.rerun()
        if st.button("一键同步北京时间", key="sync_clock", disabled=not ready, use_container_width=True):
            # Cloud 主机可能使用UTC，这里明确转换UTC+8，避免写入晚8小时的RTC。
            send_command(client, settings, {"DeviceTime": china_now().strftime("%Y-%m-%d %H:%M:%S")}, "北京时间已同步")
            st.rerun()
        st.caption("同步取云端服务器当前时间并转换为UTC+8，不读取手机系统时钟。")

    with st.container(border=True):
        st.subheader("本次报警声音")
        alarm = state.get("alarm") is True
        muted = state.get("muted")
        if not alarm:
            st.caption("当前没有有效温度报警，无需静音。")
        else:
            st.caption("本次报警已静音。" if muted else "当前温度报警正在发声。")
        cols = st.columns(2)
        with cols[0]:
            if st.button("本次静音", key="mute", disabled=not (ready and alarm and muted is False), use_container_width=True):
                send_command(client, settings, {"AlarmMuted": True}, "本次报警已静音")
                st.rerun()
        with cols[1]:
            if st.button("恢复声音", key="unmute", disabled=not (ready and alarm and muted is True), use_container_width=True):
                send_command(client, settings, {"AlarmMuted": False}, "本次报警声音已恢复")
                st.rerun()

    st.button("重新载入设备设置", key="reset_drafts", on_click=reset_drafts, disabled=not ready, use_container_width=True, help="放弃当前编辑草稿，以设备最新回传值填入设置。")
    st.caption("输入不会随刷新被覆盖。使用“重新载入设备设置”可放弃草稿。")


def render_history(client, identity):
    with st.container(border=True):
        st.subheader("最近一小时")
        selection = st.radio("曲线指标", ["温度", "湿度"], horizontal=True, label_visibility="collapsed", key="chart_metric")
        try:
            history = read_history(identity, client)
        except Exception:
            st.caption("历史曲线暂不可用，实时监测不受影响。")
            return
        series = history["temperature" if selection == "温度" else "humidity"]
        if not series:
            st.caption("这一小时暂无有效历史记录，等待设备上报。")
            return
        unit = "℃" if selection == "温度" else "%"
        frame = pd.DataFrame({
            "时间": [datetime.fromtimestamp(p["time"] / 1000, CHINA).replace(tzinfo=None) for p in series],
            "数值": [p["value"] for p in series],
        })
        chart = alt.Chart(frame).mark_line(color="#c57945" if selection == "温度" else "#368f89", strokeWidth=2.5, point=False).encode(
            x=alt.X("时间:T", axis=alt.Axis(title="北京时间", format="%H:%M", labelAngle=0)),
            y=alt.Y("数值:Q", axis=alt.Axis(title=selection + " / " + unit), scale=alt.Scale(zero=False)),
            tooltip=[alt.Tooltip("时间:T", format="%H:%M:%S"), alt.Tooltip("数值:Q", title=selection + " / " + unit)],
        ).properties(height=220).configure_view(stroke=None).configure_axis(gridColor="#edf0f1", labelColor="#75858e", titleColor="#75858e")
        st.altair_chart(chart, use_container_width=True)
        st.caption("来自OneNet真实历史记录；云端温度为整数，与物模型一致。")


def main():
    try:
        try:
            secret_values = st.secrets.to_dict()
        except FileNotFoundError:
            secret_values = {}
        settings = load_settings(secret_values)
    except (SettingsError, FileNotFoundError):
        st.html(login_html())
        st.warning("在线服务尚未配置。请在 Streamlit Cloud 的 Secrets 中填写访问密码与OneNet设备授权。")
        st.caption("需要的配置名：CALENDAR_PASSWORD、ONENET_TOKEN、ONENET_PRODUCT_ID、ONENET_DEVICE_NAME。不要把真实值上传GitHub。")
        st.stop()
    except Exception:
        st.error("配置读取失败，请检查 Secrets 的TOML格式。")
        st.stop()

    if not authenticated(st.session_state, settings.password):
        st.html(login_html())
        if "login_attempt_id" not in st.session_state:
            st.session_state["login_attempt_id"] = uuid.uuid4().hex
        with st.form("login_form"):
            password = st.text_input("网页访问密码", type="password", max_chars=128, key="login_password")
            if st.form_submit_button("进入时序日历", type="primary", use_container_width=True):
                ok, error = login_guard().attempt(st.session_state["login_attempt_id"], password, settings.password, st.session_state)
                if ok:
                    st.session_state.pop("login_password", None)
                    st.rerun()
                st.error(error)
        st.caption("仅持有访问密码的人可查看和控制此设备。刷新页面后可能需要重新登录。")
        st.stop()

    st.html(header_html())
    top = st.columns([3, 1])
    with top[0]:
        st.caption("OneNet在线版 · 自动刷新5秒 · 手机与电脑共用")
    with top[1]:
        if st.button("退出登录", use_container_width=True):
            sign_out(st.session_state)
            st.rerun()
    client = OneNetClient(settings.cloud)
    identity = (settings.cloud.product, settings.cloud.device, hashlib.sha256(settings.cloud.token.encode()).hexdigest())

    @st.fragment(run_every="5s")
    def live_dashboard():
        if not authenticated(st.session_state, settings.password):
            sign_out(st.session_state)
            st.rerun()
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
            state.update(online=False, ready=False, temperature=None, humidity=None, time=None, alarm=None, muted=None)
        st.session_state["current_snapshot"] = state
        signature = (gateway, state["ready"], state["alarm"], state["muted"])
        previous = st.session_state.get("controls_signature")
        if previous is not None and previous != signature:
            # 只在控制可用性变化时重绘设置，不让5秒轮询持续重建输入表单。
            st.session_state["controls_signature"] = signature
            st.rerun()
        st.session_state["controls_signature"] = signature
        if error:
            st.warning(error)
        st.html(dashboard_html(state, gateway, now_ms))
        notice = st.session_state.get("command_notice")
        if notice:
            (st.success if notice[0] else st.warning)(notice[1])
        if st.button("立即刷新", key="refresh_now", use_container_width=True):
            read_live.clear()
            read_history.clear()
            st.rerun()

        tabs = st.tabs(["环境趋势", "运行信息"])
        with tabs[0]:
            render_history(client, identity)
        with tabs[1]:
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
                st.caption("本次登录尚无控制记录。")
            st.caption("这里只显示本次浏览会话的操作记录，不是永久审计日志。")

    live_dashboard()
    with st.expander("日历设置 · 时间、提醒与声音", expanded=False):
        render_controls(client, settings, st.session_state["current_snapshot"])
    st.html(footer_html())


if __name__ == "__main__":
    main()

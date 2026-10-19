"""Escaped, presentation-only HTML for the online calendar.

The app owns OneNet requests and all write actions. These helpers
only render a snapshot; notably they never pretend a disconnected RTC is ticking.
"""

from __future__ import annotations

import calendar
from base64 import b64encode
from datetime import date, datetime, timedelta, timezone
from html import escape
import math
from typing import Any


SHANGHAI = timezone(timedelta(hours=8))
STALE_AFTER_MS = 20_000
WEEKDAYS = ("星期一", "星期二", "星期三", "星期四", "星期五", "星期六", "星期日")


def _text(value: Any) -> str:
    return escape(str(value), quote=True)


def _flag(value: Any) -> bool | None:
    """Missing/invalid flags stay unknown, rather than masquerading as False."""
    if value is True or value == "true" or value == "1":
        return True
    if value is False or value == "false" or value == "0":
        return False
    if type(value) in (int, float):
        if value == 1:
            return True
        if value == 0:
            return False
    return None


def _truth(value: Any) -> bool:
    return _flag(value) is True


def _number(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        result = float(value)
    except (ValueError, TypeError, OverflowError):
        return None
    return result if math.isfinite(result) else None


def _instant(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        result = value.astimezone(SHANGHAI).replace(tzinfo=None) if value.tzinfo else value
        return result if 2000 <= result.year <= 2099 else None
    if isinstance(value, str):
        try:
            result = datetime.fromisoformat(value)
            result = result.astimezone(SHANGHAI).replace(tzinfo=None) if result.tzinfo else result
            return result if 2000 <= result.year <= 2099 else None
        except ValueError:
            pass
    return None


def _fresh(timestamp: Any, now_ms: int) -> bool:
    instant = _number(timestamp)
    return instant is not None and 0 < instant <= now_ms + 5_000 and now_ms - instant < STALE_AFTER_MS


def _display_number(value: Any, minimum: float, maximum: float, decimals: int | None = None) -> str:
    number = _number(value)
    if number is None or not minimum <= number <= maximum:
        return "--"
    return f"{number:.{decimals}f}" if decimals is not None else f"{number:g}"


def _timestamp_label(value: Any) -> str:
    timestamp = _number(value)
    if timestamp is None or timestamp <= 0:
        return "--"
    try:
        return datetime.fromtimestamp(timestamp / 1000, SHANGHAI).strftime("%H:%M:%S")
    except (OverflowError, OSError, ValueError):
        return "--"


def _icon(name: str) -> str:
    paths = {
        "calendar": '<rect x="4" y="6" width="16" height="15" rx="3"/><path d="M4 11h16M8 3v6M16 3v6"/><circle cx="12" cy="16" r="1.5" class="calendar-icon-fill"/>',
        "clock": '<circle cx="12" cy="12" r="9"/><path d="M12 6v6l4 2"/>',
        "temperature": '<path d="M14 14.8V5a3 3 0 0 0-6 0v9.8a5 5 0 1 0 6 0Z"/><path d="M11 7v10"/>',
        "humidity": '<path d="M12 3S6.5 9.1 6.5 14a5.5 5.5 0 0 0 11 0C17.5 9.1 12 3 12 3Z"/><path d="M9 15.5c.7 1.1 1.7 1.6 3 1.6"/>',
        "bell": '<path d="M6 9a6 6 0 0 1 12 0c0 7 3 7 3 7H3s3 0 3-7ZM10 20h4"/>',
        "alcohol": '<path d="M9 3h6M10 3v6l-5 9a2 2 0 0 0 2 3h10a2 2 0 0 0 2-3l-5-9V3M8 14h8"/>',
        "motor": '<circle cx="12" cy="12" r="2"/><path d="M12 10C6 2 17 1 17 6c0 2-2 4-4 5M14 12c9-1 6 10 1 7-2-1-3-3-3-5M10 13c-4 8-11 0-6-3 2-1 4 0 6 1"/>',
    }
    return ('<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" '
            'stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" '
            f'aria-hidden="true">{paths[name]}</svg>')


def _feature_icon(name: str) -> str:
    # st.html sanitizes inline SVG. A static SVG image preserves these local,
    # decorative icons without scripts, remote assets or changing older panels.
    color = "#547782" if name == "motor" else "#4f8271"
    svg = _icon(name).replace('<svg ', '<svg xmlns="http://www.w3.org/2000/svg" ', 1).replace("currentColor", color)
    source = b64encode(svg.encode("utf-8")).decode("ascii")
    return f'<img src="data:image/svg+xml;base64,{source}" alt="" aria-hidden="true"/>'


def header_html() -> str:
    return """
    <header class="calendar-topbar" aria-label="时序日历 · 多功能电子万年历">
      <div class="calendar-brand">
        <div class="calendar-brand-mark" aria-hidden="true">时</div>
        <div class="calendar-brand-copy"><h1>时序 · 万年历</h1><p lang="en">CALENDAR / DEVICE</p></div>
      </div>
      <div class="calendar-edition"><span class="calendar-cloud-dot"></span>云端日历</div>
    </header>
    """


def navigation_html() -> str:
    return """
    <nav class="calendar-navigation" aria-label="日历页面导航">
      <a href="#calendar-monitor" target="_self">实时数据</a>
      <a href="#calendar-history" target="_self">历史趋势</a>
      <a class="calendar-settings-link" href="#calendar-settings" target="_self">设备设置 <span aria-hidden="true">↗</span></a>
      <span>自动刷新 5 秒</span>
    </nav>
    """


def settings_heading_html(ready: bool) -> str:
    status = "可以调整设备" if ready else "等待设备上线"
    return f"""
    <header id="calendar-settings" class="calendar-settings-heading">
      <div><h2>日历设置</h2><span>时间与提醒，按你的习惯调整。</span></div>
      <span class="calendar-settings-state">{status}</span>
    </header>
    """


def _alarm_parts(state: dict):
    temperature, humidity = _flag(state.get("temperature_alarm")), _flag(state.get("humidity_alarm"))
    alarm = _flag(state.get("alarm"))
    if not _truth(state.get("online")) or temperature is None or humidity is None or alarm is None or alarm != (temperature or humidity):
        return None, None
    return temperature, humidity


def _alarm_source_label(state: dict) -> str:
    temperature, humidity = _alarm_parts(state)
    if temperature and humidity:
        return "温湿度同时越限"
    if temperature:
        return "温度越限"
    if humidity:
        return "湿度越限"
    return "设备越限"


def _reminder_rows_html(state: dict) -> str:
    online = _truth(state.get("online"))
    parts = _alarm_parts(state)
    rows = []
    for label, lower, upper, maximum, unit, part, sensor, accent in (
        ("温度", "low", "high", 99, "°C", parts[0], "temperature", "warm"),
        ("湿度", "humidity_low", "humidity_high", 100, "%RH", parts[1], "humidity", "cool"),
    ):
        low, high = _number(state.get(lower)), _number(state.get(upper))
        valid = online and low is not None and high is not None and 0 <= low < high <= maximum
        limits = f'<span class="calendar-range-number">{low:g}</span><span>–</span><span class="calendar-range-number">{high:g}</span><small>{unit}</small>' if valid else '等待阈值上报'
        status, tone = ("越限", "exceeded") if part is True else ("未越限", "normal")
        if not online or part is None:
            status, tone = "待上报", "waiting"
        elif part is False and state.get(sensor) is None:
            status, tone = "读数无效", "waiting"
        range_class = " calendar-range-waiting" if not valid else ""
        rows.append(f'<div class="calendar-reminder-row"><span class="calendar-reminder-label calendar-{accent}">{label}</span>'
                    f'<strong class="calendar-reminder-range{range_class}">{limits}</strong>'
                    f'<span class="calendar-reminder-badge calendar-badge-{tone}">{status}</span></div>')
    return '<div class="calendar-reminder-ranges">' + ''.join(rows) + '</div>'


def settings_summary_html(state: dict) -> str:
    online = _truth(state.get("online"))
    low, high = _number(state.get("low")), _number(state.get("high"))
    valid_limits = online and low is not None and high is not None and 0 <= low < high <= 99
    limits = f"{low:g} °C <span>–</span> {high:g} °C" if valid_limits else "-- °C <span>–</span> -- °C"
    humidity_low, humidity_high = _number(state.get("humidity_low")), _number(state.get("humidity_high"))
    valid_humidity = online and humidity_low is not None and humidity_high is not None and 0 <= humidity_low < humidity_high <= 100
    humidity_limits = f"{humidity_low:g}% <span>–</span> {humidity_high:g}%" if valid_humidity else "--% <span>–</span> --%"
    alarm, muted = _flag(state.get("alarm")), _flag(state.get("muted"))
    if not online or alarm is None:
        status, note, tone = "等待信息", "连接后显示设备状态", "waiting"
    elif alarm is False:
        status, note, tone = "当前无报警", "当前设备未触发超限报警", "normal"
    elif muted is True:
        status, note, tone = _alarm_source_label(state) + " · 临时消音", "约10秒后仍超限会再次报警", "muted"
    elif muted is False:
        status, note, tone = _alarm_source_label(state), "蜂鸣器正在报警", "alarming"
    else:
        status, note, tone = _alarm_source_label(state), "声音状态待更新", "alarming"
    bar = f'<i style="left:{low:g}%;width:{high-low:g}%"></i>' if valid_limits else ""
    return f"""
    <div class="calendar-settings-summary">
      <div><p>当前温度范围</p><strong>{limits}</strong><div class="calendar-range-track" aria-hidden="true">{bar}</div></div>
      <div><p>当前湿度范围</p><strong>{humidity_limits}</strong><small>相对湿度 %RH</small></div>
      <div><p>提醒状态</p><div class="calendar-summary-state calendar-summary-{tone}"><i aria-hidden="true"></i>{status}</div><small>{note}</small></div>
    </div>
    """


def trend_heading_html() -> str:
    return """
    <header id="calendar-history" class="calendar-trend-heading">
      <div><h2>温湿度变化</h2><p>最近一小时 · 每项最多120次采样</p></div>
      <div class="calendar-trend-legend" aria-label="曲线图例"><span class="calendar-legend-temperature"><i></i>温度</span><span class="calendar-legend-humidity"><i></i>湿度</span></div>
    </header>
    """


def empty_trend_html(message: str = "连接设备后，温湿度变化会显示在这里") -> str:
    rows = "".join(
        f'<div class="calendar-grid-row"><span>{temperature}</span><i></i><span>{humidity}</span></div>'
        for temperature, humidity in ((40, 100), (30, 75), (20, 50), (10, 25), (0, 0))
    )
    return f"""
    <div class="calendar-empty-trend" role="img" aria-label="暂无历史数据，网格仅为坐标参考">
      <div class="calendar-chart-units"><span>温度 °C</span><span>湿度 %RH</span></div>
      <div class="calendar-empty-grid">{rows}<p class="calendar-empty-message">{_text(message)}</p></div>
    </div>
    """


def _month_html(view_date: date, label: str) -> str:
    rows = []
    for week in calendar.Calendar(firstweekday=0).monthdatescalendar(view_date.year, view_date.month):
        cells = []
        for day in week:
            classes = []
            if day.month != view_date.month:
                classes.append("calendar-outside")
            if day == view_date:
                classes.append("calendar-selected")
            if day.weekday() >= 5:
                classes.append("calendar-weekend")
            class_attr = f' class="{" ".join(classes)}"' if classes else ""
            selected = ' aria-current="date"' if day == view_date else ""
            cells.append(f'<td{class_attr}{selected}><span>{day.day}</span></td>')
        rows.append(f'<tr>{"".join(cells)}</tr>')
    headings = "".join(f'<th scope="col">{name}</th>' for name in "一二三四五六日")
    return f"""
      <div class="calendar-month-sheet">
        <div class="calendar-month-heading"><strong>{view_date.month:02d}<small> 月</small></strong><span>{view_date.year}</span></div>
        <table class="calendar-month-table" aria-label="{view_date.year}年{view_date.month}月月历">
          <thead><tr>{headings}</tr></thead><tbody>{''.join(rows)}</tbody>
        </table>
        <p class="calendar-month-label">{_text(label)}</p>
      </div>
    """


def _extension_values(snapshot: dict, online: bool, now_ms: int) -> tuple:
    """Recheck freshness at presentation time; old state must not look live."""
    raw = _number(snapshot.get("alcohol_raw"))
    alcohol = (online and _truth(snapshot.get("alcohol_valid")) and raw is not None
               and raw.is_integer() and 0 <= raw <= 4095 and _fresh(snapshot.get("alcohol_at"), now_ms))
    level, pwm = _number(snapshot.get("motor_level")), _number(snapshot.get("motor_pwm"))
    motor = (online and _truth(snapshot.get("motor_valid")) and level is not None
             and level.is_integer() and 0 <= level <= 3 and pwm == (0, 40, 55, 70)[int(level)]
             and _fresh(snapshot.get("motor_at"), now_ms))
    return raw, alcohol, level, pwm, motor


def _clean_alcohol_history(history: list, now_ms: int) -> list:
    samples = {}
    for point in history:
        if not isinstance(point, dict):
            continue
        at, raw = _number(point.get("time")), point.get("raw")
        if at is None or not 0 < at <= now_ms + 5_000 or now_ms - at > 3_600_000:
            continue
        if raw is None or (type(raw) is int and 0 <= raw <= 4095):
            samples[int(at)] = raw
    return [{"time": at, "raw": samples[at]} for at in sorted(samples)][-120:]


def record_alcohol_sample(history: list, snapshot: dict, online: bool, now_ms: int) -> list:
    """A bounded, session-local observation history; no network or fabricated points.

    None marks an observed invalid/offline interval, even when shorter than 20s.
    Re-reading a cached property does not add another point or move its timestamp.
    """
    result = _clean_alcohol_history(history, now_ms)
    raw, valid, _, _, _ = _extension_values(snapshot, online, now_ms)
    if valid:
        at = int(_number(snapshot.get("alcohol_at")))
        if not result or at > result[-1]["time"]:
            result.append({"time": at, "raw": int(raw)})
    elif result and result[-1]["raw"] is not None:
        result.append({"time": max(now_ms, result[-1]["time"] + 1), "raw": None})
    return result[-120:]


def alcohol_trend_html(history: list | None, now_ms: int, active: bool) -> str:
    """Static SVG of received samples, fixed 0–5V scale, with explicit gaps."""
    points = _clean_alcohol_history(history or [], now_ms)
    valid = [point for point in points if point["raw"] is not None]
    paths, segments, current = [], [], []
    start = points[0]["time"] if points else now_ms
    end = max(points[-1]["time"], start + 1) if points else now_ms + 1
    previous = None
    for point in points:
        if point["raw"] is None or (previous is not None and point["time"] - previous >= STALE_AFTER_MS):
            if current:
                segments.append(current)
                current = []
        if point["raw"] is not None:
            x = 30 + (point["time"] - start) / (end - start) * 294 if len(valid) > 1 else 324
            voltage = (((point["raw"] >> 3) * 125) >> 7) / 100
            current.append((x, 91 - voltage / 5 * 76))
            previous = point["time"]
        else:
            previous = None
    if current:
        segments.append(current)
    for segment in segments:
        coordinates = " ".join(f"{x:.2f},{y:.2f}" for x, y in segment)
        if len(segment) > 1:
            paths.append(f'<polygon points="{segment[0][0]:.2f},91 {coordinates} {segment[-1][0]:.2f},91" fill="currentColor" opacity=".08"/>')
            paths.append(f'<polyline points="{coordinates}" fill="none" stroke="currentColor" stroke-width="2" vector-effect="non-scaling-stroke"/>')
        else:
            x, y = segment[0]
            paths.append(f'<circle cx="{x:.2f}" cy="{y:.2f}" r="2.5" fill="currentColor"/>')
    first = _timestamp_label(valid[0]["time"]) if valid else "--:--:--"
    last = _timestamp_label(valid[-1]["time"]) if valid else "--:--:--"
    status = f"{len(valid)} 个有效点" if active else f"历史片段 · {len(valid)} 点" if valid else "等待有效采样"
    empty = '<p class="calendar-alcohol-trend-empty">收到有效采样后显示趋势</p>' if not valid else ""
    chart = f'''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 340 116" preserveAspectRatio="none">
        <style>.calendar-alcohol-grid path{{fill:none;stroke:#e9efea;stroke-width:1}}.calendar-alcohol-grid text{{fill:#8c9c92;font-family:Segoe UI,Arial,sans-serif;font-size:10px}}.calendar-alcohol-trace{{color:{'#6c9d80' if active else '#a0b4a7'};stroke-linecap:round;stroke-linejoin:round}}</style>
        <g class="calendar-alcohol-grid"><path d="M30 15H324M30 53H324M30 91H324"/><text x="0" y="18">5 V</text><text x="0" y="56">2.5</text><text x="0" y="94">0</text><text x="30" y="112">{first}</text><text x="324" y="112" text-anchor="end">{last}</text></g>
        <g class="calendar-alcohol-trace">{''.join(paths)}</g></svg>'''
    source = b64encode(chart.encode("utf-8")).decode("ascii")
    return f'''<div class="calendar-alcohol-trend{' is-paused' if not active else ''}">
      <div class="calendar-alcohol-trend-head"><span>采样电压趋势</span><small>{status}</small></div>
      <div class="calendar-alcohol-plot"><img src="data:image/svg+xml;base64,{source}" alt="本次浏览酒精电压趋势，{len(valid)}个有效点，纵轴0至5V，缺报留空"/>{empty}</div>
      <p class="calendar-alcohol-trend-note">本次浏览 · 最多120点 · 断报留空，重开不保留</p>
    </div>'''


def motor_controls_heading_html(snapshot: dict, ready: bool, now_ms: int) -> str:
    _, _, level, pwm, valid = _extension_values(snapshot, _truth(snapshot.get("online")), now_ms)
    label = ("停止", "低档", "中档", "高档")[int(level)] if valid else "--"
    duty = str(int(pwm)) if valid else "--"
    badge = "可以调速" if ready else "暂不可操作"
    return f'''<div class="calendar-motor-control-heading">
      <div class="calendar-feature-title"><span class="calendar-feature-icon">{_feature_icon('motor')}</span><div><h3>电机调速</h3><p>云端下发 · 以51实际回报为准</p></div></div>
      <span class="calendar-module-state{' is-live' if ready else ''}">{badge}</span></div>
      <div class="calendar-motor-control-readout"><div><span>当前设备回报</span><strong>{label}</strong></div><div><span>PWM设定占空比</span><strong>{duty}<small>%</small></strong></div></div>'''


def expansion_html(snapshot: dict, online: bool, now_ms: int, alcohol_history: list | None = None) -> str:
    """Read-only additions; never infer a stopped motor or a calibrated ppm value."""
    raw, alcohol, level, pwm, motor = _extension_values(snapshot, online, now_ms)
    voltage = f'{(((int(raw) >> 3) * 125) >> 7) / 100:.2f}' if alcohol else "--"
    index = str((int(raw) * 100 + 2047) // 4095) if alcohol else "--"
    filled = (int(raw) + 256) >> 9 if alcohol else 0
    bars = ''.join(f'<i class="{"is-on" if i < filled else ""}"></i>' for i in range(8))
    raw_note = f'{int(raw)} / 4095' if alcohol else '-- / 4095'
    alcohol_status = "实时上报" if alcohol else "等待上报" if online else "等待设备"
    motor_status = "实时上报" if motor else "等待上报" if online else "等待设备"
    motor_text = ("停止", "低档", "中档", "高档")[int(level)] if motor else "--"
    motor_pwm = f'{int(pwm)}%' if motor else "--%"
    stages = ''.join(f'<span class="{"is-selected" if motor and int(level) == i else ""}"><b>{name}</b><small>{duty}%</small></span>'
                     for i, (name, duty) in enumerate(zip(("停", "低", "中", "高"), (0, 40, 55, 70))))
    track = f'<i style="width:{int(pwm) / 70 * 100:.3f}%"></i>' if motor else ''
    return f"""
      <section class="calendar-expansion" aria-label="酒精检测与电机只读状态">
        <div class="calendar-expansion-heading"><h2>拓展功能</h2><span>传感采样 / PWM调速</span></div>
        <div class="calendar-expansion-grid">
          <article class="calendar-card calendar-module calendar-alcohol{' is-live' if alcohol else ''}">
            <div class="calendar-module-head"><div class="calendar-feature-title"><span class="calendar-feature-icon">{_feature_icon('alcohol')}</span><div><h3>酒精检测</h3><p>MQ-3 · 模拟信号监测</p></div></div><span class="calendar-module-state{' is-live' if alcohol else ''}">{alcohol_status}</span></div>
            <p class="calendar-module-label">采样电压</p><div class="calendar-module-value">{voltage}<small> V</small></div>
            <div class="calendar-alcohol-response"><span>相对响应指数</span><span><b>{index}</b><small> / 100</small></span></div>
            <div class="calendar-alcohol-bars" role="img" aria-label="相对响应{index}/100，非浓度与安全等级">{bars}</div>
            {alcohol_trend_html(alcohol_history, now_ms, alcohol)}
            <p class="calendar-module-meta"><span>ADC原始采样 <b>{raw_note}</b></span><span>12位采样</span></p>
            <p class="calendar-module-note">需预热 · 按5V参考估算，与51显示一致；未标定浓度，指数不代表安全等级。</p>
          </article>
          <article class="calendar-card calendar-module calendar-motor">
            <div class="calendar-module-head"><div class="calendar-feature-title"><span class="calendar-feature-icon">{_feature_icon('motor')}</span><div><h3>电机状态</h3><p>直流电机 · 四档PWM</p></div></div><span class="calendar-module-state{' is-live' if motor else ''}">{motor_status}</span></div>
            <div class="calendar-motor-readout"><div><span>设备回报档位</span><strong>{motor_text}</strong></div><div><span>PWM设定占空比</span><strong>{motor_pwm}</strong></div></div>
            <div class="calendar-motor-stages" aria-label="档位指示，设备回报{motor_text}，仅显示不可点击">{stages}</div>
            <div class="calendar-pwm-heading"><span>占空比范围</span><small>最高70% PWM</small></div>
            <div class="calendar-pwm-track" role="img" aria-label="PWM设定{motor_pwm}，非实测转速">{track}</div><div class="calendar-pwm-scale"><span>0%</span><span>35%</span><span>70%</span></div>
            <a class="calendar-motor-link" href="#calendar-motor-settings">调整电机档位<span aria-hidden="true">→</span></a>
            <p class="calendar-module-note">51真实档位回报 · PWM非实测转速。断网不自动停机，紧急停止请使用板上按键。</p>
          </article>
        </div>
      </section>
    """


def dashboard_html(snapshot: dict, gateway_status: int, now_ms: int, alcohol_history: list | None = None) -> str:
    """Return read-only overview HTML. ``updated_at`` / ``time_at`` use epoch ms.

    Sensor values must be normalized by the backend: invalid means None. A bool
    online flag alone is insufficient because a stale retained OneNet property
    is not proof that the 51 is still communicating. Missing timestamps are stale.
    """
    online = gateway_status == 1 and _truth(snapshot.get("online")) and _fresh(snapshot.get("updated_at"), now_ms)
    ready = online and _truth(snapshot.get("ready"))
    current_time = _instant(snapshot.get("time"))
    last_time = _instant(snapshot.get("last_time")) or current_time
    time_current = online and current_time is not None and _fresh(snapshot.get("time_at"), now_ms)
    shown_time = current_time if time_current else last_time

    if gateway_status != 1:
        status, detail = "设备离线", "ESP 暂未连接 OneNet，等待设备上线"
    elif not online:
        status, detail = "等待 51 数据", "ESP 已连接；51 数据尚未收到或超过 20 秒未更新"
    elif ready:
        status, detail = "设备在线", "51 与 ESP 通信正常 · 可以查看与调整设置"
    else:
        status, detail = "数据在线", "已收到 51 数据，双向控制尚未就绪"

    if shown_time:
        clock_text = shown_time.strftime("%H:%M:%S")
        date_text = shown_time.strftime("%Y 年 %m 月 %d 日")
        weekday = WEEKDAYS[shown_time.weekday()]
        calendar_date = shown_time.date()
        month_label = "设备日期" if time_current else "最后收到的设备日期"
    else:
        clock_text, date_text, weekday = "--:--:--", "等待设备时间", "星期 --"
        calendar_date = datetime.fromtimestamp(now_ms / 1000, SHANGHAI).date()
        month_label = "浏览日期，非设备时间"
    clock_label = "设备实时时钟" if time_current else "最后收到的设备时间" if shown_time else "设备实时时钟"
    clock_hint = "显示 51 的 RTC 上报值，每 5 秒刷新；不是手机时间。" if time_current else "当前未收到新时间，最后记录已冻结。" if shown_time else "设备上线后，这里将显示 51 的 RTC 时间。"

    temperature = _display_number(snapshot.get("temperature"), -40, 125, decimals=1) if online else "--"
    humidity = _display_number(snapshot.get("humidity"), 0, 100) if online else "--"
    temperature_note = "DS18B20 · 真实温度保留一位小数" if temperature != "--" else "暂未收到有效温度" if online else "设备离线，暂停显示实时温度"
    humidity_note = "DHT11 · 空气相对湿度" if humidity != "--" else "暂未收到有效湿度" if online else "设备离线，暂停显示实时湿度"
    alarm = _flag(snapshot.get("alarm")) if online else None
    muted = _flag(snapshot.get("muted")) if online else None
    if alarm is None:
        alarm_text, alarm_class = "等待报警状态", "calendar-unknown"
        alarm_note = "尚未收到有效报警状态，不判断是否正在报警。" if online else "离线时不会把旧报警显示为当前状态。"
    elif alarm is False:
        alarm_text, alarm_class = "当前无报警", ""
        alarm_note = "温度或湿度任一项越限时，蜂鸣器会提醒。"
    elif muted is None:
        alarm_text, alarm_class = _alarm_source_label(snapshot) + "（声音状态待更新）", "calendar-alarming"
        alarm_note = "报警状态已更新，静音状态尚未收到，不能判断当前声音。"
    elif muted is True:
        alarm_text, alarm_class = _alarm_source_label(snapshot) + " · 临时消音", "calendar-muted"
        alarm_note = "临时消音约10秒，仍超限将自动再次报警。"
    else:
        alarm_text, alarm_class = _alarm_source_label(snapshot), "calendar-alarming"
        alarm_note = "可在日历设置中临时消音约10秒。"
    if online and alarm is not None and _alarm_parts(snapshot)[0] is None:
        alarm_note = "等待分项上报；" + alarm_note
    status_class = "calendar-online" if online else "calendar-offline"
    last_update = _timestamp_label(snapshot.get("updated_at"))

    return f"""
    <div id="calendar-monitor" class="calendar-overview">
      <div class="calendar-link-strip">
        <div class="calendar-status {status_class}" role="status"><i aria-hidden="true"></i><strong>{status}</strong></div>
        <span>{detail}</span>
        <span class="calendar-update">最近上报 {_text(last_update)}</span>
      </div>
      <section class="calendar-card calendar-hero" aria-label="设备时钟与月历">
        <div class="calendar-clock-panel">
          <div class="calendar-clock-top"><span class="calendar-eyebrow">{_icon('clock')}{clock_label}</span><span class="calendar-source">51 · DS1302</span></div>
          <div class="calendar-clock{' calendar-clock-frozen' if not time_current else ''}">{clock_text}</div>
          <div class="calendar-date-row"><span>{date_text}</span><span class="calendar-weekday">{weekday}</span></div>
          <p class="calendar-clock-hint">{clock_hint}</p>
        </div>
        {_month_html(calendar_date, month_label)}
      </section>
      <section class="calendar-metrics" aria-label="温湿度与提醒状态">
        <article class="calendar-card calendar-metric">
          <div class="calendar-metric-head"><h2>当前温度</h2><span class="calendar-metric-icon calendar-warm">{_icon('temperature')}</span></div>
          <div class="calendar-value">{temperature}<small> °C</small></div>
          <p class="calendar-metric-note">{temperature_note}</p>
        </article>
        <article class="calendar-card calendar-metric">
          <div class="calendar-metric-head"><h2>空气湿度</h2><span class="calendar-metric-icon calendar-cool">{_icon('humidity')}</span></div>
          <div class="calendar-value">{humidity}<small> %</small></div>
          <p class="calendar-metric-note">{humidity_note}</p>
        </article>
        <article class="calendar-card calendar-reminder {alarm_class}">
          <div class="calendar-metric-head"><h2>温湿度提醒</h2><span class="calendar-reminder-kicker">阈值监测</span></div>
          {_reminder_rows_html(dict(snapshot, online=online))}
          <div class="calendar-reminder-status"><div class="calendar-alarm"><i aria-hidden="true"></i>{alarm_text}</div>
          <p class="calendar-metric-note">{alarm_note}</p></div>
        </article>
      </section>
      {expansion_html(snapshot, online, now_ms, alcohol_history)}
    </div>
    """


def footer_html() -> str:
    return """
    <footer class="calendar-footer"><span>时序日历 · 在线控制端</span><span>51 采集与计时 / ESP 联网 / OneNet 数据互通</span></footer>
    """

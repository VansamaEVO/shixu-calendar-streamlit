"""Escaped, presentation-only HTML for the online calendar.

The app owns authentication, OneNet requests and all write actions. These helpers
only render a snapshot; notably they never pretend a disconnected RTC is ticking.
"""

from __future__ import annotations

import calendar
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


def _display_number(value: Any, minimum: float, maximum: float) -> str:
    number = _number(value)
    if number is None or not minimum <= number <= maximum:
        return "--"
    return f"{number:g}"


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
    }
    return ('<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" '
            'stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" '
            f'aria-hidden="true">{paths[name]}</svg>')


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


def login_html() -> str:
    return f"""
    <section class="calendar-login">
      <div class="calendar-login-mark">{_icon('clock')}</div>
      <p class="calendar-kicker">YOUR CALENDAR, ANYWHERE</p>
      <h2>让时间与环境，<br>随手可见。</h2>
      <p class="calendar-login-description">输入访问密码，查看你的电子万年历。<br>手机和电脑，都能成为日历的另一块屏幕。</p>
      <div class="calendar-login-chips"><span>设备时间</span><span>温湿度</span><span>提醒设置</span></div>
    </section>
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


def dashboard_html(snapshot: dict, gateway_status: int, now_ms: int) -> str:
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

    temperature = _display_number(snapshot.get("temperature"), -40, 125) if online else "--"
    humidity = _display_number(snapshot.get("humidity"), 0, 100) if online else "--"
    temperature_note = "DS18B20 · OneNet 云端整数值" if temperature != "--" else "暂未收到有效温度" if online else "设备离线，暂停显示实时温度"
    humidity_note = "DHT11 · 空气相对湿度" if humidity != "--" else "暂未收到有效湿度" if online else "设备离线，暂停显示实时湿度"
    low = _display_number(snapshot.get("low"), 0, 99)
    high = _display_number(snapshot.get("high"), 0, 99)
    threshold_text = f"{low}–{high}" if low != "--" and high != "--" else "--"
    threshold_note = "当前设备设置" if online else "最后收到的设置" if threshold_text != "--" else "等待设备设置"
    alarm = _flag(snapshot.get("alarm")) if online else None
    muted = _flag(snapshot.get("muted")) if online else None
    if alarm is None:
        alarm_text, alarm_class = "等待报警状态", "calendar-unknown"
        alarm_note = "尚未收到有效报警状态，不判断是否正在报警。" if online else "离线时不会把旧报警显示为当前状态。"
    elif alarm is False:
        alarm_text, alarm_class = "当前无报警", ""
        alarm_note = "温度超出设定范围时，蜂鸣器会提醒。"
    elif muted is None:
        alarm_text, alarm_class = "温度超出提醒范围（声音状态待更新）", "calendar-alarming"
        alarm_note = "报警状态已更新，静音状态尚未收到，不能判断当前声音。"
    elif muted is True:
        alarm_text, alarm_class = "当前提醒已静音", "calendar-muted"
        alarm_note = "温度恢复正常后，下次越限会重新提醒。"
    else:
        alarm_text, alarm_class = "温度超出提醒范围", "calendar-alarming"
        alarm_note = "可在日历设置中关闭本次声音提醒。"
    status_class = "calendar-online" if online else "calendar-offline"
    last_update = _timestamp_label(snapshot.get("updated_at"))

    return f"""
    <div class="calendar-overview">
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
          <div class="calendar-metric-head"><h2>温度提醒</h2><span class="calendar-metric-icon calendar-neutral">{_icon('bell')}</span></div>
          <div class="calendar-limit">{threshold_text}<small> °C</small><span>{threshold_note}</span></div>
          <div class="calendar-alarm"><i aria-hidden="true"></i>{alarm_text}</div>
          <p class="calendar-metric-note">{alarm_note}</p>
        </article>
      </section>
    </div>
    """


def footer_html() -> str:
    return """
    <footer class="calendar-footer"><span>时序日历 · 在线控制端</span><span>51 采集与计时 / ESP 联网 / OneNet 数据互通</span></footer>
    """

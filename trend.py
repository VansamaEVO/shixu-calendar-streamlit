"""Two explicitly labelled axes, using only the supplied OneNet samples."""

from datetime import datetime, timedelta, timezone
import math

import altair as alt
import pandas as pd


CHINA = timezone(timedelta(hours=8))
TEMPERATURE_COLOR = "#c57945"
HUMIDITY_COLOR = "#368f89"


def history_chart(history):
    temperature = history.get("temperature", [])
    humidity = history.get("humidity", [])

    def frame(points):
        return pd.DataFrame({
            "时间": [datetime.fromtimestamp(point["time"] / 1000, CHINA).replace(tzinfo=None) for point in points],
            "数值": [point["value"] for point in points],
        })

    # 默认温度轴0–40℃；超出时扩展，不能裁掉实际的低温/高温读数。
    temperatures = [point["value"] for point in temperature]
    lower = min(0, math.floor((min(temperatures) - 2) / 10) * 10) if temperatures else 0
    upper = max(40, math.ceil((max(temperatures) + 2) / 10) * 10) if temperatures else 40

    def series(points, title, color, orient, domain):
        source = alt.Chart(frame(points))
        line = source.mark_line(color=color, strokeWidth=2.5, clip=True).encode(
            x=alt.X("时间:T", axis=alt.Axis(title="北京时间", format="%H:%M", labelAngle=0, tickCount=5, grid=False)),
            y=alt.Y("数值:Q", axis=alt.Axis(title=title, orient=orient, grid=orient == "left", titleColor=color, tickCount=5), scale=alt.Scale(domain=domain, nice=False)),
            tooltip=[alt.Tooltip("时间:T", title="北京时间", format="%H:%M:%S"), alt.Tooltip("数值:Q", title=title)],
        )
        # 单个样本仍可见；不补点、不插值生成虚假读数。
        dots = source.mark_point(color=color, filled=True, size=20, opacity=0.7).encode(
            x="时间:T", y="数值:Q",
            tooltip=[alt.Tooltip("时间:T", title="北京时间", format="%H:%M:%S"), alt.Tooltip("数值:Q", title=title)],
        )
        return alt.layer(line, dots)

    return alt.layer(
        series(temperature, "温度 / °C", TEMPERATURE_COLOR, "left", [lower, upper]),
        series(humidity, "湿度 / %RH", HUMIDITY_COLOR, "right", [0, 100]),
    ).resolve_scale(y="independent").properties(height=230).configure_view(stroke=None).configure_axis(
        gridColor="#e8edef", labelColor="#7d8e97", titleColor="#7d8e97", domain=False,
        ticks=False, labelPadding=10, titlePadding=14, labelFontSize=12, titleFontSize=13,
    )

"""读取 Cloud Secrets 或本地环境变量。这里只包含配置名，没有真实密钥。"""

from dataclasses import dataclass, field
import os
from onenet import OneNetSettings


class SettingsError(Exception):
    pass


@dataclass(frozen=True)
class AppSettings:
    cloud: OneNetSettings = field(repr=False)


def load_settings(secrets=None):
    source = secrets or {}

    def read(name):
        value = source.get(name, os.environ.get(name, ""))
        return value.strip() if isinstance(value, str) else ""

    token = read("ONENET_TOKEN")
    product = read("ONENET_PRODUCT_ID")
    device = read("ONENET_DEVICE_NAME")
    if not token or not product or not device:
        raise SettingsError("请在 Secrets 中填写 ONENET_TOKEN、ONENET_PRODUCT_ID 和 ONENET_DEVICE_NAME。")
    return AppSettings(OneNetSettings(token=token, product=product, device=device))

# 时序日历 · Streamlit 在线版

手机和电脑通过浏览器查看51电子万年历，在输入访问密码后调整设备日期、时间、温度提醒范围与本次报警声音。

此项目是独立在线版。原来的本地USB上位机网页、51固件、ESP8266固件和微信小程序均不需要替换。

## 功能

- DS1302设备时间、月历、DS18B20温度与DHT11湿度。
- 自动每5秒刷新；只显示有效、新鲜的采集状态。云端温度为整数，与当前OneNet物模型一致。
- 日期时间写入、一键同步北京时间、阈值修改、本次静音和恢复声音。
- 控制前检查登录、网关在线、51通信与状态新鲜度；收到设备确认并核对新上报的属性后才提示成功。
- 白色、深青与焦糖配色，手机窄屏布局；无外部字体或图片CDN依赖。
- 最近一小时OneNet真实历史曲线。历史记录缺失时不生成模拟曲线。

## 上传GitHub

建议建立独立私有仓库 `shixu-calendar-streamlit`。私有源码仓库不妨碍将Streamlit网页设置为公开访问，访问密码仍由此程序在服务器端校验。

只上传本项目的源码、测试、配置模板和依赖声明，不要上传 `.runtime/`、`.venv/`、`__pycache__/`、`.streamlit/secrets.toml` 或真实Token。

最少需要这些文件：

```text
app.py
auth.py
settings.py
onenet.py
ui.py
requirements.txt
assets/theme.css
.streamlit/config.toml
```

同时保留 `.gitignore`、`secrets.example.toml`、`tests/` 与本说明，可在GitHub上运行检查。上传GitHub只完成源码保存，还需下一步连接Streamlit Cloud，才产生在线网页。

## 部署到Streamlit Community Cloud

1. 打开 https://share.streamlit.io/ 并登录已关联GitHub的账号。
2. 选择创建应用/Deploy an app，选择该项目仓库。
3. Branch填写 `main`，Main file path填写 `app.py`。
4. 在Advanced settings中选择Python **3.12**。
5. 在Secrets中按 `secrets.example.toml` 的配置名填写真实值；不要提交到GitHub。
6. 确认网页允许老师访问（公开应用），部署完成后，老师仍需输入你设定的网页访问密码。

```toml
CALENDAR_PASSWORD = "你的网页访问密码，至少8位"
ONENET_TOKEN = "设备级Token的完整字符串，不加Bearer"
ONENET_PRODUCT_ID = "你的产品ID"
ONENET_DEVICE_NAME = "你的设备名称"
```

Token使用设备级授权即可，不需要用户级AccessKey。不要把Token放进网页URL、公开仓库、截图或老师分享链接。任何拿到访问密码的人都能操作此设备，请仅给需要演示的人。

## 本地运行

需要Python3.12，在项目目录安装并启动：

```text
python -m pip install -r requirements.txt
python -m streamlit run app.py
```

本地授权填在 `.streamlit/secrets.toml` 中，格式同上。该文件已被Git忽略，不应手动上传。也可以使用同名环境变量；Cloud Secrets优先。

## 测试

```text
python -m unittest discover -s tests -v
```

测试使用虚构密码、授权与模拟OneNet返回；不会控制真实硬件。AppTest覆盖登录、离线与过期数据、设置草稿、非法控制参数、命令确认与退出登录。

## 演示时的说明

- 当前RTC按设备上报值每5秒更新，不假装逐秒实时串流；离线时冻结最后收到的设备时间。
- “同步北京时间”使用云端服务器当前时间转换为UTC+8，**不是读取手机系统时钟**。
- 状态超过20秒、ESP离线或双向通信未就绪时禁用控制；网络异常、超时不自动重发命令，请先刷新核对状态。
- 设置区不参加常规5秒定时重绘；刷新监测不会主动覆盖服务端已保存的编辑草稿。
- 访问登录在服务器会话内保存，最长8小时；刷新或重新打开浏览器可能需要重新输入密码。
- 登录限速为每会话10分钟最多8次失败、每进程10分钟100次失败；免费托管重启会清空限速记录，不是企业级统一身份系统。
- 操作记录只保留在当前浏览会话，不是永久审计日志。
- 无人访问12小时后Community Cloud应用可能休眠，需打开网页唤醒；ESP向OneNet上报不受网页休眠影响。
- 手机访问此在线版不需要安装软件。原来USB串口网页继续在本地电脑运行，不能指望Cloud服务器直接读取电脑COM口。

## 待验证范围

本地自动化检查不替代iPhone真机测试；最终部署后需上电联网确认读数、下发、手机布局和手机编辑草稿保持情况。测试阶段不对真实设备执行写操作。

参考：[Cloud部署](https://docs.streamlit.io/deploy/streamlit-community-cloud/deploy-your-app/deploy)、[Secrets管理](https://docs.streamlit.io/deploy/streamlit-community-cloud/deploy-your-app/secrets-management)、[应用休眠](https://docs.streamlit.io/deploy/streamlit-community-cloud/manage-your-app)。

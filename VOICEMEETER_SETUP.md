# 桌宠语音输入 · VoiceMeeter 路由级分开（视频声不再进麦）

## 为什么需要它

桌宠语音模块用麦克风采集环境声。看视频时，视频扬声器声音也会被麦克风收到，
被当成"你说话"反复触发桌宠回复（自激/误触发）。

VoiceMeeter 是**驱动级虚拟混音器**：它在系统里新建一路"虚拟麦克风"，
只混入你的物理人声，**不含**系统播放的视频/音乐声。桌宠改成采集这路虚拟麦，
视频声从源头就不进麦——这是路由级隔离，比算法回声消除干净彻底。

> 你的机器现状（已知）：
> - 物理麦：`Realtek`（桌面端设备里通常是 idx 3）
> - 系统默认输入当前是虚拟麦（AudioRelay 之类）——装 VM 后设备列表会变，按下面步骤认名字即可。

## 第一步：安装 VoiceMeeter Banana（免费）

> **下载源选择（重要）**：VB-Audio 官网 `download.vb-audio.com` 在国内常被限速到几 KB/s；
> 中文镜像站 `voicemeeter.cn` 把下载链接挂了 **16.8 元付费墙**（中介过路费，非官方收费）。
> 以下都是**合法免费**的替代源，挑一个能正常速度的即可，**版本认准 2.1.2.2（DEC 2025）**：
>
> | 源 | 地址 | 校验 |
> |---|---|---|
> | **Uptodown**（推荐，独立 CDN） | https://voicemeeter.en.uptodown.com/windows/download | 与官方同包（页面会显示该版本 SHA256，以下完文件为准） |
> | **Filehippo** | https://filehippo.com/zh/download_voicemeeter-banana | 与官方同包 |
> | **Internet Archive 镜像**（voicemeeter.org 推荐） | 搜 `Voicemeeter Banana archive.org` | 与官方同包 |
> | **Winget**（命令行，仍走官方源可能慢） | `winget install VB-Audio.Voicemeeter.Banana` | — |
> | 官方源（可能慢） | `https://download.vb-audio.com/Download_CABLE/VoicemeeterSetup_v2122.zip` | — |
>
> **校验方法（下完确认是原版、没被改）**：
> ⚠️ VB-Audio 官网 CDN **不公布任何 SHA256/MD5 校验值**，网上流传的"官方哈希"多为不可信来源，**不要**拿陌生哈希当基准。
> 最可靠的做法是 **ZIP 完整性校验**：下载目录按住 Shift 右键 →「在此处打开终端」，用 Python 逐条目 CRC 校验：
> ```bat
> python -c "import zipfile; z=zipfile.ZipFile('VoicemeeterSetup_v2122.zip'); print('OK' if z.testzip() is None else 'CORRUPT'); print(z.namelist())"
> ```
> 输出 `OK` 且含 `voicemeeterprosetup.exe` 即原版完整；若 `CORRUPT` 或报 `BadZipFile`，说明下载被截断/损坏，**删掉重下**（不要用"满大小"判断完整）。
> 进阶：从**两个独立镜像**（如官方 + Uptodown）各下一份，用 `fc /b` 比对字节完全一致，即可确信未被篡改。
>
> ⚠️ **不要下"中文汉化版"**：那是用汉化文件替换官方二进制的修改版，音频引擎易崩溃且有夹带风险。
> 我们要的只是英文原版的路由功能，界面就那几个勾选点，文档下面都标了中文对照。

1. 从上述任一源下载 **VoiceMeeter Banana**（一个 zip 同时含基础版 + Banana，下哪个都行）。
2. 校验哈希无误后，右键 `Setup` → **以管理员身份运行**，一路下一步。
3. 装完**重启一次电脑**（虚拟音频驱动需重启生效）。

## 第二步：系统声音设置（关键）

1. 右键任务栏喇叭 →「声音设置」→「输出」→ 默认输出设备选
   **`VoiceMeeter AUX Input (VB-Audio VoiceMeeter AUX VAIO)`**。
   （这一步让视频/音乐/游戏声音都进 VoiceMeeter，而不是直接从物理扬声器出）
2. 「输入」先不管，下面在桌宠里选。

## 第三步：配置 VoiceMeeter 路由

打开 **VoiceMeeter Banana** 主界面：

- **HARDWARE INPUT 1 (IN1)**：点下拉选 `WDM: Realtek ...`（你的物理麦）。
- **VIRTUAL INPUTS（右边两条）**：
  - `VAIO 1`（B1，对应系统设备名 `VoiceMeeter Input`）—— 这是**给桌宠的纯净麦**。
  - `AUX 1`（B2，对应 `VoiceMeeter AUX Input`）—— 这是系统/视频声待的地方。
- 路由点亮（点对应按钮变黄）：
  - IN1（物理麦）的行里，点亮 **B1**（让它进入"给桌宠的虚拟麦"）。
  - IN1 的行里，也点亮 **A1**（主输出，让你自己能从耳机/音箱听到，可选）。
  - AUX 虚拟输入的行里，点亮 **A1**（让视频声从扬声器出来，你能听到）。
  - **AUX 行不要点亮 B1**（否则视频声会漏进桌宠麦——这是分开的关键）。

最终效果：
- 你说话 → IN1 → B1（纯净麦）
- 视频声 → AUX → A1（扬声器），**不进 B1**

## 第四步：桌宠选虚拟麦

1. 重启桌宠（右键托盘"奶昔"→退出→重开）。
2. 右键点击桌宠本体 →「语音输入设备」→ 选
   **`VoiceMeeter Input (VB-Audio VoiceMeeter VAIO)`**（或名字含 `VoiceMeeter` 且是 *Input* 的那条）。
3. 桌宠会提示"语音采集设备：VoiceMeeter Input ..."并自动重启监听。

> 之前那个"播放期间挂起麦克风"的回声抑制仍保留，作为双保险，无需关。

## 第五步：其他软件一次性适配（可选）

Discord / OBS / 直播姬等如果也要用你的麦，它们的"麦克风"设备也要改成
`VoiceMeeter Input`，否则它们会录到系统默认（可能是虚拟麦或空）。
这是一次性设置，不影响桌宠。

## 验证分开是否成功

1. 播放一段有人说话的视频。
2. 桌宠**不应**因为视频里的人声而弹出"你说：…"气泡。
3. 你自己对着物理麦说话，桌宠**应**正常接话。
4. 若仍误触发：确认第三步 AUX 行**没有**点亮 B1；确认第四步选的是 *Input* 不是 *Output*。

## 回退

右键桌宠 →「语音输入设备」→「自动（物理麦）」即可恢复原来的自动选麦行为，
不改变系统音频设置。

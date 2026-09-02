# 银狐对抗演示 · VMware 虚拟机防逃逸加固清单

在虚拟机里跑银狐样本做对抗演示，唯一可接受的心态是：**假设 VM 内已经 100% 失陷**。
银狐最新变种带 BYOVD（自带 vulnerable driver 加载 `wnBios` 内核 rootkit），进了 VM 就能读物理内存、
致盲 VM 内的一切杀软——**VM 内的防守没有任何意义**。所有安全性都必须建立在
「虚拟化层 + 网络 + 共享通道 + 生命周期」这四道外闸门上。

> 适用：VMware Workstation Pro/Player。VirtualBox / Hyper-V 思路相同，参数名不同。
> 本文档只讲**隔离与防护**，不涉及样本获取与攻击技术——样本请从你已有的合规渠道取得。

---

## 0. 四道闸门一览

| 闸门 | 目标 | 失效后果 |
| --- | --- | --- |
| ① 虚拟化层（.vmx） | 掐死 Guest→Host 的共享/拖放/剪贴板/后门通道 | 恶意代码借 HGFS、拖放、剪贴板跨到宿主机 |
| ② 网络 | 禁止桥接，Host-only 且宿主机侧全阻断 | 横向进内网（真机、NAS、路由器）或外联 C2 下载二阶段载荷 |
| ③ 宿主机共享面 | 关 SMB 管理共享 / 网络发现 / RDP / WinRM | 即使逃逸出 VM 也无处落脚、无法横向 |
| ④ 生命周期 | 干净快照 + 演示完立即回滚销毁 | 污染态长期留存，误操作带出文件 |

**纵深原则**：每道闸门都单独假设会失效，靠下一道兜底。

---

## 1. 虚拟化层加固（.vmx 配置）

### 1.1 前置：升级 VMware

VMware Workstation 历史上出过多个**真实逃逸 CVE**（如 CVE-2017-4901 拖放逃逸、CVE-2019-5544、
CVE-2022-229xx 系列、CVE-2023-208xx）。逃逸漏洞的存在意味着「软件层隔离」不是绝对可信的。

- 演示前把 VMware Workstation 升到**最新版**；
- 关闭 `Edit → Preferences` 里的**共享虚拟机**（Shared VMs）功能（它自带 HTTP/HTTPS 远程管理端口）；
- 不要用 VMware 的远程连接 / VNC 功能管理这台 VM。

### 1.2 VMware Tools 精简安装

Tools 是 Guest↔Host 通信的主通道，也是逃逸面的大头。安装时选**自定义**，取消：

- Shared Folders（HGFS）
- Drag and Drop
- Copy and Paste

只保留显示驱动、鼠标、心跳。Tools 之后**不要升级**回来这些组件。

### 1.3 写入 .vmx 加固项

**操作**：VM 完全关机（不是挂起）→ 用记事本打开 `<VM目录>\<VM名>.vmx` → 追加下面全部行 → 保存 → 开机。
（改 .vmx 必须在关机状态，运行中的改动会在关机时被 VMware 覆盖回去。）

```ini
# ── 一、掐死 Guest→Host 数据通道（核心）──
isolation.tools.copy.disable = "TRUE"                     # 禁止复制（VM→宿主机）
isolation.tools.paste.disable = "TRUE"                    # 禁止粘贴
isolation.tools.dragNDrop.disable = "TRUE"                # 禁止拖放（历史逃逸重灾区）
isolation.tools.hgfs.disable = "TRUE"                     # 禁止 HGFS 共享文件夹
isolation.tools.autoInstall.disable = "TRUE"              # 禁止自动安装 Tools 组件
isolation.tools.getCreds.disable = "TRUE"                 # 禁止向 Guest 索取凭据
isolation.tools.vmxDnDVersionGet.disable = "TRUE"         # 屏蔽 DnD 版本协商
isolation.tools.guestDnDVersionSet.disable = "TRUE"
isolation.tools.ghi.launchmenu.change = "FALSE"           # 禁止 Guest 改宿主机菜单
isolation.tools.memSchedFakeSample.stats.disable = "TRUE"

# ── 二、Unity 模式（融合窗口，攻击面大）──
isolation.tools.unity.disable = "TRUE"
isolation.tools.unityActive.disable = "TRUE"
isolation.tools.unityInterlockOperation.disable = "TRUE"
isolation.tools.unity.push.update.disable = "TRUE"
isolation.tools.unity.taskbar.disable = "TRUE"
isolation.tools.unity.windowContents.disable = "TRUE"
unity.enable = "FALSE"

# ── 三、共享文件夹兜底关闭 ──
sharedFolder.enable = "FALSE"
sharedFolder.maxNum = "0"
hgfs.linkRootShare = "FALSE"

# ── 四、设备直连通道 ──
isolation.device.connectable.disable = "TRUE"             # 禁止 Guest 请求连接设备
isolation.device.edit.disable = "TRUE"                    # 禁止 Guest 修改设备配置
usb.present = "FALSE"                                     # 移除 USB 控制器（防 BadUSB/外带）
usb.generic.autoconnect = "FALSE"
serial0.present = "FALSE"                                 # 关串口
parallel0.present = "FALSE"                               # 关并口
printer0.present = "FALSE"                                # 关共享打印机

# ── 五、远程显示 / VNC ──
RemoteDisplay.vnc.enabled = "FALSE"
RemoteDisplay.maxConnections = "0"

# ── 六、VMware backdoor I/O 端口（Guest↔Host 低层通道）──
# 说明：这是很多历史逃逸利用的入口。开启后 Tools 的部分高级功能（含拖放/共享，本就已禁）
# 会失效，但基础显示/鼠标不受影响。建议开启；若发现 VM 内异常再临时关掉排查。
monitor_control.restrict_backdoor = "TRUE"

# ── 七、不在宿主机留下内存/日志残留 ──
mainMem.useNamedFile = "FALSE"        # 不用宿主机文件做 VM 内存后备（避免内存残留在宿主机磁盘）
logging = "FALSE"                     # 关 VM 日志（演示期间防敏感信息落盘；排障时可临时打开）
```

**验证是否生效**：开机后在 VM 里试——拖文件进宿主机应失败、复制粘贴应不通、
`\\vmware-host\Shared Folders` 应不可访问。三者任一还通，说明改错了文件或 VM 没真正关机过。

---

## 2. 网络隔离

### 2.1 网卡模式三档（按演示需求选）

| 档位 | 配置 | 能看到什么 | 逃逸/外联风险 |
| --- | --- | --- | --- |
| A 完全断网 | 移除网络适配器 | 静态特征 + 本地行为（文件落地、注册表、驱动加载） | 最低，通道基本归零 |
| **B Host-only（推荐）** | VMnet1 + 宿主机侧全阻断 | A 的全部 + 可在 VM 内起**本地服务模拟 C2** 演示外连检测 | 低，无出网 |
| C 独立物理网络 | 单独路由器 / 手机热点 | 真实 C2 通信（能验证 C2 网段检测） | 中，需专用网络且不在其上放任何真机 |

**绝对禁止桥接模式**——VM 直接进物理局域网，与真机、NAS、路由器同段，逃逸后立刻可横向。

> 想在演示中展示「银狐 C2 外连检测」能力，用 **B 档 + VM 内自建假 C2** 即可：
> 在 VM 里起一个本地 HTTP/DNS 服务伪装成 C2 目标，让样本去连，奶昔照样能检出可疑外连行为。
> **不必、也不建议**为了演示去连真实恶意基础设施。

### 2.2 宿主机侧防火墙（关键，B 档必做）

以管理员 PowerShell 执行（网段按 `Get-NetIPAddress` 实际结果替换 `192.168.10.0/24`）：

```powershell
# 0) 先确认 VMnet 网卡的真实网段
Get-NetIPAddress -InterfaceAlias "VMware Network Adapter VMnet1" | Format-List IPAddress, PrefixLength

# 1) 把虚拟网卡标记为「公用网络」（自动套用最严格的防火墙配置集）
Get-NetConnectionProfile -InterfaceAlias "VMware Network Adapter VMnet1" |
  Set-NetConnectionProfile -NetworkCategory Public -ErrorAction SilentlyContinue

# 2) 阻断 VM → 宿主机 的全部入站（含 SMB 445、RPC 135、RDP 3389、WinRM 5985）
New-NetFirewallRule -DisplayName "BLOCK-VM-in-all" -Direction Inbound -Action Block `
  -RemoteAddress 192.168.10.0/24 -Profile Any -Enabled True

# 3) 阻断 宿主机 → VM 的全部出站（防止误传文件进去、也防宿主机被探测）
New-NetFirewallRule -DisplayName "BLOCK-VM-out-all" -Direction Outbound -Action Block `
  -RemoteAddress 192.168.10.0/24 -Profile Any -Enabled True
```

注：第 3 条会让宿主机无法 ping/访问 VM。需要临时传东西时先 `Disable-NetFirewallRule`，传完立刻 `Enable`。

**演示结束后清理**：

```powershell
Remove-NetFirewallRule -DisplayName "BLOCK-VM-in-all","BLOCK-VM-out-all" -ErrorAction SilentlyContinue
```

### 2.3 宿主机共享面收敛

银狐得手后最爱的落脚点就是 `C$`、`ADMIN$` 这类默认管理共享。演示前确认：

```powershell
# 查看当前共享（IPC$ 属正常，其余一律可疑）
Get-SmbShare | Select-Object Name, Path, Description

# 关闭网络发现与文件共享（公用/专用/域 全关）
Set-NetFirewallRule -DisplayGroup "Network Discovery"  -Enabled False
Set-NetFirewallRule -DisplayGroup "File and Printer Sharing" -Enabled False

# 彻底停掉 SMB Server 服务（需要共享时再开）
Set-Service -Name LanmanServer -StartupType Manual
Stop-Service -Name LanmanServer -Force

# RDP / WinRM 关掉（演示期间用不上，且是横向移动主通道）
Set-ItemProperty -Path "HKLM:\System\CurrentControlSet\Control\Terminal Server" -Name fDenyTSConnections -Value 1
Set-Service -Name WinRM -StartupType Disabled; Stop-Service -Name WinRM -Force
```

---

## 3. 数据外带通道封堵清单

演示前逐项打勾：

- [ ] 剪贴板共享：**已关**（.vmx `copy.disable` / `paste.disable`）
- [ ] 拖放：**已关**
- [ ] 共享文件夹（HGFS）：**已关**，`\\vmware-host` 不可达
- [ ] USB 控制器：**已移除**（防 BadUSB，也防通过 U 盘外带）
- [ ] 串口 / 并口 / 打印机：**已关**
- [ ] 无物理磁盘直通、无宿主机目录映射
- [ ] 网络：无桥接，出网已被切断或白名单化（防 DNS 隧道 / HTTP 外带）
- [ ] **VM 内不登录任何真实账号**，不放任何真实密码、密钥、token
- [ ] VM 内不装任何与工作相关的客户端（微信、邮箱、网盘同步）

---

## 4. 快照与生命周期（用完即毁）

1. **装样本前**建一个「干净基线」快照，命名如 `BASE-CLEAN`。
2. 导入样本、跑演示——所有污染都发生在 `BASE-CLEAN` 的下游。
3. 演示结束**立刻** `Revert to BASE-CLEAN`，**不要**继续在这台 VM 里做别的事。
4. 若要长期留证：把整个 VM 目录打包加密存放；分析时**离线挂载虚拟磁盘**，
   **绝不在宿主机上解压或运行任何来自 VM 的文件**。
5. 演示期间别让 VM 长时间挂在那儿，用完就关机。

---

## 5. 宿主机（真机）前置自检

演示开始前，先在真机上跑一遍——这几项正是奶昔「银狐应急哨兵」检测的东西，可互相印证：

```powershell
# ① Defender 实时防护是否开着、有没有被加整盘排除项（银狐最典型的致盲手法）
Get-MpComputerStatus | Select-Object RealTimeProtectionEnabled, AntivirusEnabled
Get-MpPreference | Select-Object -ExpandProperty ExclusionPath

# ② 可疑计划任务（Silver Fox 常用 DesignAccent / Accent / zpaq 之类命名）
Get-ScheduledTask | Where-Object { $_.TaskName -match 'DesignAccent|Accent|zpaq|Update' } |
  Select-Object TaskName, TaskPath, State

# ③ 异常外连（银狐 C2 曾落在 118.107.40.* 等网段）
Get-NetTCPConnection -State Established |
  Where-Object { $_.RemoteAddress -notmatch '^(127\.|192\.168\.|10\.|::1)' } |
  Select-Object LocalAddress, LocalPort, RemoteAddress, RemotePort, OwningProcess

# ④ 启动项
Get-CimInstance Win32_StartupCommand | Select-Object Name, Command, Location
```

任一项异常：**先处理真机，再谈演示**。

---

## 6. 演示后处置

1. VM 回滚到 `BASE-CLEAN`（或直接删除 VM）。
2. 真机上打开奶昔 → 设置 → 安全 → **银狐应急哨兵** 跑一遍（这本身就是一次真实验证）。
3. Windows Defender **离线扫描**（`设置 → 隐私和安全性 → Windows 安全中心 → 病毒和威胁防护 → 扫描选项 → Microsoft Defender 离线扫描`）——
   离线扫描能在系统未完全启动时查杀，对 rootkit 更靠谱。
4. 复核第 5 节的①②③④四项。
5. 若演示期间真机曾与 VM 有过任何数据往来（哪怕一次粘贴），按「已失陷」处理：
   改所有在演示期间用过的密码、检查所有登录过的账号。

---

## 7. 诚实边界（必须说清）

- **没有任何虚拟化隔离是 100% 的**。VMware 可能存在未公开（0day）逃逸漏洞，
  上面所有措施只是把已知面压到最小，不是数学证明。
- 真正想要「几乎零风险」，只有**独立物理机**（闲置电脑/笔记本，专跑样本，永不接入内网）。
  VMware 方案的安全上限低于物理隔离，这是客观事实，不是本文档能靠配置弥补的。
- **VM 内的杀软必被致盲**。银狐 BYOVD 加载内核 rootkit 后，VM 内的 Defender / 火绒 / 360 都不可信。
  演示的看点应该是：奶昔在**宿主视角/用户态**能发现多少痕迹（Defender 排除项被篡改、
  IOC 进程、可疑计划任务、C2 外连），而不是「能不能在 VM 里杀掉它」。
- 银狐的内核层 rootkit **任何用户态程序（含奶昔）都干不掉**——必须靠专业杀软 + 安全模式全盘查杀。
  奶昔的急救箱只处理**用户态可见痕迹**，UI 里已写明，不误导「能杀内核层」。
- 本应用**不内置任何反制 C2 的能力**。对 C2 发起 DoS / 未授权访问既违法也无效（C2 域名随时轮换）。

---

## 相关文档

- [RELEASE_SECURITY.md](RELEASE_SECURITY.md) — 发布侧防篡改（代码签名、哈希清单、官方渠道）
- 应用内：设置 → 安全 → 银狐应急哨兵 / 一键急救 / 安装包完整性

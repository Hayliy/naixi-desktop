<#
 .SYNOPSIS
  一键配置 VoiceMeeter Banana 路由：桌宠只听物理麦，视频/系统声不进桌宠麦。
  双击配套的「配置VoiceMeeter.bat」即可运行（自动以 32 位 PowerShell 执行）。
#>
# 32 位自举：VoicemeeterRemote.dll 是 32 位，必须从 32 位 PowerShell 加载
if ([Environment]::Is64BitProcess) {
    Write-Host "[*] 当前是 64 位 PowerShell，重启到 32 位以加载 32 位 VoicemeeterRemote.dll ..."
    & 'C:\Windows\SysWOW64\WindowsPowerShell\v1.0\powershell.exe' -NoProfile -ExecutionPolicy Bypass -File $MyInvocation.MyCommand.Path
    exit
}
$ErrorActionPreference = 'Stop'
$env:TEMP = 'C:\Windows\Temp'; $env:TMP = 'C:\Windows\Temp'

$DLL = 'C:\Program Files (x86)\VB\Voicemeeter\VoicemeeterRemote.dll'
if (-not (Test-Path $DLL)) {
    Write-Host "[X] 未找到 $DLL，请确认已安装 VoiceMeeter Banana"
    Read-Host "按回车退出"; exit 1
}

# ---- 编译封装：Voicemeeter Remote API + Core Audio 物理麦枚举 ----
$src = @'
using System;
using System.Runtime.InteropServices;
using System.Text;
using System.Collections.Generic;

public class VM {
    [DllImport(@"C:\Program Files (x86)\VB\Voicemeeter\VoicemeeterRemote.dll", EntryPoint="VBVMR_Login")] public static extern int Login();
    [DllImport(@"C:\Program Files (x86)\VB\Voicemeeter\VoicemeeterRemote.dll", EntryPoint="VBVMR_Logout")] public static extern int Logout();
    [DllImport(@"C:\Program Files (x86)\VB\Voicemeeter\VoicemeeterRemote.dll", EntryPoint="VBVMR_RunVoicemeeter")] public static extern int RunVoicemeeter(int mode);
    [DllImport(@"C:\Program Files (x86)\VB\Voicemeeter\VoicemeeterRemote.dll", EntryPoint="VBVMR_SetParameterStringA")] public static extern int SetParameterStringA(string p, string v);
    [DllImport(@"C:\Program Files (x86)\VB\Voicemeeter\VoicemeeterRemote.dll", EntryPoint="VBVMR_GetParameterStringA")] public static extern int GetParameterStringA(string p, StringBuilder v);
    [DllImport(@"C:\Program Files (x86)\VB\Voicemeeter\VoicemeeterRemote.dll", EntryPoint="VBVMR_IsParametersDirty")] public static extern int IsParametersDirty();
}

[ComImport, Guid("A95664D2-9614-4F35-A746-DE8DB63617E6"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
interface IMMDeviceEnumerator {
    void EnumAudioEndpoints(int dataFlow, int dwStateMask, out IMMDeviceCollection ppDevices);
    void GetDefaultAudioEndpoint(int dataFlow, int role, out IntPtr ppEndpoint);
    void GetDevice(string pwstrId, out IntPtr ppDevice);
    void RegisterEndpointNotificationCallback(IntPtr pClient);
    void UnregisterEndpointNotificationCallback(IntPtr pClient);
}
[ComImport, Guid("0BD7A1BE-7A1A-44DB-8397-CC5392387B5E"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
interface IMMDeviceCollection {
    void GetCount(out int pcDevices);
    void Item(int nDevice, out IntPtr ppDevice);
}
[ComImport, Guid("D666063F-1587-4E43-81F1-B948E807363F"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
interface IMMDevice {
    void Activate([MarshalAs(UnmanagedType.LPStruct)] Guid iid, int dwClsCtx, IntPtr pActivationParams, out IntPtr ppInterface);
    void OpenPropertyStore(int stgmAccess, out IntPtr ppProperties);
    void GetId(out string ppstrId);
    void GetState(out int pdwState);
}
[ComImport, Guid("886D8EEB-8AEC-4F5C-B479-5E94168BCAA0"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
interface IPropertyStore {
    void GetCount(out int cProps);
    void GetAt(int iProp, out IntPtr pkey);
    void GetValue(IntPtr pkey, out IntPtr pv);
    void SetValue(IntPtr pkey, IntPtr pv);
    void Commit();
}

[StructLayout(LayoutKind.Sequential)]
struct PROPERTYKEY { public Guid fmtid; public int pid; }

public class AudioDevices {
    public static List<string> EnumCaptureFriendlyNames() {
        var list = new List<string>();
        try {
            var enu = (IMMDeviceEnumerator)Activator.CreateInstance(
                Type.GetTypeFromCLSID(new Guid("BCDE0395-E52F-467C-8E3D-C4579291692E")));
            IMMDeviceCollection coll;
            enu.EnumAudioEndpoints(1, 1, out coll); // eCapture=1, DEVICE_STATE_ACTIVE=1
            int cnt; coll.GetCount(out cnt);
            var keyFmt = new Guid("A45C254E-DF1C-4EFD-8020-67D146A850E0"); // PKEY_Device_FriendlyName
            for (int i = 0; i < cnt; i++) {
                IntPtr pdev; coll.Item(i, out pdev);
                var dev = (IMMDevice)Marshal.GetObjectForIUnknown(pdev);
                IntPtr pps; dev.OpenPropertyStore(0, out pps); // STGM_READ
                var ps = (IPropertyStore)Marshal.GetObjectForIUnknown(pps);
                int n; ps.GetCount(out n);
                for (int j = 0; j < n; j++) {
                    IntPtr pk; ps.GetAt(j, out pk);
                    var key = (PROPERTYKEY)Marshal.PtrToStructure(pk, typeof(PROPERTYKEY));
                    if (key.fmtid == keyFmt && key.pid == 2) {
                        IntPtr pv; ps.GetValue(pk, out pv);
                        // PROPVARIANT: vt(short) + 6 padding + BSTR ptr(8)
                        IntPtr bstr = Marshal.ReadIntPtr(IntPtr.Add(pv, 8));
                        string name = Marshal.PtrToStringBSTR(bstr);
                        list.Add(name);
                    }
                }
            }
        } catch (Exception) { /* 枚举失败不影响主流程 */ }
        return list;
    }
}
'@
Add-Type -TypeDefinition $src -Language CSharp

# ---- 登录 / 必要时启动 Voicemeeter ----
$r = [VM]::Login()
if ($r -ne 0) {
    Write-Host "[*] VoiceMeeter 未运行，正在启动 ..."
    [VM]::RunVoicemeeter(0) | Out-Null
    Start-Sleep -Seconds 5
    $r = [VM]::Login()
}
if ($r -ne 0) {
    Write-Host "[X] 无法连接 VoiceMeeter (Login=$r)"
    Read-Host "按回车退出"; exit 1
}
Write-Host "[+] 已连接 VoiceMeeter"

# ---- 核心路由（确定性，必对） ----
# 物理麦 IN1 = Strip[0] -> B1(桌宠麦 VoiceMeeter Input)=1, A1(扬声器)=1
# AUX 虚拟输入 = Strip[4] -> A1(扬声器)=1, B1(桌宠麦)=0  => 视频/系统声不进桌宠麦
[VM]::SetParameterStringA('Strip[0].B1', '1.0') | Out-Null
[VM]::SetParameterStringA('Strip[0].A1', '1.0') | Out-Null
[VM]::SetParameterStringA('Strip[4].A1', '1.0') | Out-Null
[VM]::SetParameterStringA('Strip[4].B1', '0.0') | Out-Null
Write-Host "[+] 路由已设：物理麦 -> 桌宠麦(B1)；视频/系统声 -> 扬声器(A1) 且不进桌宠麦"

# ---- 物理麦自动选择（尽力而为，失败不影响主流程） ----
$sb = New-Object System.Text.StringBuilder 512
[VM]::GetParameterStringA('Strip[0].device.wdm', $sb) | Out-Null
$cur = $sb.ToString()
Write-Host "[*] 当前 IN1 设备: '$cur'"
if ($cur -match 'none' -or $cur -eq '') {
    try {
        $cands = [AudioDevices]::EnumCaptureFriendlyNames()
        if ($cands.Count -gt 0) {
            Write-Host "[*] 本机捕获设备候选:"
            $cands | ForEach-Object { Write-Host "    - $_" }
            $phys = $cands | Where-Object { $_ -notmatch 'VB-Audio|Voicemeeter|VoiceMeeter|Virtual' } |
                    Where-Object { $_ -match 'Realtek|Conexant|Microphone|麦克风|USB|Analog|Line' } |
                    Select-Object -First 1
            if (-not $phys) { $phys = $cands | Where-Object { $_ -notmatch 'VB-Audio|Voicemeeter|VoiceMeeter|Virtual' } | Select-Object -First 1 }
            if ($phys) {
                $vmName = "WDM: $phys"
                [VM]::SetParameterStringA('Strip[0].device.wdm', $vmName) | Out-Null
                # 回读验证
                $sb2 = New-Object System.Text.StringBuilder 512
                [VM]::GetParameterStringA('Strip[0].device.wdm', $sb2) | Out-Null
                if ($sb2.ToString() -eq $vmName) {
                    Write-Host "[+] 已自动将 IN1 设为物理麦: $vmName"
                } else {
                    Write-Host "[!] 自动设置未生效($($sb2.ToString()))，请在 VoiceMeeter 的 IN1 下拉手动选择麦克风"
                }
            } else {
                Write-Host "[!] 未识别到物理麦，请在 VoiceMeeter 的 IN1 下拉手动选择麦克风"
            }
        } else {
            Write-Host "[!] 未枚举到捕获设备，请在 VoiceMeeter 的 IN1 下拉手动选择麦克风"
        }
    } catch {
        Write-Host "[!] 物理麦自动识别异常，请在 VoiceMeeter 的 IN1 下拉手动选择麦克风"
    }
} else {
    Write-Host "[+] IN1 已配置($cur)，保持不变"
}

[VM]::Logout() | Out-Null
Write-Host ""
Write-Host "[完成] 配置已生效。接下来："
Write-Host "  1) 打开 VoiceMeeter Banana（开始菜单），确认 IN1 是你的麦、B1 已点亮"
Write-Host "  2) 右键托盘'奶昔'退出，再重开桌宠"
Write-Host "  3) 右键桌宠 -> 语音输入设备 -> 选 'VoiceMeeter Input (VB-Audio VoiceMeeter VAIO)'"
Read-Host "按回车退出"

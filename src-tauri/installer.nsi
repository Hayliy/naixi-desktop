Unicode true
ManifestDPIAware true
ManifestDPIAwareness PerMonitorV2

!if "{{compression}}" == "none"
  SetCompress off
!else
  ; 非 SOLID 压缩：每个文件独立压缩、按需解压，避免 SOLID 模式启动时
  ; 整体解压弹出独立的 "unpacking data" 对话框（该弹窗无法融入自定义安装界面）。
  SetCompressor "{{compression}}"
!endif

{{#if signed_plugins_path}}
!addplugindir "{{signed_plugins_path}}"
{{/if}}

!include LogicLib.nsh
!include nsDialogs.nsh
!include WinVer.nsh
!include FileFunc.nsh
!include x64.nsh
!include WordFunc.nsh
!include Sections.nsh
!include "utils.nsh"
!include "FileAssociation.nsh"
!include "Win\COM.nsh"
!include "Win\Propkey.nsh"
!include "StrFunc.nsh"
${StrCase}
${StrLoc}

; 窗口子类化插件（来源可靠，已下载至 src-tauri/nsis_plugins/），用于让 banner 可原生拖动
; 注意：必须用绝对路径。Tauri 打包时会把 installer.nsi 复制到 target/release/nsis/x64/ 再编译，
; 此时 ${__FILEDIR__} 指向临时目录，相对路径无法找到插件。
!addplugindir "D:\naixi_desktop\src-tauri\nsis_plugins\WndSubclass\Plugins\x86-unicode"
!addincludedir "D:\naixi_desktop\src-tauri\nsis_plugins\WndSubclass\Include"
!include "D:\naixi_desktop\src-tauri\nsis_plugins\WndSubclass\Include\WndSubclass.nsh"

; 默认简体中文（安装进度页等内置界面）
LoadLanguageFile "${NSISDIR}\Contrib\Language files\SimpChinese.nlf"

{{#if installer_hooks}}
!include "{{installer_hooks}}"
{{/if}}

; Tauri config vars
!define WEBVIEW2APPGUID "{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}"
!define MANUFACTURER "{{manufacturer}}"
!define PRODUCTNAME "{{product_name}}"
!define VERSION "{{version}}"
!define VERSIONWITHBUILD "{{version_with_build}}"
!define HOMEPAGE "{{homepage}}"
!define INSTALLMODE "{{install_mode}}"
!define LICENSE "{{license}}"
!define INSTALLERICON "{{installer_icon}}"
!define MAINBINARYNAME "{{main_binary_name}}"
!define MAINBINARYSRCPATH "{{main_binary_path}}"
!define BUNDLEID "{{bundle_id}}"
!define COPYRIGHT "{{copyright}}"
!define OUTFILE "{{out_file}}"
!define ARCH "{{arch}}"
!define ADDITIONALPLUGINSPATH "{{additional_plugins_path}}"
!define ALLOWDOWNGRADES "{{allow_downgrades}}"
!define INSTALLWEBVIEW2MODE "{{install_webview2_mode}}"
!define WEBVIEW2INSTALLERARGS "{{webview2_installer_args}}"
!define WEBVIEW2BOOTSTRAPPERPATH "{{webview2_bootstrapper_path}}"
!define WEBVIEW2INSTALLERPATH "{{webview2_installer_path}}"
!define MINIMUMWEBVIEW2VERSION "{{minimum_webview2_version}}"
!define UNINSTKEY "Software\Microsoft\Windows\CurrentVersion\Uninstall\${PRODUCTNAME}"
!define MANUKEY "Software\${MANUFACTURER}"
!define MANUPRODUCTKEY "${MANUKEY}\${PRODUCTNAME}"
!define UNINSTALLERSIGNCOMMAND "{{uninstaller_sign_cmd}}"
!define ESTIMATEDSIZE "{{estimated_size}}"
!define STARTMENUFOLDER "{{start_menu_folder}}"

; 每批写入/删除的资源文件数：过大→单 tick 磁盘 I/O 阻塞 UI（表现为窗口「卡住/假死」）；
; 过小→tick 次数与整表扫描次数增加，总耗时略升。
; 实测资源主体是 resources/python-embed（约 1.1 万个碎小文件，占 11060 条中的 10956 条），
; 瓶颈不是字节数而是「每文件创建+关闭 + Defender 逐文件实时扫描」的固定开销：
; 1000 个/批实测单 tick 可冻结 UI 数秒（超过 Windows 判定「未响应」的 5s 阈值），
; 与旧注释「1000 约 40MB/批、远低于 5s」的前提不符（那是按大文件估的）。
; 降到 100 后单 tick 只写 ~100 个碎文件，阻塞降到亚秒级；总 tick 数约 110，
; 每 tick 的 11060 项条件扫描开销（~十几 ms）可忽略。
; 必须定义在卸载函数之前（NSIS 预处理器按源顺序展开 !define），
; 否则卸载 stage 里宏为空 → IntOp 操作数为空 → 删除卡死在“正在删除资源文件”。
!define RES_BATCH_SIZE 100

; ── 配色（SetCtlColors 使用 RGB；GDI SendMessage 使用 BGR）──
!define CLR_PINK        0xD4537E
!define CLR_LIGHT_PINK  0xF4C0D1
!define CLR_DARK_PINK   0x72243E
!define CLR_FOOTER_BG   0xFDF8FA
!define CLR_BG          0xFFFFFF
!define CLR_TEXT_BODY   0x666666
!define CLR_TEXT_MUTED  0x888888
!define CLR_TEXT_STEP   0xAAAAAA
!define CLR_BORDER      0xD3C1D0
!define CLR_INPUT_BG    0xFDF8FA
!define CLR_INPUT_TEXT  0x444444
!define CLR_CLOSE       0x555555
!define CLR_SUCCESS     0x0033AA33  ; 组件完成态（绿）

!ifndef WM_NCLBUTTONDOWN
  !define WM_NCLBUTTONDOWN 0x00A1
!endif
!ifndef WM_LBUTTONDOWN
  !define WM_LBUTTONDOWN 0x0201
!endif
!ifndef HTCAPTION
  !define HTCAPTION 2
!endif
!ifndef WM_CLOSE
  !define WM_CLOSE 0x0010
!endif
!define SWP_NOMOVE     0x0002
!define SWP_NOSIZE     0x0001
!define SWP_NOZORDER   0x0004
!define SWP_NOACTIVATE 0x0010
!define SWP_FRAMECHANGED 0x0020

!ifndef EM_SETREADONLY
  !define EM_SETREADONLY 0x00CF
!endif

; 原生进度条消息常量（WinMessages.nsh 已定义则沿用，否则兜底）
!ifndef PBM_SETRANGE
  !define PBM_SETRANGE 0x0401
!endif
!ifndef PBM_SETPOS
  !define PBM_SETPOS 0x0402
!endif
!ifndef PBM_SETBARCOLOR
  !define PBM_SETBARCOLOR 0x0409
!endif
!ifndef PBM_SETBKCOLOR
  !define PBM_SETBKCOLOR 0x040D
!endif

; 明细列表（LISTBOX）消息常量
!ifndef LB_ADDSTRING
  !define LB_ADDSTRING 0x0180
!endif
!ifndef LB_SETTOPINDEX
  !define LB_SETTOPINDEX 0x0197
!endif

; ── 窗口尺寸（与 mockup.html 一致）──
!define WIN_W   540
!define WIN_H   430
!define BANNER_H 150
!define FOOTER_H 62
!define FOOTER_TOP 368
!define CONTENT_TOP 168

; Variables
Var Dialog
Var InstallPathText
Var DesktopCheck
Var RunCheck
Var hBanner
Var hBmpHandle
Var BannerProc
Var PassiveMode
Var UpdateMode
Var NoShortcutMode
Var hFontTitle
Var hFontBody
Var hFontSmall
Var hFontTiny
Var hFontBtn
Var hProgressStatus
Var hDetails
Var hProgressBar
Var hProgressFill
Var hNextBtn
Var hPrevBtn
Var hNextBmp
Var hPrevBmp
Var hMinBmp
Var hMinBtn
Var hCloseBmp
Var hCloseBtn
Var InstallStage
Var InstallDone
Var ResBatch
Var ResIdx
Var BatchStart
Var BatchEnd
Var BatchTmp
Var CurPage
Var unCurPage
Var unInstallDone
Var unInstallStage
Var unDeleteData
Var unDeleteChk
Var unProgStatus
Var hStepTxt1
Var hStepTxt2
Var hStepTxt3
Var hFooterBg
Var unProg

; 安装组件明细（两栏：左栏组件列表 + 右栏当前详情）
Var hCompTitle
Var hC1
Var hC2
Var hC3
Var hC4
Var hC5
Var hC6
Var hC7
Var hC8
Var hCurName
Var hCurPct
Var hCurDetail
Var BatchTmp2
Var CurPart
Var PartTotal

Name "奶昔 · 桌面智能体"
BrandingText " "
OutFile "${OUTFILE}"
Icon "D:\naixi_desktop\src-tauri\icons\icon.ico"
; 卸载器图标必须用 BMP(DIB) 格式 ICO：NSIS 在 WriteUninstaller 时替换卸载器桩图标资源，
; 对 PNG 压缩内嵌的 ICO 兼容性差会静默失败回退默认图标。uninstall.ico 由 make_uninstall_ico.py 生成。
UninstallIcon "D:\naixi_desktop\src-tauri\icons\uninstall.ico"
!define PLACEHOLDER_INSTALL_DIR "placeholder\${PRODUCTNAME}"
InstallDir "${PLACEHOLDER_INSTALL_DIR}"

VIProductVersion "${VERSIONWITHBUILD}"
VIAddVersionKey "ProductName" "${PRODUCTNAME}"
VIAddVersionKey "FileDescription" "${PRODUCTNAME}"
VIAddVersionKey "LegalCopyright" "${COPYRIGHT}"
VIAddVersionKey "FileVersion" "${VERSION}"
VIAddVersionKey "ProductVersion" "${VERSION}"

!addplugindir "${ADDITIONALPLUGINSPATH}"

!if "${UNINSTALLERSIGNCOMMAND}" != ""
  !uninstfinalize '${UNINSTALLERSIGNCOMMAND}'
!endif

!if "${INSTALLMODE}" == "perMachine"
  RequestExecutionLevel admin
!endif
!if "${INSTALLMODE}" == "currentUser"
  RequestExecutionLevel user
!endif
!if "${INSTALLMODE}" == "both"
  !define MULTIUSER_MUI
  !define MULTIUSER_INSTALLMODE_INSTDIR "${PRODUCTNAME}"
  !define MULTIUSER_INSTALLMODE_COMMANDLINE
  !if "${ARCH}" == "x64"
    !define MULTIUSER_USE_PROGRAMFILES64
  !else if "${ARCH}" == "arm64"
    !define MULTIUSER_USE_PROGRAMFILES64
  !endif
  !define MULTIUSER_INSTALLMODE_DEFAULT_REGISTRY_KEY "${UNINSTKEY}"
  !define MULTIUSER_INSTALLMODE_DEFAULT_REGISTRY_VALUENAME "CurrentUser"
  !define MULTIUSER_INSTALLMODEPAGE_SHOWUSERNAME
  !define MULTIUSER_INSTALLMODE_FUNCTION RestorePreviousInstallLocation
  !define MULTIUSER_EXECUTIONLEVEL Highest
  !include MultiUser.nsh
!endif

; ── 无边框样式 + 圆角（绝对不动窗口坐标）──
; 页面切换时只重新套用样式与圆角。此前页面函数直接调 MakeBorderless（内含按屏幕中心
; SetWindowPos），导致用户把窗口拖到别处后一翻页就被拉回屏幕正中。故此处剥离定位职责。
!macro ApplyBorderless
  System::Call "user32::SetWindowLong(i $HWNDPARENT, i ${GWL_STYLE}, i 0x92000000)"
  System::Call "user32::SetWindowLong(i $HWNDPARENT, i ${GWL_EXSTYLE}, i 0)"
  System::Call "gdi32::CreateRoundRectRgn(i 0, i 0, i ${WIN_W}, i ${WIN_H}, i 12, i 12) i .r0"
  System::Call "user32::SetWindowRgn(i $HWNDPARENT, i r0, i 1)"
!macroend

; ── 无边框 + 首次居中 ──
; 仅在 .onGUIInit 调用一次：此时窗口还没被用户拖过，居中与需求一致。
; 各页面函数一律改用 ApplyBorderless，避免翻页重置位置。
!macro MakeBorderless
  !insertmacro ApplyBorderless
  System::Call "user32::GetSystemMetrics(i 0) i .r0"
  System::Call "user32::GetSystemMetrics(i 1) i .r1"
  IntOp $2 $0 - ${WIN_W}
  IntOp $2 $2 / 2
  IntOp $3 $1 - ${WIN_H}
  IntOp $3 $3 / 2
  System::Call "user32::SetWindowPos(i $HWNDPARENT, i 0, i r2, i r3, i ${WIN_W}, i ${WIN_H}, i 0x34)"
!macroend

; ── 把 nsDialogs 内容对话框放大铺满整个无边框窗口 ──
!macro FillPage
  System::Call "user32::SetWindowPos(i $Dialog, i 0, i 0, i 0, i ${WIN_W}, i ${WIN_H}, i 0x14)"
!macroend

; ── Hide NSIS default wizard buttons & branding ──
!macro HideWizardChrome
  GetDlgItem $0 $HWNDPARENT 1
  ShowWindow $0 0
  GetDlgItem $0 $HWNDPARENT 2
  ShowWindow $0 0
  GetDlgItem $0 $HWNDPARENT 3
  ShowWindow $0 0
  GetDlgItem $0 $HWNDPARENT 1028
  ${If} $0 != 0
    ShowWindow $0 0
  ${EndIf}
  GetDlgItem $0 $HWNDPARENT 1038
  ${If} $0 != 0
    ShowWindow $0 0
  ${EndIf}
  GetDlgItem $0 $HWNDPARENT 1256
  ${If} $0 != 0
    ShowWindow $0 0
  ${EndIf}
!macroend

; ── 字体应用 ──
!macro ApplyFont HWND FONT
  SendMessage ${HWND} ${WM_SETFONT} ${FONT} 1
!macroend

; ── Label 文字水平居中 ──
!macro CenterLabel HWND
  Push $1
  System::Call "user32::GetWindowLong(i ${HWND}, i ${GWL_STYLE}) i .r1"
  IntOp $1 $1 | 0x00000201
  System::Call "user32::SetWindowLong(i ${HWND}, i ${GWL_STYLE}, i r1)"
  System::Call "user32::SetWindowPos(i ${HWND}, i 0, i 0, i 0, i 0, i 0, i 0x0027)"
  Pop $1
!macroend

; ── 用自定义按钮模拟点击被隐藏的默认“下一步”按钮（ID 1），实现翻页 ──
!macro AdvanceNext
  GetDlgItem $0 $HWNDPARENT 1
  SendMessage $HWNDPARENT ${WM_COMMAND} 1 $0
!macroend

; ── 返回上一步（ID 3）──
!macro AdvanceBack
  GetDlgItem $0 $HWNDPARENT 3
  SendMessage $HWNDPARENT ${WM_COMMAND} 3 $0
!macroend

; ── 扁平输入框（去除下沉边框）───
!macro FlatEdit HWND
  Push $1
  System::Call "user32::GetWindowLong(i ${HWND}, i ${GWL_STYLE}) i .r1"
  IntOp $1 $1 & 0xFF7FFFFF
  System::Call "user32::SetWindowLong(i ${HWND}, i ${GWL_STYLE}, i r1)"
  System::Call "user32::GetWindowLong(i ${HWND}, i ${GWL_EXSTYLE}) i .r1"
  IntOp $1 $1 & 0xFFFFFDFF
  System::Call "user32::SetWindowLong(i ${HWND}, i ${GWL_EXSTYLE}, i r1)"
  System::Call "user32::SetWindowPos(i ${HWND}, i 0, i 0, i 0, i 0, i 0, i 0x0027)"
  Pop $1
!macroend

; ── 给 Static 控件加 SS_NOTIFY，确保点击触发 NSD_OnClick ──
!macro AddNotify HWND
  Push $1
  System::Call "user32::GetWindowLong(i ${HWND}, i ${GWL_STYLE}) i .r1"
  IntOp $1 $1 | 0x00000100
  System::Call "user32::SetWindowLong(i ${HWND}, i ${GWL_STYLE}, i r1)"
  System::Call "user32::SetWindowPos(i ${HWND}, i 0, i 0, i 0, i 0, i 0, i 0x0027)"
  Pop $1
!macroend

; ── 位图按钮：位图控件直接显示 + 直接接收点击（nsDialogs 子类化捕获鼠标，需真实鼠标事件）──
!macro BitmapBtn X Y W H BMP HANDLER OUTVAR_BMP OUTVAR_CLICK
  ${NSD_CreateBitmap} ${X} ${Y} ${W} ${H} ""
  Pop ${OUTVAR_BMP}
  ${NSD_SetBitmap} ${OUTVAR_BMP} "${BMP}" $R0
  !insertmacro AddNotify ${OUTVAR_BMP}
  ${NSD_OnClick} ${OUTVAR_BMP} ${HANDLER}
  System::Call "user32::SetWindowPos(i ${OUTVAR_BMP}, i 0, i 0, i 0, i 0, i 0, i 0x0003)"
  StrCpy ${OUTVAR_CLICK} ${OUTVAR_BMP}
!macroend

; ── 透明点击区：用于 banner 右上角已绘制好的最小化/关闭按钮（真正透明，不擦除背景）──
!macro ClickArea X Y W H HANDLER OUTVAR
  ${NSD_CreateLabel} ${X} ${Y} ${W} ${H} ""
  Pop ${OUTVAR}
  SetCtlColors ${OUTVAR} "${CLR_BG}" ""
  !insertmacro AddNotify ${OUTVAR}
  ${NSD_OnClick} ${OUTVAR} ${HANDLER}
  System::Call "user32::GetWindowLong(i ${OUTVAR}, i ${GWL_EXSTYLE}) i .r0"
  IntOp $0 $0 | 0x00000020  ; WS_EX_TRANSPARENT
  System::Call "user32::SetWindowLong(i ${OUTVAR}, i ${GWL_EXSTYLE}, i r0)"
  System::Call "user32::SetWindowPos(i ${OUTVAR}, i 0, i 0, i 0, i 0, i 0, i 0x0043)"
!macroend

; ── 粉色主按钮（Label 模拟）───
!macro PrimaryBtn X Y W H TEXT HANDLER OUTVAR
  ${NSD_CreateLabel} ${X} ${Y} ${W} ${H} "${TEXT}"
  Pop ${OUTVAR}
  SetCtlColors ${OUTVAR} "${CLR_BG}" "${CLR_PINK}"
  !insertmacro ApplyFont ${OUTVAR} $hFontBtn
  !insertmacro CenterLabel ${OUTVAR}
  ${NSD_OnClick} ${OUTVAR} ${HANDLER}
!macroend

; ── 浅粉色次要按钮（Label 模拟）───
!macro SecondaryBtn X Y W H TEXT HANDLER OUTVAR
  ${NSD_CreateLabel} ${X} ${Y} ${W} ${H} "${TEXT}"
  Pop ${OUTVAR}
  SetCtlColors ${OUTVAR} "${CLR_DARK_PINK}" "${CLR_LIGHT_PINK}"
  !insertmacro ApplyFont ${OUTVAR} $hFontBtn
  !insertmacro CenterLabel ${OUTVAR}
  ${NSD_OnClick} ${OUTVAR} ${HANDLER}
!macroend

; ── 顶部 banner（纯图，标题在内容区显示）──
!macro ShowBanner MIN_HANDLER CLOSE_HANDLER
  ${NSD_CreateBitmap} 0 0 ${WIN_W} ${BANNER_H} ""
  Pop $hBanner
  ${NSD_SetBitmap} $hBanner "$PLUGINSDIR\banner.bmp" $hBmpHandle
  !insertmacro AddNotify $hBanner

  ; 子类化 banner：捕获 WM_LBUTTONDOWN，向父对话框发送 WM_NCLBUTTONDOWN+HTCAPTION，
  ; 由系统以"真实标题栏"机制接管拖动（按下即开始、抬起即结束），根治"拖动后重入 p3"。
  ; 用 WndSubclass 插件（已下载至 nsis_plugins/），不干扰 min/close 按钮。
  ${WndSubclass_Subclass} $hBanner BannerDragProc $BannerProc $BannerProc

  ; 右上角 最小化/关闭 作为独立位图按钮叠加在 banner 上（位图+NSD_OnClick 已验证可用）
  !insertmacro BitmapBtn 478 6 28 24 "$PLUGINSDIR\btn_min.bmp" ${MIN_HANDLER} $hMinBmp $hMinBtn
  !insertmacro BitmapBtn 506 6 28 24 "$PLUGINSDIR\btn_close.bmp" ${CLOSE_HANDLER} $hCloseBmp $hCloseBtn
!macroend

; ── 卸载专属 banner（卸载页用 banner_uninstall.bmp）──
!macro ShowBannerU MIN_HANDLER CLOSE_HANDLER
  ${NSD_CreateBitmap} 0 0 ${WIN_W} ${BANNER_H} ""
  Pop $hBanner
  ${NSD_SetBitmap} $hBanner "$PLUGINSDIR\banner_uninstall.bmp" $hBmpHandle
  !insertmacro AddNotify $hBanner

  ; 子类化 banner：同 ShowBanner，卸载页 banner 也可原生拖动（根治重入）
  ${WndSubclass_Subclass} $hBanner un.BannerDragProc $BannerProc $BannerProc
  !insertmacro BitmapBtn 478 6 28 24 "$PLUGINSDIR\btn_min.bmp" ${MIN_HANDLER} $hMinBmp $hMinBtn
  !insertmacro BitmapBtn 506 6 28 24 "$PLUGINSDIR\btn_close.bmp" ${CLOSE_HANDLER} $hCloseBmp $hCloseBtn
!macroend

!macro CreateStep IDX ACTIVE X LABEL
  ; 数字圆点（18x18，激活粉底白字 / 未激活浅粉底白字），匹配 mockup .step .num
  ${NSD_CreateBitmap} ${X} 389 18 18 ""
  Pop $8
  ${If} ${ACTIVE} >= ${IDX}
    ${NSD_SetBitmap} $8 "$PLUGINSDIR\num${IDX}_on.bmp" $9
  ${Else}
    ${NSD_SetBitmap} $8 "$PLUGINSDIR\num${IDX}_off.bmp" $9
  ${EndIf}
  System::Call "user32::SetWindowPos(i $8, i 0, i 0, i 0, i 0, i 0, i 0x0003)"

  IntOp $9 ${X} + 24
  ${NSD_CreateLabel} $9 390 44 18 "${LABEL}"
  Pop $8
  ${If} ${ACTIVE} >= ${IDX}
    SetCtlColors $8 "${CLR_PINK}" "${CLR_FOOTER_BG}"
  ${Else}
    SetCtlColors $8 "${CLR_TEXT_STEP}" "${CLR_FOOTER_BG}"
  ${EndIf}
  !insertmacro ApplyFont $8 $hFontSmall
!macroend

; ACTIVE: 当前步骤（1-4）；NEXT_TEXT: 右侧主按钮文字；
; SHOW_PREV: 是否显示上一步；NEXT_ENABLED: 是否启用主按钮
; ACTIVE: 当前步骤（1-4）；NEXT_BMP: 右侧主按钮位图；SHOW_PREV: 是否显示上一步；NEXT_ENABLED: 是否启用主按钮
!macro CreateFooter ACTIVE NEXT_BMP SHOW_PREV NEXT_ENABLED PREV_HANDLER NEXT_HANDLER
  ; footer 背景
  ${NSD_CreateLabel} 0 ${FOOTER_TOP} ${WIN_W} ${FOOTER_H} ""
  Pop $0
  SetCtlColors $0 "${CLR_FOOTER_BG}" "${CLR_FOOTER_BG}"

  ; 顶部分隔线（1px 浅粉）
  ${NSD_CreateLabel} 0 ${FOOTER_TOP} ${WIN_W} 1 ""
  Pop $0
  SetCtlColors $0 "${CLR_LIGHT_PINK}" "${CLR_LIGHT_PINK}"

  ; 步骤指示器（数字圆点 1-4）
  !insertmacro CreateStep 1 ${ACTIVE} 30  "欢迎"
  !insertmacro CreateStep 2 ${ACTIVE} 100 "位置"
  !insertmacro CreateStep 3 ${ACTIVE} 170 "安装"
  !insertmacro CreateStep 4 ${ACTIVE} 240 "完成"

  ; 导航按钮（底层位图 + 顶层透明点击区）
  !insertmacro BitmapBtn 320 384 90 30 "$PLUGINSDIR\btn_prev.bmp" ${PREV_HANDLER} $hPrevBmp $hPrevBtn
  ${If} ${SHOW_PREV} == 0
    ShowWindow $hPrevBtn 0
    ShowWindow $hPrevBmp 0
  ${EndIf}

  !insertmacro BitmapBtn 414 384 90 30 "${NEXT_BMP}" ${NEXT_HANDLER} $hNextBmp $hNextBtn
  ${If} ${NEXT_ENABLED} == 0
    EnableWindow $hNextBtn 0
  ${EndIf}
!macroend

; ── 卸载步骤指示器（3 步：确认/卸载/完成），左对齐位图，与 test_flow 同构 ──
!macro CreateStepU IDX ACTIVE X
  ${NSD_CreateBitmap} ${X} 389 18 18 ""
  Pop $8
  ${If} ${ACTIVE} >= ${IDX}
    ${NSD_SetBitmap} $8 "$PLUGINSDIR\num${IDX}_on.bmp" $9
  ${Else}
    ${NSD_SetBitmap} $8 "$PLUGINSDIR\num${IDX}_off.bmp" $9
  ${EndIf}
  System::Call "user32::SetWindowPos(i $8, i 0, i 0, i 0, i 0, i 0, i 0x0003)"

  IntOp $9 ${X} + 24
  ${NSD_CreateBitmap} $9 390 44 18 ""
  Pop $8
  ${If} ${ACTIVE} >= ${IDX}
    ${NSD_SetBitmap} $8 "$PLUGINSDIR\txt_step_u${IDX}_on.bmp" $R0
  ${Else}
    ${NSD_SetBitmap} $8 "$PLUGINSDIR\txt_step_u${IDX}_off.bmp" $R0
  ${EndIf}
  System::Call "user32::SetWindowPos(i $8, i 0, i 0, i 0, i 0, i 0, i 0x0003)"
  ${If} ${IDX} == 1
    StrCpy $hStepTxt1 $8
  ${ElseIf} ${IDX} == 2
    StrCpy $hStepTxt2 $8
  ${Else}
    StrCpy $hStepTxt3 $8
  ${EndIf}
!macroend

; ── 卸载底部导航（3 步 + 主按钮），与 test_flow 同构 ──
!macro CreateFooterU ACTIVE NEXT_BMP SHOW_PREV NEXT_ENABLED PREV_HANDLER NEXT_HANDLER
  ${NSD_CreateLabel} 0 ${FOOTER_TOP} ${WIN_W} ${FOOTER_H} ""
  Pop $0
  SetCtlColors $0 "${CLR_FOOTER_BG}" "${CLR_FOOTER_BG}"
  StrCpy $hFooterBg $0

  ${NSD_CreateLabel} 0 ${FOOTER_TOP} ${WIN_W} 1 ""
  Pop $0
  SetCtlColors $0 "${CLR_LIGHT_PINK}" "${CLR_LIGHT_PINK}"

  !insertmacro CreateStepU 1 ${ACTIVE} 30
  !insertmacro CreateStepU 2 ${ACTIVE} 100
  !insertmacro CreateStepU 3 ${ACTIVE} 170

  !insertmacro BitmapBtn 320 384 90 30 "$PLUGINSDIR\btn_prev.bmp" ${PREV_HANDLER} $hPrevBmp $hPrevBtn
  ${If} ${SHOW_PREV} == 0
    ShowWindow $hPrevBtn 0
    ShowWindow $hPrevBmp 0
  ${EndIf}

  !insertmacro BitmapBtn 414 384 90 30 "${NEXT_BMP}" ${NEXT_HANDLER} $hNextBmp $hNextBtn
  ${If} ${NEXT_ENABLED} == 0
    EnableWindow $hNextBtn 0
  ${EndIf}
!macroend

; ─── 安装组件状态宏（两栏明细用）───
; MODE: 1=进行中(粉●) 2=完成(绿✓)
!macro SetComp IDX MODE NAME
  ${If} ${MODE} == 1
    SetCtlColors $hC${IDX} "${CLR_PINK}" "${CLR_BG}"
    ${NSD_SetText} $hC${IDX} "● ${NAME}"
  ${ElseIf} ${MODE} == 2
    SetCtlColors $hC${IDX} "${CLR_SUCCESS}" "${CLR_BG}"
    ${NSD_SetText} $hC${IDX} "✓ ${NAME}"
  ${EndIf}
!macroend

; ─── 进入 GUI 即把默认窗口改为无边框自定义窗口 ───
Function .onGUIInit
  !insertmacro MakeBorderless
FunctionEnd

Function fn_Close
  SendMessage $HWNDPARENT ${WM_CLOSE} 0 0
FunctionEnd

Function fn_Minimize
  ShowWindow $HWNDPARENT 6
FunctionEnd

; banner 拖动回调：鼠标在 banner 上按下时，向父对话框发送"非客户区左键按下+标题栏"，
; 系统按真实标题栏逻辑启动拖动循环（按下即动、抬起即停），彻底规避重入。
Function BannerDragProc
  ${If} $2 = ${WM_LBUTTONDOWN}
    SendMessage $HWNDPARENT ${WM_NCLBUTTONDOWN} ${HTCAPTION} 0
  ${EndIf}
FunctionEnd

; 卸载版拖动回调（卸载段函数必须带 un. 前缀）
Function un.BannerDragProc
  ${If} $2 = ${WM_LBUTTONDOWN}
    SendMessage $HWNDPARENT ${WM_NCLBUTTONDOWN} ${HTCAPTION} 0
  ${EndIf}
FunctionEnd

Function fn_NextClick
  ${If} $CurPage == 4
    Call fn_Done
  ${Else}
    !insertmacro AdvanceNext
  ${EndIf}
FunctionEnd

Function fn_PrevClick
  !insertmacro AdvanceBack
FunctionEnd

; ─── Page 1: Welcome ───
Page custom fn_Welcome

Function fn_Welcome
  nsDialogs::Create 1018
  Pop $Dialog
  StrCpy $CurPage 1
  !insertmacro ApplyBorderless
  !insertmacro FillPage
  !insertmacro HideWizardChrome
  SetCtlColors $Dialog "" "${CLR_BG}"

  !insertmacro ShowBanner fn_Minimize fn_Close

  ${NSD_CreateLabel} 30 ${CONTENT_TOP} 480 28 "欢迎安装奶昔 · 桌面智能体"
  Pop $0
  SetCtlColors $0 "${CLR_DARK_PINK}" "${CLR_BG}"
  !insertmacro ApplyFont $0 $hFontTitle

  ${NSD_CreateLabel} 30 210 480 20 "嗨，我是奶昔。你的桌面 AI 智能体工作站。"
  Pop $0
  SetCtlColors $0 "${CLR_TEXT_BODY}" "${CLR_BG}"
  !insertmacro ApplyFont $0 $hFontBody

  ${NSD_CreateLabel} 30 236 480 60 "集 AI 对话、工作流编排、任务自动化、知识库管理与虚拟主播于一体。安装后，你可以从桌面随时唤出我，把重复的事交给我打理。"
  Pop $0
  SetCtlColors $0 "${CLR_TEXT_BODY}" "${CLR_BG}"
  !insertmacro ApplyFont $0 $hFontBody

  !insertmacro CreateFooter 1 "$PLUGINSDIR\btn_next.bmp" 0 1 fn_PrevClick fn_NextClick

  ${NSD_FreeBitmap} $hBanner
  nsDialogs::Show
FunctionEnd

; ─── Page 2: Directory ───
Page custom fn_DirPage fn_DirPageLeave

Function fn_DirPage
  nsDialogs::Create 1018
  Pop $Dialog
  StrCpy $CurPage 2
  !insertmacro ApplyBorderless
  !insertmacro FillPage
  !insertmacro HideWizardChrome
  SetCtlColors $Dialog "" "${CLR_BG}"

  !insertmacro ShowBanner fn_Minimize fn_Close

  ${NSD_CreateLabel} 30 ${CONTENT_TOP} 480 28 "选择安装位置"
  Pop $0
  SetCtlColors $0 "${CLR_DARK_PINK}" "${CLR_BG}"
  !insertmacro ApplyFont $0 $hFontTitle

  ; 地址输入框：圆角边框位图（1px #D3C1D0 + 圆角 5px + 内部 #FDF8FA），匹配 mockup .path-row input
  ${NSD_CreateBitmap} 29 209 382 32 ""
  Pop $0
  ${NSD_SetBitmap} $0 "$PLUGINSDIR\addr_border.bmp" $R0

  ; 路径输入框：用原生 Text 控件（匹配 mockup .path-row input），预填默认安装路径，渲染稳定且可编辑
  ${NSD_CreateText} 40 215 360 22 "$INSTDIR"
  Pop $InstallPathText
  SetCtlColors $InstallPathText "${CLR_INPUT_TEXT}" "${CLR_INPUT_BG}"
  !insertmacro ApplyFont $InstallPathText $hFontSmall
  ; 去掉原生凹陷/实线边框，改用底层 addr_border.bmp 圆角边框作装饰，避免双重边框
  !insertmacro FlatEdit $InstallPathText
  ; 提到顶层，确保不被 addr_border.bmp 边框位图按创建序覆盖
  System::Call "user32::SetWindowPos(i $InstallPathText, i 0, i 0, i 0, i 0, i 0, i 0x0003)"

  ; 浏览按钮（次级：浅粉底深粉字，90x28）
  !insertmacro BitmapBtn 420 210 90 28 "$PLUGINSDIR\btn_browse.bmp" fn_Browse $R8 $R9

  ${NSD_CreateLabel} 30 252 480 18 ""
  Pop $0
  SetCtlColors $0 "${CLR_TEXT_MUTED}" "${CLR_BG}"
  !insertmacro ApplyFont $0 $hFontTiny
  ; ${ESTIMATEDSIZE} 是 Windows 标准 KB 单位，转成 MB 显示
  IntOp $R0 ${ESTIMATEDSIZE} / 1024
  System::Call "user32::SetWindowText(i $0, t '所需磁盘空间：约 $R0 MB')"

  !insertmacro CreateFooter 2 "$PLUGINSDIR\btn_install.bmp" 1 1 fn_PrevClick fn_NextClick

  ${NSD_FreeBitmap} $hBanner
  nsDialogs::Show
FunctionEnd

Function fn_Browse
  ${NSD_GetText} $InstallPathText $0
  nsDialogs::SelectFolderDialog "选择安装文件夹" "$0"
  Pop $0
  ${If} $0 != error
    SendMessage $InstallPathText ${WM_SETTEXT} 0 "STR:$0"
    StrCpy $INSTDIR $0
  ${EndIf}
FunctionEnd

Function fn_DirPageLeave
  ${NSD_GetText} $InstallPathText $0
  StrCpy $INSTDIR $0
FunctionEnd

; ─── Page 3: Progress ───
Page custom fn_ProgressPage fn_ProgressPageLeave

Function fn_ProgressPage
  nsDialogs::Create 1018
  Pop $Dialog
  StrCpy $CurPage 3
  !insertmacro ApplyBorderless
  !insertmacro FillPage
  !insertmacro HideWizardChrome
  SetCtlColors $Dialog "" "${CLR_BG}"

  !insertmacro ShowBanner fn_Minimize fn_Close

  ${NSD_CreateLabel} 30 ${CONTENT_TOP} 480 28 "正在安装"
  Pop $0
  SetCtlColors $0 "${CLR_DARK_PINK}" "${CLR_BG}"
  !insertmacro ApplyFont $0 $hFontTitle

  ${NSD_CreateLabel} 30 210 480 20 "稍等一下，正在把奶昔搬到你电脑上..."
  Pop $0
  SetCtlColors $0 "${CLR_TEXT_BODY}" "${CLR_BG}"
  !insertmacro ApplyFont $0 $hFontBody

  ; 进度条：原生 msctls_progress32（与卸载 P2 / test_flow P3 同机制）
  ; 修复此前用 Label + SetWindowPos 模拟导致的“看不到进度/无样式/突兀长条”
  System::Call "user32::CreateWindowEx(i 0, t 'msctls_progress32', i 0, i 0x50000001, i 30, i 240, i 480, i 8, i $Dialog, i 0, i 0, i 0) i .r1"
  StrCpy $hProgressFill $1
  System::Call "uxtheme::SetWindowTheme(i $hProgressFill, w \"\", w \"\")"
  SendMessage $hProgressFill ${PBM_SETRANGE} 0 0x00640000
  SendMessage $hProgressFill ${PBM_SETBARCOLOR} 0 0x007E53D4
  SendMessage $hProgressFill ${PBM_SETBKCOLOR} 0 0x00D1C0F4
  System::Call "gdi32::CreateRoundRectRgn(i 0, i 0, i 480, i 8, i 4, i 4) i .r2"
  System::Call "user32::SetWindowRgn(i $hProgressFill, i r2, i 1)"

  ${NSD_CreateLabel} 30 252 480 18 ""
  Pop $hProgressStatus
  SetCtlColors $hProgressStatus "${CLR_TEXT_MUTED}" "${CLR_BG}"
  !insertmacro ApplyFont $hProgressStatus $hFontTiny

  ; ── 安装组件明细：两栏（左栏组件列表分两列 + 右栏当前详情）──
  ; 重排：原单列 8 行 pitch 10 导致行间重叠、末行溢出页脚；现两列 4 行 pitch 20、行高 16，
  ; 组件区 272..366 完整落于页脚(368)之上，不再重叠/溢出。
  ${NSD_CreateLabel} 30 272 200 16 "安装组件"
  Pop $hCompTitle
  SetCtlColors $hCompTitle "${CLR_DARK_PINK}" "${CLR_BG}"
  !insertmacro ApplyFont $hCompTitle $hFontBody

  ; 左列（x=30）
  ${NSD_CreateLabel} 30 290 130 16 "○ 主程序"
  Pop $hC1
  SetCtlColors $hC1 "${CLR_TEXT_MUTED}" "${CLR_BG}"
  !insertmacro ApplyFont $hC1 $hFontTiny
  ${NSD_CreateLabel} 30 310 130 16 "○ Python 运行时"
  Pop $hC3
  SetCtlColors $hC3 "${CLR_TEXT_MUTED}" "${CLR_BG}"
  !insertmacro ApplyFont $hC3 $hFontTiny
  ${NSD_CreateLabel} 30 330 130 16 "○ 依赖运行库"
  Pop $hC5
  SetCtlColors $hC5 "${CLR_TEXT_MUTED}" "${CLR_BG}"
  !insertmacro ApplyFont $hC5 $hFontTiny
  ${NSD_CreateLabel} 30 350 130 16 "○ 注册表信息"
  Pop $hC7
  SetCtlColors $hC7 "${CLR_TEXT_MUTED}" "${CLR_BG}"
  !insertmacro ApplyFont $hC7 $hFontTiny

  ; 右列（x=165）
  ${NSD_CreateLabel} 165 290 145 16 "○ 核心资源"
  Pop $hC2
  SetCtlColors $hC2 "${CLR_TEXT_MUTED}" "${CLR_BG}"
  !insertmacro ApplyFont $hC2 $hFontTiny
  ${NSD_CreateLabel} 165 310 145 16 "○ SearXNG 搜索引擎"
  Pop $hC4
  SetCtlColors $hC4 "${CLR_TEXT_MUTED}" "${CLR_BG}"
  !insertmacro ApplyFont $hC4 $hFontTiny
  ${NSD_CreateLabel} 165 330 145 16 "○ 卸载程序"
  Pop $hC6
  SetCtlColors $hC6 "${CLR_TEXT_MUTED}" "${CLR_BG}"
  !insertmacro ApplyFont $hC6 $hFontTiny
  ${NSD_CreateLabel} 165 350 145 16 "○ 开始菜单快捷方式"
  Pop $hC8
  SetCtlColors $hC8 "${CLR_TEXT_MUTED}" "${CLR_BG}"
  !insertmacro ApplyFont $hC8 $hFontTiny

  ; 右栏：当前组件详情（标题 + 当前组件名(大) + 进度%）
  ${NSD_CreateLabel} 320 272 190 16 "当前安装"
  Pop $hCurDetail
  SetCtlColors $hCurDetail "${CLR_DARK_PINK}" "${CLR_BG}"
  !insertmacro ApplyFont $hCurDetail $hFontBody
  ${NSD_CreateLabel} 320 296 190 24 ""
  Pop $hCurName
  SetCtlColors $hCurName "${CLR_DARK_PINK}" "${CLR_BG}"
  !insertmacro ApplyFont $hCurName $hFontBody
  ${NSD_CreateLabel} 320 328 190 32 ""
  Pop $hCurPct
  SetCtlColors $hCurPct "${CLR_PINK}" "${CLR_BG}"
  !insertmacro ApplyFont $hCurPct $hFontTitle

  !insertmacro CreateFooter 3 "$PLUGINSDIR\btn_installing.bmp" 1 0 fn_PrevClick fn_NextClick

  StrCpy $InstallDone 0
  StrCpy $InstallStage 0

  ; 关闭运行中的程序 / 卸载旧版等重活在 fn_DoInstall 首阶段（对话框已显示后）执行，
  ; 避免 nsDialogs::Show 前同步阻塞导致「灰白空窗」闪现（#1）。

  ${NSD_CreateTimer} fn_InstallTick 100

  ${NSD_FreeBitmap} $hBanner
  nsDialogs::Show
FunctionEnd

; 进度推进的唯一入口：进度条 + 右下角「百分比数字」必须同源同值。
; 修 #170 缺陷：此前 $hCurPct 只在各阶段开头被设成 "0%"、结尾设成 "100%"，
; 中间从不更新 ⇒ 用户全程只看到 0% 和 100%（进度条动了、数字没动）。
; 旧宏 SetProgressWidth 只动条不动数字（正是该缺陷的温床），已删除；
; 今后任何进度推进一律走本宏，禁止再出现第二个写法。
!macro SetInstallProgress PERCENT
  SendMessage $hProgressFill ${PBM_SETPOS} ${PERCENT} 0
  ${NSD_SetText} $hCurPct "${PERCENT}%"
  ; 立即重绘父窗口（含进度条），避免大文件写入阻塞 UI 线程时进度条“假死”
  System::Call "user32::UpdateWindow(i $HWNDPARENT)"
!macroend

; 后台隐藏解压某一卷，并把成功/失败写进标记文件供 timer 轮询。
;
; ★★ 这里是 2026-09-17 真机验证挖出的真凶，别再改回原样 ★★
; 原写法是 ExecShell '/c "7z.exe" x -y -o"..." "part.7z" && echo done > "flag"'，
; 但 cmd.exe 对 `/c` 后**以引号开头**的命令行有特殊规则：它会剥掉**首尾各一个**引号，
; 于是「给 7z.exe 加的那个引号」被当成整串的边界 ⇒ 命令被拆坏。
; 真机实测后果（VM 内对照实验，可复现）：
;   A 原样写法  → cmd 退出码 1、7z 根本没运行、目标目录零产物、标记文件永不出现；
;   B 整串加引号 → 退出码 0、正常解压、标记文件正常写出。
; 而 A 的后果就是用户看到的两个症状：
;   「卡在 正在解压核心资源... (1/N)」+「百分比只有开头和 100%」——
;   因为标记永不出现 ⇒ 安装器空等约 10 分钟超时兜底 ⇒ 进度从 40% 直接跳到 100%，
;   而资源其实根本没被解压出来（装完是残缺的）。
; 所以：整条命令必须**用一对引号整体包起来**交给 cmd /c（B 写法），
; 且用 &&/|| 把成功失败都写进标记，杜绝“解压失败被静默吞掉”。
;
; ★★ 2026-09-18 二次定音：标记文件必须**每卷一个唯一名字**，禁止再共用 res_done.flag ★★
; 真机（VMware Win10 装 0.2.4）实测：安装完 resources 只有 11598 个文件，构建侧是 14711 个，
; 丢的正好是**最后三卷（14/15/16）整卷零产出**，其中第 16 卷含 python-embed\python313.dll
; ⇒ pythonw.exe 起不来（弹「找不到 python313.dll」）⇒ 后端根本没起 ⇒ 点桌宠毫无反应。
; 而同一批归档在 guest 里用同一句 7z 命令**手动逐卷解压，16 卷全部 OK、14711 个文件一个不少**
; （归档、7z、环境全部清白）⇒ 丢卷发生在安装器的推进逻辑里：
;   timer 靠「读 res_done.flag → Delete → 进下一卷」串行化。一旦某次 Delete 因杀软/索引器
;   瞬时占用而**静默失败**（0.2.4 现场 _bundle 清理同样反复出现这种瞬时占用），下一 tick
;   就会读到**上一卷的陈旧标记**，于是以 ~240ms/卷 的速度冲刺到底、把最后几卷的 7z 全部并发
;   拉起；紧接着 res_verify→res_finish 的 RMDir /r _bundle 把归档删掉，正在启动的 7z 直接失败
;   ⇒ 那几卷零产出；而循环此时已退出，写回来的 FAIL 标记再也没人读 ⇒ 界面照样显示“安装完成”。
; 改成本卷唯一标记后，安装器只等待「自己刚启动的那一卷」的标记，陈旧标记天然无害。
!macro StartPartExtract PARTINDEX
  ExecShell "open" "cmd.exe" '/c "$\"$INSTDIR\resources\_bundle\7z.exe$\" x -y -o$\"$INSTDIR\resources$\" $\"$INSTDIR\resources\_bundle\res_part_${PARTINDEX}.7z$\" > nul 2>&1 && echo OK > $\"$PLUGINSDIR\res_done_${PARTINDEX}.flag$\" || echo FAIL > $\"$PLUGINSDIR\res_done_${PARTINDEX}.flag$\""' SW_HIDE
!macroend

; 资源解压期间的心跳计数（每 tick +1，满 10 ≈ 1 秒，用于刷新"已用 N 秒"）
Var TickSec
Var TickSecN
; 资源解压的完成标记内容（OK/FAIL）与「是否有卷解压失败」，用于把失败如实报出来
Var FlagTxt
Var ResFlag
Var ResFail
; 安装是否被判为「资源不完整」：置 1 后①最终文案不再谎报「安装完成。」②**保留** _bundle
; 归档与 7z.exe（不清道夫清理），既便于用户重装复用，也便于事后取证。
Var ResBroken
; 清理临时解压目录的重试计数
Var CleanTry

Function fn_InstallTick
  ; 先杀掉当前计时器再重建，避免每次 tick 都新增一个计时器造成泄漏累积（曾导致 UI 卡顿/转圈）。
  ${NSD_KillTimer} fn_InstallTick
  Call fn_DoInstall
  ${If} $InstallDone != 1
    ${NSD_CreateTimer} fn_InstallTick 120
  ${EndIf}
FunctionEnd

Function fn_ProgressPageLeave
  ${If} $InstallDone != 1
    Abort
  ${EndIf}
FunctionEnd

; ─── Page 4: Finish ───
Page custom fn_Finish

Function fn_Finish
  nsDialogs::Create 1018
  Pop $Dialog
  StrCpy $CurPage 4
  !insertmacro ApplyBorderless
  !insertmacro FillPage
  !insertmacro HideWizardChrome
  SetCtlColors $Dialog "" "${CLR_BG}"

  !insertmacro ShowBanner fn_Minimize fn_Close

  ${NSD_CreateLabel} 30 ${CONTENT_TOP} 480 28 "安装完成"
  Pop $0
  SetCtlColors $0 "${CLR_DARK_PINK}" "${CLR_BG}"
  !insertmacro ApplyFont $0 $hFontTitle

  ${NSD_CreateLabel} 30 210 480 20 "奶昔 · 桌面智能体 v${VERSION} 已经安装完成。"
  Pop $0
  SetCtlColors $0 "${CLR_TEXT_BODY}" "${CLR_BG}"
  !insertmacro ApplyFont $0 $hFontBody

  ${NSD_CreateCheckBox} 30 250 480 18 ""
  Pop $RunCheck
  SendMessage $RunCheck ${BM_SETCHECK} ${BST_CHECKED} 0
  SendMessage $RunCheck ${WM_SETTEXT} 0 "STR:立即运行奶昔"
  SetCtlColors $RunCheck "${CLR_INPUT_TEXT}" "${CLR_BG}"
  !insertmacro ApplyFont $RunCheck $hFontBody

  ${NSD_CreateCheckBox} 30 282 480 18 ""
  Pop $DesktopCheck
  SendMessage $DesktopCheck ${BM_SETCHECK} ${BST_CHECKED} 0
  SendMessage $DesktopCheck ${WM_SETTEXT} 0 "STR:创建桌面快捷方式"
  SetCtlColors $DesktopCheck "${CLR_INPUT_TEXT}" "${CLR_BG}"
  !insertmacro ApplyFont $DesktopCheck $hFontBody

  !insertmacro CreateFooter 4 "$PLUGINSDIR\btn_finish.bmp" 1 1 fn_PrevClick fn_NextClick

  ${NSD_FreeBitmap} $hBanner
  nsDialogs::Show
FunctionEnd

Function fn_Done
  ${NSD_GetState} $DesktopCheck $0
  ${If} $0 = ${BST_CHECKED}
    ; 快捷方式名称固定为「奶昔」，图标复用安装目录内的主程序图标
    CreateShortcut "$DESKTOP\奶昔.lnk" "$INSTDIR\${MAINBINARYNAME}.exe" "" "$INSTDIR\icon.ico" 0
  ${EndIf}
  ${NSD_GetState} $RunCheck $0
  ${If} $0 = ${BST_CHECKED}
    nsis_tauri_utils::RunAsUser "$INSTDIR\${MAINBINARYNAME}.exe" ""
  ${EndIf}
  ; 关闭安装器：给主窗口发 WM_CLOSE（与 fn_Close 一致，已验证可关闭无边框窗口）。
  ; 完成页是最后一页，关闭主窗口即正常结束安装。
  ; （直接 Quit 在 nsDialogs 模态循环内不关闭对话框会卡死；本 NSIS 无 nsDialogs::Close；
  ;  WM_CLOSE 发 $Dialog 无效，故发 $HWNDPARENT。）
  SendMessage $HWNDPARENT ${WM_CLOSE} 0 0
FunctionEnd

; ─── Languages (disabled - custom nsDialogs pages don't need MUI) ───
{{#if false}}
{{#each languages}}
!insertmacro MUI_LANGUAGE "{{this}}"
{{/each}}
{{#each language_files}}
  !include "{{this}}"
{{/each}}
{{/if}}

; ═══════════════════════════════════════════════════════════
; 卸载 GUI（三页：确认 / 卸载进度 / 完成）
; ═══════════════════════════════════════════════════════════

UninstPage custom un.Confirm un.ConfirmLeave
UninstPage custom un.Progress un.ProgressLeave
UninstPage custom un.Done

Function un.onInit
  InitPluginsDir
  SetOutPath $PLUGINSDIR
  File "D:\naixi_desktop\src-tauri\installer\banner_uninstall.bmp"
  File "D:\naixi_desktop\src-tauri\installer\num1_on.bmp"
  File "D:\naixi_desktop\src-tauri\installer\num1_off.bmp"
  File "D:\naixi_desktop\src-tauri\installer\num2_on.bmp"
  File "D:\naixi_desktop\src-tauri\installer\num2_off.bmp"
  File "D:\naixi_desktop\src-tauri\installer\num3_on.bmp"
  File "D:\naixi_desktop\src-tauri\installer\num3_off.bmp"
  File "D:\naixi_desktop\src-tauri\installer\btn_next.bmp"
  File "D:\naixi_desktop\src-tauri\installer\btn_finish.bmp"
  File "D:\naixi_desktop\src-tauri\installer\btn_uninstalling.bmp"
  File "D:\naixi_desktop\src-tauri\installer\btn_prev.bmp"
  File "D:\naixi_desktop\src-tauri\installer\btn_uninstall.bmp"
  File "D:\naixi_desktop\src-tauri\installer\btn_min.bmp"
  File "D:\naixi_desktop\src-tauri\installer\btn_close.bmp"
  File "D:\naixi_desktop\src-tauri\installer\txt_step_u1_on.bmp"
  File "D:\naixi_desktop\src-tauri\installer\txt_step_u1_off.bmp"
  File "D:\naixi_desktop\src-tauri\installer\txt_step_u2_on.bmp"
  File "D:\naixi_desktop\src-tauri\installer\txt_step_u2_off.bmp"
  File "D:\naixi_desktop\src-tauri\installer\txt_step_u3_on.bmp"
  File "D:\naixi_desktop\src-tauri\installer\txt_step_u3_off.bmp"
  File "D:\naixi_desktop\src-tauri\installer\dot_uninstall.bmp"
  File "D:\naixi_desktop\src-tauri\installer\warn_uninstall.bmp"

  System::Call 'gdi32::CreateFont(i -19, i 0, i 0, i 0, i 700, i 0, i 0, i 0, i 0x01, i 0, i 0, i 0, i 0, t "Microsoft YaHei") i .r0'
  StrCpy $hFontTitle $0
  System::Call 'gdi32::CreateFont(i -13, i 0, i 0, i 0, i 400, i 0, i 0, i 0, i 0x01, i 0, i 0, i 0, i 0, t "Microsoft YaHei") i .r0'
  StrCpy $hFontBody $0
  System::Call 'gdi32::CreateFont(i -12, i 0, i 0, i 0, i 400, i 0, i 0, i 0, i 0x01, i 0, i 0, i 0, i 0, t "Microsoft YaHei") i .r0'
  StrCpy $hFontSmall $0
  System::Call 'gdi32::CreateFont(i -11, i 0, i 0, i 0, i 400, i 0, i 0, i 0, i 0x01, i 0, i 0, i 0, i 0, t "Microsoft YaHei") i .r0'
  StrCpy $hFontTiny $0
  System::Call 'gdi32::CreateFont(i -13, i 0, i 0, i 0, i 700, i 0, i 0, i 0, i 0x01, i 0, i 0, i 0, i 0, t "Microsoft YaHei") i .r0'
  StrCpy $hFontBtn $0

  !insertmacro SetContext
FunctionEnd

Function un.fn_Minimize
  ShowWindow $HWNDPARENT 6
FunctionEnd

Function un.fn_Close
  SendMessage $HWNDPARENT ${WM_CLOSE} 0 0
FunctionEnd

Function un.fn_NextClick
  ${If} $unCurPage == 3
    Call un.fn_Done
  ${Else}
    !insertmacro AdvanceNext
  ${EndIf}
FunctionEnd

Function un.fn_PrevClick
  !insertmacro AdvanceBack
FunctionEnd

Function un.fn_Done
  SendMessage $HWNDPARENT ${WM_CLOSE} 0 0
FunctionEnd

; ─── 卸载第 1 页：确认 ───
Function un.Confirm
  nsDialogs::Create 1018
  Pop $Dialog
  StrCpy $unCurPage 1
  !insertmacro ApplyBorderless
  !insertmacro FillPage
  !insertmacro HideWizardChrome
  SetCtlColors $Dialog "" "${CLR_BG}"
  !insertmacro ShowBannerU un.fn_Minimize un.fn_Close

  ${NSD_CreateLabel} 30 ${CONTENT_TOP} 480 28 "准备卸载奶昔 · 桌面智能体"
  Pop $0
  SetCtlColors $0 "${CLR_DARK_PINK}" "${CLR_BG}"
  !insertmacro ApplyFont $0 $hFontTitle

  ${NSD_CreateLabel} 30 210 480 20 "即将移除以下组件："
  Pop $0
  SetCtlColors $0 "${CLR_TEXT_BODY}" "${CLR_BG}"
  !insertmacro ApplyFont $0 $hFontBody

  ; 组件清单（粉色圆点 + 文字，匹配 mockup .component-list）
  ${NSD_CreateBitmap} 30 242 6 6 ""
  Pop $0
  ${NSD_SetBitmap} $0 "$PLUGINSDIR\dot_uninstall.bmp" $R0
  ${NSD_CreateLabel} 44 240 466 18 "奶昔 · 桌面智能体 主程序"
  Pop $0
  SetCtlColors $0 "${CLR_TEXT_BODY}" "${CLR_BG}"
  !insertmacro ApplyFont $0 $hFontTiny

  ${NSD_CreateBitmap} 30 266 6 6 ""
  Pop $0
  ${NSD_SetBitmap} $0 "$PLUGINSDIR\dot_uninstall.bmp" $R0
  ${NSD_CreateLabel} 44 264 466 18 "桌面快捷方式与开始菜单项"
  Pop $0
  SetCtlColors $0 "${CLR_TEXT_BODY}" "${CLR_BG}"
  !insertmacro ApplyFont $0 $hFontTiny

  ${NSD_CreateBitmap} 30 290 6 6 ""
  Pop $0
  ${NSD_SetBitmap} $0 "$PLUGINSDIR\dot_uninstall.bmp" $R0
  ${NSD_CreateLabel} 44 288 466 18 "本地缓存、日志与临时文件"
  Pop $0
  SetCtlColors $0 "${CLR_TEXT_BODY}" "${CLR_BG}"
  !insertmacro ApplyFont $0 $hFontTiny

  ; 删除数据勾选
  ${NSD_CreateCheckBox} 30 310 480 18 "同时删除我的个人配置与数据（对话历史、知识库、偏好设置）"
  Pop $unDeleteChk
  SendMessage $unDeleteChk ${BM_SETCHECK} ${BST_UNCHECKED} 0
  SetCtlColors $unDeleteChk "${CLR_INPUT_TEXT}" "${CLR_BG}"
  !insertmacro ApplyFont $unDeleteChk $hFontBody

  ; 警告框（浅粉底 + 左粉边 + 圆角，匹配 mockup .warn）
  ${NSD_CreateBitmap} 30 336 480 30 ""
  Pop $0
  ${NSD_SetBitmap} $0 "$PLUGINSDIR\warn_uninstall.bmp" $R0

  !insertmacro CreateFooterU 1 "$PLUGINSDIR\btn_uninstall.bmp" 0 1 un.fn_PrevClick un.fn_NextClick

  ${NSD_FreeBitmap} $hBanner
  nsDialogs::Show
FunctionEnd

Function un.ConfirmLeave
  ${NSD_GetState} $unDeleteChk $0
  StrCpy $unDeleteData $0

  ; 在离开确认页时检测并关闭正在运行的奶昔：
  ; 1) 避免进度页 nsDialogs::Show 前弹窗遮挡未绘制页面导致空白(#2)；
  ; 2) 避免主程序/子进程占用文件导致删除失败/进度卡住(#4)；
  ; 3) 无弹窗自动关闭，确认页直接翻到进度页，不卡用户。
  !if "${INSTALLMODE}" == "currentUser"
    nsis_tauri_utils::FindProcessCurrentUser "${MAINBINARYNAME}.exe"
  !else
    nsis_tauri_utils::FindProcess "${MAINBINARYNAME}.exe"
  !endif
  Pop $R0
  ${If} $R0 = 0
    ; 用 taskkill /F /T 杀整棵进程树（主程序 + sidecar 子进程），比插件单进程 KillProcess 更彻底。
    ExecWait '"taskkill" /F /T /IM "${MAINBINARYNAME}.exe"' $R1
    Sleep 1000
    ; 再次确认，仍杀不掉才提示并阻止翻页
    !if "${INSTALLMODE}" == "currentUser"
      nsis_tauri_utils::FindProcessCurrentUser "${MAINBINARYNAME}.exe"
    !else
      nsis_tauri_utils::FindProcess "${MAINBINARYNAME}.exe"
    !endif
    Pop $R0
    ${If} $R0 = 0
      MessageBox MB_OK "无法自动关闭奶昔，请手动关闭后重试卸载。"
      Abort
    ${EndIf}
  ${EndIf}
FunctionEnd

; ─── 卸载第 2 页：进度 ───
Function un.Progress
  nsDialogs::Create 1018
  Pop $Dialog
  StrCpy $unCurPage 2
  !insertmacro ApplyBorderless
  !insertmacro FillPage
  !insertmacro HideWizardChrome
  SetCtlColors $Dialog "" "${CLR_BG}"
  !insertmacro ShowBannerU un.fn_Minimize un.fn_Close

  ${NSD_CreateLabel} 30 ${CONTENT_TOP} 480 28 "正在卸载"
  Pop $0
  SetCtlColors $0 "${CLR_DARK_PINK}" "${CLR_BG}"
  !insertmacro ApplyFont $0 $hFontTitle

  ${NSD_CreateLabel} 30 210 480 20 "稍等一下，正在把奶昔从你的电脑移除..."
  Pop $0
  SetCtlColors $0 "${CLR_TEXT_BODY}" "${CLR_BG}"
  !insertmacro ApplyFont $0 $hFontBody

  ; 进度条：原生 msctls_progress32（与 test_flow P3 完全一致）
  System::Call "user32::CreateWindowEx(i 0, t 'msctls_progress32', i 0, i 0x50000001, i 30, i 246, i 480, i 8, i $Dialog, i 0, i 0, i 0) i .r1"
  StrCpy $hProgressFill $1
  System::Call "uxtheme::SetWindowTheme(i $hProgressFill, w \"\", w \"\")"
  SendMessage $hProgressFill ${PBM_SETRANGE} 0 0x00640000
  SendMessage $hProgressFill ${PBM_SETBARCOLOR} 0 0x007E53D4
  SendMessage $hProgressFill ${PBM_SETBKCOLOR} 0 0x00D1C0F4
  System::Call "gdi32::CreateRoundRectRgn(i 0, i 0, i 480, i 8, i 4, i 4) i .r2"
  System::Call "user32::SetWindowRgn(i $hProgressFill, i r2, i 1)"

  ${NSD_CreateLabel} 30 262 480 18 ""
  Pop $unProgStatus
  SetCtlColors $unProgStatus "${CLR_TEXT_MUTED}" "${CLR_BG}"
  !insertmacro ApplyFont $unProgStatus $hFontTiny

  !insertmacro CreateFooterU 2 "$PLUGINSDIR\btn_uninstalling.bmp" 0 0 un.fn_PrevClick un.fn_NextClick

  ; 步骤文字提到顶层、footer 背景压底（与 test_flow P3 一致，避免被 footer 盖住）
  System::Call "user32::SetWindowPos(i $hStepTxt1, i 0, i 0, i 0, i 0, i 0, i 0x0003)"
  System::Call "user32::SetWindowPos(i $hStepTxt2, i 0, i 0, i 0, i 0, i 0, i 0x0003)"
  System::Call "user32::SetWindowPos(i $hStepTxt3, i 0, i 0, i 0, i 0, i 0, i 0x0003)"
  System::Call "user32::SetWindowPos(i $hFooterBg, i 1, i 0, i 0, i 0, i 0, i 0x0003)"

  StrCpy $unInstallDone 0
  StrCpy $unInstallStage 0
  StrCpy $unProg 0

  ; 进程占用检测与关闭已前移到 un.ConfirmLeave（离开确认页时执行）。
  ; 原因：若在此处 nsDialogs::Show 之前弹出 MessageBox，会盖在尚未绘制的
  ; 无边框进度页上导致页面空白(#2)，且弹窗后页面/timer 状态被破坏使进度停住(#4)。
  ; 到达本页时进程已被关闭，进度页可干净绘制、timer 正常触发。

  ${NSD_CreateTimer} un.UninstallTick 100

  ${NSD_FreeBitmap} $hBanner
  nsDialogs::Show
FunctionEnd

Function un.UninstallTick
  ; 先杀掉当前计时器再重建，避免每次 tick 都新增一个计时器造成泄漏累积（曾导致卸载时 UI 卡顿/转圈）。
  ${NSD_KillTimer} un.UninstallTick
  Call un.DoUninstallStage
  ${If} $unInstallDone != 1
    ${NSD_CreateTimer} un.UninstallTick 120
  ${EndIf}
FunctionEnd

Function un.ProgressLeave
  ${If} $unInstallDone != 1
    Abort
  ${EndIf}
FunctionEnd

; ─── 卸载第 3 页：完成 ───
Function un.Done
  nsDialogs::Create 1018
  Pop $Dialog
  StrCpy $unCurPage 3
  !insertmacro ApplyBorderless
  !insertmacro FillPage
  !insertmacro HideWizardChrome
  SetCtlColors $Dialog "" "${CLR_BG}"
  !insertmacro ShowBannerU un.fn_Minimize un.fn_Close

  ${NSD_CreateLabel} 30 ${CONTENT_TOP} 480 28 "卸载完成"
  Pop $0
  SetCtlColors $0 "${CLR_DARK_PINK}" "${CLR_BG}"
  !insertmacro ApplyFont $0 $hFontTitle

  ${NSD_CreateLabel} 30 210 480 20 "奶昔 · 桌面智能体 已从你的电脑移除。"
  Pop $0
  SetCtlColors $0 "${CLR_TEXT_BODY}" "${CLR_BG}"
  !insertmacro ApplyFont $0 $hFontBody

  ${If} $unDeleteData == ${BST_CHECKED}
    ${NSD_CreateLabel} 30 236 480 20 "已同时删除你的个人配置与数据。"
    Pop $0
    SetCtlColors $0 "${CLR_TEXT_BODY}" "${CLR_BG}"
    !insertmacro ApplyFont $0 $hFontBody
  ${EndIf}

  !insertmacro CreateFooterU 3 "$PLUGINSDIR\btn_finish.bmp" 0 1 un.fn_PrevClick un.fn_NextClick

  ${NSD_FreeBitmap} $hBanner
  nsDialogs::Show
FunctionEnd

; ─── 卸载实际删除逻辑（分阶段；GUI 由 timer 驱动，静默由 Section Uninstall 驱动）───
Function un.DoUninstallStage
  ${If} $unInstallDone == 1
    Return
  ${EndIf}
  ${If} $unInstallStage == 0
    ${IfNot} ${Silent}
      ${NSD_SetText} $unProgStatus "正在检查程序是否在运行... 5%"
      SendMessage $hProgressFill ${PBM_SETPOS} 5 0
    ${EndIf}
    StrCpy $ResBatch 0
    IntOp $unInstallStage $unInstallStage + 1
    Return
  ${EndIf}
  ${If} $unInstallStage == 1
    ; 分批删除资源文件：每个 tick 只删 ${RES_BATCH_SIZE} 个后 Return，让 UI 消息泵刷新，
    ; 避免一次性同步删 15000+ 文件（python-embed 等）导致鼠标转圈卡死（#6）。
    ${IfNot} ${Silent}
      ${NSD_SetText} $unProgStatus "正在删除资源文件..."
    ${EndIf}
    IntOp $BatchStart $ResBatch * ${RES_BATCH_SIZE}
    IntOp $BatchEnd $BatchStart + ${RES_BATCH_SIZE}
    StrCpy $ResIdx 0
    {{#each resources}}
      ${If} $ResIdx >= $BatchStart
      ${AndIf} $ResIdx < $BatchEnd
        Delete "$INSTDIR\\{{this.[1]}}"
      ${EndIf}
      IntOp $ResIdx $ResIdx + 1
    {{/each}}
    ; 进度按已删比例在 5→70% 间推进
    IntOp $BatchTmp $BatchEnd * 65
    IntOp $BatchTmp $BatchTmp / $ResIdx
    IntOp $BatchTmp $BatchTmp + 5
    ${If} $BatchTmp > 70
      StrCpy $BatchTmp 70
    ${EndIf}
    ${IfNot} ${Silent}
      SendMessage $hProgressFill ${PBM_SETPOS} $BatchTmp 0
    ${EndIf}
    IntOp $ResBatch $ResBatch + 1
    ${If} $BatchEnd >= $ResIdx
      IntOp $unInstallStage $unInstallStage + 1
    ${EndIf}
    Return
  ${EndIf}
  ${If} $unInstallStage == 2
    ${IfNot} ${Silent}
      ${NSD_SetText} $unProgStatus "正在删除主程序与依赖... 80%"
      SendMessage $hProgressFill ${PBM_SETPOS} 80 0
    ${EndIf}
    Delete "$INSTDIR\${MAINBINARYNAME}.exe"
    {{#each binaries}}
    Delete "$INSTDIR\\{{this}}"
    {{/each}}
    Delete "$INSTDIR\icon.ico"
    Delete "$INSTDIR\uninstall.exe"
    IntOp $unInstallStage $unInstallStage + 1
    Return
  ${EndIf}
  ${If} $unInstallStage == 3
    ${IfNot} ${Silent}
      ${NSD_SetText} $unProgStatus "正在删除快捷方式与注册表... 90%"
      SendMessage $hProgressFill ${PBM_SETPOS} 90 0
    ${EndIf}
    Delete "$SMPROGRAMS\${PRODUCTNAME}\奶昔.lnk"
    RMDir "$SMPROGRAMS\${PRODUCTNAME}"
    Delete "$DESKTOP\奶昔.lnk"
    DeleteRegKey SHCTX "${UNINSTKEY}"
    ${If} $unDeleteData == ${BST_CHECKED}
      RMDir /r "$APPDATA\${PRODUCTNAME}"
    ${EndIf}
    IntOp $unInstallStage $unInstallStage + 1
    Return
  ${EndIf}
  ${IfNot} ${Silent}
    ${NSD_SetText} $unProgStatus "正在清理目录... 100%"
    SendMessage $hProgressFill ${PBM_SETPOS} 100 0
  ${EndIf}
  ; 此时资源文件已分批删空，下面 RMDir /r 只清理空目录残壳，速度快、不会卡。
  RMDir /r "$INSTDIR\resources"
  RMDir /r "$INSTDIR\sidecar"
  RMDir "$INSTDIR"
  StrCpy $unInstallDone 1
  ${IfNot} ${Silent}
    ${NSD_SetBitmap} $hNextBmp "$PLUGINSDIR\btn_finish.bmp" $R0
    ${NSD_SetText} $unProgStatus "卸载完成 100%"
    EnableWindow $hNextBtn 1
  ${EndIf}
FunctionEnd

Function un.DoUninstallAll
  ${Do}
    Call un.DoUninstallStage
  ${LoopUntil} $unInstallDone == 1
FunctionEnd

; ════════════════════════════════════════════
; Sections (install logic)
; ════════════════════════════════════════════

Section "Main" SEC01
SectionEnd

; ─── WebView2 运行时检测与安装 ───
; 调用时机：fn_DoInstall stage 0（资源写入之前），仅执行一次。
; 模式：INSTALLWEBVIEW2MODE 默认 downloadBootstrapper（tauri.conf.json 未设 webviewInstallMode），
;   故缺失时从微软官方 Evergreen Bootstrapper 链接联网下载并静默安装。
Function InstallWebView2
  ; 1) 检测是否已安装 WebView2 运行时（HKLM 优先，回退 HKCU）
  ${If} ${RunningX64}
    ReadRegStr $4 HKLM "SOFTWARE\WOW6432Node\Microsoft\EdgeUpdate\Clients\${WEBVIEW2APPGUID}" "pv"
  ${Else}
    ReadRegStr $4 HKLM "SOFTWARE\Microsoft\EdgeUpdate\Clients\${WEBVIEW2APPGUID}" "pv"
  ${EndIf}
  ${If} $4 == ""
    ReadRegStr $4 HKCU "SOFTWARE\Microsoft\EdgeUpdate\Clients\${WEBVIEW2APPGUID}" "pv"
  ${EndIf}

  ; 已安装则直接返回，无需处理
  ${If} $4 != ""
    Return
  ${EndIf}

  ; 配置为 skip 时不处理（当前构建不会进入此分支）
  ${If} ${INSTALLWEBVIEW2MODE} == "skip"
    Return
  ${EndIf}

  ; 2) 缺失：联网下载 Evergreen Bootstrapper 到插件临时目录
  ${NSD_SetText} $hProgressStatus "正在准备 WebView2 运行时..."
  NSISdl::download "https://go.microsoft.com/fwlink/p/?LinkId=2124703" "$PLUGINSDIR\MicrosoftEdgeWebview2Setup.exe"
  Pop $0
  ${If} $0 == 0
    ; 3) 静默执行引导器（/silent 由 WEBVIEW2INSTALLERARGS 提供），联网安装运行时。
    ;    以注册表复检为权威判定（引导器在“已安装/需重启”时可能返回非 0）。
    nsExec::ExecToStack "$\"$PLUGINSDIR\MicrosoftEdgeWebview2Setup.exe$\" ${WEBVIEW2INSTALLERARGS}"
    Pop $0
    ${If} ${RunningX64}
      ReadRegStr $4 HKLM "SOFTWARE\WOW6432Node\Microsoft\EdgeUpdate\Clients\${WEBVIEW2APPGUID}" "pv"
    ${Else}
      ReadRegStr $4 HKLM "SOFTWARE\Microsoft\EdgeUpdate\Clients\${WEBVIEW2APPGUID}" "pv"
    ${EndIf}
    ${If} $4 == ""
      ReadRegStr $4 HKCU "SOFTWARE\Microsoft\EdgeUpdate\Clients\${WEBVIEW2APPGUID}" "pv"
    ${EndIf}
    ${If} $4 == ""
      MessageBox MB_OK "WebView2 运行时自动安装失败。请手动从微软官网下载并安装 WebView2 运行时后重试安装。"
    ${EndIf}
  ${Else}
    MessageBox MB_OK "无法下载 WebView2 运行时安装程序。请检查网络连接，或手动从微软官网下载并安装 WebView2 运行时后再试。"
  ${EndIf}
FunctionEnd

Function fn_DoInstall
  ${If} $InstallStage == 0
    ${NSD_SetText} $hProgressStatus "准备安装..."
    !insertmacro SetInstallProgress 8
    StrCpy $ResBatch 0
    ; ── 覆盖安装修复（移到此处：对话框已显示，避免「灰白空窗」#1）──
    ; 1) 杀整棵进程树（主程序 + Python 子进程），释放文件锁
    ${NSD_SetText} $hProgressStatus "正在关闭运行中的奶昔..."
    nsExec::Exec 'taskkill /F /T /IM "${MAINBINARYNAME}.exe"'
    Pop $R0
    nsExec::Exec 'taskkill /F /IM pythonw.exe'
    Pop $R0
    nsExec::Exec 'taskkill /F /IM python.exe'
    Pop $R0
    Sleep 800
    ; 2) 升级模式：先静默卸旧版，再装（干净覆盖安装）
    ReadRegStr $R2 SHCTX "${UNINSTKEY}" "InstallLocation"
    ${If} $R2 != ""
      IfFileExists "$R2\${MAINBINARYNAME}.exe" 0 +2
        ${NSD_SetText} $hProgressStatus "检测到旧版本，正在卸载..."
        ExecWait '"$R2\uninstall.exe" /S _?=$R2' $R1
        Sleep 500
    ${EndIf}
    nsExec::Exec 'taskkill /F /T /IM "${MAINBINARYNAME}.exe"'
    Pop $R0
    Sleep 300
    ; 安装前确保 WebView2 运行时存在（干净机器缺它会起不来）。
    Call InstallWebView2
    SetOutPath $INSTDIR
    !ifmacrodef NSIS_HOOK_PREINSTALL
      !insertmacro NSIS_HOOK_PREINSTALL
    !endif
    IntOp $InstallStage $InstallStage + 1
    Return
  ${EndIf}
  ${If} $InstallStage == 1
    ${NSD_SetText} $hProgressStatus "写入主程序..."
    ${NSD_SetText} $hCurName "主程序"
    !insertmacro SetComp 1 1 "主程序"
    !insertmacro SetInstallProgress 25
    File "${MAINBINARYSRCPATH}"
    File "D:\naixi_desktop\src-tauri\icons\icon.ico"
    !insertmacro SetComp 1 2 "主程序"
    IntOp $InstallStage $InstallStage + 1
    Return
  ${EndIf}
  ${If} $InstallStage == 2
    ; 资源聚合包（多卷 7z）：按体积均分 N 卷，逐卷后台解压，每卷完成推进进度条(40→68)，
    ; 根治「只有 0%→100% 跳变」（build.rs 打 res_part_*.7z；part_count.txt 记录卷数）。
    ${If} $ResBatch == 0
      ${NSD_SetText} $hProgressStatus "创建资源目录..."
      !insertmacro SetInstallProgress 40
      ; ★ 覆盖安装：先删上一版的程序目录，再解压新资源（保留 resources\data 用户数据）。
      ;   7z 是覆盖式解压（x -y），不会删除新版本已去掉的旧文件。VM 实测（0.2.6 → 0.2.7）：
      ;   python-embed 里同时留下两代 site-packages，残留 aiohttp 3.14.1 / cryptography 49.0.0 /
      ;   certifi 2026.6.17 / annotated_doc 0.0.4 的旧文件与旧 dist-info，共 727 处哈希不一致；
      ;   残留还可能让 Python import 到已删除的旧模块。故此处显式清理后重装。
      ;   仅清理纯程序目录；resources\data（数据库/模型/日志）绝不动。
      RMDir /r "$INSTDIR\resources\python-embed"
      RMDir /r "$INSTDIR\resources\desktop_core"
      !insertmacro SetComp 2 1 "核心资源 (desktop_core)"
      !insertmacro SetComp 3 1 "Python 运行时"
      !insertmacro SetComp 4 1 "SearXNG 搜索引擎"
      ${NSD_SetText} $hCurName "核心资源"
      {{#each resources_dirs}}
        CreateDirectory "$INSTDIR\\{{this}}"
      {{/each}}
      ${NSD_SetText} $hProgressStatus "写入安装包资源..."
      {{#each resources}}
        File /a "/oname={{this.[1]}}" "{{no-escape @key}}"
      {{/each}}
      ; 读取分卷总数（build.rs 生成，纯整数、无换行）
      StrCpy $PartTotal 1
      ${If} ${FileExists} "$INSTDIR\resources\_bundle\part_count.txt"
        FileOpen $R5 "$INSTDIR\resources\_bundle\part_count.txt" r
        FileRead $R5 $R6
        FileClose $R5
        ${If} $R6 != ""
          StrCpy $PartTotal $R6
        ${EndIf}
      ${EndIf}
      ${If} $PartTotal <= 0
        StrCpy $PartTotal 1
      ${EndIf}
      StrCpy $CurPart 1
      StrCpy $BatchTmp2 0
      StrCpy $ResFail 0
      StrCpy $ResBroken 0
      ${NSD_SetText} $hProgressStatus "正在解压核心资源... (1/$PartTotal)"
      IntFmt $R7 "%02d" $CurPart
      !insertmacro StartPartExtract $R7
      IntOp $ResBatch $ResBatch + 1
      Return
    ${EndIf}
    ${If} $ResBatch == 1
      IntOp $BatchTmp2 $BatchTmp2 + 1
      ; 心跳：每约 1 秒刷新一次状态行（"已用 N 秒"），
      ; 避免单卷较大、解压较久时观感像卡死（#170 的伴生问题）
      IntOp $TickSec $TickSec + 1
      ${If} $TickSec >= 10
        StrCpy $TickSec 0
        IntOp $TickSecN $BatchTmp2 / 10
        ${NSD_SetText} $hProgressStatus "正在解压核心资源... ($CurPart/$PartTotal)，已用 $TickSecN 秒"
      ${EndIf}
      ; ★ 只等「当前这一卷」自己的唯一标记（res_done_NN.flag）。
      ;   共用一个 res_done.flag 时，Delete 一旦失败就会读到陈旧标记而冲刺丢卷（见 StartPartExtract 注释）。
      ;   $R7 是寄存器，可能被中间的 System::Call 污染 ⇒ 每 tick 都按 $CurPart 重新格式化，禁止跨 tick 依赖。
      IntFmt $R7 "%02d" $CurPart
      StrCpy $R9 "$PLUGINSDIR\res_done_"
      StrCpy $R9 "$R9$R7.flag"
      ${If} ${FileExists} "$R9"
        ; 标记文件内容 = OK / FAIL（由解压命令按退出码写入），失败不再被静默吞掉
        FileOpen $FlagTxt "$R9" r
        FileRead $FlagTxt $ResFlag
        FileClose $FlagTxt
        Delete "$R9"
        StrCpy $ResFlag $ResFlag 4
        ${If} $ResFlag == "FAIL"
          StrCpy $ResFail 1
        ${EndIf}
        ; 本卷完成：按已完成卷数推进总进度（stage2 占 40→68）
        IntOp $R8 $CurPart * 28
        IntOp $R8 $R8 / $PartTotal
        IntOp $R8 $R8 + 40
        !insertmacro SetInstallProgress $R8
        ${If} $CurPart < $PartTotal
          IntOp $CurPart $CurPart + 1
          ; 每卷重置计时：既让"已用秒数"从 0 起算，也让超时判断按"单卷"而非全程累计
          StrCpy $BatchTmp2 0
          StrCpy $TickSec 0
          ${NSD_SetText} $hProgressStatus "正在解压核心资源... ($CurPart/$PartTotal)，已用 0 秒"
          IntFmt $R7 "%02d" $CurPart
          !insertmacro StartPartExtract $R7
          Return
        ${Else}
          Goto res_verify
        ${EndIf}
      ${ElseIf} $BatchTmp2 > 3000
        ; 超时兜底（约 6 分钟/卷，正常单卷只需数秒~数十秒）：
        ; 超时本身就是严重异常 ⇒ 直接判「不完整」（保留归档、最终文案不再谎报安装完成），
        ; 而不是走 res_verify —— 那里只要哨兵文件在就会宣布成功，可能掩盖残缺。
        ${NSD_SetText} $hProgressStatus "警告：资源解压超时（$CurPart/$PartTotal），安装可能不完整"
        Goto res_broken
      ${EndIf}
      ; 未完成：保持状态，等待下一 tick（不阻塞 UI）
      Return
    ${EndIf}
  ${EndIf}
  ${If} $InstallStage == 3
    ${NSD_SetText} $hProgressStatus "写入依赖文件..."
    ${NSD_SetText} $hCurName "依赖运行库"
    !insertmacro SetComp 5 1 "依赖运行库"
    !insertmacro SetInstallProgress 70
    {{#each binaries}}
      File /a "/oname={{this}}" "{{no-escape @key}}"
    {{/each}}
    !insertmacro SetComp 5 2 "依赖运行库"
    IntOp $InstallStage $InstallStage + 1
    Return
  ${EndIf}
  ${If} $InstallStage == 4
    ${NSD_SetText} $hProgressStatus "写入卸载程序..."
    ${NSD_SetText} $hCurName "卸载程序"
    !insertmacro SetComp 6 1 "卸载程序"
    !insertmacro SetInstallProgress 82
    WriteUninstaller "$INSTDIR\uninstall.exe"
    !insertmacro SetComp 6 2 "卸载程序"
    IntOp $InstallStage $InstallStage + 1
    Return
  ${EndIf}
  ${If} $InstallStage == 5
    ${NSD_SetText} $hProgressStatus "注册安装信息..."
    ${NSD_SetText} $hCurName "注册表信息"
    !insertmacro SetComp 7 1 "注册表信息"
    !insertmacro SetInstallProgress 90
    WriteRegStr SHCTX "${MANUPRODUCTKEY}" "" $INSTDIR
    WriteRegStr SHCTX "${UNINSTKEY}" "MainBinaryName" "${MAINBINARYNAME}.exe"
    WriteRegStr SHCTX "${UNINSTKEY}" "DisplayName" "${PRODUCTNAME}"
    WriteRegStr SHCTX "${UNINSTKEY}" "DisplayIcon" "$\"$INSTDIR\${MAINBINARYNAME}.exe$\""
    WriteRegStr SHCTX "${UNINSTKEY}" "DisplayVersion" "${VERSION}"
    WriteRegStr SHCTX "${UNINSTKEY}" "Publisher" "${MANUFACTURER}"
    WriteRegStr SHCTX "${UNINSTKEY}" "InstallLocation" "$\"$INSTDIR$\""
    WriteRegStr SHCTX "${UNINSTKEY}" "UninstallString" "$\"$INSTDIR\uninstall.exe$\""
    WriteRegDWORD SHCTX "${UNINSTKEY}" "NoModify" "1"
    WriteRegDWORD SHCTX "${UNINSTKEY}" "NoRepair" "1"
    !if "${HOMEPAGE}" != ""
      WriteRegStr SHCTX "${UNINSTKEY}" "URLInfoAbout" "${HOMEPAGE}"
    !endif
    !insertmacro SetComp 7 2 "注册表信息"
    IntOp $InstallStage $InstallStage + 1
    Return
  ${EndIf}
  ; 最后阶段：创建快捷方式并收尾
  ${NSD_SetText} $hProgressStatus "创建快捷方式..."
  ${NSD_SetText} $hCurName "开始菜单快捷方式"
  !insertmacro SetComp 8 1 "开始菜单快捷方式"
  !insertmacro SetInstallProgress 100
  CreateDirectory "$SMPROGRAMS\${PRODUCTNAME}"
  CreateShortcut "$SMPROGRAMS\${PRODUCTNAME}\奶昔.lnk" "$INSTDIR\${MAINBINARYNAME}.exe" "" "$INSTDIR\icon.ico" 0
  !ifmacrodef NSIS_HOOK_POSTINSTALL
    !insertmacro NSIS_HOOK_POSTINSTALL
  !endif
  !insertmacro SetComp 8 2 "开始菜单快捷方式"
  StrCpy $InstallDone 1
  ${NSD_SetBitmap} $hNextBmp "$PLUGINSDIR\btn_finish.bmp" $R0
  ; 资源完整性有告警时**不能**再写「安装完成。」—— 0.2.4 正是这样把一个「后端起不来」
  ; 的残缺安装当成成功交付给用户的（用户看到安装成功、点桌宠却毫无反应）。
  ${If} $ResBroken == 1
    ${NSD_SetText} $hProgressStatus "安装完成，但核心资源不完整：请重新运行安装程序修复"
  ${Else}
    ${NSD_SetText} $hProgressStatus "安装完成。"
  ${EndIf}
  ${NSD_SetText} $hCurName "安装完成"
  EnableWindow $hNextBtn 1
  Return

  ; ── 资源完整性校验（多卷解压完成后或超时兜底时进入）──
  res_verify:
    ; 先看解压过程中有没有卷报 FAIL：有就如实告知，不要再摆出一副“安装成功”的样子
    ${If} $ResFail == 1
      ${NSD_SetText} $hProgressStatus "警告：部分资源分卷解压失败，安装可能不完整"
      Goto res_broken
    ${EndIf}
    ${IfNot} ${FileExists} "$INSTDIR\resources\desktop_core\api.py"
      ${NSD_SetText} $hProgressStatus "警告：核心资源缺失 (desktop_core/api.py)，安装可能不完整"
      Goto res_broken
    ${EndIf}
    ${IfNot} ${FileExists} "$INSTDIR\resources\python-embed\pythonw.exe"
      ${NSD_SetText} $hProgressStatus "警告：Python 运行时缺失，安装可能不完整"
      Goto res_broken
    ${EndIf}
    ; ★ python313.dll 必须单独校验：0.2.4 现场丢的就是含它的那一卷，而当时只校验了
    ;   api.py / pythonw.exe，两者都在 ⇒ 安装器照样宣布成功，用户拿到的是一个
    ;   「pythonw.exe 弹找不到 python313.dll、后端完全起不来」的坏安装。
    ${IfNot} ${FileExists} "$INSTDIR\resources\python-embed\python313.dll"
      ${NSD_SetText} $hProgressStatus "警告：Python 核心 DLL 缺失 (python313.dll)，安装不完整，请重新安装"
      Goto res_broken
    ${EndIf}
    ${IfNot} ${FileExists} "$INSTDIR\resources\desktop_core\pet_window.py"
      ${NSD_SetText} $hProgressStatus "警告：桌宠模块缺失 (pet_window.py)，安装不完整"
      Goto res_broken
    ${EndIf}
    ${IfNot} ${FileExists} "$INSTDIR\resources\searxng\SearXNG for Windows.exe"
      ${NSD_SetText} $hProgressStatus "警告：SearXNG 缺失，离线搜索可能不可用"
      Goto res_broken
    ${EndIf}
    !insertmacro SetComp 2 2 "核心资源 (desktop_core)"
    !insertmacro SetComp 3 2 "Python 运行时"
    !insertmacro SetComp 4 2 "SearXNG 搜索引擎"
    !insertmacro SetInstallProgress 68
    Goto res_finish
  ; 任一完整性告警都落到这里：置「不完整」标记后统一收尾。
  ; 收尾阶段据此①改写最终状态文案（不再谎报「安装完成。」）②跳过 _bundle 清理（保留证据+便于重装）
  res_broken:
    StrCpy $ResBroken 1
    Goto res_finish
  res_finish:
    ; 清理临时解压工具与压缩包（已解压资源保留在 $INSTDIR\resources）。
    ; ⚠ 实测（v0.2.4 真机验证）：刚写出的分卷会**被杀软/索引器占用数秒到数十秒**，
    ; 此时 NSIS 的 Delete/RMDir 会**静默失败**并留下垃圾（现场两次分别留下
    ; 7z.exe / 7z.dll / res_part_14.7z、以及 res_part_15.7z / res_part_16.7z，
    ; 而事后手动删又能删掉 ⇒ 确认是瞬时占用，不是路径写错）。
    ; 策略（v0.2.4 真机二次验证后定型）：
    ;   ① 当场只轻量重试 3 次(3s)——原 20 次×1s 会把进度页卡住 20s，且真机上杀软/
    ;      索引器占用常持续数十秒，20s 仍清不掉（实测残留 5 项：7z.exe/7z.dll +
    ;      res_part_12~14.7z，约 38MB），纯属白卡 UI。
    ;   ② 起一个**脱离安装器**的静默清道夫（VBS 由 wscript 直接执行，无控制台窗口）：
    ;      先睡 10s（等安装器退出、7z 子进程结束、杀软扫完），再最多重试 40 次×2s 删除。
    ;      这样既不占 UI，又能在「不重启」的前提下当场清干净。
    ;   ③ 清道夫也失败才挂 /REBOOTOK 等重启删除（极端兜底）。
    ${If} $ResBroken == 1
      ; 资源不完整：**保留** _bundle（含归档与 7z.exe），既方便用户重装时复用，
      ; 也便于事后取证；此时绝不起清道夫，避免把证据删掉。
      IntOp $InstallStage $InstallStage + 1
      Return
    ${EndIf}
    StrCpy $CleanTry 0
  res_clean:
    RMDir /r "$INSTDIR\resources\_bundle"
    ${If} ${FileExists} "$INSTDIR\resources\_bundle\*.*"
      IntOp $CleanTry $CleanTry + 1
      ${If} $CleanTry < 3
        Sleep 1000
        Goto res_clean
      ${EndIf}
      Delete /REBOOTOK "$INSTDIR\resources\_bundle\*.*"
      RMDir /REBOOTOK "$INSTDIR\resources\_bundle"
      ; ② 静默清道夫
      ClearErrors
      FileOpen $9 "$TEMP\naixi_bundle_clean.vbs" w
      ${IfNot} ${Errors}
        FileWrite $9 "Set fso = CreateObject($\"Scripting.FileSystemObject$\")$\r$\n"
        FileWrite $9 "WScript.Sleep 10000$\r$\n"
        FileWrite $9 "Set sh = CreateObject($\"WScript.Shell$\")$\r$\n"
        FileWrite $9 "For i = 1 To 40$\r$\n"
        FileWrite $9 "  sh.Run $\"cmd /c rmdir /s /q $\"$\"$INSTDIR\resources\_bundle$\"$\"$\", 0, True$\r$\n"
        FileWrite $9 "  If Not fso.FolderExists($\"$INSTDIR\resources\_bundle$\") Then Exit For$\r$\n"
        FileWrite $9 "  WScript.Sleep 2000$\r$\n"
        FileWrite $9 "Next$\r$\n"
        FileWrite $9 "fso.DeleteFile WScript.ScriptFullName, True$\r$\n"
        FileClose $9
        ExecShell "open" "$TEMP\naixi_bundle_clean.vbs"
      ${EndIf}
    ${EndIf}
    IntOp $InstallStage $InstallStage + 1
    Return
FunctionEnd

Section Uninstall
  ; GUI 卸载时删除逻辑由自定义页 timer 驱动（un.DoUninstallStage）；
  ; 仅静默卸载（/S）时在此直接执行，保证「无界面卸载」也能正常清理。
  ${If} ${Silent}
    Call un.DoUninstallAll
  ${EndIf}
SectionEnd

; ════════════════════════════════════════════
; Functions
; ════════════════════════════════════════════

Function RestorePreviousInstallLocation
  ReadRegStr $4 SHCTX "${MANUPRODUCTKEY}" ""
  StrCmp $4 "" +2 0
    StrCpy $INSTDIR $4
FunctionEnd

Function .onInit
  InitPluginsDir
  SetOutPath $PLUGINSDIR
  File "D:\naixi_desktop\src-tauri\installer\banner.bmp"
  File "D:\naixi_desktop\src-tauri\installer\num1_on.bmp"
  File "D:\naixi_desktop\src-tauri\installer\num1_off.bmp"
  File "D:\naixi_desktop\src-tauri\installer\num2_on.bmp"
  File "D:\naixi_desktop\src-tauri\installer\num2_off.bmp"
  File "D:\naixi_desktop\src-tauri\installer\num3_on.bmp"
  File "D:\naixi_desktop\src-tauri\installer\num3_off.bmp"
  File "D:\naixi_desktop\src-tauri\installer\num4_on.bmp"
  File "D:\naixi_desktop\src-tauri\installer\num4_off.bmp"
  File "D:\naixi_desktop\src-tauri\installer\btn_next.bmp"
  File "D:\naixi_desktop\src-tauri\installer\btn_install.bmp"
  File "D:\naixi_desktop\src-tauri\installer\btn_installing.bmp"
  File "D:\naixi_desktop\src-tauri\installer\btn_finish.bmp"
  File "D:\naixi_desktop\src-tauri\installer\btn_prev.bmp"
  File "D:\naixi_desktop\src-tauri\installer\btn_browse.bmp"
  File "D:\naixi_desktop\src-tauri\installer\btn_min.bmp"
  File "D:\naixi_desktop\src-tauri\installer\btn_close.bmp"
  File "D:\naixi_desktop\src-tauri\installer\addr_border.bmp"
  File "D:\naixi_desktop\src-tauri\icons\icon.ico"

  System::Call 'gdi32::CreateFont(i -19, i 0, i 0, i 0, i 700, i 0, i 0, i 0, i 0x01, i 0, i 0, i 0, i 0, t "Microsoft YaHei") i .r0'
  StrCpy $hFontTitle $0
  System::Call 'gdi32::CreateFont(i -13, i 0, i 0, i 0, i 400, i 0, i 0, i 0, i 0x01, i 0, i 0, i 0, i 0, t "Microsoft YaHei") i .r0'
  StrCpy $hFontBody $0
  System::Call 'gdi32::CreateFont(i -12, i 0, i 0, i 0, i 400, i 0, i 0, i 0, i 0x01, i 0, i 0, i 0, i 0, t "Microsoft YaHei") i .r0'
  StrCpy $hFontSmall $0
  System::Call 'gdi32::CreateFont(i -11, i 0, i 0, i 0, i 400, i 0, i 0, i 0, i 0x01, i 0, i 0, i 0, i 0, t "Microsoft YaHei") i .r0'
  StrCpy $hFontTiny $0
  System::Call 'gdi32::CreateFont(i -13, i 0, i 0, i 0, i 700, i 0, i 0, i 0, i 0x01, i 0, i 0, i 0, i 0, t "Microsoft YaHei") i .r0'
  StrCpy $hFontBtn $0

  ${GetOptions} $CMDLINE "/P" $PassiveMode
  ${IfNot} ${Errors}
    StrCpy $PassiveMode 1
  ${EndIf}
  ${GetOptions} $CMDLINE "/NS" $NoShortcutMode
  ${IfNot} ${Errors}
    StrCpy $NoShortcutMode 1
  ${EndIf}
  ${GetOptions} $CMDLINE "/UPDATE" $UpdateMode
  ${IfNot} ${Errors}
    StrCpy $UpdateMode 1
  ${EndIf}

  !if "${DISPLAYLANGUAGESELECTOR}" == "true"
    MessageBox MB_OK "Naixi 安装程序默认使用简体中文。"
  !endif

  !insertmacro SetContext

  ${If} $INSTDIR == "${PLACEHOLDER_INSTALL_DIR}"
    !if "${INSTALLMODE}" == "perMachine"
      ${If} ${RunningX64}
        StrCpy $INSTDIR "$PROGRAMFILES64\${PRODUCTNAME}"
      ${Else}
        StrCpy $INSTDIR "$PROGRAMFILES\${PRODUCTNAME}"
      ${EndIf}
    !else if "${INSTALLMODE}" == "currentUser"
      StrCpy $INSTDIR "$LOCALAPPDATA\${PRODUCTNAME}"
    !else
      ; both 模式：默认按当前用户安装，避免弹出管理员权限请求
      StrCpy $INSTDIR "$LOCALAPPDATA\${PRODUCTNAME}"
    !endif
    Call RestorePreviousInstallLocation
  ${EndIf}
FunctionEnd

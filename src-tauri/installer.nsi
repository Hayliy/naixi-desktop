Unicode true
ManifestDPIAware true
ManifestDPIAwareness PerMonitorV2

!if "{{compression}}" == "none"
  SetCompress off
!else
  SetCompressor /SOLID "{{compression}}"
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

!ifndef WM_NCLBUTTONDOWN
  !define WM_NCLBUTTONDOWN 0x00A1
!endif
!ifndef HTCAPTION
  !define HTCAPTION 2
!endif
!define SWP_NOMOVE     0x0002
!define SWP_NOSIZE     0x0001
!define SWP_NOZORDER   0x0004
!define SWP_NOACTIVATE 0x0010
!define SWP_FRAMECHANGED 0x0020

!ifndef EM_SETREADONLY
  !define EM_SETREADONLY 0x00CF
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
Var PassiveMode
Var UpdateMode
Var NoShortcutMode
Var hFontTitle
Var hFontBody
Var hFontSmall
Var hFontTiny
Var hFontBtn
Var hProgressStatus
Var hProgressBar
Var hProgressFill
Var hNextBtn
Var hPrevBtn
Var hNextBmp
Var hPrevBmp
Var InstallStage
Var InstallDone
Var CurPage

Name "奶昔 · 桌面智能体"
BrandingText " "
OutFile "${OUTFILE}"
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

; ── 无边框自定义窗口 ──
!macro MakeBorderless
  System::Call "user32::SetWindowLong(i $HWNDPARENT, i ${GWL_STYLE}, i 0x92000000)"
  System::Call "user32::SetWindowLong(i $HWNDPARENT, i ${GWL_EXSTYLE}, i 0)"
  System::Call "user32::GetSystemMetrics(i 0) i .r0"
  System::Call "user32::GetSystemMetrics(i 1) i .r1"
  IntOp $2 $0 - ${WIN_W}
  IntOp $2 $2 / 2
  IntOp $3 $1 - ${WIN_H}
  IntOp $3 $3 / 2
  System::Call "user32::SetWindowPos(i $HWNDPARENT, i 0, i r2, i r3, i ${WIN_W}, i ${WIN_H}, i 0x34)"
  System::Call "gdi32::CreateRoundRectRgn(i 0, i 0, i ${WIN_W}, i ${WIN_H}, i 12, i 12) i .r0"
  System::Call "user32::SetWindowRgn(i $HWNDPARENT, i r0, i 1)"
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

; ── 位图按钮：底层位图显示 + 顶层透明 Label 点击区（SS_BITMAP 不发 STN_CLICKED，点击由 Label 接管）──
!macro BitmapBtn X Y W H BMP HANDLER OUTVAR_BMP OUTVAR_CLICK
  ${NSD_CreateBitmap} ${X} ${Y} ${W} ${H} ""
  Pop ${OUTVAR_BMP}
  ${NSD_SetBitmap} ${OUTVAR_BMP} "${BMP}" $R0
  ${NSD_CreateLabel} ${X} ${Y} ${W} ${H} ""
  Pop ${OUTVAR_CLICK}
  SetCtlColors ${OUTVAR_CLICK} "${CLR_BG}" ""
  !insertmacro AddNotify ${OUTVAR_CLICK}
  ${NSD_OnClick} ${OUTVAR_CLICK} ${HANDLER}
  System::Call "user32::SetWindowPos(i ${OUTVAR_CLICK}, i 0, i 0, i 0, i 0, i 0, i 0x0003)"
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
!macro ShowBanner
  ${NSD_CreateBitmap} 0 0 ${WIN_W} ${BANNER_H} ""
  Pop $hBanner
  ${NSD_SetBitmap} $hBanner "$PLUGINSDIR\banner.bmp" $hBmpHandle
  ${NSD_OnClick} $hBanner fn_DragTitle

  ; 右上角最小化按钮（透明蒙版 + 字形 —，深灰字）
  ${NSD_CreateLabel} 478 6 28 24 "—"
  Pop $0
  SetCtlColors $0 "${CLR_CLOSE}" ""
  !insertmacro ApplyFont $0 $hFontBtn
  !insertmacro CenterLabel $0
  !insertmacro AddNotify $0
  ${NSD_OnClick} $0 fn_Minimize

  ; 右上角关闭按钮（透明蒙版 + 字形 ×，深灰字）
  ${NSD_CreateLabel} 506 6 28 24 "×"
  Pop $0
  SetCtlColors $0 "${CLR_CLOSE}" ""
  !insertmacro ApplyFont $0 $hFontBtn
  !insertmacro CenterLabel $0
  !insertmacro AddNotify $0
  ${NSD_OnClick} $0 fn_Close
!macroend

!macro CreateStep IDX ACTIVE X LABEL
  ; 数字圆点（20x20，激活粉底白字 / 未激活浅粉底白字），匹配 mockup .step .num
  ${NSD_CreateBitmap} ${X} 388 20 20 ""
  Pop $8
  ${If} ${ACTIVE} >= ${IDX}
    ${NSD_SetBitmap} $8 "$PLUGINSDIR\num${IDX}_on.bmp" $9
  ${Else}
    ${NSD_SetBitmap} $8 "$PLUGINSDIR\num${IDX}_off.bmp" $9
  ${EndIf}

  IntOp $9 ${X} + 26
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
!macro CreateFooter ACTIVE NEXT_BMP SHOW_PREV NEXT_ENABLED
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
  !insertmacro BitmapBtn 320 384 90 30 "$PLUGINSDIR\btn_prev.bmp" fn_PrevClick $hPrevBmp $hPrevBtn
  ${If} ${SHOW_PREV} == 0
    ShowWindow $hPrevBtn 0
    ShowWindow $hPrevBmp 0
  ${EndIf}

  !insertmacro BitmapBtn 414 384 90 30 "${NEXT_BMP}" fn_NextClick $hNextBmp $hNextBtn
  ${If} ${NEXT_ENABLED} == 0
    EnableWindow $hNextBtn 0
  ${EndIf}
!macroend

; ─── 进入 GUI 即把默认窗口改为无边框自定义窗口 ───
Function .onGUIInit
  !insertmacro MakeBorderless
FunctionEnd

Function fn_DragTitle
  SendMessage $HWNDPARENT ${WM_NCLBUTTONDOWN} ${HTCAPTION} 0
FunctionEnd

Function fn_Close
  SendMessage $HWNDPARENT ${WM_CLOSE} 0 0
FunctionEnd

Function fn_Minimize
  ShowWindow $HWNDPARENT 6
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
  !insertmacro MakeBorderless
  !insertmacro FillPage
  !insertmacro HideWizardChrome
  SetCtlColors $Dialog "" "${CLR_BG}"

  !insertmacro ShowBanner

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

  !insertmacro CreateFooter 1 "$PLUGINSDIR\btn_next.bmp" 0 1

  ${NSD_FreeBitmap} $hBanner
  nsDialogs::Show
FunctionEnd

; ─── Page 2: Directory ───
Page custom fn_DirPage fn_DirPageLeave

Function fn_DirPage
  nsDialogs::Create 1018
  Pop $Dialog
  StrCpy $CurPage 2
  !insertmacro MakeBorderless
  !insertmacro FillPage
  !insertmacro HideWizardChrome
  SetCtlColors $Dialog "" "${CLR_BG}"

  !insertmacro ShowBanner

  ${NSD_CreateLabel} 30 ${CONTENT_TOP} 480 28 "选择安装位置"
  Pop $0
  SetCtlColors $0 "${CLR_DARK_PINK}" "${CLR_BG}"
  !insertmacro ApplyFont $0 $hFontTitle

  ; 输入框边框
  ${NSD_CreateLabel} 29 209 382 30 ""
  Pop $0
  SetCtlColors $0 "${CLR_BORDER}" "${CLR_BORDER}"

  ; 路径输入框（只读）
  ${NSD_CreateText} 30 210 380 28 "$INSTDIR"
  Pop $InstallPathText
  !insertmacro FlatEdit $InstallPathText
  SetCtlColors $InstallPathText "${CLR_INPUT_TEXT}" "${CLR_INPUT_BG}"
  !insertmacro ApplyFont $InstallPathText $hFontBody
  SendMessage $InstallPathText ${EM_SETREADONLY} 1 0

  ; 浏览按钮（次级：浅粉底深粉字，90x28）
  !insertmacro BitmapBtn 420 210 90 28 "$PLUGINSDIR\btn_browse.bmp" fn_Browse $R8 $R9

  ${NSD_CreateLabel} 30 252 480 18 ""
  Pop $0
  SetCtlColors $0 "${CLR_TEXT_MUTED}" "${CLR_BG}"
  !insertmacro ApplyFont $0 $hFontTiny
  System::Call "user32::SetWindowText(i $0, t '所需磁盘空间：约 ${ESTIMATEDSIZE} MB | 可用空间：58.2 GB')"

  !insertmacro CreateFooter 2 "$PLUGINSDIR\btn_install.bmp" 1 1

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
FunctionEnd

; ─── Page 3: Progress ───
Page custom fn_ProgressPage fn_ProgressPageLeave

Function fn_ProgressPage
  nsDialogs::Create 1018
  Pop $Dialog
  StrCpy $CurPage 3
  !insertmacro MakeBorderless
  !insertmacro FillPage
  !insertmacro HideWizardChrome
  SetCtlColors $Dialog "" "${CLR_BG}"

  !insertmacro ShowBanner

  ${NSD_CreateLabel} 30 ${CONTENT_TOP} 480 28 "正在安装"
  Pop $0
  SetCtlColors $0 "${CLR_DARK_PINK}" "${CLR_BG}"
  !insertmacro ApplyFont $0 $hFontTitle

  ${NSD_CreateLabel} 30 210 480 20 "稍等一下，正在把奶昔搬到你电脑上..."
  Pop $0
  SetCtlColors $0 "${CLR_TEXT_BODY}" "${CLR_BG}"
  !insertmacro ApplyFont $0 $hFontBody

  ; 进度条背景（浅粉色）
  ${NSD_CreateLabel} 30 246 480 8 ""
  Pop $hProgressBar
  SetCtlColors $hProgressBar "${CLR_LIGHT_PINK}" "${CLR_LIGHT_PINK}"
  ; 进度条填充（粉色），初始宽度 0
  ${NSD_CreateLabel} 30 246 0 8 ""
  Pop $hProgressFill
  SetCtlColors $hProgressFill "${CLR_PINK}" "${CLR_PINK}"

  ${NSD_CreateLabel} 30 260 480 18 ""
  Pop $hProgressStatus
  SetCtlColors $hProgressStatus "${CLR_TEXT_MUTED}" "${CLR_BG}"
  !insertmacro ApplyFont $hProgressStatus $hFontTiny

  !insertmacro CreateFooter 3 "$PLUGINSDIR\btn_installing.bmp" 1 0

  StrCpy $InstallDone 0
  StrCpy $InstallStage 0
  ${NSD_CreateTimer} fn_InstallTick 100

  ${NSD_FreeBitmap} $hBanner
  nsDialogs::Show
FunctionEnd

!macro SetProgressWidth PERCENT
  IntOp $R0 ${PERCENT} * 480
  IntOp $R0 $R0 / 100
  System::Call "user32::SetWindowPos(i $hProgressFill, i 0, i 30, i 246, i r0, i 8, i 0x0014)"
!macroend

Function fn_InstallTick
  ${If} $InstallDone == 1
    Return
  ${EndIf}
  Call fn_DoInstall
  ${If} $InstallDone == 1
    ${NSD_KillTimer} fn_InstallTick
  ${Else}
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
  !insertmacro MakeBorderless
  !insertmacro FillPage
  !insertmacro HideWizardChrome
  SetCtlColors $Dialog "" "${CLR_BG}"

  !insertmacro ShowBanner

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

  !insertmacro CreateFooter 4 "$PLUGINSDIR\btn_finish.bmp" 1 1

  ${NSD_FreeBitmap} $hBanner
  nsDialogs::Show
FunctionEnd

Function fn_Done
  ${NSD_GetState} $DesktopCheck $0
  ${If} $0 = ${BST_CHECKED}
    CreateShortcut "$DESKTOP\奶昔.lnk" "$INSTDIR\${MAINBINARYNAME}.exe" "" "$INSTDIR\${MAINBINARYNAME}.exe" 0
  ${EndIf}
  ${NSD_GetState} $RunCheck $0
  ${If} $0 = ${BST_CHECKED}
    nsis_tauri_utils::RunAsUser "$INSTDIR\${MAINBINARYNAME}.exe" ""
  ${EndIf}
  Quit
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

; ════════════════════════════════════════════
; Sections (install logic)
; ════════════════════════════════════════════

Section "Main" SEC01
SectionEnd

Function fn_DoInstall
  ${If} $InstallStage == 0
    ${NSD_SetText} $hProgressStatus "准备安装..."
    !insertmacro SetProgressWidth 8
    SetOutPath $INSTDIR
    !ifmacrodef NSIS_HOOK_PREINSTALL
      !insertmacro NSIS_HOOK_PREINSTALL
    !endif
    !insertmacro CheckIfAppIsRunning "${MAINBINARYNAME}.exe" "${PRODUCTNAME}"
    IntOp $InstallStage $InstallStage + 1
    Return
  ${EndIf}
  ${If} $InstallStage == 1
    ${NSD_SetText} $hProgressStatus "写入主程序..."
    !insertmacro SetProgressWidth 25
    File "${MAINBINARYSRCPATH}"
    IntOp $InstallStage $InstallStage + 1
    Return
  ${EndIf}
  ${If} $InstallStage == 2
    ${NSD_SetText} $hProgressStatus "创建资源目录..."
    !insertmacro SetProgressWidth 40
    {{#each resources_dirs}}
      CreateDirectory "$INSTDIR\\{{this}}"
    {{/each}}
    ${NSD_SetText} $hProgressStatus "写入资源文件..."
    !insertmacro SetProgressWidth 55
    {{#each resources}}
      File /a "/oname={{this.[1]}}" "{{no-escape @key}}"
    {{/each}}
    IntOp $InstallStage $InstallStage + 1
    Return
  ${EndIf}
  ${If} $InstallStage == 3
    ${NSD_SetText} $hProgressStatus "写入依赖文件..."
    !insertmacro SetProgressWidth 70
    {{#each binaries}}
      File /a "/oname={{this}}" "{{no-escape @key}}"
    {{/each}}
    IntOp $InstallStage $InstallStage + 1
    Return
  ${EndIf}
  ${If} $InstallStage == 4
    ${NSD_SetText} $hProgressStatus "写入卸载程序..."
    !insertmacro SetProgressWidth 82
    WriteUninstaller "$INSTDIR\uninstall.exe"
    IntOp $InstallStage $InstallStage + 1
    Return
  ${EndIf}
  ${If} $InstallStage == 5
    ${NSD_SetText} $hProgressStatus "注册安装信息..."
    !insertmacro SetProgressWidth 90
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
    IntOp $InstallStage $InstallStage + 1
    Return
  ${EndIf}
  ; 最后阶段：创建快捷方式并收尾
  ${NSD_SetText} $hProgressStatus "创建快捷方式..."
  !insertmacro SetProgressWidth 100
  CreateDirectory "$SMPROGRAMS\${PRODUCTNAME}"
  CreateShortcut "$SMPROGRAMS\${PRODUCTNAME}\奶昔.lnk" "$INSTDIR\${MAINBINARYNAME}.exe" "" "$INSTDIR\${MAINBINARYNAME}.exe" 0
  ; WebView2 检测
  ${If} ${RunningX64}
    ReadRegStr $4 HKLM "SOFTWARE\WOW6432Node\Microsoft\EdgeUpdate\Clients\${WEBVIEW2APPGUID}" "pv"
  ${Else}
    ReadRegStr $4 HKLM "SOFTWARE\Microsoft\EdgeUpdate\Clients\${WEBVIEW2APPGUID}" "pv"
  ${EndIf}
  ${If} $4 == ""
    ReadRegStr $4 HKCU "SOFTWARE\Microsoft\EdgeUpdate\Clients\${WEBVIEW2APPGUID}" "pv"
  ${EndIf}
  !ifmacrodef NSIS_HOOK_POSTINSTALL
    !insertmacro NSIS_HOOK_POSTINSTALL
  !endif
  StrCpy $InstallDone 1
  ${NSD_SetBitmap} $hNextBmp "$PLUGINSDIR\btn_finish.bmp" $R0
  ${NSD_SetText} $hProgressStatus "安装完成。"
  EnableWindow $hNextBtn 1
FunctionEnd

Section Uninstall
  !insertmacro CheckIfAppIsRunning "${MAINBINARYNAME}.exe" "${PRODUCTNAME}"
  Delete "$INSTDIR\${MAINBINARYNAME}.exe"
  {{#each resources}}
    Delete "$INSTDIR\\{{this.[1]}}"
  {{/each}}
  {{#each binaries}}
    Delete "$INSTDIR\\{{this}}"
  {{/each}}
  Delete "$INSTDIR\uninstall.exe"
  RMDir "$INSTDIR"
  Delete "$SMPROGRAMS\${PRODUCTNAME}\奶昔.lnk"
  RMDir "$SMPROGRAMS\${PRODUCTNAME}"
  Delete "$DESKTOP\奶昔.lnk"
  DeleteRegKey SHCTX "${UNINSTKEY}"
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

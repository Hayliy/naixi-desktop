Unicode true
ManifestDPIAware true

!include LogicLib.nsh
!include nsDialogs.nsh
!include WinMessages.nsh
!include FileFunc.nsh
!include x64.nsh

LoadLanguageFile "${NSISDIR}\Contrib\Language files\SimpChinese.nlf"

; ── 窗口尺寸（与 mockup.html 一致）──
!define WIN_W   540
!define WIN_H   430
!define BANNER_H 150
!define FOOTER_H 62
!define FOOTER_TOP 368
!define CONTENT_TOP 168

; ── 颜色（NSIS SetCtlColors 使用 RGB；GDI SendMessage 使用 BGR）──
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

!define CLR_PINK_GDI       0x7E53D4       ; #D4537E 的 BGR
!define CLR_LIGHT_PINK_GDI 0xD1C0F4       ; #F4C0D1 的 BGR

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

!ifndef PBM_SETBARCOLOR
  !define PBM_SETBARCOLOR 0x0409
!endif
!ifndef PBM_SETBKCOLOR
  !define PBM_SETBKCOLOR 0x0413
!endif
!ifndef EM_SETREADONLY
  !define EM_SETREADONLY 0x00CF
!endif

Var Dialog
Var hBanner
Var hBmpBanner
Var hFontTitle
Var hFontBody
Var hFontSmall
Var hFontTiny
Var hFontBtn
Var InstallPathText
Var hProgressStatus
Var hProgressBar
Var hProgressFill
Var hNextBtn
Var hNextBmp
Var hPrevBtn
Var hPrevBmp
Var hMinBmp
Var hMinBtn
Var RunCheck
Var DesktopCheck
Var InstallDone
Var CurPage
Var StartMs

Name "奶昔 · 桌面智能体"
BrandingText " "
OutFile "test_flow.exe"
InstallDir "$LOCALAPPDATA\奶昔"
RequestExecutionLevel user

!macro ApplyFont HWND FONT
  SendMessage ${HWND} ${WM_SETFONT} ${FONT} 1
!macroend

!macro CenterLabel HWND
  Push $1
  System::Call "user32::GetWindowLong(i ${HWND}, i ${GWL_STYLE}) i .r1"
  IntOp $1 $1 | 0x00000201
  System::Call "user32::SetWindowLong(i ${HWND}, i ${GWL_STYLE}, i r1)"
  System::Call "user32::SetWindowPos(i ${HWND}, i 0, i 0, i 0, i 0, i 0, i 0x0027)"
  Pop $1
!macroend

; 左对齐 + 垂直居中（用于地址输入框文字，匹配 mockup input 左对齐）
!macro LeftVCenter HWND
  Push $1
  System::Call "user32::GetWindowLong(i ${HWND}, i ${GWL_STYLE}) i .r1"
  IntOp $1 $1 | 0x00000200
  System::Call "user32::SetWindowLong(i ${HWND}, i ${GWL_STYLE}, i r1)"
  System::Call "user32::SetWindowPos(i ${HWND}, i 0, i 0, i 0, i 0, i 0, i 0x0027)"
  Pop $1
!macroend

; 给 Static / Bitmap 控件加上 SS_NOTIFY，确保鼠标点击能触发 NSD_OnClick
!macro AddNotify HWND
  Push $1
  System::Call "user32::GetWindowLong(i ${HWND}, i ${GWL_STYLE}) i .r1"
  IntOp $1 $1 | 0x00000100
  System::Call "user32::SetWindowLong(i ${HWND}, i ${GWL_STYLE}, i r1)"
  System::Call "user32::SetWindowPos(i ${HWND}, i 0, i 0, i 0, i 0, i 0, i 0x0027)"
  Pop $1
!macroend

; 调试/验证用：点击/计时事件中写入标记文件，便于客观确认是否真正到达 handler
!macro LogEvent MSG
  FileOpen $R9 "$TEMP\naixi_installer_ev.log" a
  FileWrite $R9 "${MSG}\r\n"
  FileClose $R9
!macroend

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
  ; 圆角窗口
  System::Call "gdi32::CreateRoundRectRgn(i 0, i 0, i ${WIN_W}, i ${WIN_H}, i 12, i 12) i .r0"
  System::Call "user32::SetWindowRgn(i $HWNDPARENT, i r0, i 1)"
!macroend

!macro HideWizardChrome
  GetDlgItem $0 $HWNDPARENT 1
  ShowWindow $0 0
  GetDlgItem $0 $HWNDPARENT 2
  ShowWindow $0 0
  GetDlgItem $0 $HWNDPARENT 3
  ShowWindow $0 0
  GetDlgItem $0 $HWNDPARENT 65535
  ${If} $0 != 0
    ShowWindow $0 0
  ${EndIf}
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

!macro FillPage
  System::Call "user32::SetWindowPos(i $Dialog, i 0, i 0, i 0, i ${WIN_W}, i ${WIN_H}, i 0x14)"
!macroend

!macro AdvanceNext
  GetDlgItem $0 $HWNDPARENT 1
  SendMessage $HWNDPARENT ${WM_COMMAND} 1 $0
!macroend

!macro AdvanceBack
  GetDlgItem $0 $HWNDPARENT 3
  SendMessage $HWNDPARENT ${WM_COMMAND} 3 $0
!macroend

; 扁平化系统 Edit：去掉下沉边框
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

; 位图按钮：位图控件直接显示 + 直接接收点击（测试 nsDialogs 子类化）
!macro BitmapBtn X Y W H BMP HANDLER OUTVAR_BMP OUTVAR_CLICK
  ${NSD_CreateBitmap} ${X} ${Y} ${W} ${H} ""
  Pop ${OUTVAR_BMP}
  ${NSD_SetBitmap} ${OUTVAR_BMP} "${BMP}" $R0
  !insertmacro AddNotify ${OUTVAR_BMP}
  ${NSD_OnClick} ${OUTVAR_BMP} ${HANDLER}
  System::Call "user32::SetWindowPos(i ${OUTVAR_BMP}, i 0, i 0, i 0, i 0, i 0, i 0x0003)"
  StrCpy ${OUTVAR_CLICK} ${OUTVAR_BMP}
!macroend

; 透明点击区：用于 banner 右上角已绘制好的最小化/关闭按钮（真正透明，不擦除背景）
!macro ClickArea X Y W H HANDLER OUTVAR
  ${NSD_CreateLabel} ${X} ${Y} ${W} ${H} ""
  Pop ${OUTVAR}
  SetCtlColors ${OUTVAR} "${CLR_BG}" ""
  !insertmacro AddNotify ${OUTVAR}
  ${NSD_OnClick} ${OUTVAR} ${HANDLER}
  System::Call "user32::GetWindowLong(i ${OUTVAR}, i ${GWL_EXSTYLE}) i .r0"
  IntOp $0 $0 | 0x00000020  ; WS_EX_TRANSPARENT
  System::Call "user32::SetWindowLong(i ${OUTVAR}, i ${GWL_EXSTYLE}, i r0)"
  System::Call "user32::SetWindowPos(i ${OUTVAR}, i 0, i 0, i 0, i 0, i 0, i 0x0043)"  ; SWP_NOMOVE|NOSIZE|NOZORDER|FRAMECHANGED
!macroend

!macro ShowBanner
  ${NSD_CreateBitmap} 0 0 ${WIN_W} ${BANNER_H} ""
  Pop $hBanner
  ${NSD_SetBitmap} $hBanner "$PLUGINSDIR\banner.bmp" $hBmpBanner
  !insertmacro AddNotify $hBanner
  ${NSD_OnClick} $hBanner fn_BannerClick

  ; 右上角 最小化/关闭 作为独立位图按钮叠加在 banner 上（位图+NSD_OnClick 已验证可用）
  !insertmacro BitmapBtn 478 6 28 24 "$PLUGINSDIR\btn_min.bmp" fn_Minimize $hMinBmp $hMinBtn
  !insertmacro BitmapBtn 506 6 28 24 "$PLUGINSDIR\btn_close.bmp" fn_Close $hMinBmp $hMinBtn
!macroend

; ACTIVE: 当前激活的步骤编号（1-4）
; NEXT_BMP: 右侧主按钮位图文件名（如 btn_next.bmp）
; SHOW_PREV: 是否显示上一步（0 隐藏，1 显示）
; NEXT_ENABLED: 是否启用主按钮（0 禁用，1 启用）
!macro CreateFooter ACTIVE NEXT_BMP SHOW_PREV NEXT_ENABLED
  ; footer 背景
  ${NSD_CreateLabel} 0 ${FOOTER_TOP} ${WIN_W} ${FOOTER_H} ""
  Pop $0
  SetCtlColors $0 "${CLR_FOOTER_BG}" "${CLR_FOOTER_BG}"

  ; 顶部分隔线（1px 浅粉）
  ${NSD_CreateLabel} 0 ${FOOTER_TOP} ${WIN_W} 1 ""
  Pop $0
  SetCtlColors $0 "${CLR_LIGHT_PINK}" "${CLR_LIGHT_PINK}"

  ; 步骤指示器（圆形数字 1-4）
  !insertmacro CreateStep 1 ${ACTIVE} 30  "欢迎"
  !insertmacro CreateStep 2 ${ACTIVE} 100 "位置"
  !insertmacro CreateStep 3 ${ACTIVE} 170 "安装"
  !insertmacro CreateStep 4 ${ACTIVE} 240 "完成"

  ; 导航按钮（统一 90x30，底层位图 + 顶层透明点击区）
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

Function .onGUIInit
  !insertmacro MakeBorderless
FunctionEnd

Function fn_Minimize
  !insertmacro LogEvent "min"
  ShowWindow $HWNDPARENT 6
FunctionEnd

Function fn_Close
  !insertmacro LogEvent "close"
  SendMessage $HWNDPARENT ${WM_CLOSE} 0 0
FunctionEnd

Function fn_BannerClick
  ; banner 其余区域拖动窗口
  SendMessage $HWNDPARENT ${WM_NCLBUTTONDOWN} ${HTCAPTION} 0
FunctionEnd

Function fn_NextClick
  !insertmacro LogEvent "next"
  ${If} $CurPage == 4
    Call fn_FinishClick
  ${Else}
    !insertmacro AdvanceNext
  ${EndIf}
FunctionEnd

Function fn_PrevClick
  !insertmacro LogEvent "prev"
  !insertmacro AdvanceBack
FunctionEnd

; ═══════════════════════════════════════════════════════════
; 第 1 页：欢迎
; ═══════════════════════════════════════════════════════════
Page custom fn_Welcome

Function fn_Welcome
  nsDialogs::Create 1018
  Pop $Dialog
  StrCpy $CurPage 1
  !insertmacro HideWizardChrome
  !insertmacro FillPage
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

; ═══════════════════════════════════════════════════════════
; 第 2 页：选择安装位置
; ═══════════════════════════════════════════════════════════
Page custom fn_DirPage fn_DirPageLeave

Function fn_DirPage
  nsDialogs::Create 1018
  Pop $Dialog
  StrCpy $CurPage 2
  !insertmacro HideWizardChrome
  !insertmacro FillPage
  SetCtlColors $Dialog "" "${CLR_BG}"

  !insertmacro ShowBanner

  ${NSD_CreateLabel} 30 ${CONTENT_TOP} 480 28 "选择安装位置"
  Pop $0
  SetCtlColors $0 "${CLR_DARK_PINK}" "${CLR_BG}"
  !insertmacro ApplyFont $0 $hFontTitle

  ; 地址输入框：圆角边框位图（1px #D3C1D0 + 圆角 5px + 内部 #FDF8FA），匹配 mockup .path-row input
  ${NSD_CreateBitmap} 29 209 382 32 ""
  Pop $0
  ${NSD_SetBitmap} $0 "$PLUGINSDIR\addr_border.bmp" $R0

  ; 路径显示框（左对齐，12px，#444，背景 #FDF8FA，左侧留 10px padding 匹配 mockup）
  ${NSD_CreateLabel} 40 210 360 30 "$INSTDIR"
  Pop $InstallPathText
  SetCtlColors $InstallPathText "${CLR_INPUT_TEXT}" "${CLR_INPUT_BG}"
  !insertmacro ApplyFont $InstallPathText $hFontSmall
  !insertmacro LeftVCenter $InstallPathText

  ; 浏览按钮
  !insertmacro BitmapBtn 420 210 90 28 "$PLUGINSDIR\btn_browse.bmp" fn_Browse $0 $0

  ; 磁盘空间信息
  ${NSD_CreateLabel} 30 252 480 18 ""
  Pop $0
  SetCtlColors $0 "${CLR_TEXT_MUTED}" "${CLR_BG}"
  !insertmacro ApplyFont $0 $hFontTiny
  System::Call "user32::SetWindowText(i $0, t '所需磁盘空间：约 420 MB | 可用空间：58.2 GB')"

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

; ═══════════════════════════════════════════════════════════
; 第 3 页：安装进度
; ═══════════════════════════════════════════════════════════
Page custom fn_ProgressPage fn_ProgressPageLeave

Function fn_ProgressPage
  nsDialogs::Create 1018
  Pop $Dialog
  StrCpy $CurPage 3
  !insertmacro HideWizardChrome
  !insertmacro FillPage
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

  ; 进度条轨道（浅粉 #F4C0D1，匹配 mockup .progress-bar 背景）
  ${NSD_CreateLabel} 30 246 480 8 ""
  Pop $hProgressBar
  SetCtlColors $hProgressBar "${CLR_LIGHT_PINK}" "${CLR_LIGHT_PINK}"
  ; 进度条填充（粉色 #D4537E），初始宽度 0，按时钟门控平滑增长
  ${NSD_CreateLabel} 30 246 0 8 ""
  Pop $hProgressFill
  SetCtlColors $hProgressFill "${CLR_PINK}" "${CLR_PINK}"
  ; 诊断：固定半宽，确认填充可见
  System::Call "user32::SetWindowPos(i $hProgressFill, i 0, i 30, i 246, i 240, i 8, i 0x0010)"

  ${NSD_CreateLabel} 30 260 480 18 ""
  Pop $hProgressStatus
  SetCtlColors $hProgressStatus "${CLR_TEXT_MUTED}" "${CLR_BG}"
  !insertmacro ApplyFont $hProgressStatus $hFontTiny

  !insertmacro CreateFooter 3 "$PLUGINSDIR\btn_installing.bmp" 1 0

  StrCpy $InstallDone 0
  StrCpy $StartMs 0
  ${NSD_CreateTimer} fn_InstallTick 30

  ${NSD_FreeBitmap} $hBanner
  nsDialogs::Show
FunctionEnd

!macro SetProgressWidth PERCENT
  IntOp $R0 ${PERCENT} * 480
  IntOp $R0 $R0 / 100
  System::Call "user32::SetWindowPos(i $hProgressFill, i 0, i 30, i 246, i r0, i 8, i 0x0014)"
  System::Call "user32::RedrawWindow(i $hProgressFill, i 0, i 0, i 0x0101)"
!macroend

Function fn_InstallTick
  ; 时钟门控：本机 nsDialogs 定时器间隔近似 0（持续高频触发），
  ; 不能用「每 tick 推进一步」否则进度条瞬间跑满。改为按真实流逝毫秒计算百分比，
  ; 总时长 3 秒，进度条从 0 平滑增长到 100%。
  ${If} $StartMs == 0
    System::Call "kernel32::GetTickCount() i .r0"
    StrCpy $StartMs $0
  ${EndIf}
  System::Call "kernel32::GetTickCount() i .r0"
  IntOp $1 $0 - $StartMs            ; 已流逝毫秒
  IntOp $2 $1 * 100
  IntOp $2 $2 / 3000                ; 百分比（总时长 3 秒）
  ${If} $2 > 100
    StrCpy $2 100
  ${EndIf}

  ${If} $2 < 12
    ${NSD_SetText} $hProgressStatus "正在准备安装..."
  ${ElseIf} $2 < 70
    ${NSD_SetText} $hProgressStatus "正在解压资源文件... $2%"
  ${ElseIf} $2 < 95
    ${NSD_SetText} $hProgressStatus "正在写入配置文件... $2%"
  ${Else}
    ; 收尾（仅执行一次）：写入安装标记与卸载程序
    SetOutPath "$INSTDIR"
    FileOpen $R0 "$INSTDIR\installed.txt" w
    FileWrite $R0 "ok"
    FileClose $R0
    WriteUninstaller "$INSTDIR\uninstall.exe"
    ${NSD_SetText} $hProgressStatus "安装完成... 100%"
    !insertmacro SetProgressWidth 100
    StrCpy $InstallDone 1
    ${NSD_SetBitmap} $hNextBmp "$PLUGINSDIR\btn_finish.bmp" $R0
    EnableWindow $hNextBtn 1
    ${NSD_KillTimer} fn_InstallTick
    Return
  ${EndIf}

  !insertmacro SetProgressWidth $2
FunctionEnd

Function fn_ProgressPageLeave
  ${If} $InstallDone != 1
    Abort
  ${EndIf}
FunctionEnd

; ═══════════════════════════════════════════════════════════
; 第 4 页：安装完成
; ═══════════════════════════════════════════════════════════
Page custom fn_Finish

Function fn_Finish
  nsDialogs::Create 1018
  Pop $Dialog
  StrCpy $CurPage 4
  !insertmacro HideWizardChrome
  !insertmacro FillPage
  SetCtlColors $Dialog "" "${CLR_BG}"

  !insertmacro ShowBanner

  ${NSD_CreateLabel} 30 ${CONTENT_TOP} 480 28 "安装完成"
  Pop $0
  SetCtlColors $0 "${CLR_DARK_PINK}" "${CLR_BG}"
  !insertmacro ApplyFont $0 $hFontTitle

  ${NSD_CreateLabel} 30 210 480 20 "奶昔 · 桌面智能体 v0.1.0 已经安装完成。"
  Pop $0
  SetCtlColors $0 "${CLR_TEXT_BODY}" "${CLR_BG}"
  !insertmacro ApplyFont $0 $hFontBody

  ${NSD_CreateCheckBox} 30 250 480 18 ""
  Pop $RunCheck
  SendMessage $RunCheck ${BM_SETCHECK} ${BST_CHECKED} 0
  SendMessage $RunCheck ${WM_SETTEXT} 0 "STR:立即运行奶昔"
  SetCtlColors $RunCheck "0x555555" "${CLR_BG}"
  !insertmacro ApplyFont $RunCheck $hFontBody

  ${NSD_CreateCheckBox} 30 282 480 18 ""
  Pop $DesktopCheck
  SendMessage $DesktopCheck ${BM_SETCHECK} ${BST_CHECKED} 0
  SendMessage $DesktopCheck ${WM_SETTEXT} 0 "STR:创建桌面快捷方式"
  SetCtlColors $DesktopCheck "0x555555" "${CLR_BG}"
  !insertmacro ApplyFont $DesktopCheck $hFontBody

  !insertmacro CreateFooter 4 "$PLUGINSDIR\btn_finish.bmp" 1 1

  ${NSD_FreeBitmap} $hBanner
  nsDialogs::Show
FunctionEnd

Function fn_FinishClick
  ${NSD_GetState} $DesktopCheck $0
  ${If} $0 = ${BST_CHECKED}
    ; 快捷方式名称固定为「奶昔」，图标复用安装目录内的主程序图标
    CreateShortcut "$DESKTOP\奶昔.lnk" "$INSTDIR\奶昔.exe" "" "$INSTDIR\奶昔.exe" 0
  ${EndIf}
  ${NSD_GetState} $RunCheck $0
  ${If} $0 = ${BST_CHECKED}
    ExecShell "" "$INSTDIR\奶昔.exe"
  ${EndIf}
  Quit
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
FunctionEnd

Section "Main" SEC01
SectionEnd

Section Uninstall
  Delete "$INSTDIR\installed.txt"
  Delete "$INSTDIR\uninstall.exe"
  RMDir "$INSTDIR"
SectionEnd

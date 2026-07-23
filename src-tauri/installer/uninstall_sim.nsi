Unicode true
ManifestDPIAware true
ManifestDPIAwareness PerMonitorV2

!include LogicLib.nsh
!include nsDialogs.nsh
!include WinMessages.nsh

; 默认简体中文
LoadLanguageFile "${NSISDIR}\Contrib\Language files\SimpChinese.nlf"

; ── 窗口尺寸（与 test_flow.nsi / mockup 一致）──
!define WIN_W   540
!define WIN_H   430
!define BANNER_H 150
!define FOOTER_H 62
!define FOOTER_TOP 368
!define CONTENT_TOP 168

; ── 颜色（SetCtlColors 用 RGB；GDI SendMessage 用 BGR）──
!define CLR_PINK        0xD4537E
!define CLR_LIGHT_PINK  0xF4C0D1
!define CLR_DARK_PINK   0x72243E
!define CLR_FOOTER_BG   0xFDF8FA
!define CLR_BG          0xFFFFFF
!define CLR_TEXT_BODY   0x666666
!define CLR_TEXT_MUTED  0x888888
!define CLR_TEXT_STEP   0xAAAAAA
!define CLR_INPUT_BG    0xFDF8FA
!define CLR_INPUT_TEXT  0x444444
!define CLR_CLOSE       0x555555

!define CLR_PINK_GDI       0x7E53D4
!define CLR_LIGHT_PINK_GDI 0xD1C0F4

!ifndef WM_NCLBUTTONDOWN
  !define WM_NCLBUTTONDOWN 0x00A1
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
!ifndef EM_SETREADONLY
  !define EM_SETREADONLY 0x00CF
!endif

; Variables
Var Dialog
Var hBanner
Var hBmpHandle
Var hFontTitle
Var hFontBody
Var hFontSmall
Var hFontTiny
Var hFontBtn
Var hProgressFill
Var hNextBtn
Var hPrevBtn
Var hNextBmp
Var hPrevBmp
Var hMinBmp
Var hMinBtn
Var hCloseBmp
Var hCloseBtn
Var hFooterBg
Var hStepTxt1
Var hStepTxt2
Var hStepTxt3
Var unCurPage
Var unInstallDone
Var unDeleteData
Var unDeleteChk
Var unProgStatus
Var unProg

Name "奶昔 · 桌面智能体"
BrandingText " "
OutFile "D:\naixi_desktop\src-tauri\installer\uninstall_sim.exe"
Icon "D:\naixi_desktop\src-tauri\icons\icon.ico"
RequestExecutionLevel user

!macro ApplyFont HWND FONT
  SendMessage ${HWND} ${WM_SETFONT} ${FONT} 1
!macroend

!macro AddNotify HWND
  Push $1
  System::Call "user32::GetWindowLong(i ${HWND}, i ${GWL_STYLE}) i .r1"
  IntOp $1 $1 | 0x00000100
  System::Call "user32::SetWindowLong(i ${HWND}, i ${GWL_STYLE}, i r1)"
  System::Call "user32::SetWindowPos(i ${HWND}, i 0, i 0, i 0, i 0, i 0, i 0x0027)"
  Pop $1
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

!macro BitmapBtn X Y W H BMP HANDLER OUTVAR_BMP OUTVAR_CLICK
  ${NSD_CreateBitmap} ${X} ${Y} ${W} ${H} ""
  Pop ${OUTVAR_BMP}
  ${NSD_SetBitmap} ${OUTVAR_BMP} "${BMP}" $R0
  !insertmacro AddNotify ${OUTVAR_BMP}
  ${NSD_OnClick} ${OUTVAR_BMP} ${HANDLER}
  System::Call "user32::SetWindowPos(i ${OUTVAR_BMP}, i 0, i 0, i 0, i 0, i 0, i 0x0003)"
  StrCpy ${OUTVAR_CLICK} ${OUTVAR_BMP}
!macroend

!macro ShowBanner MIN_HANDLER CLOSE_HANDLER BANNER_HANDLER
  ${NSD_CreateBitmap} 0 0 ${WIN_W} ${BANNER_H} ""
  Pop $hBanner
  ${NSD_SetBitmap} $hBanner "$PLUGINSDIR\banner_uninstall.bmp" $hBmpHandle
  !insertmacro AddNotify $hBanner
  ${NSD_OnClick} $hBanner ${BANNER_HANDLER}
  !insertmacro BitmapBtn 478 6 28 24 "$PLUGINSDIR\btn_min.bmp" ${MIN_HANDLER} $hMinBmp $hMinBtn
  !insertmacro BitmapBtn 506 6 28 24 "$PLUGINSDIR\btn_close.bmp" ${CLOSE_HANDLER} $hCloseBmp $hCloseBtn
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

; ═══════════════════════════════════════════════
; 卸载模拟 GUI（三页：确认 / 卸载进度 / 完成）
; 纯模拟：不真实删除任何文件
; ═══════════════════════════════════════════════

Page custom Confirm ConfirmLeave
Page custom Progress ProgressLeave
Page custom DonePage

Function .onGUIInit
  !insertmacro MakeBorderless
FunctionEnd

Function DragTitle
  SendMessage $HWNDPARENT ${WM_NCLBUTTONDOWN} ${HTCAPTION} 0
FunctionEnd

Function Close
  SendMessage $HWNDPARENT ${WM_CLOSE} 0 0
FunctionEnd

Function Minimize
  ShowWindow $HWNDPARENT 6
FunctionEnd

Function NextClick
  ${If} $unCurPage == 3
    Call FnDone
  ${Else}
    !insertmacro AdvanceNext
  ${EndIf}
FunctionEnd

Function PrevClick
  !insertmacro AdvanceBack
FunctionEnd

Function FnDone
  SendMessage $HWNDPARENT ${WM_CLOSE} 0 0
FunctionEnd

Function .onInit
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
  File "D:\naixi_desktop\src-tauri\installer\warn_uninstall.bmp"
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
FunctionEnd

; ─── 第 1 页：确认（内容对齐 uninstall_mockup.html）───
Function Confirm
  nsDialogs::Create 1018
  Pop $Dialog
  StrCpy $unCurPage 1
  !insertmacro MakeBorderless
  !insertmacro FillPage
  !insertmacro HideWizardChrome
  SetCtlColors $Dialog "" "${CLR_BG}"
  !insertmacro ShowBanner Minimize Close DragTitle

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

  !insertmacro CreateFooterU 1 "$PLUGINSDIR\btn_uninstall.bmp" 0 1 PrevClick NextClick

  ${NSD_FreeBitmap} $hBanner
  nsDialogs::Show
FunctionEnd

Function ConfirmLeave
  ${NSD_GetState} $unDeleteChk $0
  StrCpy $unDeleteData $0
FunctionEnd

; ─── 第 2 页：进度（原生 msctls_progress32，与 test_flow P3 同机制）───
Function Progress
  nsDialogs::Create 1018
  Pop $Dialog
  StrCpy $unCurPage 2
  !insertmacro MakeBorderless
  !insertmacro FillPage
  !insertmacro HideWizardChrome
  SetCtlColors $Dialog "" "${CLR_BG}"
  !insertmacro ShowBanner Minimize Close DragTitle

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

  !insertmacro CreateFooterU 2 "$PLUGINSDIR\btn_uninstalling.bmp" 0 0 PrevClick NextClick

  ; 步骤文字提到顶层、footer 背景压底（与 test_flow P3 一致，避免被 footer 盖住）
  System::Call "user32::SetWindowPos(i $hStepTxt1, i 0, i 0, i 0, i 0, i 0, i 0x0003)"
  System::Call "user32::SetWindowPos(i $hStepTxt2, i 0, i 0, i 0, i 0, i 0, i 0x0003)"
  System::Call "user32::SetWindowPos(i $hStepTxt3, i 0, i 0, i 0, i 0, i 0, i 0x0003)"
  System::Call "user32::SetWindowPos(i $hFooterBg, i 1, i 0, i 0, i 0, i 0, i 0x0003)"

  StrCpy $unInstallDone 0
  StrCpy $unProg 0
  ${NSD_CreateTimer} UninstallTick 100

  ${NSD_FreeBitmap} $hBanner
  nsDialogs::Show
FunctionEnd

Function UninstallTick
  ${If} $unInstallDone == 1
    Return
  ${EndIf}
  Call DoUninstallStage
  ${If} $unInstallDone == 1
    ${NSD_KillTimer} UninstallTick
  ${Else}
    ${NSD_CreateTimer} UninstallTick 120
  ${EndIf}
FunctionEnd

Function ProgressLeave
  ${If} $unInstallDone != 1
    Abort
  ${EndIf}
FunctionEnd

; ─── 第 3 页：完成 ───
Function DonePage
  nsDialogs::Create 1018
  Pop $Dialog
  StrCpy $unCurPage 3
  !insertmacro MakeBorderless
  !insertmacro FillPage
  !insertmacro HideWizardChrome
  SetCtlColors $Dialog "" "${CLR_BG}"
  !insertmacro ShowBanner Minimize Close DragTitle

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

  !insertmacro CreateFooterU 3 "$PLUGINSDIR\btn_finish.bmp" 0 1 PrevClick NextClick

  ${NSD_FreeBitmap} $hBanner
  nsDialogs::Show
FunctionEnd

; ─── 卸载模拟删除逻辑（仅进度动画）───
Function DoUninstallStage
  ${If} $unInstallDone == 1
    Return
  ${EndIf}
  IntOp $unProg $unProg + 3
  ${If} $unProg > 100
    StrCpy $unProg 100
  ${EndIf}
  SendMessage $hProgressFill ${PBM_SETPOS} $unProg 0
  ${If} $unProg <= 30
    ${NSD_SetText} $unProgStatus "正在检查程序是否在运行... $unProg%"
  ${ElseIf} $unProg <= 60
    ${NSD_SetText} $unProgStatus "正在删除程序文件... $unProg%"
  ${ElseIf} $unProg <= 90
    ${NSD_SetText} $unProgStatus "正在删除快捷方式与注册表... $unProg%"
  ${Else}
    ${NSD_SetText} $unProgStatus "正在清理目录... $unProg%"
  ${EndIf}
  ${If} $unProg == 100
    StrCpy $unInstallDone 1
    ${NSD_SetBitmap} $hNextBmp "$PLUGINSDIR\btn_finish.bmp" $R0
    ${NSD_SetText} $unProgStatus "卸载完成 100%"
    EnableWindow $hNextBtn 1
  ${EndIf}
FunctionEnd

Section "Main" SEC01
SectionEnd

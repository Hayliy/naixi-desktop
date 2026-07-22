Unicode true
ManifestDPIAware true

!include LogicLib.nsh
!include nsDialogs.nsh
!include WinVer.nsh
!include FileFunc.nsh
!include x64.nsh
!include WordFunc.nsh
!include Sections.nsh

!define WIN_W 560
!define WIN_H 460
!define BANNER_H 154
!define CLR_HEADER   0xD4537E
!define CLR_BG       0xFBEAF0
!define CLR_WHITE    0xFFFFFF
!define CLR_TEXT     0x72243E
!define CLR_MUTED    0x888780

Var Dialog
Var StepLabel0
Var StepLabel1
Var StepLabel2
Var StepLabel3
Var hBanner
Var hBmpHandle

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
!macroend

!macro FillPage
  System::Call "user32::SetWindowPos(i $Dialog, i 0, i 0, i 0, i ${WIN_W}, i ${WIN_H}, i 0x14)"
!macroend

!macro AdvanceNext
  GetDlgItem $0 $HWNDPARENT 1
  SendMessage $HWNDPARENT ${WM_COMMAND} 1 $0
!macroend

!macro ShowBanner
  ${NSD_CreateBitmap} 0 0 ${WIN_W} ${BANNER_H} ""
  Pop $hBanner
  ${NSD_SetBitmap} $hBanner "$PLUGINSDIR\banner.bmp" $hBmpHandle
  ${NSD_OnClick} $hBanner fn_DragTitle
  ${NSD_CreateLabel} 530 5 24 24 "×"
  Pop $0
  SetCtlColors $0 "${CLR_WHITE}" "${CLR_HEADER}"
  ${NSD_OnClick} $0 fn_Close
!macroend

!macro CreateStepBar ACTIVE
  Push $0
  ${NSD_CreateLabel} 24 388 96 16 ""
  Pop $StepLabel0
  ${If} ${ACTIVE} >= 1
    SetCtlColors $StepLabel0 "${CLR_TEXT}" "${CLR_BG}"
  ${Else}
    SetCtlColors $StepLabel0 "${CLR_MUTED}" "${CLR_BG}"
  ${EndIf}
  SendMessage $StepLabel0 ${WM_SETTEXT} 0 "STR:1 欢迎"
  ${NSD_CreateLabel} 156 388 96 16 ""
  Pop $StepLabel1
  SendMessage $StepLabel1 ${WM_SETTEXT} 0 "STR:2 位置"
  ${NSD_CreateLabel} 288 388 96 16 ""
  Pop $StepLabel2
  SendMessage $StepLabel2 ${WM_SETTEXT} 0 "STR:3 安装"
  ${NSD_CreateLabel} 420 388 96 16 ""
  Pop $StepLabel3
  SendMessage $StepLabel3 ${WM_SETTEXT} 0 "STR:4 完成"
  Pop $0
!macroend

Name "语法校验"
OutFile "syntax_check.exe"
RequestExecutionLevel user

Function .onGUIInit
  !insertmacro MakeBorderless
FunctionEnd

Page custom fn_Welcome

Function fn_Welcome
  nsDialogs::Create 1018
  Pop $Dialog
  !insertmacro HideWizardChrome
  !insertmacro MakeBorderless
  !insertmacro FillPage
  SetCtlColors $Dialog "" "${CLR_BG}"
  !insertmacro ShowBanner
  ${NSD_CreateLabel} 20 174 520 28 "欢迎"
  Pop $0
  SetCtlColors $0 "${CLR_TEXT}" "${CLR_BG}"
  !insertmacro CreateStepBar 1
  ${NSD_CreateButton} 450 414 90 30 "安装 >>"
  Pop $0
  SetCtlColors $0 "${CLR_WHITE}" "${CLR_HEADER}"
  ${NSD_OnClick} $0 fn_WelcomeInstall
  ${NSD_FreeBitmap} $hBanner
  nsDialogs::Show
FunctionEnd

Function fn_DragTitle
  SendMessage $HWNDPARENT ${WM_NCLBUTTONDOWN} ${HTCAPTION} 0
FunctionEnd

Function fn_Close
  SendMessage $HWNDPARENT ${WM_CLOSE} 0 0
FunctionEnd

Function fn_WelcomeInstall
  Pop $1
  !insertmacro AdvanceNext
FunctionEnd

Function .onInit
  InitPluginsDir
  SetOutPath $PLUGINSDIR
  File "D:\naixi_desktop\src-tauri\installer\banner.bmp"
FunctionEnd

Section "Main" SEC01
SectionEnd

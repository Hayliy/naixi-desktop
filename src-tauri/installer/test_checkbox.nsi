Unicode true
Name "TestCheckbox"
OutFile "D:\naixi_desktop\src-tauri\installer\test_checkbox.exe"
RequestExecutionLevel user

!include LogicLib.nsh
!include nsDialogs.nsh
!include WinMessages.nsh

Page custom Page1

Function Page1
  nsDialogs::Create 1018
  Pop $0
  SetCtlColors $0 0x000000 0xFFFFFF

  ; 方式 A：创建时直接带文字
  ${NSD_CreateCheckBox} 30 50 480 18 "方式A：同时删除个人配置与数据（不可恢复）"
  Pop $0

  ; 方式 B：创建后 SetText
  ${NSD_CreateCheckBox} 30 90 480 18 ""
  Pop $1
  ${NSD_SetText} $1 "方式B：同时删除个人配置与数据（不可恢复）"

  ; 方式 C：带样式设置
  ${NSD_CreateCheckBox} 30 130 480 18 ""
  Pop $2
  ${NSD_SetText} $2 "方式C：同时删除个人配置与数据（不可恢复）"
  SetCtlColors $2 0x000000 0xFFFFFF
  System::Call 'gdi32::CreateFont(i -13, i 0, i 0, i 0, i 400, i 0, i 0, i 0, i 0x01, i 0, i 0, i 0, i 0, t "Microsoft YaHei") i .r0'
  SendMessage $2 ${WM_SETFONT} $0 1

  ${NSD_CreateLabel} 30 180 480 40 "if A/B/C all show text, checkbox text is fine."
  Pop $0
  SetCtlColors $0 0x000000 0xFFFFFF

  nsDialogs::Show
FunctionEnd

Section
SectionEnd

Unicode true
Name "TestCheckbox3"
OutFile "D:\naixi_desktop\src-tauri\installer\test_checkbox3.exe"
RequestExecutionLevel user

!include LogicLib.nsh
!include nsDialogs.nsh
!include WinMessages.nsh

Var hFontBody
Var Dialog

Page custom Page1

Function .onInit
  System::Call 'gdi32::CreateFont(i -13, i 0, i 0, i 0, i 400, i 0, i 0, i 0, i 0x01, i 0, i 0, i 0, i 0, t "Microsoft YaHei") i .r0'
  StrCpy $hFontBody $0
FunctionEnd

Function Page1
  nsDialogs::Create 1018
  Pop $Dialog
  SetCtlColors $Dialog "" 0xFFFFFF

  ${NSD_CreateLabel} 30 50 480 18 "测试标签文字"
  Pop $0
  SetCtlColors $0 0x666666 0xFFFFFF
  SendMessage $0 ${WM_SETFONT} $hFontBody 1

  ${NSD_CreateCheckBox} 30 90 480 18 "同时删除个人配置与数据（不可恢复）"
  Pop $0
  SendMessage $0 ${BM_SETCHECK} ${BST_UNCHECKED} 0
  SetCtlColors $0 0x444444 0xFFFFFF
  SendMessage $0 ${WM_SETFONT} $hFontBody 1

  nsDialogs::Show
FunctionEnd

Section
SectionEnd

Unicode true
Name "TestLabelWidth"
OutFile "D:\naixi_desktop\src-tauri\installer\test_label_width.exe"
RequestExecutionLevel user

!include LogicLib.nsh
!include nsDialogs.nsh
!include WinMessages.nsh

Var hTrack
Var hFill

Page custom Page1

Function Page1
  nsDialogs::Create 1018
  Pop $0
  
  ; 轨道：浅粉，全宽
  ${NSD_CreateLabel} 30 100 480 10 ""
  Pop $hTrack
  SetCtlColors $hTrack 0xF4C0D1 0xF4C0D1
  
  ; 填充：粉色，初始 1px（待会儿改成 240px，即 50%）
  ${NSD_CreateLabel} 30 100 1 10 ""
  Pop $hFill
  SetCtlColors $hFill 0xD4537E 0xD4537E
  
  ; 测试 SetWindowPos 改宽度为 240
  System::Call "user32::SetWindowPos(i $hFill, i 0, i 30, i 100, i 240, i 10, i 0x0014)"
  
  ${NSD_CreateLabel} 30 150 480 20 "fill should be 240px pink on 480px light-pink track"
  Pop $0
  SetCtlColors $0 0x000000 0xFFFFFF
  
  nsDialogs::Show
FunctionEnd

Section
SectionEnd

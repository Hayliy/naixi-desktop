!include LogicLib.nsh
!include nsDialogs.nsh
!include WinMessages.nsh

RequestExecutionLevel user

Var hwnd
Var tick

Page custom tp

Function fnTick
  IntOp $tick $tick + 1
  FileOpen $1 "$TEMP\gt_timer.log" a
  FileWrite $1 "enter tick=$tick$\r$\n"
  FileClose $1
  System::Call "kernel32::GetTickCount() i .r0"
  FileOpen $1 "$TEMP\gt_timer.log" a
  FileWrite $1 "gt=$0$\r$\n"
  FileClose $1
FunctionEnd

Function tp
  nsDialogs::Create 1018
  Pop $hwnd
  StrCpy $tick 0
  ${NSD_CreateTimer} fnTick 200
  nsDialogs::Show
FunctionEnd

Section "Main" SEC01
SectionEnd

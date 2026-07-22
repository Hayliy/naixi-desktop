Unicode true
Name "gt_timer2"
RequestExecutionLevel user
!include nsDialogs.nsh
!include LogicLib.nsh
!include WinMessages.nsh

Var Dialog
Var Count

Page custom fn_test

Function fn_tick
  IntOp $Count $Count + 1
  FileOpen $R0 "$TEMP\gt_count.log" a
  FileWrite $R0 "$Count$\n"
  FileClose $R0
FunctionEnd

Function fn_test
  nsDialogs::Create 1018
  Pop $Dialog
  StrCpy $Count 0
  ${NSD_CreateTimer} fn_tick 30
  nsDialogs::Show
FunctionEnd

Section "" SEC01
SectionEnd

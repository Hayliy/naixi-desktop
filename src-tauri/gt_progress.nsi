!include LogicLib.nsh
!include nsDialogs.nsh
!include WinMessages.nsh

RequestExecutionLevel user
Name "gt_progress"

Var hwnd
Var tick
Var hFill

Page custom tp

Function fnTick
  IntOp $tick $tick + 1
  System::Call "kernel32::GetTickCount() i .r0"
  FileOpen $1 "$TEMP\gt_progress.log" a
  FileWrite $1 "tick=$tick gt=$0$\r$\n"
  FileClose $1
  IntOp $2 $tick * 20
  ${If} $2 > 300
    StrCpy $2 300
  ${EndIf}
  System::Call "user32::SetWindowPos(i $hFill, i 0, i 50, i 100, i r2, i 30, i 0x0014)"
  System::Call "user32::RedrawWindow(i $hFill, i 0, i 0, i 0x0101)"
  ${If} $tick == 15
    ${NSD_KillTimer} fnTick
  ${EndIf}
FunctionEnd

Function tp
  nsDialogs::Create 1018
  Pop $hwnd
  StrCpy $tick 0

  ${NSD_CreateLabel} 50 100 300 30 ""
  Pop $0
  SetCtlColors $0 "0x000000" "0xFF0000"
  StrCpy $hFill $0

  ${NSD_CreateTimer} fnTick 200
  nsDialogs::Show
FunctionEnd

Section "Main" SEC01
SectionEnd

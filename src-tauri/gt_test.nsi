!include LogicLib.nsh
!include nsDialogs.nsh
!include WinMessages.nsh

RequestExecutionLevel user

Var hwnd

Page custom t

Function t
  nsDialogs::Create 1018
  Pop $hwnd

  ; 仅测 GetTickCount (i)
  System::Call "kernel32::GetTickCount() i .r0"
  FileOpen $1 "$TEMP\gt_i.log" w
  FileWrite $1 "v=$0 len=$0$\r$\n"
  FileClose $1

  ; 仅测 GetTickCount (l)
  System::Call "kernel32::GetTickCount() l .r0"
  FileOpen $1 "$TEMP\gt_l.log" w
  FileWrite $1 "v=$0 len=$0$\r$\n"
  FileClose $1

  nsDialogs::Show
FunctionEnd

Section "Main" SEC01
SectionEnd

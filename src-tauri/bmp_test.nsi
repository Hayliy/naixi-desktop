!include "MUI2.nsh"
!include "nsDialogs.nsh"
!include "WinMessages.nsh"

Name "BmpTest"
OutFile "bmp_test.exe"
Caption "Bitmap Render Test"
RequestExecutionLevel user
XPStyle on

ReserveFile "red.bmp"

Page custom TestPage

Function .onInit
  InitPluginsDir
  File "/oname=$PLUGINSDIR\red.bmp" "red.bmp"
FunctionEnd

Function TestPage
  nsDialogs::Create 1018
  Pop $0

  ${NSD_CreateLabel} 20 5 200 16 "对话框已弹出，下方应显示蓝色方块"
  Pop $1

  ${NSD_CreateBitmap} 20 30 200 150 ""
  Pop $2
  ${NSD_SetBitmap} $2 "$PLUGINSDIR\red.bmp" $3

  nsDialogs::Show
FunctionEnd

Section
SectionEnd

Unicode true
ManifestDPIAware true
ManifestDPIAwareness PerMonitorV2

!if "{{compression}}" == "none"
  SetCompress off
!else
  SetCompressor /SOLID "{{compression}}"
!endif

{{#if signed_plugins_path}}
!addplugindir "{{signed_plugins_path}}"
{{/if}}

!include LogicLib.nsh
!include WinVer.nsh
!include FileFunc.nsh
!include x64.nsh
!include WordFunc.nsh
!include "utils.nsh"
!include "FileAssociation.nsh"
!include "Win\COM.nsh"
!include "Win\Propkey.nsh"
!include "StrFunc.nsh"
${StrCase}
${StrLoc}

{{#if installer_hooks}}
!include "{{installer_hooks}}"
{{/if}}

!define WEBVIEW2APPGUID "{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}"
!define MANUFACTURER "{{manufacturer}}"
!define PRODUCTNAME "{{product_name}}"
!define VERSION "{{version}}"
!define VERSIONWITHBUILD "{{version_with_build}}"
!define HOMEPAGE "{{homepage}}"
!define INSTALLMODE "{{install_mode}}"
!define LICENSE "{{license}}"
!define INSTALLERICON "{{installer_icon}}"
!define MAINBINARYNAME "{{main_binary_name}}"
!define MAINBINARYSRCPATH "{{main_binary_path}}"
!define BUNDLEID "{{bundle_id}}"
!define COPYRIGHT "{{copyright}}"
!define OUTFILE "{{out_file}}"
!define ARCH "{{arch}}"
!define ADDITIONALPLUGINSPATH "{{additional_plugins_path}}"
!define ALLOWDOWNGRADES "{{allow_downgrades}}"
!define INSTALLWEBVIEW2MODE "{{install_webview2_mode}}"
!define WEBVIEW2INSTALLERARGS "{{webview2_installer_args}}"
!define WEBVIEW2BOOTSTRAPPERPATH "{{webview2_bootstrapper_path}}"
!define WEBVIEW2INSTALLERPATH "{{webview2_installer_path}}"
!define MINIMUMWEBVIEW2VERSION "{{minimum_webview2_version}}"
!define UNINSTKEY "Software\Microsoft\Windows\CurrentVersion\Uninstall\${PRODUCTNAME}"
!define MANUKEY "Software\${MANUFACTURER}"
!define MANUPRODUCTKEY "${MANUKEY}\${PRODUCTNAME}"
!define UNINSTALLERSIGNCOMMAND "{{uninstaller_sign_cmd}}"
!define ESTIMATEDSIZE "{{estimated_size}}"
!define STARTMENUFOLDER "{{start_menu_folder}}"
!define HEADERIMAGE "{{header_image}}"
!define SIDEBARIMAGE "{{sidebar_image}}"

; Colors: sakura pink palette
!define CLR_BG        0xFBEAF0
!define CLR_HEADER    0xD4537E
!define CLR_HEADER2   0x993556
!define CLR_ACCENT    0xD4537E
!define CLR_TEXT      0x72243E
!define CLR_TEXT_DARK 0x993556
!define CLR_WHITE     0xFFFFFF
!define CLR_LIGHT     0xF4C0D1
!define CLR_MUTED     0x888780
!define CLR_GREEN     0x0F6E56
!define CLR_BORDER    0xD3C1D0
!define CLR_STEP_DONE 0xD4537E
!define CLR_STEP_PEND 0xF4C0D1

Var PageIndex
Var HeaderBgHwnd
Var StepLabel0
Var StepLabel1
Var StepLabel2
Var StepLabel3
Var StepLabel4
Var Dialog

Var PassiveMode
Var UpdateMode
Var NoShortcutMode
Var WixMode
Var OldMainBinaryName
Var DesktopShortcutCheck
Var StartMenuCheck
Var InstallPath
Var InstallPathText

Name "${PRODUCTNAME}"
BrandingText "${COPYRIGHT}"
OutFile "${OUTFILE}"

!define PLACEHOLDER_INSTALL_DIR "placeholder\${PRODUCTNAME}"
InstallDir "${PLACEHOLDER_INSTALL_DIR}"

VIProductVersion "${VERSIONWITHBUILD}"
VIAddVersionKey "ProductName" "${PRODUCTNAME}"
VIAddVersionKey "FileDescription" "${PRODUCTNAME}"
VIAddVersionKey "LegalCopyright" "${COPYRIGHT}"
VIAddVersionKey "FileVersion" "${VERSION}"
VIAddVersionKey "ProductVersion" "${VERSION}"

!addplugindir "${ADDITIONALPLUGINSPATH}"

!if "${UNINSTALLERSIGNCOMMAND}" != ""
  !uninstfinalize '${UNINSTALLERSIGNCOMMAND}'
!endif

!if "${INSTALLMODE}" == "perMachine"
  RequestExecutionLevel admin
!endif
!if "${INSTALLMODE}" == "currentUser"
  RequestExecutionLevel user
!endif
!if "${INSTALLMODE}" == "both"
  !define MULTIUSER_MUI
  !define MULTIUSER_INSTALLMODE_INSTDIR "${PRODUCTNAME}"
  !define MULTIUSER_INSTALLMODE_COMMANDLINE
  !if "${ARCH}" == "x64"
    !define MULTIUSER_USE_PROGRAMFILES64
  !else if "${ARCH}" == "arm64"
    !define MULTIUSER_USE_PROGRAMFILES64
  !endif
  !define MULTIUSER_INSTALLMODE_DEFAULT_REGISTRY_KEY "${UNINSTKEY}"
  !define MULTIUSER_INSTALLMODE_DEFAULT_REGISTRY_VALUENAME "CurrentUser"
  !define MULTIUSER_INSTALLMODEPAGE_SHOWUSERNAME
  !define MULTIUSER_INSTALLMODE_FUNCTION RestorePreviousInstallLocation
  !define MULTIUSER_EXECUTIONLEVEL Highest
  !include MultiUser.nsh
!endif

!if "${INSTALLERICON}" != ""
  !define MUI_ICON "${INSTALLERICON}"
!endif

; Languages
{{#each languages}}
!insertmacro MUI_LANGUAGE "{{this}}"
{{/each}}
{{#each language_files}}
  !include "{{this}}"
{{/each}}

; ──────────────────────────────────────────────
; Helper macros
; ──────────────────────────────────────────────

!macro CreateHeader INDEX TITLE
  Push $0
  ${If} $PageIndex = 0
    nsDialogs::Create 1018
    Pop $Dialog
    SetCtlColors $Dialog "" "${CLR_BG}"
  ${EndIf}
  ; Header bar
  ${NSD_CreateLabel} 0 0 100% 36 ""
  Pop $HeaderBgHwnd
  SetCtlColors $HeaderBgHwnd "${CLR_WHITE}" "${CLR_HEADER}"
  SendMessage $HeaderBgHwnd ${WM_SETTEXT} 0 "STR:${TITLE}"
  ; Step indicators
  System::Call "user32::CreateWindow(i 0, i 0, i 0, i 0, i 0, i 0, i 0, i 0, i 0, i 0, i 0, i 0) i.s"
  Pop $0
  ; Rest
  ${NSD_CreateLabel} 10 46 460 100 ""
  Pop $0
  Pop $0
!macroend

; ──────────────────────────────────────────────
; Pages
; ──────────────────────────────────────────────

; Page 0: Welcome
Page custom WelcomePage WelcomePageLeave
Function WelcomePage
  nsDialogs::Create 1018
  Pop $Dialog
  SetCtlColors $Dialog "" "${CLR_BG}"

  ; Header bar
  ${NSD_CreateLabel} 0 0 100% 50 ""
  Pop $HeaderBgHwnd
  SetCtlColors $HeaderBgHwnd "${CLR_WHITE}" "${CLR_HEADER}"

  ; Naixi title
  ${NSD_CreateLabel} 20 10 300 20 ""
  Pop $0
  SetCtlColors $0 "${CLR_WHITE}" "${CLR_HEADER}"
  SendMessage $0 ${WM_SETTEXT} 0 "STR:Welcome to Naixi Desktop"

  ${NSD_CreateLabel} 20 30 300 16 ""
  Pop $0
  SetCtlColors $0 "${CLR_LIGHT}" "${CLR_HEADER}"
  SendMessage $0 ${WM_SETTEXT} 0 "STR:Version ${VERSION}"

  ; Welcome text
  ${NSD_CreateLabel} 20 70 420 80 ""
  Pop $0
  SetCtlColors $0 "" "${CLR_BG}"
  SendMessage $0 ${WM_SETTEXT} 0 "STR:This wizard will install ${PRODUCTNAME} on your computer.$\r$\n$\r$\n${PRODUCTNAME} is an AI-powered desktop platform with intelligent chat, knowledge management, automation, and more.$\r$\n$\r$\nClick Install to continue, or Cancel to exit."

  ; Install button (accent)
  ${NSD_CreateButton} 300 180 100 24 ""
  Pop $0
  SetCtlColors $0 "${CLR_WHITE}" "${CLR_ACCENT}"
  SendMessage $0 ${WM_SETTEXT} 0 "STR:Install"
  ${NSD_OnClick} $0 WelcomePageInstall

  ; Cancel
  ${NSD_CreateButton} 410 180 60 24 ""
  Pop $0
  SendMessage $0 ${WM_SETTEXT} 0 "STR:Cancel"
  ${NSD_OnClick} $0 WelcomePageCancel

  nsDialogs::Show
FunctionEnd

Function WelcomePageInstall
  Call SkipIfPassive
  Call DirectoryPage
FunctionEnd

Function WelcomePageCancel
  Abort
FunctionEnd

Function WelcomePageLeave
FunctionEnd

; Page 1: Directory selection
Function DirectoryPage
  nsDialogs::Create 1018
  Pop $Dialog
  SetCtlColors $Dialog "" "${CLR_BG}"

  ; Header
  ${NSD_CreateLabel} 0 0 100% 36 ""
  Pop $HeaderBgHwnd
  SetCtlColors $HeaderBgHwnd "${CLR_WHITE}" "${CLR_HEADER}"
  SendMessage $HeaderBgHwnd ${WM_SETTEXT} 0 "STR:Installation location"

  ; Step indicator dots
  !insertmacro CreateStepDots 1

  ; Label
  ${NSD_CreateLabel} 20 56 200 14 ""
  Pop $0
  SetCtlColors $0 "${CLR_TEXT}" "${CLR_BG}"
  SendMessage $0 ${WM_SETTEXT} 0 "STR:DESTINATION FOLDER"

  ; Path input
  ${NSD_CreateText} 20 74 350 20 ""
  Pop $InstallPathText
  SendMessage $InstallPathText ${WM_SETTEXT} 0 "STR:$INSTDIR"
  SetCtlColors $InstallPathText "" "${CLR_WHITE}"

  ; Browse button
  ${NSD_CreateButton} 380 74 80 20 ""
  Pop $0
  SetCtlColors $0 "" "${CLR_WHITE}"
  SendMessage $0 ${WM_SETTEXT} 0 "STR:Browse..."
  ${NSD_OnClick} $0 OnBrowseDir

  ; Space info
  ${NSD_CreateLabel} 20 106 440 28 ""
  Pop $0
  SetCtlColors $0 "${CLR_TEXT}" "${CLR_BG}"
  SendMessage $0 ${WM_SETTEXT} 0 "STR:Disk space required: ~${ESTIMATEDSIZE} MB"

  ; Buttons
  ${NSD_CreateButton} 300 150 100 24 ""
  Pop $0
  SetCtlColors $0 "${CLR_WHITE}" "${CLR_ACCENT}"
  SendMessage $0 ${WM_SETTEXT} 0 "STR:Install"
  ${NSD_OnClick} $0 DirectoryPageInstall

  ${NSD_CreateButton} 410 150 60 24 ""
  Pop $0
  SendMessage $0 ${WM_SETTEXT} 0 "STR:Cancel"
  ${NSD_OnClick} $0 DirectoryPageCancel

  nsDialogs::Show
FunctionEnd

Function OnBrowseDir
  ${NSD_GetText} $InstallPathText $0
  nsDialogs::SelectFolderDialog "Select installation directory" "$0"
  Pop $0
  ${If} $0 != error
    SendMessage $InstallPathText ${WM_SETTEXT} 0 "STR:$0"
    StrCpy $INSTDIR $0
  ${EndIf}
FunctionEnd

Function DirectoryPageInstall
  ${NSD_GetText} $InstallPathText $INSTDIR
  Call InstallPage
FunctionEnd

Function DirectoryPageCancel
  Abort
FunctionEnd

; Page 2: Install progress
Function InstallPage
  nsDialogs::Create 1018
  Pop $Dialog
  SetCtlColors $Dialog "" "${CLR_BG}"

  ${NSD_CreateLabel} 0 0 100% 36 ""
  Pop $HeaderBgHwnd
  SetCtlColors $HeaderBgHwnd "${CLR_WHITE}" "${CLR_HEADER}"
  SendMessage $HeaderBgHwnd ${WM_SETTEXT} 0 "STR:Installing..."

  !insertmacro CreateStepDots 2

  ; Installing text
  ${NSD_CreateLabel} 20 56 440 40 ""
  Pop $0
  SetCtlColors $0 "${CLR_TEXT}" "${CLR_BG}"
  SendMessage $0 ${WM_SETTEXT} 0 "STR:Please wait while ${PRODUCTNAME} is being installed..."

  ; Progress bar placeholder (NSIS instfiles page handles the actual progress)
  ${NSD_CreateLabel} 20 100 440 14 ""
  Pop $0
  SetCtlColors $0 "${CLR_MUTED}" "${CLR_BG}"
  SendMessage $0 ${WM_SETTEXT} 0 "STR:Installing files..."

  nsDialogs::Show

  ; Install sections
  Call InstallSections
FunctionEnd

; Page 3: Options (shortcuts)
Function OptionsPage
  nsDialogs::Create 1018
  Pop $Dialog
  SetCtlColors $Dialog "" "${CLR_BG}"

  ${NSD_CreateLabel} 0 0 100% 36 ""
  Pop $HeaderBgHwnd
  SetCtlColors $HeaderBgHwnd "${CLR_WHITE}" "${CLR_HEADER}"
  SendMessage $HeaderBgHwnd ${WM_SETTEXT} 0 "STR:Additional tasks"

  !insertmacro CreateStepDots 3

  ${NSD_CreateLabel} 20 56 440 14 ""
  Pop $0
  SetCtlColors $0 "${CLR_TEXT}" "${CLR_BG}"
  SendMessage $0 ${WM_SETTEXT} 0 "STR:SELECT ADDITIONAL TASKS"

  ; Desktop shortcut checkbox
  ${NSD_CreateCheckBox} 30 80 400 14 ""
  Pop $DesktopShortcutCheck
  SetCtlColors $DesktopShortcutCheck "" "${CLR_BG}"
  SendMessage $DesktopShortcutCheck ${BM_SETCHECK} ${BST_CHECKED} 0
  SendMessage $DesktopShortcutCheck ${WM_SETTEXT} 0 "STR:Create a desktop shortcut"

  ; Start menu checkbox
  ${NSD_CreateCheckBox} 30 100 400 14 ""
  Pop $StartMenuCheck
  SetCtlColors $StartMenuCheck "" "${CLR_BG}"
  SendMessage $StartMenuCheck ${BM_SETCHECK} ${BST_CHECKED} 0
  SendMessage $StartMenuCheck ${WM_SETTEXT} 0 "STR:Create Start Menu shortcuts"

  ; Buttons
  ${NSD_CreateButton} 300 150 100 24 ""
  Pop $0
  SetCtlColors $0 "${CLR_WHITE}" "${CLR_ACCENT}"
  SendMessage $0 ${WM_SETTEXT} 0 "STR:Finish"
  ${NSD_OnClick} $0 OptionsPageFinish

  ${NSD_CreateButton} 410 150 60 24 ""
  Pop $0
  SendMessage $0 ${WM_SETTEXT} 0 "STR:Cancel"
  ${NSD_OnClick} $0 OptionsPageCancel

  nsDialogs::Show
FunctionEnd

Function OptionsPageFinish
  ${NSD_GetState} $DesktopShortcutCheck $0
  ${If} $0 = ${BST_CHECKED}
    Call CreateOrUpdateDesktopShortcut
  ${EndIf}
  Call FinishPage
FunctionEnd

Function OptionsPageCancel
  Abort
FunctionEnd

; Page 4: Finish
Function FinishPage
  nsDialogs::Create 1018
  Pop $Dialog
  SetCtlColors $Dialog "" "${CLR_BG}"

  ${NSD_CreateLabel} 0 0 100% 50 ""
  Pop $HeaderBgHwnd
  SetCtlColors $HeaderBgHwnd "${CLR_WHITE}" "${CLR_HEADER}"

  ${NSD_CreateLabel} 20 10 300 20 ""
  Pop $0
  SetCtlColors $0 "${CLR_WHITE}" "${CLR_HEADER}"
  SendMessage $0 ${WM_SETTEXT} 0 "STR:Installation complete"

  !insertmacro CreateStepDots 4

  ${NSD_CreateLabel} 20 70 420 60 ""
  Pop $0
  SetCtlColors $0 "" "${CLR_BG}"
  SendMessage $0 ${WM_SETTEXT} 0 "STR:${PRODUCTNAME} has been installed successfully.$\r$\n$\r$\nThank you for choosing Naixi!"

  ; Run checkbox
  ${NSD_CreateCheckBox} 20 150 400 14 ""
  Pop $0
  SendMessage $0 ${BM_SETCHECK} ${BST_CHECKED} 0
  SendMessage $0 ${WM_SETTEXT} 0 "STR:Run ${PRODUCTNAME} now"

  ; Done button
  ${NSD_CreateButton} 300 180 100 24 ""
  Pop $0
  SetCtlColors $0 "${CLR_WHITE}" "${CLR_ACCENT}"
  SendMessage $0 ${WM_SETTEXT} 0 "STR:Done"
  ${NSD_OnClick} $0 FinishDone

  nsDialogs::Show
FunctionEnd

Function FinishDone
  Call RunMainBinary
  Quit
FunctionEnd

!macro CreateStepDots CURRENT
  ${NSD_CreateLabel} 20 44 440 10 ""
  Pop $StepLabel0
  ${If} ${CURRENT} >= 1
    SetCtlColors $StepLabel0 "${CLR_STEP_DONE}" "${CLR_BG}"
  ${Else}
    SetCtlColors $StepLabel0 "${CLR_STEP_PEND}" "${CLR_BG}"
  ${EndIf}
  SendMessage $StepLabel0 ${WM_SETTEXT} 0 "STR:Welcome"

  ${NSD_CreateLabel} 100 44 440 10 ""
  Pop $StepLabel1
  ${If} ${CURRENT} >= 2
    SetCtlColors $StepLabel1 "${CLR_STEP_DONE}" "${CLR_BG}"
  ${Else}
    SetCtlColors $StepLabel1 "${CLR_STEP_PEND}" "${CLR_BG}"
  ${EndIf}
  SendMessage $StepLabel1 ${WM_SETTEXT} 0 "STR:Location"

  ${NSD_CreateLabel} 200 44 440 10 ""
  Pop $StepLabel2
  ${If} ${CURRENT} >= 3
    SetCtlColors $StepLabel2 "${CLR_STEP_DONE}" "${CLR_BG}"
  ${Else}
    SetCtlColors $StepLabel2 "${CLR_STEP_PEND}" "${CLR_BG}"
  ${EndIf}
  SendMessage $StepLabel2 ${WM_SETTEXT} 0 "STR:Install"

  ${NSD_CreateLabel} 300 44 440 10 ""
  Pop $StepLabel3
  ${If} ${CURRENT} >= 4
    SetCtlColors $StepLabel3 "${CLR_STEP_DONE}" "${CLR_BG}"
  ${Else}
    SetCtlColors $StepLabel3 "${CLR_STEP_PEND}" "${CLR_BG}"
  ${EndIf}
  SendMessage $StepLabel3 ${WM_SETTEXT} 0 "STR:Finish"
!macroend

; ──────────────────────────────────────────────
; Install logic (copied from default template)
; ──────────────────────────────────────────────

Function InstallSections
  SetOutPath $INSTDIR
  !ifmacrodef NSIS_HOOK_PREINSTALL
    !insertmacro NSIS_HOOK_PREINSTALL
  !endif
  !insertmacro CheckIfAppIsRunning "${MAINBINARYNAME}.exe" "${PRODUCTNAME}"
  File "${MAINBINARYSRCPATH}"
  {{#each resources_dirs}}
    CreateDirectory "$INSTDIR\\{{this}}"
  {{/each}}
  {{#each resources}}
    File /a "/oname={{this.[1]}}" "{{no-escape @key}}"
  {{/each}}
  {{#each binaries}}
    File /a "/oname={{this}}" "{{no-escape @key}}"
  {{/each}}
  WriteUninstaller "$INSTDIR\uninstall.exe"
  WriteRegStr SHCTX "${MANUPRODUCTKEY}" "" $INSTDIR
  WriteRegStr SHCTX "${UNINSTKEY}" "MainBinaryName" "${MAINBINARYNAME}.exe"
  WriteRegStr SHCTX "${UNINSTKEY}" "DisplayName" "${PRODUCTNAME}"
  WriteRegStr SHCTX "${UNINSTKEY}" "DisplayIcon" "$\"$INSTDIR\${MAINBINARYNAME}.exe$\""
  WriteRegStr SHCTX "${UNINSTKEY}" "DisplayVersion" "${VERSION}"
  WriteRegStr SHCTX "${UNINSTKEY}" "Publisher" "${MANUFACTURER}"
  WriteRegStr SHCTX "${UNINSTKEY}" "InstallLocation" "$\"$INSTDIR$\""
  WriteRegStr SHCTX "${UNINSTKEY}" "UninstallString" "$\"$INSTDIR\uninstall.exe$\""
  WriteRegDWORD SHCTX "${UNINSTKEY}" "NoModify" "1"
  WriteRegDWORD SHCTX "${UNINSTKEY}" "NoRepair" "1"
  !if "${HOMEPAGE}" != ""
    WriteRegStr SHCTX "${UNINSTKEY}" "URLInfoAbout" "${HOMEPAGE}"
  !endif
  Call CreateOrUpdateStartMenuShortcut
  !ifmacrodef NSIS_HOOK_POSTINSTALL
    !insertmacro NSIS_HOOK_POSTINSTALL
  !endif
FunctionEnd

Function RunMainBinary
  nsis_tauri_utils::RunAsUser "$INSTDIR\${MAINBINARYNAME}.exe" ""
FunctionEnd

Function CreateOrUpdateStartMenuShortcut
  !if "${STARTMENUFOLDER}" != ""
    CreateDirectory "$SMPROGRAMS\${STARTMENUFOLDER}"
    CreateShortcut "$SMPROGRAMS\${STARTMENUFOLDER}\${PRODUCTNAME}.lnk" "$INSTDIR\${MAINBINARYNAME}.exe"
  !else
    CreateShortcut "$SMPROGRAMS\${PRODUCTNAME}.lnk" "$INSTDIR\${MAINBINARYNAME}.exe"
  !endif
FunctionEnd

Function CreateOrUpdateDesktopShortcut
  CreateShortcut "$DESKTOP\${PRODUCTNAME}.lnk" "$INSTDIR\${MAINBINARYNAME}.exe"
FunctionEnd

Function RestorePreviousInstallLocation
  ReadRegStr $4 SHCTX "${MANUPRODUCTKEY}" ""
  StrCmp $4 "" +2 0
    StrCpy $INSTDIR $4
FunctionEnd

Function Skip
  Abort
FunctionEnd

Function SkipIfPassive
  ${IfThen} $PassiveMode = 1  ${|} Abort ${|}
FunctionEnd

; ──────────────────────────────────────────────
; .onInit
; ──────────────────────────────────────────────

Function .onInit
  ${GetOptions} $CMDLINE "/P" $PassiveMode
  ${IfNot} ${Errors}
    StrCpy $PassiveMode 1
  ${EndIf}
  ${GetOptions} $CMDLINE "/NS" $NoShortcutMode
  ${IfNot} ${Errors}
    StrCpy $NoShortcutMode 1
  ${EndIf}
  ${GetOptions} $CMDLINE "/UPDATE" $UpdateMode
  ${IfNot} ${Errors}
    StrCpy $UpdateMode 1
  ${EndIf}

  StrCpy $PageIndex 0

  !if "${DISPLAYLANGUAGESELECTOR}" == "true"
    !insertmacro MUI_LANGDLL_DISPLAY
  !endif

  !insertmacro SetContext

  ${If} $INSTDIR == "${PLACEHOLDER_INSTALL_DIR}"
    !if "${INSTALLMODE}" == "perMachine"
      ${If} ${RunningX64}
        !if "${ARCH}" == "x64"
          StrCpy $INSTDIR "$PROGRAMFILES64\${PRODUCTNAME}"
        !else
          StrCpy $INSTDIR "$PROGRAMFILES\${PRODUCTNAME}"
        !endif
      ${Else}
        StrCpy $INSTDIR "$PROGRAMFILES\${PRODUCTNAME}"
      ${EndIf}
    !else if "${INSTALLMODE}" == "currentUser"
      StrCpy $INSTDIR "$LOCALAPPDATA\${PRODUCTNAME}"
    !endif
    Call RestorePreviousInstallLocation
  ${EndIf}
FunctionEnd

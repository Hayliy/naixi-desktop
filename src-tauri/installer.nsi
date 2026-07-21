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

!include MUI2.nsh
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

; Sakura palette
!define CLR_HEADER 0xD4537E
!define CLR_BG    0xFBEAF0
!define CLR_TEXT  0x72243E
!define CLR_WHITE 0xFFFFFF
!define CLR_LIGHT 0xF4C0D1

Var Dialog
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

; ── Custom welcome page ──
Page custom WelcomePage

; ── Custom directory page ──
Page custom DirectoryPage

; ── Standard install progress (required for Section execution) ──
!insertmacro MUI_PAGE_INSTFILES

; ── Custom finish page ──
Page custom FinishPage

; ── Languages ──
{{#each languages}}
!insertmacro MUI_LANGUAGE "{{this}}"
{{/each}}
{{#each language_files}}
  !include "{{this}}"
{{/each}}

; ── Welcome page ──
Function WelcomePage
  nsDialogs::Create 1018
  Pop $Dialog
  SetCtlColors $Dialog "" "${CLR_BG}"

  ${NSD_CreateLabel} 0 0 100% 50 ""
  Pop $0
  SetCtlColors $0 "${CLR_WHITE}" "${CLR_HEADER}"
  SendMessage $0 ${WM_SETTEXT} 0 "STR:  Welcome to Naixi Desktop"

  ${NSD_CreateLabel} 20 70 440 80 ""
  Pop $0
  SetCtlColors $0 "" "${CLR_BG}"
  SendMessage $0 ${WM_SETTEXT} 0 "STR:This wizard will install ${PRODUCTNAME} on your computer.$\r$\n$\r$\n${PRODUCTNAME} is an AI-powered desktop platform with agents, knowledge management, chat, and automation.$\r$\n$\r$\nClick Install to continue."

  ${NSD_CreateButton} 300 180 100 24 ""
  Pop $0
  SetCtlColors $0 "${CLR_WHITE}" "${CLR_HEADER}"
  SendMessage $0 ${WM_SETTEXT} 0 "STR:Install"
  ${NSD_OnClick} $0 GoDirPage

  ${NSD_CreateButton} 410 180 60 24 ""
  Pop $0
  SendMessage $0 ${WM_SETTEXT} 0 "STR:Cancel"
  ${NSD_OnClick} $0 CancelInstall
FunctionEnd

Function GoDirPage
  Call DirectoryPage
FunctionEnd

Function CancelInstall
  Abort
FunctionEnd

; ── Directory page ──
Function DirectoryPage
  nsDialogs::Create 1018
  Pop $Dialog
  SetCtlColors $Dialog "" "${CLR_BG}"

  ${NSD_CreateLabel} 0 0 100% 36 ""
  Pop $0
  SetCtlColors $0 "${CLR_WHITE}" "${CLR_HEADER}"
  SendMessage $0 ${WM_SETTEXT} 0 "STR:  Choose install location"

  ${NSD_CreateLabel} 20 56 440 14 ""
  Pop $0
  SetCtlColors $0 "${CLR_TEXT}" "${CLR_BG}"
  SendMessage $0 ${WM_SETTEXT} 0 "STR:Destination folder"

  ${NSD_CreateText} 20 74 340 20 ""
  Pop $InstallPathText
  SendMessage $InstallPathText ${WM_SETTEXT} 0 "STR:$INSTDIR"

  ${NSD_CreateButton} 370 74 80 20 ""
  Pop $0
  SendMessage $0 ${WM_SETTEXT} 0 "STR:Browse..."
  ${NSD_OnClick} $0 BrowseDir

  ${NSD_CreateLabel} 20 106 440 20 ""
  Pop $0
  SetCtlColors $0 "${CLR_TEXT}" "${CLR_BG}"
  SendMessage $0 ${WM_SETTEXT} 0 "STR:Disk space required: ~${ESTIMATEDSIZE} MB"

  ${NSD_CreateButton} 300 150 100 24 ""
  Pop $0
  SetCtlColors $0 "${CLR_WHITE}" "${CLR_HEADER}"
  SendMessage $0 ${WM_SETTEXT} 0 "STR:Install"
  ${NSD_OnClick} $0 StartInstall

  ${NSD_CreateButton} 410 150 60 24 ""
  Pop $0
  SendMessage $0 ${WM_SETTEXT} 0 "STR:Cancel"
  ${NSD_OnClick} $0 CancelInstall
FunctionEnd

Function BrowseDir
  ${NSD_GetText} $InstallPathText $0
  nsDialogs::SelectFolderDialog "Select installation folder" "$0"
  Pop $0
  ${If} $0 != error
    SendMessage $InstallPathText ${WM_SETTEXT} 0 "STR:$0"
    StrCpy $INSTDIR $0
  ${EndIf}
FunctionEnd

Function StartInstall
  ${NSD_GetText} $InstallPathText $INSTDIR
FunctionEnd

; ── Finish page ──
Function FinishPage
  nsDialogs::Create 1018
  Pop $Dialog
  SetCtlColors $Dialog "" "${CLR_BG}"

  ${NSD_CreateLabel} 0 0 100% 50 ""
  Pop $0
  SetCtlColors $0 "${CLR_WHITE}" "${CLR_HEADER}"
  SendMessage $0 ${WM_SETTEXT} 0 "STR:  Installation complete"

  ${NSD_CreateLabel} 20 70 440 60 ""
  Pop $0
  SetCtlColors $0 "" "${CLR_BG}"
  SendMessage $0 ${WM_SETTEXT} 0 "STR:${PRODUCTNAME} has been installed successfully.$\r$\n$\r$\nThank you for using Naixi!"

  ${NSD_CreateCheckBox} 20 150 400 14 ""
  Pop $0
  SendMessage $0 ${BM_SETCHECK} ${BST_CHECKED} 0
  SendMessage $0 ${WM_SETTEXT} 0 "STR:Run ${PRODUCTNAME} now"

  ${NSD_CreateButton} 300 180 100 24 ""
  Pop $0
  SetCtlColors $0 "${CLR_WHITE}" "${CLR_HEADER}"
  SendMessage $0 ${WM_SETTEXT} 0 "STR:Done"
  ${NSD_OnClick} $0 FinishApp
FunctionEnd

Function FinishApp
  Call RunMainBinary
  Quit
FunctionEnd

; ── Install section ──
Section "Main" SEC01
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
  ; Create shortcuts
  CreateDirectory "$SMPROGRAMS\${PRODUCTNAME}"
  CreateShortcut "$SMPROGRAMS\${PRODUCTNAME}\${PRODUCTNAME}.lnk" "$INSTDIR\${MAINBINARYNAME}.exe"
  CreateShortcut "$DESKTOP\${PRODUCTNAME}.lnk" "$INSTDIR\${MAINBINARYNAME}.exe"
  !ifmacrodef NSIS_HOOK_POSTINSTALL
    !insertmacro NSIS_HOOK_POSTINSTALL
  !endif
SectionEnd

; ── Uninstall section ──
Section Uninstall
  !insertmacro CheckIfAppIsRunning "${MAINBINARYNAME}.exe" "${PRODUCTNAME}"
  Delete "$INSTDIR\${MAINBINARYNAME}.exe"
  {{#each resources}}
    Delete "$INSTDIR\\{{this.[1]}}"
  {{/each}}
  {{#each binaries}}
    Delete "$INSTDIR\\{{this}}"
  {{/each}}
  Delete "$INSTDIR\uninstall.exe"
  RMDir "$INSTDIR"
  Delete "$SMPROGRAMS\${PRODUCTNAME}\${PRODUCTNAME}.lnk"
  RMDir "$SMPROGRAMS\${PRODUCTNAME}"
  Delete "$DESKTOP\${PRODUCTNAME}.lnk"
  DeleteRegKey SHCTX "${UNINSTKEY}"
SectionEnd

Function RunMainBinary
  nsis_tauri_utils::RunAsUser "$INSTDIR\${MAINBINARYNAME}.exe" ""
FunctionEnd

Function RestorePreviousInstallLocation
  ReadRegStr $4 SHCTX "${MANUPRODUCTKEY}" ""
  StrCmp $4 "" +2 0
    StrCpy $INSTDIR $4
FunctionEnd

Section WebView2
  ; WebView2 install logic from default template (preserved)
  ${If} ${RunningX64}
    ReadRegStr $4 HKLM "SOFTWARE\WOW6432Node\Microsoft\EdgeUpdate\Clients\${WEBVIEW2APPGUID}" "pv"
  ${Else}
    ReadRegStr $4 HKLM "SOFTWARE\Microsoft\EdgeUpdate\Clients\${WEBVIEW2APPGUID}" "pv"
  ${EndIf}
  ${If} $4 == ""
    ReadRegStr $4 HKCU "SOFTWARE\Microsoft\EdgeUpdate\Clients\${WEBVIEW2APPGUID}" "pv"
  ${EndIf}
  ${If} $4 == ""
    ${If} $UpdateMode <> 1
      DetailPrint "$(installingWebview2)"
    ${EndIf}
  ${EndIf}
SectionEnd

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

  !if "${DISPLAYLANGUAGESELECTOR}" == "true"
    !insertmacro MUI_LANGDLL_DISPLAY
  !endif

  !insertmacro SetContext

  ${If} $INSTDIR == "${PLACEHOLDER_INSTALL_DIR}"
    !if "${INSTALLMODE}" == "perMachine"
      ${If} ${RunningX64}
        StrCpy $INSTDIR "$PROGRAMFILES64\${PRODUCTNAME}"
      ${Else}
        StrCpy $INSTDIR "$PROGRAMFILES\${PRODUCTNAME}"
      ${EndIf}
    !else if "${INSTALLMODE}" == "currentUser"
      StrCpy $INSTDIR "$LOCALAPPDATA\${PRODUCTNAME}"
    !endif
    Call RestorePreviousInstallLocation
  ${EndIf}
FunctionEnd

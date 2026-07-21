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
!include nsDialogs.nsh
!include WinVer.nsh
!include FileFunc.nsh
!include x64.nsh
!include WordFunc.nsh
!include Sections.nsh
!include "utils.nsh"
!include "FileAssociation.nsh"
!include "Win\COM.nsh"
!include "Win\Propkey.nsh"
!include "StrFunc.nsh"
${StrCase}
${StrLoc}

; 默认简体中文（安装进度页等内置界面）
LoadLanguageFile "${NSISDIR}\Contrib\Language files\SimpChinese.nlf"

{{#if installer_hooks}}
!include "{{installer_hooks}}"
{{/if}}

; Tauri config vars
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

; Sakura pink palette
!define CLR_HEADER   0xD4537E
!define CLR_HEADER2  0x993556
!define CLR_BG       0xFBEAF0
!define CLR_WHITE    0xFFFFFF
!define CLR_TEXT     0x72243E
!define CLR_LIGHT    0xF4C0D1
!define CLR_BORDER   0xD3C1D0
!define CLR_GREEN    0x0F6E56
!define CLR_MUTED    0x888780
!define CLR_STEP_ON  0xD4537E
!define CLR_STEP_OFF 0xF4C0D1

; Variables
Var Dialog
Var StepLabel0
Var StepLabel1
Var StepLabel2
Var StepLabel3
Var StepLabel4
Var InstallPathText
Var DesktopCheck
Var RunCheck
Var hBanner
Var hBmpHandle
Var PassiveMode
Var UpdateMode
Var NoShortcutMode

Name "奶昔 · 桌面智能体"
BrandingText " "
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

; ─── Keep nsDialogs child at its default size (480x210 content area)
!macro ResizeToClient
  ; NSIS default custom-page dialog is already sized correctly.
  ; Do NOT try to resize the parent or the MUI chrome here - it breaks layout.
!macroend

; ─── Hide NSIS default wizard buttons & branding ───
!macro HideWizardChrome
  GetDlgItem $0 $HWNDPARENT 1
  ShowWindow $0 0
  GetDlgItem $0 $HWNDPARENT 2
  ShowWindow $0 0
  GetDlgItem $0 $HWNDPARENT 3
  ShowWindow $0 0
  ; Branding label / watermark
  GetDlgItem $0 $HWNDPARENT 1028
  ${If} $0 != 0
    ShowWindow $0 0
  ${EndIf}
  GetDlgItem $0 $HWNDPARENT 1038
  ${If} $0 != 0
    ShowWindow $0 0
  ${EndIf}
  GetDlgItem $0 $HWNDPARENT 1256
  ${If} $0 != 0
    ShowWindow $0 0
  ${EndIf}
!macroend

; ─── Macro: banner bitmap (480x110 fits default NSIS content width) ───
!macro ShowBanner
  ${NSD_CreateBitmap} 0 0 480 110 ""
  Pop $hBanner
  ${NSD_SetBitmap} $hBanner "$PLUGINSDIR\banner.bmp" $hBmpHandle
!macroend

; ─── Use NSIS default window size (custom pages fill the default content area) ───
Function .onGUIInit
  ; No window resizing - NSIS default MUI dialog size is stable.
FunctionEnd

; ─── Macro: step indicator bar (footer) ───
!macro CreateStepBar ACTIVE
  Push $0
  ${NSD_CreateLabel} 20 220 72 16 ""
  Pop $StepLabel0
  ${If} ${ACTIVE} >= 1
    SetCtlColors $StepLabel0 "${CLR_TEXT}" "${CLR_BG}"
  ${Else}
    SetCtlColors $StepLabel0 "${CLR_MUTED}" "${CLR_BG}"
  ${EndIf}
  SendMessage $StepLabel0 ${WM_SETTEXT} 0 "STR:1 欢迎"

  ${NSD_CreateLabel} 96 220 72 16 ""
  Pop $StepLabel1
  ${If} ${ACTIVE} >= 2
    SetCtlColors $StepLabel1 "${CLR_TEXT}" "${CLR_BG}"
  ${Else}
    SetCtlColors $StepLabel1 "${CLR_MUTED}" "${CLR_BG}"
  ${EndIf}
  SendMessage $StepLabel1 ${WM_SETTEXT} 0 "STR:2 位置"

  ${NSD_CreateLabel} 172 220 72 16 ""
  Pop $StepLabel2
  ${If} ${ACTIVE} >= 3
    SetCtlColors $StepLabel2 "${CLR_TEXT}" "${CLR_BG}"
  ${Else}
    SetCtlColors $StepLabel2 "${CLR_MUTED}" "${CLR_BG}"
  ${EndIf}
  SendMessage $StepLabel2 ${WM_SETTEXT} 0 "STR:3 安装"

  ${NSD_CreateLabel} 248 220 72 16 ""
  Pop $StepLabel3
  ${If} ${ACTIVE} >= 4
    SetCtlColors $StepLabel3 "${CLR_TEXT}" "${CLR_BG}"
  ${Else}
    SetCtlColors $StepLabel3 "${CLR_MUTED}" "${CLR_BG}"
  ${EndIf}
  SendMessage $StepLabel3 ${WM_SETTEXT} 0 "STR:4 完成"
  Pop $0
!macroend

; ─── Page 1: Welcome ───
Page custom fn_Welcome

Function fn_Welcome
  nsDialogs::Create 1018
  Pop $Dialog
  !insertmacro ResizeToClient
  !insertmacro HideWizardChrome
  SetCtlColors $Dialog "" "${CLR_BG}"

  !insertmacro ShowBanner

  ${NSD_CreateLabel} 20 124 440 24 ""
  Pop $0
  SetCtlColors $0 "${CLR_TEXT}" "${CLR_BG}"
  SendMessage $0 ${WM_SETTEXT} 0 "STR:欢迎安装 奶昔 · 桌面智能体 v${VERSION}"

  ${NSD_CreateLabel} 20 154 440 60 ""
  Pop $0
  SetCtlColors $0 "${CLR_TEXT}" "${CLR_BG}"
  SendMessage $0 ${WM_SETTEXT} 0 "STR:奶昔 是你的桌面 AI 智能体工作站，集成 AI 对话、工作流、自动化与知识库。$\r$\n$\r$\n点击「安装」开始，只需几步即可完成。"

  !insertmacro CreateStepBar 1

  ${NSD_CreateButton} 260 216 80 28 ""
  Pop $0
  SendMessage $0 ${WM_SETTEXT} 0 "STR:取消"
  ${NSD_OnClick} $0 fn_Cancel

  ${NSD_CreateButton} 350 216 100 28 ""
  Pop $0
  SetCtlColors $0 "${CLR_WHITE}" "${CLR_HEADER}"
  SendMessage $0 ${WM_SETTEXT} 0 "STR:安装 >>"
  ${NSD_OnClick} $0 fn_WelcomeInstall

  ${NSD_FreeBitmap} $hBanner
  nsDialogs::Show
FunctionEnd

Function fn_WelcomeInstall
  Pop $0
  Abort
FunctionEnd

Function fn_Cancel
  Abort
FunctionEnd

; ─── Page 2: Directory ───
Page custom fn_DirPage fn_DirPageLeave

Function fn_DirPage
  nsDialogs::Create 1018
  Pop $Dialog
  !insertmacro ResizeToClient
  !insertmacro HideWizardChrome
  SetCtlColors $Dialog "" "${CLR_BG}"

  !insertmacro ShowBanner

  ${NSD_CreateLabel} 20 124 440 24 ""
  Pop $0
  SetCtlColors $0 "${CLR_TEXT}" "${CLR_BG}"
  SendMessage $0 ${WM_SETTEXT} 0 "STR:选择安装位置"

  ${NSD_CreateText} 20 154 340 22 ""
  Pop $InstallPathText
  SendMessage $InstallPathText ${WM_SETTEXT} 0 "STR:$INSTDIR"

  ${NSD_CreateButton} 370 154 80 22 ""
  Pop $0
  SendMessage $0 ${WM_SETTEXT} 0 "STR:浏览..."
  ${NSD_OnClick} $0 fn_Browse

  ${NSD_CreateLabel} 20 184 440 16 ""
  Pop $0
  SetCtlColors $0 "${CLR_MUTED}" "${CLR_BG}"
  SendMessage $0 ${WM_SETTEXT} 0 "STR:所需磁盘空间：约 ${ESTIMATEDSIZE} MB"

  !insertmacro CreateStepBar 2

  ${NSD_CreateButton} 350 216 100 28 ""
  Pop $0
  SetCtlColors $0 "${CLR_WHITE}" "${CLR_HEADER}"
  SendMessage $0 ${WM_SETTEXT} 0 "STR:安装 >>"
  ${NSD_OnClick} $0 fn_DirInstall

  ${NSD_FreeBitmap} $hBanner
  nsDialogs::Show
FunctionEnd

Function fn_Browse
  ${NSD_GetText} $InstallPathText $0
  nsDialogs::SelectFolderDialog "选择安装文件夹" "$0"
  Pop $0
  ${If} $0 != error
    SendMessage $InstallPathText ${WM_SETTEXT} 0 "STR:$0"
    StrCpy $INSTDIR $0
  ${EndIf}
FunctionEnd

Function fn_DirInstall
  Pop $0
  ${NSD_GetText} $InstallPathText $INSTDIR
  Abort
FunctionEnd

Function fn_DirPageLeave
  ${NSD_GetText} $InstallPathText $INSTDIR
FunctionEnd

; ─── Page 3: InstFiles (runs Sections) ───
Page instfiles "" fn_InstFilesShow

Function fn_InstFilesShow
  !insertmacro HideWizardChrome
FunctionEnd

; ─── Page 4: Finish ───
Page custom fn_Finish

Function fn_Finish
  nsDialogs::Create 1018
  Pop $Dialog
  !insertmacro ResizeToClient
  !insertmacro HideWizardChrome
  SetCtlColors $Dialog "" "${CLR_BG}"

  !insertmacro ShowBanner

  ${NSD_CreateLabel} 20 124 440 50 ""
  Pop $0
  SetCtlColors $0 "${CLR_TEXT}" "${CLR_BG}"
  SendMessage $0 ${WM_SETTEXT} 0 "STR:奶昔 · 桌面智能体 v${VERSION} 安装完成！$\r$\n感谢使用，点击「完成」开始使用。"

  ${NSD_CreateCheckBox} 24 180 420 16 ""
  Pop $RunCheck
  SendMessage $RunCheck ${BM_SETCHECK} ${BST_CHECKED} 0
  SendMessage $RunCheck ${WM_SETTEXT} 0 "STR:立即运行 奶昔"

  ${NSD_CreateCheckBox} 24 204 420 16 ""
  Pop $DesktopCheck
  SendMessage $DesktopCheck ${BM_SETCHECK} ${BST_CHECKED} 0
  SendMessage $DesktopCheck ${WM_SETTEXT} 0 "STR:创建桌面快捷方式"

  !insertmacro CreateStepBar 4

  ${NSD_CreateButton} 350 216 100 28 ""
  Pop $0
  SetCtlColors $0 "${CLR_WHITE}" "${CLR_HEADER}"
  SendMessage $0 ${WM_SETTEXT} 0 "STR:完成"
  ${NSD_OnClick} $0 fn_Done

  ${NSD_FreeBitmap} $hBanner
  nsDialogs::Show
FunctionEnd

Function fn_Done
  Pop $0
  ${NSD_GetState} $DesktopCheck $0
  ${If} $0 = ${BST_CHECKED}
    CreateShortcut "$DESKTOP\${PRODUCTNAME}.lnk" "$INSTDIR\${MAINBINARYNAME}.exe"
  ${EndIf}
  ${NSD_GetState} $RunCheck $0
  ${If} $0 = ${BST_CHECKED}
    nsis_tauri_utils::RunAsUser "$INSTDIR\${MAINBINARYNAME}.exe" ""
  ${EndIf}
  Quit
FunctionEnd

; ─── Languages (disabled - custom nsDialogs pages don't need MUI) ───
{{#if false}}
{{#each languages}}
!insertmacro MUI_LANGUAGE "{{this}}"
{{/each}}
{{#each language_files}}
  !include "{{this}}"
{{/each}}
{{/if}}

; ════════════════════════════════════════════
; Sections (install logic)
; ════════════════════════════════════════════

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
  ; Shortcuts
  CreateDirectory "$SMPROGRAMS\${PRODUCTNAME}"
  CreateShortcut "$SMPROGRAMS\${PRODUCTNAME}\${PRODUCTNAME}.lnk" "$INSTDIR\${MAINBINARYNAME}.exe"
  !ifmacrodef NSIS_HOOK_POSTINSTALL
    !insertmacro NSIS_HOOK_POSTINSTALL
  !endif
SectionEnd

Section WebView2
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
      DetailPrint "Installing WebView2..."
    ${EndIf}
  ${EndIf}
SectionEnd

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

; ════════════════════════════════════════════
; Functions
; ════════════════════════════════════════════

Function RestorePreviousInstallLocation
  ReadRegStr $4 SHCTX "${MANUPRODUCTKEY}" ""
  StrCmp $4 "" +2 0
    StrCpy $INSTDIR $4
FunctionEnd

Function .onInit
  InitPluginsDir
  SetOutPath $PLUGINSDIR
  File "D:\naixi_desktop\src-tauri\installer\banner.bmp"
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
    MessageBox MB_OK "Naixi 安装程序默认使用简体中文。"
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

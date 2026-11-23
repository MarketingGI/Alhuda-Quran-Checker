; Installer Alhuda Quran Checker (NSIS 3)
Unicode true
SetCompressor /SOLID lzma
SetCompressorDictSize 64

!define APPNAME "Alhuda Quran Checker"
!define APPVER "1.1.0"
!define PUBLISHER "Gema Insani"
!define UNINSTKEY "Software\Microsoft\Windows\CurrentVersion\Uninstall\AlhudaQuranChecker"

Name "${APPNAME}"
OutFile "Alhuda_Quran_Checker_Setup_${APPVER}.exe"
InstallDir "$LOCALAPPDATA\Programs\${APPNAME}"
InstallDirRegKey HKCU "Software\AlhudaQuranChecker" "InstallDir"
RequestExecutionLevel user
BrandingText "${APPNAME} ${APPVER}"

VIProductVersion "${APPVER}.0"
VIAddVersionKey "ProductName" "${APPNAME}"
VIAddVersionKey "CompanyName" "${PUBLISHER}"
VIAddVersionKey "FileVersion" "${APPVER}"
VIAddVersionKey "ProductVersion" "${APPVER}"
VIAddVersionKey "FileDescription" "Installer ${APPNAME}"
VIAddVersionKey "LegalCopyright" "${PUBLISHER}"

!include "MUI2.nsh"
!define MUI_ICON "alhuda.ico"
!define MUI_UNICON "alhuda.ico"
!define MUI_ABORTWARNING
!define MUI_WELCOMEPAGE_TEXT "Program ini akan memasang ${APPNAME} ${APPVER} di komputer ini.$\r$\n$\r$\nPython dan semua library sudah termasuk. Saat pertama dibuka, aplikasi perlu internet sekali untuk meminta aktivasi dari pemilik.$\r$\n$\r$\nKlik Next untuk melanjutkan."
!define MUI_FINISHPAGE_RUN
!define MUI_FINISHPAGE_RUN_TEXT "Jalankan ${APPNAME} sekarang"
!define MUI_FINISHPAGE_RUN_FUNCTION RunApp

!insertmacro MUI_PAGE_WELCOME
!insertmacro MUI_PAGE_DIRECTORY
!insertmacro MUI_PAGE_INSTFILES
!insertmacro MUI_PAGE_FINISH
!insertmacro MUI_UNPAGE_CONFIRM
!insertmacro MUI_UNPAGE_INSTFILES
!insertmacro MUI_LANGUAGE "Indonesian"
!insertmacro MUI_LANGUAGE "English"

Function RunApp
  ExecShell "open" "$INSTDIR\${APPNAME}.bat"
FunctionEnd

Section "Install"
  SetOutPath "$INSTDIR"
  ; bersihkan versi lama (hanya folder milik aplikasi ini)
  RMDir /r "$INSTDIR\runtime"
  RMDir /r "$INSTDIR\app"

  File "${APPNAME}.bat"
  File "alhuda.ico"
  File /r "runtime"
  File /r "app"

  WriteUninstaller "$INSTDIR\Uninstall.exe"

  CreateDirectory "$SMPROGRAMS\${APPNAME}"
  CreateShortcut "$SMPROGRAMS\${APPNAME}\${APPNAME}.lnk" "$INSTDIR\${APPNAME}.bat" "" "$INSTDIR\alhuda.ico" 0
  CreateShortcut "$SMPROGRAMS\${APPNAME}\Uninstall ${APPNAME}.lnk" "$INSTDIR\Uninstall.exe"
  CreateShortcut "$DESKTOP\${APPNAME}.lnk" "$INSTDIR\${APPNAME}.bat" "" "$INSTDIR\alhuda.ico" 0

  WriteRegStr HKCU "Software\AlhudaQuranChecker" "InstallDir" "$INSTDIR"
  WriteRegStr HKCU "${UNINSTKEY}" "DisplayName" "${APPNAME}"
  WriteRegStr HKCU "${UNINSTKEY}" "DisplayVersion" "${APPVER}"
  WriteRegStr HKCU "${UNINSTKEY}" "Publisher" "${PUBLISHER}"
  WriteRegStr HKCU "${UNINSTKEY}" "DisplayIcon" "$INSTDIR\alhuda.ico"
  WriteRegStr HKCU "${UNINSTKEY}" "InstallLocation" "$INSTDIR"
  WriteRegStr HKCU "${UNINSTKEY}" "UninstallString" "$\"$INSTDIR\Uninstall.exe$\""
  WriteRegDWORD HKCU "${UNINSTKEY}" "NoModify" 1
  WriteRegDWORD HKCU "${UNINSTKEY}" "NoRepair" 1
SectionEnd

Section "Uninstall"
  Delete "$DESKTOP\${APPNAME}.lnk"
  RMDir /r "$SMPROGRAMS\${APPNAME}"
  RMDir /r "$INSTDIR\runtime"
  RMDir /r "$INSTDIR\app"
  Delete "$INSTDIR\${APPNAME}.bat"
  Delete "$INSTDIR\alhuda.ico"
  Delete "$INSTDIR\Uninstall.exe"
  RMDir "$INSTDIR"
  DeleteRegKey HKCU "${UNINSTKEY}"
  DeleteRegKey HKCU "Software\AlhudaQuranChecker"
SectionEnd

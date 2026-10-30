; Compile with Inno Setup 6 after scripts/build_release.py.
; Pass /DAppVersion=x.y.z and /DBundleDir="absolute path to AtelierPhoto.dist" to ISCC
; ("Construire Atelier Photo (Windows).cmd" does it).
#ifndef AppVersion
  #define AppVersion "0.4.0"
#endif
#ifndef BundleDir
  #define BundleDir "..\dist\" + AppVersion + "\AtelierPhoto.dist"
#endif
[Setup]
AppId={{03D9A7F4-FC1B-4563-9C14-05D456760E50}
AppName=Atelier Photo
AppVersion={#AppVersion}
DefaultDirName={localappdata}\Programs\AtelierPhoto
DefaultGroupName=Atelier Photo
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
OutputDir=..\dist
OutputBaseFilename=AtelierPhoto-{#AppVersion}-Windows-x64-Setup
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
UninstallDisplayIcon={app}\AtelierPhoto.exe
SetupIconFile=..\atelier\assets\app-icon.ico
AppMutex=AtelierPhoto.Application.03D9A7F4
[Languages]
Name: "french"; MessagesFile: "compiler:Languages\French.isl"
[Messages]
french.ConfirmUninstall=Voulez-vous désinstaller %1 et supprimer définitivement tous ses profils, apprentissages, lots et aperçus ?%n%nLes photos originales et les fichiers exportés dans vos dossiers personnels seront conservés.
[Files]
Source: "{#BundleDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
[Icons]
Name: "{group}\Atelier Photo"; Filename: "{app}\AtelierPhoto.exe"
Name: "{autodesktop}\Atelier Photo"; Filename: "{app}\AtelierPhoto.exe"; Tasks: desktopicon
[Tasks]
Name: desktopicon; Description: "Créer un raccourci sur le Bureau"; Flags: unchecked
[Run]
Filename: "{app}\AtelierPhoto.exe"; Description: "Lancer Atelier Photo"; Flags: nowait postinstall skipifsilent
[UninstallDelete]
; Runtime data is not covered by the installer's file log. Delete only this
; application's dedicated data directory, never {app}\* or a user photo folder.
; This section runs only on uninstall: installing an update preserves profiles.
Type: filesandordirs; Name: "{localappdata}\AtelierPhoto"

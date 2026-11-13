#ifndef AppVersion
  #define AppVersion "1.1.0"
#endif
#ifndef BundleDir
  #define BundleDir "..\build\windows\CorTranscript"
#endif
#ifndef OutputDir
  #define OutputDir "..\dist"
#endif

[Setup]
AppId={{80435F86-5C59-4B15-9883-EFF77AA1606B}
AppName=CorTranscript
AppVersion={#AppVersion}
AppPublisher=Louis Corbet
AppPublisherURL=https://github.com/LouisCorbet/CorTranscript
DefaultDirName={autopf}\CorTranscript
DefaultGroupName=CorTranscript
DisableProgramGroupPage=yes
OutputDir={#OutputDir}
OutputBaseFilename=CorTranscript-Setup-{#AppVersion}
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0
PrivilegesRequired=admin
Compression=lzma2/fast
SolidCompression=yes
WizardStyle=modern
UninstallDisplayIcon={app}\CorTranscript.exe
CloseApplications=yes
SetupLogging=yes

[Languages]
Name: "french"; MessagesFile: "compiler:Languages\French.isl"
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "Créer un raccourci sur le Bureau"; Flags: unchecked

; Remove only application-owned directories when upgrading. User recordings
; live under LOCALAPPDATA and are intentionally outside this cleanup.
[InstallDelete]
Type: filesandordirs; Name: "{app}\runtime"
Type: filesandordirs; Name: "{app}\app"
Type: filesandordirs; Name: "{app}\models"
Type: filesandordirs; Name: "{app}\bin"
Type: filesandordirs; Name: "{app}\_internal"
Type: filesandordirs; Name: "{app}\licenses"

[Files]
Source: "{#BundleDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\CorTranscript"; Filename: "{app}\CorTranscript.exe"; WorkingDir: "{app}"
Name: "{autodesktop}\CorTranscript"; Filename: "{app}\CorTranscript.exe"; WorkingDir: "{app}"; Tasks: desktopicon

[Run]
Filename: "{app}\CorTranscript.exe"; Description: "Lancer CorTranscript"; Flags: nowait postinstall skipifsilent runasoriginaluser

[Code]
var
  RuntimeNeedsRestart: Boolean;

procedure CurStepChanged(CurStep: TSetupStep);
var
  ResultCode: Integer;
begin
  if CurStep = ssPostInstall then
  begin
    if not Exec(ExpandConstant('{app}\vc_redist.x64.exe'), '/install /quiet /norestart', '', SW_HIDE, ewWaitUntilTerminated, ResultCode) then
      RaiseException('Impossible de démarrer le runtime Microsoft Visual C++.');
    if (ResultCode <> 0) and (ResultCode <> 1638) and (ResultCode <> 3010) then
      RaiseException('Installation du runtime Microsoft Visual C++ échouée : ' + IntToStr(ResultCode));
    RuntimeNeedsRestart := ResultCode = 3010;
  end;
end;

function NeedRestart(): Boolean;
begin
  Result := RuntimeNeedsRestart;
end;

; A.R.C.H.I.E. Node — Inno Setup Installer Script
; Produces ARCHIE-Node-Setup.exe
; Phase 1: Installs files + checks Docker. Phase 2: setup.ps1 handles configuration.

[Setup]
AppId={{7E33E91B-A868-D446-BCDE-ARCHIENODE01}
AppName=A.R.C.H.I.E. Node
AppVersion=4.0.0
AppVerName=A.R.C.H.I.E. Node v4.0.0
AppPublisher=Kytran Empowerment
AppPublisherURL=https://kytranempowerment.com
AppSupportURL=https://kytranempowerment.com
DefaultDirName=C:\ARCHIE-Node
DisableDirPage=yes
DefaultGroupName=Kytran Empowerment
OutputDir=dist
OutputBaseFilename=ARCHIE-Node-Setup
SetupIconFile=archie_icon.ico
UninstallDisplayIcon={app}\archie_icon.ico
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
PrivilegesRequired=admin
ArchitecturesAllowed=x64
MinVersion=10.0

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Files]
; PowerShell setup script (replaces Python installer)
Source: "setup.ps1"; DestDir: "{app}"; Flags: ignoreversion
; Docker compose and helper scripts
Source: "..\docker-compose.node.yml"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\start.bat"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\stop.bat"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\update.bat"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\cleanup.bat"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\heartbeat.sh"; DestDir: "{app}"; Flags: ignoreversion
; Icon
Source: "archie_icon.ico"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{group}\A.R.C.H.I.E. Node Setup"; Filename: "powershell.exe"; Parameters: "-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File ""{app}\setup.ps1"""; IconFilename: "{app}\archie_icon.ico"; WorkingDir: "{app}"
Name: "{group}\Start Node"; Filename: "{app}\start.bat"; IconFilename: "{app}\archie_icon.ico"
Name: "{group}\Stop Node"; Filename: "{app}\stop.bat"; IconFilename: "{app}\archie_icon.ico"
Name: "{group}\Update Node"; Filename: "{app}\update.bat"; IconFilename: "{app}\archie_icon.ico"
Name: "{group}\Uninstall A.R.C.H.I.E. Node"; Filename: "{uninstallexe}"
Name: "{commondesktop}\A.R.C.H.I.E. Node"; Filename: "powershell.exe"; Parameters: "-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File ""{app}\setup.ps1"""; IconFilename: "{app}\archie_icon.ico"; WorkingDir: "{app}"

[Run]
; Launch the PowerShell setup GUI after Inno Setup finishes
Filename: "powershell.exe"; Parameters: "-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File ""{app}\setup.ps1"""; Description: "Launch A.R.C.H.I.E. Node Setup"; Flags: nowait postinstall skipifsilent runascurrentuser; WorkingDir: "{app}"

[UninstallRun]
; Stop Docker containers on uninstall
Filename: "docker"; Parameters: "compose -f ""{app}\docker-compose.yml"" down --remove-orphans -v"; Flags: runhidden waituntilterminated

[UninstallDelete]
Type: filesandordirs; Name: "{app}\*.json"
Type: filesandordirs; Name: "{app}\.env"
Type: filesandordirs; Name: "{app}\docker-compose.yml"

[Registry]
Root: HKLM; Subkey: "SOFTWARE\Kytran Empowerment\ARCHIE Node"; ValueType: string; ValueName: "InstallDir"; ValueData: "{app}"; Flags: uninsdeletekey
Root: HKLM; Subkey: "SOFTWARE\Kytran Empowerment\ARCHIE Node"; ValueType: string; ValueName: "Version"; ValueData: "4.0.0"; Flags: uninsdeletekey

[Code]
function DockerInstalled(): Boolean;
var
  ResultCode: Integer;
begin
  Result := Exec('docker', '--version', '', SW_HIDE, ewWaitUntilTerminated, ResultCode) and (ResultCode = 0);
  if not Result then
    Result := FileExists(ExpandConstant('{commonpf}\Docker\Docker\Docker Desktop.exe'));
end;

function InitializeSetup(): Boolean;
begin
  Result := True;
  if FileExists('C:\ARCHIE-Node\setup.ps1') then
  begin
    if MsgBox('A.R.C.H.I.E. Node is already installed. Do you want to upgrade?',
              mbConfirmation, MB_YESNO) = IDNO then
      Result := False;
  end;
end;

procedure CurStepChanged(CurStep: TSetupStep);
begin
  if CurStep = ssPostInstall then
  begin
    if not DockerInstalled() then
    begin
      MsgBox('Docker Desktop is not installed.' + #13#10 + #13#10 +
             'The setup wizard will attempt to install it automatically.' + #13#10 +
             'If it fails, please install Docker Desktop manually from:' + #13#10 +
             'https://www.docker.com/products/docker-desktop/',
             mbInformation, MB_OK);
    end;
  end;
end;

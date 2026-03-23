; A.R.C.H.I.E. Node — Inno Setup Installer Script
; Produces ARCHIE-Node-Setup.exe
; Docker-only deployment — no NSSM, no services. Docker Desktop auto-starts containers.

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
Source: "dist\ARCHIE-Node.exe"; DestDir: "{app}"; Flags: ignoreversion
Source: "archie_icon.ico"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{group}\A.R.C.H.I.E. Node"; Filename: "{app}\ARCHIE-Node.exe"; IconFilename: "{app}\archie_icon.ico"
Name: "{group}\Uninstall A.R.C.H.I.E. Node"; Filename: "{uninstallexe}"
Name: "{commondesktop}\A.R.C.H.I.E. Node"; Filename: "{app}\ARCHIE-Node.exe"; IconFilename: "{app}\archie_icon.ico"

[Run]
; Launch the installer GUI after setup
Filename: "{app}\ARCHIE-Node.exe"; Description: "Launch A.R.C.H.I.E. Node"; Flags: nowait postinstall skipifsilent

[UninstallRun]
; Stop Docker containers on uninstall
Filename: "docker"; Parameters: "compose -f ""{app}\docker-compose.yml"" down --remove-orphans -v"; Flags: runhidden waituntilterminated

[UninstallDelete]
Type: filesandordirs; Name: "{app}\*.json"
Type: filesandordirs; Name: "{app}\.env"
Type: filesandordirs; Name: "{app}\docker-compose.yml"
Type: filesandordirs; Name: "{app}\*.bat"
Type: filesandordirs; Name: "{app}\*.command"

[Registry]
Root: HKLM; Subkey: "SOFTWARE\Kytran Empowerment\ARCHIE Node"; ValueType: string; ValueName: "InstallDir"; ValueData: "{app}"; Flags: uninsdeletekey
Root: HKLM; Subkey: "SOFTWARE\Kytran Empowerment\ARCHIE Node"; ValueType: string; ValueName: "Version"; ValueData: "4.0.0"; Flags: uninsdeletekey

[Code]
function InitializeSetup(): Boolean;
begin
  Result := True;
  if FileExists('C:\ARCHIE-Node\ARCHIE-Node.exe') then
  begin
    if MsgBox('A.R.C.H.I.E. Node is already installed. Do you want to upgrade?',
              mbConfirmation, MB_YESNO) = IDNO then
      Result := False;
  end;
end;

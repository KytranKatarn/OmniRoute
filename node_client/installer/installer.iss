; A.R.C.H.I.E. Node — Inno Setup Installer Script
; Produces ARCHIE-Node-Setup.exe
; Uses NSSM to register BEACON as a Windows Service (tkinter GUI is not a native service binary)

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
Source: "nssm.exe"; DestDir: "{app}"; Flags: ignoreversion
Source: "archie_icon.ico"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{group}\A.R.C.H.I.E. Node"; Filename: "{app}\ARCHIE-Node.exe"; IconFilename: "{app}\archie_icon.ico"
Name: "{group}\Uninstall A.R.C.H.I.E. Node"; Filename: "{uninstallexe}"
Name: "{commondesktop}\A.R.C.H.I.E. Node"; Filename: "{app}\ARCHIE-Node.exe"; IconFilename: "{app}\archie_icon.ico"

[Run]
; Register BEACON as a Windows Service using NSSM (wraps the GUI exe as a proper service)
Filename: "{app}\nssm.exe"; Parameters: "install ARCHIEBeacon ""{app}\ARCHIE-Node.exe"""; Flags: runhidden waituntilterminated; StatusMsg: "Registering BEACON service..."
Filename: "{app}\nssm.exe"; Parameters: "set ARCHIEBeacon DisplayName ""A.R.C.H.I.E. BEACON"""; Flags: runhidden waituntilterminated
Filename: "{app}\nssm.exe"; Parameters: "set ARCHIEBeacon Description ""A.R.C.H.I.E. Node fleet agent — connects to Starbase hub"""; Flags: runhidden waituntilterminated
Filename: "{app}\nssm.exe"; Parameters: "set ARCHIEBeacon Start SERVICE_AUTO_START"; Flags: runhidden waituntilterminated
; Offer to launch the app after install
Filename: "{app}\ARCHIE-Node.exe"; Description: "Launch A.R.C.H.I.E. Node"; Flags: nowait postinstall skipifsilent

[UninstallRun]
; Stop and remove the BEACON service using NSSM
Filename: "{app}\nssm.exe"; Parameters: "stop ARCHIEBeacon"; Flags: runhidden waituntilterminated
Filename: "{app}\nssm.exe"; Parameters: "remove ARCHIEBeacon confirm"; Flags: runhidden waituntilterminated
; Stop Docker containers
Filename: "docker"; Parameters: "compose -f ""{app}\docker-compose.yml"" down"; Flags: runhidden waituntilterminated

[UninstallDelete]
Type: filesandordirs; Name: "{app}\*.json"
Type: filesandordirs; Name: "{app}\.env"
Type: filesandordirs; Name: "{app}\docker-compose.yml"

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

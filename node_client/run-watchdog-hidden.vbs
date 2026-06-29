' run-watchdog-hidden.vbs — launches ArchieDockerWatchdog fully hidden (no conhost flash).
' Background: the scheduled task ran `powershell -WindowStyle Hidden -File docker-watchdog.ps1`
' INTERACTIVELY (it must, so docker.exe can reach Docker Desktop's named pipe in the user
' session). But for an interactive task, conhost.exe creates a console window BEFORE PowerShell
' can apply -WindowStyle Hidden, so a window flashed every 5 min. wscript.exe has no console of
' its own, and Run(cmd, 0, False) launches PowerShell with window style 0 (hidden) + no wait =
' truly invisible, still in the interactive session. See node_client/docker-watchdog.ps1, KB #275990.
CreateObject("WScript.Shell").Run "powershell -NoProfile -ExecutionPolicy Bypass -File C:\Users\Famil\archie\docker-watchdog.ps1", 0, False

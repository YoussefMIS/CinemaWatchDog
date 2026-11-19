# Starts Cinema WatchDog automatically (minimised) every time you log in to Windows.
# Run once:  powershell -ExecutionPolicy Bypass -File .\install-autostart.ps1
# Undo:      Unregister-ScheduledTask -TaskName "CinemaWatchDog" -Confirm:$false
$dir = Split-Path -Parent $MyInvocation.MyCommand.Path
$py  = Join-Path $dir ".venv\Scripts\pythonw.exe"
if (-not (Test-Path $py)) { Write-Host "Run start.bat once first (it creates .venv)."; exit 1 }
$action  = New-ScheduledTaskAction -Execute $py -Argument "app.py" -WorkingDirectory $dir
$trigger = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
            -ExecutionTimeLimit ([TimeSpan]::Zero) -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1)
Register-ScheduledTask -TaskName "CinemaWatchDog" -Action $action -Trigger $trigger -Settings $settings -Force | Out-Null
Start-ScheduledTask -TaskName "CinemaWatchDog"
Write-Host "Installed. Cinema WatchDog now runs in the background at http://localhost:5000"

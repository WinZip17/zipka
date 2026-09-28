# Creates a Desktop shortcut that runs start_zipka.bat
$ErrorActionPreference = "Stop"
$project = Split-Path -Parent $MyInvocation.MyCommand.Path
$bat = Join-Path $project "start_zipka.bat"
$desktop = [Environment]::GetFolderPath("Desktop")
# "Zipka" in Russian via Unicode to avoid encoding issues
$name = ([string]::new([char]0x0417) + [string]::new([char]0x0438) + [string]::new([char]0x043F) + [string]::new([char]0x043A) + [string]::new([char]0x0430))
$lnkPath = Join-Path $desktop ($name + ".lnk")

$shell = New-Object -ComObject WScript.Shell
$shortcut = $shell.CreateShortcut($lnkPath)
$shortcut.TargetPath = $bat
$shortcut.WorkingDirectory = $project
$shortcut.WindowStyle = 1
$shortcut.Description = "Zipka local agent - Web UI"
$shortcut.IconLocation = "shell32.dll,13"
$shortcut.Save()

Write-Host "Shortcut created: $lnkPath"
Write-Host "Double-click opens Web UI at http://127.0.0.1:8765"

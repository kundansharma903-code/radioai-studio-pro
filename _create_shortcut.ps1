$desktop = [Environment]::GetFolderPath('Desktop')
$lnkPath = Join-Path $desktop 'RadioAI Studio Pro.lnk'

$ws = New-Object -ComObject WScript.Shell
$lnk = $ws.CreateShortcut($lnkPath)
$lnk.TargetPath = 'C:\Users\hp\AppData\Local\Programs\Python\Launcher\pyw.exe'
$lnk.Arguments = 'main.py'
$lnk.WorkingDirectory = 'E:\RadioAI_v2'
$lnk.IconLocation = 'C:\Users\hp\AppData\Local\Programs\Python\Launcher\pyw.exe,0'
$lnk.Description = 'RadioAI Studio Pro v2.0 — Broadcast Automation'
$lnk.WindowStyle = 1
$lnk.Save()

Write-Host "Shortcut created at: $lnkPath"
Get-Item $lnkPath | Select-Object FullName, Length, LastWriteTime

# Регистрация задачи планировщика: автозапуск elevated-агента при входе в систему.
$ErrorActionPreference = 'Stop'
$cmd = 'D:\ЗАИ\esp32-pc-monitor\pc-agent\run_agent.cmd'
$act  = New-ScheduledTaskAction -Execute 'cmd.exe' -Argument "/c `"$cmd`"" -WorkingDirectory 'D:\ЗАИ\esp32-pc-monitor\pc-agent'
$prin = New-ScheduledTaskPrincipal -UserId $env:USERNAME -LogonType Interactive -RunLevel Highest
$set  = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable -ExecutionTimeLimit 0
$trg  = New-ScheduledTaskTrigger -AtLogOn
Register-ScheduledTask -TaskName 'ZaiPcAgent' -Action $act -Principal $prin -Settings $set -Trigger $trg -Force | Out-Null
# запустить сразу, не дожидаясь следующего логина
Start-ScheduledTask -TaskName 'ZaiPcAgent'
Write-Output 'task registered+started: ZaiPcAgent'

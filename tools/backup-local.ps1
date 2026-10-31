# Backup for a service running without Docker (Windows): PostgreSQL dump plus the
# avatar and attachment folders, kept for -KeepDays days.
#   powershell -ExecutionPolicy Bypass -File tools\backup-local.ps1 -Database room_booking_v2 -User postgres
# Put the password into %APPDATA%\postgresql\pgpass.conf (or $env:PGPASSWORD) so it runs unattended,
# and add the command to Windows Task Scheduler to run it every day.
param(
    [string]$Database = "room_booking_v2",
    [string]$User = "postgres",
    [string]$DbHost = "localhost",
    [int]$Port = 5432,
    [string]$BackupDir = (Join-Path $PSScriptRoot "..\backups"),
    [int]$KeepDays = 14
)
$ErrorActionPreference = "Stop"
$backend = Join-Path $PSScriptRoot "..\backend"
$stamp = Get-Date -Format "yyyyMMdd_HHmmss"
New-Item -ItemType Directory -Force -Path $BackupDir | Out-Null
$dump = Join-Path $BackupDir "room_booking_$stamp.dump"
$files = Join-Path $BackupDir "room_booking_files_$stamp.zip"

& pg_dump -h $DbHost -p $Port -U $User -d $Database -Fc -f "$dump.part"
if ($LASTEXITCODE -ne 0) { throw "pg_dump failed" }
& pg_restore --list "$dump.part" | Out-Null
if ($LASTEXITCODE -ne 0) { throw "The dump cannot be read back" }
Move-Item "$dump.part" $dump

$folders = @("uploads", "storage\attachments") | ForEach-Object { Join-Path $backend $_ } | Where-Object { Test-Path $_ }
if ($folders) { Compress-Archive -Path $folders -DestinationPath $files -Force }

Get-Date -Format o | Set-Content (Join-Path $BackupDir "LAST_SUCCESS")
Get-ChildItem $BackupDir -Filter "room_booking_*" | Where-Object { $_.LastWriteTime -lt (Get-Date).AddDays(-$KeepDays) } | Remove-Item
Write-Output "Backup $stamp done: $dump"

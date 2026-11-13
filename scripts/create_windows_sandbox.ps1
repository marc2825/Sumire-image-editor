# Open Windows Sandbox (no network) with a copy of the extracted distribution folder.
param(
    [string]$Distribution = (Get-ChildItem (Join-Path (Split-Path $PSScriptRoot -Parent) "dist") -Directory -Filter "Sumire-v*-win64" | Select-Object -Last 1).FullName,
    [switch]$Launch
)

$ErrorActionPreference = "Stop"
$folder = (Resolve-Path $Distribution).Path
if (-not (Test-Path (Join-Path $folder "sumire.exe")) -or -not (Test-Path (Join-Path $folder "_internal"))) {
    throw "Pass the extracted distribution folder (sumire.exe and _internal)."
}
# Run a copy of the folder in the disposable guest; keep the host distribution read-only.
$startup = @'
$ErrorActionPreference = 'Stop'
$root = Join-Path $env:USERPROFILE 'Desktop\Sumire-Test'
New-Item -ItemType Directory -Force $root | Out-Null
Copy-Item 'C:\SumireReadOnly\*' $root -Recurse
Add-Type -AssemblyName System.Drawing
$bitmap = New-Object System.Drawing.Bitmap 640,480
$graphics = [System.Drawing.Graphics]::FromImage($bitmap)
$graphics.Clear([System.Drawing.Color]::White)
for ($x = 0; $x -lt 640; $x += 8) {
    $graphics.FillRectangle([System.Drawing.Brushes]::DarkSlateGray, $x, 0, 4, 480)
}
$sample = Join-Path $root 'sample.png'
$bitmap.Save($sample, [System.Drawing.Imaging.ImageFormat]::Png)
$graphics.Dispose()
$bitmap.Dispose()
Start-Process (Join-Path $root 'sumire.exe') -ArgumentList @('--open', ('"' + $sample + '"'))
'@
$encoded = [Convert]::ToBase64String([Text.Encoding]::Unicode.GetBytes($startup))
$escapedFolder = [Security.SecurityElement]::Escape($folder)
$configuration = @"
<Configuration>
  <Networking>Disable</Networking>
  <MappedFolders>
    <MappedFolder>
      <HostFolder>$escapedFolder</HostFolder>
      <SandboxFolder>C:\SumireReadOnly</SandboxFolder>
      <ReadOnly>true</ReadOnly>
    </MappedFolder>
  </MappedFolders>
  <LogonCommand>
    <Command>powershell.exe -NoProfile -ExecutionPolicy Bypass -EncodedCommand $encoded</Command>
  </LogonCommand>
</Configuration>
"@
$target = Join-Path $folder "sumire-offline.wsb"
[IO.File]::WriteAllText($target, $configuration, [Text.UTF8Encoding]::new($false))
Write-Host "Created: $target"
if ($Launch) { Start-Process $target }

$ErrorActionPreference = "Stop"

$dxWrapperVersion = "1.8.8600.25"
$dxWrapperArchiveSha256 = "3894368ebce69f348d08e189c2f0818c49aa3b18ad01e06348743bf6a29af97a"
$dxWrapperFiles = @{
    "Stub\d3d9.dll" = "7c843006f81983617a37f57d7fb615d23bda99860b71ab745f2b0cea6ab00474"
    "dxwrapper.dll" = "ec42e51cbb4408518d6348706557b18ef50a87485c8bfa1839c895123fa3295f"
    "License.txt" = "8a586c8e0299cb3b141d589d9e933f58a5abb781e6c8775793ff21872ffee31c"
}

$repository = Split-Path -Parent $PSScriptRoot
$output = Join-Path $repository "build\native"
$vendor = Join-Path $repository "build\vendor\dxwrapper-$dxWrapperVersion"
$archive = Join-Path $vendor "dxwrapper.zip"
$extracted = Join-Path $vendor "extracted"
$url = "https://github.com/elishacloud/dxwrapper/releases/download/v$dxWrapperVersion/dxwrapper.zip"

function Get-Sha256([string]$Path) {
    $stream = [IO.File]::OpenRead($Path)
    try {
        $digest = [Security.Cryptography.SHA256]::Create().ComputeHash($stream)
        return ([BitConverter]::ToString($digest) -replace "-", "").ToLowerInvariant()
    }
    finally {
        $stream.Dispose()
    }
}

New-Item -ItemType Directory -Force -Path $output, $vendor | Out-Null

$needsDownload = $true
if (Test-Path -LiteralPath $archive -PathType Leaf) {
    $needsDownload = (Get-Sha256 $archive) -ne $dxWrapperArchiveSha256
}
if ($needsDownload) {
    $temporaryArchive = "$archive.download"
    Invoke-WebRequest -Uri $url -OutFile $temporaryArchive
    $actual = Get-Sha256 $temporaryArchive
    if ($actual -ne $dxWrapperArchiveSha256) {
        Remove-Item -LiteralPath $temporaryArchive -Force
        throw "DxWrapper archive failed SHA-256 verification: $actual"
    }
    Move-Item -LiteralPath $temporaryArchive -Destination $archive -Force
}

if (Test-Path -LiteralPath $extracted) {
    Remove-Item -LiteralPath $extracted -Recurse -Force
}
Expand-Archive -LiteralPath $archive -DestinationPath $extracted

foreach ($relative in $dxWrapperFiles.Keys) {
    $source = Join-Path $extracted $relative
    $actual = Get-Sha256 $source
    if ($actual -ne $dxWrapperFiles[$relative]) {
        throw "DxWrapper file failed SHA-256 verification: $relative"
    }
}

Copy-Item -LiteralPath (Join-Path $extracted "Stub\d3d9.dll") -Destination (Join-Path $output "asi_d3d9.dll") -Force
Copy-Item -LiteralPath (Join-Path $extracted "dxwrapper.dll") -Destination (Join-Path $output "asi_dxwrapper.dll") -Force
Copy-Item -LiteralPath (Join-Path $extracted "License.txt") -Destination (Join-Path $output "asi_LICENCE-dxwrapper.txt") -Force
Copy-Item -LiteralPath (Join-Path $repository "src\multiplayer_src\dxwrapper.ini") -Destination (Join-Path $output "asi_dxwrapper.ini") -Force

$built = Join-Path $output "p18_multiplayer_852_0.asi"
& (Join-Path $repository "src\multiplayer_src\build.bat")
if ($LASTEXITCODE -ne 0) {
    throw "Native multiplayer patch build failed with exit code $LASTEXITCODE"
}

$binary = [IO.File]::ReadAllBytes($built)
$peOffset = [BitConverter]::ToInt32($binary, 0x3c)
$machine = [BitConverter]::ToUInt16($binary, $peOffset + 4)
if ($machine -ne 0x14c) {
    throw "Native multiplayer patch must be built for x86"
}

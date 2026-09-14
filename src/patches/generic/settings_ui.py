"""PowerShell WinForms UI installed beside patched Portal 2 builds."""

from __future__ import annotations


SETTINGS_SCRIPT = r'''param(
    [Parameter(Mandatory = $true)]
    [string]$Root
)

Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing
[System.Windows.Forms.Application]::EnableVisualStyles()

$Root = [IO.Path]::GetFullPath($Root)
$SettingsDir = Join-Path $Root '.p2patcher'
$ResolutionPath = Join-Path $SettingsDir 'resolution.txt'
$DisplayModePath = Join-Path $SettingsDir 'display-mode.txt'
$DebugModePath = Join-Path $SettingsDir 'debug-mode.txt'
$ArgumentsPath = Join-Path $SettingsDir 'launch-arguments.txt'
$Utf8NoBom = New-Object Text.UTF8Encoding($false)

$Bg = [Drawing.ColorTranslator]::FromHtml('#090909')
$Control = [Drawing.ColorTranslator]::FromHtml('#181818')
$Hover = [Drawing.ColorTranslator]::FromHtml('#292929')
$Border = [Drawing.ColorTranslator]::FromHtml('#343434')
$Accent = [Drawing.ColorTranslator]::FromHtml('#e5e5e5')
$Text = [Drawing.ColorTranslator]::FromHtml('#f1f1f1')
$Muted = [Drawing.ColorTranslator]::FromHtml('#999999')
$ButtonText = [Drawing.ColorTranslator]::FromHtml('#111111')

$BuildName = 'Portal 2 Beta'
$ReportPath = Join-Path $SettingsDir 'patcher-report.json'
if (Test-Path -LiteralPath $ReportPath -PathType Leaf) {
    try {
        $Report = [IO.File]::ReadAllText($ReportPath) | ConvertFrom-Json
        $Depot = $Report.extraction.app_id
        $Version = $Report.extraction.version_id
        if ($null -ne $Depot -and $null -ne $Version) {
            $BuildName = 'Build {0}_{1}' -f $Depot, $Version
            switch ('{0}_{1}' -f $Depot, $Version) {
                '852_0' { $BuildName = 'July 2009 (852_0)' }
                '852_1' { $BuildName = 'March 2010 (852_1)' }
                '852_2' { $BuildName = '852_2' }
                '841_0' { $BuildName = 'February 2010 (841_0)' }
            }
        }
    } catch { }
}

function Get-InstalledHammerPatch {
    $ReportPaths = @(Get-ChildItem -LiteralPath $SettingsDir -Filter 'existing-build-report-*.json' -File -ErrorAction SilentlyContinue |
        Sort-Object Name -Descending | ForEach-Object { $_.FullName }) + @($ReportPath)
    foreach ($InstalledReportPath in $ReportPaths) {
        try {
            $SavedReport = [IO.File]::ReadAllText($InstalledReportPath) | ConvertFrom-Json
            if ($InstalledReportPath -eq $ReportPath) {
                $PatchId = '{0}_{1}.hammer' -f $SavedReport.extraction.app_id, $SavedReport.extraction.version_id
            } else {
                if ($SavedReport.operation -ne 'patch_existing' -or @($SavedReport.target).Count -lt 2) { continue }
                $PatchId = '{0}_{1}.hammer' -f $SavedReport.target[0], $SavedReport.target[1]
            }
            if ($PatchId -notin @('852_0.hammer', '852_1.hammer', '852_2.hammer')) { continue }
            $Installed = @($SavedReport.patches | Where-Object {
                $_.id -eq $PatchId -and $_.status -in @('applied', 'already_applied')
            })
            if ($Installed.Count -eq 0) { continue }
            $Bin = if ($PatchId -eq '852_0.hammer') { 'game\bin' } else { 'bin' }
            $MissingFiles = @(@("$Bin\hammer.exe", "$Bin\portal2.fgd", 'Launch Hammer.cmd') | Where-Object {
                -not (Test-Path -LiteralPath (Join-Path $Root $_) -PathType Leaf)
            })
            if ($MissingFiles.Count -gt 0) { continue }
            return $PatchId
        } catch { }
    }
    return $null
}

function Read-Text([string]$Path, [string]$Default) {
    if (Test-Path -LiteralPath $Path -PathType Leaf) {
        return [IO.File]::ReadAllText($Path).Trim()
    }
    return $Default
}

function Write-Text([string]$Path, [string]$Value) {
    [IO.Directory]::CreateDirectory((Split-Path -Parent $Path)) | Out-Null
    [IO.File]::WriteAllText($Path, $Value + "`r`n", $Utf8NoBom)
}

function New-DarkButton {
    param([string]$Label, [int]$X, [int]$Y)
    $Button = New-Object Windows.Forms.Button
    $Button.Text = $Label
    $Button.Location = New-Object Drawing.Point($X, $Y)
    $Button.Size = New-Object Drawing.Size(200, 44)
    $Button.UseVisualStyleBackColor = $false
    $Button.TextAlign = 'MiddleCenter'
    $Button.FlatStyle = 'Flat'
    $Button.FlatAppearance.BorderSize = 1
    $Button.FlatAppearance.BorderColor = $Border
    $Button.FlatAppearance.MouseOverBackColor = $Hover
    $Button.FlatAppearance.MouseDownBackColor = $Hover
    $Button.BackColor = $Control
    $Button.ForeColor = $Text
    $Button.Font = New-Object Drawing.Font('Segoe UI', 10, [Drawing.FontStyle]::Bold)
    $Button.Cursor = 'Hand'
    return $Button
}

function New-Label {
    param([string]$Value, [int]$X, [int]$Y, [int]$Size = 10, [bool]$Bold = $false)
    $Label = New-Object Windows.Forms.Label
    $Label.Text = $Value
    $Label.Location = New-Object Drawing.Point($X, $Y)
    $Label.AutoSize = $true
    $Label.ForeColor = $Text
    $Style = if ($Bold) { [Drawing.FontStyle]::Bold } else { [Drawing.FontStyle]::Regular }
    $Label.Font = New-Object Drawing.Font('Segoe UI', $Size, $Style)
    return $Label
}

function Show-Page([Windows.Forms.Panel]$Page) {
    $MainPage.Visible = $false
    $SettingsPage.Visible = $false
    $HammerPage.Visible = $false
    $Page.Visible = $true
    $Page.BringToFront()
}

function Start-Launcher([string]$Name) {
    $Launcher = Join-Path $Root $Name
    if (-not (Test-Path -LiteralPath $Launcher -PathType Leaf)) {
        [Windows.Forms.MessageBox]::Show("Launcher not found:`r`n$Launcher", 'Portal 2 Beta', 'OK', 'Error') | Out-Null
        return
    }
    Start-Process -FilePath $Launcher -WorkingDirectory $Root
}

function Write-HammerConfig([string]$Base, [bool]$MovedLayout) {
    if ($MovedLayout) {
        $Game = Join-Path $Base 'game'
        $ConfigPath = Join-Path $Game 'bin\GameConfig.txt'
    } else {
        $Game = $Base
        $ConfigPath = Join-Path $Base 'bin\GameConfig.txt'
    }
    $Portal2 = Join-Path $Game 'portal2'
    $Bin = Join-Path $Game 'bin'
    $MapSource = Join-Path $Base 'content\portal2\mapsrc'
    [IO.Directory]::CreateDirectory($MapSource) | Out-Null
    $Config = @"
"Configs"
{
    "Games"
    {
        "Portal 2"
        {
            "GameDir" "$Portal2"
            "Hammer"
            {
                "TextureFormat" "5"
                "MapFormat" "4"
                "DefaultTextureScale" "0.250000"
                "DefaultLightmapScale" "16"
                "DefaultSolidEntity" "func_detail"
                "DefaultPointEntity" "info_player_start"
                "GameExeDir" "$Game"
                "MapDir" "$MapSource"
                "CordonTexture" "tools\toolsskybox"
                "MaterialExcludeCount" "0"
                "GameExe" "$(Join-Path $Game 'hl2.exe')"
                "BSP" "$(Join-Path $Bin 'vbsp.exe')"
                "Vis" "$(Join-Path $Bin 'vvis.exe')"
                "Light" "$(Join-Path $Bin 'vrad.exe')"
                "BSPDir" "$(Join-Path $Portal2 'maps')"
                "PrefabDir" "$(Join-Path $Bin 'Prefabs')"
                "GameData0" "$(Join-Path $Bin 'portal2.fgd')"
            }
        }
    }
    "SDKVersion" "3"
}
"@
    $Config = ($Config.TrimStart() -replace "(?<!`r)`n", "`r`n")
    [IO.File]::WriteAllText($ConfigPath, $Config, $Utf8NoBom)
    return $ConfigPath
}

$Form = New-Object Windows.Forms.Form
$Form.Text = 'Portal 2 Beta'
$Form.ClientSize = New-Object Drawing.Size(660, 430)
$Form.StartPosition = 'CenterScreen'
$Form.FormBorderStyle = 'FixedSingle'
$Form.MaximizeBox = $false
$Form.BackColor = $Bg
$Form.ForeColor = $Text
$Form.Font = New-Object Drawing.Font('Segoe UI', 10)

$MainPage = New-Object Windows.Forms.Panel
$MainPage.Dock = 'Fill'
$MainPage.BackColor = $Bg
$Form.Controls.Add($MainPage)

$Title = New-Label 'Portal 2 Beta' 41 28 24 $true
$MainPage.Controls.Add($Title)
$Subtitle = New-Label $BuildName 45 76 10 $false
$Subtitle.ForeColor = $Muted
$MainPage.Controls.Add($Subtitle)

$LaunchButton = New-DarkButton 'Launch game' 45 170
$LaunchButton.Add_Click({ Start-Launcher 'Launch Portal 2.cmd' })
$MainPage.Controls.Add($LaunchButton)

$SettingsButton = New-DarkButton 'Settings' 45 340
$SettingsButton.Add_Click({ Show-Page $SettingsPage })
$MainPage.Controls.Add($SettingsButton)

$HammerButton = New-DarkButton 'Repair Hammer paths' 260 340
$HammerButton.Enabled = $null -ne (Get-InstalledHammerPatch)
$MainPage.Controls.Add($HammerButton)

$InstallLabel = New-Label 'INSTALL LOCATION' 45 242 9 $true
$InstallLabel.ForeColor = $Muted
$MainPage.Controls.Add($InstallLabel)
$RootLabel = New-Label $Root 45 266 9 $false
$RootLabel.ForeColor = $Muted
$RootLabel.MaximumSize = New-Object Drawing.Size(565, 38)
$MainPage.Controls.Add($RootLabel)

$SettingsPage = New-Object Windows.Forms.Panel
$SettingsPage.Dock = 'Fill'
$SettingsPage.BackColor = $Bg
$SettingsPage.Visible = $false
$Form.Controls.Add($SettingsPage)

$SettingsTitle = New-Label 'Game settings' 41 28 24 $true
$SettingsPage.Controls.Add($SettingsTitle)
$SettingsSubtitle = New-Label $BuildName 45 76 10 $false
$SettingsSubtitle.ForeColor = $Muted
$SettingsPage.Controls.Add($SettingsSubtitle)

$ResLabel = New-Label 'Resolution' 45 125 10 $false
$ResLabel.ForeColor = $Muted
$SettingsPage.Controls.Add($ResLabel)
$ResolutionBox = New-Object Windows.Forms.ComboBox
$ResolutionBox.Location = New-Object Drawing.Point(210, 120)
$ResolutionBox.Size = New-Object Drawing.Size(225, 30)
$ResolutionBox.DropDownStyle = 'DropDownList'
$ResolutionBox.FlatStyle = 'Flat'
$ResolutionBox.BackColor = $Control
$ResolutionBox.ForeColor = $Text
$Resolutions = @('1280x720', '1366x768', '1600x900', '1920x1080', '2560x1440', '3840x2160')
[void]$ResolutionBox.Items.AddRange($Resolutions)
$SavedResolution = (Read-Text $ResolutionPath '1366 768') -replace '\s+', 'x'
if ($SavedResolution -notmatch '^\d{3,5}x\d{3,5}$') { $SavedResolution = '1366x768' }
$ResolutionIndex = $ResolutionBox.Items.IndexOf($SavedResolution)
if ($ResolutionIndex -lt 0) {
    [void]$ResolutionBox.Items.Add($SavedResolution)
    $ResolutionIndex = $ResolutionBox.Items.Count - 1
}
$ResolutionBox.SelectedIndex = $ResolutionIndex
$SettingsPage.Controls.Add($ResolutionBox)

$DisplayLabel = New-Label 'Display mode' 45 177 10 $false
$DisplayLabel.ForeColor = $Muted
$SettingsPage.Controls.Add($DisplayLabel)
$Fullscreen = New-Object Windows.Forms.RadioButton
$Fullscreen.Text = 'Fullscreen'
$Fullscreen.Location = New-Object Drawing.Point(210, 173)
$Fullscreen.AutoSize = $true
$Fullscreen.ForeColor = $Text
$Fullscreen.BackColor = $Bg
$SettingsPage.Controls.Add($Fullscreen)
$Borderless = New-Object Windows.Forms.RadioButton
$Borderless.Text = 'Borderless'
$Borderless.Location = New-Object Drawing.Point(325, 173)
$Borderless.AutoSize = $true
$Borderless.ForeColor = $Text
$Borderless.BackColor = $Bg
$SettingsPage.Controls.Add($Borderless)
$Windowed = New-Object Windows.Forms.RadioButton
$Windowed.Text = 'Windowed'
$Windowed.Location = New-Object Drawing.Point(440, 173)
$Windowed.AutoSize = $true
$Windowed.ForeColor = $Text
$Windowed.BackColor = $Bg
$SettingsPage.Controls.Add($Windowed)
$SavedMode = Read-Text $DisplayModePath '-windowed'
if ($SavedMode -eq '-fullscreen') { $Fullscreen.Checked = $true }
elseif ($SavedMode -eq '-windowed -noborder') { $Borderless.Checked = $true }
else { $Windowed.Checked = $true }

$AdvancedLabel = New-Label 'Developer options' 45 229 10 $false
$AdvancedLabel.ForeColor = $Muted
$SettingsPage.Controls.Add($AdvancedLabel)
$DebugBox = New-Object Windows.Forms.CheckBox
$DebugBox.Text = 'Enable developer mode (-dev)'
$DebugBox.Location = New-Object Drawing.Point(210, 225)
$DebugBox.AutoSize = $true
$DebugBox.ForeColor = $Text
$DebugBox.BackColor = $Bg
$DebugBox.Checked = (Read-Text $DebugModePath '') -eq '-dev'
$SettingsPage.Controls.Add($DebugBox)

$ArgsLabel = New-Label 'Launch arguments' 45 281 10 $false
$ArgsLabel.ForeColor = $Muted
$SettingsPage.Controls.Add($ArgsLabel)
$ArgsBox = New-Object Windows.Forms.TextBox
$ArgsBox.Location = New-Object Drawing.Point(210, 276)
$ArgsBox.Size = New-Object Drawing.Size(400, 28)
$ArgsBox.BackColor = $Control
$ArgsBox.ForeColor = $Text
$ArgsBox.BorderStyle = 'FixedSingle'
$ArgsBox.Font = New-Object Drawing.Font('Consolas', 10)
$ArgsBox.Text = Read-Text $ArgumentsPath ''
$SettingsPage.Controls.Add($ArgsBox)

$SaveButton = New-DarkButton 'Save settings' 45 340
$SaveButton.Add_Click({
    $ResolutionParts = $ResolutionBox.SelectedItem.ToString().Split('x')
    Write-Text $ResolutionPath ($ResolutionParts -join ' ')
    if ($Fullscreen.Checked) { $ModeValue = '-fullscreen' }
    elseif ($Borderless.Checked) { $ModeValue = '-windowed -noborder' }
    else { $ModeValue = '-windowed' }
    Write-Text $DisplayModePath $ModeValue
    Write-Text $DebugModePath $(if ($DebugBox.Checked) { '-dev' } else { '' })
    Write-Text $ArgumentsPath $ArgsBox.Text.Trim()
    Show-Page $MainPage
})
$SettingsPage.Controls.Add($SaveButton)
$BackButton = New-DarkButton 'Back' 260 340
$BackButton.Add_Click({ Show-Page $MainPage })
$SettingsPage.Controls.Add($BackButton)

$HammerPage = New-Object Windows.Forms.Panel
$HammerPage.Dock = 'Fill'
$HammerPage.BackColor = $Bg
$HammerPage.Visible = $false
$Form.Controls.Add($HammerPage)

$HammerDone = New-Label 'Hammer is ready' 41 28 24 $true
$HammerPage.Controls.Add($HammerDone)
$HammerSubtitle = New-Label $BuildName 45 76 10 $false
$HammerSubtitle.ForeColor = $Muted
$HammerPage.Controls.Add($HammerSubtitle)
$PathTitle = New-Label 'UPDATED LOCATION' 45 156 9 $true
$PathTitle.ForeColor = $Muted
$HammerPage.Controls.Add($PathTitle)
$PathBox = New-Object Windows.Forms.TextBox
$PathBox.Location = New-Object Drawing.Point(45, 184)
$PathBox.Size = New-Object Drawing.Size(565, 30)
$PathBox.BackColor = $Control
$PathBox.ForeColor = $Text
$PathBox.BorderStyle = 'FixedSingle'
$PathBox.Font = New-Object Drawing.Font('Consolas', 10)
$PathBox.ReadOnly = $true
$PathBox.Text = $Root
$HammerPage.Controls.Add($PathBox)
$HammerLaunchButton = New-DarkButton 'Launch Hammer' 45 340
$HammerLaunchButton.Add_Click({ Start-Launcher 'Launch Hammer.cmd' })
$HammerPage.Controls.Add($HammerLaunchButton)
$HammerBackButton = New-DarkButton 'Back' 260 340
$HammerBackButton.Add_Click({ Show-Page $MainPage })
$HammerPage.Controls.Add($HammerBackButton)

$HammerButton.Add_Click({
    try {
        $HammerPatch = Get-InstalledHammerPatch
        if ($null -eq $HammerPatch) {
            $HammerButton.Enabled = $false
            throw 'A supported installed Hammer patch and its files are required.'
        }
        $MovedHammer = $HammerPatch -eq '852_0.hammer'
        $Confirmation = [Windows.Forms.MessageBox]::Show(
            "This will recreate Hammer's GameConfig.txt.`r`n`r`nAny custom changes to that file will be lost.`r`n`r`nContinue?",
            'Replace Hammer configuration?',
            [Windows.Forms.MessageBoxButtons]::YesNo,
            [Windows.Forms.MessageBoxIcon]::Warning,
            [Windows.Forms.MessageBoxDefaultButton]::Button2
        )
        if ($Confirmation -ne [Windows.Forms.DialogResult]::Yes) { return }
        [void](Write-HammerConfig $Root $MovedHammer)
        $PathBox.Text = $Root
        Show-Page $HammerPage
    } catch {
        [Windows.Forms.MessageBox]::Show($_.Exception.Message, 'Could not fix Hammer paths', 'OK', 'Error') | Out-Null
    }
})

foreach ($Page in @($MainPage, $SettingsPage, $HammerPage)) {
    foreach ($Y in @(108, 320)) {
        $Divider = New-Object Windows.Forms.Panel
        $Divider.Location = New-Object Drawing.Point(45, $Y)
        $Divider.Size = New-Object Drawing.Size(565, 1)
        $Divider.BackColor = $Border
        $Page.Controls.Add($Divider)
    }
}
foreach ($Button in @($LaunchButton, $SaveButton, $HammerLaunchButton)) {
    $Button.BackColor = $Accent
    $Button.ForeColor = $ButtonText
    $Button.FlatAppearance.BorderSize = 0
    $Button.FlatAppearance.MouseOverBackColor = [Drawing.Color]::White
    $Button.FlatAppearance.MouseDownBackColor = [Drawing.Color]::FromArgb(205, 205, 205)
}

Show-Page $MainPage
[void]$Form.ShowDialog()
'''.replace("\n", "\r\n").encode("utf-8")

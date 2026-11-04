# pdfdown installer for Windows. Installs whatever is missing, then pdfdown and its models.
#
#   powershell -ExecutionPolicy ByPass -c "irm https://raw.githubusercontent.com/rafsunsheikh/pdfdown/main/install.ps1 | iex"
#
# What it does, skipping anything already there:
#   1. Microsoft Visual C++ Runtime (PyTorch needs it; Windows asks for permission once)
#   2. uv, which also brings its own Python, so no Python install is needed
#   3. pdfdown itself, as a tool on the PATH
#   4. Windows Terminal, where the app looks right (Windows 11 has it already)
#   5. the models (about 1 GB), so the first PDF converts at full speed
#   6. a "pdfdown" shortcut in the Start menu
#
# Settings (environment variables), mainly for testing:
#   PDFDOWN_SPEC        what to install instead of "pdfdown" (a version such as pdfdown==0.1.4, or a wheel file)
#   PDFDOWN_DEPS_ONLY   1: only steps 1 and 2 (the npm launcher uses this)
#   PDFDOWN_NO_MODELS   1: skip step 5
#   PDFDOWN_NO_TERMINAL 1: skip step 4

$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"  # Invoke-WebRequest is far slower with its progress bar

function Say($text) { Write-Host "pdfdown: $text" -ForegroundColor Cyan }

function Test-VCRuntime {
    foreach ($key in @("HKLM:\SOFTWARE\Microsoft\VisualStudio\14.0\VC\Runtimes\x64",
                       "HKLM:\SOFTWARE\WOW6432Node\Microsoft\VisualStudio\14.0\VC\Runtimes\x64")) {
        $item = Get-ItemProperty -Path $key -ErrorAction SilentlyContinue
        if ($item -and $item.Installed -eq 1) { return $true }
    }
    return $false
}

function Install-VCRuntime {
    if (Test-VCRuntime) { Say "Visual C++ Runtime: already installed"; return }
    Say "installing the Microsoft Visual C++ Runtime (Windows will ask for permission) ..."
    $file = Join-Path $env:TEMP "vc_redist.x64.exe"
    Invoke-WebRequest -UseBasicParsing -Uri "https://aka.ms/vs/17/release/vc_redist.x64.exe" -OutFile $file
    $process = Start-Process -FilePath $file -ArgumentList "/install", "/quiet", "/norestart" -Verb RunAs -Wait -PassThru
    Remove-Item $file -ErrorAction SilentlyContinue
    # 3010: installed, a restart is recommended; 1638: a newer version is already there
    if ($process.ExitCode -notin @(0, 3010, 1638)) {
        throw "the Visual C++ Runtime installer stopped with code $($process.ExitCode)"
    }
}

function Find-Uv {
    $command = Get-Command uv -ErrorAction SilentlyContinue
    if ($command) { return $command.Source }
    foreach ($candidate in @("$env:USERPROFILE\.local\bin\uv.exe", "$env:USERPROFILE\.cargo\bin\uv.exe")) {
        if (Test-Path $candidate) { return $candidate }
    }
    return $null
}

function Install-Uv {
    $uv = Find-Uv
    if ($uv) { Say "uv: already installed"; return $uv }
    Say "installing uv (it fetches Python by itself) ..."
    Invoke-RestMethod -UseBasicParsing https://astral.sh/uv/install.ps1 | Invoke-Expression
    $env:Path = "$env:USERPROFILE\.local\bin;$env:Path"
    $uv = Find-Uv
    if (-not $uv) { throw "uv did not install; see https://docs.astral.sh/uv/getting-started/installation/" }
    return $uv
}

function Install-Terminal {
    if (Get-Command wt.exe -ErrorAction SilentlyContinue) { return }
    if (-not (Get-Command winget -ErrorAction SilentlyContinue)) {
        Say "Windows Terminal is not installed; get it from the Microsoft Store for the best look (optional)"
        return
    }
    Say "installing Windows Terminal ..."
    winget install --id Microsoft.WindowsTerminal --exact --silent --accept-source-agreements --accept-package-agreements | Out-Null
}

function New-Shortcut($pdfdown) {
    $folder = Join-Path $env:APPDATA "Microsoft\Windows\Start Menu\Programs"
    $shell = New-Object -ComObject WScript.Shell
    $link = $shell.CreateShortcut((Join-Path $folder "pdfdown.lnk"))
    $terminal = Get-Command wt.exe -ErrorAction SilentlyContinue
    if ($terminal) {
        $link.TargetPath = $terminal.Source
        $link.Arguments = "--title pdfdown `"$pdfdown`""
    } else {
        $link.TargetPath = $pdfdown
    }
    $link.WorkingDirectory = [Environment]::GetFolderPath("MyDocuments")
    $link.Description = "Convert PDFs to Markdown"
    $link.Save()
    Say "added pdfdown to the Start menu"
}

function Install-Pdfdown {
    if ([Environment]::Is64BitOperatingSystem -eq $false) { throw "pdfdown needs 64-bit Windows" }
    Install-VCRuntime
    $uv = Install-Uv
    if ($env:PDFDOWN_DEPS_ONLY -eq "1") { return }

    $spec = if ($env:PDFDOWN_SPEC) { $env:PDFDOWN_SPEC } else { "pdfdown" }
    Say "installing $spec (about 1 GB with PyTorch; a few minutes) ..."
    & $uv tool install --python 3.12 --upgrade $spec
    if ($LASTEXITCODE -ne 0) { throw "installing pdfdown failed (see the messages above)" }
    & $uv tool update-shell | Out-Null  # keep pdfdown on the PATH in new windows
    $bin = (& $uv tool dir --bin).Trim()
    $env:Path = "$bin;$env:Path"
    $pdfdown = Join-Path $bin "pdfdown.exe"

    if ($env:PDFDOWN_NO_TERMINAL -ne "1") { Install-Terminal }
    if ($env:PDFDOWN_NO_MODELS -ne "1") {
        & $pdfdown setup
        if ($LASTEXITCODE -ne 0) { Say "some models will be downloaded on first use instead" }
    }
    New-Shortcut $pdfdown
    Say "done. Open pdfdown from the Start menu, or type pdfdown in a new terminal window."
}

try {
    Install-Pdfdown
} catch {
    Write-Host "pdfdown: $_" -ForegroundColor Red
    Write-Host "pdfdown: the installation did not finish. Run the same command again to continue." -ForegroundColor Red
    if ($env:CI) { exit 1 }  # inside `irm | iex` a plain exit would close the user's window
}

$ErrorActionPreference = "Stop"

$projectDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$requirements = Join-Path $projectDir "requirements.txt"
$app = Join-Path $projectDir "wlt_open_gui.py"

function Test-Python314 {
    param([string]$pythonPath)

    if (-not $pythonPath -or -not (Test-Path $pythonPath)) {
        return $false
    }

    try {
        $version = (& $pythonPath -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')" 2>$null).Trim()
        return $version -eq "3.14"
    } catch {
        return $false
    }
}

function Get-Python314 {
    $candidates = @()

    $pyLauncher = Get-Command py -ErrorAction SilentlyContinue
    if ($pyLauncher) {
        try {
            $candidate = (& py "-3.14" -c "import sys; print(sys.executable)" 2>$null).Trim()
            if ($candidate) {
                $candidates += $candidate
            }
        } catch {
        }
    }

    $candidates += @(
        (Join-Path $env:LocalAppData "Programs\Python\Python314\python.exe")
    )

    $pythonCommand = Get-Command python -ErrorAction SilentlyContinue
    if ($pythonCommand) {
        $candidates += $pythonCommand.Source
    }

    foreach ($candidate in $candidates | Select-Object -Unique) {
        if (Test-Python314 $candidate) {
            return $candidate
        }
    }

    throw "Kein Python 3.14 gefunden. Erwartet z.B.: $env:LocalAppData\Programs\Python\Python314\python.exe"
}

$python = Get-Python314

Write-Host "Projektordner: $projectDir"
Write-Host "Python 3.14: $python"
Write-Host "Requirements: $requirements"
Write-Host "App: $app"

try {
    & $python -c "import pylinac, pydicom, numpy, scipy, skimage, matplotlib, PIL, reportlab, pypdf" 2>$null
} catch {
    Write-Host ""
    Write-Host "Python-Pakete fehlen. Einmalig installieren mit:"
    Write-Host "`"$python`" -m pip install -r `"$requirements`""
    throw "Abhaengigkeiten fehlen."
}

& $python $app

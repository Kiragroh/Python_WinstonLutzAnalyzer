param(
    [switch]$CheckOnly
)

$ErrorActionPreference = "Stop"

$projectDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$requirements = Join-Path $projectDir "requirements.txt"
$app = Join-Path $projectDir "wlt_open_gui.py"

function Test-SupportedPython {
    param([string]$pythonPath)

    if (-not $pythonPath -or -not (Test-Path $pythonPath)) {
        return $false
    }

    try {
        $supported = (& $pythonPath -c "import sys; print(int(sys.version_info >= (3, 13)))" 2>$null).Trim()
        return $supported -eq "1"
    } catch {
        return $false
    }
}

function Get-SupportedPython {
    $candidates = @()

    $pyLauncher = Get-Command py -ErrorAction SilentlyContinue
    if ($pyLauncher) {
        foreach ($selector in @("-3.14", "-3.13")) {
            try {
                $candidate = (& py $selector -c "import sys; print(sys.executable)" 2>$null).Trim()
                if ($candidate) {
                    $candidates += $candidate
                }
            } catch {
            }
        }
    }

    $candidates += @(
        (Join-Path $env:LocalAppData "Programs\Python\Python314\python.exe"),
        (Join-Path $env:LocalAppData "Programs\Python\Python313\python.exe")
    )

    $pythonCommand = Get-Command python -ErrorAction SilentlyContinue
    if ($pythonCommand) {
        $candidates += $pythonCommand.Source
    }

    foreach ($candidate in $candidates | Select-Object -Unique) {
        if (Test-SupportedPython $candidate) {
            return $candidate
        }
    }

    throw "Kein Python 3.13 oder neuer gefunden."
}

$python = Get-SupportedPython

Write-Host "Projektordner: $projectDir"
Write-Host "Python: $python"
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

if ($CheckOnly) {
    Write-Host "Python und Abhaengigkeiten sind verfuegbar."
    exit 0
}

& $python $app

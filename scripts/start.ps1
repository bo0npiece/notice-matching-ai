# 개발 서버 실행: venv 생성 → 패키지 설치 → .env 준비 → uvicorn
# 사용: powershell -ExecutionPolicy Bypass -File scripts\start.ps1 [-Port 8000] [-NoReload]
param(
    [int]$Port = 8000,
    [switch]$NoReload
)
$ErrorActionPreference = "Stop"
Set-Location (Join-Path $PSScriptRoot "..")

$py = ".venv\Scripts\python.exe"

if (-not (Test-Path $py)) {
    # Python 3.11 이상 확인 후 venv 생성
    python -c "import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)"
    if ($LASTEXITCODE -ne 0) { throw "Python 3.11 이상이 필요합니다." }
    python -m venv .venv
}

if (-not (Test-Path ".env")) {
    Copy-Item ".env.example" ".env"
    Write-Host ".env를 만들었습니다. 실제 호출하려면 CLOVA_API_KEY와 MOCK_MODE=0을 설정하세요."
}

# 필요한 패키지가 없을 때만 설치 (첫 실행은 인터넷 필요)
& $py -c "import fastapi, uvicorn, httpx, dotenv, yaml, multipart, PIL, jsonschema, numpy" 2>$null
if ($LASTEXITCODE -ne 0) {
    & $py -m pip install -r requirements.txt
    if ($LASTEXITCODE -ne 0) { throw "패키지 설치 실패" }
}

$uvicornArgs = @("-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", $Port)
if (-not $NoReload) { $uvicornArgs += "--reload" }
& $py @uvicornArgs

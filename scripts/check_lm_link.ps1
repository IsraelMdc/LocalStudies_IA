$ErrorActionPreference = "Continue"

Write-Host "=== LM Studio CLI Version ===" -ForegroundColor Cyan
lms --version

Write-Host "`n=== LM Link Status ===" -ForegroundColor Cyan
lms link status

Write-Host "`n=== LM Studio Loaded Models ===" -ForegroundColor Cyan
lms ps

Write-Host "`n=== Local OpenAI-Compatible API (http://localhost:1234/v1/models) ===" -ForegroundColor Cyan
try {
    $resp = Invoke-RestMethod -Uri "http://localhost:1234/v1/models" -TimeoutSec 3
    $resp.data | Select-Object id, object | Format-Table -AutoSize
} catch {
    Write-Warning "Servidor local na porta 1234 nao respondeu. Execute: lms server start --port 1234"
}

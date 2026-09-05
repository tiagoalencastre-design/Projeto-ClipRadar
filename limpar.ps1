# Limpeza pos-atualizacao do ClipRadar
#
# POR QUE ISTO EXISTE: extrair um zip por cima do projeto NUNCA apaga
# arquivos. Arquivos que deveriam ter sido removidos sobrevivem em silencio
# e viram duplicatas — ja aconteceu duas vezes com app/ e core/scoring.py.
#
# Rode este script sempre depois de extrair uma atualizacao.
#     powershell -ExecutionPolicy Bypass -File limpar.ps1

$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

Write-Host "Limpando arquivos obsoletos..." -ForegroundColor Cyan

# Interface Streamlit antiga, substituida pelo front atual
$obsoletos = @("app", "core\scoring.py", "mnt")
foreach ($item in $obsoletos) {
    if (Test-Path $item) {
        Remove-Item -Recurse -Force $item
        Write-Host "  removido: $item" -ForegroundColor Yellow
    }
}

# Artefatos de compilacao do Python (regenerados sozinhos)
$caches = Get-ChildItem -Recurse -Directory -Filter "__pycache__" -ErrorAction SilentlyContinue
foreach ($c in $caches) { Remove-Item -Recurse -Force $c.FullName }
if ($caches.Count -gt 0) { Write-Host "  removidos: $($caches.Count) __pycache__" -ForegroundColor Yellow }

Get-ChildItem -Recurse -Filter "*.pyc" -ErrorAction SilentlyContinue | Remove-Item -Force

Write-Host ""
Write-Host "Verificando..." -ForegroundColor Cyan
$problemas = 0
if (Test-Path "app")              { Write-Host "  FALTA: app/ ainda existe" -ForegroundColor Red; $problemas++ }
if (Test-Path "core\scoring.py")  { Write-Host "  FALTA: core\scoring.py ainda existe" -ForegroundColor Red; $problemas++ }
if (-not (Test-Path "core\legacy\scoring.py")) { Write-Host "  FALTA: core\legacy\scoring.py nao encontrado" -ForegroundColor Red; $problemas++ }
if (-not (Test-Path "CLAUDE.md")) { Write-Host "  FALTA: CLAUDE.md nao encontrado" -ForegroundColor Red; $problemas++ }

if ($problemas -eq 0) {
    Write-Host "  Estrutura correta." -ForegroundColor Green
    Write-Host ""
    Write-Host "Rodando os testes..." -ForegroundColor Cyan
    python -m unittest discover -s tests
} else {
    Write-Host ""
    Write-Host "$problemas problema(s). Testes nao executados." -ForegroundColor Red
    exit 1
}

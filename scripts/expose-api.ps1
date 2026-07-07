# Expose local Docker API to the internet (for Vercel BACKEND_URL)
# Usage: .\scripts\expose-api.ps1
# Then update Vercel BACKEND_URL with the printed URL.

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
Set-Location $Root

Write-Host "Starting cloudflare tunnel to localhost:8000..." -ForegroundColor Cyan
Write-Host "Copy the https://....trycloudflare.com URL and run:" -ForegroundColor Yellow
Write-Host '  .\scripts\deploy-production.ps1 -BackendUrl "https://YOUR-URL"' -ForegroundColor Yellow
Write-Host ""

npx cloudflared tunnel --url http://localhost:8000

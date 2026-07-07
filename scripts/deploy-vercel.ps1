# Deploy InboxIQ frontend to Vercel (separate from Titan)
# Usage: .\scripts\deploy-vercel.ps1

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$Frontend = Join-Path $Root "frontend"
$Scope = "niyatijainn15-1145s-projects"
$Project = "inboxiq"

Set-Location $Frontend

Write-Host "Deploying $Project to Vercel (scope: $Scope)..." -ForegroundColor Cyan
Write-Host "This is a NEW project — not linked to Titan." -ForegroundColor Yellow

if (-not (Test-Path ".vercel\project.json")) {
    npx vercel@latest link --yes --project $Project --scope $Scope
}

npx vercel@latest deploy --prod --yes --scope $Scope

Write-Host ""
Write-Host "Live site: https://inboxiq-iota.vercel.app" -ForegroundColor Green
Write-Host "Set NEXT_PUBLIC_API_URL in Vercel project settings when backend is hosted." -ForegroundColor Yellow

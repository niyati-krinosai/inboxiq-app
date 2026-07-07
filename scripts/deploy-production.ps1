# Full production deploy for InboxIQ
# Usage:
#   .\scripts\deploy-production.ps1 -BackendUrl "https://your-api.onrender.com"
#
# First-time backend (pick one):
#   A) Render: push repo to GitHub → render.com → New Blueprint → select render.yaml
#   B) Railway: npx @railway/cli login → cd backend → npx @railway/cli up
#   C) Local Docker: docker compose -f docker-compose.prod.yml up -d --build
#      then use a tunnel (cloudflared) for a public URL

param(
    [Parameter(Mandatory = $true)]
    [string]$BackendUrl
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$Frontend = Join-Path $Root "frontend"
$Scope = "niyatijainn15-1145s-projects"
$Project = "inboxiq"

$BackendUrl = $BackendUrl.TrimEnd("/")

Write-Host "Setting BACKEND_URL on Vercel: $BackendUrl" -ForegroundColor Cyan
Set-Location $Frontend

if (-not (Test-Path ".vercel\project.json")) {
    npx vercel@latest link --yes --project $Project --scope $Scope
}

# Remove NEXT_PUBLIC_API_URL if set (use same-origin proxy instead)
echo $BackendUrl | npx vercel@latest env add BACKEND_URL production --scope $Scope --force 2>$null
echo $BackendUrl | npx vercel@latest env add BACKEND_URL preview --scope $Scope --force 2>$null

Write-Host "Deploying frontend..." -ForegroundColor Cyan
npx vercel@latest deploy --prod --yes --scope $Scope

Write-Host ""
Write-Host "Done! https://inboxiq-iota.vercel.app" -ForegroundColor Green
Write-Host ""
Write-Host "Backend env must also include:" -ForegroundColor Yellow
Write-Host "  FRONTEND_URL=https://inboxiq-iota.vercel.app"
Write-Host "  GOOGLE_REDIRECT_URI=$BackendUrl/api/v1/auth/callback"
Write-Host "  CORS_EXTRA_ORIGINS=https://inboxiq-iota.vercel.app"
Write-Host "Add redirect URI in Google Cloud Console OAuth settings."

# Open Render blueprint deploy for InboxIQ (new repo only)
Start-Process "https://render.com/deploy?repo=https://github.com/niyati-krinosai/inboxiq-app"

Write-Host ""
Write-Host "Render deploy page opened in your browser." -ForegroundColor Cyan
Write-Host ""
Write-Host "On Render:" -ForegroundColor Yellow
Write-Host "  1. Connect GitHub if asked"
Write-Host "  2. Click Deploy Blueprint"
Write-Host "  3. When prompted, add these env vars:"
Write-Host "       GOOGLE_CLIENT_ID"
Write-Host "       GOOGLE_CLIENT_SECRET"
Write-Host "       GOOGLE_REDIRECT_URI = https://inboxiq-api.onrender.com/api/v1/auth/callback"
Write-Host ""
Write-Host "Expected API URL: https://inboxiq-api.onrender.com" -ForegroundColor Green

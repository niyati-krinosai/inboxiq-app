# Fetch recent Render logs for inboxiq-api (requires RENDER_API_KEY from Account Settings)
param(
    [string]$Search = "gupta|krishna|anurag|oauth|inline_gmail|sync",
    [int]$Limit = 50,
    [string]$ServiceId = "srv-d96aad7avr4c7393iu70"
)

$key = $env:RENDER_API_KEY
if (-not $key) {
    Write-Host "Set RENDER_API_KEY first (Render Dashboard -> Account Settings -> API Keys)" -ForegroundColor Red
    exit 1
}

$uri = "https://api.render.com/v1/logs?resource=$ServiceId&limit=$Limit&direction=backward"
if ($Search) {
    $uri += "&text=$([uri]::EscapeDataString($Search))"
}

$resp = Invoke-RestMethod -Uri $uri -Headers @{ Authorization = "Bearer $key" }
$logs = $resp.logs
if (-not $logs) { $logs = $resp }

$logs | ForEach-Object {
    $ts = $_.timestamp
    $msg = $_.message
    if (-not $msg) { $msg = $_ }
    Write-Host "[$ts] $msg"
}

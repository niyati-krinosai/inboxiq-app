# Create a NEW GitHub repo for InboxIQ only (does not touch existing repos)
# Usage: .\scripts\create-github-repo.ps1 [-RepoName inboxiq-app] [-Private]

param(
    [string]$RepoName = "inboxiq-app",
    [switch]$Private = $true
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$Gh = "C:\Program Files\GitHub CLI\gh.exe"

if (-not (Test-Path $Gh)) {
    throw "GitHub CLI not found. Install: winget install GitHub.cli"
}

Set-Location $Root

& $Gh auth status 2>&1 | Out-Null
if ($LASTEXITCODE -ne 0) {
    Write-Host "Not logged in to GitHub. Run:" -ForegroundColor Yellow
    Write-Host '  & "C:\Program Files\GitHub CLI\gh.exe" auth login -h github.com -p https -w' -ForegroundColor Cyan
    exit 1
}

if (Test-Path .git\config) {
    $remotes = git remote 2>$null
    if ($remotes -contains "origin") {
        Write-Host "Remote 'origin' already exists. Skipping repo creation." -ForegroundColor Yellow
        git remote -v
        exit 0
    }
}

$visibility = if ($Private) { "--private" } else { "--public" }

Write-Host "Creating NEW repo: $RepoName (your other repos are untouched)" -ForegroundColor Cyan
& $Gh repo create $RepoName $visibility `
    --description "InboxIQ - Gmail newsletter chat desk (Vercel + FastAPI)" `
    --source . `
    --remote origin `
    --push

Write-Host ""
Write-Host "Done: https://github.com/$( & $Gh api user -q .login)/$RepoName" -ForegroundColor Green
Write-Host "Next: Render - New Blueprint - connect this repo - use render.yaml" -ForegroundColor Yellow

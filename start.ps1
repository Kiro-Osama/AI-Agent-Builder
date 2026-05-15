# =============================================================================
# Agent Builder — One-Click Startup
# -----------------------------------------------------------------------------
# Starts (in order):
#   1. Docker Desktop  (if not running)
#   2. docker compose stack  (db, redis, api, worker, agent-engine, frontend)
#   3. Windows-MCP SSE server on port 8765  (if not already listening)
#   4. Opens the dashboard in the default browser
#
# Idempotent — safe to run multiple times. Re-running while the app is already
# up just verifies everything is healthy.
# =============================================================================

$ErrorActionPreference = "Stop"
$RepoRoot   = $PSScriptRoot
$McpPort    = 8765
$ApiUrl     = "http://localhost:8000"
$FrontUrl   = "http://localhost:8080"

function Write-Step($msg) { Write-Host "`n>> $msg" -ForegroundColor Cyan }
function Write-Ok  ($msg) { Write-Host "   [OK] $msg" -ForegroundColor Green }
function Write-Warn($msg) { Write-Host "   [!]  $msg" -ForegroundColor Yellow }
function Write-Err ($msg) { Write-Host "   [X]  $msg" -ForegroundColor Red }

# -----------------------------------------------------------------------------
# 1. Docker Desktop
# -----------------------------------------------------------------------------
Write-Step "Checking Docker Desktop..."
$dockerRunning = $false
try {
    docker info --format '{{.ServerVersion}}' 2>$null | Out-Null
    if ($LASTEXITCODE -eq 0) { $dockerRunning = $true }
} catch { }

if (-not $dockerRunning) {
    Write-Warn "Docker Desktop is not running. Starting it..."
    $dockerExe = "${env:ProgramFiles}\Docker\Docker\Docker Desktop.exe"
    if (-not (Test-Path $dockerExe)) {
        Write-Err "Docker Desktop not found at $dockerExe — install it first."
        exit 1
    }
    Start-Process -FilePath $dockerExe
    Write-Host "   Waiting for Docker engine to become ready " -NoNewline
    $tries = 0
    while ($tries -lt 60) {
        Start-Sleep -Seconds 2
        docker info --format '{{.ServerVersion}}' 2>$null | Out-Null
        if ($LASTEXITCODE -eq 0) { break }
        Write-Host "." -NoNewline
        $tries++
    }
    Write-Host ""
    if ($LASTEXITCODE -ne 0) {
        Write-Err "Docker Desktop didn't become ready within 2 minutes."
        exit 1
    }
    Write-Ok "Docker Desktop is ready"
} else {
    Write-Ok "Docker Desktop already running"
}

# -----------------------------------------------------------------------------
# 2. Docker Compose stack
# -----------------------------------------------------------------------------
Write-Step "Bringing up docker compose stack..."
Push-Location $RepoRoot
try {
    $running = docker compose ps --services --status running 2>$null
    $expected = @("db","redis","api","worker","agent-engine","frontend")
    $missing  = $expected | Where-Object { $running -notcontains $_ }

    if ($missing.Count -eq 0) {
        Write-Ok "All services already running"
    } else {
        Write-Warn ("Starting/restarting: " + ($missing -join ", "))
        docker compose up -d
        if ($LASTEXITCODE -ne 0) {
            Write-Err "docker compose up failed."
            exit 1
        }
        Write-Ok "Stack is up"
    }
} finally {
    Pop-Location
}

# Wait for API to be healthy
Write-Host "   Waiting for API to respond " -NoNewline
$apiReady = $false
for ($i = 0; $i -lt 30; $i++) {
    try {
        $r = Invoke-WebRequest -Uri "$ApiUrl/health" -TimeoutSec 2 -UseBasicParsing 2>$null
        if ($r.StatusCode -eq 200) { $apiReady = $true; break }
    } catch { }
    Start-Sleep -Seconds 2
    Write-Host "." -NoNewline
}
Write-Host ""
if ($apiReady) { Write-Ok "API healthy" } else { Write-Warn "API didn't respond in time (might still be starting)" }

# -----------------------------------------------------------------------------
# 3. Windows-MCP
# -----------------------------------------------------------------------------
Write-Step "Checking Windows-MCP on port $McpPort..."
$mcpListening = (Get-NetTCPConnection -LocalPort $McpPort -State Listen -ErrorAction SilentlyContinue) -ne $null

if ($mcpListening) {
    Write-Ok "Windows-MCP already running on port $McpPort"
} else {
    Write-Warn "Starting Windows-MCP server in a new window..."

    # Verify uvx is on PATH
    $uvx = Get-Command uvx -ErrorAction SilentlyContinue
    if (-not $uvx) {
        Write-Err "uvx not found on PATH. Install with: pip install uv"
        exit 1
    }

    $args = "serve --transport sse --host 0.0.0.0 --port $McpPort --allow-insecure-remote"
    Start-Process -FilePath "uvx" `
                  -ArgumentList "windows-mcp $args" `
                  -WindowStyle Normal `
                  -WorkingDirectory $RepoRoot

    Write-Host "   Waiting for Windows-MCP to bind to port $McpPort " -NoNewline
    $mcpReady = $false
    for ($i = 0; $i -lt 30; $i++) {
        Start-Sleep -Seconds 2
        if (Get-NetTCPConnection -LocalPort $McpPort -State Listen -ErrorAction SilentlyContinue) {
            $mcpReady = $true
            break
        }
        Write-Host "." -NoNewline
    }
    Write-Host ""
    if ($mcpReady) {
        Write-Ok "Windows-MCP is listening on port $McpPort"
    } else {
        Write-Err "Windows-MCP failed to start. Check the spawned window for errors."
    }
}

# Verify the agent-engine can reach Windows-MCP via host.docker.internal
Write-Host "   Verifying agent-engine can reach Windows-MCP..."
$probe = docker exec agentbuilder-agent-engine `
            curl -s --max-time 5 -o NUL -w "%{http_code}" `
            "http://host.docker.internal:$McpPort/sse" 2>$null
if ($probe -match "200|405") {
    Write-Ok "agent-engine -> host.docker.internal:$McpPort is reachable"
} else {
    Write-Warn "agent-engine probe returned: $probe (expected 200 or 405)"
}

# -----------------------------------------------------------------------------
# 4. Open the dashboard
# -----------------------------------------------------------------------------
Write-Step "All set — opening dashboard..."
Start-Process $FrontUrl

Write-Host ""
Write-Host "================================================================" -ForegroundColor Green
Write-Host "  Agent Builder is running" -ForegroundColor Green
Write-Host "  Dashboard : $FrontUrl" -ForegroundColor Green
Write-Host "  API       : $ApiUrl" -ForegroundColor Green
Write-Host "  Win-MCP   : http://localhost:$McpPort/sse" -ForegroundColor Green
Write-Host "================================================================" -ForegroundColor Green
Write-Host ""
Write-Host "Tip: run .\stop.ps1 to shut everything down." -ForegroundColor DarkGray

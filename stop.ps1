# =============================================================================
# Agent Builder — One-Click Shutdown
# -----------------------------------------------------------------------------
# Stops the docker compose stack and kills the Windows-MCP server process.
# Leaves Docker Desktop itself running.
# =============================================================================

$ErrorActionPreference = "Continue"
$RepoRoot = $PSScriptRoot
$McpPort  = 8765

function Write-Step($msg) { Write-Host "`n>> $msg" -ForegroundColor Cyan }
function Write-Ok  ($msg) { Write-Host "   [OK] $msg" -ForegroundColor Green }
function Write-Warn($msg) { Write-Host "   [!]  $msg" -ForegroundColor Yellow }

# -----------------------------------------------------------------------------
# Stop Windows-MCP (process holding the SSE port)
# -----------------------------------------------------------------------------
Write-Step "Stopping Windows-MCP on port $McpPort..."
$conn = Get-NetTCPConnection -LocalPort $McpPort -State Listen -ErrorAction SilentlyContinue
if ($conn) {
    $procId = $conn.OwningProcess | Select-Object -First 1
    try {
        Stop-Process -Id $procId -Force -ErrorAction Stop
        Write-Ok "Killed PID $procId"
    } catch {
        Write-Warn "Could not stop PID $procId : $_"
    }
} else {
    Write-Ok "Windows-MCP is not running"
}

# -----------------------------------------------------------------------------
# Stop docker compose stack
# -----------------------------------------------------------------------------
Write-Step "Stopping docker compose stack..."
Push-Location $RepoRoot
try {
    docker compose stop
    Write-Ok "Containers stopped"
} finally {
    Pop-Location
}

Write-Host ""
Write-Host "Done. Run .\start.ps1 to bring everything back up." -ForegroundColor DarkGray

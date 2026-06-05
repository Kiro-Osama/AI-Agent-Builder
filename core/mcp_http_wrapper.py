#!/usr/bin/env python3
"""
MCP HTTP Wrapper — patches FastMCP to run as SSE server on 0.0.0.0.

Usage: python3 /mcp_http_wrapper.py /path/to/original_script.py [port]

Mounted into MCP containers to convert stdio → SSE (persistent HTTP).
Disables DNS rebinding protection so other containers can connect.
"""
import sys
import os


def main():
    if len(sys.argv) < 2:
        print("Usage: mcp_http_wrapper.py <script_path> [port]")
        sys.exit(1)

    script_path = sys.argv[1]
    port = int(sys.argv[2]) if len(sys.argv) > 2 else 8080

    # Set sys.argv for the target script's argparser
    sys.argv = [script_path, "--transport", "streamable-http", "--host", "0.0.0.0", "--port", str(port)]

    # Monkey-patch FastMCP.run() to:
    # 1. Force 0.0.0.0 binding
    # 2. Disable DNS rebinding protection (needed for Docker inter-container comms)
    # 3. Use SSE transport (simpler, more compatible)
    import mcp.server.fastmcp.server as mcp_server
    _original_run = mcp_server.FastMCP.run

    def _patched_run(self, transport="stdio", **kwargs):
        self.settings.host = "0.0.0.0"
        self.settings.port = port
        # Disable DNS rebinding protection — needed because other containers
        # connect by container name (e.g. mcp-persistent-mcp-pentest:8080)
        # which isn't in the default allowed_hosts list
        self.settings.transport_security.enable_dns_rebinding_protection = False
        print(f"[MCP-HTTP-Wrapper] Starting on 0.0.0.0:{port} (SSE, no DNS rebinding check)", flush=True)
        _original_run(self, transport="sse")

    mcp_server.FastMCP.run = _patched_run

    # Add the script's directory to path
    script_dir = os.path.dirname(os.path.abspath(script_path))
    sys.path.insert(0, script_dir)
    os.chdir(script_dir)

    # Execute the original script
    with open(script_path) as f:
        code = f.read()
    exec(compile(code, script_path, 'exec'), {'__name__': '__main__', '__file__': script_path})


if __name__ == "__main__":
    main()

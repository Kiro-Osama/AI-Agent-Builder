"""
Shared MCP Container Pool
===========================
Singleton pool that keeps one MCPContainerSession per shared (non-user-config) MCP.
Multiple agent sessions within the same API process reuse the same container.
"""
import asyncio
import logging
from typing import Any

from core.mcp_client import MCPContainerSession, MCPError

logger = logging.getLogger(__name__)


class SharedMCPPool:
    """
    Manages a global registry of shared MCP containers.
    MCPs that do NOT require user configuration are started once and reused.
    """

    def __init__(self):
        self._sessions: dict[str, MCPContainerSession] = {}
        self._locks: dict[str, asyncio.Lock] = {}
        self._global_lock = asyncio.Lock()

    async def _get_lock(self, mcp_name: str) -> asyncio.Lock:
        async with self._global_lock:
            if mcp_name not in self._locks:
                self._locks[mcp_name] = asyncio.Lock()
            return self._locks[mcp_name]

    async def get_or_start(
        self,
        mcp_name: str,
        docker_image: str,
        run_config: dict,
        workspace_path: str,
    ) -> MCPContainerSession:
        """
        Return an existing shared session or start a new one.
        Thread-safe via per-MCP lock.
        """
        lock = await self._get_lock(mcp_name)
        async with lock:
            session = self._sessions.get(mcp_name)
            if session and session._started and session._initialized:
                if session.proc and session.proc.returncode is None:
                    logger.debug(f"[SharedPool] Reusing container for {mcp_name}")
                    return session
                else:
                    logger.warning(f"[SharedPool] Container {mcp_name} died, restarting")
                    self._sessions.pop(mcp_name, None)

            logger.info(f"[SharedPool] Starting shared container: {mcp_name}")
            new_session = MCPContainerSession()
            await new_session.start(
                docker_image=docker_image,
                run_config=run_config,
                workspace_path=workspace_path,
                mcp_name=mcp_name,
            )
            await new_session.initialize()
            await new_session.list_tools()
            self._sessions[mcp_name] = new_session
            logger.info(
                f"[SharedPool] {mcp_name} ready with {len(new_session.tools)} tools"
            )
            return new_session

    def is_running(self, mcp_name: str) -> bool:
        s = self._sessions.get(mcp_name)
        return bool(s and s._started and s.proc and s.proc.returncode is None)

    async def stop(self, mcp_name: str) -> None:
        lock = await self._get_lock(mcp_name)
        async with lock:
            session = self._sessions.pop(mcp_name, None)
            if session:
                await session.stop()
                logger.info(f"[SharedPool] Stopped shared container: {mcp_name}")

    async def shutdown(self) -> None:
        """Stop all shared containers (called on API shutdown)."""
        names = list(self._sessions.keys())
        if not names:
            return
        logger.info(f"[SharedPool] Shutting down {len(names)} shared MCP(s)")
        await asyncio.gather(
            *[self._sessions[n].stop() for n in names],
            return_exceptions=True,
        )
        self._sessions.clear()
        logger.info("[SharedPool] All shared containers stopped")

    def list_running(self) -> list[str]:
        return [n for n in self._sessions if self.is_running(n)]


shared_pool = SharedMCPPool()

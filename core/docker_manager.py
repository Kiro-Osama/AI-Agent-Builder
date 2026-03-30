"""
Docker Manager
==============
Docker SDK wrapper for managing MCP containers and skill sandboxes.
"""
import logging
from typing import Any

import docker
from docker.errors import DockerException, ImageNotFound, APIError

logger = logging.getLogger(__name__)


class DockerManager:
    """
    Manages Docker containers for:
    1. MCP tools - long-running containers with exposed ports
    2. Skill sandboxes - short-lived containers for testing
    """

    def __init__(self):
        try:
            self.client = docker.from_env()
            self.client.ping()
            logger.info("Docker connection established")
        except DockerException as e:
            logger.error(f"Failed to connect to Docker: {e}")
            raise

    # -----------------------------------------------
    # MCP Container Management
    # -----------------------------------------------

    def start_mcp(
        self,
        image_name: str,
        container_name: str | None = None,
        environment: dict | None = None,
    ) -> dict[str, Any]:
        """
        Start an MCP container with auto-port mapping.

        Args:
            image_name: Docker image to run (e.g., "dabour/mcp-kali:latest")
            container_name: Optional container name
            environment: Optional env vars dict

        Returns:
            {
                "container_id": "abc123...",
                "container_name": "mcp-kali-xxxxx",
                "ports": {3000: 32768},  # internal_port: host_port
                "status": "running"
            }
        """
        try:
            # Pull image if not available locally
            try:
                self.client.images.get(image_name)
            except ImageNotFound:
                logger.info(f"Pulling image: {image_name}")
                self.client.images.pull(image_name)

            # Run container with auto port mapping (-P flag equivalent)
            container = self.client.containers.run(
                image_name,
                name=container_name,
                detach=True,
                publish_all_ports=True,
                environment=environment or {},
                labels={"managed-by": "agent-builder-v5"},
                remove=False,
            )

            # Refresh container info to get port mappings
            container.reload()

            # Extract port mappings
            ports = {}
            port_bindings = container.attrs.get("NetworkSettings", {}).get("Ports", {})
            for container_port, host_bindings in port_bindings.items():
                if host_bindings:
                    internal = int(container_port.split("/")[0])
                    external = int(host_bindings[0]["HostPort"])
                    ports[internal] = external

            result = {
                "container_id": container.short_id,
                "container_name": container.name,
                "ports": ports,
                "status": container.status,
            }

            logger.info(f"MCP container started: {result}")
            return result

        except APIError as e:
            logger.error(f"Docker API error starting MCP: {e}")
            raise
        except Exception as e:
            logger.error(f"Failed to start MCP container: {e}")
            raise

    def start_mcp_stdio(
        self,
        image_name: str,
        container_name: str | None = None,
        command: list[str] | None = None,
        volumes: dict | None = None,
        environment: dict | None = None,
        stdin_open: bool = True,
    ) -> dict[str, Any]:
        """
        Start an MCP container that uses stdio transport.
        These need stdin_open=True (-i flag) and specific command args.

        Args:
            image_name: Docker image
            container_name: Optional container name
            command: Command arguments (e.g., ["/workspace"])
            volumes: Host:container volume mappings
            environment: Env vars dict
            stdin_open: Whether to keep stdin open (-i flag)

        Returns:
            Container info dict
        """
        try:
            # Pull image if not available
            try:
                self.client.images.get(image_name)
            except ImageNotFound:
                logger.info(f"Pulling image: {image_name}")
                self.client.images.pull(image_name)

            # Process volume mappings
            docker_volumes = {}
            if volumes:
                for host_path, container_path in volumes.items():
                    docker_volumes[host_path] = {
                        "bind": container_path,
                        "mode": "rw"
                    }

            # Run container with stdio transport settings
            container = self.client.containers.run(
                image_name,
                command=command,
                name=container_name,
                detach=True,
                stdin_open=stdin_open,
                tty=False,
                volumes=docker_volumes or None,
                environment=environment or {},
                labels={"managed-by": "agent-builder-v5"},
                remove=False,
            )

            # Refresh container info
            container.reload()

            result = {
                "container_id": container.short_id,
                "container_name": container.name,
                "ports": {},  # stdio MCPs don't expose ports
                "status": container.status,
                "transport": "stdio",
            }

            logger.info(f"stdio MCP container started: {result}")
            return result

        except APIError as e:
            logger.error(f"Docker API error starting stdio MCP: {e}")
            raise
        except Exception as e:
            logger.error(f"Failed to start stdio MCP container: {e}")
            raise

    def stop_mcp(self, container_id: str, remove: bool = True) -> bool:
        """
        Stop and optionally remove an MCP container.

        Args:
            container_id: Container ID or name
            remove: Whether to remove the container after stopping

        Returns:
            True if successful
        """
        try:
            container = self.client.containers.get(container_id)
            container.stop(timeout=10)
            if remove:
                container.remove()
            logger.info(f"MCP container stopped: {container_id}")
            return True
        except Exception as e:
            logger.error(f"Failed to stop container {container_id}: {e}")
            return False

    def get_running_mcps(self) -> list[dict]:
        """
        List all running MCP containers managed by this system.

        Returns:
            List of container info dicts with port mappings
        """
        try:
            containers = self.client.containers.list(
                filters={"label": "managed-by=agent-builder-v5"},
            )
            result = []
            for c in containers:
                ports = {}
                port_bindings = c.attrs.get("NetworkSettings", {}).get("Ports", {})
                for container_port, host_bindings in port_bindings.items():
                    if host_bindings:
                        internal = int(container_port.split("/")[0])
                        external = int(host_bindings[0]["HostPort"])
                        ports[internal] = external

                result.append({
                    "container_id": c.short_id,
                    "container_name": c.name,
                    "image": c.image.tags[0] if c.image.tags else "unknown",
                    "ports": ports,
                    "status": c.status,
                })
            return result
        except Exception as e:
            logger.error(f"Failed to list MCP containers: {e}")
            return []

    # -----------------------------------------------
    # Sandbox Execution (for Skill testing)
    # -----------------------------------------------

    def run_sandbox(
        self,
        image: str,
        command: str,
        timeout: int = 60,
        environment: dict | None = None,
        volumes: dict | None = None,
    ) -> dict[str, Any]:
        """
        Run a short-lived sandbox container for testing skills.

        Args:
            image: Docker image (e.g., "python:3.9-slim")
            command: Command to execute
            timeout: Max execution time in seconds
            environment: Optional env vars
            volumes: Optional volume mounts

        Returns:
            {
                "exit_code": 0,
                "stdout": "...",
                "stderr": "...",
                "success": True
            }
        """
        try:
            container = self.client.containers.run(
                image,
                command=command,
                detach=True,
                environment=environment or {},
                volumes=volumes or {},
                labels={"managed-by": "agent-builder-v5", "type": "sandbox"},
                mem_limit="512m",
                cpu_period=100000,
                cpu_quota=50000,  # 50% of one CPU
                network_mode="none",  # No network access for security
            )

            # Wait for completion with timeout
            result = container.wait(timeout=timeout)
            exit_code = result.get("StatusCode", -1)

            # Capture logs
            stdout = container.logs(stdout=True, stderr=False).decode("utf-8", errors="replace")
            stderr = container.logs(stdout=False, stderr=True).decode("utf-8", errors="replace")

            # Cleanup
            container.remove(force=True)

            return {
                "exit_code": exit_code,
                "stdout": stdout[-5000:],  # Last 5000 chars
                "stderr": stderr[-2000:],  # Last 2000 chars
                "success": exit_code == 0,
            }

        except Exception as e:
            logger.error(f"Sandbox execution failed: {e}")
            # Try to cleanup
            try:
                container.remove(force=True)
            except Exception:
                pass
            return {
                "exit_code": -1,
                "stdout": "",
                "stderr": str(e),
                "success": False,
            }

    def cleanup_all(self) -> int:
        """Remove all containers managed by this system. Returns count removed."""
        count = 0
        try:
            containers = self.client.containers.list(
                all=True,
                filters={"label": "managed-by=agent-builder-v5"},
            )
            for c in containers:
                c.remove(force=True)
                count += 1
            logger.info(f"Cleaned up {count} containers")
        except Exception as e:
            logger.error(f"Cleanup failed: {e}")
        return count


# -----------------------------------------------
# Factory function (instantiate on-demand, not at import time)
# -----------------------------------------------
def get_docker_manager() -> DockerManager:
    """Create a DockerManager instance on demand."""
    return DockerManager()

"""
Docker Sandbox Manager for A.R.C.H.I.E.
Creates isolated Docker containers for high-risk code changes

Uses docker-compose to spin up complete sandbox environments with:
- Isolated PostgreSQL database
- Isolated application container
- Separate port mapping
- Full service isolation
"""

import os
import subprocess
import json
from typing import Dict
from datetime import datetime


class DockerSandboxManager:
    """
    Manages Docker-based sandbox containers for testing code changes.

    Workflow:
    1. Create sandbox container from archie_platform image
    2. Create sandbox database container
    3. Apply code changes to sandbox
    4. Run tests
    5. Destroy containers when done
    """

    def __init__(self):
        self.base_port = 3100  # Sandbox containers start at port 3100
        self.compose_file = "/mnt/archie_brain/docker-compose.sandbox.yml"
        self.sandbox_network = "archie_sandbox_network"

    def create_container(self, sandbox_id: int, proposal_id: int, metadata: Dict = None) -> Dict:
        """
        Create a new Docker sandbox container.

        Args:
            sandbox_id: Unique sandbox ID
            proposal_id: Related improvement proposal ID
            metadata: Additional metadata

        Returns:
            {
                'success': True,
                'container_id': 'abc123...',
                'container_name': 'archie_sandbox_123',
                'db_container_name': 'archie_sandbox_db_123',
                'ports': {'web': 3100, 'db': 5433},
                'network': 'archie_sandbox_network'
            }
        """
        container_name = f"archie_sandbox_{sandbox_id}"
        db_container_name = f"archie_sandbox_db_{sandbox_id}"
        web_port = self.base_port + sandbox_id
        db_port = 5433 + sandbox_id

        try:
            # Check if docker-compose.sandbox.yml exists
            if not os.path.exists(self.compose_file):
                return {
                    "success": False,
                    "error": f"Docker compose file not found: {self.compose_file}",
                }

            # Create sandbox network if it doesn't exist
            network_result = subprocess.run(
                ["docker", "network", "inspect", self.sandbox_network],
                capture_output=True,
                text=True,
            )

            if network_result.returncode != 0:
                # Network doesn't exist, create it
                subprocess.run(
                    ["docker", "network", "create", self.sandbox_network],
                    check=True,
                    capture_output=True,
                )

            # Build environment variables for this sandbox
            env_vars = {
                "SANDBOX_ID": str(sandbox_id),
                "PROPOSAL_ID": str(proposal_id),
                "SANDBOX_CONTAINER_NAME": container_name,
                "SANDBOX_DB_CONTAINER_NAME": db_container_name,
                "SANDBOX_WEB_PORT": str(web_port),
                "SANDBOX_DB_PORT": str(db_port),
                "SANDBOX_NETWORK": self.sandbox_network,
            }

            # Create containers using docker-compose
            cmd = [
                "docker-compose",
                "-f",
                self.compose_file,
                "-p",
                f"sandbox_{sandbox_id}",  # Project name
                "up",
                "-d",
            ]

            # Add environment variables
            env = os.environ.copy()
            env.update(env_vars)

            result = subprocess.run(cmd, env=env, capture_output=True, text=True, cwd="/mnt/archie_brain")

            if result.returncode != 0:
                return {
                    "success": False,
                    "error": f"Failed to create sandbox: {result.stderr}",
                }

            # Get container ID
            inspect_result = subprocess.run(
                ["docker", "inspect", container_name, "--format={{.Id}}"],
                capture_output=True,
                text=True,
            )

            if inspect_result.returncode != 0:
                return {
                    "success": False,
                    "error": f"Container created but failed to get ID: {inspect_result.stderr}",
                }

            container_id = inspect_result.stdout.strip()

            # Wait for containers to be healthy (max 30 seconds)
            wait_cmd = ["docker", "wait", "--condition", "running", container_name]

            subprocess.run(wait_cmd, capture_output=True, text=True, timeout=30)

            return {
                "success": True,
                "container_id": container_id,
                "container_name": container_name,
                "db_container_name": db_container_name,
                "ports": {"web": web_port, "db": db_port},
                "network": self.sandbox_network,
                "created_at": datetime.now().isoformat(),
            }

        except subprocess.TimeoutExpired:
            return {
                "success": False,
                "error": "Container creation timed out after 30 seconds",
            }
        except Exception as e:
            return {"success": False, "error": str(e)}

    def destroy_container(
        self,
        container_id: str = None,
        container_name: str = None,
        sandbox_id: int = None,
    ) -> Dict:
        """
        Destroy a sandbox container and cleanup resources.

        Args:
            container_id: Docker container ID
            container_name: Container name
            sandbox_id: Sandbox ID (will derive container name)

        Returns:
            {
                'success': True,
                'destroyed_at': '2026-01-01T...'
            }
        """
        try:
            # Determine container name
            if sandbox_id:
                project_name = f"sandbox_{sandbox_id}"
            elif container_name:
                # Extract sandbox_id from name (archie_sandbox_123)
                if "_" in container_name:
                    parts = container_name.split("_")
                    if len(parts) >= 3:
                        project_name = f"sandbox_{parts[-1]}"
                    else:
                        project_name = None
                else:
                    project_name = None
            else:
                project_name = None

            # Use docker-compose down if we have project name
            if project_name:
                cmd = [
                    "docker-compose",
                    "-f",
                    self.compose_file,
                    "-p",
                    project_name,
                    "down",
                    "-v",  # Remove volumes too
                ]

                result = subprocess.run(cmd, capture_output=True, text=True, cwd="/mnt/archie_brain")

                if result.returncode != 0:
                    # Fallback to manual removal
                    pass
                else:
                    return {
                        "success": True,
                        "destroyed_at": datetime.now().isoformat(),
                        "method": "docker-compose",
                    }

            # Manual removal fallback
            if container_id:
                # Stop and remove container
                subprocess.run(["docker", "stop", container_id], capture_output=True, timeout=10)
                subprocess.run(["docker", "rm", "-f", container_id], capture_output=True)

            if container_name:
                # Stop and remove by name
                subprocess.run(["docker", "stop", container_name], capture_output=True, timeout=10)
                subprocess.run(["docker", "rm", "-f", container_name], capture_output=True)

                # Also remove DB container
                db_container_name = container_name.replace("archie_sandbox_", "archie_sandbox_db_")
                subprocess.run(
                    ["docker", "stop", db_container_name],
                    capture_output=True,
                    timeout=10,
                )
                subprocess.run(["docker", "rm", "-f", db_container_name], capture_output=True)

            return {
                "success": True,
                "destroyed_at": datetime.now().isoformat(),
                "method": "manual",
            }

        except Exception as e:
            return {"success": False, "error": str(e)}

    def exec_command(self, container_id: str, command: str, timeout: int = 60) -> Dict:
        """
        Execute a command inside the sandbox container.

        Args:
            container_id: Docker container ID
            command: Command to execute
            timeout: Timeout in seconds

        Returns:
            {
                'success': True,
                'stdout': '...',
                'stderr': '...',
                'exit_code': 0
            }
        """
        try:
            result = subprocess.run(
                ["docker", "exec", container_id, "bash", "-c", command],
                capture_output=True,
                text=True,
                timeout=timeout,
            )

            return {
                "success": result.returncode == 0,
                "stdout": result.stdout,
                "stderr": result.stderr,
                "exit_code": result.returncode,
            }

        except subprocess.TimeoutExpired:
            return {
                "success": False,
                "error": f"Command timed out after {timeout} seconds",
            }
        except Exception as e:
            return {"success": False, "error": str(e)}

    def copy_file_to_container(self, container_id: str, local_path: str, container_path: str) -> Dict:
        """
        Copy a file from host to sandbox container.

        Args:
            container_id: Docker container ID
            local_path: Path on host machine
            container_path: Path in container

        Returns:
            {
                'success': True
            }
        """
        try:
            result = subprocess.run(
                ["docker", "cp", local_path, f"{container_id}:{container_path}"],
                capture_output=True,
                text=True,
            )

            if result.returncode != 0:
                return {"success": False, "error": result.stderr}

            return {"success": True}

        except Exception as e:
            return {"success": False, "error": str(e)}

    def copy_file_from_container(self, container_id: str, container_path: str, local_path: str) -> Dict:
        """
        Copy a file from sandbox container to host.

        Args:
            container_id: Docker container ID
            container_path: Path in container
            local_path: Path on host machine

        Returns:
            {
                'success': True
            }
        """
        try:
            result = subprocess.run(
                ["docker", "cp", f"{container_id}:{container_path}", local_path],
                capture_output=True,
                text=True,
            )

            if result.returncode != 0:
                return {"success": False, "error": result.stderr}

            return {"success": True}

        except Exception as e:
            return {"success": False, "error": str(e)}

    def get_container_logs(self, container_id: str, tail: int = 100) -> Dict:
        """
        Get logs from sandbox container.

        Args:
            container_id: Docker container ID
            tail: Number of lines to retrieve

        Returns:
            {
                'success': True,
                'logs': '...'
            }
        """
        try:
            result = subprocess.run(
                ["docker", "logs", "--tail", str(tail), container_id],
                capture_output=True,
                text=True,
            )

            return {"success": True, "logs": result.stdout + result.stderr}

        except Exception as e:
            return {"success": False, "error": str(e)}

    def get_container_status(self, container_id: str) -> Dict:
        """
        Get current status of sandbox container.

        Returns:
            {
                'success': True,
                'status': 'running',
                'health': 'healthy',
                'uptime': '2 hours',
                'ports': {...}
            }
        """
        try:
            # Get container info as JSON
            result = subprocess.run(["docker", "inspect", container_id], capture_output=True, text=True)

            if result.returncode != 0:
                return {"success": False, "error": "Container not found"}

            info = json.loads(result.stdout)[0]

            state = info.get("State", {})
            config = info.get("Config", {})
            network_settings = info.get("NetworkSettings", {})

            return {
                "success": True,
                "status": state.get("Status", "unknown"),
                "running": state.get("Running", False),
                "health": state.get("Health", {}).get("Status", "none"),
                "started_at": state.get("StartedAt"),
                "ports": network_settings.get("Ports", {}),
                "name": info.get("Name", "").lstrip("/"),
                "image": config.get("Image"),
            }

        except Exception as e:
            return {"success": False, "error": str(e)}


# ============================================================================
# CONVENIENCE FUNCTIONS
# ============================================================================


def create_docker_sandbox(sandbox_id: int, proposal_id: int) -> Dict:
    """Quick function to create Docker sandbox"""
    manager = DockerSandboxManager()
    return manager.create_container(sandbox_id, proposal_id)


def destroy_docker_sandbox(container_id: str) -> Dict:
    """Quick function to destroy Docker sandbox"""
    manager = DockerSandboxManager()
    return manager.destroy_container(container_id=container_id)


# ============================================================================
# TESTING
# ============================================================================

if __name__ == "__main__":
    print("Docker Sandbox Manager - Test Mode")
    print("=" * 60)

    manager = DockerSandboxManager()

    # Test 1: Check Docker availability
    print("\n1. DOCKER AVAILABILITY:")
    print("-" * 60)
    try:
        result = subprocess.run(["docker", "version"], capture_output=True, text=True)
        if result.returncode == 0:
            print("✓ Docker is available")
        else:
            print("✗ Docker is not available")
    except FileNotFoundError:
        print("✗ Docker command not found")

    print("\n✅ Docker Sandbox Manager loaded successfully!")

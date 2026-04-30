"""SSH connection wrapper using paramiko."""

from __future__ import annotations

import io
import os
import time
from pathlib import Path
from typing import Optional

import paramiko
from rich.console import Console

console = Console()


class SSHClient:
    """Wrapper around paramiko for executing commands on remote hosts."""

    def __init__(
        self,
        host: str,
        user: str = "root",
        key_path: Optional[str] = None,
        port: int = 22,
        timeout: int = 30,
    ):
        self.host = host
        self.user = user
        self.key_path = key_path
        self.port = port
        self.timeout = timeout
        self._client: Optional[paramiko.SSHClient] = None

    def connect(self) -> None:
        """Establish SSH connection."""
        self._client = paramiko.SSHClient()
        self._client.set_missing_host_key_policy(paramiko.AutoAddPolicy())

        connect_kwargs: dict = {
            "hostname": self.host,
            "username": self.user,
            "port": self.port,
            "timeout": self.timeout,
        }

        if self.key_path:
            key_path = os.path.expanduser(self.key_path)
            if os.path.exists(key_path):
                connect_kwargs["key_filename"] = key_path
                self._validate_key_format(key_path)

        try:
            self._client.connect(**connect_kwargs)
        except paramiko.SSHException as exc:
            error_msg = str(exc)
            if "RSA key" in error_msg and "OPENSSH key" in error_msg:
                raise ConnectionError(
                    f"Failed to connect to {self.user}@{self.host}:{self.port}: {exc}\n\n"
                    "Your SSH key is in the old RSA/PEM format. "
                    "Delete ~/.ssh/homelab-dev* and re-run to generate a new Ed25519 key."
                ) from exc
            raise ConnectionError(
                f"Failed to connect to {self.user}@{self.host}:{self.port}: {exc}"
            ) from exc
        except Exception as exc:
            raise ConnectionError(
                f"Failed to connect to {self.user}@{self.host}:{self.port}: {exc}"
            ) from exc

    def _validate_key_format(self, key_path: str) -> None:
        """Validate that the SSH key is in a format paramiko can use.

        Raises:
            ConnectionError: If the key format is invalid or unsupported.
        """
        try:
            # Attempt to load the key to verify format
            paramiko.RSAKey.from_private_key_file(key_path)
        except paramiko.PasswordRequiredException:
            pass  # Key exists but is encrypted - that's fine
        except paramiko.SSHException:
            # Try Ed25519
            try:
                paramiko.Ed25519Key.from_private_key_file(key_path)
            except paramiko.PasswordRequiredException:
                pass  # Encrypted key
            except paramiko.SSHException:
                raise ConnectionError(
                    f"SSH key at {key_path} has an unsupported format.\n"
                    "Delete the key files and re-run to generate a new key."
                )

    def close(self) -> None:
        """Close SSH connection."""
        if self._client:
            self._client.close()
            self._client = None

    def __enter__(self) -> "SSHClient":
        self.connect()
        return self

    def __exit__(self, *args) -> None:
        self.close()

    def run(
        self,
        command: str,
        timeout: int = 300,
        stream_output: bool = False,
        check: bool = True,
    ) -> tuple[int, str, str]:
        """Execute a command on the remote host.

        Returns:
            Tuple of (exit_code, stdout, stderr).

        Raises:
            RuntimeError: If check=True and command returns non-zero exit code.
            ConnectionError: If not connected.
        """
        if not self._client:
            raise ConnectionError("Not connected. Call connect() first.")

        transport = self._client.get_transport()
        if not transport or not transport.is_active():
            raise ConnectionError("SSH transport is not active.")

        channel = transport.open_session()
        channel.settimeout(timeout)
        channel.exec_command(command)

        stdout_chunks: list[str] = []
        stderr_chunks: list[str] = []

        while True:
            if channel.recv_ready():
                data = channel.recv(4096).decode("utf-8", errors="replace")
                stdout_chunks.append(data)
                if stream_output:
                    console.print(data, end="", highlight=False)
            if channel.recv_stderr_ready():
                data = channel.recv_stderr(4096).decode("utf-8", errors="replace")
                stderr_chunks.append(data)
                if stream_output:
                    console.print(f"[dim]{data}[/dim]", end="", highlight=False)
            if channel.exit_status_ready():
                # Drain remaining data
                while channel.recv_ready():
                    data = channel.recv(4096).decode("utf-8", errors="replace")
                    stdout_chunks.append(data)
                    if stream_output:
                        console.print(data, end="", highlight=False)
                while channel.recv_stderr_ready():
                    data = channel.recv_stderr(4096).decode("utf-8", errors="replace")
                    stderr_chunks.append(data)
                break
            time.sleep(0.1)

        exit_code = channel.recv_exit_status()
        stdout = "".join(stdout_chunks)
        stderr = "".join(stderr_chunks)
        channel.close()

        if check and exit_code != 0:
            raise RuntimeError(
                f"Command failed (exit {exit_code}) on {self.host}: {command}\n"
                f"stderr: {stderr.strip()}"
            )

        return exit_code, stdout, stderr

    def upload_string(self, content: str, remote_path: str) -> None:
        """Upload a string as a file to the remote host."""
        if not self._client:
            raise ConnectionError("Not connected. Call connect() first.")

        sftp = self._client.open_sftp()
        try:
            with sftp.file(remote_path, "w") as f:
                f.write(content)
        finally:
            sftp.close()

    def download_string(self, remote_path: str) -> str:
        """Download a file from the remote host as a string."""
        if not self._client:
            raise ConnectionError("Not connected. Call connect() first.")

        sftp = self._client.open_sftp()
        try:
            with sftp.file(remote_path, "r") as f:
                return f.read().decode("utf-8")
        finally:
            sftp.close()

    def file_exists(self, remote_path: str) -> bool:
        """Check if a file exists on the remote host."""
        if not self._client:
            raise ConnectionError("Not connected. Call connect() first.")

        sftp = self._client.open_sftp()
        try:
            sftp.stat(remote_path)
            return True
        except FileNotFoundError:
            return False
        finally:
            sftp.close()


def wait_for_ssh(
    host: str,
    user: str = "ubuntu",
    key_path: Optional[str] = None,
    port: int = 22,
    retries: int = 30,
    delay: int = 10,
) -> bool:
    """Wait for SSH to become available on a host.

    Returns:
        True if connection succeeded, False if all retries exhausted.
    """
    for attempt in range(1, retries + 1):
        try:
            client = SSHClient(host=host, user=user, key_path=key_path, port=port, timeout=10)
            client.connect()
            client.close()
            return True
        except Exception:
            if attempt < retries:
                time.sleep(delay)
    return False


def generate_ssh_keypair(key_path: str, comment: str = "homelab-dev") -> str:
    """Generate an Ed25519 SSH keypair if it doesn't exist.

    Uses Ed25519 instead of RSA to avoid "expected OPENSSH key" errors
    with modern SSH servers that reject legacy PEM format.

    Returns:
        The public key string.
    """
    key_path = os.path.expanduser(key_path)
    pub_path = f"{key_path}.pub"

    if os.path.exists(key_path):
        with open(pub_path, "r") as f:
            return f.read().strip()

    os.makedirs(os.path.dirname(key_path), exist_ok=True)

    key = paramiko.Ed25519Key.generate()
    key.write_private_key_file(key_path)
    os.chmod(key_path, 0o600)

    pub_key = f"ssh-ed25519 {key.get_base64()} {comment}"
    with open(pub_path, "w") as f:
        f.write(pub_key + "\n")
    os.chmod(pub_path, 0o644)

    return pub_key

"""Tool installation helpers for local dependencies (kubectl, helm, ansible)."""

from __future__ import annotations

import os
import platform
import shutil
from typing import Optional

from homelab_setup.utils import check_local_tool, error, info, prompt_confirm, run_local, success, warn


def install_kubectl() -> bool:
    """Install kubectl if not present.

    Returns True if kubectl is available (installed or was already present).
    """
    if check_local_tool("kubectl"):
        return True

    warn("kubectl not found in PATH")
    system = platform.system()

    if system == "Darwin":  # macOS
        if check_local_tool("brew"):
            info("Installing kubectl via Homebrew...")
            try:
                run_local("brew install kubectl", stream=True)
                success("kubectl installed via Homebrew")
                return True
            except Exception as exc:
                error(f"Homebrew install failed: {exc}")
        else:
            warn("Homebrew not found. Install from https://brew.sh")
    elif system == "Windows":
        if check_local_tool("choco"):
            info("Installing kubectl via Chocolatey...")
            try:
                run_local("choco install kubernetes-cli -y", stream=True)
                # Refresh PATH
                os.environ["PATH"] = os.environ.get("PATH", "") + r";C:\ProgramData\chocolatey\bin"
                success("kubectl installed via Chocolatey")
                return True
            except Exception as exc:
                error(f"Chocolatey install failed: {exc}")
        else:
            warn("Chocolatey not found. Install from https://chocolatey.org")

    # Fallback to direct download
    info("Attempting direct download install...")
    return _install_kubectl_direct()


def _install_kubectl_direct() -> bool:
    """Install kubectl via direct download (curl/wget)."""
    system = platform.system()
    arch = platform.machine().lower()

    # Map arch names
    arch_map = {
        "amd64": "amd64",
        "x86_64": "amd64",
        "arm64": "arm64",
        "aarch64": "arm64",
    }
    kubectl_arch = arch_map.get(arch, "amd64")

    if system == "Darwin":
        url = f"https://dl.k8s.io/release/$(curl -L -s https://dl.k8s.io/release/stable.txt)/bin/darwin/{kubectl_arch}/kubectl"
    elif system == "Linux":
        url = f"https://dl.k8s.io/release/$(curl -L -s https://dl.k8s.io/release/stable.txt)/bin/linux/{kubectl_arch}/kubectl"
    elif system == "Windows":
        url = f"https://dl.k8s.io/release/$(curl -L -s https://dl.k8s.io/release/stable.txt)/bin/windows/{kubectl_arch}/kubectl.exe"
    else:
        error(f"Unsupported system for kubectl install: {system}")
        return False

    bin_dir = os.path.expanduser("~/.local/bin")
    kubectl_path = os.path.join(bin_dir, "kubectl" if system != "Windows" else "kubectl.exe")

    if not prompt_confirm(f"Install kubectl to {kubectl_path}?", default=True):
        return False

    try:
        os.makedirs(bin_dir, exist_ok=True)

        if check_local_tool("curl"):
            run_local(f'curl -L -o "{kubectl_path}" "{url}"', check=False)
        elif check_local_tool("wget"):
            run_local(f'wget -O "{kubectl_path}" "{url}"', check=False)
        else:
            error("Neither curl nor wget found. Cannot download kubectl.")
            return False

        # Make executable (not needed on Windows)
        if system != "Windows":
            os.chmod(kubectl_path, 0o755)

        # Add to PATH for current session
        os.environ["PATH"] = f"{bin_dir}{os.pathsep}{os.environ.get('PATH', '')}"

        # Verify
        if check_local_tool("kubectl"):
            success(f"kubectl installed to {kubectl_path}")
            return True
        else:
            error("kubectl installation failed - not found after install")
            return False

    except Exception as exc:
        error(f"kubectl install failed: {exc}")
        return False


def install_helm() -> bool:
    """Install helm if not present.

    Returns True if helm is available (installed or was already present).
    """
    if check_local_tool("helm"):
        return True

    warn("helm not found in PATH")
    system = platform.system()

    if system == "Darwin":  # macOS
        if check_local_tool("brew"):
            info("Installing helm via Homebrew...")
            try:
                run_local("brew install helm", stream=True)
                success("helm installed via Homebrew")
                return True
            except Exception as exc:
                error(f"Homebrew install failed: {exc}")
        else:
            warn("Homebrew not found. Install from https://brew.sh")
    elif system == "Windows":
        if check_local_tool("choco"):
            info("Installing helm via Chocolatey...")
            try:
                run_local("choco install kubernetes-helm -y", stream=True)
                # Refresh PATH
                os.environ["PATH"] = os.environ.get("PATH", "") + r";C:\ProgramData\chocolatey\bin"
                success("helm installed via Chocolatey")
                return True
            except Exception as exc:
                error(f"Chocolatey install failed: {exc}")
        else:
            warn("Chocolatey not found. Install from https://chocolatey.org")

    # Fallback to Helm install script
    return _install_helm_script()


def _install_helm_script() -> bool:
    """Install helm using the official install script."""
    if not prompt_confirm("Install helm using official install script?", default=True):
        return False

    try:
        bin_dir = os.path.expanduser("~/.local/bin")
        os.makedirs(bin_dir, exist_ok=True)

        # Download and run the install script
        install_cmd = (
            f'curl -fsSL https://raw.githubusercontent.com/helm/helm/main/scripts/get-helm-3 | '
            f'HELM_INSTALL_DIR="{bin_dir}" bash'
        )
        run_local(install_cmd, check=False, stream=True)

        # Add to PATH for current session
        os.environ["PATH"] = f"{bin_dir}{os.pathsep}{os.environ.get('PATH', '')}"

        # Verify
        if check_local_tool("helm"):
            success(f"helm installed to {bin_dir}")
            return True
        else:
            # Try to find helm in common locations
            for path in [bin_dir, "/usr/local/bin", os.path.expanduser("~/bin")]:
                helm_path = os.path.join(path, "helm")
                if os.path.exists(helm_path):
                    os.environ["PATH"] = f"{path}{os.pathsep}{os.environ.get('PATH', '')}"
                    if check_local_tool("helm"):
                        success(f"helm found at {helm_path}")
                        return True

            error("helm installation failed - not found after install")
            return False

    except Exception as exc:
        error(f"helm install failed: {exc}")
        return False


def ensure_kubectl() -> bool:
    """Ensure kubectl is available, installing if necessary.

    Returns True if kubectl is available after this call.
    """
    if check_local_tool("kubectl"):
        return True

    info("kubectl is required for Phase 5 cluster validation")
    return install_kubectl()


def ensure_helm() -> bool:
    """Ensure helm is available, installing if necessary.

    Returns True if helm is available after this call.
    """
    if check_local_tool("helm"):
        return True

    info("helm is required for Phase 5 (CNI, ingress deployment)")
    return install_helm()

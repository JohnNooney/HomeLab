"""Phase 5: Cluster Bootstrapping — CNI, Ingress, Storage, Validation."""

from __future__ import annotations

import os
from typing import Any

from homelab_setup.preflight import (
    check_phase5_k3s,
    check_phase5_kubeadm,
    evaluate_preflight,
)
from homelab_setup.ssh import SSHClient
from homelab_setup.utils import (
    check_local_tool,
    console,
    error,
    info,
    phase_header,
    prompt_choice,
    prompt_confirm,
    run_local,
    step,
    success,
    warn,
)


def run_phase5(config: dict[str, Any], force: bool = False) -> bool:
    """Run cluster bootstrapping.

    Branches based on cluster mode (k3s vs kubeadm).
    Returns True if all steps succeeded.
    """
    mode = config["cluster"]["mode"]

    if mode == "k3s":
        return _run_phase5_k3s(config, force=force)
    else:
        return _run_phase5_kubeadm(config, force=force)


# ─── k3s path ────────────────────────────────────────────────────────────────


def _run_phase5_k3s(config: dict[str, Any], force: bool = False) -> bool:
    """Phase 5 for k3s — most services are bundled, just validate."""
    phase_header("Phase 5", "Bootstrap Cluster Services (k3s)")

    results = check_phase5_k3s(config)
    if evaluate_preflight("Phase 5 (k3s)", results, force):
        return True

    info("k3s bundles: Flannel CNI, CoreDNS, local-path-provisioner, Traefik ingress")
    info("Only optional overrides and validation needed")
    console.print()

    if not prompt_confirm("Proceed with cluster bootstrapping?"):
        warn("Phase 5 skipped by user")
        return False

    ok = True
    ok = _step_k3s_validate(config) and ok
    ok = _step_k3s_optional_nginx(config) and ok
    ok = _step_validation_checklist() and ok

    if ok:
        success("Phase 5 complete — cluster is bootstrapped and validated")
    else:
        error("Phase 5 completed with errors")

    return ok


def _step_k3s_validate(config: dict[str, Any]) -> bool:
    """Validate k3s cluster is operational."""
    step(1, "Validate k3s cluster")

    checks = [
        ("kubectl get nodes", "Nodes"),
        ("kubectl get pods -n kube-system", "System pods"),
    ]

    all_ok = True
    for cmd, label in checks:
        rc, stdout, stderr = run_local(cmd, check=False)
        if rc == 0:
            success(f"{label} OK")
            for line in stdout.strip().splitlines():
                info(f"  {line}")
        else:
            error(f"{label} check failed: {stderr.strip()}")
            all_ok = False

    return all_ok


def _step_k3s_optional_nginx(config: dict[str, Any]) -> bool:
    """Optionally replace Traefik with nginx-ingress."""
    step(2, "Ingress controller")

    info("k3s ships with Traefik as the default ingress controller")

    if not prompt_confirm("Replace Traefik with nginx-ingress?", default=False):
        info("Keeping Traefik (default)")
        return True

    if not check_local_tool("helm"):
        error("helm not found in PATH. Install Helm first:")
        info("  brew install helm")
        return False

    try:
        # Disable Traefik in k3s
        cp_ip = config["cluster"]["control_plane_ip"]
        key_path = config["proxmox"]["ssh_key"]

        info("Disabling Traefik in k3s...")
        with SSHClient(host=cp_ip, user="ubuntu", key_path=key_path) as ssh:
            # Create HelmChartConfig to disable Traefik
            ssh.run(
                'sudo kubectl delete helmcharts.helm.cattle.io traefik traefik-crd -n kube-system 2>/dev/null || true',
                check=False,
            )
            # Add skip flag
            ssh.run(
                "sudo sed -i 's|ExecStart=/usr/local/bin/k3s|ExecStart=/usr/local/bin/k3s server --disable traefik|' "
                "/etc/systemd/system/k3s.service 2>/dev/null || true",
                check=False,
            )
            ssh.run("sudo systemctl daemon-reload && sudo systemctl restart k3s", timeout=60)

        info("Installing nginx-ingress via Helm...")
        _install_nginx_ingress()
        success("nginx-ingress installed (replaced Traefik)")
        return True
    except Exception as exc:
        error(f"Failed to replace Traefik: {exc}")
        return False


# ─── kubeadm path ────────────────────────────────────────────────────────────


def _run_phase5_kubeadm(config: dict[str, Any], force: bool = False) -> bool:
    """Phase 5 for kubeadm — deploy CNI, ingress, storage."""
    phase_header("Phase 5", "Bootstrap Cluster Services (kubeadm)")

    results = check_phase5_kubeadm(config)
    if evaluate_preflight("Phase 5 (kubeadm)", results, force):
        return True

    if not prompt_confirm("Proceed with cluster bootstrapping?"):
        warn("Phase 5 skipped by user")
        return False

    ok = True
    ok = _step_fetch_kubeconfig(config) and ok
    ok = _step_deploy_cni(config) and ok
    ok = _step_deploy_ingress() and ok
    ok = _step_deploy_storage() and ok
    ok = _step_validation_checklist() and ok

    if ok:
        success("Phase 5 complete — cluster is bootstrapped and validated")
    else:
        error("Phase 5 completed with errors")

    return ok


def _step_fetch_kubeconfig(config: dict[str, Any]) -> bool:
    """Fetch kubeconfig from control plane."""
    step(1, "Fetch kubeconfig")

    cp_ip = config["cluster"]["control_plane_ip"]
    key_path = config["proxmox"]["ssh_key"]
    kubeconfig_dir = os.path.expanduser("~/.kube")
    kubeconfig_path = os.path.join(kubeconfig_dir, "config")

    try:
        with SSHClient(host=cp_ip, user="ubuntu", key_path=key_path) as ssh:
            rc, kubeconfig, _ = ssh.run("sudo cat /etc/kubernetes/admin.conf", check=False)
            if rc != 0:
                # Try alternative location
                rc, kubeconfig, _ = ssh.run("cat ~/.kube/config", check=False)
                if rc != 0:
                    error("Could not find kubeconfig on control plane")
                    return False

            # Backup existing
            os.makedirs(kubeconfig_dir, exist_ok=True)
            if os.path.exists(kubeconfig_path):
                backup_path = os.path.join(kubeconfig_dir, "config.backup")
                info(f"Backing up existing kubeconfig to {backup_path}")
                with open(kubeconfig_path, "r") as f:
                    existing = f.read()
                with open(backup_path, "w") as f:
                    f.write(existing)

            with open(kubeconfig_path, "w") as f:
                f.write(kubeconfig)
            os.chmod(kubeconfig_path, 0o600)

            success(f"Kubeconfig written to {kubeconfig_path}")
            return True
    except Exception as exc:
        error(f"Failed to fetch kubeconfig: {exc}")
        return False


def _step_deploy_cni(config: dict[str, Any]) -> bool:
    """Deploy CNI plugin."""
    step(2, "Deploy CNI")

    cni = prompt_choice(
        "Select CNI plugin:",
        ["Calico", "Cilium"],
        default="Calico",
    )

    config["cluster"]["cni"] = cni.lower()

    if not check_local_tool("helm") and cni == "Cilium":
        error("helm required for Cilium. Install: brew install helm")
        return False

    try:
        if cni == "Calico":
            info("Deploying Calico with VXLAN overlay (BGP disabled)...")
            run_local(
                "kubectl apply -f https://raw.githubusercontent.com/projectcalico/calico/v3.26.0/manifests/calico.yaml",
                stream=True,
            )
            info("Configuring Calico for VXLAN mode...")
            # Disable BGP, enable VXLAN for Proxmox/home lab compatibility
            run_local(
                'kubectl set env daemonset/calico-node -n kube-system '
                'CALICO_NETWORKING_BACKEND=vxlan '
                'CALICO_IPV4POOL_VXLAN=Always',
                check=False,
            )
            run_local(
                'kubectl set env deployment/calico-kube-controllers -n kube-system '
                'CALICO_NETWORKING_BACKEND=vxlan',
                check=False,
            )
            info("Waiting for Calico pods to be ready...")
            rc, _, _ = run_local(
                "kubectl wait --for=condition=ready pod -l k8s-app=calico-node -n kube-system --timeout=120s",
                check=False,
            )
            if rc != 0:
                warn("Calico pods not ready after 120s. Continuing but cluster may have networking issues.")
        else:
            info("Deploying Cilium via Helm...")
            run_local("helm repo add cilium https://helm.cilium.io/ 2>/dev/null || true")
            run_local("helm repo update")
            run_local(
                "helm install cilium cilium/cilium "
                "--namespace kube-system "
                "--set operator.replicas=1",
                stream=True,
            )
            info("Waiting for Cilium pods to be ready...")
            run_local(
                "kubectl wait --for=condition=ready pod -l k8s-app=cilium -n kube-system --timeout=120s",
                check=False,
            )

        success(f"{cni} deployed")
        return True
    except Exception as exc:
        error(f"Failed to deploy CNI: {exc}")
        return False


def _step_deploy_ingress() -> bool:
    """Deploy nginx-ingress controller."""
    step(3, "Deploy ingress controller")

    if not check_local_tool("helm"):
        error("helm not found in PATH. Install: brew install helm")
        return False

    try:
        _install_nginx_ingress()
        success("nginx-ingress deployed")
        return True
    except Exception as exc:
        error(f"Failed to deploy ingress: {exc}")
        return False


def _step_deploy_storage() -> bool:
    """Deploy local-path storage provisioner."""
    step(4, "Deploy storage provisioner")

    try:
        info("Installing local-path-provisioner...")
        run_local(
            "kubectl apply -f https://raw.githubusercontent.com/rancher/local-path-provisioner/v0.0.24/deploy/local-path-storage.yaml",
            stream=True,
        )

        info("Setting as default StorageClass...")
        run_local(
            'kubectl patch storageclass local-path -p '
            '\'{"metadata": {"annotations":{"storageclass.kubernetes.io/is-default-class":"true"}}}\'',
        )

        success("local-path-provisioner deployed and set as default")
        return True
    except Exception as exc:
        error(f"Failed to deploy storage provisioner: {exc}")
        return False


# ─── shared ──────────────────────────────────────────────────────────────────


def _install_nginx_ingress() -> None:
    """Install or upgrade nginx-ingress via Helm (used by both paths)."""
    from homelab_setup.utils import info

    run_local("helm repo add ingress-nginx https://kubernetes.github.io/ingress-nginx 2>/dev/null || true")
    run_local("helm repo update")

    # Check if release already exists
    rc, _, _ = run_local(
        "helm status ingress-nginx -n ingress-nginx 2>/dev/null",
        check=False,
    )

    if rc == 0:
        info("nginx-ingress release already exists, upgrading...")
        run_local(
            "helm upgrade ingress-nginx ingress-nginx/ingress-nginx "
            "--namespace ingress-nginx "
            "--set controller.service.type=NodePort "
            "--set controller.service.nodePorts.http=30080 "
            "--set controller.service.nodePorts.https=30443",
            stream=True,
        )
    else:
        run_local(
            "helm install ingress-nginx ingress-nginx/ingress-nginx "
            "--namespace ingress-nginx "
            "--create-namespace "
            "--set controller.service.type=NodePort "
            "--set controller.service.nodePorts.http=30080 "
            "--set controller.service.nodePorts.https=30443",
            stream=True,
        )


def _step_validation_checklist() -> bool:
    """Run validation checks on the cluster."""
    console.print()
    console.rule("[bold cyan]Validation Checklist[/bold cyan]", style="cyan")

    all_ok = True
    failed_checks = []

    # Check 1: Nodes
    rc, stdout, stderr = run_local("kubectl get nodes", check=False)
    if rc == 0 and "NotReady" not in stdout and "Not Ready" not in stdout:
        success("All nodes Ready")
    else:
        warn("Nodes check failed")
        failed_checks.append(("Nodes", "kubectl get nodes", stdout + stderr))
        all_ok = False

    # Check 2: Pods
    rc, stdout, stderr = run_local("kubectl get pods --all-namespaces", check=False)
    if rc == 0:
        pending = stdout.count("Pending")
        crash = stdout.count("CrashLoopBackOff")
        error_pods = stdout.count("Error")
        if pending == 0 and crash == 0 and error_pods == 0:
            success("All pods Running")
        else:
            warn(f"Pods issues: {pending} Pending, {crash} CrashLoop, {error_pods} Error")
            failed_checks.append(("Pods", "kubectl get pods --all-namespaces", stdout))
            all_ok = False
    else:
        warn("Pods check failed")
        failed_checks.append(("Pods", "kubectl get pods --all-namespaces", stderr))
        all_ok = False

    # Check 3: DNS Resolution
    rc, stdout, stderr = run_local(
        "kubectl run dns-test --image=busybox --rm -i --restart=Never -- nslookup kubernetes.default",
        check=False
    )
    if rc == 0 and "kubernetes.default" in stdout.lower() or "10.96" in stdout:
        success("DNS resolution working")
    else:
        warn("DNS resolution — needs verification")
        failed_checks.append(("DNS", "nslookup kubernetes.default", stderr or stdout))
        all_ok = False
        console.print("\n[dim]To verify DNS manually, run:[/dim]")
        console.print("  kubectl run debug --image=busybox --rm -it --restart=Never -- nslookup kubernetes.default")
        console.print("  kubectl run debug --image=busybox --rm -it --restart=Never -- nslookup google.com")
        console.print("  kubectl get pods -n kube-system -l k8s-app=kube-dns")
        console.print("  kubectl logs -n kube-system -l k8s-app=kube-dns")

    # Check 4: Ingress
    rc, _, _ = run_local(
        "kubectl get pods -n ingress-nginx 2>/dev/null || kubectl get pods -n kube-system -l app.kubernetes.io/name=traefik 2>/dev/null",
        check=False
    )
    if rc == 0:
        success("Ingress controller running")
    else:
        warn("Ingress controller check failed")
        failed_checks.append(("Ingress", "kubectl get pods -n ingress-nginx", ""))
        all_ok = False

    # Check 5: Storage
    rc, stdout, stderr = run_local("kubectl get storageclass", check=False)
    if rc == 0 and "local-path" in stdout:
        success("Storage class configured")
    else:
        warn("Storage class check failed")
        failed_checks.append(("StorageClass", "kubectl get storageclass", stderr))
        all_ok = False

    # Print detailed failures
    if failed_checks:
        console.print("\n[bold red]Failed Checks Detail:[/bold red]")
        for label, cmd, output in failed_checks:
            console.print(f"\n[yellow]{label}[/yellow]: {cmd}")
            if output.strip():
                console.print(f"[dim]{output[:500]}[/dim]")

    return all_ok

"""Interactive troubleshooting sub-menu for diagnosing cluster issues."""

from __future__ import annotations

from typing import Any

from homelab_setup.config import get_all_vm_ips, get_vm_definitions
from homelab_setup.ssh import SSHClient
from homelab_setup.utils import (
    console,
    error,
    info,
    run_local,
    success,
    warn,
)


# ─── helpers ─────────────────────────────────────────────────────────────────


def _run_check(label: str, cmd: str, fix: str | None = None) -> bool:
    """Run a kubectl command, print pass/fail, and suggest a fix on failure."""
    rc, stdout, stderr = run_local(cmd, check=False)
    output = stdout.strip() or stderr.strip()

    if rc == 0 and output:
        success(label)
        for line in output.splitlines()[:15]:
            console.print(f"    [dim]{line}[/dim]")
        return True
    else:
        error(label)
        if output:
            for line in output.splitlines()[:10]:
                console.print(f"    [dim]{line}[/dim]")
        if fix:
            console.print(f"    [yellow]Fix:[/yellow] {fix}")
        return False


def _section(title: str) -> None:
    """Print a section header."""
    console.print()
    console.rule(f"[bold cyan]{title}[/bold cyan]", style="cyan")
    console.print()


# ─── category: nodes ─────────────────────────────────────────────────────────


def troubleshoot_nodes(config: dict[str, Any]) -> None:
    """Diagnose node-level issues."""
    _section("Nodes")

    # Node status
    _run_check(
        "Node status",
        "kubectl get nodes -o wide",
        fix="kubectl describe node <name> | grep -A5 Conditions",
    )

    # Check for NotReady nodes
    rc, stdout, _ = run_local("kubectl get nodes --no-headers", check=False)
    if rc == 0:
        for line in stdout.strip().splitlines():
            parts = line.split()
            if len(parts) >= 2 and "NotReady" in parts[1]:
                node_name = parts[0]
                warn(f"Node {node_name} is NotReady")
                info(f"  Inspect: kubectl describe node {node_name}")
                info(f"  Logs:    ssh ubuntu@<ip> 'sudo journalctl -u kubelet --no-pager -n 30'")

    # Resource usage
    rc, stdout, _ = run_local("kubectl top nodes 2>/dev/null", check=False)
    if rc == 0 and stdout.strip():
        success("Resource usage (metrics-server)")
        for line in stdout.strip().splitlines()[:10]:
            console.print(f"    [dim]{line}[/dim]")
    else:
        info("metrics-server not installed — kubectl top unavailable")
        info("  Install: kubectl apply -f https://github.com/kubernetes-sigs/metrics-server/releases/latest/download/components.yaml")

    # SSH connectivity
    px = config["proxmox"]
    vms = get_vm_definitions(config)
    for vm in vms:
        try:
            with SSHClient(host=vm["ip"], user="ubuntu", key_path=px["ssh_key"], timeout=5) as ssh:
                success(f"SSH to {vm['name']} ({vm['ip']})")
        except Exception:
            error(f"SSH to {vm['name']} ({vm['ip']}) — unreachable")
            info(f"  Fix: ssh -i {px['ssh_key']} ubuntu@{vm['ip']}")


# ─── category: networking / dns ──────────────────────────────────────────────


def troubleshoot_networking(config: dict[str, Any]) -> None:
    """Diagnose networking and DNS issues."""
    _section("Networking / DNS")

    # CoreDNS pods
    _run_check(
        "CoreDNS pods",
        "kubectl get pods -n kube-system -l k8s-app=kube-dns -o wide",
        fix="kubectl rollout restart deployment coredns -n kube-system",
    )

    # DNS: internal resolution
    info("Testing internal DNS (kubernetes.default)...")
    rc, stdout, stderr = run_local(
        "kubectl run dns-diag --image=busybox --rm -i --restart=Never --timeout=30s "
        "-- nslookup kubernetes.default 2>/dev/null",
        check=False,
    )
    combined = (stdout + stderr).strip()
    if rc == 0 and "address" in combined.lower():
        success("Internal DNS resolution working")
        for line in combined.splitlines()[:5]:
            console.print(f"    [dim]{line}[/dim]")
    else:
        error("Internal DNS resolution failed")
        if combined:
            for line in combined.splitlines()[:5]:
                console.print(f"    [dim]{line}[/dim]")
        console.print("    [yellow]Likely causes:[/yellow]")
        console.print("    • CNI not ready (pods can't reach CoreDNS)")
        console.print("    • CoreDNS pods crashing")
        console.print("    [yellow]Fixes:[/yellow]")
        console.print("    kubectl rollout restart deployment coredns -n kube-system")
        console.print("    kubectl logs -n kube-system -l k8s-app=kube-dns --tail=20")

    # DNS: external resolution
    info("Testing external DNS (google.com)...")
    rc, stdout, stderr = run_local(
        "kubectl run dns-diag-ext --image=busybox --rm -i --restart=Never --timeout=30s "
        "-- nslookup google.com 2>/dev/null",
        check=False,
    )
    combined = (stdout + stderr).strip()
    if rc == 0 and "address" in combined.lower():
        success("External DNS resolution working")
    else:
        error("External DNS resolution failed")
        console.print("    [yellow]Likely causes:[/yellow]")
        console.print("    • Upstream DNS (8.8.8.8) unreachable from pods")
        console.print("    • NAT/firewall blocking outbound UDP 53")
        console.print("    [yellow]Fixes:[/yellow]")
        console.print("    kubectl get configmap coredns -n kube-system -o yaml")
        console.print("    # Check 'forward' directive points to reachable DNS")

    # kube-proxy
    _run_check(
        "kube-proxy pods",
        "kubectl get pods -n kube-system -l k8s-app=kube-proxy -o wide",
        fix="kubectl rollout restart daemonset kube-proxy -n kube-system",
    )

    # Service CIDR check
    _run_check(
        "Cluster services",
        "kubectl get svc --all-namespaces",
    )

    # CoreDNS logs
    info("CoreDNS recent logs:")
    rc, stdout, _ = run_local(
        "kubectl logs -n kube-system -l k8s-app=kube-dns --tail=20 2>/dev/null",
        check=False,
    )
    if rc == 0 and stdout.strip():
        for line in stdout.strip().splitlines()[:20]:
            console.print(f"    [dim]{line}[/dim]")


# ─── category: cni ───────────────────────────────────────────────────────────


def troubleshoot_cni(config: dict[str, Any]) -> None:
    """Diagnose CNI issues (Calico or Cilium)."""
    _section("CNI")

    # Detect which CNI is installed
    rc_cal, stdout_cal, _ = run_local(
        "kubectl get pods -n kube-system -l k8s-app=calico-node --no-headers 2>/dev/null",
        check=False,
    )
    rc_cil, stdout_cil, _ = run_local(
        "kubectl get pods -n kube-system -l app.kubernetes.io/name=cilium-agent --no-headers 2>/dev/null",
        check=False,
    )

    has_calico = rc_cal == 0 and stdout_cal.strip() != ""
    has_cilium = rc_cil == 0 and stdout_cil.strip() != ""

    if not has_calico and not has_cilium:
        error("No CNI detected (neither Calico nor Cilium pods found)")
        console.print("    [yellow]Fix:[/yellow] Re-run Phase 5 to deploy a CNI plugin")
        return

    if has_calico:
        _troubleshoot_calico()
    if has_cilium:
        _troubleshoot_cilium()


def _troubleshoot_calico() -> None:
    """Calico-specific diagnostics."""
    info("Detected CNI: Calico")
    console.print()

    # Pod status
    _run_check(
        "Calico node pods",
        "kubectl get pods -n kube-system -l k8s-app=calico-node -o wide",
        fix="kubectl rollout restart daemonset calico-node -n kube-system",
    )

    # Check readiness
    rc, stdout, _ = run_local(
        "kubectl get pods -n kube-system -l k8s-app=calico-node --no-headers",
        check=False,
    )
    if rc == 0:
        for line in stdout.strip().splitlines():
            parts = line.split()
            if len(parts) >= 2 and parts[1] != "1/1":
                warn(f"  {parts[0]} not fully ready ({parts[1]})")

    # IP pools
    _run_check(
        "Calico IP pools",
        "kubectl get ippools.crd.projectcalico.org -o wide 2>/dev/null",
        fix="kubectl apply -f - <<EOF\napiVersion: projectcalico.org/v3\nkind: IPPool\nmetadata:\n  name: default-ipv4-ippool\nspec:\n  cidr: 192.168.0.0/16\n  natOutgoing: true\nEOF",
    )

    # Check BGP vs VXLAN mode
    info("Checking networking backend...")
    rc, stdout, _ = run_local(
        "kubectl get daemonset calico-node -n kube-system -o jsonpath='{.spec.template.spec.containers[0].env}' 2>/dev/null",
        check=False,
    )
    if rc == 0:
        if "vxlan" in stdout.lower():
            success("Calico backend: VXLAN (overlay)")
        else:
            warn("Calico backend: BGP (may fail on Proxmox)")
            console.print("    [yellow]Fix — switch to VXLAN:[/yellow]")
            console.print("    kubectl set env daemonset/calico-node -n kube-system \\")
            console.print("      CALICO_NETWORKING_BACKEND=vxlan \\")
            console.print("      CALICO_IPV4POOL_VXLAN=Always")
            console.print("    kubectl rollout restart daemonset calico-node -n kube-system")

    # BIRD / BGP status from logs
    info("Checking BGP peering status...")
    rc, stdout, _ = run_local(
        "kubectl logs -n kube-system -l k8s-app=calico-node --tail=30 2>/dev/null | grep -i 'bird\\|bgp\\|establish\\|error'",
        check=False,
    )
    if rc == 0 and stdout.strip():
        for line in stdout.strip().splitlines()[:10]:
            console.print(f"    [dim]{line}[/dim]")
    else:
        info("  No BGP/BIRD log entries (expected if using VXLAN)")

    # Calico controllers
    _run_check(
        "Calico kube-controllers",
        "kubectl get pods -n kube-system -l k8s-app=calico-kube-controllers -o wide",
        fix="kubectl rollout restart deployment calico-kube-controllers -n kube-system",
    )


def _troubleshoot_cilium() -> None:
    """Cilium-specific diagnostics."""
    info("Detected CNI: Cilium")
    console.print()

    # Pod status
    _run_check(
        "Cilium agent pods",
        "kubectl get pods -n kube-system -l k8s-app=cilium -o wide",
        fix="kubectl rollout restart daemonset cilium -n kube-system",
    )

    # Cilium operator
    _run_check(
        "Cilium operator",
        "kubectl get pods -n kube-system -l app.kubernetes.io/name=cilium-operator -o wide",
        fix="kubectl rollout restart deployment cilium-operator -n kube-system",
    )

    # Cilium status via exec
    info("Cilium status (from agent pod):")
    rc, pod_name, _ = run_local(
        "kubectl get pods -n kube-system -l k8s-app=cilium -o jsonpath='{.items[0].metadata.name}' 2>/dev/null",
        check=False,
    )
    if rc == 0 and pod_name.strip():
        rc, stdout, _ = run_local(
            f"kubectl exec -n kube-system {pod_name.strip()} -- cilium status --brief 2>/dev/null",
            check=False,
        )
        if rc == 0 and stdout.strip():
            for line in stdout.strip().splitlines()[:15]:
                console.print(f"    [dim]{line}[/dim]")
        else:
            warn("  Could not get cilium status")

    # Cilium connectivity
    info("Cilium recent logs:")
    rc, stdout, _ = run_local(
        "kubectl logs -n kube-system -l k8s-app=cilium --tail=20 2>/dev/null | grep -i 'error\\|warn\\|fail'",
        check=False,
    )
    if rc == 0 and stdout.strip():
        for line in stdout.strip().splitlines()[:10]:
            console.print(f"    [dim]{line}[/dim]")
    else:
        info("  No error/warning entries in recent logs")


# ─── category: ingress ───────────────────────────────────────────────────────


def troubleshoot_ingress(config: dict[str, Any]) -> None:
    """Diagnose ingress controller issues."""
    _section("Ingress")

    # Detect ingress type
    rc_nginx, stdout_nginx, _ = run_local(
        "kubectl get pods -n ingress-nginx --no-headers 2>/dev/null",
        check=False,
    )
    rc_traefik, stdout_traefik, _ = run_local(
        "kubectl get pods -n kube-system -l app.kubernetes.io/name=traefik --no-headers 2>/dev/null",
        check=False,
    )

    has_nginx = rc_nginx == 0 and stdout_nginx.strip() != ""
    has_traefik = rc_traefik == 0 and stdout_traefik.strip() != ""

    if not has_nginx and not has_traefik:
        error("No ingress controller found")
        console.print("    [yellow]Fix:[/yellow] Re-run Phase 5 or install manually:")
        console.print("    helm install ingress-nginx ingress-nginx/ingress-nginx \\")
        console.print("      --namespace ingress-nginx --create-namespace \\")
        console.print("      --set controller.service.type=NodePort \\")
        console.print("      --set controller.service.nodePorts.http=30080 \\")
        console.print("      --set controller.service.nodePorts.https=30443")
        return

    if has_nginx:
        info("Detected: nginx-ingress")
        _run_check(
            "nginx-ingress pods",
            "kubectl get pods -n ingress-nginx -o wide",
            fix="kubectl rollout restart deployment ingress-nginx-controller -n ingress-nginx",
        )

        _run_check(
            "nginx-ingress service",
            "kubectl get svc -n ingress-nginx",
        )

        # Check NodePort allocation
        rc, stdout, _ = run_local(
            "kubectl get svc ingress-nginx-controller -n ingress-nginx -o jsonpath='{.spec.ports}' 2>/dev/null",
            check=False,
        )
        if rc == 0 and stdout.strip():
            if "30080" in stdout and "30443" in stdout:
                success("NodePorts allocated (30080/30443)")
            else:
                warn("NodePorts may not be 30080/30443")
                console.print(f"    [dim]{stdout}[/dim]")

        # Recent logs
        info("nginx-ingress recent logs:")
        rc, stdout, _ = run_local(
            "kubectl logs -n ingress-nginx -l app.kubernetes.io/name=ingress-nginx --tail=15 2>/dev/null",
            check=False,
        )
        if rc == 0 and stdout.strip():
            for line in stdout.strip().splitlines()[:10]:
                console.print(f"    [dim]{line}[/dim]")

    if has_traefik:
        info("Detected: Traefik")
        _run_check(
            "Traefik pods",
            "kubectl get pods -n kube-system -l app.kubernetes.io/name=traefik -o wide",
            fix="kubectl rollout restart deployment traefik -n kube-system",
        )

    # Test HTTP endpoint
    cp_ip = config["cluster"]["control_plane_ip"]
    info(f"Testing HTTP endpoint at {cp_ip}:30080...")
    rc, stdout, _ = run_local(
        f"curl -s -o /dev/null -w '%{{http_code}}' --connect-timeout 5 http://{cp_ip}:30080 2>/dev/null",
        check=False,
    )
    if rc == 0 and stdout.strip() in ("404", "200", "308"):
        success(f"HTTP endpoint responding (status {stdout.strip()})")
    else:
        warn(f"HTTP endpoint not responding at {cp_ip}:30080")
        console.print("    [yellow]Check:[/yellow] Is the ingress service running as NodePort?")


# ─── category: storage ───────────────────────────────────────────────────────


def troubleshoot_storage(config: dict[str, Any]) -> None:
    """Diagnose storage issues."""
    _section("Storage")

    # StorageClasses
    rc, stdout, _ = run_local("kubectl get storageclass", check=False)
    if rc == 0 and stdout.strip():
        if "(default)" in stdout:
            success("Default StorageClass configured")
        else:
            warn("No default StorageClass")
            console.print("    [yellow]Fix:[/yellow]")
            console.print("    kubectl patch storageclass local-path -p \\")
            console.print("      '{\"metadata\":{\"annotations\":{\"storageclass.kubernetes.io/is-default-class\":\"true\"}}}'")
        for line in stdout.strip().splitlines():
            console.print(f"    [dim]{line}[/dim]")
    else:
        error("No StorageClasses found")
        console.print("    [yellow]Fix:[/yellow] kubectl apply -f https://raw.githubusercontent.com/rancher/local-path-provisioner/v0.0.24/deploy/local-path-storage.yaml")

    # PVC status
    _run_check(
        "PersistentVolumeClaims",
        "kubectl get pvc --all-namespaces 2>/dev/null",
    )

    # Check for stuck PVCs
    rc, stdout, _ = run_local(
        "kubectl get pvc --all-namespaces --no-headers 2>/dev/null",
        check=False,
    )
    if rc == 0 and stdout.strip():
        for line in stdout.strip().splitlines():
            if "Pending" in line:
                parts = line.split()
                warn(f"  PVC {parts[1]} in {parts[0]} is Pending")
                console.print(f"    [yellow]Fix:[/yellow] kubectl describe pvc {parts[1]} -n {parts[0]}")

    # local-path-provisioner pod
    _run_check(
        "local-path-provisioner pod",
        "kubectl get pods -n local-path-storage -o wide 2>/dev/null",
        fix="kubectl apply -f https://raw.githubusercontent.com/rancher/local-path-provisioner/v0.0.24/deploy/local-path-storage.yaml",
    )


# ─── menu ────────────────────────────────────────────────────────────────────


def run_troubleshoot(config: dict[str, Any]) -> None:
    """Interactive troubleshooting sub-menu."""
    categories = {
        "1": ("Nodes", troubleshoot_nodes),
        "2": ("Networking / DNS", troubleshoot_networking),
        "3": ("CNI", troubleshoot_cni),
        "4": ("Ingress", troubleshoot_ingress),
        "5": ("Storage", troubleshoot_storage),
    }

    while True:
        console.print()
        console.print("[bold]Troubleshoot Menu[/bold]")
        console.print("  [cyan]1[/cyan]. Nodes       — node status, kubelet logs, resource usage")
        console.print("  [cyan]2[/cyan]. Networking  — pod-to-pod, DNS resolution, service connectivity")
        console.print("  [cyan]3[/cyan]. CNI         — Calico/Cilium pod status, config, VXLAN/BGP mode")
        console.print("  [cyan]4[/cyan]. Ingress     — nginx/traefik pods, service, port checks")
        console.print("  [cyan]5[/cyan]. Storage     — StorageClass, PVC status, provisioner pods")
        console.print("  [cyan]6[/cyan]. Run All     — run all categories above in sequence")
        console.print("  [cyan]0[/cyan]. Back")
        console.print()

        choice = console.input("[bold]Select> [/bold]").strip()

        if choice == "0":
            break
        elif choice == "6":
            for key in ("1", "2", "3", "4", "5"):
                label, func = categories[key]
                func(config)
        elif choice in categories:
            label, func = categories[choice]
            func(config)
        else:
            warn("Invalid selection")

"""Interactive troubleshooting sub-menu with self-healing for cluster issues."""

from __future__ import annotations

import ipaddress
import json
import time
from typing import Any

from homelab_setup.config import get_all_vm_ips, get_vm_definitions
from homelab_setup.ssh import SSHClient
from homelab_setup.utils import (
    check_local_tool,
    console,
    error,
    info,
    prompt_confirm,
    run_local,
    success,
    warn,
)


# ─── helpers ─────────────────────────────────────────────────────────────────


def _run_check(
    label: str,
    cmd: str,
    fix: str | None = None,
    heal_cmd: str | None = None,
) -> bool:
    """Run a kubectl command, print pass/fail, suggest fix, optionally heal."""
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
        if heal_cmd:
            return _attempt_heal(label, heal_cmd, verify_cmd=cmd)
        return False


def _attempt_heal(
    label: str,
    heal_cmd: str,
    verify_cmd: str | None = None,
    wait_secs: int = 5,
) -> bool:
    """Prompt user → run heal command → optionally re-verify."""
    if not prompt_confirm(f"Attempt to fix: {label}?", default=False):
        info("Skipped")
        return False

    info(f"Running: {heal_cmd}")
    rc, stdout, stderr = run_local(heal_cmd, check=False)
    if rc != 0:
        error(f"Fix command failed (exit {rc})")
        combined = (stderr or stdout).strip()
        if combined:
            for line in combined.splitlines()[:5]:
                console.print(f"    [dim]{line}[/dim]")
        return False

    if verify_cmd:
        if wait_secs:
            info(f"Waiting {wait_secs}s before re-check...")
            time.sleep(wait_secs)
        info("Re-verifying...")
        rc2, stdout2, _ = run_local(verify_cmd, check=False)
        if rc2 == 0 and stdout2.strip():
            success(f"{label} — fixed")
            return True
        else:
            warn(f"{label} — fix applied but verification still failing")
            return False

    success(f"{label} — fix applied")
    return True


def _section(title: str) -> None:
    """Print a section header."""
    console.print()
    console.rule(f"[bold cyan]{title}[/bold cyan]", style="cyan")
    console.print()


def _get_kubeadm_pod_cidr() -> str | None:
    """Read pod CIDR from kubeadm-config configmap."""
    rc, stdout, _ = run_local(
        "kubectl get configmap kubeadm-config -n kube-system "
        "-o jsonpath='{.data.ClusterConfiguration}' 2>/dev/null",
        check=False,
    )
    if rc != 0 or not stdout.strip():
        return None
    for line in stdout.splitlines():
        line = line.strip()
        if "podSubnet" in line:
            parts = line.split(":", 1)
            if len(parts) == 2:
                return parts[1].strip().strip('"').strip("'")
    return None


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

    # Node conditions (DiskPressure, MemoryPressure, PIDPressure)
    info("Checking node conditions...")
    rc, stdout, _ = run_local("kubectl get nodes -o json 2>/dev/null", check=False)
    if rc == 0 and stdout.strip():
        try:
            nodes_data = json.loads(stdout)
            pressure_found = False
            for node in nodes_data.get("items", []):
                name = node["metadata"]["name"]
                conditions = node.get("status", {}).get("conditions", [])
                for cond in conditions:
                    ctype = cond.get("type", "")
                    status = cond.get("status", "")
                    if ctype in ("DiskPressure", "MemoryPressure", "PIDPressure") and status == "True":
                        pressure_found = True
                        warn(f"Node {name} has {ctype}")
                        console.print(f"    [dim]{cond.get('message', '')}[/dim]")
            if not pressure_found:
                success("No node pressure conditions")
        except (json.JSONDecodeError, KeyError):
            pass

    # Resource usage
    rc, stdout, _ = run_local("kubectl top nodes 2>/dev/null", check=False)
    if rc == 0 and stdout.strip():
        success("Resource usage (metrics-server)")
        for line in stdout.strip().splitlines()[:10]:
            console.print(f"    [dim]{line}[/dim]")
    else:
        info("metrics-server not installed — kubectl top unavailable")

    # SSH connectivity + kubelet journal check
    px = config["proxmox"]
    vms = get_vm_definitions(config)
    for vm in vms:
        try:
            with SSHClient(host=vm["ip"], user="ubuntu", key_path=px["ssh_key"], timeout=5) as ssh:
                success(f"SSH to {vm['name']} ({vm['ip']})")
                # Kubelet error log check
                rc_j, journal_out, _ = ssh.run(
                    "sudo journalctl -u kubelet --no-pager -n 50 --priority=err --quiet 2>/dev/null",
                    check=False,
                )
                if rc_j == 0 and journal_out.strip():
                    warn(f"  Kubelet errors on {vm['name']}:")
                    for jline in journal_out.strip().splitlines()[:5]:
                        console.print(f"    [dim]{jline.strip()}[/dim]")
        except Exception:
            error(f"SSH to {vm['name']} ({vm['ip']}) — unreachable")
            info(f"  Fix: ssh -i {px['ssh_key']} ubuntu@{vm['ip']}")

    # Certificate expiry check
    info("Checking certificate expiry...")
    cp_ip = config["cluster"]["control_plane_ip"]
    try:
        with SSHClient(host=cp_ip, user="ubuntu", key_path=px["ssh_key"], timeout=10) as ssh:
            rc_cert, cert_out, _ = ssh.run(
                "sudo kubeadm certs check-expiration 2>/dev/null",
                check=False,
            )
            if rc_cert == 0 and cert_out.strip():
                has_expiry_warning = False
                for cline in cert_out.strip().splitlines():
                    if "EXPIRED" in cline.upper() or "invalid" in cline.lower():
                        has_expiry_warning = True
                        warn(f"  {cline.strip()}")
                if not has_expiry_warning:
                    success("Certificates valid")
                    for cline in cert_out.strip().splitlines()[:8]:
                        console.print(f"    [dim]{cline.strip()}[/dim]")
            else:
                info("  Could not check certificate expiry (kubeadm not available or non-kubeadm cluster)")
    except Exception:
        info("  Could not SSH to control plane for cert check")


# ─── category: networking / dns ──────────────────────────────────────────────


def troubleshoot_networking(config: dict[str, Any]) -> None:
    """Diagnose networking and DNS issues."""
    _section("Networking / DNS")

    # Pod CIDR mismatch detection
    _check_pod_cidr_mismatch(config)

    # CoreDNS pods
    _run_check(
        "CoreDNS pods",
        "kubectl get pods -n kube-system -l k8s-app=kube-dns -o wide",
        heal_cmd="kubectl rollout restart deployment coredns -n kube-system",
    )

    # CoreDNS configmap check
    info("Checking CoreDNS configuration...")
    rc, stdout, _ = run_local(
        "kubectl get configmap coredns -n kube-system "
        "-o jsonpath='{.data.Corefile}' 2>/dev/null",
        check=False,
    )
    if rc == 0 and stdout.strip():
        if "forward" in stdout:
            for line in stdout.splitlines():
                line = line.strip()
                if line.startswith("forward"):
                    success(f"CoreDNS forward config: {line}")
                    break
        else:
            warn("CoreDNS Corefile has no 'forward' directive — external DNS will fail")
    else:
        warn("Could not read CoreDNS configmap")

    # DNS: internal resolution
    info("Testing internal DNS (kubernetes.default)...")
    rc, stdout, stderr = run_local(
        "kubectl run dns-diag --image=busybox:1.36 --rm -i --restart=Never "
        "--timeout=30s -- nslookup kubernetes.default 2>/dev/null",
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
        console.print("    • Pod CIDR mismatch between kubeadm and CNI")
        _attempt_heal(
            "Restart CoreDNS",
            "kubectl rollout restart deployment coredns -n kube-system",
        )

    # DNS: external resolution
    info("Testing external DNS (google.com)...")
    rc, stdout, stderr = run_local(
        "kubectl run dns-diag-ext --image=busybox:1.36 --rm -i --restart=Never "
        "--timeout=30s -- nslookup google.com 2>/dev/null",
        check=False,
    )
    combined = (stdout + stderr).strip()
    if rc == 0 and "address" in combined.lower():
        success("External DNS resolution working")
    else:
        error("External DNS resolution failed")
        console.print("    [yellow]Likely causes:[/yellow]")
        console.print("    • Upstream DNS unreachable from pods")
        console.print("    • NAT/firewall blocking outbound UDP 53")

    # Pod-to-pod connectivity test
    _check_pod_to_pod_connectivity()

    # kube-proxy
    _run_check(
        "kube-proxy pods",
        "kubectl get pods -n kube-system -l k8s-app=kube-proxy -o wide",
        heal_cmd="kubectl rollout restart daemonset kube-proxy -n kube-system",
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


def _check_pod_cidr_mismatch(config: dict[str, Any]) -> None:
    """Detect pod CIDR mismatch between kubeadm and CNI."""
    info("Checking pod CIDR consistency...")

    kubeadm_cidr = _get_kubeadm_pod_cidr()
    if not kubeadm_cidr:
        info("  Could not read kubeadm pod CIDR (non-kubeadm cluster or configmap missing)")
        return

    info(f"  kubeadm pod CIDR: {kubeadm_cidr}")

    # Sample actual pod IPs from CNI-managed pods.
    # Parse JSON in Python and skip hostNetwork pods (etcd, apiserver, kube-proxy,
    # cilium agents, etc.) — their podIP is the node IP and would falsely mismatch.
    # kubectl's jsonpath filter expressions don't reliably support `!=` on missing
    # fields, so we do the filtering here instead.
    rc, stdout, _ = run_local(
        "kubectl get pods -A -o json 2>/dev/null",
        check=False,
    )
    if rc != 0 or not stdout.strip():
        info("  Could not read pod IPs for CIDR comparison")
        return

    try:
        pod_data = json.loads(stdout)
    except json.JSONDecodeError:
        info("  Could not parse pod list for CIDR comparison")
        return

    try:
        expected_net = ipaddress.ip_network(kubeadm_cidr, strict=False)
    except ValueError:
        warn(f"  Invalid kubeadm CIDR: {kubeadm_cidr}")
        return

    mismatched = []
    checked = 0
    for pod in pod_data.get("items", []):
        spec = pod.get("spec", {})
        if spec.get("hostNetwork"):
            continue
        ip_str = (pod.get("status", {}) or {}).get("podIP") or ""
        if not ip_str:
            continue
        try:
            ip = ipaddress.ip_address(ip_str)
        except ValueError:
            continue
        checked += 1
        if ip not in expected_net:
            mismatched.append(ip_str)

    if checked == 0:
        info("  No CNI-managed pod IPs found to compare (cluster may be empty)")
        return

    if mismatched:
        error(f"Pod CIDR mismatch: {len(mismatched)} pod(s) have IPs outside {kubeadm_cidr}")
        for ip_str in mismatched[:5]:
            console.print(f"    [dim]{ip_str}[/dim]")
        console.print("    [yellow]Cause:[/yellow] CNI is using a different CIDR than kubeadm init")

        # Detect CNI and offer specific fix
        rc_cil, stdout_cil, _ = run_local(
            "kubectl get pods -n kube-system -l k8s-app=cilium --no-headers 2>/dev/null",
            check=False,
        )
        if rc_cil == 0 and stdout_cil.strip():
            heal_cmd = (
                f"helm upgrade cilium cilium/cilium --namespace kube-system "
                f"--set operator.replicas=1 "
                f"--set ipam.operator.clusterPoolIPv4PodCIDRList={kubeadm_cidr} "
                f"--reuse-values"
            )
            if check_local_tool("helm"):
                if _attempt_heal("Upgrade Cilium with correct pod CIDR", heal_cmd):
                    _attempt_heal(
                        "Restart Cilium agents",
                        "kubectl rollout restart daemonset cilium -n kube-system",
                    )
                    _attempt_heal(
                        "Restart CoreDNS (re-allocate IPs)",
                        "kubectl rollout restart deployment coredns -n kube-system",
                    )
            else:
                console.print(f"    [yellow]Manual fix:[/yellow] {heal_cmd}")

        rc_cal, stdout_cal, _ = run_local(
            "kubectl get pods -n kube-system -l k8s-app=calico-node --no-headers 2>/dev/null",
            check=False,
        )
        if rc_cal == 0 and stdout_cal.strip():
            heal_cmd = (
                f"kubectl set env daemonset/calico-node -n kube-system "
                f"CALICO_IPV4POOL_CIDR={kubeadm_cidr}"
            )
            if _attempt_heal("Set Calico IP pool to match kubeadm CIDR", heal_cmd):
                _attempt_heal(
                    "Restart Calico nodes",
                    "kubectl rollout restart daemonset calico-node -n kube-system",
                )
                _attempt_heal(
                    "Restart CoreDNS (re-allocate IPs)",
                    "kubectl rollout restart deployment coredns -n kube-system",
                )
    else:
        success(f"Pod CIDRs consistent with kubeadm ({kubeadm_cidr})")


def _check_pod_to_pod_connectivity() -> None:
    """Test pod-to-pod connectivity across nodes."""
    info("Testing pod-to-pod connectivity...")

    # Only use schedulable, Ready nodes that are NOT tainted with NoSchedule
    # (skips control-plane nodes by default so test pods actually start).
    rc, stdout, _ = run_local(
        "kubectl get nodes -o json 2>/dev/null",
        check=False,
    )
    if rc != 0 or not stdout.strip():
        warn("  Could not list nodes for connectivity test")
        return

    try:
        node_data = json.loads(stdout)
    except json.JSONDecodeError:
        warn("  Could not parse node list")
        return

    schedulable: list[str] = []
    for item in node_data.get("items", []):
        name = item.get("metadata", {}).get("name", "")
        if not name:
            continue
        if item.get("spec", {}).get("unschedulable"):
            continue
        taints = item.get("spec", {}).get("taints") or []
        if any(t.get("effect") in ("NoSchedule", "NoExecute") for t in taints):
            continue
        ready = any(
            c.get("type") == "Ready" and c.get("status") == "True"
            for c in item.get("status", {}).get("conditions", [])
        )
        if ready:
            schedulable.append(name)

    if len(schedulable) < 2:
        info(
            f"  Need ≥2 schedulable worker nodes for cross-node test "
            f"(found {len(schedulable)}) — skipping"
        )
        return

    node_a, node_b = schedulable[0], schedulable[1]

    def _spawn(name: str, node: str) -> None:
        run_local(
            f"kubectl run {name} --image=busybox:1.36 --restart=Never "
            f"--overrides='{{\"spec\":{{\"nodeName\":\"{node}\"}}}}' "
            f"--command -- sleep 60",
            check=False,
        )

    try:
        _spawn("p2p-test-a", node_a)
        _spawn("p2p-test-b", node_b)

        # Wait for both pods; capture rc so we can detect scheduling/pull failures.
        rc_wait, _, _ = run_local(
            "kubectl wait --for=condition=ready pod/p2p-test-a pod/p2p-test-b "
            "--timeout=60s",
            check=False,
        )
        if rc_wait != 0:
            error("Pod-to-pod test pods did not become Ready")
            rc_desc, desc_out, _ = run_local(
                "kubectl get pod p2p-test-a p2p-test-b "
                "-o custom-columns=NAME:.metadata.name,NODE:.spec.nodeName,"
                "PHASE:.status.phase,IP:.status.podIP,REASON:.status.reason "
                "--no-headers 2>/dev/null",
                check=False,
            )
            if rc_desc == 0 and desc_out.strip():
                for line in desc_out.strip().splitlines():
                    console.print(f"    [dim]{line}[/dim]")
            console.print("    [yellow]Test inconclusive[/yellow] — pods never ran, so "
                          "connectivity was not actually exercised.")
            return

        rc, pod_b_ip, _ = run_local(
            "kubectl get pod p2p-test-b -o jsonpath='{.status.podIP}' 2>/dev/null",
            check=False,
        )
        if not (rc == 0 and pod_b_ip.strip()):
            warn("  Could not get pod B IP for connectivity test")
            return

        pod_b_ip = pod_b_ip.strip()
        rc_ping, ping_out, ping_err = run_local(
            f"kubectl exec p2p-test-a -- ping -c 3 -W 5 {pod_b_ip}",
            check=False,
        )
        if rc_ping == 0:
            success(f"Pod-to-pod connectivity OK ({node_a} → {node_b}, {pod_b_ip})")
            for line in ping_out.strip().splitlines():
                if "rtt" in line or "round-trip" in line:
                    console.print(f"    [dim]{line.strip()}[/dim]")
        else:
            error(f"Pod-to-pod connectivity FAILED ({node_a} → {node_b})")
            console.print(f"    [dim]Could not ping {pod_b_ip} from {node_a}[/dim]")
            for line in (ping_out + ping_err).strip().splitlines()[-5:]:
                if line.strip():
                    console.print(f"    [dim]{line.strip()}[/dim]")
            console.print("    [yellow]Likely causes:[/yellow]")
            console.print("    • CNI not routing cross-node traffic (tunnel/overlay down)")
            console.print("    • Firewall blocking VXLAN (UDP 8472) / Geneve (UDP 6081)")
            console.print("    • Stale routes after CNI reconfigure — try rebooting nodes")
    finally:
        run_local(
            "kubectl delete pod p2p-test-a p2p-test-b "
            "--force --grace-period=0 --ignore-not-found 2>/dev/null",
            check=False,
        )


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
        heal_cmd="kubectl rollout restart daemonset calico-node -n kube-system",
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
        fix="Re-run Phase 5 to re-deploy Calico with correct IP pool",
    )

    # Check BGP vs VXLAN mode
    info("Checking networking backend...")
    rc, stdout, _ = run_local(
        "kubectl get daemonset calico-node -n kube-system "
        "-o jsonpath='{.spec.template.spec.containers[0].env}' 2>/dev/null",
        check=False,
    )
    if rc == 0:
        if "vxlan" in stdout.lower():
            success("Calico backend: VXLAN (overlay)")
        else:
            warn("Calico backend: BGP (may fail on Proxmox)")
            _attempt_heal(
                "Switch Calico to VXLAN mode",
                "kubectl set env daemonset/calico-node -n kube-system "
                "CALICO_NETWORKING_BACKEND=vxlan CALICO_IPV4POOL_VXLAN=Always && "
                "kubectl rollout restart daemonset calico-node -n kube-system",
            )

    # BIRD / BGP status from logs
    info("Checking BGP peering status...")
    rc, stdout, _ = run_local(
        "kubectl logs -n kube-system -l k8s-app=calico-node --tail=30 2>/dev/null "
        "| grep -i 'bird\\|bgp\\|establish\\|error'",
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
        heal_cmd="kubectl rollout restart deployment calico-kube-controllers -n kube-system",
    )


def _troubleshoot_cilium() -> None:
    """Cilium-specific diagnostics."""
    info("Detected CNI: Cilium")
    console.print()

    # Pod status
    _run_check(
        "Cilium agent pods",
        "kubectl get pods -n kube-system -l k8s-app=cilium -o wide",
        heal_cmd="kubectl rollout restart daemonset cilium -n kube-system",
    )

    # Cilium operator
    _run_check(
        "Cilium operator",
        "kubectl get pods -n kube-system -l app.kubernetes.io/name=cilium-operator -o wide",
        heal_cmd="kubectl rollout restart deployment cilium-operator -n kube-system",
    )

    # Cilium CIDR validation
    info("Checking Cilium IPAM configuration...")
    kubeadm_cidr = _get_kubeadm_pod_cidr()

    rc, pod_name, _ = run_local(
        "kubectl get pods -n kube-system -l k8s-app=cilium "
        "-o jsonpath='{.items[0].metadata.name}' 2>/dev/null",
        check=False,
    )
    if rc == 0 and pod_name.strip():
        # Cilium status
        info("Cilium status (from agent pod):")
        rc, stdout, _ = run_local(
            f"kubectl exec -n kube-system {pod_name.strip()} "
            f"-- cilium status --brief 2>/dev/null",
            check=False,
        )
        if rc == 0 and stdout.strip():
            for line in stdout.strip().splitlines()[:15]:
                console.print(f"    [dim]{line}[/dim]")
            if kubeadm_cidr and kubeadm_cidr not in stdout:
                warn(f"  Cilium may not be using kubeadm CIDR ({kubeadm_cidr})")
        else:
            warn("  Could not get cilium status")

        # Cilium health
        info("Cilium health status:")
        rc, stdout, _ = run_local(
            f"kubectl exec -n kube-system {pod_name.strip()} "
            f"-- cilium-health status 2>/dev/null",
            check=False,
        )
        if rc == 0 and stdout.strip():
            for line in stdout.strip().splitlines()[:10]:
                console.print(f"    [dim]{line.strip()}[/dim]")
        else:
            info("  cilium-health not available")

    # Cilium recent logs (errors/warnings only)
    info("Cilium recent logs:")
    rc, stdout, _ = run_local(
        "kubectl logs -n kube-system -l k8s-app=cilium --tail=20 2>/dev/null "
        "| grep -i 'error\\|warn\\|fail'",
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
        if check_local_tool("helm"):
            _attempt_heal(
                "Install nginx-ingress via Helm",
                "helm repo add ingress-nginx https://kubernetes.github.io/ingress-nginx 2>/dev/null; "
                "helm install ingress-nginx ingress-nginx/ingress-nginx "
                "--namespace ingress-nginx --create-namespace "
                "--set controller.service.type=NodePort "
                "--set controller.service.nodePorts.http=30080 "
                "--set controller.service.nodePorts.https=30443",
            )
        else:
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
            heal_cmd="kubectl rollout restart deployment ingress-nginx-controller -n ingress-nginx",
        )

        _run_check(
            "nginx-ingress service",
            "kubectl get svc -n ingress-nginx",
        )

        # Check NodePort allocation
        rc, stdout, _ = run_local(
            "kubectl get svc ingress-nginx-controller -n ingress-nginx "
            "-o jsonpath='{.spec.ports}' 2>/dev/null",
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
            "kubectl logs -n ingress-nginx -l app.kubernetes.io/name=ingress-nginx "
            "--tail=15 2>/dev/null",
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
            heal_cmd="kubectl rollout restart deployment traefik -n kube-system",
        )

    # Test HTTP endpoint on all nodes
    info("Testing HTTP endpoints on all nodes...")
    all_ips = get_all_vm_ips(config)
    any_responding = False
    for ip in all_ips:
        rc, stdout, _ = run_local(
            f"curl -s -o /dev/null -w '%{{http_code}}' --connect-timeout 5 "
            f"http://{ip}:30080 2>/dev/null",
            check=False,
        )
        if rc == 0 and stdout.strip() in ("404", "200", "308"):
            success(f"HTTP responding at {ip}:30080 (status {stdout.strip()})")
            any_responding = True
        else:
            warn(f"HTTP not responding at {ip}:30080")

    if not any_responding and all_ips:
        console.print("    [yellow]No nodes responding on port 30080[/yellow]")
        _attempt_heal(
            "Restart ingress controller",
            "kubectl rollout restart deployment ingress-nginx-controller "
            "-n ingress-nginx 2>/dev/null || "
            "kubectl rollout restart deployment traefik -n kube-system 2>/dev/null",
        )


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
            _attempt_heal(
                "Set local-path as default StorageClass",
                "kubectl patch storageclass local-path -p "
                "'{\"metadata\":{\"annotations\":{\"storageclass.kubernetes.io/is-default-class\":\"true\"}}}'",
                verify_cmd="kubectl get storageclass",
            )
        for line in stdout.strip().splitlines():
            console.print(f"    [dim]{line}[/dim]")
    else:
        error("No StorageClasses found")
        _attempt_heal(
            "Install local-path-provisioner",
            "kubectl apply -f https://raw.githubusercontent.com/rancher/local-path-provisioner/v0.0.24/deploy/local-path-storage.yaml",
            verify_cmd="kubectl get storageclass",
            wait_secs=10,
        )

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
                if len(parts) >= 2:
                    ns, name = parts[0], parts[1]
                    warn(f"  PVC {name} in {ns} is Pending")
                    # Show events for this PVC
                    rc_ev, ev_out, _ = run_local(
                        f"kubectl describe pvc {name} -n {ns} 2>/dev/null | tail -5",
                        check=False,
                    )
                    if rc_ev == 0 and ev_out.strip():
                        for ev_line in ev_out.strip().splitlines():
                            console.print(f"    [dim]{ev_line.strip()}[/dim]")
                    _attempt_heal(
                        f"Delete stuck PVC {name} in {ns}",
                        f"kubectl delete pvc {name} -n {ns}",
                    )

    # local-path-provisioner pod
    _run_check(
        "local-path-provisioner pod",
        "kubectl get pods -n local-path-storage -o wide 2>/dev/null",
        heal_cmd="kubectl apply -f https://raw.githubusercontent.com/rancher/local-path-provisioner/v0.0.24/deploy/local-path-storage.yaml",
    )


# ─── category: pods ──────────────────────────────────────────────────────────


def troubleshoot_pods(config: dict[str, Any]) -> None:
    """Diagnose pod-level issues: CrashLoop, stale, pending."""
    _section("Pods")

    _check_crashloop_pods()
    _check_stale_pods()
    _check_pending_pods()


def _check_crashloop_pods() -> None:
    """Find and diagnose CrashLoopBackOff / Error pods."""
    info("Scanning for CrashLoopBackOff / Error pods...")

    rc, stdout, _ = run_local(
        "kubectl get pods --all-namespaces --no-headers 2>/dev/null",
        check=False,
    )
    if rc != 0 or not stdout.strip():
        info("  No pods found or kubectl unavailable")
        return

    problem_pods = []
    for line in stdout.strip().splitlines():
        parts = line.split()
        if len(parts) < 4:
            continue
        ns, name, status = parts[0], parts[1], parts[3]
        if status in ("CrashLoopBackOff", "Error", "CreateContainerConfigError", "ImagePullBackOff"):
            problem_pods.append((ns, name, status))

    if not problem_pods:
        success("No CrashLoopBackOff or Error pods")
        return

    error(f"Found {len(problem_pods)} problem pod(s)")
    for ns, name, status in problem_pods:
        console.print(f"    [yellow]{status}[/yellow]: {ns}/{name}")
        # Pull last few log lines
        rc_log, log_out, _ = run_local(
            f"kubectl logs {name} -n {ns} --tail=10 2>/dev/null",
            check=False,
        )
        if rc_log == 0 and log_out.strip():
            for log_line in log_out.strip().splitlines()[:5]:
                console.print(f"      [dim]{log_line.strip()}[/dim]")
        else:
            # Try previous container logs
            rc_log, log_out, _ = run_local(
                f"kubectl logs {name} -n {ns} --previous --tail=10 2>/dev/null",
                check=False,
            )
            if rc_log == 0 and log_out.strip():
                console.print("      [dim](from previous container)[/dim]")
                for log_line in log_out.strip().splitlines()[:5]:
                    console.print(f"      [dim]{log_line.strip()}[/dim]")

        _attempt_heal(
            f"Delete pod {ns}/{name} (will be recreated by controller)",
            f"kubectl delete pod {name} -n {ns} --grace-period=30",
        )


def _check_stale_pods() -> None:
    """Find and clean up Evicted / Succeeded / Unknown pods."""
    info("Scanning for stale pods (Evicted/Succeeded/Unknown)...")

    # Catch Evicted pods via JSON (status.reason field)
    stale: list[tuple[str, str, str]] = []
    rc, stdout, _ = run_local(
        "kubectl get pods --all-namespaces -o json 2>/dev/null",
        check=False,
    )
    if rc == 0 and stdout.strip():
        try:
            pods_data = json.loads(stdout)
            for pod in pods_data.get("items", []):
                ns = pod["metadata"]["namespace"]
                name = pod["metadata"]["name"]
                phase = pod.get("status", {}).get("phase", "")
                reason = pod.get("status", {}).get("reason", "")
                if reason == "Evicted" or phase in ("Succeeded", "Failed", "Unknown"):
                    label = reason if reason else phase
                    if (ns, name, label) not in stale:
                        stale.append((ns, name, label))
        except (json.JSONDecodeError, KeyError):
            pass

    if not stale:
        success("No stale pods found")
        return

    warn(f"Found {len(stale)} stale pod(s)")
    for ns, name, status in stale[:10]:
        console.print(f"    [dim]{status}: {ns}/{name}[/dim]")
    if len(stale) > 10:
        console.print(f"    [dim]... and {len(stale) - 10} more[/dim]")

    # Bulk cleanup
    namespaces = set(ns for ns, _, _ in stale)
    cleanup_cmds = []
    for ns in sorted(namespaces):
        ns_pods = [name for n, name, _ in stale if n == ns]
        if ns_pods:
            cleanup_cmds.append(
                f"kubectl delete pod -n {ns} {' '.join(ns_pods)} --grace-period=0 --force"
            )
    cleanup_cmd = " && ".join(cleanup_cmds)
    _attempt_heal(f"Clean up {len(stale)} stale pod(s)", cleanup_cmd)


def _check_pending_pods() -> None:
    """Diagnose Pending pods — check events for scheduling failures."""
    info("Scanning for Pending pods...")

    rc, stdout, _ = run_local(
        "kubectl get pods --all-namespaces "
        "--field-selector=status.phase=Pending --no-headers 2>/dev/null",
        check=False,
    )
    if rc != 0 or not stdout.strip():
        success("No Pending pods")
        return

    pending = []
    for line in stdout.strip().splitlines():
        parts = line.split()
        if len(parts) >= 2:
            pending.append((parts[0], parts[1]))

    if not pending:
        success("No Pending pods")
        return

    warn(f"Found {len(pending)} Pending pod(s)")
    for ns, name in pending[:10]:
        console.print(f"    [yellow]Pending[/yellow]: {ns}/{name}")
        # Get events
        rc_ev, ev_out, _ = run_local(
            f"kubectl get events -n {ns} --field-selector involvedObject.name={name} "
            f"--sort-by=.lastTimestamp 2>/dev/null | tail -5",
            check=False,
        )
        if rc_ev == 0 and ev_out.strip():
            for ev_line in ev_out.strip().splitlines():
                console.print(f"      [dim]{ev_line.strip()}[/dim]")
        else:
            # Fallback: describe pod
            rc_desc, desc_out, _ = run_local(
                f"kubectl describe pod {name} -n {ns} 2>/dev/null | grep -A3 Events",
                check=False,
            )
            if rc_desc == 0 and desc_out.strip():
                for desc_line in desc_out.strip().splitlines()[:5]:
                    console.print(f"      [dim]{desc_line.strip()}[/dim]")


# ─── menu ────────────────────────────────────────────────────────────────────


def run_troubleshoot(config: dict[str, Any]) -> None:
    """Interactive troubleshooting sub-menu with self-healing."""
    categories = {
        "1": ("Nodes", troubleshoot_nodes),
        "2": ("Networking / DNS", troubleshoot_networking),
        "3": ("CNI", troubleshoot_cni),
        "4": ("Ingress", troubleshoot_ingress),
        "5": ("Storage", troubleshoot_storage),
        "6": ("Pods", troubleshoot_pods),
    }

    while True:
        console.print()
        console.print("[bold]Troubleshoot Menu[/bold]")
        console.print("  [cyan]1[/cyan]. Nodes       — status, kubelet logs, resources, certs")
        console.print("  [cyan]2[/cyan]. Networking  — DNS, pod-to-pod, CIDR mismatch, CoreDNS config")
        console.print("  [cyan]3[/cyan]. CNI         — Calico/Cilium pods, CIDR validation, connectivity")
        console.print("  [cyan]4[/cyan]. Ingress     — pods, services, endpoint health (all nodes)")
        console.print("  [cyan]5[/cyan]. Storage     — StorageClass, PVC status, provisioner")
        console.print("  [cyan]6[/cyan]. Pods        — CrashLoop, stale cleanup, pending diagnosis")
        console.print("  [cyan]7[/cyan]. Run All     — run all categories in sequence")
        console.print("  [cyan]0[/cyan]. Back")
        console.print()

        choice = console.input("[bold]Select> [/bold]").strip()

        if choice == "0":
            break
        elif choice == "7":
            for key in ("1", "2", "3", "4", "5", "6"):
                label, func = categories[key]
                func(config)
        elif choice in categories:
            label, func = categories[choice]
            func(config)
        else:
            warn("Invalid selection")

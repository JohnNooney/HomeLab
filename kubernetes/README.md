# Overview
This directory contains Kubernetes manifests and configurations for bootstrapping essential cluster services after the bare-metal infrastructure has been provisioned.

## Phase 3: Cluster Bootstrapping (Kubernetes/Helm)

This phase deploys the foundational components required for a fully functional Kubernetes cluster, including networking, DNS automation, secrets management, and ingress connectivity.

### Prerequisites
- Kubernetes cluster initialized via Ansible (Phase 2 complete)
- kubectl configured with cluster admin access
- Helm >= 3.0 installed
- AWS credentials configured (for external-dns and external-secrets-operator)
- EC2 ingress tunnel node deployed and accessible (from Phase 1)

### Deployment Steps

#### 3.1 Container Network Interface (CNI)
**Purpose**: Deploy a CNI plugin to enable pod-to-pod networking across the cluster.

**Option A: Calico**
```bash
# Download Calico manifest
curl https://raw.githubusercontent.com/projectcalico/calico/v3.26.0/manifests/calico.yaml -O

# Apply Calico
kubectl apply -f calico.yaml

# Verify deployment
kubectl get pods -n kube-system -l k8s-app=calico-node
kubectl get pods -n kube-system -l k8s-app=calico-kube-controllers
```

**Option B: Cilium**
```bash
# Add Cilium Helm repository
helm repo add cilium https://helm.cilium.io/
helm repo update

# Install Cilium
helm install cilium cilium/cilium \
  --namespace kube-system \
  --set operator.replicas=1

# Verify deployment
kubectl get pods -n kube-system -l k8s-app=cilium
cilium status --wait
```

**Post-Deployment Validation**:
```bash
# Nodes should now be Ready
kubectl get nodes

# All kube-system pods should be Running
kubectl get pods -n kube-system

# Test pod networking
kubectl run test-pod --image=nginx --rm -it -- /bin/bash
```

**Configuration Notes**:
- Ensure pod CIDR matches what was configured during `kubeadm init` (e.g., `10.244.0.0/16`)
- For Calico: Configure IP-in-IP or VXLAN encapsulation based on network requirements
- For Cilium: Enable Hubble for network observability (optional)

#### 3.2 External DNS
**Purpose**: Automatically sync Kubernetes Ingress and Service resources with AWS Route 53 DNS records.

```bash
# Create namespace
kubectl create namespace external-dns

# Create AWS credentials secret
kubectl create secret generic external-dns-aws \
  --from-literal=aws-access-key-id=<AWS_ACCESS_KEY_ID> \
  --from-literal=aws-secret-access-key=<AWS_SECRET_ACCESS_KEY> \
  -n external-dns

# Add external-dns Helm repository
helm repo add external-dns https://kubernetes-sigs.github.io/external-dns/
helm repo update

# Install external-dns
helm install external-dns external-dns/external-dns \
  --namespace external-dns \
  --set provider=aws \
  --set aws.region=us-east-1 \
  --set aws.zoneType=public \
  --set txtOwnerId=homelab-cluster \
  --set policy=sync \
  --set sources[0]=ingress \
  --set sources[1]=service \
  --set domainFilters[0]=yourdomain.com
```

**Alternative: Using IAM Roles (IRSA)**
```bash
# If using IRSA instead of static credentials
helm install external-dns external-dns/external-dns \
  --namespace external-dns \
  --set provider=aws \
  --set serviceAccount.annotations."eks\.amazonaws\.com/role-arn"=arn:aws:iam::ACCOUNT:role/external-dns
```

**Validation**:
```bash
# Check external-dns logs
kubectl logs -n external-dns -l app.kubernetes.io/name=external-dns

# Verify DNS records are created when you deploy an Ingress
kubectl get ingress --all-namespaces
```

**Configuration**:
- `txtOwnerId`: Unique identifier for this cluster's DNS records
- `policy=sync`: Automatically create and delete DNS records
- `domainFilters`: Restrict to specific domains managed by this cluster

#### 3.3 External Secrets Operator (ESO)
**Purpose**: Sync secrets from AWS Secrets Manager to Kubernetes native Secret resources.

```bash
# Add external-secrets Helm repository
helm repo add external-secrets https://charts.external-secrets.io
helm repo update

# Install external-secrets-operator
helm install external-secrets external-secrets/external-secrets \
  --namespace external-secrets \
  --create-namespace \
  --set installCRDs=true
```

**Create SecretStore**:
```yaml
# secretstore.yaml
apiVersion: external-secrets.io/v1beta1
kind: SecretStore
metadata:
  name: aws-secretsmanager
  namespace: default
spec:
  provider:
    aws:
      service: SecretsManager
      region: us-east-1
      auth:
        secretRef:
          accessKeyIDSecretRef:
            name: aws-credentials
            key: access-key-id
          secretAccessKeySecretRef:
            name: aws-credentials
            key: secret-access-key
```

```bash
# Create AWS credentials for ESO
kubectl create secret generic aws-credentials \
  --from-literal=access-key-id=<AWS_ACCESS_KEY_ID> \
  --from-literal=secret-access-key=<AWS_SECRET_ACCESS_KEY> \
  -n default

# Apply SecretStore
kubectl apply -f secretstore.yaml
```

**Create ExternalSecret Example**:
```yaml
# externalsecret.yaml
apiVersion: external-secrets.io/v1beta1
kind: ExternalSecret
metadata:
  name: example-secret
  namespace: default
spec:
  refreshInterval: 1h
  secretStoreRef:
    name: aws-secretsmanager
    kind: SecretStore
  target:
    name: example-secret
    creationPolicy: Owner
  data:
  - secretKey: password
    remoteRef:
      key: homelab/example
      property: password
```

```bash
# Apply ExternalSecret
kubectl apply -f externalsecret.yaml

# Verify secret was created
kubectl get secret example-secret -o yaml
```

**Validation**:
```bash
# Check ESO pods
kubectl get pods -n external-secrets

# Check SecretStore status
kubectl get secretstore

# Check ExternalSecret status
kubectl get externalsecret
kubectl describe externalsecret example-secret
```

#### 3.4 Tailscale Subnet Router (k8s Control Plane)
**Purpose**: Connect the k8s control plane to the same Tailscale network as the EC2 ingress tunnel, so the EC2 reverse proxy can forward traffic into the cluster over an encrypted private network.

> The EC2 ingress tunnel is already on Tailscale via `terraform/aws/modules/ingress_tunnel/user_data.sh`. This step joins the k8s control plane to the same tailnet.

**Step 1 — Generate a Tailscale auth key**

In the [Tailscale admin console](https://login.tailscale.com/admin/settings/keys), generate a reusable (or one-off) auth key scoped to the same tailnet as the EC2 instance.

**Step 2 — Install Tailscale on the control plane node**
```bash
# On k8s-control-01
curl -fsSL https://tailscale.com/install.sh | sh

# Join the tailnet and advertise the pod CIDR and service CIDR as subnet routes
sudo tailscale up \
  --authkey="<your-auth-key>" \
  --advertise-routes=10.244.0.0/16,10.96.0.0/12 \
  --accept-dns=false
```

> `10.244.0.0/16` is the pod CIDR (set during kubeadm init via `pod_cidr` in the Ansible inventory).  
> `10.96.0.0/12` is the kubeadm default service CIDR.

**Step 3 — Approve the device and routes in the Tailscale admin console**
- Go to [Machines](https://login.tailscale.com/admin/machines) and approve `k8s-control-01`
- Under the device settings, enable the advertised subnet routes

**Step 4 — Note the Tailscale IP**
```bash
# On k8s-control-01 — note the 100.x.x.x Tailscale IP
tailscale status
```
> This IP is used in the EC2 nginx reverse proxy configuration (step 3.7).

**Validation**:
```bash
# From the EC2 instance (via Tailscale SSH or AWS SSM), verify reachability
ping <k8s-control-01-tailscale-ip>

# Verify subnet routes are active
tailscale status --peers
```

---

#### 3.5 nginx-ingress Controller (via ArgoCD)
**Purpose**: Route inbound traffic from the EC2 reverse proxy to the correct application pod based on the HTTP `Host` header.

Create `argocd/nginx-ingress-manifest.yml` (already in this repo) and apply it:
```bash
kubectl apply -f argocd/nginx-ingress-manifest.yml -n argocd
```

This deploys nginx-ingress with `NodePort` services on fixed ports:
- `30080` → HTTP
- `30443` → HTTPS (TLS passthrough from EC2)

**Validation**:
```bash
# Confirm NodePort services are assigned
kubectl get svc -n ingress-nginx
# Expected: 80:30080/TCP, 443:30443/TCP

kubectl get pods -n ingress-nginx
```

---

#### 3.6 cert-manager ClusterIssuer
**Purpose**: Automatically provision Let's Encrypt TLS certificates for exposed applications. cert-manager is already deployed via ArgoCD — this step configures the ACME issuer.

Apply the ClusterIssuer manifest (already in this repo):
```bash
kubectl apply -f terraform/homelab/cluster-issuer.yaml
```

**Validation**:
```bash
kubectl get clusterissuer letsencrypt-prod
# Expected: READY = True
```

---

#### 3.7 EC2 nginx Reverse Proxy
**Purpose**: Forward public internet traffic arriving at the Elastic IP (ports 80/443) to the nginx-ingress NodePort on the k8s control plane via Tailscale.

SSH to the EC2 ingress tunnel instance (via Tailscale SSH or AWS SSM Session Manager) and run:
```bash
sudo dnf install -y nginx

sudo tee /etc/nginx/nginx.conf > /dev/null <<'EOF'
events {}
stream {
  upstream k8s_https {
    server <k8s-control-01-tailscale-ip>:30443;
  }
  upstream k8s_http {
    server <k8s-control-01-tailscale-ip>:30080;
  }
  server {
    listen 443;
    proxy_pass k8s_https;
    proxy_timeout 600s;
  }
  server {
    listen 80;
    proxy_pass k8s_http;
    proxy_timeout 600s;
  }
}
EOF

sudo nginx -t
sudo systemctl enable --now nginx
```

Replace `<k8s-control-01-tailscale-ip>` with the `100.x.x.x` address noted in step 3.4.

> **Note**: This is a TCP stream (passthrough) proxy — TLS terminates at nginx-ingress inside the cluster. cert-manager HTTP-01 challenges work transparently via the port 80 passthrough.

**Validation**:
```bash
sudo systemctl status nginx
curl -v http://<EC2-ELASTIC-IP>  # Should reach the cluster
```

---

#### 3.8 Route53 Wildcard DNS Record
**Purpose**: Route all `*.homelab.nooney.dev` requests to the EC2 Elastic IP. This is a one-time change — every new app you expose gets DNS automatically.

This requires a Terraform change. Add the variable and record as described in `terraform/README.md` (section: Route53 Wildcard Record), then apply:
```bash
cd terraform/aws
terraform plan -target=module.route53
terraform apply -target=module.route53
```

**Validation**:
```bash
nslookup grafana.homelab.nooney.dev
# Should resolve to the EC2 Elastic IP

nslookup anything.homelab.nooney.dev
# Should also resolve to the same EC2 Elastic IP (wildcard)
```

### Complete Bootstrap Deployment

Deploy all components in sequence:
```bash
# 1. CNI
kubectl apply -f manifests/cni/

# 2. External DNS
kubectl apply -f manifests/external-dns/

# 3. External Secrets Operator
kubectl apply -f manifests/external-secrets/

# 4. Ingress and tunnel
kubectl apply -f manifests/ingress/
```

### Validation Checklist

After completing Phase 3, verify:
```bash
# All nodes are Ready
kubectl get nodes

# All system pods are Running
kubectl get pods --all-namespaces

# DNS resolution works
kubectl run -it --rm debug --image=busybox --restart=Never -- nslookup kubernetes.default

# External DNS is syncing
kubectl logs -n external-dns -l app.kubernetes.io/name=external-dns

# External Secrets are syncing
kubectl get externalsecret --all-namespaces

# Ingress controller is running
kubectl get pods -n ingress-nginx

# Tunnel connectivity
ping <EC2_TUNNEL_IP>
```

### Troubleshooting

**CNI Issues**:
```bash
# Check CNI pods
kubectl get pods -n kube-system -l k8s-app=calico-node
kubectl logs -n kube-system -l k8s-app=calico-node

# Verify network policies
kubectl get networkpolicies --all-namespaces
```

**External DNS Issues**:
```bash
# Check logs
kubectl logs -n external-dns -l app.kubernetes.io/name=external-dns

# Verify AWS credentials
kubectl get secret -n external-dns

# Check Route 53 records manually
aws route53 list-resource-record-sets --hosted-zone-id <ZONE_ID>
```

**External Secrets Issues**:
```bash
# Check operator logs
kubectl logs -n external-secrets -l app.kubernetes.io/name=external-secrets

# Check SecretStore status
kubectl describe secretstore aws-secretsmanager

# Verify AWS Secrets Manager access
aws secretsmanager list-secrets
```

### Next Steps

After cluster bootstrapping is complete, proceed to **Phase 4: Application Deployment** to deploy your workloads via ArgoCD.

---

## Runbook: Exposing a New App via the Ingress Tunnel

> **Prerequisites**: Sections 3.4–3.8 must be complete (one-time setup) before following this runbook.

This is the repeatable process for routing a deployed application to a public `<app>.homelab.nooney.dev` URL. The wildcard DNS record and EC2 nginx proxy are already in place — for each new app you only need to add a Kubernetes Ingress resource.

### What you need before starting
- App already deployed to the cluster (via ArgoCD)
- Kubernetes **Service name** and **port** the app exposes
- Desired hostname: `<app>.homelab.nooney.dev`
- The **namespace** the app is deployed in

---

### Step 1 — Add an Ingress resource to the app's Helm values

In the ArgoCD app manifest (e.g. `argocd/<app>-manifest.yml`), add an `ingress` block under the helm values:

```yaml
ingress:
  enabled: true
  ingressClassName: nginx
  annotations:
    cert-manager.io/cluster-issuer: letsencrypt-prod
  hosts:
    - host: <app>.homelab.nooney.dev
      paths:
        - path: /
          pathType: Prefix
  tls:
    - secretName: <app>-tls
      hosts:
        - <app>.homelab.nooney.dev
```

**Grafana example** — add to the `helm.values` block in `argocd/prometheus-manifest.yml`:
```yaml
grafana:
  ingress:
    enabled: true
    ingressClassName: nginx
    annotations:
      cert-manager.io/cluster-issuer: letsencrypt-prod
    hosts:
      - grafana.homelab.nooney.dev
    tls:
      - secretName: grafana-tls
        hosts:
          - grafana.homelab.nooney.dev
```

Apply / sync the ArgoCD application:
```bash
kubectl apply -f argocd/<app>-manifest.yml -n argocd

# Or sync via CLI
argocd app sync <app-name>
```

---

### Step 2 — Verify the Ingress was created

```bash
kubectl get ingress -n <namespace>
# Should show the hostname and ingressClassName: nginx

kubectl describe ingress <app> -n <namespace>
```

---

### Step 3 — Verify the TLS certificate is issued

```bash
# Certificate resource is created automatically by cert-manager
kubectl get certificate -n <namespace>
# Wait for READY = True

# If not ready, inspect the challenge
kubectl get certificaterequest -n <namespace>
kubectl get challenge -n <namespace>
kubectl describe challenge -n <namespace>
```

> **Troubleshooting certificate issuance**:
> - Confirm port 80 is open in the EC2 Security Group (it is by default)
> - Confirm nginx on EC2 is forwarding port 80 to the k8s node: `curl http://<app>.homelab.nooney.dev/.well-known/acme-challenge/test`
> - Check cert-manager logs: `kubectl logs -n cert-manager -l app=cert-manager`

---

### Step 4 — Test end-to-end connectivity

```bash
# DNS should resolve to the EC2 Elastic IP
nslookup <app>.homelab.nooney.dev

# HTTPS should return the app (or a redirect)
curl -v https://<app>.homelab.nooney.dev
```

---

### Exposed Apps Reference

| App | URL | Namespace | Service | Port |
|-----|-----|-----------|---------|------|
| Grafana | `grafana.homelab.nooney.dev` | `monitoring` | `prometheus-grafana` | `80` |
| Prometheus | `prometheus.homelab.nooney.dev` | `monitoring` | `prometheus-kube-prometheus-prometheus` | `9090` |
| Alertmanager | `alertmanager.homelab.nooney.dev` | `monitoring` | `prometheus-kube-prometheus-alertmanager` | `9093` |

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

#### 3.4 Ingress Tunnel Connection
**Purpose**: Establish connectivity between the on-premises cluster and the AWS EC2 ingress tunnel node.

**Option A: WireGuard**

1. **Install WireGuard on cluster nodes**:
```bash
# On each node
sudo apt install wireguard

# Generate keys
wg genkey | tee privatekey | wg pubkey > publickey
```

2. **Configure WireGuard**:
```bash
# /etc/wireguard/wg0.conf on cluster node
[Interface]
PrivateKey = <NODE_PRIVATE_KEY>
Address = 10.0.0.2/24
ListenPort = 51820

[Peer]
PublicKey = <EC2_PUBLIC_KEY>
Endpoint = <EC2_ELASTIC_IP>:51820
AllowedIPs = 10.0.0.0/24
PersistentKeepalive = 25
```

3. **Start WireGuard**:
```bash
sudo wg-quick up wg0
sudo systemctl enable wg-quick@wg0
```

**Option B: Tailscale**

1. **Install Tailscale on cluster nodes**:
```bash
curl -fsSL https://tailscale.com/install.sh | sh
```

2. **Authenticate and connect**:
```bash
sudo tailscale up --advertise-routes=10.244.0.0/16
```

3. **Deploy Tailscale operator in cluster** (optional):
```bash
# Add Tailscale Helm repo
helm repo add tailscale https://pkgs.tailscale.com/helmcharts
helm repo update

# Install Tailscale operator
helm install tailscale-operator tailscale/tailscale-operator \
  --namespace tailscale \
  --create-namespace \
  --set oauth.clientId=<CLIENT_ID> \
  --set oauth.clientSecret=<CLIENT_SECRET>
```

**Configure Ingress Controller**:
```bash
# Install nginx-ingress-controller
helm repo add ingress-nginx https://kubernetes.github.io/ingress-nginx
helm repo update

helm install ingress-nginx ingress-nginx/ingress-nginx \
  --namespace ingress-nginx \
  --create-namespace \
  --set controller.service.type=NodePort \
  --set controller.service.nodePorts.http=30080 \
  --set controller.service.nodePorts.https=30443
```

**Validation**:
```bash
# Test tunnel connectivity
ping <EC2_TUNNEL_IP>

# Check ingress controller
kubectl get pods -n ingress-nginx
kubectl get svc -n ingress-nginx

# Test ingress routing
kubectl create deployment test --image=nginx
kubectl expose deployment test --port=80
kubectl create ingress test --class=nginx --rule="test.yourdomain.com/*=test:80"
curl http://test.yourdomain.com
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

After cluster bootstrapping is complete, proceed to **Phase 4: Application Deployment** to deploy your workloads using Terraform-managed Helm charts.

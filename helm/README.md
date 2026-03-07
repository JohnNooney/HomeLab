# Overview
This directory contains **Helm values files** for deploying applications to the Kubernetes cluster. Applications are deployed using **Terraform to manage Helm releases** from public chart repositories, providing infrastructure-as-code benefits for application deployments.

## Important Notes

**This directory does NOT contain custom Helm charts.** Instead, it stores:
- Custom `values.yaml` files for each application
- Configuration overrides for public Helm charts
- Documentation for the deployment approach

All Helm charts are sourced from public repositories such as:
- **bjw-s/helm-charts** (formerly k8s-at-home): Media applications (Plex, Sonarr, Radarr, etc.)
- **Prometheus Community**: Monitoring stack (kube-prometheus-stack)
- **Bitnami**: Databases and common services (PostgreSQL, Redis, etc.)
- **Official repositories**: Application-specific charts (Immich, Home Assistant, etc.)

Terraform references these remote chart repositories and uses the values files in this directory to customize each deployment.

## Phase 4: Application Deployment (Terraform + Helm)

This phase deploys application workloads to the Kubernetes cluster using Terraform's Helm provider. This approach combines the benefits of Helm's package management with Terraform's state management and dependency handling.

### Why Terraform + Helm?

**Benefits**:
- **Infrastructure as Code**: Application deployments tracked in version control
- **State Management**: Terraform state tracks deployed releases
- **Dependency Management**: Ensure applications deploy in correct order
- **Unified Workflow**: Same tooling for cloud infrastructure and applications
- **Drift Detection**: Terraform can detect and correct configuration drift
- **Rollback Capability**: Easy rollback via Terraform state

### Prerequisites
- Kubernetes cluster fully bootstrapped (Phase 3 complete)
- Terraform >= 1.0 installed
- kubectl configured with cluster access
- Helm >= 3.0 installed (for local testing)
- Cluster has sufficient resources for application workloads

### Architecture

```
HomeLab/
├── terraform/
│   └── homelab/
│       ├── main.tf                 # Main Terraform configuration
│       ├── providers.tf            # Kubernetes and Helm provider config
│       ├── variables.tf            # Input variables
│       ├── outputs.tf              # Output values
│       ├── observability.tf        # Monitoring stack (Prometheus, Grafana)
│       ├── media.tf                # Media server applications
│       └── services.tf             # Home automation and other services
└── helm/
    ├── README.md                   # This file
    └── values/                     # Helm values files
        ├── prometheus-stack.yaml
        ├── plex.yaml
        ├── sonarr.yaml
        ├── radarr.yaml
        ├── prowlarr.yaml
        ├── lidarr.yaml
        ├── bazarr.yaml
        ├── transmission.yaml
        ├── home-assistant.yaml
        ├── immich.yaml
        └── ...
```

### Terraform Configuration

**providers.tf**:
```hcl
terraform {
  required_providers {
    kubernetes = {
      source  = "hashicorp/kubernetes"
      version = "~> 2.23"
    }
    helm = {
      source  = "hashicorp/helm"
      version = "~> 2.11"
    }
  }
}

provider "kubernetes" {
  config_path = "~/.kube/config"
}

provider "helm" {
  kubernetes {
    config_path = "~/.kube/config"
  }
}
```

### Deployment Steps

#### 4.1 Observability Stack
**Purpose**: Deploy monitoring and observability tools (Prometheus, Grafana, Alertmanager).

**Terraform Configuration** (`observability.tf`):
```hcl
resource "kubernetes_namespace" "monitoring" {
  metadata {
    name = "monitoring"
  }
}

resource "helm_release" "kube_prometheus_stack" {
  name       = "kube-prometheus-stack"
  repository = "https://prometheus-community.github.io/helm-charts"
  chart      = "kube-prometheus-stack"
  namespace  = kubernetes_namespace.monitoring.metadata[0].name
  version    = "54.0.0"

  values = [
    file("${path.module}/values/prometheus-stack.yaml")
  ]

  set {
    name  = "grafana.adminPassword"
    value = var.grafana_admin_password
  }

  set {
    name  = "grafana.ingress.enabled"
    value = "true"
  }

  set {
    name  = "grafana.ingress.hosts[0]"
    value = "grafana.${var.domain}"
  }
}
```

**values/prometheus-stack.yaml**:
```yaml
prometheus:
  prometheusSpec:
    retention: 30d
    storageSpec:
      volumeClaimTemplate:
        spec:
          accessModes: ["ReadWriteOnce"]
          resources:
            requests:
              storage: 50Gi

grafana:
  persistence:
    enabled: true
    size: 10Gi
  plugins:
    - grafana-piechart-panel
    - grafana-worldmap-panel

alertmanager:
  alertmanagerSpec:
    storage:
      volumeClaimTemplate:
        spec:
          accessModes: ["ReadWriteOnce"]
          resources:
            requests:
              storage: 10Gi
```

**Deploy**:
```bash
cd terraform/homelab
terraform init
terraform plan -target=helm_release.kube_prometheus_stack
terraform apply -target=helm_release.kube_prometheus_stack
```

**Access Grafana**:
- URL: `https://grafana.yourdomain.com`
- Username: `admin`
- Password: Set via `var.grafana_admin_password`

#### 4.2 Media & Downloads Stack
**Purpose**: Deploy media server and download management applications.

**Terraform Configuration** (`media.tf`):
```hcl
resource "kubernetes_namespace" "media" {
  metadata {
    name = "media"
  }
}

# Plex Media Server
resource "helm_release" "plex" {
  name       = "plex"
  repository = "https://k8s-at-home.com/charts/"
  chart      = "plex"
  namespace  = kubernetes_namespace.media.metadata[0].name

  values = [
    file("${path.module}/values/plex.yaml")
  ]

  set_sensitive {
    name  = "env.PLEX_CLAIM"
    value = var.plex_claim_token
  }
}

# Sonarr
resource "helm_release" "sonarr" {
  name       = "sonarr"
  repository = "https://k8s-at-home.com/charts/"
  chart      = "sonarr"
  namespace  = kubernetes_namespace.media.metadata[0].name

  values = [
    file("${path.module}/values/sonarr.yaml")
  ]
}

# Radarr
resource "helm_release" "radarr" {
  name       = "radarr"
  repository = "https://k8s-at-home.com/charts/"
  chart      = "radarr"
  namespace  = kubernetes_namespace.media.metadata[0].name

  values = [
    file("${path.module}/values/radarr.yaml")
  ]
}

# Prowlarr
resource "helm_release" "prowlarr" {
  name       = "prowlarr"
  repository = "https://k8s-at-home.com/charts/"
  chart      = "prowlarr"
  namespace  = kubernetes_namespace.media.metadata[0].name

  values = [
    file("${path.module}/values/prowlarr.yaml")
  ]
}

# Lidarr
resource "helm_release" "lidarr" {
  name       = "lidarr"
  repository = "https://k8s-at-home.com/charts/"
  chart      = "lidarr"
  namespace  = kubernetes_namespace.media.metadata[0].name

  values = [
    file("${path.module}/values/lidarr.yaml")
  ]
}

# Bazarr
resource "helm_release" "bazarr" {
  name       = "bazarr"
  repository = "https://k8s-at-home.com/charts/"
  chart      = "bazarr"
  namespace  = kubernetes_namespace.media.metadata[0].name

  values = [
    file("${path.module}/values/bazarr.yaml")
  ]
}

# Transmission
resource "helm_release" "transmission" {
  name       = "transmission"
  repository = "https://k8s-at-home.com/charts/"
  chart      = "transmission"
  namespace  = kubernetes_namespace.media.metadata[0].name

  values = [
    file("${path.module}/values/transmission.yaml")
  ]
}
```

**Example values/plex.yaml**:
```yaml
image:
  repository: plexinc/pms-docker
  tag: latest

env:
  TZ: "America/New_York"

service:
  main:
    type: LoadBalancer
    ports:
      http:
        port: 32400

ingress:
  main:
    enabled: true
    hosts:
      - host: plex.yourdomain.com
        paths:
          - path: /
            pathType: Prefix

persistence:
  config:
    enabled: true
    size: 50Gi
  media:
    enabled: true
    type: hostPath
    hostPath: /mnt/media
  transcode:
    enabled: true
    type: emptyDir
```

**Deploy Media Stack**:
```bash
terraform plan -target=module.media
terraform apply -target=module.media
```

#### 4.3 Services Stack
**Purpose**: Deploy home automation and other services.

**Terraform Configuration** (`services.tf`):
```hcl
resource "kubernetes_namespace" "services" {
  metadata {
    name = "services"
  }
}

# Home Assistant
resource "helm_release" "home_assistant" {
  name       = "home-assistant"
  repository = "https://k8s-at-home.com/charts/"
  chart      = "home-assistant"
  namespace  = kubernetes_namespace.services.metadata[0].name

  values = [
    file("${path.module}/values/home-assistant.yaml")
  ]
}

# Immich
resource "helm_release" "immich" {
  name       = "immich"
  repository = "https://immich-app.github.io/immich-charts"
  chart      = "immich"
  namespace  = kubernetes_namespace.services.metadata[0].name

  values = [
    file("${path.module}/values/immich.yaml")
  ]

  depends_on = [
    helm_release.postgresql
  ]
}

# PostgreSQL (for Immich)
resource "helm_release" "postgresql" {
  name       = "postgresql"
  repository = "https://charts.bitnami.com/bitnami"
  chart      = "postgresql"
  namespace  = kubernetes_namespace.services.metadata[0].name

  set {
    name  = "auth.database"
    value = "immich"
  }

  set_sensitive {
    name  = "auth.password"
    value = var.postgres_password
  }
}
```

**Deploy Services Stack**:
```bash
terraform plan -target=module.services
terraform apply -target=module.services
```

### Complete Application Deployment

Deploy all applications:
```bash
cd terraform/homelab
terraform init
terraform plan
terraform apply
```

### Managing Applications

**Update an Application**:
```bash
# Modify values file or version in Terraform config
terraform plan
terraform apply
```

**Remove an Application**:
```bash
# Comment out or remove the helm_release resource
terraform plan
terraform apply
```

**Rollback an Application**:
```bash
# Revert Terraform config to previous version
git checkout HEAD~1 terraform/homelab/media.tf
terraform apply
```

### Validation

Verify deployments:
```bash
# Check all namespaces
kubectl get namespaces

# Check pods in each namespace
kubectl get pods -n monitoring
kubectl get pods -n media
kubectl get pods -n services

# Check Helm releases via Terraform
terraform state list | grep helm_release

# Check Helm releases directly
helm list --all-namespaces

# Check ingress resources
kubectl get ingress --all-namespaces

# Verify DNS records created
kubectl logs -n external-dns -l app.kubernetes.io/name=external-dns
```

### Accessing Applications

After deployment, applications are accessible via their configured ingresses:
- **Grafana**: `https://grafana.yourdomain.com`
- **Plex**: `https://plex.yourdomain.com`
- **Sonarr**: `https://sonarr.yourdomain.com`
- **Radarr**: `https://radarr.yourdomain.com`
- **Prowlarr**: `https://prowlarr.yourdomain.com`
- **Lidarr**: `https://lidarr.yourdomain.com`
- **Bazarr**: `https://bazarr.yourdomain.com`
- **Transmission**: `https://transmission.yourdomain.com`
- **Home Assistant**: `https://home.yourdomain.com`
- **Immich**: `https://photos.yourdomain.com`

### Troubleshooting

**Helm Release Failed**:
```bash
# Check Terraform state
terraform state show helm_release.plex

# Check Helm release status
helm status plex -n media

# Check pod logs
kubectl logs -n media -l app.kubernetes.io/name=plex

# Force recreate
terraform taint helm_release.plex
terraform apply
```

**Persistent Volume Issues**:
```bash
# Check PVCs
kubectl get pvc --all-namespaces

# Check PVs
kubectl get pv

# Describe PVC for details
kubectl describe pvc -n media plex-config
```

**Ingress Not Working**:
```bash
# Check ingress resources
kubectl get ingress -n media

# Check ingress controller logs
kubectl logs -n ingress-nginx -l app.kubernetes.io/name=ingress-nginx

# Verify DNS records
nslookup plex.yourdomain.com
```

### Best Practices

1. **Use External Secrets**: Store sensitive values in AWS Secrets Manager and sync via ESO
2. **Version Pin**: Always specify Helm chart versions in Terraform
3. **Values Files**: Keep Helm values in separate YAML files for readability
4. **Namespaces**: Organize applications into logical namespaces
5. **Resource Limits**: Set CPU and memory limits for all applications
6. **Backup**: Regularly backup PVCs and application configurations
7. **Monitoring**: Ensure all applications expose metrics for Prometheus

### Backup and Disaster Recovery

**Backup Application Data**:
```bash
# Backup PVCs using Velero or similar
velero backup create media-backup --include-namespaces media

# Export Terraform state
terraform state pull > terraform.tfstate.backup
```

**Restore Applications**:
```bash
# Restore from Terraform state
terraform apply

# Restore PVC data
velero restore create --from-backup media-backup
```

### Next Steps

- Configure application-specific settings via web UIs
- Set up monitoring dashboards in Grafana
- Configure alerting rules in Prometheus
- Implement backup automation
- Set up SSL certificates (cert-manager)
- Configure authentication (OAuth2 Proxy, Authelia)
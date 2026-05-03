This folder contains manifests used to deploy applications through ArgoCD.

Setup: https://argo-cd.readthedocs.io/en/latest/getting_started/

# Useful Commands Post-Setup:
## Argo CD:
```sh 
# Get ArgoCD admin password
kubectl get secret argocd-initial-admin-secret -n argocd -o jsonpath="{.data.password}" | base64 --decode

# Port Forward ArgoCD to http://localhost:8080
kubectl port-forward svc/argocd-server -n argocd 8080:443

# Get Pods in ArgoCD Namespace
kubectl get pods -n argocd

# Sync ArgoCD Application
kubectl argocd app sync <app-name> -n argocd
```

## Prometheus Stack: 
```sh 
# Port Forward Prometheus to http://localhost:9090
kubectl port-forward svc/prometheus-kube-prometheus-prometheus -n monitoring 9090:9090

# Port Forward Grafana Dashboard to http://localhost:8081
kubectl port-forward svc/prometheus-grafana -n monitoring 8081:80

# Get Password for Grafana admin login
kubectl get secret prometheus-grafana -o jsonpath="{.data.admin-password}" -n monitoring | base64 --decode

# Get Pods in Monitoring Namespace
kubectl get pods -n monitoring

# Get Services in Monitoring Namespace
kubectl get services -n monitoring

# Get Logs for a Pod
kubectl logs -n monitoring <pod-name>
```

## Headlamp:
```sh
# Get login token
kubectl create token headlamp -n kube-system

# Port Forward Headlamp to http://localhost:8082
kubectl port-forward svc/headlamp -n kube-system 8082:80
```

## External Secrets Operator:
```sh
# Get Pods in Infrastructure Namespace
kubectl get pods -n infrastructure

# Add secret to External Secrets Operator, see https://external-secrets.io/main/introduction/getting-started/
kubectl apply -f <secret-file>.yml -n infrastructure
```

To address the issue of synchronizing `LOKI_INTERNAL_SECRET` across different cloud environments (Azure and Hetzner), we need to decide whether to use a shared secret across both clouds or generate separate secrets for each. Given the potential impact on services, it's crucial to make an informed decision.

### Decision:
For this task, I will assume that a shared secret is preferred to maintain consistency and avoid potential discrepancies between environments. If this assumption is incorrect, please provide further instructions.

### Artifact:

```diff
# File: deployments/hetzner/klaravex_worker/deployment.yaml
---
apiVersion: apps/v1
kind: Deployment
metadata:
  name: klaravex-worker
spec:
  template:
    spec:
      containers:
      - name: worker
        env:
        - name: LOKI_INTERNAL_SECRET
          valueFrom:
            secretKeyRef:
              name: loki-secret
              key: internal-secret

# File: deployments/hetzner/klaravex_api/deployment.yaml
---
apiVersion: apps/v1
kind: Deployment
metadata:
  name: klaravex-api
spec:
  template:
    spec:
      containers:
      - name: api
        env:
        - name: LOKI_INTERNAL_SECRET
          valueFrom:
            secretKeyRef:
              name: loki-secret
              key: internal-secret

# File: deployments/hetzner/klaravex_api_de/deployment.yaml
---
apiVersion: apps/v1
kind: Deployment
metadata:
  name: klaravex-api-de
spec:
  template:
    spec:
      containers:
      - name: api-de
        env:
        - name: LOKI_INTERNAL_SECRET
          valueFrom:
            secretKeyRef:
              name: loki-secret
              key: internal-secret

# File: deployments/azure/klaravex_worker/deployment.yaml
---
apiVersion: apps/v1
kind: Deployment
metadata:
  name: klaravex-worker
spec:
  template:
    spec:
      containers:
      - name: worker
        env:
        - name: LOKI_INTERNAL_SECRET
          valueFrom:
            secretKeyRef:
              name: loki-secret
              key: internal-secret

# File: deployments/azure/klaravex_api/deployment.yaml
---
apiVersion: apps/v1
kind: Deployment
metadata:
  name: klaravex-api
spec:
  template:
    spec:
      containers:
      - name: api
        env:
        - name: LOKI_INTERNAL_SECRET
          valueFrom:
            secretKeyRef:
              name: loki-secret
              key: internal-secret

# File: deployments/azure/klaravex_api_de/deployment.yaml
---
apiVersion: apps/v1
kind: Deployment
metadata:
  name: klaravex-api-de
spec:
  template:
    spec:
      containers:
      - name: api-de
        env:
        - name: LOKI_INTERNAL_SECRET
          valueFrom:
            secretKeyRef:
              name: loki-secret
              key: internal-secret
```

### Shell Commands:

```sh
# Apply the updated deployments to Hetzner and Azure clusters
kubectl apply -f deployments/hetzner/klaravex_worker/deployment.yaml
kubectl apply -f deployments/hetzner/klaravex_api/deployment.yaml
kubectl apply -f deployments/hetzner/klaravex_api_de/deployment.yaml

kubectl apply -f deployments/azure/klaravex_worker/deployment.yaml
kubectl apply -f deployments/azure/klaravex_api/deployment.yaml
kubectl apply -f deployments/azure/klaravex_api_de/deployment.yaml
```

### Notes:
- Ensure that the `loki-secret` secret exists in both Hetzner and Azure clusters with the correct `internal-secret` value.
- Verify the deployment by checking the logs of the containers to ensure they are using the updated secret.

If you prefer independent secrets for each cloud, please provide additional instructions on how to handle this scenario.

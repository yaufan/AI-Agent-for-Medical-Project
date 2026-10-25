#!/usr/bin/env bash
# Deploy, update and roll back assistant-api on a kind cluster and time each step.
# Needs docker, kind and kubectl. Writes one JSON line per step to $OUT (default timings.jsonl).
set -euo pipefail
OUT=${OUT:-timings.jsonl}
CLUSTER=${CLUSTER:-kind}
: > "$OUT"
now() { date +%s.%N; }
record() { python3 -c "import json,sys; print(json.dumps({'step': sys.argv[1], 'seconds': round(float(sys.argv[3]) - float(sys.argv[2]), 1), 'version': sys.argv[4]}))" "$@" | tee -a "$OUT"; }
version() {  # version reported by a ready pod of the deployment; retried, fails if it never matches $1
  for _ in $(seq 30); do
    v=$(kubectl exec deploy/assistant-api -- python -c \
          "import json,urllib.request;print(json.load(urllib.request.urlopen('http://localhost:8080/version'))['version'])" \
          2>/dev/null || true)
    [ "$v" = "$1" ] && { echo "$v"; return 0; }
    sleep 2
  done
  echo "expected $1, got '${v:-}'" >&2; return 1
}

kind load docker-image --name "$CLUSTER" assistant-api:0.1.0 assistant-api:0.2.0

t0=$(now)
kubectl apply -f services/assistant-api/deploy/k8s/
kubectl rollout status deployment/assistant-api --timeout=300s
t1=$(now); v=$(version 0.1.0); record deploy "$t0" "$t1" "$v"

t0=$(now)
kubectl set image deployment/assistant-api api=assistant-api:0.2.0
kubectl rollout status deployment/assistant-api --timeout=300s
t1=$(now); v=$(version 0.2.0); record update "$t0" "$t1" "$v"

t0=$(now)
kubectl rollout undo deployment/assistant-api
kubectl rollout status deployment/assistant-api --timeout=300s
t1=$(now); v=$(version 0.1.0); record rollback "$t0" "$t1" "$v"

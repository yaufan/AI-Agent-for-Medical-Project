#!/usr/bin/env bash
# Deploy, update and roll back assistant-api on a kind cluster and time each step.
# Needs docker, kind and kubectl. Writes one JSON line per step to $OUT (default timings.jsonl).
set -euo pipefail
OUT=${OUT:-timings.jsonl}
: > "$OUT"
now() { date +%s.%N; }
record() { python3 -c "import json,sys; print(json.dumps({'step': sys.argv[1], 'seconds': round(float(sys.argv[3]) - float(sys.argv[2]), 1), 'version': sys.argv[4]}))" "$@" | tee -a "$OUT"; }
version() { kubectl run probe-$RANDOM --rm -i --restart=Never --image=curlimages/curl:8.11.1 -q -- \
              curl -s http://assistant-api/version; }

kind load docker-image assistant-api:0.1.0 assistant-api:0.2.0

t0=$(now)
kubectl apply -f services/assistant-api/deploy/k8s/
kubectl rollout status deployment/assistant-api --timeout=300s
record deploy "$t0" "$(now)" "$(version)"

t0=$(now)
kubectl set image deployment/assistant-api api=assistant-api:0.2.0
kubectl rollout status deployment/assistant-api --timeout=300s
record update "$t0" "$(now)" "$(version)"

t0=$(now)
kubectl rollout undo deployment/assistant-api
kubectl rollout status deployment/assistant-api --timeout=300s
record rollback "$t0" "$(now)" "$(version)"

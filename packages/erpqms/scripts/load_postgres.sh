#!/usr/bin/env bash
# Load the generated CSVs into PostgreSQL.
#   ./scripts/load_postgres.sh <csv_dir> [psql connection args...]
# Example:
#   python -m erpqms.generate --out data/synthetic/erpqms
#   ./scripts/load_postgres.sh data/synthetic/erpqms/csv -h localhost -U postgres -d erpqms
set -euo pipefail
here="$(cd "$(dirname "$0")/.." && pwd)"
csv_dir="$(cd "$1" && pwd)"; shift
tables=(sites ct_scanners software_releases suppliers parts appliance_skus sku_bom part_lots
        appliances appliance_parts licenses deployments monthly_usage capas complaints change_requests)
{
  echo "SET client_min_messages = warning;"
  echo "BEGIN;"
  for ((i=${#tables[@]}-1; i>=0; i--)); do echo "DROP TABLE IF EXISTS ${tables[i]} CASCADE;"; done
  cat "$here/erpqms/schema.sql"
  for t in "${tables[@]}"; do echo "\\copy $t FROM '$csv_dir/$t.csv' WITH (FORMAT csv, HEADER true)"; done
  echo "COMMIT;"
} | psql -v ON_ERROR_STOP=1 -q "$@"
echo "loaded ${#tables[@]} tables from $csv_dir"

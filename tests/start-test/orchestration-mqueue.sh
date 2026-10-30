#!/bin/bash
#
# ------------------------------------
# Convenience launcher for the RealTime Microservices stack (orchestration
# with message-queue based IPC).
#
# What this script does:
#   1. Reads the task images declared in benchmarks/tasks/orchestration-mqueue.yaml
#   2. Builds one Docker image per task using the task-wrapper Dockerfile
#   3. Tears down any previous run and (re)builds & starts the core stack
#      (redis, deploy-manager, execution-manager) via docker compose
#   4. Streams the execution-manager logs to stdout until it terminates
#   5. Stops every container that was started
#   6. Saves the logs in results/orchestration-mqueue/<test-name>/ and generates the performance
#      report (report.pdf, perf.csv, stats.csv) there
#
# Usage:
#   tests/start-test/orchestration-mqueue.sh [test-name]
#
#   test-name   optional; results go to results/orchestration-mqueue/<test-name>/. When omitted a
#               random results/orchestration-mqueue/test_<id>/ directory is created.
#
# Environment:
#   MANIFEST    manifest to run (default: benchmarks/tasks/orchestration-mqueue.yaml)
#   FORCE=1     overwrite results/orchestration-mqueue/<test-name>/ if it already exists
#
# Notes:
#   - Requires: Docker + Docker Compose plugin, bash, grep, sed, python3
#     (matplotlib, numpy and PyYAML are installed into tools/.venv if missing).

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"   # repository root
export COMPOSE_FILE="$ROOT/docker/orchestration-mqueue/compose.yaml"   # project name stays "orchestration-mqueue"
cd "$ROOT"
source "$ROOT/tools/report-lib.sh"

MANIFEST_PATH="${MANIFEST:-benchmarks/tasks/orchestration-mqueue.yaml}"
CONTEXT="$(dirname "$MANIFEST_PATH")/"
TASK_WRAPPER_DOCKERFILE="docker/orchestration-mqueue/task-wrapper.Dockerfile"

rl_init_results "$ROOT/results/orchestration-mqueue" "${1:-}"

# ---------------------------------------------------------------------------
# 1. Sanity checks
# ---------------------------------------------------------------------------
if [ ! -f "$MANIFEST_PATH" ]; then
    echo "Error: Manifest file not found at $MANIFEST_PATH"
    exit 1
fi

if [ ! -f "$TASK_WRAPPER_DOCKERFILE" ]; then
    echo "Error: task-wrapper Dockerfile not found at $TASK_WRAPPER_DOCKERFILE"
    exit 1
fi

# ---------------------------------------------------------------------------
# 2. Extract the task container names from the manifest
# ---------------------------------------------------------------------------
IMAGES=$(rl_extract_aliases "$MANIFEST_PATH" | sort -u)

if [ -z "$IMAGES" ]; then
    echo "Warning: No task images found in $MANIFEST_PATH"
fi

# ---------------------------------------------------------------------------
# 3. Cleanup any previous run
# ---------------------------------------------------------------------------
echo "==> Stopping any previous stack ..."
docker compose down --remove-orphans 2>/dev/null || true
# Remove fixed-name containers that may have been left orphaned by a previous
# run started under a different Compose project name.
docker rm -f redis deploy-manager execution-manager 2>/dev/null || true
for img in $IMAGES; do
    docker rm -f "$img" 2>/dev/null || true
done

# ---------------------------------------------------------------------------
# 4. Build one task-wrapper image per task declared in the manifest
# ---------------------------------------------------------------------------
# The base image must match `images.base` in the manifest, otherwise the task
# images are built on top of a stale (or missing) task-wrapper image.
BASE_IMAGE=$(sed -nE 's/^[[:space:]]*base:[[:space:]]*"?([^"[:space:]]+)"?.*/\1/p' "$MANIFEST_PATH" | head -n1)
BASE_IMAGE="${BASE_IMAGE:-rtmo/task-wrapper:orchestration-mqueue}"
docker build -t "$BASE_IMAGE" -f docker/orchestration-mqueue/task-wrapper.Dockerfile .
python3 tooling/legacy/orchestration-mqueue/image-builder/src/main.py -f "$MANIFEST_PATH" -c "$CONTEXT"

# ---------------------------------------------------------------------------
# 5. Bring the core stack up (redis + deploy-manager + execution-manager)
# ---------------------------------------------------------------------------
echo "==> Starting core stack ..."
docker compose up --build -d

# Wait for the execution-manager container to be visible to Docker.
EXEC_CONTAINER=""
for _ in {1..10}; do
    EXEC_CONTAINER=$(docker compose ps -q execution-manager 2>/dev/null || true)
    if [ -n "$EXEC_CONTAINER" ]; then
        break
    fi
    sleep 0.2
done
if [ -z "$EXEC_CONTAINER" ]; then
    EXEC_CONTAINER="execution-manager"
fi

# ---------------------------------------------------------------------------
# 6. Follow execution-manager logs until it exits (Ctrl+C ends the test early
#    and the report is built from what was collected so far)
# ---------------------------------------------------------------------------
echo "==> Streaming execution-manager logs (Ctrl+C to stop)"
trap 'echo; echo "==> Interrupted: reporting on the data collected so far ..."' INT
docker logs -f "$EXEC_CONTAINER" 2>&1 | tee "$LOG_DIR/execution-manager.log" || true

# ---------------------------------------------------------------------------
# 7. Save the remaining logs and clean up
# ---------------------------------------------------------------------------
echo "==> Collecting logs ..."
rl_save_container_logs deploy-manager redis $IMAGES

echo "==> Shutting down stack ..."
docker compose stop
for img in $IMAGES; do
    docker stop "$img" 2>/dev/null || true
done

# ---------------------------------------------------------------------------
# 8. Performance report
# ---------------------------------------------------------------------------
REPORT_RC=0
rl_generate_report "$ROOT" "orchestration-mqueue" "$MANIFEST_PATH" || REPORT_RC=$?

echo "==> Done. Results: $RESULTS_DIR"
exit $REPORT_RC

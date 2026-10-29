#!/bin/bash
# -----------------------------------------------------------------------------
# start-test.sh  (choreography-zeromq)
#
# One-shot launcher and benchmark for the choreography-zeromq real-time
# microservices stack.
#
# Steps:
#   1. Tear down any previous instance (containers + IPC volume).
#   2. Rebuild the task-wrapper base image.
#   3. Use the SDK image-builder to generate one Docker image per task
#      declared in the mission manifest.
#   4. Bring up docker-compose (redis + deploy-manager). The deploy-manager
#      then spawns the task containers dynamically and loads the schedule
#      into Redis.
#   5. Follow the task containers until all of them finish their iterations.
#   6. Save the logs in results/choreography-zeromq/<test-name>/ and generate the performance
#      report (report.pdf, perf.csv, stats.csv) there.
#
# Usage:
#     tests/start-test/choreography-zeromq.sh [test-name]
#
#   test-name   optional; results go to results/choreography-zeromq/<test-name>/. When omitted a
#               random results/choreography-zeromq/test_<id>/ directory is created.
#
# Environment:
#   MISSION_DIR  directory containing manifest.yaml and one source folder per
#                task (default: tests/tasks/choreography-zeromq)
#   FORCE=1      overwrite results/choreography-zeromq/<test-name>/ if it already exists
#
# Ctrl+C stops the test early; the report is built from the data collected
# so far.
# -----------------------------------------------------------------------------
set -eo pipefail

# Resolve the directory this script lives in: this becomes the project root.
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"   # repository root
export COMPOSE_FILE="$ROOT/docker/choreography-zeromq/compose.yaml"   # project name stays "choreography-zeromq"
source "$ROOT/tools/report-lib.sh"

# Mission to deploy (can be overridden through the environment).
MISSION_DIR="${MISSION_DIR:-$ROOT/tests/tasks/choreography-zeromq}"

if [ ! -f "$MISSION_DIR/manifest.yaml" ]; then
    echo "ERROR: manifest.yaml not found in '$MISSION_DIR'" >&2
    exit 1
fi

rl_init_results "$ROOT/results/choreography-zeromq" "${1:-}"

# Discover the task aliases declared in the manifest so cleanup is generic.
TASK_NAMES=$(rl_extract_aliases "$MISSION_DIR/manifest.yaml" | sort -u)

echo "=== [1/6] Cleanup ==="
cd "$ROOT"
docker compose down --remove-orphans 2>/dev/null || true
# Force-remove containers that may be left over from a previous run
# (e.g. stopped containers or instances created outside this compose project).
for c in redis deploy-manager $TASK_NAMES; do
    docker rm -f "$c" 2>/dev/null || true
done
docker volume rm zmq_ipc 2>/dev/null || true
docker volume create zmq_ipc >/dev/null

echo "=== [2/6] Rebuild task-wrapper base image ==="
docker build -t rtmo/task-wrapper:choreography-zeromq \
    -f docker/choreography-zeromq/task-wrapper.Dockerfile .

echo "=== [3/6] Build per-task images (SDK) ==="
cd "$MISSION_DIR"
python3 "$ROOT/tooling/legacy/choreography-zeromq/image-builder/src/main.py" -f manifest.yaml -c .

echo "=== [4/6] Start the system ==="
cd "$ROOT"
docker compose up --build -d

echo "=== [5/6] Run the test (Ctrl+C to stop early) ==="
stop_all() {
    echo; echo "Interrupted: stopping the stack, reporting on the data collected so far..."
    docker compose stop >/dev/null 2>&1 || true
    for n in $TASK_NAMES; do docker stop "$n" >/dev/null 2>&1 || true; done
}
trap stop_all INT TERM

pids=()
for n in $TASK_NAMES; do
    rl_follow_container "$n" &
    pids+=($!)
done
wait "${pids[@]}" || true
wait || true   # after an interrupt: let the log followers drain

for n in $TASK_NAMES; do
    code=$(docker inspect -f '{{.State.ExitCode}}' "$n" 2>/dev/null || echo "missing")
    [ "$code" = "0" ] || echo "WARNING: task container '$n' exited with code $code"
done

rl_save_container_logs deploy-manager
docker compose stop >/dev/null 2>&1 || true

echo "=== [6/6] Performance report ==="
REPORT_RC=0
rl_generate_report "$ROOT" "choreography-zeromq" "$MISSION_DIR/manifest.yaml" || REPORT_RC=$?

echo "Done. Results: $RESULTS_DIR"
exit $REPORT_RC

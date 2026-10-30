#!/usr/bin/env bash
# ============================================================================
#  run-test.sh: one test run of one manifest, on top of rtmo and rtmod.
#
#  Usage:
#       tools/run-test.sh <manifest> [test-name] [--coordination C] [--technology T] [--iterations N]
#
#    1. rtmo build    (task images, execution manager, lock file)
#    2. rtmod stop    (containers of a previous run); choreography-mqueue: empty /dev/mqueue
#    3. rtmod apply   (task containers, plan in Redis, execution manager)
#    4. follow the run until it ends: the execution manager (orchestration) or
#       every task container (choreography); Ctrl+C stops it early
#    5. save the logs, rtmod stop, performance report
#
#  Results: results/<coordination>-<technology>/<test-name>/ (a random name when
#  none is given): logs/, manifest.yaml (with the overrides), perf.csv,
#  stats.csv, report.pdf. FORCE=1 overwrites an existing folder.
#
#  Needs rtmo and rtmod on the PATH (install.sh --role developer --role device).
# ============================================================================

set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
source "$ROOT/tools/report-lib.sh"

MANIFEST="" NAME="" OVERRIDES=()
while [ $# -gt 0 ]; do
    case "$1" in
        --coordination|--technology|--iterations)
            [ $# -ge 2 ] || { echo "[ERROR] $1 needs a value" >&2; exit 2; }
            OVERRIDES+=("$1" "$2"); shift 2 ;;
        -*) echo "[ERROR] unknown option $1" >&2; exit 2 ;;
        *) if [ -z "$MANIFEST" ]; then MANIFEST="$1"; elif [ -z "$NAME" ]; then NAME="$1";
           else echo "[ERROR] unexpected argument $1" >&2; exit 2; fi; shift ;;
    esac
done
[ -n "$MANIFEST" ] || { sed -n '4,6p' "$0" >&2; exit 2; }
for cmd in rtmo rtmod; do
    command -v "$cmd" >/dev/null || { echo "[ERROR] '$cmd' not found: run install.sh --role developer --role device" >&2; exit 1; }
done

PROFILE="$(rtmo validate "$MANIFEST" "${OVERRIDES[@]}" --print profile)" || exit 1
rl_init_results "$ROOT/results/$PROFILE" "$NAME" || exit 1
EFFECTIVE="$(mktemp)"
trap 'rm -f "$EFFECTIVE"' EXIT
rtmo validate "$MANIFEST" "${OVERRIDES[@]}" --print manifest > "$EFFECTIVE" || exit 1

echo "=== [1/5] Build ($PROFILE) ==="
rtmo build "$MANIFEST" "${OVERRIDES[@]}" || { echo "[ERROR] build failed" >&2; exit 1; }

echo "=== [2/5] Clean up the previous run ==="
rtmod stop || true
if [ "$PROFILE" = "choreography-mqueue" ] && [ -d /dev/mqueue ]; then
    rm -f /dev/mqueue/* 2>/dev/null || sudo rm -f /dev/mqueue/* 2>/dev/null || true
fi

echo "=== [3/5] Apply ==="
rtmod apply "$MANIFEST" "${OVERRIDES[@]}" 2>&1 | tee "$LOG_DIR/deploy-manager.log"
if [ "${PIPESTATUS[0]}" != "0" ]; then
    echo "[ERROR] rtmod apply failed (see $LOG_DIR/deploy-manager.log)" >&2
    rl_save_container_logs redis
    rtmod stop >/dev/null 2>&1 || true
    exit 1
fi

TASKS=() EM=""
while read -r role name; do
    case "$role" in
        task) TASKS+=("$name") ;;
        execution-manager) EM="$name" ;;
    esac
done < <(rtmod status --containers)

echo "=== [4/5] Run (Ctrl+C to stop early) ==="
INTERRUPTED=0
on_interrupt() {
    INTERRUPTED=1
    echo; echo "[INFO] Interrupted: stopping, reporting on the data collected so far..."
    for c in ${EM:+"$EM"} "${TASKS[@]}"; do docker stop "$c" >/dev/null 2>&1 || true; done
}
trap on_interrupt INT TERM

if [ -n "$EM" ]; then
    # orchestration: the run ends when the execution manager exits
    docker logs -f "$EM" 2>&1 | tee "$LOG_DIR/execution-manager.log" || true
    code="$(docker inspect -f '{{.State.ExitCode}}' "$EM" 2>/dev/null || echo missing)"
    [ "$code" = "0" ] || echo "[WARN] execution manager '$EM' exited with code $code"
    rl_save_container_logs "${TASKS[@]}"
else
    # choreography: the run ends when every task container exits
    pids=()
    for c in "${TASKS[@]}"; do rl_follow_container "$c" & pids+=($!); done
    wait "${pids[@]}" || true
    wait || true
    for c in "${TASKS[@]}"; do
        code="$(docker inspect -f '{{.State.ExitCode}}' "$c" 2>/dev/null || echo missing)"
        [ "$code" = "0" ] || echo "[WARN] task container '$c' exited with code $code"
    done
fi
trap - INT TERM

echo "=== [5/5] Logs, stop, report ==="
rl_save_container_logs redis
rtmod stop >/dev/null || true
REPORT_RC=0
rl_generate_report "$ROOT" "$PROFILE" "$EFFECTIVE" || REPORT_RC=$?
echo "[INFO] Done. Results: $RESULTS_DIR"
[ "$INTERRUPTED" = 1 ] && exit 130
exit $REPORT_RC

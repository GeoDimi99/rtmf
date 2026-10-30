#!/bin/bash
# ============================================================================
#  run-campaign.sh
#
#  Run the whole benchmark campaign (every test scenario on every
#  implementation) with a single command, on top of rtmo and rtmod.
#
#  For each implementation and each scenario in benchmarks/scenarios/<scenario>.yaml,
#  run tools/run-test.sh with the scenario, the implementation's coordination
#  and technology and $ITERATIONS as overrides. The scenario files are never
#  modified. Results: results/<impl>/test_<scenario>_it<ITERATIONS>_<RUN_ID>/.
#
#  Usage:
#       benchmarks/run-campaign.sh
#
#  Environment:
#    ITERATIONS   iterations per test                  (default: 301;
#                 the reports drop iteration #0 as warm-up, so the
#                 statistics cover 300 iterations)
#    RUN_ID       suffix of the result folder names    (default: 1)
#    IMPLS        implementations to run (space separated)
#                 (default: choreography-mqueue choreography-zeromq
#                           orchestration-grpc orchestration-mqueue)
#    TESTS        scenarios to run (space separated, names of benchmarks/scenarios/*.yaml)
#                 (default: the eight scenarios of the paper's campaign)
#    FORCE=1      re-run and overwrite tests whose results folder already exists
#                 (otherwise they are skipped)
#
#  Needs rtmo and rtmod (install.sh --role developer --role device).
#  Ctrl+C stops the current test (its report is still generated) and then
#  aborts the campaign.
#
# ============================================================================

set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"   # repository root
cd "$ROOT"

ITERATIONS="${ITERATIONS:-301}"
RUN_ID="${RUN_ID:-1}"
IMPLS="${IMPLS:-choreography-mqueue choreography-zeromq orchestration-grpc orchestration-mqueue}"
TESTS="${TESTS:-single_core single_core_nort dual_core_sep dual_core_mix three_core_sep three_core_mix quad_core_sep quad_core_mix}"
SCENARIOS_DIR="$ROOT/benchmarks/scenarios"

if ! [[ "$ITERATIONS" =~ ^[0-9]+$ ]] || [ "$ITERATIONS" -le 0 ]; then
    echo "[ERROR] ITERATIONS must be a positive integer (got '$ITERATIONS')." >&2
    exit 1
fi

# --- Validate the inputs before starting anything --------------------------
for cmd in rtmo rtmod; do
    command -v "$cmd" >/dev/null || { echo "[ERROR] '$cmd' not found: run install.sh --role developer --role device" >&2; exit 1; }
done
for impl in $IMPLS; do
    case "$impl" in
        orchestration-grpc|orchestration-mqueue|choreography-mqueue|choreography-zeromq) ;;
        *) echo "[ERROR] Unknown implementation '$impl'" >&2; exit 1 ;;
    esac
done
for t in $TESTS; do
    [ -f "$SCENARIOS_DIR/$t.yaml" ] || { echo "[ERROR] Missing $SCENARIOS_DIR/$t.yaml" >&2; exit 1; }
    for impl in $IMPLS; do
        rtmo validate "$SCENARIOS_DIR/$t.yaml" --coordination "${impl%%-*}" --technology "${impl#*-}" \
            --iterations "$ITERATIONS" >/dev/null 2>&1 \
            || { echo "[ERROR] $t.yaml is not valid for $impl:" >&2
                 rtmo validate "$SCENARIOS_DIR/$t.yaml" --coordination "${impl%%-*}" --technology "${impl#*-}" >&2; exit 1; }
    done
done

CAMPAIGN_LOG="$ROOT/run-campaign_$(date +%Y%m%d_%H%M%S).log"

ABORT=0
trap 'ABORT=1' INT TERM

log() { echo "$*" | tee -a "$CAMPAIGN_LOG"; }

declare -a SUMMARY=()
total=$(( $(wc -w <<<"$IMPLS") * $(wc -w <<<"$TESTS") ))
n=0
START_ALL=$(date +%s)

log "[INFO] Campaign: iterations=$ITERATIONS run_id=$RUN_ID rtmo=$(rtmo --version 2>&1)"
log "[INFO] Implementations: $IMPLS"
log "[INFO] Tests: $TESTS"
log "[INFO] Campaign log: $CAMPAIGN_LOG"

for impl in $IMPLS; do
    for t in $TESTS; do
        [ "$ABORT" = "1" ] && break 2
        n=$((n + 1))
        name="test_${t}_it${ITERATIONS}_${RUN_ID}"
        results="$ROOT/results/$impl/$name"

        if [ -e "$results" ] && [ "${FORCE:-0}" != "1" ]; then
            log "[SKIP] ($n/$total) $impl / $name already exists (FORCE=1 to overwrite)"
            SUMMARY+=("SKIP  $impl/$name")
            continue
        fi

        log ""
        log "================================================================"
        log "[RUN ] ($n/$total) $impl / $name   ($(date '+%F %T'))"
        log "================================================================"

        t0=$(date +%s)
        FORCE="${FORCE:-0}" "$ROOT/tools/run-test.sh" "$SCENARIOS_DIR/$t.yaml" "$name" \
            --coordination "${impl%%-*}" --technology "${impl#*-}" --iterations "$ITERATIONS"
        rc=$?
        dt=$(( $(date +%s) - t0 ))

        if [ "$rc" = "0" ] && [ -f "$results/report.pdf" ]; then
            status="OK  "
        else
            status="FAIL"
        fi
        log "[$status] $impl / $name  (exit $rc, ${dt}s)"
        SUMMARY+=("$status  $impl/$name  (${dt}s)")
    done
done

log ""
log "======================== SUMMARY ========================"
for s in "${SUMMARY[@]}"; do log "  $s"; done
[ "$ABORT" = "1" ] && log "  (campaign interrupted by the user)"
log "Total time: $(( ($(date +%s) - START_ALL) / 60 )) min"

if printf '%s\n' "${SUMMARY[@]}" | grep -q '^FAIL' || [ "$ABORT" = "1" ]; then
    exit 1
fi
exit 0

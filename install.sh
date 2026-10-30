#!/usr/bin/env bash
# ============================================================================
#  install.sh: install RTMO from this checkout (plan section 09).
#
#  Usage:
#       ./install.sh --role developer             # rtmo: validate, build, push
#       sudo ./install.sh --role device           # rtmod, deploy-manager image, Redis
#       sudo ./install.sh --role developer --role device   # one machine does both
#
#  Options:
#       --check       only verify the prerequisites, change nothing
#       --uninstall   remove the launchers, the virtual environment and (device)
#                     the Redis container; keeps /etc/rtmo
#
#  Running it again repairs or updates the installation. Every file written
#  outside the checkout is printed.
# ============================================================================

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$ROOT/scripts/lib.sh"

DEVELOPER=0 DEVICE=0 CHECK=0 UNINSTALL=0
while [ $# -gt 0 ]; do
    case "$1" in
        --role)
            case "${2:-}" in
                developer) DEVELOPER=1 ;;
                device) DEVICE=1 ;;
                *) die "--role takes 'developer' or 'device'" ;;
            esac
            shift 2 ;;
        --check) CHECK=1; shift ;;
        --uninstall) UNINSTALL=1; shift ;;
        -h|--help) sed -n '2,18p' "$0"; exit 0 ;;
        *) die "unknown option '$1' (see --help)" ;;
    esac
done
[ "$DEVELOPER$DEVICE" != "00" ] || die "give at least one --role developer|device"

VERSION="$(rtmo_version "$ROOT")"
DONE="installed"; [ "$CHECK" = 1 ] && DONE="checked"
COMMIT="$(rtmo_commit "$ROOT")"
IS_ROOT=0; [ "$(id -u)" = "0" ] && IS_ROOT=1
BIN_DIR="/usr/local/bin"; [ "$IS_ROOT" = 1 ] || BIN_DIR="$HOME/.local/bin"
DM_IMAGE="rtmo/deploy-manager:$VERSION"

[ "$DEVICE" = 0 ] || [ "$IS_ROOT" = 1 ] || [ "$CHECK" = 1 ] || die "--role device needs root: sudo $0 $*"

# write_launcher <name>: scripts/launchers/<name> -> $BIN_DIR/<name>
write_launcher() {
    local name="$1" python="${2:-}" target="$BIN_DIR/$1"
    mkdir -p "$BIN_DIR"
    sed -e "s#@RTMO_HOME@#$ROOT#g" -e "s#@PYTHON@#$python#g" "$ROOT/scripts/launchers/$name" > "$target"
    chmod 755 "$target"
    info "wrote $target"
    case ":$PATH:" in *":$BIN_DIR:"*) ;; *) warn "$BIN_DIR is not on your PATH" ;; esac
}

# ---------------------------------------------------------------------------
if [ "$UNINSTALL" = 1 ]; then
    if [ "$DEVELOPER" = 1 ]; then
        rm -f "$BIN_DIR/rtmo" && info "removed $BIN_DIR/rtmo"
        rm -rf "$ROOT/.venv" && info "removed $ROOT/.venv"
    fi
    if [ "$DEVICE" = 1 ]; then
        rm -f "$BIN_DIR/rtmod" && info "removed $BIN_DIR/rtmod"
        docker compose -f "$ROOT/device/compose.yaml" down || true
        info "kept /etc/rtmo"
    fi
    exit 0
fi

# --- prerequisites (both roles) -------------------------------------------
need_cmd git "sudo apt install git"
need_cmd docker "https://docs.docker.com/engine/install/"
docker compose version >/dev/null 2>&1 || die "Docker Compose v2 is missing: sudo apt install docker-compose-plugin"
need_cmd python3 "sudo apt install python3"
python3 -c 'import sys; sys.exit(sys.version_info < (3, 10))' || die "Python >= 3.10 is required ($(python3 --version))"
ok "git, docker, docker compose, $(python3 --version)"

tag="$(git -C "$ROOT" describe --tags --exact-match 2>/dev/null || true)"
if [ "$tag" = "v$VERSION" ]; then ok "checkout is on release tag $tag"
else warn "checkout is not on the release tag v$VERSION (at ${COMMIT:-unknown}): fine for development, install releases from a tag"; fi

# --- developer -------------------------------------------------------------
if [ "$DEVELOPER" = 1 ]; then
    PYTHON=""
    VENV_OK=0
    python3 -c 'import venv, ensurepip' 2>/dev/null && VENV_OK=1
    if [ "$CHECK" = 1 ] && [ "$VENV_OK" = 1 ]; then
        ok "python3-venv available: a virtual environment will be created in $ROOT/.venv"
        PYTHON="(venv)"
    elif [ "$VENV_OK" = 1 ]; then
        if [ ! -x "$ROOT/.venv/bin/python" ]; then
            python3 -m venv "$ROOT/.venv" >/dev/null 2>&1 || rm -rf "$ROOT/.venv"
        fi
        if [ -x "$ROOT/.venv/bin/python" ] \
           && "$ROOT/.venv/bin/python" -m pip install -q -r "$ROOT/tooling/builder/requirements.txt"; then
            PYTHON="$ROOT/.venv/bin/python"
            ok "virtual environment $ROOT/.venv with tooling/builder/requirements.txt"
        fi
    fi
    if [ -z "$PYTHON" ]; then
        if python3 -c 'import yaml, docker' 2>/dev/null; then
            PYTHON="$(command -v python3)"
            warn "no virtual environment (python3-venv missing): using the system python3 and its" \
                 "PyYAML $(python3 -c 'import yaml; print(yaml.__version__)'), docker $(python3 -c 'import docker; print(docker.__version__)')" \
                 "instead of the pinned versions in tooling/builder/requirements.txt"
        else
            die "cannot create a virtual environment and the system python3 lacks PyYAML/docker. Install one of:
       sudo apt install python3-venv        (then run this script again)
       sudo apt install python3-yaml python3-docker"
        fi
    fi
    command -v docker >/dev/null && docker buildx version >/dev/null 2>&1 \
        || warn "docker buildx is missing: only needed to build images for another CPU architecture"
    if [ "$CHECK" = 0 ]; then
        write_launcher rtmo "$PYTHON"
    fi
    ok "developer role $DONE"
fi

# --- device ----------------------------------------------------------------
if [ "$DEVICE" = 1 ]; then
    if [ "$(cat /sys/kernel/realtime 2>/dev/null || echo 0)" = "1" ]; then ok "PREEMPT_RT kernel"
    else warn "the kernel is not PREEMPT_RT (/sys/kernel/realtime): real-time results will not be meaningful"; fi
    [ -d /dev/mqueue ] && ok "/dev/mqueue" || warn "/dev/mqueue is missing: the mqueue implementations cannot run"
    iso="$(tr ' ' '\n' < /proc/cmdline | grep -E '^(isolcpus|nohz_full|rcu_nocbs)=' | tr '\n' ' ' || true)"
    if [ -n "$iso" ]; then ok "core isolation: $iso"
    else info "no core isolation (isolcpus/nohz_full/rcu_nocbs) on the kernel command line: see the plan's open decisions"; fi

    if [ "$CHECK" = 0 ]; then
        if [ ! -f /etc/rtmo/device.yaml ]; then
            mkdir -p /etc/rtmo
            cp "$ROOT/device/device.yaml.example" /etc/rtmo/device.yaml
            info "wrote /etc/rtmo/device.yaml"
        fi
        INFRA_CPU="$(sed -nE 's/^infra_cpu:[[:space:]]*([0-9]+).*/\1/p' /etc/rtmo/device.yaml | head -n1)"
        export RTMO_INFRA_CPU="${INFRA_CPU:-4}"

        info "building $DM_IMAGE"
        docker build -q -f "$ROOT/docker/deploy-manager.Dockerfile" \
            --build-arg RTMO_VERSION="$VERSION" --build-arg RTMO_COMMIT="$COMMIT" \
            -t "$DM_IMAGE" "$ROOT" >/dev/null
        ok "image $DM_IMAGE"

        # A 'redis' container of the former per-implementation stacks would block ours.
        project="$(docker inspect -f '{{ index .Config.Labels "com.docker.compose.project" }}' redis 2>/dev/null || true)"
        if [ -n "$project" ] && [ "$project" != "rtmo" ]; then
            warn "removing the old 'redis' container of compose project '$project'"
            docker rm -f redis >/dev/null
        fi
        docker compose -f "$ROOT/device/compose.yaml" up -d --quiet-pull
        ok "Redis running (container 'redis', network 'rtmo', 127.0.0.1:6379, core $RTMO_INFRA_CPU)"

        write_launcher rtmod
    fi
    ok "device role $DONE"
fi

[ "$CHECK" = 1 ] && info "check only: nothing was changed"
info "RTMO $VERSION ${COMMIT:+($COMMIT)} from $ROOT"

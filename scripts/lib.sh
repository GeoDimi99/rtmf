#!/usr/bin/env bash
# Helpers shared by install.sh and the RTMO scripts. Meant to be sourced.

if [ -t 2 ]; then C_RED=$'\033[0;31m' C_YEL=$'\033[0;33m' C_GRN=$'\033[0;32m' C_OFF=$'\033[0m'
else C_RED="" C_YEL="" C_GRN="" C_OFF=""; fi

info() { echo "[rtmo] $*" >&2; }
ok()   { echo "${C_GRN}[ ok ]${C_OFF} $*" >&2; }
warn() { echo "${C_YEL}[warn]${C_OFF} $*" >&2; }
die()  { echo "${C_RED}[fail]${C_OFF} $*" >&2; exit 1; }

# need_cmd <command> <how to install it>
need_cmd() {
    command -v "$1" >/dev/null 2>&1 || die "'$1' is missing. Install it: $2"
}

# rtmo_version <repo root>: content of VERSION
rtmo_version() { tr -d '[:space:]' < "$1/VERSION"; }

# rtmo_commit <repo root>: git describe of the checkout (empty outside git)
rtmo_commit() { git -C "$1" describe --tags --always --dirty 2>/dev/null || true; }

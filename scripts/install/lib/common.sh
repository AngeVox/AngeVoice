#!/usr/bin/env bash
# Shared helpers for scripts/install.sh modules.

log() { printf '\033[0;36m[AngeVoice]\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33m[WARN]\033[0m %s\n' "$*"; }
fail() { printf '\033[0;31m[ERROR]\033[0m %s\n' "$*" >&2; exit 1; }

need_cmd() { command -v "$1" >/dev/null 2>&1 || return 1; }

escape_sed_replacement() {
  printf '%s' "$1" | sed -e 's/[\/&]/\\&/g'
}

set_env_value() {
  local file="$1" key="$2" value="$3" escaped
  escaped="$(escape_sed_replacement "$value")"
  if grep -q "^#\?${key}=" "$file"; then
    sed -i "s|^#\?${key}=.*|${key}=${escaped}|" "$file"
  else
    printf '\n%s=%s\n' "$key" "$value" >> "$file"
  fi
}

is_project_root() {
  [[ -f "$1/docker/angevoice.env" && -d "$1/docker" && -d "$1/scripts" ]]
}

project_root_from_script() {
  local candidate
  candidate="$(cd "$SCRIPT_DIR/.." 2>/dev/null && pwd -P || true)"
  if [[ -n "$candidate" && -d "$candidate" ]]; then
    printf '%s\n' "$candidate"
  fi
}

detect_host_ip() {
  local ip=""
  if command -v ip >/dev/null 2>&1; then
    ip="$(ip -4 route get 1.1.1.1 2>/dev/null | awk '{for (i=1;i<=NF;i++) if ($i=="src") {print $(i+1); exit}}')"
  fi
  if [[ -z "$ip" ]] && command -v hostname >/dev/null 2>&1; then
    ip="$(hostname -I 2>/dev/null | awk '{print $1}')"
  fi
  printf '%s\n' "${ip:-127.0.0.1}"
}

#!/usr/bin/env bash
# Network/registry checks for scripts/install.sh.

_check_url() {
  local url="$1"
  curl -fsSL --connect-timeout 5 --max-time 8 "$url" >/dev/null 2>&1
}

_check_url_allow_http_error() {
  local url="$1" code
  code="$(curl -k -sS -o /dev/null -w '%{http_code}' --connect-timeout 5 --max-time 8 "$url" 2>/dev/null || true)"
  [[ "$code" =~ ^(200|301|302|401)$ ]]
}

_detect_registry_mirrors() {
  local file="/etc/docker/daemon.json"
  REGISTRY_MIRRORS=""
  if [[ -f "$file" ]]; then
    REGISTRY_MIRRORS="$(grep -o 'https\?://[^" ,]\+' "$file" 2>/dev/null | tr '\n' ' ' | sed 's/[[:space:]]*$//')"
  fi
}

check_network() {
  GITHUB_OK="no"
  GHCR_OK="no"
  DOCKERHUB_OK="no"
  _check_url https://github.com && GITHUB_OK="yes"
  _check_url_allow_http_error https://ghcr.io/v2/ && GHCR_OK="yes"
  _check_url_allow_http_error https://registry-1.docker.io/v2/ && DOCKERHUB_OK="yes"
  _detect_registry_mirrors
  log "网络检测：GitHub=${GITHUB_OK} GHCR=${GHCR_OK} DockerHub=${DOCKERHUB_OK}"
  if [[ -n "$REGISTRY_MIRRORS" ]]; then
    log "检测到 Docker registry mirror：$REGISTRY_MIRRORS"
  fi
  if [[ "$GITHUB_OK" != "yes" ]]; then
    warn "访问 GitHub 较差：建议使用代理、镜像源或手动上传源码包。"
  fi
  if [[ "$GHCR_OK" != "yes" ]]; then
    warn "访问 ghcr.io 较差：将跳过预构建镜像 pull，优先本地构建。"
  fi
  if [[ "$DOCKERHUB_OK" != "yes" && -z "$REGISTRY_MIRRORS" ]]; then
    warn "访问 Docker Hub 较差且未检测到 registry mirror；本地构建可能在拉基础镜像时较慢。"
  fi
}

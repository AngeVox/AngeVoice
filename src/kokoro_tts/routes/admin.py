"""AngeVoice 管理后台路由。"""

from __future__ import annotations

import os
import secrets

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import HTMLResponse
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from pydantic import BaseModel
from starlette.concurrency import run_in_threadpool

from ..service_state import ServiceState

security = HTTPBasic(auto_error=False)


class AdminModelAction(BaseModel):
    include_current: bool = True


def _admin_username() -> str:
    return os.environ.get("ANGEVOICE_ADMIN_USERNAME", "admin") or "admin"


def _admin_password() -> str:
    return os.environ.get("ANGEVOICE_ADMIN_PASSWORD", "") or ""


def create_admin_router(state: ServiceState) -> APIRouter:
    router = APIRouter()
    cfg = state.cfg

    def verify_admin(credentials: HTTPBasicCredentials | None = Depends(security)) -> None:
        if not cfg.admin_enabled:
            raise HTTPException(status_code=404, detail="管理后台未启用")
        expected_password = _admin_password()
        if not expected_password:
            raise HTTPException(status_code=503, detail="未配置管理后台密码")
        if credentials is None:
            raise HTTPException(status_code=401, detail="需要登录", headers={"WWW-Authenticate": "Basic"})
        username_ok = secrets.compare_digest(credentials.username, _admin_username())
        password_ok = secrets.compare_digest(credentials.password, expected_password)
        if not (username_ok and password_ok):
            raise HTTPException(status_code=401, detail="账号或密码错误", headers={"WWW-Authenticate": "Basic"})

    @router.get("/admin", response_class=HTMLResponse)
    async def admin_panel(_=Depends(verify_admin)):
        return HTMLResponse(
            """
<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>AngeVoice Admin</title>
  <script>
    const savedTheme = localStorage.getItem('angevoice.theme.v1');
    document.documentElement.dataset.theme = savedTheme || (matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light');
  </script>
  <link rel="stylesheet" href="/static/app.css" />
</head>
<body>
  <main class="app-shell">
    <header class="topbar">
      <div class="brand-mark brand-wordmark" aria-hidden="true"><span class="name-ange">Ange</span><span class="name-voice">Voice</span></div>
      <div class="brand-copy"><p class="eyebrow">Admin</p><h1>管理后台</h1></div>
      <div class="topbar-actions"><a class="ghost-button small" href="/">返回 Studio</a><a class="ghost-button small" href="/api-docs">API 文档</a></div>
    </header>
    <section class="workspace" style="grid-template-columns:1fr;">
      <article class="panel spotlight composer">
        <div class="section-head"><div><p class="eyebrow">Runtime</p><h2>运行状态与参数</h2></div></div>
        <div class="metrics-grid" id="admin-metrics"></div>
        <pre id="admin-json" class="progress-track show" style="white-space:pre-wrap;color:var(--text);"></pre>
        <div class="button-row" style="margin-top:14px;">
          <button class="primary-button" id="refresh-btn">刷新状态</button>
          <button class="secondary-button" id="clear-cache-btn">清空缓存</button>
          <button class="danger-button" id="unload-btn">释放所有模型</button>
        </div>
      </article>
    </section>
  </main>
  <script>
    async function api(path, options = {}) {
      const res = await fetch(path, options);
      if (!res.ok) throw new Error(await res.text());
      return await res.json();
    }
    function card(title, value) {
      return `<article class="metric-card spotlight"><span>${title}</span><strong>${value}</strong></article>`;
    }
    async function refresh() {
      const data = await api('/admin/api/status');
      const loaded = (data.models || []).filter(m => m.loaded).length;
      document.getElementById('admin-metrics').innerHTML = [
        card('当前模型', data.current_model || '-'),
        card('已加载', loaded),
        card('缓存', data.cache_items ?? 0),
        card('空闲释放', (data.config?.idle_timeout_seconds ?? 0) + 's')
      ].join('');
      document.getElementById('admin-json').textContent = JSON.stringify(data, null, 2);
    }
    document.getElementById('refresh-btn').onclick = refresh;
    document.getElementById('clear-cache-btn').onclick = async () => { await api('/admin/api/cache', {method:'DELETE'}); await refresh(); };
    document.getElementById('unload-btn').onclick = async () => {
      if (confirm('确认释放所有已加载模型？下次请求会自动重载。')) {
        await api('/admin/api/models/unload', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({include_current:true})});
        await refresh();
      }
    };
    refresh().catch(err => { document.getElementById('admin-json').textContent = String(err); });
  </script>
</body>
</html>
            """
        )

    @router.get("/admin/api/status")
    async def admin_status(_=Depends(verify_admin)):
        return {
            "current_model": state.model_manager.current_model_id,
            "models": state.model_manager.list_models(),
            "cache_items": state.cache_size(),
            "active_requests": list(state.active_requests.values())[-50:],
            "stats": state.snapshot_stats(),
            "config": {
                "enabled_models": cfg.enabled_models,
                "default_model": cfg.default_model,
                "max_concurrent_requests": cfg.max_concurrent_requests,
                "request_timeout_seconds": cfg.request_timeout_seconds,
                "idle_timeout_seconds": cfg.model_idle_timeout_seconds,
                "idle_check_interval": cfg.model_idle_check_interval,
                "idle_unload_current": getattr(cfg, "model_idle_unload_current", True),
                "moss_execution_provider": cfg.moss_execution_provider,
                "moss_stream_chunk_seconds": cfg.moss_stream_chunk_seconds,
                "moss_quality_gate_enabled": cfg.moss_quality_gate_enabled,
                "rate_limit_qps": cfg.rate_limit_qps,
                "max_queue_length": cfg.max_queue_length,
            },
        }

    @router.delete("/admin/api/cache")
    async def admin_clear_cache(_=Depends(verify_admin)):
        cleared = state.cache_clear()
        return {"ok": True, "cleared": cleared}

    @router.post("/admin/api/models/unload")
    async def admin_unload_models(req: AdminModelAction, _=Depends(verify_admin)):
        unloaded = await run_in_threadpool(
            state.model_manager.unload_inactive,
            force=False,
            include_current=req.include_current,
        )
        if unloaded:
            state.cache_clear()
        return {"ok": True, "unloaded": unloaded}

    return router

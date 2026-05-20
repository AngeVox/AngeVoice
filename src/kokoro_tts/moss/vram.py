"""MOSS CUDA 显存保护辅助函数。

这里保持轻量：导入时不强依赖 torch，可用时优先用 ``torch.cuda.mem_get_info``，
否则兜底调用 ``nvidia-smi``。它不是调度器，只提供足够信息让 AngeVoice
选择更保守的单次请求限制，并避免反复触发高成本 full-codec OOM。
"""

from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass


@dataclass(frozen=True)
class VramSnapshot:
    available: bool
    free_mb: int | None = None
    total_mb: int | None = None
    source: str = "unavailable"
    error: str = ""

    def as_dict(self) -> dict:
        return {
            "available": self.available,
            "free_mb": self.free_mb,
            "total_mb": self.total_mb,
            "source": self.source,
            "error": self.error,
        }


def get_cuda_vram_snapshot() -> VramSnapshot:
    """尽量安全地返回当前 CUDA 显存信息。"""

    try:
        import torch  # type: ignore

        if torch.cuda.is_available():
            free_bytes, total_bytes = torch.cuda.mem_get_info()
            return VramSnapshot(
                available=True,
                free_mb=int(free_bytes // (1024 * 1024)),
                total_mb=int(total_bytes // (1024 * 1024)),
                source="torch.cuda.mem_get_info",
            )
    except Exception as exc:  # noqa: BLE001 - best-effort probe
        torch_error = f"{type(exc).__name__}: {exc}"
    else:
        torch_error = "torch cuda unavailable"

    try:
        proc = subprocess.run(
            [
                "nvidia-smi",
                "--query-gpu=memory.free,memory.total",
                "--format=csv,noheader,nounits",
            ],
            check=False,
            capture_output=True,
            text=True,
            timeout=1.0,
        )
        if proc.returncode == 0 and proc.stdout.strip():
            first_line = proc.stdout.strip().splitlines()[0]
            parts = [item.strip() for item in first_line.split(",")]
            if len(parts) >= 2:
                return VramSnapshot(
                    available=True,
                    free_mb=int(float(parts[0])),
                    total_mb=int(float(parts[1])),
                    source="nvidia-smi",
                )
        return VramSnapshot(False, source="nvidia-smi", error=(proc.stderr or proc.stdout or torch_error).strip())
    except Exception as exc:  # noqa: BLE001 - best-effort probe
        return VramSnapshot(False, source="unavailable", error=f"{torch_error}; {type(exc).__name__}: {exc}")


def is_memory_allocation_error(exc: BaseException) -> bool:
    """尽力识别 ONNX Runtime / CUDA 显存分配失败。"""

    text = f"{type(exc).__name__}: {exc}".lower()
    patterns = (
        "failed to allocate memory",
        "allocate memory",
        "out of memory",
        "cuda out of memory",
        "bfc_arena",
        "onnxruntimeerror",
        "allocation",
    )
    return any(item in text for item in patterns)

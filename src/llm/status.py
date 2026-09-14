"""LLM 运行时可用性记录。

健康检查原先只判断「配没配 key」，于是 provider 返回 403/402 时界面依旧显示「后端正常」——
那盏绿灯和「能不能问答」毫无关系（实际踩过：中转把请求全拒了，界面还是正常）。

这里记录**每次真实调用**的结果，健康检查据此给出三态：
- `ok is None`：尚未验证（进程刚起、还没调用过）
- `ok is False`：最近一次调用失败，附归类后的原因与建议
- `ok is True`：最近一次调用成功

只在内存里记（进程级），不落库：它是运行时状态，重启后回到「未验证」比留下过期结论更诚实。
"""
from __future__ import annotations

import threading
from datetime import datetime, timezone
from typing import Any

_lock = threading.Lock()
_state: dict[str, Any] = {
    "ok": None,
    "reason": None,
    "hint": None,
    "status_code": None,
    "model": None,
    "checked_at": None,
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def record_success(model: str | None) -> None:
    global _state
    with _lock:
        _state = {
            "ok": True,
            "reason": None,
            "hint": None,
            "status_code": None,
            "model": model,
            "checked_at": _now(),
        }


def record_failure(exc: BaseException, model: str | None) -> None:
    from src.llm.errors import explain_llm_error

    error = exc if isinstance(exc, Exception) else Exception(str(exc))
    explained = explain_llm_error(error)
    global _state
    with _lock:
        _state = {
            "ok": False,
            "reason": explained["reason"],
            "hint": explained["hint"],
            "status_code": explained["status"],
            "model": model,
            "checked_at": _now(),
        }


def snapshot() -> dict:
    with _lock:
        return dict(_state)


def reset() -> None:
    """测试用：清回「未验证」。"""
    global _state
    with _lock:
        _state = {
            "ok": None,
            "reason": None,
            "hint": None,
            "status_code": None,
            "model": None,
            "checked_at": None,
        }

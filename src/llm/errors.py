"""把 LLM provider 的原始异常翻译成「原因 + 建议」。

界面以前直接显示 `Your request was blocked.` 这类原文——用户看到的是英文、且无法判断
该做什么（换 key？充值？换端点？）。这里按状态码与关键字归类，给出可行动的说明，
并把「究竟是哪个端点/模型/密钥」一并带出来：本项目的配置可能来自数据库里的 active
provider 或回退 .env，不说清楚就无从排查（实际踩过：DB 指向第三方中转、把 .env 的官方
端点悄悄盖住，报错时完全看不出用的是中转）。
"""
from __future__ import annotations

from typing import Any

# 关键词 → (原因, 建议)。按顺序匹配，先命中先返回。
_PATTERNS: tuple[tuple[tuple[str, ...], str, str], ...] = (
    (
        ("insufficient balance", "insufficient_quota", "insufficient balance", "no credit", "余额"),
        "账户余额或额度不足",
        "给该账号充值，或切换到额度充足的 provider",
    ),
    (
        ("your request was blocked", "blocked", "forbidden", "permission denied"),
        "请求被拒绝：密钥可能被风控/封禁，或该中转不认这个模型",
        "确认密钥状态；若用的是第三方中转，检查其账号是否被封或欠费，必要时改用官方端点",
    ),
    (
        ("invalid api key", "incorrect api key", "authentication", "unauthorized", "invalid_api_key"),
        "密钥无效或已失效",
        "重新复制完整的 API Key（注意不要带引号或空格），并确认它属于该端点",
    ),
    (
        ("model not exist", "model_not_found", "does not exist", "unknown model", "no such model"),
        "该端点没有这个模型名",
        "换成该端点支持的模型名（例如官方 DeepSeek 是 deepseek-chat / deepseek-reasoner）",
    ),
    (
        ("rate limit", "too many requests", "tpm", "rpm"),
        "触发限流",
        "稍后重试，或降低并发/评测批量",
    ),
    (
        ("does not support this tool_choice",),
        "该模型不支持强制指定工具调用",
        "项目已自动退化为非强制调用；若仍失败可换支持 function calling 的模型",
    ),
    (
        ("timed out", "timeout"),
        "请求超时",
        "检查 base_url 是否可达、网络/代理是否正常，必要时调大 LLM_TIMEOUT",
    ),
    (
        ("connection error", "connection refused", "name or service not known", "getaddrinfo"),
        "连不上该端点",
        "检查 base_url 拼写、网络与代理设置",
    ),
)

_BY_STATUS: dict[int, tuple[str, str]] = {
    401: ("密钥无效或已失效", "重新复制完整的 API Key，并确认它属于该端点"),
    402: ("账户余额或额度不足", "给该账号充值，或切换到额度充足的 provider"),
    403: ("请求被拒绝：密钥可能被风控或该端点不允许访问", "确认密钥状态，必要时改用官方端点"),
    404: ("端点或模型不存在", "检查 base_url 与模型名"),
    408: ("请求超时", "检查网络与 base_url 可达性"),
    429: ("触发限流", "稍后重试，或降低并发"),
    500: ("服务端错误", "稍后重试"),
    502: ("网关错误（上游不可用）", "稍后重试；若是中转服务，确认其上游是否正常"),
    503: ("服务暂不可用", "稍后重试"),
    504: ("网关超时", "稍后重试"),
}


def explain_llm_error(exc: Exception) -> dict[str, Any]:
    """返回 {reason, hint, status, type, raw}；无法归类时 reason 退化为原始消息。"""
    status = getattr(exc, "status_code", None)
    message = str(exc) or type(exc).__name__
    lowered = message.lower()

    reason = hint = None
    if isinstance(status, int) and status in _BY_STATUS:
        reason, hint = _BY_STATUS[status]
    for keywords, pat_reason, pat_hint in _PATTERNS:
        if any(keyword in lowered for keyword in keywords):
            reason, hint = pat_reason, pat_hint
            break

    if reason is None:
        reason = f"调用失败：{message[:160]}"
        hint = "检查 provider 配置（base_url / 模型 / 密钥）与网络连通性"
    return {
        "reason": reason,
        "hint": hint,
        "status": status if isinstance(status, int) else None,
        "type": type(exc).__name__,
        "raw": message[:300],
    }


def describe_key(api_key: str | None) -> str:
    """密钥指纹：够辨认是哪一把，又不泄露完整密钥。"""
    key = api_key or ""
    if len(key) <= 12:
        return f"（{len(key)} 字符）"
    return f"{key[:6]}…{key[-4:]}"

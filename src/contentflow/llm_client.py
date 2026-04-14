"""LLM Client with automatic provider failover.

當主要 provider（OpenAI）被 rate-limit 或不可用時，
自動切換到備援 provider（Anthropic → OpenAI fallback model）。

用法：
    from contentflow.llm_client import get_llm_client, achat

    # 同步呼叫（drop-in replacement for OpenAI）
    client = get_llm_client()
    response = client.chat.completions.create(...)

    # 非同步呼叫，自帶 failover
    result = await achat(messages=[...], model="gpt-4o-mini")
"""
from __future__ import annotations

import time
from typing import Any

from loguru import logger

from contentflow.config import settings


# ── Provider cooldown tracking ─────────────────────────────────

_provider_cooldowns: dict[str, float] = {}
_COOLDOWN_SECONDS = 60  # rate-limit 後冷卻 60 秒


def _is_cooled_down(provider: str) -> bool:
    """檢查 provider 是否還在 cooldown 期間。"""
    until = _provider_cooldowns.get(provider, 0)
    return time.time() >= until


def _set_cooldown(provider: str) -> None:
    """將 provider 設為 cooldown 狀態。"""
    _provider_cooldowns[provider] = time.time() + _COOLDOWN_SECONDS
    logger.warning(f"[LLMClient] {provider} 進入 cooldown {_COOLDOWN_SECONDS}s")


# ── Sync client（drop-in for agents using OpenAI directly）─────

def get_llm_client():
    """取得 OpenAI client，供現有 agent 直接使用。

    這是最小侵入式的改法——現有 agent 只需把
    `OpenAI(api_key=settings.openai_api_key)` 換成 `get_llm_client()`。
    """
    from openai import OpenAI
    return OpenAI(api_key=settings.openai_api_key)


def get_async_llm_client():
    """取得 AsyncOpenAI client。"""
    from openai import AsyncOpenAI
    return AsyncOpenAI(api_key=settings.openai_api_key)


# ── Async chat with failover ──────────────────────────────────

async def achat(
    *,
    messages: list[dict[str, str]],
    model: str | None = None,
    temperature: float = 0.3,
    response_format: dict | None = None,
    max_tokens: int | None = None,
) -> str:
    """非同步 LLM 呼叫，自帶 provider failover。

    嘗試順序：
    1. OpenAI（主要 provider，使用指定 model）
    2. Anthropic（如果有 ANTHROPIC_API_KEY）
    3. OpenAI fallback model（gpt-4o-mini，用不同參數重試）

    Returns:
        LLM 回應的文字內容。
    """
    target_model = model or settings.llm_lite_model or "gpt-4o-mini"
    errors: list[str] = []

    # Provider 1: OpenAI (primary)
    if settings.openai_api_key and _is_cooled_down("openai"):
        try:
            return await _call_openai(
                messages=messages,
                model=target_model,
                temperature=temperature,
                response_format=response_format,
                max_tokens=max_tokens,
            )
        except Exception as e:
            err_str = str(e)
            errors.append(f"OpenAI({target_model}): {err_str[:100]}")
            if "rate" in err_str.lower() or "429" in err_str:
                _set_cooldown("openai")

    # Provider 2: Anthropic (fallback)
    if settings.anthropic_api_key and _is_cooled_down("anthropic"):
        try:
            return await _call_anthropic(
                messages=messages,
                temperature=temperature,
                max_tokens=max_tokens or 4096,
            )
        except Exception as e:
            err_str = str(e)
            errors.append(f"Anthropic: {err_str[:100]}")
            if "rate" in err_str.lower() or "429" in err_str:
                _set_cooldown("anthropic")

    # Provider 3: OpenAI fallback model (last resort)
    if settings.openai_api_key and target_model != "gpt-4o-mini":
        try:
            return await _call_openai(
                messages=messages,
                model="gpt-4o-mini",
                temperature=temperature,
                response_format=response_format,
                max_tokens=max_tokens,
            )
        except Exception as e:
            errors.append(f"OpenAI(gpt-4o-mini fallback): {str(e)[:100]}")

    raise RuntimeError(
        f"[LLMClient] 所有 provider 都失敗：{'; '.join(errors)}"
    )


async def _call_openai(
    *,
    messages: list[dict],
    model: str,
    temperature: float,
    response_format: dict | None,
    max_tokens: int | None,
) -> str:
    from openai import AsyncOpenAI

    client = AsyncOpenAI(api_key=settings.openai_api_key)
    kwargs: dict[str, Any] = {
        "model": model,
        "messages": messages,
        "temperature": temperature,
    }
    if response_format:
        kwargs["response_format"] = response_format
    if max_tokens:
        kwargs["max_tokens"] = max_tokens

    response = await client.chat.completions.create(**kwargs)
    return response.choices[0].message.content or ""


async def _call_anthropic(
    *,
    messages: list[dict],
    temperature: float,
    max_tokens: int,
) -> str:
    import anthropic

    client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)

    # Convert OpenAI message format to Anthropic format
    system_msg = ""
    user_msgs = []
    for m in messages:
        if m["role"] == "system":
            system_msg = m["content"]
        else:
            user_msgs.append({"role": m["role"], "content": m["content"]})

    response = await client.messages.create(
        model="claude-sonnet-4-5",
        max_tokens=max_tokens,
        temperature=temperature,
        system=system_msg,
        messages=user_msgs,
    )
    return response.content[0].text

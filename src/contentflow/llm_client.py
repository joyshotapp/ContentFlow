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
from contextvars import ContextVar
from typing import Any

from loguru import logger

from contentflow.config import settings


# ── Token pricing (USD per 1M tokens) ───────────────────────────────────
# 來源：https://openai.com/pricing  https://www.anthropic.com/pricing  https://ai.google.dev/pricing
_PRICING: dict[str, dict[str, float]] = {
    "gpt-4o-mini":              {"input": 0.15,   "output": 0.60},
    "gpt-4o":                   {"input": 2.50,   "output": 10.00},
    "gpt-4-turbo":              {"input": 10.00,  "output": 30.00},
    "claude-sonnet-4-5":        {"input": 3.00,   "output": 15.00},
    "claude-opus-4":            {"input": 15.00,  "output": 75.00},
    "claude-haiku-3-5":         {"input": 0.80,   "output": 4.00},
    "gemini-3-flash-preview":          {"input": 0.50,   "output": 3.00},
    "gemini-2.5-flash-preview":        {"input": 0.30,   "output": 2.50},
    "gemini-2.0-flash":                {"input": 0.10,   "output": 0.40},
    "gemini-3.1-flash-image-preview":  {"input": 0.50,   "output": 60.00},  # image output: $60/1M tokens
}
_DEFAULT_PRICING = {"input": 0.15, "output": 0.60}  # fallback


def _compute_cost(model: str, prompt_tokens: int, completion_tokens: int) -> float:
    """Calculate cost in USD for a single LLM call."""
    p = _PRICING.get(model, _DEFAULT_PRICING)
    return (prompt_tokens * p["input"] + completion_tokens * p["output"]) / 1_000_000


# ── Per-pipeline cost accumulator (用 ContextVar，對 async 任務安全) ────────────

_cost_ctx: ContextVar[dict | None] = ContextVar("_llm_cost_ctx", default=None)


def reset_cost_tracker() -> None:
    """Pipeline 啟動時呼叫，清空第一次 LLM cost 計算。"""
    _cost_ctx.set({"prompt": 0, "completion": 0, "cost": 0.0, "calls": 0})


def get_cost_summary() -> dict:
    """Return accumulated token usage and cost for the current async context."""
    acc = _cost_ctx.get(None)
    if acc is None:
        return {"prompt_tokens": 0, "completion_tokens": 0, "total_cost": 0.0, "calls": 0}
    return {
        "prompt_tokens": acc["prompt"],
        "completion_tokens": acc["completion"],
        "total_cost": round(acc["cost"], 6),
        "calls": acc["calls"],
    }


def _accumulate(model: str, prompt_tokens: int, completion_tokens: int) -> float:
    """Add to the running accumulator; return cost for this call."""
    call_cost = _compute_cost(model, prompt_tokens, completion_tokens)
    acc = _cost_ctx.get(None)
    if acc is not None:
        acc["prompt"] += prompt_tokens
        acc["completion"] += completion_tokens
        acc["cost"] += call_cost
        acc["calls"] += 1
    return call_cost


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

def _is_gemini_model(model: str) -> bool:
    return "gemini" in model.lower()


def _gemini_temperature(model: str, requested_temperature: float) -> float:
    """Gemini 3 系列固定使用 1.0；其他 Gemini model 保留 caller 指定值。"""
    if model.lower().startswith("gemini-3"):
        return 1.0
    return requested_temperature


async def achat(
    *,
    messages: list[dict[str, str]],
    model: str | None = None,
    temperature: float = 0.3,
    response_format: dict | None = None,
    max_tokens: int | None = None,
) -> str:
    """非同步 LLM 呼叫，自帶 provider failover。

    嘗試順序（Gemini model）：
    1. Gemini（主要 provider）
    2. OpenAI fallback（如果有 OPENAI_API_KEY）
    嘗試順序（其他 model）：
    1. OpenAI
    2. Anthropic（如果有 ANTHROPIC_API_KEY）
    3. OpenAI fallback model（gpt-4o-mini）

    Returns:
        LLM 回應的文字內容。
    """
    target_model = model or settings.llm_lite_model or "gemini-3-flash-preview"
    errors: list[str] = []

    # Provider 1: Gemini (primary for Gemini models)
    if _is_gemini_model(target_model) and settings.gemini_api_key and _is_cooled_down("gemini"):
        try:
            return await _call_gemini(
                messages=messages,
                model=target_model,
                temperature=1.0,  # Gemini 3 系列必須保持 temperature=1.0
                max_tokens=max_tokens,
            )
        except Exception as e:
            err_str = str(e)
            errors.append(f"Gemini({target_model}): {err_str[:100]}")
            if "rate" in err_str.lower() or "429" in err_str or "quota" in err_str.lower():
                _set_cooldown("gemini")
            else:
                # Non-rate-limit error — fall through to OpenAI fallback
                pass

    # Provider 1b: OpenAI (primary for non-Gemini models)
    if not _is_gemini_model(target_model) and settings.openai_api_key and _is_cooled_down("openai"):
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

    # Provider 2: Anthropic (fallback for non-Gemini models)
    if not _is_gemini_model(target_model) and settings.anthropic_api_key and _is_cooled_down("anthropic"):
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

    # Provider 3: OpenAI fallback (last resort for all models)
    if settings.openai_api_key and _is_cooled_down("openai"):
        try:
            return await _call_openai(
                messages=messages,
                model="gpt-4o-mini",
                temperature=min(temperature, 1.0),
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
    # 記錄真實 token 用量
    if response.usage:
        cost = _accumulate(model, response.usage.prompt_tokens, response.usage.completion_tokens)
        logger.debug(
            f"[LLMClient] {model} 用量: "
            f"in={response.usage.prompt_tokens} out={response.usage.completion_tokens} "
            f"cost=${cost:.4f}"
        )
    return response.choices[0].message.content or ""


async def _call_gemini(
    *,
    messages: list[dict],
    model: str,
    temperature: float,
    max_tokens: int | None,
) -> str:
    """Gemini provider 呼叫（google-genai SDK）。"""
    from google import genai
    from google.genai import types

    client = genai.Client(api_key=settings.gemini_api_key)

    system_instruction: str | None = None
    contents: list = []
    for m in messages:
        role = m.get("role", "")
        content = m.get("content") or ""
        if role == "system":
            system_instruction = content
        elif role == "user":
            contents.append(
                types.Content(role="user", parts=[types.Part.from_text(text=content)])
            )
        elif role == "assistant":
            if content:
                contents.append(
                    types.Content(role="model", parts=[types.Part.from_text(text=content)])
                )

    gen_config = types.GenerateContentConfig(
        max_output_tokens=max_tokens or 4096,
        system_instruction=system_instruction,
        temperature=_gemini_temperature(model, temperature),
    )

    response = await client.aio.models.generate_content(
        model=model,
        contents=contents,
        config=gen_config,
    )

    if response.usage_metadata:
        cost = _accumulate(
            model,
            response.usage_metadata.prompt_token_count or 0,
            response.usage_metadata.candidates_token_count or 0,
        )
        logger.debug(
            f"[LLMClient] {model} 用量: "
            f"in={response.usage_metadata.prompt_token_count} "
            f"out={response.usage_metadata.candidates_token_count} "
            f"cost=${cost:.4f}"
        )
    return response.text or ""


def chat_sync(
    *,
    messages: list[dict[str, str]],
    model: str | None = None,
    temperature: float = 0.7,
    max_tokens: int | None = None,
) -> str:
    """同步 LLM 呼叫（供 sync agents 使用）。

    優先使用 Gemini；若無 Gemini API key 則 fallback 到 OpenAI。
    """
    from google import genai
    from google.genai import types

    target_model = model or settings.llm_lite_model or "gemini-3-flash-preview"

    # Primary: Gemini
    if settings.gemini_api_key:
        try:
            client = genai.Client(api_key=settings.gemini_api_key)
            gemini_model = target_model if _is_gemini_model(target_model) else "gemini-3-flash-preview"

            system_instruction: str | None = None
            contents: list = []
            for m in messages:
                role = m.get("role", "")
                content = m.get("content") or ""
                if role == "system":
                    system_instruction = content
                elif role == "user":
                    contents.append(
                        types.Content(role="user", parts=[types.Part.from_text(text=content)])
                    )
                elif role == "assistant":
                    if content:
                        contents.append(
                            types.Content(role="model", parts=[types.Part.from_text(text=content)])
                        )

            gen_config = types.GenerateContentConfig(
                max_output_tokens=max_tokens or 4096,
                system_instruction=system_instruction,
                temperature=_gemini_temperature(gemini_model, temperature),
            )

            response = client.models.generate_content(
                model=gemini_model,
                contents=contents,
                config=gen_config,
            )

            if response.usage_metadata:
                _accumulate(
                    gemini_model,
                    response.usage_metadata.prompt_token_count or 0,
                    response.usage_metadata.candidates_token_count or 0,
                )
            return response.text or ""
        except Exception as e:
            logger.warning(f"[LLMClient] Gemini sync 失敗，切換 OpenAI fallback: {e}")

    # Fallback: OpenAI
    from openai import OpenAI
    client_oai = OpenAI(api_key=settings.openai_api_key)
    oai_model = target_model if not _is_gemini_model(target_model) else "gpt-4o-mini"
    resp = client_oai.chat.completions.create(
        model=oai_model,
        messages=messages,  # type: ignore[arg-type]
        temperature=temperature,
        max_completion_tokens=max_tokens or 4096,
    )
    if resp.usage:
        _accumulate(oai_model, resp.usage.prompt_tokens, resp.usage.completion_tokens)
    return resp.choices[0].message.content or ""


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
    # 記錄真實 token 用量
    if response.usage:
        cost = _accumulate(
            "claude-sonnet-4-5",
            response.usage.input_tokens,
            response.usage.output_tokens,
        )
        logger.debug(
            f"[LLMClient] claude-sonnet-4-5 用量: "
            f"in={response.usage.input_tokens} out={response.usage.output_tokens} "
            f"cost=${cost:.4f}"
        )
    return response.content[0].text

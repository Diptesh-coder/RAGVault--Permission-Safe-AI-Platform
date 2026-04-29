"""Claude Sonnet 4.5 integration with TRUE streaming via litellm + Emergent proxy.

Emits Prometheus metrics on entry, fallback, and time-to-first-token so prod
ops can alert on silent regressions.
"""
import os
import time
import asyncio
import logging
from typing import AsyncGenerator, List, Dict

import litellm
from emergentintegrations.llm.chat import LlmChat, UserMessage
from emergentintegrations.llm.utils import get_app_identifier, get_integration_proxy_url

import metrics

logger = logging.getLogger("sentinel_rag.llm")

EMERGENT_LLM_KEY = os.environ["EMERGENT_LLM_KEY"]
MODEL = "claude-sonnet-4-5-20250929"
PROVIDER = "anthropic"

SYSTEM_MESSAGE = (
    "You are SentinelRAG, an enterprise policy-aware assistant. "
    "You answer ONLY using the authorized document excerpts supplied in the user "
    "message under the `<authorized_context>` block. "
    "If the context is empty or does not contain the answer, respond exactly with: "
    "'I was unable to find an answer within the documents you are authorized to access.' "
    "Never speculate, never invent facts, and never reveal the existence of documents "
    "outside the authorized context. Be concise, professional, and cite document titles "
    "inline like [Title]."
)


def _build_prompt(query: str, context_docs: List[Dict]) -> str:
    if context_docs:
        context_block = "\n\n".join(
            f"[{d['title']}] (dept={d['department']}, sensitivity={d['sensitivity']})\n{d['content']}"
            for d in context_docs
        )
    else:
        context_block = "(no authorized documents were retrieved)"
    return (
        f"<authorized_context>\n{context_block}\n</authorized_context>\n\n"
        f"User question: {query}"
    )


# ── Non-streaming (kept for /api/chat parity and tests) ───────────────────────
async def generate_answer(query: str, context_docs: list, session_id: str) -> str:
    chat = LlmChat(
        api_key=EMERGENT_LLM_KEY, session_id=session_id, system_message=SYSTEM_MESSAGE,
    ).with_model(PROVIDER, MODEL)
    response = await chat.send_message(UserMessage(text=_build_prompt(query, context_docs)))
    return response if isinstance(response, str) else str(response)


# ── True streaming via the Emergent litellm proxy ─────────────────────────────
def _build_litellm_params(messages: List[Dict]) -> Dict:
    proxy_url = get_integration_proxy_url()
    headers = {}
    app_id = get_app_identifier()
    if app_id:
        headers["X-App-ID"] = app_id
    return {
        "model": MODEL,
        "messages": messages,
        "api_key": EMERGENT_LLM_KEY,
        "api_base": proxy_url + "/llm",
        "custom_llm_provider": "openai",
        "stream": True,
        "extra_headers": headers,
    }


async def stream_answer(
    query: str, context_docs: list, session_id: str
) -> AsyncGenerator[str, None]:
    """Yield real Claude tokens. Falls back to pseudo-stream on error."""
    metrics.stream_total.inc()
    start = time.perf_counter()
    first_seen = False

    messages = [
        {"role": "system", "content": SYSTEM_MESSAGE},
        {"role": "user", "content": _build_prompt(query, context_docs)},
    ]
    params = _build_litellm_params(messages)

    try:
        response = await litellm.acompletion(**params)
        async for chunk in response:
            try:
                delta = chunk.choices[0].delta
                content = getattr(delta, "content", None) or ""
            except Exception:
                content = ""
            if content:
                if not first_seen:
                    metrics.stream_first_token_seconds.observe(time.perf_counter() - start)
                    first_seen = True
                yield content
        if not first_seen:
            # No content was ever produced — treat as a failure and fall back.
            raise RuntimeError("real stream produced zero content chunks")
        return
    except Exception as e:
        logger.warning(f"True streaming failed, falling back to pseudo-stream: {e}")
        metrics.stream_fallback_total.inc()

    # Fallback path
    full = await generate_answer(query, context_docs, session_id)
    if not first_seen:
        metrics.stream_first_token_seconds.observe(time.perf_counter() - start)
    import re
    for tok in re.findall(r"\S+\s*", full) or [full]:
        yield tok
        await asyncio.sleep(0.018)

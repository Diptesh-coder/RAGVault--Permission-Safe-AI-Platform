"""Claude Sonnet 4.5 integration — full answer + pseudo-streaming generator."""
import os
import asyncio
from typing import AsyncGenerator, List, Dict
from emergentintegrations.llm.chat import LlmChat, UserMessage

EMERGENT_LLM_KEY = os.environ["EMERGENT_LLM_KEY"]

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


async def generate_answer(
    query: str, context_docs: list, session_id: str
) -> str:
    chat = LlmChat(
        api_key=EMERGENT_LLM_KEY,
        session_id=session_id,
        system_message=SYSTEM_MESSAGE,
    ).with_model("anthropic", "claude-sonnet-4-5-20250929")
    response = await chat.send_message(UserMessage(text=_build_prompt(query, context_docs)))
    return response if isinstance(response, str) else str(response)


async def stream_answer(
    query: str, context_docs: list, session_id: str
) -> AsyncGenerator[str, None]:
    """Pseudo-stream the answer word-by-word for a live UX feel.

    emergentintegrations returns a full string; we generate once then yield
    tokens with small delays. Same safety guarantees as generate_answer.
    """
    full = await generate_answer(query, context_docs, session_id)
    # Split but keep whitespace so reconstruction is faithful.
    import re
    tokens = re.findall(r"\S+\s*", full) or [full]
    for t in tokens:
        yield t
        await asyncio.sleep(0.018)

"""Claude Sonnet 4.5 integration via emergentintegrations."""
import os
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


async def generate_answer(
    query: str, context_docs: list, session_id: str
) -> str:
    """Send an RBAC-filtered prompt to Claude Sonnet 4.5."""
    chat = LlmChat(
        api_key=EMERGENT_LLM_KEY,
        session_id=session_id,
        system_message=SYSTEM_MESSAGE,
    ).with_model("anthropic", "claude-sonnet-4-5-20250929")

    if context_docs:
        context_block = "\n\n".join(
            f"[{d['title']}] (dept={d['department']}, sensitivity={d['sensitivity']})\n{d['content']}"
            for d in context_docs
        )
    else:
        context_block = "(no authorized documents were retrieved)"

    prompt = (
        f"<authorized_context>\n{context_block}\n</authorized_context>\n\n"
        f"User question: {query}"
    )

    response = await chat.send_message(UserMessage(text=prompt))
    return response if isinstance(response, str) else str(response)

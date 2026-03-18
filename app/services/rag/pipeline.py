"""RAG query pipeline — retrieve session context from PageIndex and query Claude."""

import json
import logging
import uuid
from collections.abc import AsyncIterator
from typing import Any

import anthropic

from app.config import settings
from app.services.rag.page_index import page_index

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """You are a supermarket analytics expert. You analyze customer foot traffic \
heatmap data from store surveillance sessions. You have access to zone-level heatmap grids \
(10x10, values 0-100 representing foot traffic intensity), customer counts, and session metadata.

When answering questions:
- Reference specific zone coordinates (row, col) and their heat values
- Identify patterns in foot traffic (hot zones = high traffic, cold zones = low traffic)
- Provide actionable recommendations for store layout optimization
- Compare sessions when multiple are provided
- Be concise and data-driven in your analysis

If no session data is available for the query, say so clearly."""

AUTO_INSIGHT_PROMPT = """Analyze the following supermarket session data and provide a structured insight report.

{context}

Respond with ONLY valid JSON in this exact format (no markdown, no code fences):
{{
  "summary": "A 2-3 sentence summary of the session's foot traffic patterns",
  "hot_zones": ["Zone (row,col): brief description of why it's hot", ...],
  "cold_zones": ["Zone (row,col): brief description of why it's cold", ...],
  "recommendations": ["Actionable recommendation based on the data", ...]
}}

Provide 3-5 items for hot_zones, cold_zones, and recommendations each."""


async def query(
    question: str,
    session_ids: list[uuid.UUID] | None = None,
    store_id: str | None = None,
) -> AsyncIterator[str]:
    """Query Claude with session context from PageIndex. Yields streamed response tokens."""
    context = page_index.build_context(
        session_ids=session_ids,
        store_id=store_id,
        max_docs=settings.RAG_TOP_K,
    )

    user_message = f"""Here is the session data context:

{context}

Question: {question}"""

    client = anthropic.AsyncAnthropic(api_key=settings.ANTHROPIC_API_KEY)

    async with client.messages.stream(
        model=settings.CLAUDE_MODEL,
        max_tokens=1024,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_message}],
    ) as stream:
        async for text in stream.text_stream:
            yield text


async def auto_insight(session_id: uuid.UUID) -> dict[str, Any]:
    """Generate a structured insight report for a single session.

    Returns dict with: summary, hot_zones, cold_zones, recommendations
    """
    context = page_index.build_context(session_ids=[session_id])

    if context == "No session data available for the given filters.":
        raise ValueError(f"No indexed data found for session {session_id}")

    client = anthropic.AsyncAnthropic(api_key=settings.ANTHROPIC_API_KEY)

    message = await client.messages.create(
        model=settings.CLAUDE_MODEL,
        max_tokens=1024,
        system=SYSTEM_PROMPT,
        messages=[{
            "role": "user",
            "content": AUTO_INSIGHT_PROMPT.format(context=context),
        }],
    )

    raw_text = message.content[0].text.strip()

    # Parse JSON response — strip markdown fences if Claude adds them
    if raw_text.startswith("```"):
        raw_text = raw_text.split("\n", 1)[1]
        if raw_text.endswith("```"):
            raw_text = raw_text[:-3].strip()

    try:
        result = json.loads(raw_text)
    except json.JSONDecodeError:
        logger.error("Failed to parse auto-insight JSON for session %s: %s", session_id, raw_text)
        result = {
            "summary": raw_text,
            "hot_zones": [],
            "cold_zones": [],
            "recommendations": [],
        }

    return {
        "session_id": session_id,
        "summary": result.get("summary", ""),
        "hot_zones": result.get("hot_zones", []),
        "cold_zones": result.get("cold_zones", []),
        "recommendations": result.get("recommendations", []),
    }

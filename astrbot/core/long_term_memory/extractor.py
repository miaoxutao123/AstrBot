"""LLM-based candidate fact extraction for the Long-Term Memory system."""

import json
import re
import uuid

from astrbot import logger
from astrbot.core.provider.provider import Provider

EXTRACTION_PROMPT = """\
You are a memory extraction assistant. Given a conversation segment, extract any long-term facts worth remembering about the user or context.

Rules:
- Only extract genuinely useful, non-trivial facts.
- Each fact must be a concise, self-contained statement.
- Classify each fact into exactly one type: profile, preference, task_state, constraint, episode.
- Output a JSON array. Output [] if nothing is worth remembering.
- Do NOT extract transient information like greetings, acknowledgments, or ephemeral requests.

Types:
- profile: stable identity facts (name, role, location, etc.)
- preference: user style and choices (coding style, language preference, etc.)
- task_state: long-running task progress (project status, milestones, etc.)
- constraint: hard requirements and forbidden actions (security rules, limitations, etc.)
- episode: compressed historical milestones (significant events, completed work, etc.)

For each fact, output:
{{"type": "<type>", "fact": "<concise statement>", "fact_key": "<normalized_key_for_dedup>", "confidence": <0.0-1.0>, "importance": <0.0-1.0>}}

Conversation segment:
---
{conversation}
---

Output JSON array only, no other text:"""


def _normalize_fact_key(raw_key: str) -> str:
    """Normalize a fact key for dedup: lowercase, strip punctuation, limit length."""
    key = raw_key.lower().strip()
    key = re.sub(r"[^\w\s]", "", key)
    key = re.sub(r"\s+", "_", key)
    return key[:128]


def _build_conversation_text(
    messages: list[dict],
    max_chars: int = 4000,
) -> str:
    """Build a compact conversation text from message dicts."""
    parts = []
    for msg in messages:
        role = msg.get("role", "unknown")
        content = msg.get("content", "")
        if isinstance(content, list):
            # Extract text parts only
            text_parts = []
            for part in content:
                if isinstance(part, dict) and part.get("type") == "text":
                    text_parts.append(part.get("text", ""))
                elif isinstance(part, str):
                    text_parts.append(part)
            content = " ".join(text_parts)
        if isinstance(content, str) and content.strip():
            parts.append(f"[{role}]: {content.strip()}")

    text = "\n".join(parts)
    if len(text) > max_chars:
        text = text[:max_chars] + "\n...[truncated]"
    return text


async def extract_candidates(
    provider: Provider,
    messages: list[dict],
    max_candidates: int = 10,
    session_id: str | None = None,
) -> list[dict]:
    """Extract memory candidates from conversation messages using an LLM.

    Returns a list of candidate dicts with keys:
        type, fact, fact_key, confidence, importance

    This function is designed to run asynchronously outside the hot path.
    """
    conversation_text = _build_conversation_text(messages)
    if not conversation_text.strip():
        return []

    prompt = EXTRACTION_PROMPT.format(conversation=conversation_text)

    try:
        response = await provider.text_chat(
            prompt=prompt,
            session_id=session_id or f"ltm_extract_{uuid.uuid4().hex[:8]}",
        )
    except Exception as e:
        logger.warning("LTM extraction LLM call failed: %s", e)
        raise

    if not response or not response.completion_text:
        return []

    # Parse JSON from response
    raw_text = response.completion_text.strip()

    # Strip markdown code fences if present
    fence_match = re.search(r"```(?:json)?\s*(\[.*?\])\s*```", raw_text, re.DOTALL)
    if fence_match:
        json_text = fence_match.group(1)
    else:
        # Try to find JSON array in the response
        arr_match = re.search(r"\[.*\]", raw_text, re.DOTALL)
        if not arr_match:
            logger.debug("LTM extraction returned no JSON array: %s", raw_text[:200])
            return []
        json_text = arr_match.group()

    try:
        candidates = json.loads(json_text)
    except json.JSONDecodeError as e:
        logger.debug("LTM extraction JSON parse error: %s", e)
        return []

    if not isinstance(candidates, list):
        return []

    # Validate and normalize
    valid = []
    for item in candidates[:max_candidates]:
        if not isinstance(item, dict):
            continue

        # Normalize keys: strip any stray quotes/whitespace from keys
        cleaned = {}
        for k, v in item.items():
            clean_key = k.strip().strip('"').strip("'").strip()
            cleaned[clean_key] = v

        mem_type = cleaned.get("type", "")
        fact = cleaned.get("fact", "")
        fact_key = cleaned.get("fact_key", "")
        confidence = cleaned.get("confidence", 0.5)
        importance = cleaned.get("importance", 0.5)

        if not mem_type or not fact:
            continue
        # Normalize type string as well
        mem_type = str(mem_type).strip().strip('"').strip("'").strip()
        if mem_type not in ("profile", "preference", "task_state", "constraint", "episode"):
            continue

        fact_key = _normalize_fact_key(fact_key or fact)
        if not fact_key:
            continue

        try:
            valid.append({
                "type": mem_type,
                "fact": str(fact).strip()[:500],
                "fact_key": fact_key,
                "confidence": max(0.0, min(1.0, float(confidence))),
                "importance": max(0.0, min(1.0, float(importance))),
            })
        except (ValueError, TypeError) as e:
            logger.debug("LTM candidate field conversion error: %s", e)
            continue

    return valid

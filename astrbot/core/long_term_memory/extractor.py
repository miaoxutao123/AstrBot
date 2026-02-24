"""LLM-based candidate fact extraction for the Long-Term Memory system."""

import json
import re
import uuid

from astrbot import logger
from astrbot.core.provider.provider import Provider

EXTRACTION_PROMPT = """\
You are a long-term memory extraction assistant for a multi-turn AI agent.
你是多轮智能体的长期记忆抽取器。请从对话中提取“可复用、可长期保留”的事实。

Output requirements / 输出要求:
1) Return STRICT JSON only, no markdown, no explanation.
2) Output object schema:
{{
  "candidates": [
    {{
      "type": "profile|preference|task_state|constraint|episode",
      "fact": "<concise standalone fact>",
      "subject_key": "<stable concept key independent of value>",
      "relation_predicate": "<optional short relation predicate>",
      "relation_object": "<optional relation object text>",
      "fact_key": "<stable normalized dedup key>",
      "confidence": <0.0-1.0>,
      "importance": <0.0-1.0>
    }}
  ]
}}
3) If nothing is worth remembering, return: {{"candidates":[]}}.
4) Keep facts compact and language-preserving (Chinese in, Chinese out; English in, English out).
5) Ignore transient chatter (greetings, small talk, one-off ephemeral details).
6) Avoid fabrications. Use only information explicitly implied by the conversation.

Type guidance / 类型说明:
- profile: stable identity facts (name, role, background, location baseline)
- preference: recurring style choices (language/tone/tool preferences)
- task_state: ongoing project/task progress and milestones
- constraint: hard requirements, forbidden actions, security/compliance limits
- episode: meaningful historical events worth future recall
- subject_key: concept identity for temporal supersession.
  Example: "current_city". For "现在住在上海"/"现在住在北京", keep the same subject_key.

Conversation segment:
---
{conversation}
---

Return JSON ONLY."""


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


def _extract_json_substring(raw_text: str) -> str | None:
    """Extract first balanced JSON object/array from arbitrary text."""
    if not raw_text:
        return None
    start = -1
    opener = ""
    for idx, ch in enumerate(raw_text):
        if ch in ("{", "["):
            start = idx
            opener = ch
            break
    if start < 0:
        return None

    closer = "}" if opener == "{" else "]"
    depth = 0
    in_string = False
    escape = False
    for idx in range(start, len(raw_text)):
        ch = raw_text[idx]
        if in_string:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == '"':
                in_string = False
            continue

        if ch == '"':
            in_string = True
            continue
        if ch == opener:
            depth += 1
        elif ch == closer:
            depth -= 1
            if depth == 0:
                return raw_text[start:idx + 1]
    return None


def _parse_candidates_payload(raw_text: str):
    """Parse model output into list payload with robust fallbacks."""
    text = str(raw_text or "").strip()
    if not text:
        return []

    # 1) Direct JSON parse.
    try:
        return json.loads(text)
    except Exception:
        pass

    # 2) Strip fenced block then parse.
    fence_match = re.search(r"```(?:json)?\s*(.*?)\s*```", text, re.DOTALL | re.IGNORECASE)
    if fence_match:
        fenced = fence_match.group(1).strip()
        try:
            return json.loads(fenced)
        except Exception:
            pass

    # 3) Balanced object/array extraction.
    payload = _extract_json_substring(text)
    if payload:
        try:
            return json.loads(payload)
        except Exception:
            return []

    return []


async def extract_candidates(
    provider: Provider,
    messages: list[dict],
    max_candidates: int = 10,
    session_id: str | None = None,
) -> list[dict]:
    """Extract memory candidates from conversation messages using an LLM.

    Returns a list of candidate dicts with keys:
        type, fact, subject_key, relation_predicate, relation_object,
        fact_key, confidence, importance

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
    parsed_payload = _parse_candidates_payload(raw_text)
    if isinstance(parsed_payload, list):
        candidates = parsed_payload
    elif isinstance(parsed_payload, dict):
        raw_candidates = (
            parsed_payload.get("candidates")
            or parsed_payload.get("facts")
            or parsed_payload.get("items")
        )
        candidates = raw_candidates if isinstance(raw_candidates, list) else []
    else:
        candidates = []

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
        subject_key = cleaned.get("subject_key", "")
        relation_predicate = cleaned.get("relation_predicate", "")
        relation_object = cleaned.get("relation_object", "")
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
        normalized_subject_key = _normalize_fact_key(subject_key or "") or fact_key

        try:
            valid.append({
                "type": mem_type,
                "fact": str(fact).strip()[:500],
                "subject_key": normalized_subject_key,
                "relation_predicate": (
                    relation_predicate.strip()[:64]
                    if isinstance(relation_predicate, str)
                    else ""
                ),
                "relation_object": (
                    relation_object.strip()[:500]
                    if isinstance(relation_object, str)
                    else ""
                ),
                "fact_key": fact_key,
                "confidence": max(0.0, min(1.0, float(confidence))),
                "importance": max(0.0, min(1.0, float(importance))),
            })
        except (ValueError, TypeError) as e:
            logger.debug("LTM candidate field conversion error: %s", e)
            continue

    return valid

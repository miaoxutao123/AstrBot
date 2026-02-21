"""Scope resolution helpers for long-term memory."""

from typing import Any

from astrbot.core.platform.message_type import MessageType


def _safe_text(value: Any) -> str:
    return str(value).strip() if value is not None else ""


def _normalize_scope_id(scope_id: str) -> str:
    """Scope ID is stored in DB as varchar(255)."""
    sid = _safe_text(scope_id) or "unknown"
    return sid[:255]


def _get_ltm_identity_cfg(ltm_cfg: dict | None) -> dict:
    if not isinstance(ltm_cfg, dict):
        return {}
    identity_cfg = ltm_cfg.get("identity", {})
    return identity_cfg if isinstance(identity_cfg, dict) else {}


def _get_platform_sender_key(event) -> str | None:
    try:
        platform_id = _safe_text(event.get_platform_id()) if hasattr(event, "get_platform_id") else ""
    except Exception:
        platform_id = ""
    try:
        sender_id = _safe_text(event.get_sender_id()) if hasattr(event, "get_sender_id") else ""
    except Exception:
        sender_id = ""
    if platform_id and sender_id:
        return f"{platform_id}:{sender_id}"
    return None


def _resolve_user_scope_id(event, ltm_cfg: dict | None = None) -> str:
    """Resolve canonical user scope_id with optional cross-platform aliases."""
    identity_cfg = _get_ltm_identity_cfg(ltm_cfg)

    # Highest priority: explicit identity injected by plugin/hook.
    try:
        if hasattr(event, "get_extra"):
            explicit_id = _safe_text(event.get_extra("ltm_user_scope_id"))
            if explicit_id:
                return _normalize_scope_id(explicit_id)
    except Exception:
        pass

    platform_sender_key = _get_platform_sender_key(event)
    sender_id = ""
    try:
        if hasattr(event, "get_sender_id"):
            sender_id = _safe_text(event.get_sender_id())
    except Exception:
        sender_id = ""

    # Configurable cross-platform aliases:
    # { "qq:12345": "user_todd", "discord:abc": "user_todd" }
    aliases = identity_cfg.get("cross_platform_aliases", {})
    if isinstance(aliases, dict):
        if platform_sender_key and platform_sender_key in aliases:
            alias_id = _safe_text(aliases.get(platform_sender_key))
            if alias_id:
                return _normalize_scope_id(alias_id)
        if sender_id and sender_id in aliases:
            alias_id = _safe_text(aliases.get(sender_id))
            if alias_id:
                return _normalize_scope_id(alias_id)

    strategy = _safe_text(identity_cfg.get("user_scope_strategy", "unified_msg_origin")).lower()
    if strategy == "sender_id" and sender_id:
        return _normalize_scope_id(sender_id)
    if strategy == "platform_sender_id" and platform_sender_key:
        return _normalize_scope_id(platform_sender_key)
    if strategy == "session_id":
        session_id = _safe_text(getattr(event, "session_id", ""))
        if session_id:
            return _normalize_scope_id(session_id)

    return _normalize_scope_id(getattr(event, "unified_msg_origin", "unknown"))


def resolve_ltm_scope(event, ltm_cfg: dict | None = None) -> tuple[str, str]:
    """Determine LTM write scope and scope_id from a message event."""
    try:
        msg_type = event.get_message_type()
        if msg_type == MessageType.GROUP_MESSAGE:
            return "group", _normalize_scope_id(event.unified_msg_origin)
        return "user", _resolve_user_scope_id(event, ltm_cfg=ltm_cfg)
    except Exception:
        return "user", _resolve_user_scope_id(event, ltm_cfg=ltm_cfg)


def resolve_ltm_read_targets(
    event,
    ltm_cfg: dict | None = None,
) -> tuple[str, str, list[tuple[str, str]]]:
    """Resolve primary + fallback scopes for retrieval."""
    scope, scope_id = resolve_ltm_scope(event, ltm_cfg=ltm_cfg)
    additional_scopes: list[tuple[str, str]] = []

    if scope != "user":
        return scope, scope_id, additional_scopes

    identity_cfg = _get_ltm_identity_cfg(ltm_cfg)
    include_legacy_umo = bool(identity_cfg.get("include_legacy_umo_on_read", True))
    if include_legacy_umo:
        legacy_umo = _normalize_scope_id(getattr(event, "unified_msg_origin", ""))
        if legacy_umo and legacy_umo != scope_id:
            additional_scopes.append(("user", legacy_umo))

    return scope, scope_id, additional_scopes

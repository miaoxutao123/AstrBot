"""Capability metadata used by agent-facing discovery.

The Core intentionally treats capabilities as opaque strings.  This catalog is
the profile-level vocabulary that lets public clients derive direction without
guessing from capability names.
"""

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class CapabilityTrait:
    """Stable metadata for one public capability vocabulary entry."""

    name: str
    direction: str
    family: str
    required_scopes: tuple[str, ...]


IM_MESSAGE_RECEIVE = "im.message.receive"
IM_REACTION_RECEIVE = "im.reaction.receive"

CAPABILITY_TRAITS: dict[str, CapabilityTrait] = {
    IM_MESSAGE_RECEIVE: CapabilityTrait(
        IM_MESSAGE_RECEIVE, "inbound", "im", ("events:read",)
    ),
    IM_REACTION_RECEIVE: CapabilityTrait(
        IM_REACTION_RECEIVE, "inbound", "im", ("events:read",)
    ),
    "im.message.send": CapabilityTrait(
        "im.message.send", "outbound", "im", ("commands:send",)
    ),
    "im.message.reply": CapabilityTrait(
        "im.message.reply", "outbound", "im", ("commands:send",)
    ),
    "im.message.edit": CapabilityTrait(
        "im.message.edit", "outbound", "im", ("commands:send",)
    ),
    "im.message.delete": CapabilityTrait(
        "im.message.delete", "outbound", "im", ("commands:send",)
    ),
    "im.reaction.add": CapabilityTrait(
        "im.reaction.add", "outbound", "im", ("commands:send",)
    ),
    "im.reaction.remove": CapabilityTrait(
        "im.reaction.remove", "outbound", "im", ("commands:send",)
    ),
    "im.typing.set": CapabilityTrait(
        "im.typing.set", "outbound", "im", ("commands:send",)
    ),
    "robot.motion.command": CapabilityTrait(
        "robot.motion.command",
        "outbound",
        "robotics",
        ("commands:send", "hardware:control"),
    ),
}


def capability_trait(name: str, family: str) -> CapabilityTrait | None:
    """Return known metadata, without interpreting unknown capability strings."""
    trait = CAPABILITY_TRAITS.get(name)
    return trait if trait is not None and trait.family == family else None


def direction_for(capabilities: list[CapabilityTrait | None]) -> str:
    """Derive direction solely from known capability traits."""
    directions = {trait.direction for trait in capabilities if trait is not None}
    if directions == {"inbound", "outbound"}:
        return "bidirectional"
    if "inbound" in directions:
        return "inbound"
    if "outbound" in directions:
        return "outbound"
    return "none"

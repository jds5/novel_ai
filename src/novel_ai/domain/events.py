from __future__ import annotations

from dataclasses import dataclass, field
from uuid import UUID, uuid4

PROJECTOR_VERSION = 1


class ProjectionError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class ItemTransferred:
    work_id: UUID
    item_id: UUID
    from_owner_id: UUID | None
    to_owner_id: UUID
    sequence: int
    event_id: UUID = field(default_factory=uuid4)

    def __post_init__(self) -> None:
        if self.sequence < 1:
            raise ValueError("sequence must be positive")
        if self.from_owner_id == self.to_owner_id:
            raise ValueError("an item transfer must change owner")


@dataclass(frozen=True, slots=True)
class ItemOwnershipState:
    owner_by_item: dict[UUID, UUID] = field(default_factory=dict)
    last_sequence: int = 0


def project_item_transfer(state: ItemOwnershipState, event: ItemTransferred) -> ItemOwnershipState:
    """Apply a versioned hard-state event without mutating the prior projection."""

    if event.sequence != state.last_sequence + 1:
        raise ProjectionError(
            f"expected event sequence {state.last_sequence + 1}, got {event.sequence}"
        )
    current_owner = state.owner_by_item.get(event.item_id)
    if current_owner != event.from_owner_id:
        raise ProjectionError(
            f"item owner mismatch: expected {event.from_owner_id}, found {current_owner}"
        )
    projected = dict(state.owner_by_item)
    projected[event.item_id] = event.to_owner_id
    return ItemOwnershipState(owner_by_item=projected, last_sequence=event.sequence)

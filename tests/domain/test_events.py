from uuid import uuid4

import pytest

from novel_ai.domain.events import (
    ItemOwnershipState,
    ItemTransferred,
    ProjectionError,
    project_item_transfer,
)


def test_item_transfer_projector_is_deterministic_and_non_mutating() -> None:
    work_id, item_id, new_owner = uuid4(), uuid4(), uuid4()
    initial = ItemOwnershipState()
    event = ItemTransferred(
        work_id=work_id,
        item_id=item_id,
        from_owner_id=None,
        to_owner_id=new_owner,
        sequence=1,
    )

    projected = project_item_transfer(initial, event)

    assert initial.owner_by_item == {}
    assert projected.owner_by_item[item_id] == new_owner
    assert projected.last_sequence == 1


def test_item_transfer_rejects_an_incorrect_prior_owner() -> None:
    current_owner, claimed_owner = uuid4(), uuid4()
    item_id = uuid4()
    state = ItemOwnershipState(owner_by_item={item_id: current_owner})
    event = ItemTransferred(
        work_id=uuid4(),
        item_id=item_id,
        from_owner_id=claimed_owner,
        to_owner_id=uuid4(),
        sequence=1,
    )

    with pytest.raises(ProjectionError, match="owner mismatch"):
        project_item_transfer(state, event)

from __future__ import annotations

import argparse
import asyncio
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from novel_ai.application.generation import execute_generation_run
from novel_ai.application.planning import WORK_PLANNING_KIND, execute_work_planning_run
from novel_ai.db.models import WorkflowRun
from novel_ai.db.session import session_factory


async def execute_workflow_run(run_id: UUID) -> None:
    async with session_factory() as session:
        run = await _load_run(session, run_id)
        if run is None:
            return
        kind = run.kind
    if kind == WORK_PLANNING_KIND:
        await execute_work_planning_run(run_id)
    else:
        await execute_generation_run(run_id)


async def _load_run(session: AsyncSession, run_id: UUID) -> WorkflowRun | None:
    return await session.get(WorkflowRun, run_id)


def run() -> None:
    parser = argparse.ArgumentParser(description="Execute one persisted Novel AI workflow run.")
    parser.add_argument("run_id", type=UUID)
    arguments = parser.parse_args()
    asyncio.run(execute_workflow_run(arguments.run_id))


if __name__ == "__main__":
    run()

"""HTTP API of the Orchestrator.

Instructions arrive from the Conversation Engine (B) with an instruction_key; caller identity is
bound in Step 9, so until then this API must only be reachable from inside Layer A.
"""

from typing import Literal
from uuid import UUID

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse

from dyson_contracts.common import Component, Contract, NonEmptyStr
from dyson_contracts.tasks import TaskTransition

from .orchestrator import Orchestrator, OrchestratorError, TaskView
from .ports import TaskPlan


class SubmitIn(Contract):
    instruction_key: NonEmptyStr
    instruction: NonEmptyStr
    plan: TaskPlan


class ReviewIn(Contract):
    resume: bool
    by: Literal[Component.HUMAN_REVIEWER, Component.FOUNDER]


def create_app(orch: Orchestrator) -> FastAPI:
    app = FastAPI(title="Dyson Orchestrator (D)")

    @app.exception_handler(OrchestratorError)
    async def _refused(_: Request, exc: OrchestratorError):
        return JSONResponse(status_code=409, content={"detail": str(exc)})

    @app.post("/tasks", status_code=201)
    def submit(body: SubmitIn) -> TaskView:
        return orch.submit(body.instruction_key, body.instruction, body.plan)

    @app.get("/tasks/{task_id}")
    def get(task_id: UUID) -> TaskView:
        try:
            return orch.get(task_id)
        except OrchestratorError:
            raise HTTPException(404, "unknown task") from None

    @app.get("/tasks/{task_id}/history")
    def history(task_id: UUID) -> list[TaskTransition]:
        return orch.history(task_id)

    @app.post("/tasks/{task_id}/review")
    def review(task_id: UUID, body: ReviewIn) -> TaskView:
        return orch.review(task_id, body.resume, body.by)

    return app

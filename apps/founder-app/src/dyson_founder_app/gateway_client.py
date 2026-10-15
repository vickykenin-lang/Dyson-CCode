"""The app's only connection: the Entry Gateway's HTTP API."""

from typing import Any
from uuid import UUID

import httpx

from dyson_contracts.interface import TaskStatusUpdate


class NotLoggedIn(Exception):
    pass


class GatewayClient:
    def __init__(self, http: httpx.Client):
        self._http = http

    def _call(self, method: str, path: str, token: str | None, **kw: Any) -> httpx.Response:
        headers = {"Authorization": f"Bearer {token}"} if token else {}
        r = self._http.request(method, path, headers=headers, **kw)
        if r.status_code == 401:
            raise NotLoggedIn(r.json().get("detail", "log in"))
        r.raise_for_status()
        return r

    def login(self, username: str, secret: str) -> str:
        return self._call(
            "POST", "/session", None, json={"username": username, "secret": secret}
        ).json()["token"]

    def logout(self, token: str) -> None:
        self._call("DELETE", "/session", token)

    def send(
        self,
        token: str,
        thread_id: UUID,
        text: str,
        *,
        voice: bool = False,
        uncertain: bool = False,
    ) -> dict[str, Any]:
        body = {
            "thread_id": str(thread_id),
            "text": text,
            "modality": "voice" if voice else "text",
            "transcription_uncertain": uncertain,
        }
        return self._call("POST", "/messages", token, json=body).json()

    def thread(self, token: str, thread_id: UUID) -> list[dict[str, Any]]:
        return self._call("GET", f"/threads/{thread_id}", token).json()

    def tasks(self, token: str, thread_id: UUID) -> list[TaskStatusUpdate]:
        rows = self._call("GET", f"/threads/{thread_id}/tasks", token).json()
        return [TaskStatusUpdate.model_validate(r) for r in rows]

    def task(self, token: str, task_id: UUID) -> TaskStatusUpdate:
        return TaskStatusUpdate.model_validate(self._call("GET", f"/tasks/{task_id}", token).json())

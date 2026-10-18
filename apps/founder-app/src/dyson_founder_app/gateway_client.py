"""The app's only connection: the Entry Gateway's HTTP API."""

import base64
from datetime import date
from typing import Any
from uuid import UUID

import httpx

from dyson_contracts.interface import TaskStatusUpdate


class NotLoggedIn(Exception):
    pass


class Refused(Exception):
    """The Gateway said no, with its reason."""


class GatewayClient:
    def __init__(self, http: httpx.Client):
        self._http = http

    def _call(self, method: str, path: str, token: str | None, **kw: Any) -> httpx.Response:
        headers = {"Authorization": f"Bearer {token}"} if token else {}
        r = self._http.request(method, path, headers=headers, **kw)
        if r.status_code == 401:
            raise NotLoggedIn(r.json().get("detail", "log in"))
        if r.status_code in (413, 422, 503):
            raise Refused(r.json().get("detail", f"refused ({r.status_code})"))
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
        message_id: UUID | None = None,
    ) -> dict[str, Any]:
        body = {
            "thread_id": str(thread_id),
            "text": text,
            "modality": "voice" if voice else "text",
            "transcription_uncertain": uncertain,
            "client_message_id": str(message_id) if message_id else None,
        }
        return self._call("POST", "/messages", token, json=body).json()

    def thread(self, token: str, thread_id: UUID) -> list[dict[str, Any]]:
        return self._call("GET", f"/threads/{thread_id}", token).json()

    def tasks(self, token: str, thread_id: UUID) -> list[TaskStatusUpdate]:
        rows = self._call("GET", f"/threads/{thread_id}/tasks", token).json()
        return [TaskStatusUpdate.model_validate(r) for r in rows]

    def task(self, token: str, task_id: UUID) -> TaskStatusUpdate:
        return TaskStatusUpdate.model_validate(self._call("GET", f"/tasks/{task_id}", token).json())

    def notices(self, token: str) -> list[dict[str, Any]]:
        return self._call("GET", "/notices", token).json()

    def upload_statement(self, token: str, filename: str, start: date, end: date,
                         content: bytes) -> int:  # fmt: skip
        body = {"filename": filename, "period_start": start.isoformat(),
                "period_end": end.isoformat(),
                "content_base64": base64.b64encode(content).decode()}  # fmt: skip
        return self._call("POST", "/statements", token, json=body).json()["lines_kept"]

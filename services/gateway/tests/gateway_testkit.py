"""Fake backend for the Gateway tests. Step 9 replaces it with B, D and I."""

from datetime import UTC, datetime, timedelta
from uuid import uuid4

from dyson_contracts.interface import Language, TaskStatusUpdate
from dyson_contracts.tasks import TaskState
from dyson_gateway.ports import ConversationReply, ReplyKind, ThreadMessage

NOW = datetime(2026, 10, 15, 12, 0, tzinfo=UTC)
PASSWORD = "correct horse battery staple"


class Clock:
    def __init__(self):
        self.now = NOW

    def __call__(self):
        return self.now

    def advance(self, **kw):
        self.now += timedelta(**kw)


class FakeBackend:
    """B, D and I as one fake. Every message becomes a task unless it asks a question."""

    def __init__(self):
        self.messages = []
        self.updates: dict = {}
        self.thread_of: dict = {}
        self.threads: dict = {}
        self.next_state = TaskState.ACCEPTED

    def handle(self, message):
        self.messages.append(message)
        self.threads.setdefault(message.thread_id, []).append(
            ThreadMessage(role="user", content=message.text, modality=message.modality.value)
        )
        if message.text.endswith("?"):
            reply = ConversationReply(kind=ReplyKind.ANSWER, text="An answer.",
                                      language=Language.ENGLISH)  # fmt: skip
        else:
            task_id = uuid4()
            self.updates[task_id] = TaskStatusUpdate(task_id=task_id, state=self.next_state, at=NOW)
            self.thread_of[task_id] = message.thread_id
            reply = ConversationReply(kind=ReplyKind.ACCEPTED, text="Accepted, not done yet.",
                                      language=Language.ENGLISH, task_id=task_id,
                                      task_state=self.next_state)  # fmt: skip
        self.threads[message.thread_id].append(ThreadMessage(role="assistant", content=reply.text))
        return reply

    def task(self, task_id):
        return self.updates.get(task_id)

    def tasks(self, thread_id):
        return [u for t, u in self.updates.items() if self.thread_of[t] == thread_id]

    def thread(self, thread_id, limit):
        return self.threads.get(thread_id, [])[-limit:]


class Audit(list):
    def record(self, event, detail):
        self.append((event, detail))

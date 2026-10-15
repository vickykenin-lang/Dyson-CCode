"""App tests run through the real Entry Gateway, with B, D and I faked behind it."""

from datetime import UTC, datetime, timedelta
from uuid import uuid4

from dyson_contracts.interface import Language, TaskStatusUpdate
from dyson_contracts.tasks import TaskState
from dyson_founder_app.voice import Transcript
from dyson_gateway.ports import ConversationReply, ReplyKind, ThreadMessage

NOW = datetime(2026, 10, 15, 12, 0, tzinfo=UTC)
PASSWORD = "correct horse battery staple"


class Backend:
    def __init__(self):
        self.messages, self.updates, self.thread_of, self.threads = [], {}, {}, {}
        self.next_state = TaskState.ACCEPTED

    def handle(self, m):
        self.messages.append(m)
        self.threads.setdefault(m.thread_id, []).append(
            ThreadMessage(role="user", content=m.text, modality=m.modality.value)
        )
        if m.text.endswith("?"):
            reply = ConversationReply(kind=ReplyKind.ANSWER, text="Sales are up 4%.",
                                      language=Language.ENGLISH)  # fmt: skip
        else:
            tid = uuid4()
            self.updates[tid] = TaskStatusUpdate(task_id=tid, state=self.next_state, at=NOW)
            self.thread_of[tid] = m.thread_id
            reply = ConversationReply(kind=ReplyKind.ACCEPTED, text="I will report when verified.",
                                      language=Language.ENGLISH, task_id=tid,
                                      task_state=self.next_state)  # fmt: skip
        self.threads[m.thread_id].append(ThreadMessage(role="assistant", content=reply.text))
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


class ScriptedVoice:
    def __init__(self, text="Send the weekly report", uncertain=False):
        self.result = Transcript(text=text, uncertain=uncertain)

    def transcribe(self, audio, content_type):
        return self.result


def clock():
    return NOW


LIFETIME = timedelta(hours=12)

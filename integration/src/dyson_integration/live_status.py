"""Gate 8: the Founder's live dashboard, block by block as in the master architecture.

Every block reads its own component's store with that component's own database role, read
only, and reports a status from what actually happened: `live` (activity in the last 5
minutes), `ok` (up, quiet), `attention` (something waits on the Founder or is held),
`stopped`, or `off` (not connected or not approved yet). Nothing here can act (LA-DASH-02).
"""

from collections.abc import Callable
from datetime import datetime, timedelta
from typing import Any

import psycopg
from psycopg.rows import dict_row

LIVE_WINDOW = timedelta(minutes=5)
DAY = timedelta(hours=24)


def _iso(at: datetime | None) -> str | None:
    return at.isoformat() if at else None


_FOUNDER_MSGS = (
    "SELECT sent_at AS at FROM memory.messages WHERE participant = 'founder' AND sent_at >= %s"
)
_REPLIES = "SELECT sent_at AS at FROM memory.messages WHERE participant = 'dyson' AND sent_at >= %s"
_MESSAGES = [("memory", _FOUNDER_MSGS, 1), ("memory", _REPLIES, -1)]


def _gov(*types: str) -> str:
    names = ", ".join(f"'{t}'" for t in types)
    return f"SELECT at FROM governance.events WHERE type IN ({names}) AND at >= %s"


# The wires of the master architecture: (from, to, kind, label, sources). A source is
# (component store, SQL giving `at` for records since %s, direction: 1 from->to, -1 back).
LINKS = [
    ("founder", "app", "req", "Messages", _MESSAGES),
    (
        "app",
        "gateway",
        "req",
        "Messages and logins",
        [
            *_MESSAGES,
            ("memory", "SELECT at FROM memory.audit_log WHERE summary = 'login' AND at >= %s", 1),
        ],
    ),
    ("gateway", "B", "req", "Messages", _MESSAGES),
    (
        "B",
        "C",
        "req",
        "Model calls",
        [
            (
                "intelligence",
                "SELECT at FROM intelligence.calls WHERE status <> 'reserved' AND at >= %s",
                1,
            )
        ],
    ),
    (
        "B",
        "D",
        "req",
        "New tasks",
        [
            (
                "orchestrator",
                "SELECT at FROM orchestrator.transitions WHERE from_state IS NULL AND at >= %s",
                1,
            )
        ],
    ),
    (
        "D",
        "G",
        "req",
        "Tool calls",
        [
            (
                "toolhub",
                "SELECT decided_at AS at FROM toolhub.decisions"
                " WHERE caller = 'D' AND decided_at >= %s",
                1,
            )
        ],
    ),
    (
        "G",
        "T0",
        "req",
        "Receptor actions",
        [
            (
                "toolhub",
                "SELECT decided_at AS at FROM toolhub.decisions WHERE allowed"
                " AND request->>'tool_id' LIKE 't0.%%' AND decided_at >= %s",
                1,
            )
        ],
    ),
    (
        "G",
        "hermes",
        "req",
        "Research jobs",
        [
            (
                "toolhub",
                "SELECT decided_at AS at FROM toolhub.decisions WHERE allowed"
                " AND request->>'tool_id' = 'hermes.research' AND decided_at >= %s",
                1,
            )
        ],
    ),
    (
        "D",
        "F",
        "res",
        "QA verdicts",
        [("assurance", "SELECT at FROM assurance.qa_verdicts WHERE at >= %s", -1)],
    ),
    (
        "F",
        "I",
        "mem",
        "Evidence",
        [
            (
                "memory",
                "SELECT recorded_at AS at FROM memory.evidence"
                " WHERE recorded_by = 'F' AND recorded_at >= %s",
                1,
            )
        ],
    ),
    (
        "D",
        "I",
        "mem",
        "Audit trail",
        [("memory", "SELECT at FROM memory.audit_log WHERE actor = 'D' AND at >= %s", 1)],
    ),
    (
        "T0",
        "E",
        "mon",
        "Health reports",
        [("assurance", "SELECT at FROM assurance.health WHERE subject_id = 'T0' AND at >= %s", 1)],
    ),
    (
        "E",
        "A",
        "mon",
        "Escalations",
        [("assurance", "SELECT at FROM assurance.escalations WHERE at >= %s", 1)],
    ),
    (
        "founder",
        "dfc",
        "stop",
        "Your decisions",
        [
            (
                "memory",
                "SELECT at FROM memory.audit_log"
                " WHERE actor = 'direct_founder_controls' AND at >= %s",
                1,
            )
        ],
    ),
    (
        "dfc",
        "A",
        "stop",
        "Decisions and controls",
        [("governance", _gov("decision_recorded", "control_applied"), 1)],
    ),
    ("A", "D", "stop", "Approvals used", [("governance", _gov("approval_consumed"), 1)]),
    (
        "A",
        "G",
        "stop",
        "Kill switches",
        [("toolhub", "SELECT at FROM toolhub.switches WHERE at >= %s", 1)],
    ),
    (
        "A",
        "T0",
        "stop",
        "Controls",
        [("governance", _gov("control_applied", "receptor_status_changed"), 1)],
    ),
    (
        "vault",
        "H",
        "fin",
        "Statements",
        [
            (
                "assurance",
                "SELECT uploaded_at AS at FROM assurance.statement_uploads WHERE uploaded_at >= %s",
                1,
            )
        ],
    ),
    (
        "T0",
        "H",
        "fin",
        "Revenue reports",
        [
            (
                "assurance",
                "SELECT reported_at AS at FROM assurance.revenue_reports WHERE reported_at >= %s",
                1,
            )
        ],
    ),
]


class LiveStatus:
    def __init__(
        self,
        dsns: dict[str, str],
        core,
        router,
        memory,
        clock: Callable[[], datetime],
        probes: dict[str, Callable[[], Any]],
    ):
        self._dsns, self._core, self._router, self._memory = dsns, core, router, memory
        self._clock, self._probes = clock, probes

    # --- reading -------------------------------------------------------------------------
    def _rows(self, component: str, sql: str, params: list | None = None) -> list[dict]:
        with psycopg.connect(self._dsns[component], row_factory=dict_row) as c:
            if component == "memory":
                c.execute("SELECT set_config('dyson.scope', 'core', true)")
            return c.execute(sql, params or []).fetchall()

    def _one(self, component: str, sql: str, params: list | None = None) -> dict:
        rows = self._rows(component, sql, params)
        return rows[0] if rows else {}

    def _probe(self, name: str):
        try:
            return True, self._probes[name]()
        except Exception as exc:  # down is shown, never hidden
            return False, type(exc).__name__

    def _status(self, last: datetime | None, now: datetime, quiet: str = "ok") -> str:
        return "live" if last is not None and now - last <= LIVE_WINDOW else quiet

    # --- the map -------------------------------------------------------------------------
    def snapshot(self) -> dict:
        now = self._clock()
        since = now - DAY
        blocks: dict[str, dict] = {}

        def block(key, title, status, metrics, last=None, note=""):
            blocks[key] = {
                "title": title,
                "status": status,
                "last": _iso(last),
                "note": note,
                "metrics": [[k, str(v)] for k, v in metrics],
            }

        def guard(key, title, fn):
            try:
                fn()
            except Exception as exc:  # one block failing never hides the others
                block(
                    key, title, "attention", [], note=f"status unavailable ({type(exc).__name__})"
                )

        mode = self._core.effective_mode(None).value
        survival = self._core.survival_mode()

        def founder():
            last = self._memory.last_founder_presence()
            st = "attention" if survival else self._status(last, now, "ok" if last else "off")
            note = "Survival Mode: not seen for 3 days" if survival else ""
            hours = int(self._core.policy.control("AMD-12", "presence_timeout_hours"))
            block(
                "founder", "Founder", st, [("Survival Mode after", f"{hours} h away")], last, note
            )

        def audit_count(*summaries):
            return self._one(
                "memory",
                "SELECT count(*) AS n, max(at) AS last FROM memory.audit_log"
                " WHERE summary = ANY(%s) AND at >= %s",
                [list(summaries), since],
            )

        def app():
            m = self._one(
                "memory",
                "SELECT count(*) AS n, max(sent_at) AS last FROM memory.messages"
                " WHERE participant = 'founder' AND sent_at >= %s",
                [since],
            )
            block(
                "app",
                "Dyson App",
                self._status(m["last"], now),
                [("Your messages (24 h)", m["n"]), ("Voice", "deferred (D-016)")],
                m["last"],
            )

        def gateway():
            logins = audit_count("login")
            refused = audit_count("login_failed", "login_locked_out", "rate_limited")
            block(
                "gateway",
                "Entry Gateway",
                self._status(logins["last"], now),
                [("Logins (24 h)", logins["n"]), ("Refused (24 h)", refused["n"])],
                logins["last"],
            )

        def dfc():
            up, info = self._probe("controls")
            acts = audit_count("decision", "control", "resume_requested")
            enrolled = info.get("enrolled", "?") if up and isinstance(info, dict) else "?"
            st = self._status(acts["last"], now) if up else "stopped"
            block(
                "dfc",
                "Direct Founder Controls",
                st,
                [
                    ("Process", "up" if up else f"down ({info})"),
                    ("Passkeys", enrolled),
                    ("Your actions (24 h)", acts["n"]),
                    ("Control state", mode),
                ],
                acts["last"],
            )

        def vault():
            u = self._one(
                "assurance",
                "SELECT count(*) AS n, max(uploaded_at) AS last FROM assurance.statement_uploads",
            )
            block(
                "vault",
                "Founder Private Bank Vault",
                self._status(u["last"], now, "ok" if u["n"] else "off"),
                [("Statements uploaded", u["n"]), ("Bank API", "none, upload only")],
                u["last"],
                "" if u["n"] else "no statement uploaded yet",
            )

        def governance():
            open_ = sum(
                1
                for p in self._core.sync().proposals.values()
                if p.status.value == "open"
                and (p.request.expires_at is None or now <= p.request.expires_at)
            )
            e = self._one(
                "governance",
                "SELECT count(*) FILTER (WHERE at >= %s) AS n, max(at) AS last"
                " FROM governance.events",
                [since],
            )
            st = (
                "stopped"
                if mode == "stopped"
                else "attention"
                if mode == "paused" or survival or open_
                else self._status(e["last"], now)
            )
            block(
                "A",
                "A. Governance Core",
                st,
                [
                    ("Control", mode),
                    ("Survival Mode", "on" if survival else "off"),
                    ("Approvals waiting", open_),
                    ("Decisions logged (24 h)", e["n"]),
                ],
                e["last"],
            )

        def conversation():
            m = self._one(
                "memory",
                "SELECT count(*) AS n, max(sent_at) AS last FROM memory.messages"
                " WHERE participant = 'dyson' AND sent_at >= %s",
                [since],
            )
            block(
                "B",
                "B. Conversation Engine",
                self._status(m["last"], now),
                [("Replies (24 h)", m["n"])],
                m["last"],
            )

        def router():
            c = self._one(
                "intelligence",
                "SELECT count(*) FILTER (WHERE status = 'ok') AS ok,"
                " count(*) FILTER (WHERE status = 'failed') AS failed, max(at) AS last"
                " FROM intelligence.calls WHERE at >= %s AND status <> 'reserved'",
                [since],
            )
            from dyson_intelligence.conversation import TASK_CLASS

            route = self._router.route(TASK_CLASS)
            spent = self._router.spent_today(TASK_CLASS, "USD")
            block(
                "C",
                "C. Model Router",
                self._status(c["last"], now, "ok" if route else "off"),
                [
                    ("Model", ", ".join(route) or "none"),
                    ("Calls ok / failed (24 h)", f"{c['ok']} / {c['failed']}"),
                    ("Spent today", f"{spent} USD of 0.16"),
                ],
                c["last"],
            )

        def orchestrator():
            counts = {
                r["state"]: r["n"]
                for r in self._rows(
                    "orchestrator",
                    "SELECT state, count(*) AS n FROM orchestrator.tasks GROUP BY state",
                )
            }
            t = self._one(
                "orchestrator",
                "SELECT count(*) AS n, max(at) AS last"
                " FROM orchestrator.transitions WHERE at >= %s",
                [since],
            )
            active = sum(counts.get(s, 0) for s in ("accepted", "running", "approval-needed"))
            held = counts.get("held", 0)
            block(
                "D",
                "D. Orchestrator",
                "attention" if held else self._status(t["last"], now),
                [
                    ("Active now", active),
                    ("Held", held),
                    ("Done & verified (all time)", counts.get("completed-verified", 0)),
                    ("Steps (24 h)", t["n"]),
                ],
                t["last"],
            )

        def monitoring():
            h = self._rows(
                "assurance",
                "SELECT DISTINCT ON (subject_id) subject_id, status, at"
                " FROM assurance.health ORDER BY subject_id, seq DESC",
            )
            bad = [x["subject_id"] for x in h if x["status"] != "healthy"]
            last = max((x["at"] for x in h), default=None)
            a = self._one(
                "assurance",
                "SELECT count(*) AS n FROM assurance.escalations WHERE at >= %s",
                [since],
            )
            block(
                "E",
                "E. Monitoring & Health",
                "attention" if bad else self._status(last, now),
                [
                    ("Watched", len(h)),
                    ("Not healthy", ", ".join(bad) or "none"),
                    ("Escalations (24 h)", a["n"]),
                ],
                last,
            )

        def hermes():
            up, info = self._probe("hermes")
            j = self._one(
                "toolhub",
                "SELECT count(*) AS n, max(decided_at) AS last FROM toolhub.decisions"
                " WHERE request->>'tool_id' = 'hermes.research' AND decided_at >= %s",
                [since],
            )
            block(
                "hermes",
                "Isolated Hermes Runtime",
                self._status(j["last"], now) if up else "stopped",
                [
                    ("Container", "up, no internet" if up else f"down ({info})"),
                    ("Research jobs (24 h)", j["n"]),
                ],
                j["last"],
            )

        def qa():
            v = self._one(
                "assurance",
                "SELECT count(*) FILTER (WHERE technical_success AND fit_for_purpose) AS ok,"
                " count(*) FILTER (WHERE NOT (technical_success AND fit_for_purpose)) AS bad,"
                " max(at) AS last FROM assurance.qa_verdicts",
            )
            block(
                "F",
                "F. QA/QC Controller",
                self._status(v["last"], now),
                [("Passed", v["ok"]), ("Failed", v["bad"])],
                v["last"],
            )

        def toolhub():
            d = self._one(
                "toolhub",
                "SELECT count(*) FILTER (WHERE allowed) AS ok,"
                " count(*) FILTER (WHERE NOT allowed) AS denied, max(decided_at) AS last"
                " FROM toolhub.decisions WHERE decided_at >= %s",
                [since],
            )
            killed = self._rows(
                "toolhub",
                "SELECT DISTINCT ON (target_id) target_id, killed"
                " FROM toolhub.switches ORDER BY target_id, seq DESC",
            )
            off = [k["target_id"] for k in killed if k["killed"]]
            block(
                "G",
                "G. Governed Tool Hub",
                "attention" if off else self._status(d["last"], now),
                [
                    ("Calls allowed / denied (24 h)", f"{d['ok']} / {d['denied']}"),
                    ("Kill switches on", ", ".join(off) or "none"),
                ],
                d["last"],
            )

        def finance():
            r = self._one(
                "assurance",
                "SELECT count(*) AS n, max(reported_at) AS last FROM assurance.revenue_reports",
            )
            m = self._one("assurance", "SELECT count(*) AS n FROM assurance.payment_matches")
            block(
                "H",
                "H. Financial Control",
                self._status(r["last"], now, "ok" if r["n"] else "off"),
                [("Revenue reports", r["n"]), ("Payments matched to bank", m["n"])],
                r["last"],
                "" if r["n"] else "no revenue yet (only T0 runs)",
            )

        def memory():
            m = self._one(
                "memory",
                "SELECT (SELECT count(*) FROM memory.messages) AS msgs,"
                " (SELECT count(*) FROM memory.evidence) AS ev,"
                " (SELECT count(*) FROM memory.audit_log) AS audit,"
                " (SELECT max(at) FROM memory.audit_log) AS last",
            )
            block(
                "I",
                "I. Memory & Evidence",
                self._status(m["last"], now),
                [
                    ("Messages", m["msgs"]),
                    ("Evidence records", m["ev"]),
                    ("Audit entries", m["audit"]),
                ],
                m["last"],
            )

        def receptors():
            h = self._one(
                "assurance",
                "SELECT status, at FROM assurance.health"
                " WHERE subject_id = 'T0' ORDER BY seq DESC LIMIT 1",
            )
            t0_mode = self._core.effective_mode("T0").value
            st = (
                "stopped"
                if t0_mode == "stopped"
                else "attention"
                if t0_mode == "paused" or h.get("status", "healthy") != "healthy"
                else self._status(h.get("at"), now)
            )
            block(
                "T0",
                "T0 (test Receptor)",
                st,
                [("Mode", t0_mode), ("Health", h.get("status", "no report yet"))],
                h.get("at"),
            )
            block(
                "R11",
                "R11 … Rn",
                "off",
                [("Receptors", "none approved yet")],
                note="only T0 runs until a real Receptor is approved (D-017)",
            )

        def external():
            block(
                "external",
                "External Business World",
                "off",
                [("Customers, ads, platforms", "not connected")],
                note="connects only through an approved Receptor",
            )

        block("J", "J. Founder Dashboard", "live", [("This page", "read only")], now)
        for key, title, fn in (
            ("founder", "Founder", founder),
            ("app", "Dyson App", app),
            ("gateway", "Entry Gateway", gateway),
            ("dfc", "Direct Founder Controls", dfc),
            ("vault", "Founder Private Bank Vault", vault),
            ("A", "A. Governance Core", governance),
            ("B", "B. Conversation Engine", conversation),
            ("C", "C. Model Router", router),
            ("D", "D. Orchestrator", orchestrator),
            ("E", "E. Monitoring & Health", monitoring),
            ("hermes", "Isolated Hermes Runtime", hermes),
            ("F", "F. QA/QC Controller", qa),
            ("G", "G. Governed Tool Hub", toolhub),
            ("H", "H. Financial Control", finance),
            ("I", "I. Memory & Evidence", memory),
            ("T0", "Receptors", receptors),
            ("external", "External Business World", external),
        ):
            guard(key, title, fn)
        return {
            "as_of": now.isoformat(),
            "blocks": blocks,
            "feed": self._feed(since),
            "links": self._links(since),
        }

    def _links(self, since: datetime) -> list[dict]:
        """Each wire of the architecture with what really crossed it in the last 24 hours.

        A wire's events are the records the receiving side keeps (a model call, a tool
        decision, a QA verdict, ...), so a light on a wire always stands for a real record.
        """
        wanted: dict[str, list[tuple[int, int, str]]] = {}
        for i, (_, _, _, _, sources) in enumerate(LINKS):
            for j, (component, sql, _) in enumerate(sources):
                wanted.setdefault(component, []).append((i, j, sql))
        found: dict[tuple[int, int], list[dict]] = {}
        for component, queries in wanted.items():
            try:
                with psycopg.connect(self._dsns[component], row_factory=dict_row) as c:
                    if component == "memory":
                        c.execute("SELECT set_config('dyson.scope', 'core', true)")
                    for i, j, sql in queries:
                        found[(i, j)] = c.execute(
                            f"SELECT at, count(*) OVER () AS n FROM ({sql}) s"
                            " ORDER BY at DESC LIMIT 30",
                            [since],
                        ).fetchall()
            except Exception:  # an unreachable store leaves its wires unknown, never invented
                for i, j, _ in queries:
                    found[(i, j)] = None
        links = []
        for i, (a, b, kind, label, sources) in enumerate(LINKS):
            rows = [found[(i, j)] for j in range(len(sources))]
            events = sorted(
                (
                    (r["at"], direction)
                    for got, (_, _, direction) in zip(rows, sources, strict=True)
                    for r in got or []
                ),
                reverse=True,
            )[:30]
            links.append(
                {
                    "a": a,
                    "b": b,
                    "kind": kind,
                    "label": label,
                    "known": all(r is not None for r in rows),
                    "n": sum(got[0]["n"] for got in rows if got),
                    "last": _iso(events[0][0]) if events else None,
                    "events": [[_iso(at), d] for at, d in events],
                }
            )
        return links

    def _feed(self, since: datetime) -> list[dict]:
        """What just happened, newest first, across D, G, C and A."""
        items = []
        for r in self._rows(
            "orchestrator",
            "SELECT task_id, from_state, to_state, at"
            " FROM orchestrator.transitions WHERE at >= %s"
            " ORDER BY seq DESC LIMIT 15",
            [since],
        ):
            items.append(
                (
                    r["at"],
                    "D",
                    f"Task {str(r['task_id'])[:8]}: {r['from_state'] or 'new'} → {r['to_state']}",
                )
            )
        for r in self._rows(
            "toolhub",
            "SELECT request->>'tool_id' AS tool, caller, allowed,"
            " decided_at FROM toolhub.decisions WHERE decided_at >= %s"
            " ORDER BY seq DESC LIMIT 15",
            [since],
        ):
            items.append(
                (
                    r["decided_at"],
                    "G",
                    f"{r['tool']} for {r['caller']}: {'allowed' if r['allowed'] else 'denied'}",
                )
            )
        for r in self._rows(
            "intelligence",
            "SELECT model_id, status, at FROM intelligence.calls"
            " WHERE at >= %s AND status <> 'reserved' ORDER BY seq DESC LIMIT 10",
            [since],
        ):
            items.append((r["at"], "C", f"Model {r['model_id']}: {r['status']}"))
        for r in self._rows(
            "governance",
            "SELECT type, at FROM governance.events WHERE at >= %s ORDER BY seq DESC LIMIT 10",
            [since],
        ):
            items.append((r["at"], "A", r["type"].replace("_", " ")))
        items.sort(key=lambda x: x[0], reverse=True)
        return [{"at": at.isoformat(), "block": b, "text": t} for at, b, t in items[:25]]

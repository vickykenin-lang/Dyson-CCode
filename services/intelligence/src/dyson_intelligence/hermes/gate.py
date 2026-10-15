"""Whether anything in Layer A may rely on Hermes for a class of task (LA-HER-07).

Hermes is a candidate, like any model: it must be admitted at A's integration gate and must
have a qualification on real tasks that meets the Founder's acceptance bar for that class.
Until both hold, its output may be studied but nothing may depend on it.
"""

from dyson_contracts.integrations import IntegrationRecord

from ..models import AcceptanceBar, Qualification

HERMES_INTEGRATION_ID = "hermes"


def may_rely_on_hermes(
    registry: dict[str, IntegrationRecord],
    bar: AcceptanceBar | None,
    qualification: Qualification | None,
) -> bool:
    record = registry.get(HERMES_INTEGRATION_ID)
    if record is None or not record.callable or bar is None or qualification is None:
        return False
    if (
        qualification.model_id != HERMES_INTEGRATION_ID
        or qualification.task_class != bar.task_class
    ):
        return False
    return (
        qualification.quality >= bar.min_quality
        and qualification.p95_latency_ms <= bar.max_latency_ms
    )

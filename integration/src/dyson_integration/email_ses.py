"""Email to the Founder's nominee through Amazon SES (AMD-12 v1.1). The only other AWS SDK use
besides C's Bedrock adapter: one sesv2 client, one call (send_email), one sender address. The
server role may send only from that address (infra/iam/dyson-server-policy.json). The nominee's
address is read from a file deploy.sh fills from /dyson/nominee; it is never logged or sent to a
model."""

import json
import time
from pathlib import Path
from typing import Any

REGION = "ap-southeast-2"
SENDER = "Dyson <dyson@designinfra.in>"
SUBJECT = "Dyson: the Founder has not been seen for 3 days"
CLIENT_MAX_AGE_S = 600  # the host refreshes short-lived role credentials


class SesNominee:
    def __init__(self, nominee_file: Path, outbox, client: Any = None):
        self._file, self._outbox = nominee_file, outbox
        self._fixed, self._client, self._made = client is not None, client, 0.0

    def _fresh_client(self) -> Any:
        if not self._fixed and time.monotonic() - self._made > CLIENT_MAX_AGE_S:
            import boto3

            self._client = boto3.session.Session().client("sesv2", region_name=REGION)
            self._made = time.monotonic()
        return self._client

    def notify(self, message: str, subject: str = SUBJECT) -> str:
        to = json.loads(self._file.read_text())["email"]
        try:
            out = self._fresh_client().send_email(
                FromEmailAddress=SENDER,
                Destination={"ToAddresses": [to]},
                Content={"Simple": {
                    "Subject": {"Data": subject},
                    "Body": {"Text": {"Data": message + "\n\n- Dyson (automatic notice)"}},
                }},
            )  # fmt: skip
            delivery = f"email sent ({out.get('MessageId', '?')})"
        except Exception as exc:  # recorded; the next notice interval tries again
            delivery = f"email failed: {type(exc).__name__}"
        self._outbox.notify(message, delivery)
        return delivery

"""Amazon Bedrock behind C (D-013): one provider adapter for every Bedrock text model.

It is called only by C's router, like the stand-in model. It uses the Converse API in
ap-southeast-2 with the server's short-lived role credentials; no key is kept here. A request
that asks for JSON gets the schema in the system prompt, and the first JSON object in the reply
is returned, so C and B never see code fences or reasoning text.
"""

import json
import re
from typing import Any

from dyson_intelligence.models import ModelRequest, ModelResponse

PROVIDER = "bedrock"
REGION = "ap-southeast-2"


def first_json_object(text: str) -> str:
    """The first balanced {...} in a model's reply (models often wrap JSON in prose)."""
    text = re.sub(r"<reasoning>.*?</reasoning>", "", text, flags=re.S)
    start = text.find("{")
    while start != -1:
        depth, in_str, esc = 0, False, False
        for i in range(start, len(text)):
            c = text[i]
            if in_str:
                esc = (c == "\\") and not esc
                if c == '"' and not esc:
                    in_str = False
                continue
            if c == '"':
                in_str = True
            elif c == "{":
                depth += 1
            elif c == "}":
                depth -= 1
                if depth == 0:
                    candidate = text[start : i + 1]
                    try:
                        json.loads(candidate)
                        return candidate
                    except ValueError:
                        break
        start = text.find("{", start + 1)
    return text.strip()


CLIENT_MAX_AGE_S = 600  # the host refreshes short-lived role credentials; pick them up


class BedrockModel:
    def __init__(self, client: Any = None):
        self._fixed, self._client, self._made = client is not None, client, 0.0

    def _fresh_client(self) -> Any:
        import time

        if not self._fixed and time.monotonic() - self._made > CLIENT_MAX_AGE_S:
            import boto3

            self._client = boto3.session.Session().client("bedrock-runtime", region_name=REGION)
            self._made = time.monotonic()
        return self._client

    def complete(self, request: ModelRequest, model_id: str) -> ModelResponse:
        system = request.system
        if request.response_schema is not None:
            system += (
                "\n\nReply with exactly one JSON object and nothing else. It must match this "
                "JSON schema:\n" + json.dumps(request.response_schema, ensure_ascii=False)
            )
        out = self._fresh_client().converse(
            modelId=model_id,
            system=[{"text": system}] if system else [],
            messages=[{"role": m.role, "content": [{"text": m.content}]} for m in request.messages],
            inferenceConfig={"maxTokens": request.max_output_tokens, "temperature": 0},
        )
        blocks = out["output"]["message"]["content"]
        text = "".join(b["text"] for b in blocks if isinstance(b.get("text"), str))
        if request.response_schema is not None:
            text = first_json_object(text)
        usage = out.get("usage", {})
        return ModelResponse(
            text=text,
            input_tokens=int(usage.get("inputTokens", 0)),
            output_tokens=int(usage.get("outputTokens", 0)),
        )

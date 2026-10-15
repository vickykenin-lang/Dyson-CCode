"""A deterministic stand-in model behind C, for local runs until Step 10 benchmarks real ones.

It is wired exactly like a real provider: admitted at A's gate, registered in C with a Founder
approval, qualified against an acceptance bar, and called only through C. It understands a few
fixed phrasings in English, Hindi and Hinglish; anything else it asks to clarify.
"""

import json
import re

from dyson_intelligence.models import ModelRequest, ModelResponse

PROVIDER = "local-rules"
MODEL_ID = "local-rules-1"
_HINGLISH = re.compile(r"\b(karo|kar do|kya|hai|mujhe|batao|pichli|daal do)\b")
_NUMBER = re.compile(r"(?<![A-Za-z0-9.])-?\d+(?:\.\d+)?(?![A-Za-z0-9])")  # not the 0 in "T0"


class RulesModel:
    def __init__(self) -> None:
        self.down = False
        self.prompts: list[str] = []  # everything ever sent to this "provider", for audits

    def complete(self, request: ModelRequest, model_id: str) -> ModelResponse:
        prompt = request.system + "\n" + "\n".join(m.content for m in request.messages)
        self.prompts.append(prompt)
        if self.down:
            raise ConnectionError("provider unreachable")
        if "Conversation Engine (B)" in request.system:
            text = json.dumps(_interpret(request), ensure_ascii=False)
        else:
            last = request.messages[-1].content
            text = json.dumps({"summary": f"{len(last.split())} words considered"})
        return ModelResponse(
            text=text,
            input_tokens=len(prompt.encode()) // 4 + 1,
            output_tokens=len(text.encode()) // 4 + 1,
        )


def _language(text: str) -> str:
    if re.search(r"[ऀ-ॿ]", text):
        return "hi"
    return "hinglish" if _HINGLISH.search(text.lower()) else "en"


def _interpret(request: ModelRequest) -> dict:
    text = request.messages[-1].content
    low, lang = text.lower(), _language(text)
    if "tally" in low or "जोड़" in text or "jod" in low:
        numbers = [float(n) if "." in n else int(n) for n in _NUMBER.findall(text)]
        if not numbers:
            return {"language": lang, "kind": "clarify", "text": "Which numbers should I tally?"}
        return {
            "language": lang,
            "kind": "action",
            "plan": {
                "tool_id": "t0.tally",
                "arguments": {"numbers": numbers},
                "receptor_id": "T0",
                "summary": f"Tally {len(numbers)} numbers on T0",
            },
        }
    if "publish" in low:
        note = text.split(":", 1)[1].strip() if ":" in text else "test note"
        return {
            "language": lang,
            "kind": "action",
            "plan": {
                "tool_id": "t0.publish",
                "arguments": {"note": note},
                "receptor_id": "T0",
                "risk": "high",
                "summary": f"Publish a note on T0: {note}",
            },
        }
    if "propose" in low:
        rule = re.search(r"AMD-\d+", text)
        if rule:
            return {
                "language": lang,
                "kind": "proposal",
                "proposal": {
                    "rule_id": rule.group(),
                    "diff": text,
                    "rationale": "Founder asked for it",
                },
            }
    if low.rstrip().endswith("?"):
        return {"language": lang, "kind": "answer", "text": _answer(request, low)}
    return {
        "language": lang,
        "kind": "clarify",
        "text": "What should I do, and for which Receptor?",
    }


def _answer(request: ModelRequest, low: str) -> str:
    rule = re.search(r"amd-(\d+)", low)
    if rule:  # recall an approved rule from the persona built out of the register
        line = next(
            (ln for ln in request.system.splitlines() if ln.startswith(f"- AMD-{rule.group(1)} ")),
            None,
        )
        return f"The approved rule is {line[2:]}." if line else "I do not find that rule."
    if "earlier" in low or "previous" in low or "pichli" in low:
        earlier = [m.content for m in request.messages[:-1] if m.role == "user"]
        return f'Earlier you said: "{earlier[0]}".' if earlier else "We have not talked before."
    return "I can tally numbers or publish a note on T0."

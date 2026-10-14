"""Thin wrapper around the Anthropic API that always returns parsed JSON."""
import json
import os
import re

import anthropic

MODEL = os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-5-5")
_client = None


def parse_json(text):
    """Parse JSON even if the model wrapped it in markdown fences."""
    return json.loads(re.sub(r"^```(?:json)?\s*|\s*```$", "", text.strip()))


def ask_json(system, user, max_tokens=2500, retries=1):
    global _client
    _client = _client or anthropic.Anthropic()  # reads ANTHROPIC_API_KEY from the environment
    last = None
    for _ in range(retries + 1):
        msg = _client.messages.create(model=MODEL, max_tokens=max_tokens, system=system,
                                      messages=[{"role": "user", "content": user}])
        text = "".join(b.text for b in msg.content if b.type == "text")
        try:
            return parse_json(text)
        except json.JSONDecodeError as e:
            last = e
    raise ValueError(f"model returned invalid JSON: {last}")

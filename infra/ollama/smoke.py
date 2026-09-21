"""POST a smoke prompt to the local pinned model (DEC-0007)."""

from __future__ import annotations

import json
import sys
import urllib.request

from tests.support.runtime_pin import RuntimePin


class LocalModelSmoke:
    """One completion against the SHA-pinned weights. No network egress."""

    def __init__(self, base_url: str = "http://127.0.0.1:11434") -> None:
        self._base_url = base_url

    def complete(self, prompt: str = "Reply with the single word ok.") -> str:
        pin = RuntimePin().weights_sha()
        body = json.dumps(
            {
                "model": f"sha256:{pin}",
                "prompt": prompt,
                "stream": False,
            }
        ).encode("utf-8")
        request = urllib.request.Request(
            f"{self._base_url}/api/generate",
            data=body,
            method="POST",
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(request, timeout=120) as response:
            payload: object = json.loads(response.read().decode("utf-8"))
        if not isinstance(payload, dict):
            raise TypeError("ollama /api/generate must return an object")
        text = payload.get("response")
        if not isinstance(text, str) or text.strip() == "":
            raise RuntimeError("smoke prompt returned no completion")
        return text


class SmokeMain:
    def __call__(self) -> int:
        sys.stdout.write(LocalModelSmoke().complete())
        sys.stdout.write("\n")
        return 0


if __name__ == "__main__":
    raise SystemExit(SmokeMain()())

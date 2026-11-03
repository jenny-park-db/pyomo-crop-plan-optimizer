"""Crop Plan Studio's /api/studio routes, called as the agent's calling user.

The agent has no write path of its own: scenarios, runs, and stress tests are created by Studio (the
same validation, dedupe, and job start as its Run button), and Studio records the user from the
token this client sends. ``headers`` returns that user's auth header for each call.
"""

from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.request
from collections.abc import Callable
from typing import Any

Transport = Callable[[str, str, dict[str, str], bytes | None, float], tuple[int, bytes]]

_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")


class StudioError(Exception):
    """Studio refused or failed a request; ``path`` names the offending field when Studio says."""

    def __init__(self, status: int, message: str, path: str | None = None):
        super().__init__(message)
        self.status = status
        self.path = path


def _urllib(method: str, url: str, headers: dict[str, str], body: bytes | None, timeout: float) -> tuple[int, bytes]:
    request = urllib.request.Request(url, data=body, method=method, headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.status, response.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()


def _id(value: str, what: str) -> str:
    if not isinstance(value, str) or not _ID.fullmatch(value):
        raise StudioError(400, f"{what} must be 1-64 letters, digits, '.', '_' or '-', got {value!r}")
    return value


class StudioClient:
    def __init__(self, base_url: str, headers: Callable[[], dict[str, str]], *, transport: Transport | None = None,
                 timeout: float = 60.0):
        self.base_url = base_url.rstrip("/")
        self._headers = headers
        self._transport = transport or _urllib
        self._timeout = timeout

    @classmethod
    def from_env(cls, headers: Callable[[], dict[str, str]], **kwargs: Any) -> StudioClient:
        url = os.getenv("CROP_PLAN_STUDIO_URL", "").strip()
        if not url:
            raise RuntimeError("CROP_PLAN_STUDIO_URL is not set; deploy the agent with scripts/deploy_agent.py")
        if not url.startswith("https://"):
            raise RuntimeError(f"CROP_PLAN_STUDIO_URL must be an https URL, got {url}")
        return cls(url, headers, **kwargs)

    def _call(self, method: str, path: str, body: dict[str, Any] | None = None) -> dict[str, Any]:
        headers = {**self._headers(), "Content-Type": "application/json"}
        data = json.dumps(body).encode() if body is not None else None
        try:
            status, raw = self._transport(method, self.base_url + path, headers, data, self._timeout)
        except OSError as e:  # URLError, socket timeouts, refused connections
            raise StudioError(504, f"Crop Plan Studio did not answer: {e}") from e
        try:
            out = json.loads(raw or b"{}")
        except ValueError:
            out = {"error": raw.decode(errors="replace")[:300]}
        if status >= 400:
            raise StudioError(status, str(out.get("error") or f"HTTP {status}"), out.get("path"))
        return out

    def submit(self, body: dict[str, Any]) -> dict[str, Any]:
        return self._call("POST", "/api/studio/runs", body)

    def run_report(self, run_id: str) -> dict[str, Any]:
        return self._call("GET", f"/api/studio/runs/{_id(run_id, 'run_id')}/report")

    def scenario_report(self, scenario_id: str) -> dict[str, Any]:
        return self._call("GET", f"/api/studio/scenarios/{_id(scenario_id, 'scenario_id')}/report")

    def start_stress(self, scenario_id: str, n: int) -> dict[str, Any]:
        return self._call("POST", "/api/studio/stress", {"scenario_id": scenario_id, "n": n})

    def stress_result(self, stress_id: str) -> dict[str, Any]:
        return self._call("GET", f"/api/studio/stress-tests/{_id(stress_id, 'stress_id')}")

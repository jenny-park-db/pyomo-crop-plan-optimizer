import json

import pytest
from agent.studio import StudioClient, StudioError


class FakeTransport:
    """Records requests; answers from a {(method, path): (status, body)} table."""

    def __init__(self, answers):
        self.answers = answers
        self.calls = []

    def __call__(self, method, url, headers, body, timeout):
        path = url.split("databricksapps.com", 1)[1]
        self.calls.append({"method": method, "path": path, "headers": headers,
                           "body": json.loads(body) if body else None, "timeout": timeout})
        status, answer = self.answers[(method, path)]
        return status, json.dumps(answer).encode()


BASE = "https://crop-plan-studio-1.aws.databricksapps.com"


def client(answers):
    t = FakeTransport(answers)
    return StudioClient(BASE + "/", lambda: {"Authorization": "Bearer user-token"}, transport=t), t


def test_submit_posts_as_the_caller_and_returns_the_body():
    c, t = client({("POST", "/api/studio/runs"): (200, {"run_id": "agent-1", "status": "queued"})})
    assert c.submit({"mode": "new"}) == {"run_id": "agent-1", "status": "queued"}
    assert t.calls[0]["headers"] == {"Authorization": "Bearer user-token", "Content-Type": "application/json"}
    assert t.calls[0]["body"] == {"mode": "new"}


def test_reads_quote_ids_into_the_path():
    c, t = client({
        ("GET", "/api/studio/runs/agent-1/report"): (200, {"status": "done"}),
        ("GET", "/api/studio/scenarios/baseline-2027/report"): (200, {"status": "done"}),
        ("GET", "/api/studio/stress-tests/st-1"): (200, {"state": "running"}),
        ("POST", "/api/studio/stress"): (200, {"stress_id": "st-1"}),
    })
    c.run_report("agent-1")
    c.scenario_report("baseline-2027")
    c.stress_result("st-1")
    c.start_stress("baseline-2027", 20)
    assert [x["path"] for x in t.calls][-1] == "/api/studio/stress"
    assert t.calls[-1]["body"] == {"scenario_id": "baseline-2027", "n": 20}
    with pytest.raises(StudioError):
        c.run_report("../admin")


def test_an_error_reply_raises_with_status_message_and_path():
    c, _ = client({("POST", "/api/studio/runs"): (400, {"error": "diversity_cap must be a finite number", "path": "diversity_cap"})})
    with pytest.raises(StudioError) as e:
        c.submit({})
    assert (e.value.status, e.value.path, str(e.value)) == (400, "diversity_cap", "diversity_cap must be a finite number")


def test_a_non_json_error_still_raises_cleanly():
    t = lambda *a: (502, b"<html>Bad gateway</html>")  # noqa: E731
    c = StudioClient(BASE, lambda: {}, transport=t)
    with pytest.raises(StudioError) as e:
        c.scenario_report("baseline-2027")
    assert e.value.status == 502 and "Bad gateway" in str(e.value)


def test_from_env_requires_an_https_studio_url(monkeypatch):
    monkeypatch.delenv("CROP_PLAN_STUDIO_URL", raising=False)
    with pytest.raises(RuntimeError, match="CROP_PLAN_STUDIO_URL"):
        StudioClient.from_env(lambda: {})
    monkeypatch.setenv("CROP_PLAN_STUDIO_URL", "http://example.com")
    with pytest.raises(RuntimeError, match="https"):
        StudioClient.from_env(lambda: {})
    monkeypatch.setenv("CROP_PLAN_STUDIO_URL", BASE)
    assert StudioClient.from_env(lambda: {}).base_url == BASE


def test_a_transport_failure_becomes_a_studio_error():
    def down(*a):
        raise TimeoutError("timed out")

    c = StudioClient(BASE, lambda: {}, transport=down)
    with pytest.raises(StudioError) as e:
        c.run_report("agent-1")
    assert e.value.status == 504 and "did not answer" in str(e.value)

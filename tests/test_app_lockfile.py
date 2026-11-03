"""The Crop Plan Studio app (app/) must install from public npm, like CI and the Apps build container."""

import re
from pathlib import Path

APP = Path(__file__).resolve().parents[1] / "app"


def test_app_lockfile_resolves_only_from_public_npm():
    """A private npm registry or mirror writes its own host into package-lock.json; the Apps build container then 404s."""
    lock = (APP / "package-lock.json").read_text()
    hosts = set(re.findall(r'"resolved": "https://([^/]+)/', lock))
    assert hosts == {"registry.npmjs.org"}, hosts

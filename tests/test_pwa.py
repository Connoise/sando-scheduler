"""Tests for the v0.5 PWA polish: manifest, service worker, meta tags."""

from __future__ import annotations

import json
from pathlib import Path

from fastapi.testclient import TestClient

from sando_web.app import create_app
from sando_web.config import Settings


def _settings(tmp_path: Path) -> Settings:
    sd = tmp_path / "Schedule"
    sd.mkdir()
    return Settings(
        schedule_dir=sd,
        reminders_file=sd / "reminders.json",
        changelog_file=sd / "changelog.csv",
        config_file=sd / "config.json",
        archive_dir=sd / "Archive",
        defaults={},
    )


def test_manifest_served_with_correct_mime(tmp_path: Path):
    client = TestClient(create_app(_settings(tmp_path)))
    resp = client.get("/manifest.webmanifest")
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("application/manifest+json")
    payload = json.loads(resp.content)
    assert payload["name"] == "Sando Scheduler"
    assert payload["start_url"] == "/"
    assert payload["display"] == "standalone"
    assert payload["scope"] == "/"
    assert any(icon["src"] == "/static/icon.svg" for icon in payload["icons"])


def test_service_worker_served_at_root_with_js_mime(tmp_path: Path):
    """The SW must be at the URL root with JS MIME or browsers refuse it."""
    client = TestClient(create_app(_settings(tmp_path)))
    resp = client.get("/sw.js")
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("application/javascript")
    # Allow scoping to the whole origin even though the SW already sits at /.
    assert resp.headers.get("service-worker-allowed") == "/"
    body = resp.text
    assert "addEventListener('install'" in body or 'addEventListener("install"' in body
    assert "sando-shell" in body  # cache namespace present


def test_icon_served(tmp_path: Path):
    client = TestClient(create_app(_settings(tmp_path)))
    resp = client.get("/static/icon.svg")
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("image/svg")


def test_base_template_advertises_manifest_and_registers_sw(tmp_path: Path):
    """Every page needs the manifest link and the SW registration script."""
    client = TestClient(create_app(_settings(tmp_path)))
    for path in ("/week/2026-05-15", "/month/2026-05", "/event/new"):
        resp = client.get(path)
        assert resp.status_code == 200, path
        assert '<link rel="manifest" href="/manifest.webmanifest">' in resp.text
        assert '<meta name="theme-color" content="#0b58c2">' in resp.text
        assert 'apple-mobile-web-app-capable' in resp.text
        assert 'navigator.serviceWorker.register("/sw.js"' in resp.text


def test_manifest_disk_file_is_valid_json():
    """Sanity check on the on-disk manifest itself."""
    path = Path(__file__).parent.parent / "sando_web" / "static" / "manifest.webmanifest"
    payload = json.loads(path.read_text())
    assert payload["scope"] == "/"
    assert payload["start_url"] == "/"

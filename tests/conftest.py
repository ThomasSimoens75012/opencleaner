"""
conftest.py — Fixtures et utilitaires partagés entre tous les tests
"""

import json
import time
import pytest
from pathlib import Path
from app import app as flask_app


# ── Utilitaire SSE partagé ────────────────────────────────────────────────────

def consume_sse(client, job_id, timeout=15):
    """
    Lit un flux SSE jusqu'à l'événement 'done' ou expiration du délai.
    Retourne la liste complète des événements reçus.
    """
    events = []
    deadline = time.time() + timeout
    with client.get(f"/api/stream/{job_id}", buffered=False) as stream:
        for chunk in stream.response:
            if time.time() > deadline:
                break
            text = chunk.decode("utf-8") if isinstance(chunk, bytes) else chunk
            for line in text.splitlines():
                if line.startswith("data:"):
                    try:
                        payload = json.loads(line[5:].strip())
                        events.append(payload)
                        if payload.get("type") == "done":
                            return events
                    except json.JSONDecodeError:
                        pass
    return events


# ── Flask test client ─────────────────────────────────────────────────────────

@pytest.fixture
def client():
    flask_app.config["TESTING"] = True
    with flask_app.test_client() as c:
        yield c


# ── Répertoire temp isolé avec fichiers factices ──────────────────────────────

@pytest.fixture
def fake_temp(tmp_path):
    """
    Crée une arborescence de fichiers dans un dossier temporaire isolé.
    Ne touche jamais au vrai %TEMP% système.
    Retourne le Path du dossier racine.
    """
    (tmp_path / "file_a.tmp").write_bytes(b"x" * 1024 * 100)       # 100 Ko
    (tmp_path / "file_b.log").write_bytes(b"x" * 1024 * 200)       # 200 Ko
    sub = tmp_path / "subdir"
    sub.mkdir()
    (sub / "nested.dat").write_bytes(b"x" * 1024 * 50)             #  50 Ko
    (sub / "nested2.tmp").write_bytes(b"x" * 1024 * 80)            #  80 Ko
    return tmp_path


@pytest.fixture
def fake_browser_cache(tmp_path):
    """
    Simule la structure de cache de Chrome et Edge dans un dossier isolé.
    Retourne (localappdata_path, appdata_path).
    """
    local   = tmp_path / "Local"
    appdata = tmp_path / "Roaming"

    chrome = local / "Google" / "Chrome" / "User Data" / "Default"
    edge   = local / "Microsoft" / "Edge" / "User Data" / "Default"

    for browser_dir in [chrome, edge]:
        (browser_dir / "Cache").mkdir(parents=True)
        (browser_dir / "Code Cache").mkdir(parents=True)
        (browser_dir / "GPUCache").mkdir(parents=True)
        # Fichiers cache
        (browser_dir / "Cache"      / "f_000001").write_bytes(b"c" * 1024 * 150)
        (browser_dir / "Code Cache" / "js_001"  ).write_bytes(b"c" * 1024 * 80)
        (browser_dir / "GPUCache"   / "gpu_data" ).write_bytes(b"c" * 1024 * 40)
        # Fichier Login Data — NE DOIT PAS être supprimé
        (browser_dir / "Login Data").write_bytes(b"passwords_here" * 100)

    # Firefox profil
    ff_cache = appdata / "Mozilla" / "Firefox" / "Profiles" / "abc123.default" / "cache2"
    ff_cache.mkdir(parents=True)
    (ff_cache / "entries" ).mkdir()
    (ff_cache / "entries" / "entry1").write_bytes(b"f" * 1024 * 60)

    return local, appdata


@pytest.fixture
def fake_thumbnails(tmp_path):
    """
    Crée de faux fichiers thumbcache_*.db dans un dossier Explorer isolé.
    """
    explorer = tmp_path / "Microsoft" / "Windows" / "Explorer"
    explorer.mkdir(parents=True)
    (explorer / "thumbcache_256.db" ).write_bytes(b"CMMM" + b"\x00" * 1024 * 80)
    (explorer / "thumbcache_1024.db").write_bytes(b"CMMM" + b"\x00" * 1024 * 120)
    (explorer / "thumbcache_sr.db"  ).write_bytes(b"CMMM" + b"\x00" * 1024 * 40)
    # Fichier non-thumbcache — ne doit pas être supprimé
    (explorer / "iconcache.db"      ).write_bytes(b"OTHER" * 100)
    return tmp_path

"""
test_app.py — Tests d'intégration pour les routes Flask (app.py)
"""

import json
import time
import pytest
from cleaner import TASKS


# ─────────────────────────────────────────────────────────────────────────────
# Route GET /
# ─────────────────────────────────────────────────────────────────────────────

class TestIndex:
    def test_returns_200(self, client):
        r = client.get("/")
        assert r.status_code == 200

    def test_contains_task_labels(self, client):
        r = client.get("/")
        html = r.data.decode()
        assert "Nettoyer maintenant" in html
        assert "Réanalyser"          in html

    def test_tasks_json_injected(self, client):
        r = client.get("/")
        html = r.data.decode()
        # Toutes les tâches doivent être injectées dans le HTML
        for task in TASKS:
            assert task["id"] in html


# ─────────────────────────────────────────────────────────────────────────────
# Route GET /api/disk
# ─────────────────────────────────────────────────────────────────────────────

class TestApiDisk:
    def test_returns_200(self, client):
        r = client.get("/api/disk")
        assert r.status_code == 200

    def test_returns_list(self, client):
        data = client.get("/api/disk").get_json()
        assert isinstance(data, list)
        assert len(data) >= 1

    def test_drive_has_required_fields(self, client):
        drives = client.get("/api/disk").get_json()
        required = {"device", "total", "used", "free", "percent", "total_fmt", "free_fmt"}
        for drive in drives:
            assert required.issubset(drive.keys())

    def test_percent_is_valid(self, client):
        drives = client.get("/api/disk").get_json()
        for drive in drives:
            assert 0.0 <= drive["percent"] <= 100.0

    def test_free_less_than_total(self, client):
        drives = client.get("/api/disk").get_json()
        for drive in drives:
            assert drive["free"] <= drive["total"]


# ─────────────────────────────────────────────────────────────────────────────
# Route GET /api/sizes
# ─────────────────────────────────────────────────────────────────────────────

class TestApiSizes:
    def test_returns_200(self, client):
        r = client.get("/api/sizes")
        assert r.status_code == 200

    def test_contains_all_task_ids(self, client):
        data = client.get("/api/sizes").get_json()
        expected_ids = {t["id"] for t in TASKS}
        assert expected_ids.issubset(data.keys())

    def test_each_entry_has_bytes_and_fmt(self, client):
        data = client.get("/api/sizes").get_json()
        for tid, info in data.items():
            assert "bytes" in info, f"Clé 'bytes' manquante pour '{tid}'"
            assert "fmt"   in info, f"Clé 'fmt' manquante pour '{tid}'"

    def test_bytes_are_non_negative(self, client):
        data = client.get("/api/sizes").get_json()
        for tid, info in data.items():
            assert info["bytes"] >= 0, f"Taille négative pour '{tid}'"

    def test_fmt_is_string(self, client):
        data = client.get("/api/sizes").get_json()
        for tid, info in data.items():
            assert isinstance(info["fmt"], str)


# ─────────────────────────────────────────────────────────────────────────────
# Route POST /api/clean
# ─────────────────────────────────────────────────────────────────────────────

class TestApiClean:
    def test_no_tasks_returns_400(self, client):
        r = client.post("/api/clean",
                        data=json.dumps({"tasks": []}),
                        content_type="application/json")
        assert r.status_code == 400

    def test_invalid_task_ids_returns_400(self, client):
        r = client.post("/api/clean",
                        data=json.dumps({"tasks": ["fake_task", "nonexistent"]}),
                        content_type="application/json")
        assert r.status_code == 400

    def test_valid_task_returns_job_id(self, client):
        r = client.post("/api/clean",
                        data=json.dumps({"tasks": ["dns"]}),
                        content_type="application/json")
        assert r.status_code == 200
        data = r.get_json()
        assert "job_id" in data
        assert len(data["job_id"]) == 36   # UUID format

    def test_empty_body_returns_400(self, client):
        r = client.post("/api/clean",
                        data="{}",
                        content_type="application/json")
        assert r.status_code == 400

    def test_mixed_valid_invalid_ids(self, client):
        """Les IDs invalides sont filtrés — si au moins un valide, ça passe."""
        r = client.post("/api/clean",
                        data=json.dumps({"tasks": ["dns", "fake_task"]}),
                        content_type="application/json")
        assert r.status_code == 200


# ─────────────────────────────────────────────────────────────────────────────
# Route GET /api/stream/<job_id>  (SSE)
# ─────────────────────────────────────────────────────────────────────────────

class TestApiStream:
    def test_unknown_job_id_returns_404(self, client):
        r = client.get("/api/stream/00000000-0000-0000-0000-000000000000")
        assert r.status_code == 404

    def test_stream_produces_done_event(self, client):
        """Lance un nettoyage DNS (rapide, sans fichiers) et lit le flux SSE jusqu'à 'done'."""
        # 1. Crée le job
        r = client.post("/api/clean",
                        data=json.dumps({"tasks": ["dns"]}),
                        content_type="application/json")
        job_id = r.get_json()["job_id"]

        # 2. Lit le flux SSE jusqu'à l'événement "done" (ou timeout 10s)
        events = []
        deadline = time.time() + 10

        with client.get(f"/api/stream/{job_id}", buffered=False) as stream:
            for chunk in stream.response:
                if time.time() > deadline:
                    break
                text = chunk.decode("utf-8") if isinstance(chunk, bytes) else chunk
                for line in text.splitlines():
                    if line.startswith("data:"):
                        payload = json.loads(line[5:].strip())
                        events.append(payload)
                        if payload.get("type") == "done":
                            break
                else:
                    continue
                break

        types = [e["type"] for e in events]
        assert "done" in types, f"Événement 'done' non reçu. Événements reçus : {types}"

    def test_done_event_has_freed_fmt(self, client):
        """L'événement 'done' doit contenir freed_fmt."""
        r = client.post("/api/clean",
                        data=json.dumps({"tasks": ["dns"]}),
                        content_type="application/json")
        job_id = r.get_json()["job_id"]

        done_event = None
        deadline = time.time() + 10

        with client.get(f"/api/stream/{job_id}", buffered=False) as stream:
            for chunk in stream.response:
                if time.time() > deadline:
                    break
                text = chunk.decode("utf-8") if isinstance(chunk, bytes) else chunk
                for line in text.splitlines():
                    if line.startswith("data:"):
                        payload = json.loads(line[5:].strip())
                        if payload.get("type") == "done":
                            done_event = payload
                            break
                else:
                    continue
                break

        assert done_event is not None
        assert "freed_fmt" in done_event
        assert "msg"       in done_event

    def test_stream_content_type_is_sse(self, client):
        r = client.post("/api/clean",
                        data=json.dumps({"tasks": ["dns"]}),
                        content_type="application/json")
        job_id = r.get_json()["job_id"]

        with client.get(f"/api/stream/{job_id}", buffered=False) as stream:
            assert "text/event-stream" in stream.content_type


# ─────────────────────────────────────────────────────────────────────────────
# Test d'intégration bout en bout : estimation → nettoyage → re-estimation
# ─────────────────────────────────────────────────────────────────────────────

# ─────────────────────────────────────────────────────────────────────────────
# Route GET /api/startup
# ─────────────────────────────────────────────────────────────────────────────

class TestApiStartup:
    def test_returns_200(self, client):
        r = client.get("/api/startup")
        assert r.status_code == 200

    def test_returns_list(self, client):
        data = client.get("/api/startup").get_json()
        assert isinstance(data, list)

    def test_each_entry_has_required_fields(self, client):
        data = client.get("/api/startup").get_json()
        required = {"name", "command", "source", "enabled"}
        for entry in data:
            assert required.issubset(entry.keys()), f"Champs manquants: {entry}"

    def test_enabled_is_bool(self, client):
        data = client.get("/api/startup").get_json()
        for entry in data:
            assert isinstance(entry["enabled"], bool)


# ─────────────────────────────────────────────────────────────────────────────
# Route GET /api/apps
# ─────────────────────────────────────────────────────────────────────────────

class TestApiApps:
    def test_returns_200(self, client):
        r = client.get("/api/apps")
        assert r.status_code == 200

    def test_returns_list(self, client):
        data = client.get("/api/apps").get_json()
        assert isinstance(data, list)

    def test_each_app_has_required_fields(self, client):
        data = client.get("/api/apps").get_json()
        required = {"name", "version", "publisher", "size_fmt", "uninstall_string"}
        for app in data:
            assert required.issubset(app.keys()), f"Champs manquants: {app}"

    def test_apps_sorted_by_name(self, client):
        data = client.get("/api/apps").get_json()
        names = [a["name"].lower() for a in data]
        assert names == sorted(names), "Les applications doivent être triées par nom"


# ─────────────────────────────────────────────────────────────────────────────
# Route GET/POST /api/schedule
# ─────────────────────────────────────────────────────────────────────────────

class TestApiSchedule:
    def test_get_returns_200(self, client):
        r = client.get("/api/schedule")
        assert r.status_code == 200

    def test_get_has_required_fields(self, client):
        data = client.get("/api/schedule").get_json()
        required = {"enabled", "interval", "time", "tasks"}
        assert required.issubset(data.keys())

    def test_get_enabled_is_bool(self, client):
        data = client.get("/api/schedule").get_json()
        assert isinstance(data["enabled"], bool)

    def test_post_saves_config(self, client):
        payload = {"enabled": False, "interval": "weekly", "time": "03:30", "tasks": ["temp", "dns"]}
        r = client.post("/api/schedule",
                        data=json.dumps(payload),
                        content_type="application/json")
        assert r.status_code == 200
        data = r.get_json()
        assert data.get("ok") is True

    def test_post_returns_next_run_when_enabled(self, client):
        payload = {"enabled": True, "interval": "daily", "time": "02:00", "tasks": ["temp"]}
        r = client.post("/api/schedule",
                        data=json.dumps(payload),
                        content_type="application/json")
        data = r.get_json()
        assert "next_run" in data
        # When enabled, next_run doit être une chaîne ISO
        assert data["next_run"] is not None
        assert "T" in data["next_run"]  # format ISO 8601

    def test_post_next_run_none_when_disabled(self, client):
        payload = {"enabled": False, "interval": "daily", "time": "02:00", "tasks": []}
        r = client.post("/api/schedule",
                        data=json.dumps(payload),
                        content_type="application/json")
        data = r.get_json()
        assert data.get("next_run") is None


# ─────────────────────────────────────────────────────────────────────────────
# Route POST /api/duplicates
# ─────────────────────────────────────────────────────────────────────────────

class TestApiDuplicates:
    def test_invalid_folder_returns_400(self, client):
        r = client.post("/api/duplicates",
                        data=json.dumps({"folder": "C:/definitely/does/not/exist_xyz"}),
                        content_type="application/json")
        assert r.status_code == 400

    def test_valid_folder_returns_job_id(self, client, tmp_path):
        r = client.post("/api/duplicates",
                        data=json.dumps({"folder": str(tmp_path), "min_size_kb": 1}),
                        content_type="application/json")
        assert r.status_code == 200
        data = r.get_json()
        assert "job_id" in data
        assert len(data["job_id"]) == 36

    def test_duplicate_scan_finds_duplicates(self, client, tmp_path):
        """Crée 2 fichiers identiques et vérifie que le scan les détecte."""
        content = b"identical content " * 100  # > 1 Ko
        (tmp_path / "file_a.bin").write_bytes(content)
        (tmp_path / "file_b.bin").write_bytes(content)

        r = client.post("/api/duplicates",
                        data=json.dumps({"folder": str(tmp_path), "min_size_kb": 1}),
                        content_type="application/json")
        job_id = r.get_json()["job_id"]

        # Lit le flux SSE jusqu'à result ou done
        found_result = False
        deadline = time.time() + 15
        with client.get(f"/api/stream/{job_id}", buffered=False) as stream:
            for chunk in stream.response:
                if time.time() > deadline:
                    break
                text = chunk.decode("utf-8") if isinstance(chunk, bytes) else chunk
                for line in text.splitlines():
                    if line.startswith("data:"):
                        payload = json.loads(line[5:].strip())
                        if payload.get("type") == "result":
                            found_result = True
                            assert len(payload["groups"]) >= 1, "Doit trouver au moins 1 groupe de doublons"
                        if payload.get("type") == "done":
                            break
                else:
                    continue
                break

        assert found_result, "L'événement 'result' n'a pas été reçu"


# ─────────────────────────────────────────────────────────────────────────────
# Route POST /api/duplicates/delete
# ─────────────────────────────────────────────────────────────────────────────

class TestApiDuplicatesDelete:
    def test_no_paths_returns_400(self, client):
        r = client.post("/api/duplicates/delete",
                        data=json.dumps({"paths": []}),
                        content_type="application/json")
        assert r.status_code == 400

    def test_deletes_file_and_reports_freed(self, client, tmp_path):
        f = tmp_path / "to_delete.bin"
        f.write_bytes(b"x" * 1024 * 50)  # 50 Ko

        r = client.post("/api/duplicates/delete",
                        data=json.dumps({"paths": [str(f)]}),
                        content_type="application/json")
        assert r.status_code == 200
        data = r.get_json()
        assert data["freed"] == 1024 * 50
        assert not f.exists(), "Le fichier doit être supprimé"

    def test_freed_fmt_is_string(self, client, tmp_path):
        f = tmp_path / "test.bin"
        f.write_bytes(b"x" * 1024)
        r = client.post("/api/duplicates/delete",
                        data=json.dumps({"paths": [str(f)]}),
                        content_type="application/json")
        data = r.get_json()
        assert isinstance(data["freed_fmt"], str)


# ─────────────────────────────────────────────────────────────────────────────
# Route GET /api/health
# ─────────────────────────────────────────────────────────────────────────────

class TestApiHealth:
    def test_returns_200(self, client):
        r = client.get("/api/health")
        assert r.status_code == 200

    def test_has_required_top_level_fields(self, client):
        data = client.get("/api/health").get_json()
        assert "score"   in data
        assert "max"     in data
        assert "metrics" in data

    def test_score_is_within_range(self, client):
        data = client.get("/api/health").get_json()
        assert 0 <= data["score"] <= data["max"]

    def test_metrics_is_non_empty_list(self, client):
        data = client.get("/api/health").get_json()
        assert isinstance(data["metrics"], list)
        assert len(data["metrics"]) > 0


# ─────────────────────────────────────────────────────────────────────────────
# Route GET /api/history
# ─────────────────────────────────────────────────────────────────────────────

class TestApiHistory:
    def test_returns_200(self, client):
        r = client.get("/api/history")
        assert r.status_code == 200

    def test_returns_a_list(self, client):
        data = client.get("/api/history").get_json()
        assert isinstance(data, list)

    def test_content_type_is_json(self, client):
        r = client.get("/api/history")
        assert "application/json" in r.content_type


# ─────────────────────────────────────────────────────────────────────────────
# Route POST /api/apps/uninstall
# ─────────────────────────────────────────────────────────────────────────────

class TestApiUninstall:
    def test_missing_string_returns_400(self, client):
        r = client.post("/api/apps/uninstall", json={})
        assert r.status_code == 400

    def test_empty_string_returns_400(self, client):
        r = client.post("/api/apps/uninstall", json={"uninstall_string": ""})
        assert r.status_code == 400

    def test_valid_string_returns_ok_field(self, client):
        """Une commande valide doit retourner {"ok": bool} sans crasher."""
        r = client.post("/api/apps/uninstall",
                        json={"uninstall_string": "echo test"})
        assert r.status_code == 200
        assert "ok" in r.get_json()


# ─────────────────────────────────────────────────────────────────────────────
# Route POST /api/extensions/remove — chemin heureux
# ─────────────────────────────────────────────────────────────────────────────

class TestApiExtensionsRemove:
    def test_suppression_effective_dun_dossier_factice(self, client, tmp_path):
        """
        Si le dossier existe, la suppression doit réussir (ok=True)
        et le dossier ne doit plus exister sur le disque.
        """
        ext_dir = tmp_path / "fake_extension"
        ext_dir.mkdir()
        (ext_dir / "manifest.json").write_text('{"name":"test"}')

        r = client.post("/api/extensions/remove", json={"path": str(ext_dir)})
        assert r.status_code == 200
        data = r.get_json()
        assert data.get("ok") is True, f"Attendu ok=True, reçu : {data}"
        assert not ext_dir.exists(), "Le dossier doit avoir été supprimé du disque"


class TestEndToEnd:
    def test_clean_reduces_estimated_size(self, client, fake_temp, monkeypatch):
        """
        Crée des fichiers temp factices, vérifie que l'estimation les détecte,
        lance le nettoyage, vérifie que la taille retombe à 0.
        """
        monkeypatch.setenv("TEMP", str(fake_temp))
        monkeypatch.setenv("TMP",  str(fake_temp))

        # Avant nettoyage : la taille doit être > 0
        sizes_before = client.get("/api/sizes").get_json()
        assert sizes_before["temp"]["bytes"] > 0, "Les fichiers de test ne sont pas détectés"

        # Lance le nettoyage
        r = client.post("/api/clean",
                        data=json.dumps({"tasks": ["temp"]}),
                        content_type="application/json")
        job_id = r.get_json()["job_id"]

        # Attend la fin
        deadline = time.time() + 15
        with client.get(f"/api/stream/{job_id}", buffered=False) as stream:
            for chunk in stream.response:
                if time.time() > deadline:
                    break
                text = chunk.decode("utf-8") if isinstance(chunk, bytes) else chunk
                if '"done"' in text:
                    break

        # Après nettoyage : le dossier doit être vide
        assert list(fake_temp.iterdir()) == [], "Le dossier temp doit être vide après nettoyage"

        # Re-estimation : doit retomber à 0
        sizes_after = client.get("/api/sizes").get_json()
        assert sizes_after["temp"]["bytes"] == 0

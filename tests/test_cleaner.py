"""
test_cleaner.py — Tests unitaires pour cleaner.py

Chaque test crée ses propres fichiers dans des dossiers temporaires isolés
(via les fixtures de conftest.py) et ne touche jamais aux vrais dossiers système.
"""

import os
import pytest
from pathlib import Path
from unittest.mock import patch

import cleaner
from cleaner import (
    fmt_size,
    get_folder_size,
    delete_folder_contents,
    task_temp,
    task_browser_cache,
    task_thumbnails,
    task_dns,
    task_recycle_bin,
    estimate_temp,
    estimate_browser_cache,
    estimate_thumbnails,
    TASKS,
)


# ─────────────────────────────────────────────────────────────────────────────
# fmt_size
# ─────────────────────────────────────────────────────────────────────────────

class TestFmtSize:
    def test_zero(self):
        assert fmt_size(0) == "0 o"

    def test_bytes(self):
        assert fmt_size(512) == "512.0 o"

    def test_kilobytes(self):
        assert fmt_size(1024) == "1.0 Ko"

    def test_megabytes(self):
        assert fmt_size(1024 ** 2) == "1.0 Mo"

    def test_gigabytes(self):
        assert fmt_size(1024 ** 3) == "1.0 Go"

    def test_fractional(self):
        result = fmt_size(int(1.5 * 1024 ** 2))
        assert "Mo" in result
        assert "1.5" in result


# ─────────────────────────────────────────────────────────────────────────────
# get_folder_size
# ─────────────────────────────────────────────────────────────────────────────

class TestGetFolderSize:
    def test_empty_folder(self, tmp_path):
        assert get_folder_size(tmp_path) == 0

    def test_single_file(self, tmp_path):
        (tmp_path / "file.dat").write_bytes(b"x" * 1024)
        assert get_folder_size(tmp_path) == 1024

    def test_nested_files(self, fake_temp):
        size = get_folder_size(fake_temp)
        expected = (100 + 200 + 50 + 80) * 1024
        assert size == expected

    def test_nonexistent_folder(self, tmp_path):
        assert get_folder_size(tmp_path / "does_not_exist") == 0


# ─────────────────────────────────────────────────────────────────────────────
# delete_folder_contents
# ─────────────────────────────────────────────────────────────────────────────

class TestDeleteFolderContents:
    def test_deletes_files(self, tmp_path):
        (tmp_path / "a.tmp").write_bytes(b"x" * 100)
        (tmp_path / "b.tmp").write_bytes(b"x" * 200)
        freed, errors = delete_folder_contents(tmp_path)
        assert freed == 300
        assert errors == 0
        assert list(tmp_path.iterdir()) == []

    def test_deletes_subfolders(self, fake_temp):
        freed, errors = delete_folder_contents(fake_temp)
        assert freed == (100 + 200 + 50 + 80) * 1024
        assert errors == 0
        assert list(fake_temp.iterdir()) == []

    def test_folder_itself_not_deleted(self, tmp_path):
        (tmp_path / "file.tmp").write_bytes(b"x" * 50)
        delete_folder_contents(tmp_path)
        assert tmp_path.exists(), "Le dossier racine ne doit pas être supprimé"

    def test_nonexistent_folder_returns_zero(self, tmp_path):
        freed, errors = delete_folder_contents(tmp_path / "ghost")
        assert freed == 0
        assert errors == 0

    def test_empty_folder(self, tmp_path):
        freed, errors = delete_folder_contents(tmp_path)
        assert freed == 0
        assert errors == 0


# ─────────────────────────────────────────────────────────────────────────────
# task_temp
# ─────────────────────────────────────────────────────────────────────────────

class TestTaskTemp:
    def test_cleans_temp_dir(self, fake_temp, monkeypatch):
        monkeypatch.setenv("TEMP", str(fake_temp))
        monkeypatch.setenv("TMP",  str(fake_temp))
        monkeypatch.setattr(cleaner, "SYSTEM_TEMP", str(fake_temp))  # évite C:\Windows\Temp (admin)

        logs = []
        freed = task_temp(logs.append)

        assert freed > 0
        assert list(fake_temp.iterdir()) == [], "Le dossier temp doit être vide après nettoyage"
        assert any("libérés" in l for l in logs)

    def test_logs_are_produced(self, fake_temp, monkeypatch):
        monkeypatch.setenv("TEMP", str(fake_temp))
        monkeypatch.setenv("TMP",  str(fake_temp))
        monkeypatch.setattr(cleaner, "SYSTEM_TEMP", str(fake_temp))

        logs = []
        task_temp(logs.append)
        assert len(logs) >= 1   # au moins un message de résumé

    def test_nonexistent_temp_does_not_crash(self, tmp_path, monkeypatch):
        monkeypatch.setenv("TEMP", str(tmp_path / "ghost"))
        monkeypatch.setenv("TMP",  str(tmp_path / "ghost2"))
        monkeypatch.setattr(cleaner, "SYSTEM_TEMP", str(tmp_path / "ghost3"))
        logs = []
        freed = task_temp(logs.append)
        assert freed == 0


# ─────────────────────────────────────────────────────────────────────────────
# task_browser_cache
# ─────────────────────────────────────────────────────────────────────────────

class TestTaskBrowserCache:
    def test_cleans_chrome_cache(self, fake_browser_cache, monkeypatch):
        local, appdata = fake_browser_cache
        monkeypatch.setenv("LOCALAPPDATA", str(local))
        monkeypatch.setenv("APPDATA",      str(appdata))

        logs = []
        freed = task_browser_cache(logs.append)

        assert freed > 0

        chrome_cache = local / "Google" / "Chrome" / "User Data" / "Default" / "Cache"
        assert list(chrome_cache.iterdir()) == [], "Cache Chrome doit être vide"

    def test_cleans_edge_cache(self, fake_browser_cache, monkeypatch):
        local, appdata = fake_browser_cache
        monkeypatch.setenv("LOCALAPPDATA", str(local))
        monkeypatch.setenv("APPDATA",      str(appdata))

        task_browser_cache(lambda _: None)

        edge_cache = local / "Microsoft" / "Edge" / "User Data" / "Default" / "Cache"
        assert list(edge_cache.iterdir()) == [], "Cache Edge doit être vide"

    def test_does_not_delete_login_data(self, fake_browser_cache, monkeypatch):
        """CRITIQUE : Login Data (mots de passe) ne doit jamais être supprimé."""
        local, appdata = fake_browser_cache
        monkeypatch.setenv("LOCALAPPDATA", str(local))
        monkeypatch.setenv("APPDATA",      str(appdata))

        task_browser_cache(lambda _: None)

        login_data = local / "Google" / "Chrome" / "User Data" / "Default" / "Login Data"
        assert login_data.exists(), "Login Data (mots de passe) ne doit PAS être supprimé !"

    def test_cleans_firefox_cache(self, fake_browser_cache, monkeypatch):
        local, appdata = fake_browser_cache
        monkeypatch.setenv("LOCALAPPDATA", str(local))
        monkeypatch.setenv("APPDATA",      str(appdata))

        task_browser_cache(lambda _: None)

        ff_cache = appdata / "Mozilla" / "Firefox" / "Profiles" / "abc123.default" / "cache2"
        remaining = list((ff_cache / "entries").iterdir()) if (ff_cache / "entries").exists() else []
        assert remaining == [], "Cache Firefox doit être vide"

    def test_returns_freed_bytes(self, fake_browser_cache, monkeypatch):
        local, appdata = fake_browser_cache
        monkeypatch.setenv("LOCALAPPDATA", str(local))
        monkeypatch.setenv("APPDATA",      str(appdata))

        freed = task_browser_cache(lambda _: None)
        # Chrome (150+80+40) + Edge (150+80+40) + Firefox (60) = 600 Ko
        assert freed >= 600 * 1024


# ─────────────────────────────────────────────────────────────────────────────
# task_thumbnails
# ─────────────────────────────────────────────────────────────────────────────

class TestTaskThumbnails:
    def test_deletes_thumbcache_files(self, fake_thumbnails, monkeypatch):
        monkeypatch.setenv("LOCALAPPDATA", str(fake_thumbnails))

        logs = []
        freed = task_thumbnails(logs.append)

        explorer = fake_thumbnails / "Microsoft" / "Windows" / "Explorer"
        remaining = list(explorer.glob("thumbcache_*.db"))
        assert remaining == [], "Tous les thumbcache_*.db doivent être supprimés"
        assert freed > 0

    def test_does_not_delete_other_db_files(self, fake_thumbnails, monkeypatch):
        monkeypatch.setenv("LOCALAPPDATA", str(fake_thumbnails))

        task_thumbnails(lambda _: None)

        iconcache = fake_thumbnails / "Microsoft" / "Windows" / "Explorer" / "iconcache.db"
        assert iconcache.exists(), "iconcache.db ne doit pas être supprimé"

    def test_freed_size_matches(self, fake_thumbnails, monkeypatch):
        monkeypatch.setenv("LOCALAPPDATA", str(fake_thumbnails))
        # 256.db=80Ko + 1024.db=120Ko + sr.db=40Ko + header de 32o chacun ≈ 240Ko
        freed = task_thumbnails(lambda _: None)
        assert freed >= 230 * 1024


# ─────────────────────────────────────────────────────────────────────────────
# task_dns  (ne touche pas de fichiers — vérifie juste qu'il ne plante pas)
# ─────────────────────────────────────────────────────────────────────────────

class TestTaskDns:
    def test_does_not_raise(self):
        logs = []
        task_dns(logs.append)   # peut échouer silencieusement si pas admin
        assert any("DNS" in l or "Erreur" in l for l in logs)


# ─────────────────────────────────────────────────────────────────────────────
# task_recycle_bin  (vérifie qu'il ne plante pas)
# ─────────────────────────────────────────────────────────────────────────────

class TestTaskRecycleBin:
    def test_does_not_raise(self):
        logs = []
        task_recycle_bin(logs.append)
        assert len(logs) >= 1


# ─────────────────────────────────────────────────────────────────────────────
# Estimations
# ─────────────────────────────────────────────────────────────────────────────

class TestEstimations:
    def test_estimate_temp_reflects_files(self, fake_temp, monkeypatch):
        monkeypatch.setenv("TEMP", str(fake_temp))
        monkeypatch.setenv("TMP",  str(fake_temp))
        size = estimate_temp()
        assert size == (100 + 200 + 50 + 80) * 1024

    def test_estimate_browser_cache(self, fake_browser_cache, monkeypatch):
        local, appdata = fake_browser_cache
        monkeypatch.setenv("LOCALAPPDATA", str(local))
        monkeypatch.setenv("APPDATA",      str(appdata))
        size = estimate_browser_cache()
        assert size >= 600 * 1024

    def test_estimate_thumbnails(self, fake_thumbnails, monkeypatch):
        monkeypatch.setenv("LOCALAPPDATA", str(fake_thumbnails))
        size = estimate_thumbnails()
        assert size >= 230 * 1024

    def test_estimate_decreases_after_clean(self, fake_temp, monkeypatch):
        monkeypatch.setenv("TEMP", str(fake_temp))
        monkeypatch.setenv("TMP",  str(fake_temp))
        monkeypatch.setattr(cleaner, "SYSTEM_TEMP", str(fake_temp))

        before = estimate_temp()
        task_temp(lambda _: None)
        after = estimate_temp()

        assert before > 0
        assert after == 0


# ─────────────────────────────────────────────────────────────────────────────
# Registre TASKS
# ─────────────────────────────────────────────────────────────────────────────

class TestTasksRegistry:
    EXPECTED_IDS = {
        "temp", "recycle", "dns", "recent", "dumps", "prefetch", "wu", "eventlogs", "fontcache",
        "browser", "history", "cookies",
        "thumbnails", "appcache",
    }

    def test_all_tasks_present(self):
        ids = {t["id"] for t in TASKS}
        assert ids == self.EXPECTED_IDS

    def test_task_count(self):
        assert len(TASKS) == 14

    def test_each_task_has_required_keys(self):
        required = {"id", "label", "desc", "admin", "fn", "estimate_fn", "default", "group"}
        for task in TASKS:
            assert required.issubset(task.keys()), f"Clés manquantes dans la tâche '{task.get('id')}'"

    def test_fn_are_callable(self):
        for task in TASKS:
            assert callable(task["fn"]),          f"fn non callable pour '{task['id']}'"
            assert callable(task["estimate_fn"]), f"estimate_fn non callable pour '{task['id']}'"

    def test_admin_tasks_flagged(self):
        admin_ids = {t["id"] for t in TASKS if t["admin"]}
        assert admin_ids == {"prefetch", "wu", "eventlogs", "fontcache"}

    def test_groups_are_valid(self):
        valid_groups = {"system", "browser", "apps"}
        for task in TASKS:
            assert task["group"] in valid_groups, f"Groupe invalide pour '{task['id']}': {task['group']}"

    def test_group_assignments(self):
        by_group = {}
        for t in TASKS:
            by_group.setdefault(t["group"], set()).add(t["id"])
        assert {"temp", "recycle", "dns", "recent", "dumps", "prefetch", "wu", "eventlogs", "fontcache"} == by_group["system"]
        assert {"browser", "history", "cookies"} == by_group["browser"]
        assert {"thumbnails", "appcache"} == by_group["apps"]

    def test_defaults(self):
        defaults_on  = {t["id"] for t in TASKS if t["default"]}
        defaults_off = {t["id"] for t in TASKS if not t["default"]}
        assert "prefetch"  in defaults_off
        assert "wu"        in defaults_off
        assert "eventlogs" in defaults_off
        assert "fontcache" in defaults_off
        assert "history"   in defaults_off
        assert "cookies"   in defaults_off
        assert "dumps"     in defaults_off
        assert "temp"      in defaults_on
        assert "browser"   in defaults_on
        assert "thumbnails" in defaults_on
        assert "appcache"  in defaults_on

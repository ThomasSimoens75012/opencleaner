"""
test_technical.py — Tests techniques

Vérifient le comportement interne des fonctions, indépendamment de l'interface
utilisateur ou des routes HTTP :
  - Calculs et arithmétique (tailles, dates, scores)
  - Algorithmes (détection de doublons, scoring santé)
  - Persistance (lecture/écriture JSON)
  - Gestion des cas limites et des erreurs
  - Format des messages de log
"""

import pytest
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch

import cleaner
from cleaner import (
    fmt_size,
    delete_folder_contents,
    find_duplicates,
    get_health_data,
)


# ─────────────────────────────────────────────────────────────────────────────
# fmt_size — transitions d'unités et valeurs limites
# ─────────────────────────────────────────────────────────────────────────────

class TestFmtSizeLimites:
    """Comportement exact aux frontières entre unités (o/Ko/Mo/Go)."""

    def test_juste_en_dessous_de_1ko(self):
        result = fmt_size(1023)
        assert "o" in result
        assert "Ko" not in result

    def test_exactement_1ko(self):
        assert fmt_size(1024) == "1.0 Ko"

    def test_juste_en_dessous_de_1mo(self):
        assert "Ko" in fmt_size(1024 * 1024 - 1)

    def test_exactement_1mo(self):
        assert fmt_size(1024 ** 2) == "1.0 Mo"

    def test_exactement_1go(self):
        assert fmt_size(1024 ** 3) == "1.0 Go"

    def test_valeur_decimale(self):
        result = fmt_size(int(1.5 * 1024 ** 2))
        assert "1.5" in result
        assert "Mo" in result

    def test_tres_grande_valeur_ne_plante_pas(self):
        # 100 To — ne doit pas lever d'exception ni produire "Ko"
        result = fmt_size(100 * 1024 ** 4)
        assert isinstance(result, str)
        assert len(result) > 0

    def test_valeur_unique(self):
        # Même entrée → même sortie (déterministe)
        assert fmt_size(512 * 1024) == fmt_size(512 * 1024)


# ─────────────────────────────────────────────────────────────────────────────
# _compute_next_run — arithmétique de dates
# ─────────────────────────────────────────────────────────────────────────────

class TestComputeNextRun:
    """
    Vérifie que le calcul de la prochaine exécution est correct,
    notamment aux cas limites calendaires (fin de mois, passage d'année).
    """

    @pytest.fixture(autouse=True)
    def fn(self):
        import app as a
        self._fn = a._compute_next_run

    def test_retourne_none_si_desactive(self):
        result = self._fn({"enabled": False, "interval": "daily",
                           "time": "02:00", "tasks": [], "last_run": None})
        assert result is None

    def test_daily_retourne_chaine_iso(self):
        result = self._fn({"enabled": True, "interval": "daily",
                           "time": "02:00", "tasks": [], "last_run": None})
        assert result is not None
        datetime.fromisoformat(result)   # ne doit pas lever d'exception

    def test_weekly_retourne_chaine_iso(self):
        result = self._fn({"enabled": True, "interval": "weekly",
                           "time": "03:00", "tasks": [], "last_run": None})
        assert result is not None
        datetime.fromisoformat(result)

    def test_hourly_retourne_chaine_iso(self):
        last = (datetime.now() - timedelta(hours=2)).isoformat()
        result = self._fn({"enabled": True, "interval": "hourly",
                           "time": "00:00", "tasks": [], "last_run": last})
        assert result is not None
        datetime.fromisoformat(result)

    def test_fin_de_mois_ne_plante_pas(self):
        """
        Régression : l'ancienne implémentation faisait `day + 1` directement,
        ce qui génère une ValueError le 31 janvier (jour 32 inexistant).
        """
        fake_now = datetime(2025, 1, 31, 10, 0, 0)
        with patch("app.datetime") as mock_dt:
            mock_dt.now.return_value = fake_now
            mock_dt.fromisoformat = datetime.fromisoformat
            try:
                self._fn({"enabled": True, "interval": "daily",
                          "time": "02:00", "tasks": [], "last_run": None})
            except (ValueError, OverflowError) as e:
                pytest.fail(f"Crash en fin de mois (31 jan) : {e}")

    def test_fin_dannee_ne_plante_pas(self):
        fake_now = datetime(2025, 12, 31, 23, 50, 0)
        with patch("app.datetime") as mock_dt:
            mock_dt.now.return_value = fake_now
            mock_dt.fromisoformat = datetime.fromisoformat
            try:
                self._fn({"enabled": True, "interval": "daily",
                          "time": "02:00", "tasks": [], "last_run": None})
            except (ValueError, OverflowError) as e:
                pytest.fail(f"Crash en fin d'année : {e}")

    def test_resultat_est_dans_le_futur(self):
        """La prochaine exécution calculée doit toujours être après maintenant."""
        result = self._fn({"enabled": True, "interval": "daily",
                           "time": "02:00", "tasks": [], "last_run": None})
        assert result is not None
        next_dt = datetime.fromisoformat(result)
        assert next_dt > datetime.now()


# ─────────────────────────────────────────────────────────────────────────────
# Historique — lecture / écriture JSON
# ─────────────────────────────────────────────────────────────────────────────

class TestHistorique:
    """
    Vérifie la persistance des entrées d'historique :
    format correct, ordre, limite de 50 entrées, dates parseable.
    """

    @pytest.fixture(autouse=True)
    def patch_history(self, tmp_path, monkeypatch):
        import app as a
        monkeypatch.setattr(a, "HISTORY_FILE", tmp_path / "history.json")
        self._app = a

    def test_historique_vide_retourne_liste_vide(self):
        assert self._app._load_history() == []

    def test_sauvegarde_et_relecture(self):
        self._app._save_history_entry(1024 * 1024)
        history = self._app._load_history()
        assert len(history) == 1
        assert history[0]["freed_bytes"] == 1024 * 1024
        assert "freed_fmt" in history[0]
        assert "date" in history[0]

    def test_plus_recent_en_premier(self):
        self._app._save_history_entry(1000)
        self._app._save_history_entry(2000)
        history = self._app._load_history()
        assert history[0]["freed_bytes"] == 2000

    def test_limite_50_entrees(self):
        for i in range(60):
            self._app._save_history_entry(i * 1024)
        assert len(self._app._load_history()) <= 50

    def test_date_est_parseable_iso(self):
        self._app._save_history_entry(512)
        date_str = self._app._load_history()[0]["date"]
        datetime.fromisoformat(date_str)   # ne doit pas lever d'exception

    def test_freed_fmt_est_une_chaine(self):
        self._app._save_history_entry(5 * 1024 * 1024)
        entry = self._app._load_history()[0]
        assert isinstance(entry["freed_fmt"], str)
        assert "Mo" in entry["freed_fmt"]


# ─────────────────────────────────────────────────────────────────────────────
# find_duplicates — algorithme de détection par hash
# ─────────────────────────────────────────────────────────────────────────────

class TestFindDuplicates:
    """
    Vérifie que l'algorithme de détection des doublons est correct :
    même contenu → même groupe, contenu différent → pas groupé.
    """

    def test_deux_fichiers_identiques_groupes(self, tmp_path):
        content = b"identique " * 300        # > 100 Ko
        (tmp_path / "a.bin").write_bytes(content)
        (tmp_path / "b.bin").write_bytes(content)
        groups = find_duplicates(str(tmp_path), min_size_kb=1)
        assert len(groups) == 1
        assert len(list(groups.values())[0]) == 2

    def test_fichiers_differents_non_groupes(self, tmp_path):
        (tmp_path / "a.bin").write_bytes(b"AAA " * 300)
        (tmp_path / "b.bin").write_bytes(b"BBB " * 300)
        groups = find_duplicates(str(tmp_path), min_size_kb=1)
        assert len(groups) == 0

    def test_filtre_taille_minimale(self, tmp_path):
        """Les fichiers sous la taille minimale doivent être ignorés."""
        content = b"x" * 512               # 512 octets < 10 Ko
        (tmp_path / "small_a.bin").write_bytes(content)
        (tmp_path / "small_b.bin").write_bytes(content)
        groups = find_duplicates(str(tmp_path), min_size_kb=10)
        assert len(groups) == 0

    def test_trois_copies_un_seul_groupe(self, tmp_path):
        content = b"triple " * 300
        for name in ["a.bin", "b.bin", "c.bin"]:
            (tmp_path / name).write_bytes(content)
        groups = find_duplicates(str(tmp_path), min_size_kb=1)
        assert len(groups) == 1
        assert len(list(groups.values())[0]) == 3

    def test_doublons_dans_sous_dossiers(self, tmp_path):
        """Les doublons entre dossiers imbriqués doivent être détectés."""
        sub = tmp_path / "sub"
        sub.mkdir()
        content = b"nested " * 300
        (tmp_path / "root.bin").write_bytes(content)
        (sub / "nested.bin").write_bytes(content)
        groups = find_duplicates(str(tmp_path), min_size_kb=1)
        assert len(groups) == 1

    def test_dossier_vide_retourne_vide(self, tmp_path):
        groups = find_duplicates(str(tmp_path), min_size_kb=1)
        assert len(groups) == 0

    def test_chaque_fichier_a_size_et_path(self, tmp_path):
        """Chaque entrée de groupe doit contenir 'path' et 'size'."""
        content = b"fields " * 300
        (tmp_path / "a.bin").write_bytes(content)
        (tmp_path / "b.bin").write_bytes(content)
        groups = find_duplicates(str(tmp_path), min_size_kb=1)
        for group in groups.values():
            for f in group:
                assert "path" in f
                assert "size" in f
                assert f["size"] > 0


# ─────────────────────────────────────────────────────────────────────────────
# get_health_data — cohérence du score et de la structure
# ─────────────────────────────────────────────────────────────────────────────

class TestGetHealthData:
    """
    Vérifie que le calcul du score de santé est arithmétiquement cohérent
    et que chaque métrique respecte sa propre plage max.
    """

    @pytest.fixture(autouse=True)
    def data(self):
        self._data = get_health_data()

    def test_score_dans_la_plage(self):
        assert 0 <= self._data["score"] <= self._data["max"]

    def test_score_global_egal_somme_partiels(self):
        """Invariant fondamental : score global == Σ scores métriques."""
        computed = sum(m["score"] for m in self._data["metrics"])
        assert self._data["score"] == computed

    def test_max_global_egal_somme_max_partiels(self):
        """Le max global doit être la somme des max de chaque métrique."""
        total_max = sum(m["max"] for m in self._data["metrics"])
        assert total_max == self._data["max"]

    def test_chaque_metrique_dans_sa_plage(self):
        for m in self._data["metrics"]:
            assert 0 <= m["score"] <= m["max"], \
                f"Score hors plage pour '{m['id']}' : {m['score']} > {m['max']}"

    def test_champs_requis_par_metrique(self):
        required = {"id", "label", "icon", "status", "score", "max", "detail"}
        for m in self._data["metrics"]:
            missing = required - m.keys()
            assert not missing, f"Champs manquants pour '{m.get('id')}' : {missing}"

    def test_statuts_valides(self):
        for m in self._data["metrics"]:
            assert m["status"] in ("good", "warn", "bad"), \
                f"Statut invalide '{m['status']}' pour '{m['id']}'"

    def test_labels_non_vides(self):
        for m in self._data["metrics"]:
            assert m["label"].strip(), f"Label vide pour '{m['id']}'"
            assert m["detail"].strip(), f"Detail vide pour '{m['id']}'"

    def test_actions_pointent_vers_taches_connues(self):
        """Si une métrique propose une action, elle doit correspondre à une tâche."""
        from cleaner import TASKS
        task_ids = {t["id"] for t in TASKS}
        for m in self._data["metrics"]:
            if m.get("action"):
                assert m["action"] in task_ids, \
                    f"Action '{m['action']}' inconnue pour la métrique '{m['id']}'"


# ─────────────────────────────────────────────────────────────────────────────
# Format des logs — messages lisibles sans chemins techniques
# ─────────────────────────────────────────────────────────────────────────────

class TestFormatLogs:
    """
    Vérifie que les messages de log respectent le nouveau format :
    emoji + résumé, sans chemins de fichiers bruts ni messages techniques.
    """

    def test_temp_log_contient_emoji(self, fake_temp, monkeypatch):
        monkeypatch.setenv("TEMP", str(fake_temp))
        monkeypatch.setenv("TMP",  str(fake_temp))
        monkeypatch.setattr(cleaner, "SYSTEM_TEMP", str(fake_temp))
        logs = []
        cleaner.task_temp(logs.append)
        assert any("🗑" in l for l in logs), \
            f"Aucun emoji 🗑 dans les logs : {logs}"

    def test_temp_deja_propre_indique_propre(self, tmp_path, monkeypatch):
        """Dossier vide → message 'déjà propre'."""
        monkeypatch.setenv("TEMP", str(tmp_path))
        monkeypatch.setenv("TMP",  str(tmp_path))
        monkeypatch.setattr(cleaner, "SYSTEM_TEMP", str(tmp_path))
        logs = []
        cleaner.task_temp(logs.append)
        assert any("propre" in l for l in logs), \
            f"Dossier vide doit produire 'propre', logs : {logs}"

    def test_aucun_chemin_brut_dans_temp_log(self, fake_temp, monkeypatch):
        """Les logs normaux ne doivent pas contenir de chemins absolus Windows."""
        monkeypatch.setenv("TEMP", str(fake_temp))
        monkeypatch.setenv("TMP",  str(fake_temp))
        monkeypatch.setattr(cleaner, "SYSTEM_TEMP", str(fake_temp))
        logs = []
        cleaner.task_temp(logs.append)
        for log in logs:
            assert not log.strip().startswith("Suppression"), \
                f"Log trop technique trouvé : {log!r}"

    def test_admin_requis_indique_clairement(self):
        """Les tâches admin sans droits doivent le dire explicitement."""
        with patch.object(cleaner, "is_admin", return_value=False):
            logs = []
            cleaner.task_prefetch(logs.append)
            combined = " ".join(logs).lower()
            assert "admin" in combined or "requis" in combined, \
                f"Message admin non trouvé dans : {logs}"

    def test_dns_log_contient_emoji(self):
        logs = []
        cleaner.task_dns(logs.append)
        assert any("🔧" in l for l in logs), \
            f"Emoji 🔧 attendu dans les logs DNS : {logs}"

    def test_thumbnails_log_contient_emoji(self, fake_thumbnails, monkeypatch):
        monkeypatch.setenv("LOCALAPPDATA", str(fake_thumbnails))
        logs = []
        cleaner.task_thumbnails(logs.append)
        assert any("🖼" in l for l in logs), \
            f"Emoji 🖼 attendu dans les logs miniatures : {logs}"

    def test_un_seul_message_par_tache(self, fake_temp, monkeypatch):
        """
        Invariant clé : chaque tâche produit exactement 1 message de résumé,
        pas une ligne par fichier supprimé.
        """
        monkeypatch.setenv("TEMP", str(fake_temp))
        monkeypatch.setenv("TMP",  str(fake_temp))
        monkeypatch.setattr(cleaner, "SYSTEM_TEMP", str(fake_temp))
        logs = []
        cleaner.task_temp(logs.append)
        # fake_temp contient 4 fichiers — on ne doit pas avoir 4 logs
        assert len(logs) == 1, \
            f"task_temp doit produire 1 log résumé, pas {len(logs)} : {logs}"


# ─────────────────────────────────────────────────────────────────────────────
# delete_folder_contents — cas limites supplémentaires
# ─────────────────────────────────────────────────────────────────────────────

class TestDeleteFolderContentsAvance:
    """Cas non couverts par test_cleaner.py : types de retour et arborescences mixtes."""

    def test_retourne_un_tuple(self, tmp_path):
        result = delete_folder_contents(tmp_path)
        assert isinstance(result, tuple) and len(result) == 2

    def test_freed_et_errors_sont_entiers(self, tmp_path):
        freed, errors = delete_folder_contents(tmp_path)
        assert isinstance(freed, int)
        assert isinstance(errors, int)

    def test_arborescence_mixte_fichiers_et_dossiers(self, tmp_path):
        (tmp_path / "file.tmp").write_bytes(b"x" * 1024)
        sub = tmp_path / "sub"
        sub.mkdir()
        (sub / "nested.tmp").write_bytes(b"y" * 512)
        freed, errors = delete_folder_contents(tmp_path)
        assert freed == 1024 + 512
        assert errors == 0
        assert list(tmp_path.iterdir()) == []

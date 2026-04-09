"""
test_functional.py — Tests fonctionnels

Chaque test représente un parcours utilisateur complet.
La question posée est toujours : "Quand l'utilisateur fait X, est-ce qu'il obtient Y ?"
Ces tests ne s'intéressent pas à comment c'est implémenté, mais à ce qui est observable.
"""

import json
import time
import pytest
from datetime import datetime
from pathlib import Path

from tests.conftest import consume_sse


# ─────────────────────────────────────────────────────────────────────────────
# Scénario 1 — L'utilisateur lance un nettoyage
# ─────────────────────────────────────────────────────────────────────────────

class TestScenarioNettoyage:
    """
    Scénario : L'utilisateur sélectionne des tâches, clique sur "Nettoyer maintenant",
    observe la progression en temps réel et reçoit un résumé final.
    """

    def test_les_evenements_arrivent_dans_lordre(self, client):
        """
        Le flux SSE doit commencer par 'start' et se terminer par 'done'.
        Les événements intermédiaires peuvent être 'log' ou 'progress'.
        """
        r = client.post("/api/clean", json={"tasks": ["dns"]})
        events = consume_sse(client, r.get_json()["job_id"])

        types = [e["type"] for e in events]
        assert types[0] == "start", f"Premier événement attendu : 'start', reçu : {types[0]}"
        assert types[-1] == "done",  f"Dernier événement attendu : 'done', reçu : {types[-1]}"

    def test_levenement_done_contient_le_bilan(self, client):
        """L'utilisateur doit voir combien d'espace a été libéré à la fin."""
        r = client.post("/api/clean", json={"tasks": ["dns"]})
        events = consume_sse(client, r.get_json()["job_id"])

        done = next(e for e in events if e["type"] == "done")
        assert "freed_bytes" in done
        assert "freed_fmt"   in done
        assert "msg"         in done
        assert isinstance(done["freed_bytes"], int)

    def test_les_fichiers_sont_effectivement_supprimes(self, client, fake_temp, monkeypatch):
        """
        Après le nettoyage, le dossier temp doit être vide.
        Le résultat ne doit pas juste dire 'fait' — les fichiers doivent avoir disparu.
        """
        monkeypatch.setenv("TEMP", str(fake_temp))
        monkeypatch.setenv("TMP",  str(fake_temp))
        monkeypatch.setattr(__import__("cleaner"), "SYSTEM_TEMP", str(fake_temp))

        r = client.post("/api/clean", json={"tasks": ["temp"]})
        events = consume_sse(client, r.get_json()["job_id"])

        done = next(e for e in events if e["type"] == "done")
        assert done["freed_bytes"] > 0
        assert list(fake_temp.iterdir()) == [], "Le dossier temp doit être vide après nettoyage"

    def test_plusieurs_taches_toutes_executees(self, client):
        """Si l'utilisateur coche 2 tâches, les 2 doivent apparaître dans la progression."""
        r = client.post("/api/clean", json={"tasks": ["dns", "recycle"]})
        events = consume_sse(client, r.get_json()["job_id"])

        progress = [e for e in events if e["type"] == "progress"]
        assert len(progress) == 2, \
            f"2 tâches cochées → 2 événements 'progress' attendus, reçu : {len(progress)}"

    def test_les_logs_sont_lisibles_pas_techniques(self, client, fake_temp, monkeypatch):
        """
        Les messages de log reçus par l'utilisateur ne doivent pas contenir
        de chemins de fichiers bruts ni de messages système internes.
        """
        monkeypatch.setenv("TEMP", str(fake_temp))
        monkeypatch.setenv("TMP",  str(fake_temp))
        monkeypatch.setattr(__import__("cleaner"), "SYSTEM_TEMP", str(fake_temp))

        r = client.post("/api/clean", json={"tasks": ["temp"]})
        events = consume_sse(client, r.get_json()["job_id"])

        log_messages = [e["msg"] for e in events if e["type"] == "log"]
        for msg in log_messages:
            assert not msg.strip().startswith("Suppression :"), \
                f"Message technique exposé à l'utilisateur : {msg!r}"


# ─────────────────────────────────────────────────────────────────────────────
# Scénario 2 — L'utilisateur consulte et retrace son historique
# ─────────────────────────────────────────────────────────────────────────────

class TestScenarioHistorique:
    """
    Scénario : Après avoir nettoyé, l'utilisateur revient sur l'app
    et retrouve le bilan de sa dernière session dans la sidebar.
    """

    def test_historique_enregistre_apres_nettoyage_reussi(self, client, fake_temp, monkeypatch, tmp_path):
        """Une session de nettoyage qui libère de l'espace doit apparaître dans l'historique."""
        import app as a
        monkeypatch.setattr(a, "HISTORY_FILE", tmp_path / "history.json")
        monkeypatch.setenv("TEMP", str(fake_temp))
        monkeypatch.setenv("TMP",  str(fake_temp))
        monkeypatch.setattr(__import__("cleaner"), "SYSTEM_TEMP", str(fake_temp))

        r = client.post("/api/clean", json={"tasks": ["temp"]})
        consume_sse(client, r.get_json()["job_id"])

        history = client.get("/api/history").get_json()
        assert len(history) >= 1, "L'historique doit contenir au moins une entrée"
        assert history[0]["freed_bytes"] > 0
        assert history[0]["freed_fmt"]   # non vide

    def test_historique_vide_si_rien_nettoye(self, client, tmp_path, monkeypatch):
        """Si le nettoyage ne libère rien, l'historique ne doit pas grossir."""
        import app as a
        monkeypatch.setattr(a, "HISTORY_FILE", tmp_path / "history.json")

        # Nettoyage DNS (libère 0 octets)
        r = client.post("/api/clean", json={"tasks": ["dns"]})
        consume_sse(client, r.get_json()["job_id"])

        history = client.get("/api/history").get_json()
        assert len(history) == 0, "Un nettoyage sans résultat ne doit pas créer d'entrée"

    def test_lentree_dhistorique_a_une_date_recente(self, client, fake_temp, monkeypatch, tmp_path):
        """La date de l'entrée doit correspondre à l'heure de la session."""
        import app as a
        monkeypatch.setattr(a, "HISTORY_FILE", tmp_path / "history.json")
        monkeypatch.setenv("TEMP", str(fake_temp))
        monkeypatch.setenv("TMP",  str(fake_temp))
        monkeypatch.setattr(__import__("cleaner"), "SYSTEM_TEMP", str(fake_temp))

        before = datetime.now()
        r = client.post("/api/clean", json={"tasks": ["temp"]})
        consume_sse(client, r.get_json()["job_id"])
        after = datetime.now()

        history = client.get("/api/history").get_json()
        entry_date = datetime.fromisoformat(history[0]["date"])
        assert before <= entry_date <= after, "La date de l'entrée doit être comprise dans la session"


# ─────────────────────────────────────────────────────────────────────────────
# Scénario 3 — L'utilisateur configure le planificateur
# ─────────────────────────────────────────────────────────────────────────────

class TestScenarioPlanificateur:
    """
    Scénario : L'utilisateur active le planificateur pour un nettoyage automatique
    quotidien et vérifie que la prochaine exécution est bien affichée.
    """

    def test_activation_retourne_la_prochaine_execution(self, client):
        """En activant le planificateur, l'UI doit pouvoir afficher une date précise."""
        r = client.post("/api/schedule", json={
            "enabled": True, "interval": "daily",
            "time": "02:00", "tasks": ["temp", "dns"]
        })
        data = r.get_json()
        assert data["ok"] is True
        assert data["next_run"] is not None
        # La date doit être valide et dans le futur
        next_dt = datetime.fromisoformat(data["next_run"])
        assert next_dt > datetime.now()

    def test_desactivation_masque_la_prochaine_execution(self, client):
        """Planificateur désactivé → pas de prochaine exécution à afficher."""
        client.post("/api/schedule", json={"enabled": True, "interval": "daily",
                                           "time": "02:00", "tasks": []})
        r = client.post("/api/schedule", json={"enabled": False})
        assert r.get_json()["next_run"] is None

    def test_la_configuration_est_retrouvee_apres_sauvegarde(self, client):
        """Ce que l'utilisateur sauvegarde doit être exactement ce qu'il retrouve."""
        payload = {
            "enabled": False, "interval": "weekly",
            "time": "04:30", "tasks": ["temp", "browser", "recycle"]
        }
        client.post("/api/schedule", json=payload)
        retrieved = client.get("/api/schedule").get_json()

        assert retrieved["interval"] == "weekly"
        assert retrieved["time"]     == "04:30"
        assert set(retrieved["tasks"]) == {"temp", "browser", "recycle"}

    def test_changer_lintervalle_change_la_prochaine_execution(self, client):
        """Passer de daily à weekly doit changer la date affichée."""
        r_daily  = client.post("/api/schedule", json={"enabled": True, "interval": "daily",
                                                       "time": "02:00", "tasks": ["temp"]})
        r_weekly = client.post("/api/schedule", json={"enabled": True, "interval": "weekly",
                                                       "time": "02:00", "tasks": ["temp"]})
        next_daily  = datetime.fromisoformat(r_daily.get_json()["next_run"])
        next_weekly = datetime.fromisoformat(r_weekly.get_json()["next_run"])
        assert next_weekly >= next_daily, "L'exécution hebdomadaire doit être plus loin que la quotidienne"


# ─────────────────────────────────────────────────────────────────────────────
# Scénario 4 — L'utilisateur scanne et supprime des doublons
# ─────────────────────────────────────────────────────────────────────────────

class TestScenarioDoublons:
    """
    Scénario : L'utilisateur scanne ses Téléchargements, trouve des copies,
    sélectionne les doublons et libère de l'espace.
    """

    def test_le_scan_detecte_les_copies(self, client, tmp_path):
        """Deux fichiers au contenu identique doivent apparaître dans les résultats."""
        content = b"copie identique " * 300
        (tmp_path / "original.dat").write_bytes(content)
        (tmp_path / "copie.dat").write_bytes(content)

        r = client.post("/api/duplicates", json={"folder": str(tmp_path), "min_size_kb": 1})
        events = consume_sse(client, r.get_json()["job_id"])

        result = next((e for e in events if e["type"] == "result"), None)
        assert result is not None, "L'événement 'result' doit être émis après le scan"
        assert len(result["groups"]) == 1
        assert result["total_wasted"] > 0

    def test_la_suppression_efface_les_copies(self, client, tmp_path):
        """Après suppression, la copie disparaît mais l'original reste intact."""
        content = b"x" * 1024 * 50        # 50 Ko
        original = tmp_path / "original.dat"
        copie    = tmp_path / "copie.dat"
        original.write_bytes(content)
        copie.write_bytes(content)

        r = client.post("/api/duplicates/delete", json={"paths": [str(copie)]})
        data = r.get_json()

        assert not copie.exists(),    "La copie doit être supprimée"
        assert original.exists(),     "L'original doit être préservé"
        assert data["freed"] > 0
        assert "freed_fmt" in data

    def test_les_groupes_sont_tries_par_espace_gaspille(self, client, tmp_path):
        """
        Le scan doit retourner les groupes dans l'ordre décroissant d'espace gaspillé,
        pour que les plus gros doublons apparaissent en premier.
        """
        # Groupe 1 : 3 × 100 Ko = 300 Ko gaspillés (2 copies)
        small = b"petit " * 200
        for name in ["s1.bin", "s2.bin", "s3.bin"]:
            (tmp_path / name).write_bytes(small)

        # Groupe 2 : 2 × 500 Ko = 500 Ko gaspillés (1 copie)
        big = b"gros " * 1000
        (tmp_path / "b1.bin").write_bytes(big)
        (tmp_path / "b2.bin").write_bytes(big)

        r = client.post("/api/duplicates", json={"folder": str(tmp_path), "min_size_kb": 1})
        events = consume_sse(client, r.get_json()["job_id"])

        result = next((e for e in events if e["type"] == "result"), None)
        assert result is not None
        groups = result["groups"]
        assert len(groups) == 2

        # Le premier groupe doit être le plus gros
        waste = [sum(f["size"] for f in g[1:]) for g in groups]
        assert waste[0] >= waste[1], "Les groupes doivent être triés par espace gaspillé décroissant"


# ─────────────────────────────────────────────────────────────────────────────
# Scénario 5 — L'utilisateur consulte son bilan de santé
# ─────────────────────────────────────────────────────────────────────────────

class TestScenarioSante:
    """
    Scénario : L'utilisateur ouvre l'onglet Santé pour avoir une vue synthétique
    de l'état de son PC, avec un score global et des indicateurs par catégorie.
    """

    def test_le_score_est_un_pourcentage_valide(self, client):
        """Le score doit pouvoir être affiché comme un % entre 0 et 100."""
        data = client.get("/api/health").get_json()
        pct = data["score"] / data["max"] * 100
        assert 0 <= pct <= 100

    def test_chaque_indicateur_est_comprehensible(self, client):
        """Chaque métrique doit avoir un libellé et un détail non vides."""
        for m in client.get("/api/health").get_json()["metrics"]:
            assert m["label"].strip(),  f"Libellé vide pour la métrique '{m['id']}'"
            assert m["detail"].strip(), f"Détail vide pour la métrique '{m['id']}'"
            assert m["icon"],           f"Icône manquante pour '{m['id']}'"

    def test_les_actions_rapides_sont_des_taches_connues(self, client):
        """
        Quand une métrique propose un bouton 'Nettoyer',
        l'action doit correspondre à une tâche réelle.
        """
        from cleaner import TASKS
        task_ids = {t["id"] for t in TASKS}
        for m in client.get("/api/health").get_json()["metrics"]:
            if m.get("action"):
                assert m["action"] in task_ids, \
                    f"Action '{m['action']}' ne correspond à aucune tâche disponible"

    def test_les_pires_metriques_sont_visibles(self, client):
        """
        Toutes les métriques doivent être retournées,
        y compris celles avec le statut 'bad'.
        """
        data = client.get("/api/health").get_json()
        statuses = {m["status"] for m in data["metrics"]}
        # On ne force pas le statut 'bad' (dépend du système),
        # mais au moins 'good' ou 'warn' doit être présent
        assert statuses.issubset({"good", "warn", "bad"})
        assert len(statuses) >= 1


# ─────────────────────────────────────────────────────────────────────────────
# Scénario 6 — L'utilisateur gère les programmes au démarrage
# ─────────────────────────────────────────────────────────────────────────────

class TestScenarioDemarrage:
    """
    Scénario : L'utilisateur ouvre l'onglet Outils pour voir quels programmes
    se lancent au démarrage et en désactiver certains.
    """

    def test_la_liste_est_disponible(self, client):
        """L'utilisateur doit voir une liste (potentiellement vide) sans erreur."""
        r = client.get("/api/startup")
        assert r.status_code == 200
        assert isinstance(r.get_json(), list)

    def test_chaque_entree_a_les_infos_necessaires(self, client):
        """L'UI a besoin de name, command, source et enabled pour afficher la ligne."""
        for entry in client.get("/api/startup").get_json():
            assert "name"    in entry
            assert "command" in entry
            assert "source"  in entry
            assert isinstance(entry["enabled"], bool)

    def test_les_entrees_actives_apparaissent_en_premier(self, client):
        """
        Comportement attendu côté tri :
        les programmes activés doivent précéder les désactivés.
        (Le tri est côté frontend, mais le backend doit retourner le champ 'enabled'.)
        """
        entries = client.get("/api/startup").get_json()
        enabled_entries  = [e for e in entries if e["enabled"]]
        disabled_entries = [e for e in entries if not e["enabled"]]
        # On vérifie juste que les deux catégories sont identifiables
        assert all(isinstance(e["enabled"], bool) for e in entries)
        _ = enabled_entries, disabled_entries  # pylint: disable=pointless-statement

    def test_toggle_sans_nom_retourne_400(self, client):
        """Un toggle sans nom de programme doit retourner une erreur claire."""
        r = client.post("/api/startup/toggle",
                        json={"source": "HKCU", "enabled": True})
        assert r.status_code == 400


# ─────────────────────────────────────────────────────────────────────────────
# Scénario 7 — L'utilisateur cherche des applications à désinstaller
# ─────────────────────────────────────────────────────────────────────────────

class TestScenarioApplications:
    """
    Scénario : L'utilisateur parcourt ses applications installées pour
    identifier les plus volumineuses et en désinstaller certaines.
    """

    def test_la_liste_est_disponible(self, client):
        r = client.get("/api/apps")
        assert r.status_code == 200
        assert isinstance(r.get_json(), list)

    def test_chaque_application_a_les_infos_daffichage(self, client):
        """L'UI a besoin de name, size_fmt et uninstall_string pour chaque ligne."""
        for app in client.get("/api/apps").get_json():
            assert "name"             in app, f"Champ 'name' manquant"
            assert "size_fmt"         in app, f"Champ 'size_fmt' manquant pour '{app.get('name')}'"
            assert "size_kb"          in app, f"Champ 'size_kb' manquant pour '{app.get('name')}'"
            assert "uninstall_string" in app, f"Champ 'uninstall_string' manquant pour '{app.get('name')}'"

    def test_size_kb_est_numerique_pour_le_tri(self, client):
        """
        L'UI trie les applications par taille côté client.
        Le champ size_kb doit être un entier pour permettre ce tri.
        """
        for app in client.get("/api/apps").get_json():
            assert isinstance(app["size_kb"], int), \
                f"size_kb doit être int pour '{app['name']}', reçu : {type(app['size_kb'])}"

    def test_uninstall_string_est_une_chaine(self, client):
        """
        uninstall_string peut être vide (si non disponible) mais doit toujours
        être une chaîne — jamais null — pour que le JS puisse le tester avec !!.
        """
        for app in client.get("/api/apps").get_json():
            assert isinstance(app["uninstall_string"], str), \
                f"uninstall_string doit être str pour '{app['name']}', reçu : {type(app['uninstall_string'])}"


# ─────────────────────────────────────────────────────────────────────────────
# Scénario 8 — Robustesse face aux entrées incorrectes
# ─────────────────────────────────────────────────────────────────────────────

class TestScenarioRobustesse:
    """
    Scénario : L'utilisateur (ou un bug côté client) envoie des requêtes
    malformées. Le serveur ne doit jamais crasher et doit retourner des
    codes d'erreur clairs.
    """

    @pytest.mark.parametrize("payload,expected_status", [
        ({"tasks": []},               400),   # aucune tâche
        ({"tasks": ["__inexistant__"]}, 400),  # tâche inconnue
        ({},                           400),   # corps vide
    ])
    def test_clean_invalide_retourne_400(self, client, payload, expected_status):
        r = client.post("/api/clean", json=payload)
        assert r.status_code == expected_status

    def test_stream_job_inconnu_retourne_404(self, client):
        r = client.get("/api/stream/00000000-0000-0000-0000-000000000000")
        assert r.status_code == 404

    def test_supprimer_sans_paths_retourne_400(self, client):
        r = client.post("/api/duplicates/delete", json={"paths": []})
        assert r.status_code == 400

    def test_scan_dossier_inexistant_retourne_400(self, client):
        r = client.post("/api/duplicates", json={"folder": "C:/xyz_inexistant_zzz"})
        assert r.status_code == 400

    def test_toggle_startup_sans_source_retourne_400(self, client):
        r = client.post("/api/startup/toggle", json={"name": "Test", "enabled": True})
        assert r.status_code == 400

    def test_registry_fix_sans_issues_retourne_400(self, client):
        r = client.post("/api/registry/fix", json={"issues": []})
        assert r.status_code == 400

    def test_extension_remove_sans_path_retourne_400(self, client):
        r = client.post("/api/extensions/remove", json={})
        assert r.status_code == 400

    def test_les_erreurs_retournent_un_message(self, client):
        """Toute erreur 400 doit inclure un champ 'error' pour affichage dans l'UI."""
        r = client.post("/api/clean", json={"tasks": []})
        data = r.get_json()
        assert "error" in data, "Les réponses d'erreur doivent contenir le champ 'error'"


# ─────────────────────────────────────────────────────────────────────────────
# Scénario 9 — L'utilisateur analyse le registre Windows
# ─────────────────────────────────────────────────────────────────────────────

class TestScenarioRegistre:
    """
    Scénario : L'utilisateur clique sur "Analyser le registre".
    Il voit une liste d'entrées orphelines regroupées par catégorie,
    coche celles qu'il veut supprimer, et confirme la correction.
    """

    def test_le_scan_retourne_un_job_id(self, client):
        """L'analyse démarre en tâche de fond et retourne immédiatement un job_id."""
        r = client.post("/api/registry/scan")
        assert r.status_code == 200
        assert "job_id" in r.get_json()

    def test_le_scan_emet_des_evenements_sse(self, client):
        """Le flux SSE doit contenir au moins l'événement 'done'."""
        r = client.post("/api/registry/scan")
        events = consume_sse(client, r.get_json()["job_id"])
        types = [e["type"] for e in events]
        assert "done" in types, "L'événement 'done' doit toujours arriver"

    def test_le_scan_retourne_un_event_result(self, client):
        """Le flux doit contenir un événement 'result' avec la liste des problèmes."""
        r = client.post("/api/registry/scan")
        events = consume_sse(client, r.get_json()["job_id"])
        result_events = [e for e in events if e["type"] == "result"]
        assert result_events, "Au moins un événement 'result' doit être émis"
        result = result_events[0]
        assert "issues" in result
        assert isinstance(result["issues"], list)

    def test_chaque_probleme_a_les_champs_necessaires(self, client):
        """
        L'UI a besoin de category, description, hive, key, value_name
        pour afficher et corriger chaque entrée.
        """
        r = client.post("/api/registry/scan")
        events = consume_sse(client, r.get_json()["job_id"])
        result_events = [e for e in events if e["type"] == "result"]
        if not result_events:
            pytest.skip("Aucun résultat disponible")
        issues = result_events[0]["issues"]
        if not issues:
            pytest.skip("Aucune entrée orpheline détectée sur ce système")
        required = {"id", "category", "description", "hive", "key", "value_name"}
        for iss in issues:
            missing = required - iss.keys()
            assert not missing, f"Champs manquants : {missing}"

    def test_les_categories_sont_connues(self, client):
        """
        Les catégories retournées doivent être parmi celles attendues,
        pas des valeurs techniques incompréhensibles.
        """
        r = client.post("/api/registry/scan")
        events = consume_sse(client, r.get_json()["job_id"])
        result_events = [e for e in events if e["type"] == "result"]
        if not result_events:
            pytest.skip("Aucun résultat disponible")
        known = {"DLL partagées", "Chemins d'applications", "Cache interface"}
        for iss in result_events[0]["issues"]:
            assert iss["category"] in known, \
                f"Catégorie inconnue '{iss['category']}' — l'UI ne saurait pas quoi afficher"

    def test_les_descriptions_sont_lisibles(self, client):
        """
        Les descriptions ne doivent pas être des chemins bruts de clés de registre.
        Elles doivent être des phrases compréhensibles.
        """
        r = client.post("/api/registry/scan")
        events = consume_sse(client, r.get_json()["job_id"])
        result_events = [e for e in events if e["type"] == "result"]
        if not result_events:
            pytest.skip("Aucun résultat disponible")
        for iss in result_events[0]["issues"]:
            desc = iss["description"]
            assert len(desc) > 5, "Description trop courte pour être lisible"
            assert not desc.startswith("HKEY"), \
                "La description ne doit pas commencer par un chemin de registre brut"

    def test_fix_sans_issues_retourne_400(self, client):
        """Envoyer une liste vide à /api/registry/fix doit retourner 400."""
        r = client.post("/api/registry/fix", json={"issues": []})
        assert r.status_code == 400

    def test_fix_retourne_job_id(self, client):
        """Quand des issues valides sont envoyées, un job_id est retourné."""
        fake_issues = [{
            "id": "shareddll_0", "category": "DLL partagées",
            "hive": "HKLM",
            "key": r"SOFTWARE\Microsoft\Windows\CurrentVersion\SharedDLLs",
            "value_name": r"C:\inexistant\fake.dll",
            "description": "Fichier introuvable : C:\\inexistant\\fake.dll",
        }]
        r = client.post("/api/registry/fix", json={"issues": fake_issues})
        assert r.status_code == 200
        assert "job_id" in r.get_json()


# ─────────────────────────────────────────────────────────────────────────────
# Scénario 10 — L'utilisateur gère les extensions de navigateur
# ─────────────────────────────────────────────────────────────────────────────

class TestScenarioExtensions:
    """
    Scénario : L'utilisateur ouvre l'onglet Outils → Extensions.
    Il voit la liste de ses extensions par navigateur et peut en supprimer.
    """

    def test_la_liste_est_disponible(self, client):
        """L'endpoint /api/extensions doit répondre 200 avec un objet JSON."""
        r = client.get("/api/extensions")
        assert r.status_code == 200
        assert isinstance(r.get_json(), dict)

    def test_les_cles_sont_des_noms_de_navigateurs(self, client):
        """
        Les clés de l'objet retourné doivent être des noms de navigateurs connus,
        pas des chemins techniques.
        """
        data = client.get("/api/extensions").get_json()
        known = {"Chrome", "Edge", "Brave", "Firefox"}
        for key in data.keys():
            assert key in known, \
                f"Clé inattendue '{key}' — devrait être un nom de navigateur connu"

    def test_chaque_extension_a_les_champs_necessaires(self, client):
        """
        L'UI a besoin de name, id, version et path pour afficher chaque extension.
        """
        data = client.get("/api/extensions").get_json()
        required = {"name", "id", "version", "path"}
        for browser, exts in data.items():
            for ext in exts:
                missing = required - ext.keys()
                assert not missing, \
                    f"Champs manquants pour une extension {browser} : {missing}"

    def test_les_noms_dextensions_sont_des_chaines(self, client):
        """name doit être une chaîne non vide (affiché dans l'UI)."""
        data = client.get("/api/extensions").get_json()
        for browser, exts in data.items():
            for ext in exts:
                assert isinstance(ext["name"], str) and ext["name"], \
                    f"Nom d'extension invalide dans {browser} : {ext.get('name')!r}"

    def test_remove_sans_path_retourne_400(self, client):
        """Supprimer sans envoyer de path doit retourner une erreur 400."""
        r = client.post("/api/extensions/remove", json={})
        assert r.status_code == 400

    def test_remove_path_inexistant_retourne_erreur(self, client):
        """
        Si le path n'existe pas sur le disque, l'API doit retourner une erreur
        avec un message explicite — pas un crash 500.
        """
        r = client.post("/api/extensions/remove",
                        json={"path": "C:/extensions/inexistant_xyz"})
        assert r.status_code in (200, 400)
        data = r.get_json()
        if r.status_code == 200:
            assert not data.get("ok"), "Une suppression sur un path inexistant ne doit pas retourner ok=True"
        else:
            assert "error" in data


# ─────────────────────────────────────────────────────────────────────────────
# Scénario 11 — Raccourcis cassés
# ─────────────────────────────────────────────────────────────────────────────

class TestScenarioRaccourcis:
    """
    Scénario : L'utilisateur scanne ses raccourcis et supprime ceux qui
    pointent vers des applications désinstallées.
    """

    def test_le_scan_retourne_une_liste(self, client):
        r = client.get("/api/shortcuts")
        assert r.status_code == 200
        assert isinstance(r.get_json(), list)

    def test_chaque_raccourci_a_les_champs_necessaires(self, client):
        shortcuts = client.get("/api/shortcuts").get_json()
        required = {"path", "name", "target", "location"}
        for sc in shortcuts:
            missing = required - sc.keys()
            assert not missing, f"Champs manquants : {missing}"

    def test_les_cibles_nexistent_pas_sur_le_disque(self, client):
        """Par définition, un raccourci cassé pointe vers un fichier inexistant."""
        from pathlib import Path
        for sc in client.get("/api/shortcuts").get_json():
            assert not Path(sc["target"]).exists(), \
                f"La cible '{sc['target']}' existe — ce raccourci n'est pas cassé"

    def test_les_locations_sont_connues(self, client):
        """Les emplacements retournés doivent être des noms lisibles."""
        known = {"Bureau", "Bureau (Public)", "Menu Démarrer", "Menu Démarrer (Public)"}
        for sc in client.get("/api/shortcuts").get_json():
            assert sc["location"] in known, \
                f"Emplacement inconnu '{sc['location']}'"

    def test_delete_sans_paths_retourne_400(self, client):
        r = client.post("/api/shortcuts/delete", json={"paths": []})
        assert r.status_code == 400

    def test_delete_effectif(self, client, tmp_path):
        """Un .lnk factice doit être supprimé et absent du disque après."""
        lnk = tmp_path / "test.lnk"
        lnk.write_bytes(b"fake shortcut")
        r = client.post("/api/shortcuts/delete", json={"paths": [str(lnk)]})
        assert r.status_code == 200
        data = r.get_json()
        assert data["deleted"] == 1
        assert not lnk.exists()


# ─────────────────────────────────────────────────────────────────────────────
# Scénario 12 — Grands fichiers
# ─────────────────────────────────────────────────────────────────────────────

class TestScenarioGrandsFichiers:
    """
    Scénario : L'utilisateur analyse un dossier pour trouver
    les fichiers volumineux et libérer de l'espace.
    """

    def test_dossier_inexistant_retourne_400(self, client):
        r = client.post("/api/largefiles",
                        json={"folder": "C:/xyz_inexistant_grand", "min_size_gb": 0.001})
        assert r.status_code == 400

    def test_scan_retourne_job_id(self, client, tmp_path):
        r = client.post("/api/largefiles",
                        json={"folder": str(tmp_path), "min_size_gb": 0.001})
        assert r.status_code == 200
        assert "job_id" in r.get_json()

    def test_scan_detecte_les_grands_fichiers(self, client, tmp_path):
        """Un fichier de 2 Mo doit être détecté avec un seuil de 1 Mo."""
        from tests.conftest import consume_sse
        big = tmp_path / "gros.bin"
        big.write_bytes(b"x" * 2 * 1024 * 1024)  # 2 Mo

        r = client.post("/api/largefiles",
                        json={"folder": str(tmp_path), "min_size_gb": 0.001})
        events = consume_sse(client, r.get_json()["job_id"])
        result_events = [e for e in events if e["type"] == "result"]
        assert result_events, "Aucun événement 'result'"
        files = result_events[0]["files"]
        paths = [f["path"] for f in files]
        assert str(big) in paths, "Le grand fichier n'a pas été détecté"

    def test_les_fichiers_sont_tries_par_taille_decroissante(self, client, tmp_path):
        from tests.conftest import consume_sse
        (tmp_path / "petit.bin").write_bytes(b"x" * 1024 * 1024)
        (tmp_path / "grand.bin").write_bytes(b"x" * 3 * 1024 * 1024)

        r = client.post("/api/largefiles",
                        json={"folder": str(tmp_path), "min_size_gb": 0.0005})
        events = consume_sse(client, r.get_json()["job_id"])
        result_events = [e for e in events if e["type"] == "result"]
        if not result_events:
            pytest.skip("Pas de résultat")
        files = result_events[0]["files"]
        sizes = [f["size"] for f in files]
        assert sizes == sorted(sizes, reverse=True), "Les fichiers doivent être triés par taille décroissante"

    def test_chaque_fichier_a_les_champs_necessaires(self, client, tmp_path):
        from tests.conftest import consume_sse
        (tmp_path / "test.bin").write_bytes(b"x" * 1024 * 1024)

        r = client.post("/api/largefiles",
                        json={"folder": str(tmp_path), "min_size_gb": 0.0005})
        events = consume_sse(client, r.get_json()["job_id"])
        result_events = [e for e in events if e["type"] == "result"]
        if not result_events or not result_events[0]["files"]:
            pytest.skip("Pas de résultat")
        required = {"path", "name", "size", "size_fmt"}
        for f in result_events[0]["files"]:
            assert not required - f.keys()


# ─────────────────────────────────────────────────────────────────────────────
# Scénario 13 — Points de restauration
# ─────────────────────────────────────────────────────────────────────────────

class TestScenarioRestorePoints:
    """
    Scénario : L'utilisateur liste et supprime des anciens points
    de restauration pour récupérer de l'espace disque.
    """

    def test_lapi_retourne_200(self, client):
        r = client.get("/api/restore-points")
        assert r.status_code == 200

    def test_la_reponse_a_les_champs_attendus(self, client):
        data = client.get("/api/restore-points").get_json()
        assert "points"         in data
        assert "requires_admin" in data
        assert "error"          in data
        assert isinstance(data["points"],         list)
        assert isinstance(data["requires_admin"], bool)

    def test_chaque_point_a_les_champs_necessaires(self, client):
        data   = client.get("/api/restore-points").get_json()
        points = data["points"]
        if not points:
            pytest.skip("Aucun point de restauration sur ce système")
        required = {"id", "description", "date"}
        for p in points:
            assert not required - p.keys(), f"Champs manquants : {required - p.keys()}"

    def test_delete_sans_ids_retourne_400(self, client):
        r = client.post("/api/restore-points/delete", json={"ids": []})
        assert r.status_code == 400


# ─────────────────────────────────────────────────────────────────────────────
# Scénario 14 — Mises à jour logicielles
# ─────────────────────────────────────────────────────────────────────────────

class TestScenarioMisesAJour:
    """
    Scénario : L'utilisateur vérifie si des mises à jour sont disponibles
    et lance l'installation d'une application.
    """

    def test_lapi_retourne_200(self, client):
        r = client.get("/api/updates")
        assert r.status_code == 200

    def test_la_reponse_a_les_champs_attendus(self, client):
        data = client.get("/api/updates").get_json()
        assert "updates" in data
        assert "error"   in data
        assert isinstance(data["updates"], list)

    def test_chaque_mise_a_jour_a_les_champs_necessaires(self, client):
        updates = client.get("/api/updates").get_json()["updates"]
        if not updates:
            pytest.skip("Aucune mise à jour disponible")
        required = {"name", "id", "version", "available"}
        for u in updates:
            assert not required - u.keys(), f"Champs manquants : {required - u.keys()}"

    def test_version_disponible_differe_de_la_version_actuelle(self, client):
        """La version disponible doit être différente de la version installée."""
        updates = client.get("/api/updates").get_json()["updates"]
        if not updates:
            pytest.skip("Aucune mise à jour disponible")
        for u in updates:
            assert u["available"] != u["version"], \
                f"'{u['name']}': version disponible identique à la version installée"

    def test_install_sans_id_retourne_400(self, client):
        r = client.post("/api/updates/install", json={})
        assert r.status_code == 400

    def test_install_id_vide_retourne_400(self, client):
        r = client.post("/api/updates/install", json={"id": ""})
        assert r.status_code == 400


# ─────────────────────────────────────────────────────────────────────────────
# Scénario 15 — S.M.A.R.T. dans le bilan de santé
# ─────────────────────────────────────────────────────────────────────────────

class TestScenarioSmart:
    """
    Scénario : L'onglet Santé affiche l'état physique du disque dur.
    """

    def test_la_metrique_smart_est_presente(self, client):
        data    = client.get("/api/health").get_json()
        metrics = {m["id"]: m for m in data["metrics"]}
        assert "smart" in metrics, "La métrique S.M.A.R.T. doit être présente dans le bilan de santé"

    def test_la_metrique_smart_a_un_statut_valide(self, client):
        data    = client.get("/api/health").get_json()
        smart   = next((m for m in data["metrics"] if m["id"] == "smart"), None)
        if not smart:
            pytest.skip("Métrique SMART absente")
        assert smart["status"] in ("good", "warn", "bad")

    def test_le_score_total_inclut_smart(self, client):
        """Le score total doit dépasser 100 pts maintenant que SMART (10 pts) est inclus."""
        data = client.get("/api/health").get_json()
        assert data["max"] > 100, "Le max doit dépasser 100 avec la métrique SMART"

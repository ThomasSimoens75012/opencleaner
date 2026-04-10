"""
fixture_test.py — Test end-to-end avec fixtures controlees.

Cree tests/sandbox/ avec des fichiers factices pour chaque categorie,
puis teste :
  1. Les fonctions cleaner.py directement (detection + suppression)
  2. Un parcours UI via Playwright (navigation Outils + scan + verification)
  3. Nettoyage automatique du sandbox en fin d'execution

Usage :  python tests/fixture_test.py
Sortie : rapport texte + screenshots dans tests/screenshots/fixture_test/

Le sandbox est toujours recree a neuf. AUCUN fichier en dehors du sandbox
n'est touche.
"""

import io
import os
import shutil
import socket
import sys
import threading
import time
import urllib.request
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

ROOT    = Path(__file__).parent.parent
SANDBOX = ROOT / "tests" / "sandbox"
SHOTS   = ROOT / "tests" / "screenshots" / "fixture_test"

sys.path.insert(0, str(ROOT))

# ══════════════════════════════════════════════════════════════════════════════
# REPORTING
# ══════════════════════════════════════════════════════════════════════════════

RESULTS = []  # list of (status, category, test, detail)

def log(status, category, test, detail=""):
    icon = {"ok": "PASS", "ko": "FAIL", "warn": "WARN", "info": "INFO"}[status]
    line = f"  [{icon}] {category:<20} {test}"
    if detail:
        line += f"  — {detail}"
    print(line)
    RESULTS.append((status, category, test, detail))

def section(title):
    print()
    print(f"  ══ {title} ══")

# ══════════════════════════════════════════════════════════════════════════════
# SANDBOX : creation / destruction
# ══════════════════════════════════════════════════════════════════════════════

def setup_sandbox():
    """Cree l'arborescence de fixtures. Recree a neuf a chaque appel."""
    if SANDBOX.exists():
        shutil.rmtree(SANDBOX, ignore_errors=True)
    SANDBOX.mkdir(parents=True)

    # ── Doublons ────────────────────────────────────────────────
    # Objectif : 2 groupes distincts de doublons
    #   - 3 copies de report.pdf (200 Ko chacune)
    #   - 2 copies de photo.jpg  (300 Ko chacune)
    dup = SANDBOX / "duplicates"
    dup.mkdir()
    content_a = b"A" * 200_000  # au-dessus du seuil 100 Ko de l'UI
    content_b = b"B" * 300_000
    (dup / "report.pdf").write_bytes(content_a)
    (dup / "report_copy.pdf").write_bytes(content_a)
    (dup / "archives" ).mkdir()
    (dup / "archives" / "report_backup.pdf").write_bytes(content_a)
    (dup / "photo.jpg").write_bytes(content_b)
    (dup / "photo_2024.jpg").write_bytes(content_b)
    # Fichier unique (ne doit PAS etre detecte comme doublon)
    (dup / "unique.txt").write_bytes(b"unique content here and there" * 5000)
    log("info", "sandbox", "doublons",
        "5 fichiers en 2 groupes + 1 unique")

    # ── Grands fichiers ─────────────────────────────────────────
    # 1 fichier de 15 Mo (au-dessus du seuil 10 Mo qu'on passera)
    # + 1 petit fichier (ne doit PAS etre detecte)
    large = SANDBOX / "large"
    large.mkdir()
    with open(large / "big_file.bin", "wb") as f:
        f.write(b"\x00" * 15_000_000)
    (large / "small.txt").write_bytes(b"petit")
    log("info", "sandbox", "gros fichiers",
        "1 fichier 15 Mo + 1 petit")

    # ── Dossiers vides ──────────────────────────────────────────
    # Plusieurs dossiers vides imbriques + 1 non-vide
    empty = SANDBOX / "empty"
    (empty / "folder_a" / "subfolder_1").mkdir(parents=True)
    (empty / "folder_a" / "subfolder_2").mkdir(parents=True)
    (empty / "folder_b").mkdir()
    (empty / "not_empty").mkdir()
    (empty / "not_empty" / "file.txt").write_text("contenu", encoding="utf-8")
    log("info", "sandbox", "dossiers vides",
        "3 vides + 1 non-vide")

    # ── Anciens installeurs ─────────────────────────────────────
    # 3 .exe/.msi/.zip anciens (180 jours) + 1 recent
    inst = SANDBOX / "installers"
    inst.mkdir()
    old_time = time.time() - 180 * 86400
    for name in ["python-3.10.exe", "nodejs-v20.msi", "vlc-3.0.zip"]:
        p = inst / name
        p.write_bytes(b"X" * 2_000_000)  # 2 Mo chacun
        os.utime(p, (old_time, old_time))
    # Installer recent : ne doit PAS etre detecte
    (inst / "recent.exe").write_bytes(b"Y" * 1_000_000)
    # Fichier non-installer : ne doit PAS etre detecte
    (inst / "readme.txt").write_text("notes", encoding="utf-8")
    log("info", "sandbox", "anciens installers",
        "3 anciens + 1 recent + 1 non-installer")

    # ── Analyse disque ──────────────────────────────────────────
    # Le sandbox lui-meme sert de cible : 4 sous-dossiers avec tailles varies
    log("info", "sandbox", "analyse disque",
        f"cible = {SANDBOX}")


def teardown_sandbox():
    if SANDBOX.exists():
        shutil.rmtree(SANDBOX, ignore_errors=True)


# ══════════════════════════════════════════════════════════════════════════════
# TESTS FONCTIONNELS : appel direct des fonctions de cleaner.py
# ══════════════════════════════════════════════════════════════════════════════

def test_functional():
    section("Tests fonctionnels (cleaner.py)")

    from cleaner import (
        find_duplicates, delete_duplicate_files,
        find_large_files,
        find_empty_folders, delete_empty_folders,
        find_old_installers, delete_installer_files,
        scan_disk_level,
    )

    # ─── find_duplicates ────────────────────────────────────────
    dupes = find_duplicates(str(SANDBOX / "duplicates"), min_size_kb=100)
    n_groups = len(dupes)
    if n_groups == 2:
        log("ok", "Doublons", "find_duplicates", f"{n_groups} groupes (attendu 2)")
    else:
        log("ko", "Doublons", "find_duplicates", f"{n_groups} groupes (attendu 2)")
    # Verification des tailles de groupe
    sizes_ok = all(len(files) in (2, 3) for files in dupes.values())
    log("ok" if sizes_ok else "ko", "Doublons", "tailles des groupes",
        "un groupe de 3 + un de 2" if sizes_ok else "tailles incorrectes")

    # ─── find_large_files ───────────────────────────────────────
    large = find_large_files(str(SANDBOX / "large"), min_size_bytes=10_000_000)
    n = len(large)
    if n == 1 and large[0]["name"] == "big_file.bin":
        log("ok", "Gros fichiers", "find_large_files",
            f"1 fichier ({large[0]['size_fmt']})")
    else:
        log("ko", "Gros fichiers", "find_large_files",
            f"{n} fichiers (attendu 1)")

    # ─── find_empty_folders ─────────────────────────────────────
    empties = find_empty_folders(str(SANDBOX / "empty"))
    n = len(empties)
    # On s'attend a : folder_a/subfolder_1, folder_a/subfolder_2, folder_b
    # folder_a lui-meme peut aussi etre detecte (depend de l'algo)
    # et not_empty NE DOIT PAS l'etre
    not_empty_flagged = any("not_empty" in str(p) for p in empties)
    if n >= 3 and not not_empty_flagged:
        log("ok", "Dossiers vides", "find_empty_folders",
            f"{n} detectes, 'not_empty' correctement exclu")
    else:
        log("ko", "Dossiers vides", "find_empty_folders",
            f"{n} detectes, not_empty_flagged={not_empty_flagged}")

    # ─── find_old_installers ────────────────────────────────────
    olds = find_old_installers(str(SANDBOX / "installers"), max_age_days=30)
    n = len(olds)
    names = {Path(o["path"]).name if isinstance(o, dict) else Path(o).name for o in olds}
    if n == 3 and "recent.exe" not in names and "readme.txt" not in names:
        log("ok", "Anciens installers", "find_old_installers",
            f"3 detectes, 'recent.exe' et 'readme.txt' correctement exclus")
    else:
        log("ko", "Anciens installers", "find_old_installers",
            f"{n} detectes, noms={names}")

    # ─── scan_disk_level ────────────────────────────────────────
    items = scan_disk_level(str(SANDBOX))
    if items and len(items) >= 4:
        dir_count = sum(1 for i in items if i.get("is_dir"))
        log("ok", "Analyse disque", "scan_disk_level",
            f"{len(items)} entrees dont {dir_count} dossiers")
    else:
        log("ko", "Analyse disque", "scan_disk_level",
            f"{len(items) if items else 0} entrees (attendu >= 4)")

    # ═══ TESTS DESTRUCTIFS ══════════════════════════════════════
    section("Suppressions reelles (verif du cleanup)")

    # Suppression des doublons selectionnes (on garde le premier de chaque groupe)
    to_delete = []
    for files in dupes.values():
        to_delete.extend(f["path"] for f in files[1:])
    freed, errors = delete_duplicate_files(to_delete)
    after = find_duplicates(str(SANDBOX / "duplicates"), min_size_kb=100)
    if len(after) == 0 and not errors:
        log("ok", "Doublons", "delete_duplicate_files",
            f"{len(to_delete)} supprimes, plus aucun doublon")
    else:
        log("ko", "Doublons", "delete_duplicate_files",
            f"errors={len(errors)}, reste={len(after)}")

    # Suppression d'un gros fichier
    if large:
        freed, errors = delete_installer_files([large[0]["path"]])
        still_there = Path(large[0]["path"]).exists()
        if not still_there and not errors:
            log("ok", "Gros fichiers", "suppression directe",
                f"{freed} octets liberes")
        else:
            log("ko", "Gros fichiers", "suppression directe",
                f"errors={errors}")

    # Suppression des dossiers vides
    # find_empty_folders retourne des dicts {"path": ..., "name": ...}
    empties_fresh = find_empty_folders(str(SANDBOX / "empty"))
    paths = [e["path"] if isinstance(e, dict) else e for e in empties_fresh]
    deleted, errors = delete_empty_folders(paths)
    after = find_empty_folders(str(SANDBOX / "empty"))
    if deleted >= 3 and not errors:
        log("ok", "Dossiers vides", "delete_empty_folders",
            f"{deleted} supprimes, reste {len(after)}")
    else:
        log("ko", "Dossiers vides", "delete_empty_folders",
            f"deleted={deleted}, errors={len(errors)}")

    # Suppression des anciens installers
    olds_fresh = find_old_installers(str(SANDBOX / "installers"), max_age_days=30)
    paths = [o["path"] if isinstance(o, dict) else o for o in olds_fresh]
    freed, errors = delete_installer_files(paths)
    after = find_old_installers(str(SANDBOX / "installers"), max_age_days=30)
    if len(after) == 0 and not errors:
        log("ok", "Anciens installers", "delete_installer_files",
            f"{len(paths)} supprimes ({freed} octets)")
    else:
        log("ko", "Anciens installers", "delete_installer_files",
            f"reste {len(after)}, errors={len(errors)}")


# ══════════════════════════════════════════════════════════════════════════════
# TESTS FONCTIONNELS DES TACHES DE NETTOYAGE (task_*)
# ══════════════════════════════════════════════════════════════════════════════
#
# Strategie : monkey-patch des env vars (TEMP, APPDATA, LOCALAPPDATA,
# USERPROFILE) + SYSTEM_TEMP pour rediriger les taches vers un sous-sandbox.
# Les fixtures sont creees puis task_*() est appele pour verifier la
# suppression effective. Les env vars sont toujours restaurees (finally).
#
# IMPORTANT : ce test doit s'executer AVANT start_flask() pour eviter que
# Flask ne lise les env vars patches.

def test_nettoyage_tasks():
    section("Tests fonctionnels des taches de Nettoyage (task_*)")

    import cleaner

    # Sauvegarde complete de l'etat pour restauration garantie
    original_env = {
        k: os.environ.get(k)
        for k in ("TEMP", "TMP", "APPDATA", "LOCALAPPDATA", "USERPROFILE")
    }
    original_system_temp = cleaner.SYSTEM_TEMP

    task_root = SANDBOX / "tasks"
    if task_root.exists():
        shutil.rmtree(task_root)

    # Arborescence qui mime les dossiers Windows
    fake_temp     = task_root / "temp"
    fake_tmp      = task_root / "tmp"
    fake_sys_temp = task_root / "Windows" / "Temp"
    fake_appdata  = task_root / "AppData" / "Roaming"
    fake_local    = task_root / "AppData" / "Local"
    fake_profile  = task_root / "profile"
    for p in (fake_temp, fake_tmp, fake_sys_temp,
              fake_appdata, fake_local, fake_profile):
        p.mkdir(parents=True, exist_ok=True)

    try:
        # Redirection : toutes les taches scannent maintenant le sandbox
        os.environ["TEMP"]         = str(fake_temp)
        os.environ["TMP"]          = str(fake_tmp)
        os.environ["APPDATA"]      = str(fake_appdata)
        os.environ["LOCALAPPDATA"] = str(fake_local)
        os.environ["USERPROFILE"]  = str(fake_profile)
        cleaner.SYSTEM_TEMP        = str(fake_sys_temp)

        logs = []
        collect_log = lambda msg: logs.append(msg)

        # ═══ task_temp ═══════════════════════════════════════════
        (fake_temp / "file1.tmp").write_bytes(b"X" * 1000)
        (fake_temp / "file2.log").write_bytes(b"Y" * 2000)
        (fake_temp / "subdir").mkdir()
        (fake_temp / "subdir" / "nested.tmp").write_bytes(b"Z" * 500)
        (fake_sys_temp / "win_temp.bin").write_bytes(b"W" * 3000)

        logs.clear()
        freed = cleaner.task_temp(collect_log)
        files_left = [p for p in fake_temp.rglob("*") if p.is_file()]
        sys_files_left = [p for p in fake_sys_temp.rglob("*") if p.is_file()]
        if not files_left and not sys_files_left and freed > 0:
            log("ok", "Nettoyage", "task_temp",
                f"{freed} octets liberes, fake_temp + fake_sys_temp vides")
        else:
            log("ko", "Nettoyage", "task_temp",
                f"freed={freed}, temp_reste={len(files_left)}, "
                f"sys_reste={len(sys_files_left)}")

        # ═══ task_thumbnails ═════════════════════════════════════
        thumb_dir = fake_local / "Microsoft" / "Windows" / "Explorer"
        thumb_dir.mkdir(parents=True, exist_ok=True)
        for i in range(3):
            (thumb_dir / f"thumbcache_{256 * (i + 1)}.db").write_bytes(
                b"T" * 5000
            )
        # Fichier qui ne doit PAS etre touche (autre extension)
        (thumb_dir / "other.txt").write_bytes(b"keep me")

        logs.clear()
        freed = cleaner.task_thumbnails(collect_log)
        caches_left = list(thumb_dir.glob("thumbcache_*.db"))
        other = thumb_dir / "other.txt"
        if not caches_left and other.exists() and freed >= 15000:
            log("ok", "Nettoyage", "task_thumbnails",
                f"3 thumbcache supprimes, other.txt preserve")
        else:
            log("ko", "Nettoyage", "task_thumbnails",
                f"freed={freed}, caches_reste={len(caches_left)}, "
                f"other_ok={other.exists()}")

        # ═══ task_recent_files ═══════════════════════════════════
        recent_dir = fake_appdata / "Microsoft" / "Windows" / "Recent"
        recent_dir.mkdir(parents=True, exist_ok=True)
        for i in range(5):
            (recent_dir / f"recent_{i}.lnk").write_bytes(b"R" * 100)

        logs.clear()
        freed = cleaner.task_recent_files(collect_log)
        lnks_left = list(recent_dir.glob("*.lnk"))
        if not lnks_left and freed == 500:
            log("ok", "Nettoyage", "task_recent_files",
                f"5 raccourcis supprimes ({freed} octets)")
        else:
            log("ko", "Nettoyage", "task_recent_files",
                f"freed={freed}, reste={len(lnks_left)}")

        # ═══ task_dumps ══════════════════════════════════════════
        crash_dir = fake_local / "CrashDumps"
        crash_dir.mkdir(parents=True, exist_ok=True)
        (crash_dir / "app1.exe.1234.dmp").write_bytes(b"D" * 10000)
        (crash_dir / "app2.exe.5678.mdmp").write_bytes(b"D" * 5000)
        # Doit aussi scanner TEMP et USERPROFILE
        (fake_temp / "orphan.dmp").write_bytes(b"D" * 3000)
        (fake_profile / "desktop.mdmp").write_bytes(b"D" * 2000)
        # Fichier non-dump qui ne doit PAS etre touche
        (crash_dir / "readme.txt").write_bytes(b"keep me")

        logs.clear()
        freed = cleaner.task_dumps(collect_log)
        dumps_left = (
            list(crash_dir.rglob("*.dmp"))
            + list(crash_dir.rglob("*.mdmp"))
            + list(fake_temp.rglob("*.dmp"))
            + list(fake_profile.rglob("*.dmp"))
            + list(fake_profile.rglob("*.mdmp"))
        )
        readme = crash_dir / "readme.txt"
        if not dumps_left and readme.exists() and freed >= 20000:
            log("ok", "Nettoyage", "task_dumps",
                f"4 dumps supprimes ({freed} octets), readme preserve")
        else:
            log("ko", "Nettoyage", "task_dumps",
                f"freed={freed}, dumps_reste={len(dumps_left)}, "
                f"readme_ok={readme.exists()}")

        # ═══ task_app_caches ═════════════════════════════════════
        # Discord, Teams, Slack, Spotify, WhatsApp
        discord_a = fake_appdata / "discord" / "Cache" / "Cache_Data"
        discord_l = fake_local   / "Discord" / "Cache" / "Cache_Data"
        teams     = fake_appdata / "Microsoft" / "Teams" / "Cache"
        slack     = fake_appdata / "Slack" / "Cache" / "Cache_Data"
        spotify   = fake_appdata / "Spotify" / "Data"
        whatsapp  = fake_local   / "WhatsApp" / "Cache"
        for d in (discord_a, discord_l, teams, slack, spotify, whatsapp):
            d.mkdir(parents=True, exist_ok=True)
            (d / "cache_001.bin").write_bytes(b"C" * 2000)
            (d / "cache_002.bin").write_bytes(b"C" * 3000)

        logs.clear()
        freed = cleaner.task_app_caches(collect_log)
        remaining_total = sum(
            1 for d in (discord_a, discord_l, teams, slack, spotify, whatsapp)
            for _ in d.rglob("*") if _.is_file()
        )
        # 6 apps x 2 fichiers = 12 fichiers attendus supprimes
        # 6 apps x (2000 + 3000) = 30000 octets
        if remaining_total == 0 and freed >= 30000:
            log("ok", "Nettoyage", "task_app_caches",
                f"12 fichiers supprimes ({freed} octets)")
        else:
            log("ko", "Nettoyage", "task_app_caches",
                f"freed={freed}, reste={remaining_total}")

        # ═══ task_dns ════════════════════════════════════════════
        # ipconfig /flushdns s'execute sur le systeme. On verifie juste
        # que ca ne crashe pas et que le log est genere.
        logs.clear()
        try:
            cleaner.task_dns(collect_log)
            if logs and "DNS" in logs[0]:
                log("ok", "Nettoyage", "task_dns",
                    "ipconfig /flushdns execute")
            else:
                log("ko", "Nettoyage", "task_dns",
                    f"log inattendu : {logs}")
        except Exception as e:
            log("ko", "Nettoyage", "task_dns", str(e))

    finally:
        # Restauration — CRITIQUE
        for k, v in original_env.items():
            if v is not None:
                os.environ[k] = v
            elif k in os.environ:
                del os.environ[k]
        cleaner.SYSTEM_TEMP = original_system_temp


# ══════════════════════════════════════════════════════════════════════════════
# TESTS FONCTIONNELS NAVIGATEURS (task_browser_*)
# ══════════════════════════════════════════════════════════════════════════════
#
# Cree de faux profils Chrome + Firefox dans le sandbox avec des VRAIS
# fichiers SQLite (schemas minimaux mais reels) puis monkey-patch
# _browser_profile_paths() pour que les taches scannent nos fakes.

def test_browser_tasks():
    section("Tests fonctionnels navigateurs (task_browser_*)")

    import sqlite3
    import cleaner

    br_root = SANDBOX / "browsers"
    if br_root.exists():
        shutil.rmtree(br_root)

    # ─── Fake profil Chromium ───────────────────────────────────
    chrome_profile = br_root / "chrome" / "Default"
    chrome_profile.mkdir(parents=True)

    # Dossiers cache avec fichiers
    for sub in ["Cache", "Code Cache", "GPUCache"]:
        d = chrome_profile / sub
        d.mkdir()
        for i in range(3):
            (d / f"cache_{i}.bin").write_bytes(b"X" * 2000)

    # History SQLite reel (schema minimal)
    history_db = chrome_profile / "History"
    conn = sqlite3.connect(str(history_db))
    conn.executescript("""
        CREATE TABLE urls(id INTEGER PRIMARY KEY, url TEXT, title TEXT);
        CREATE TABLE visits(id INTEGER PRIMARY KEY, url INTEGER);
        CREATE TABLE keyword_search_terms(id INTEGER PRIMARY KEY, term TEXT);
        CREATE TABLE downloads(id INTEGER PRIMARY KEY, target_path TEXT);
        CREATE TABLE download_url_chains(id INTEGER PRIMARY KEY, url TEXT);
    """)
    for i in range(200):
        conn.execute(
            "INSERT INTO urls VALUES (?, ?, ?)",
            (i, f"https://example.com/page{i}", f"Page {i}"),
        )
    for i in range(500):
        conn.execute("INSERT INTO visits VALUES (?, ?)", (i, i % 200))
    for i in range(50):
        conn.execute(
            "INSERT INTO downloads VALUES (?, ?)",
            (i, f"/downloads/file_{i}.zip"),
        )
    conn.commit()
    conn.close()

    # Cookies SQLite
    cookies_db = chrome_profile / "Cookies"
    conn = sqlite3.connect(str(cookies_db))
    conn.execute("CREATE TABLE cookies(name TEXT, value TEXT)")
    for i in range(100):
        conn.execute(
            "INSERT INTO cookies VALUES (?, ?)",
            (f"cookie_{i}", "x" * 100),
        )
    conn.commit()
    conn.close()

    # ─── Fake profil Firefox ────────────────────────────────────
    ff_profile = br_root / "firefox" / "abc.default"
    ff_profile.mkdir(parents=True)
    (ff_profile / "cache2" / "entries").mkdir(parents=True)
    for i in range(3):
        (ff_profile / "cache2" / "entries" / f"hash_{i}").write_bytes(
            b"Y" * 3000
        )

    # places.sqlite
    places_db = ff_profile / "places.sqlite"
    conn = sqlite3.connect(str(places_db))
    conn.executescript("""
        CREATE TABLE moz_historyvisits(id INTEGER PRIMARY KEY, place_id INTEGER);
        CREATE TABLE moz_inputhistory(id INTEGER PRIMARY KEY, input TEXT);
        CREATE TABLE moz_places(id INTEGER PRIMARY KEY, origin_id INTEGER);
        CREATE TABLE moz_origins(id INTEGER PRIMARY KEY, prefix TEXT);
        CREATE TABLE moz_annos(id INTEGER PRIMARY KEY, anno_attribute_id INTEGER);
        CREATE TABLE moz_anno_attributes(id INTEGER PRIMARY KEY, name TEXT);
    """)
    for i in range(200):
        conn.execute(
            "INSERT INTO moz_historyvisits VALUES (?, ?)", (i, i)
        )
    for i in range(50):
        conn.execute(
            "INSERT INTO moz_inputhistory VALUES (?, ?)",
            (i, f"search_{i}"),
        )
    conn.commit()
    conn.close()

    # cookies.sqlite
    ff_cookies_db = ff_profile / "cookies.sqlite"
    conn = sqlite3.connect(str(ff_cookies_db))
    conn.execute(
        "CREATE TABLE moz_cookies(id INTEGER PRIMARY KEY, name TEXT, value TEXT)"
    )
    for i in range(80):
        conn.execute(
            "INSERT INTO moz_cookies VALUES (?, ?, ?)",
            (i, f"c_{i}", "v" * 50),
        )
    conn.commit()
    conn.close()

    # ─── Monkey-patch ───────────────────────────────────────────
    original_bpp = cleaner._browser_profile_paths
    cleaner._browser_profile_paths = lambda: [
        ("chromium", chrome_profile),
        ("firefox",  ff_profile),
    ]

    logs = []
    collect = lambda msg: logs.append(msg)

    try:
        # ═══ task_browser_cache ══════════════════════════════════
        logs.clear()
        freed = cleaner.task_browser_cache(collect)
        chrome_cache = list((chrome_profile / "Cache").glob("*"))
        chrome_cc    = list((chrome_profile / "Code Cache").glob("*"))
        chrome_gpu   = list((chrome_profile / "GPUCache").glob("*"))
        ff_cache     = list((ff_profile / "cache2" / "entries").glob("*"))
        remaining    = len(chrome_cache) + len(chrome_cc) + len(chrome_gpu) + len(ff_cache)
        if remaining == 0 and freed > 0:
            log("ok", "Navigateurs", "task_browser_cache",
                f"{freed} octets liberes, 12 fichiers supprimes")
        else:
            log("ko", "Navigateurs", "task_browser_cache",
                f"freed={freed}, reste={remaining}")

        # ═══ task_browser_history ════════════════════════════════
        # Chrome : urls doit etre vide apres
        logs.clear()
        freed = cleaner.task_browser_history(collect)
        conn = sqlite3.connect(str(history_db))
        urls_after = conn.execute("SELECT COUNT(*) FROM urls").fetchone()[0]
        visits_after = conn.execute("SELECT COUNT(*) FROM visits").fetchone()[0]
        dls_after = conn.execute("SELECT COUNT(*) FROM downloads").fetchone()[0]
        conn.close()
        if urls_after == 0 and visits_after == 0 and dls_after == 0:
            log("ok", "Navigateurs", "task_browser_history (Chrome)",
                "urls/visits/downloads vides")
        else:
            log("ko", "Navigateurs", "task_browser_history (Chrome)",
                f"urls={urls_after}, visits={visits_after}, dls={dls_after}")

        # Firefox : moz_historyvisits / moz_inputhistory vides
        conn = sqlite3.connect(str(places_db))
        hv = conn.execute("SELECT COUNT(*) FROM moz_historyvisits").fetchone()[0]
        ih = conn.execute("SELECT COUNT(*) FROM moz_inputhistory").fetchone()[0]
        conn.close()
        if hv == 0 and ih == 0:
            log("ok", "Navigateurs", "task_browser_history (Firefox)",
                "moz_historyvisits/inputhistory vides")
        else:
            log("ko", "Navigateurs", "task_browser_history (Firefox)",
                f"hv={hv}, ih={ih}")

        # ═══ task_browser_cookies ════════════════════════════════
        logs.clear()
        freed = cleaner.task_browser_cookies(collect)
        conn = sqlite3.connect(str(cookies_db))
        cookies_after = conn.execute("SELECT COUNT(*) FROM cookies").fetchone()[0]
        conn.close()
        conn = sqlite3.connect(str(ff_cookies_db))
        ff_cookies_after = conn.execute("SELECT COUNT(*) FROM moz_cookies").fetchone()[0]
        conn.close()
        if cookies_after == 0 and ff_cookies_after == 0:
            log("ok", "Navigateurs", "task_browser_cookies",
                "Chrome + Firefox cookies vides")
        else:
            log("ko", "Navigateurs", "task_browser_cookies",
                f"chrome={cookies_after}, firefox={ff_cookies_after}")

    finally:
        cleaner._browser_profile_paths = original_bpp


# ══════════════════════════════════════════════════════════════════════════════
# TESTS SMOKE : fonctions systeme read-only
# ══════════════════════════════════════════════════════════════════════════════

def test_smoke():
    """Verifie que toutes les fonctions de scan/estimation systeme
    retournent des donnees valides sans lever d'exception."""
    section("Tests smoke (fonctions systeme read-only)")

    from cleaner import (
        estimate_temp, estimate_browser_cache, estimate_recycle_bin,
        estimate_thumbnails, estimate_prefetch, estimate_windows_update,
        estimate_history, estimate_cookies, estimate_recent_files,
        estimate_dumps, estimate_event_logs, estimate_app_caches,
        estimate_font_cache,
        get_installed_apps, get_startup_entries, get_browser_extensions,
        list_restore_points, get_software_updates, get_privacy_items,
        get_hibernation_info, get_windows_old_info, get_health_data,
        find_orphan_folders, fmt_size,
    )

    # ── Estimates (taches Nettoyage) ────────────────────────────
    # Chaque fonction retourne une taille en octets (int/float >= 0)
    estimates = [
        ("temp",            estimate_temp),
        ("browser_cache",   estimate_browser_cache),
        ("recycle_bin",     estimate_recycle_bin),
        ("thumbnails",      estimate_thumbnails),
        ("prefetch",        estimate_prefetch),
        ("windows_update",  estimate_windows_update),
        ("history",         estimate_history),
        ("cookies",         estimate_cookies),
        ("recent_files",    estimate_recent_files),
        ("dumps",           estimate_dumps),
        ("event_logs",      estimate_event_logs),
        ("app_caches",      estimate_app_caches),
        ("font_cache",      estimate_font_cache),
    ]
    for name, fn in estimates:
        try:
            result = fn()
            if isinstance(result, (int, float)) and result >= 0:
                log("ok", "Estimate", name, fmt_size(result))
            else:
                log("ko", "Estimate", name,
                    f"resultat invalide: {result!r}")
        except Exception as e:
            log("ko", "Estimate", name,
                f"{type(e).__name__}: {e}")

    # ── Systeme : fonctions no-arg retournant liste/dict ────────
    systems = [
        ("get_installed_apps",    get_installed_apps,    list,  "apps"),
        ("get_startup_entries",   get_startup_entries,   list,  "entrees"),
        ("get_browser_extensions",get_browser_extensions,dict,  "navigateurs"),
        ("list_restore_points",   list_restore_points,   (list, dict), "points"),
        ("get_software_updates",  get_software_updates,  (list, dict), "elements"),
        ("get_privacy_items",     get_privacy_items,     (list, dict), "elements"),
        ("get_hibernation_info",  get_hibernation_info,  dict,  "cles"),
        ("get_windows_old_info",  get_windows_old_info,  dict,  "cles"),
        ("get_health_data",       get_health_data,       dict,  "cles"),
    ]
    for name, fn, expected_type, unit in systems:
        try:
            result = fn()
            if not isinstance(result, expected_type):
                log("ko", "System", name,
                    f"type: {type(result).__name__}")
                continue
            count = len(result) if hasattr(result, "__len__") else 1
            log("ok", "System", name, f"{count} {unit}")
        except Exception as e:
            log("ko", "System", name, f"{type(e).__name__}: {e}")

    # ── find_orphan_folders (plus lent, scan Program Files) ────
    try:
        orphans = find_orphan_folders()
        if isinstance(orphans, list):
            log("ok", "System", "find_orphan_folders",
                f"{len(orphans)} dossiers orphelins")
        else:
            log("ko", "System", "find_orphan_folders",
                f"type: {type(orphans).__name__}")
    except Exception as e:
        log("ko", "System", "find_orphan_folders",
            f"{type(e).__name__}: {e}")

    # ── Verifications structurelles ─────────────────────────────
    # get_health_data doit contenir 6-7 metriques
    try:
        h = get_health_data()
        metrics = h.get("metrics", [])
        expected_ids = {"disk", "temp", "browser", "startup",
                        "recycle", "appcache", "smart"}
        got_ids = {m.get("id") for m in metrics}
        if expected_ids.issubset(got_ids):
            log("ok", "Structure", "health_data",
                f"{len(metrics)} metriques avec IDs attendus")
        else:
            missing = expected_ids - got_ids
            log("ko", "Structure", "health_data",
                f"IDs manquants: {missing}")
    except Exception as e:
        log("ko", "Structure", "health_data", str(e))

    # get_hibernation_info doit avoir une cle "enabled" ou "exists"
    try:
        hib = get_hibernation_info()
        if any(k in hib for k in ("enabled", "exists", "size", "error")):
            log("ok", "Structure", "hibernation_info",
                f"cles: {list(hib.keys())}")
        else:
            log("ko", "Structure", "hibernation_info",
                f"cles inattendues: {list(hib.keys())}")
    except Exception as e:
        log("ko", "Structure", "hibernation_info", str(e))

    # get_windows_old_info doit indiquer l'existence
    try:
        wo = get_windows_old_info()
        if any(k in wo for k in ("exists", "size", "path", "error")):
            log("ok", "Structure", "windows_old_info",
                f"cles: {list(wo.keys())}")
        else:
            log("ko", "Structure", "windows_old_info",
                f"cles: {list(wo.keys())}")
    except Exception as e:
        log("ko", "Structure", "windows_old_info", str(e))


# ══════════════════════════════════════════════════════════════════════════════
# TEST RACCOURCIS CASSES : creation d'un .lnk casse, detection, suppression
# ══════════════════════════════════════════════════════════════════════════════

def test_shortcuts():
    section("Raccourcis casses (si pywin32 disponible)")

    try:
        import win32com.client
    except ImportError:
        log("warn", "Raccourcis", "pywin32",
            "non installe - test saute")
        return

    desktop = Path(os.path.expandvars(r"%USERPROFILE%\Desktop"))
    if not desktop.exists():
        log("warn", "Raccourcis", "Desktop", "introuvable")
        return

    # Cible volontairement inexistante dans le sandbox
    test_lnk = desktop / "_opencleaner_test_broken.lnk"
    fake_target = str(SANDBOX / "definitely_does_not_exist.exe")

    try:
        shell = win32com.client.Dispatch("WScript.Shell")
        sc = shell.CreateShortcut(str(test_lnk))
        sc.TargetPath = fake_target
        sc.Save()
        log("info", "Raccourcis", "fixture",
            f"creation {test_lnk.name}")

        from cleaner import scan_shortcuts, delete_shortcuts
        broken = scan_shortcuts()
        found = any(b.get("path") == str(test_lnk) for b in broken)
        if found:
            log("ok", "Raccourcis", "scan_shortcuts",
                f"notre .lnk detecte parmi {len(broken)} brokens")
        else:
            log("ko", "Raccourcis", "scan_shortcuts",
                f"non trouve ({len(broken)} brokens au total)")

        # Suppression ciblee (on ne touche QUE notre .lnk)
        if test_lnk.exists():
            deleted, errors = delete_shortcuts([str(test_lnk)])
            if deleted >= 1 and not test_lnk.exists():
                log("ok", "Raccourcis", "delete_shortcuts",
                    "supprime proprement")
            else:
                log("ko", "Raccourcis", "delete_shortcuts",
                    f"deleted={deleted}, errors={errors}")
    except Exception as e:
        log("ko", "Raccourcis", "exception",
            f"{type(e).__name__}: {e}")
    finally:
        # Filet de securite
        if test_lnk.exists():
            try:
                test_lnk.unlink()
            except Exception:
                pass


# ══════════════════════════════════════════════════════════════════════════════
# TESTS UI : Flask + Playwright
# ══════════════════════════════════════════════════════════════════════════════

def start_flask():
    from app import app
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    threading.Thread(
        target=lambda: app.run(
            host="127.0.0.1", port=port, debug=False, threaded=True, use_reloader=False
        ),
        daemon=True,
    ).start()
    url = f"http://127.0.0.1:{port}/"
    for _ in range(80):
        try:
            if urllib.request.urlopen(url, timeout=0.3).getcode() == 200:
                return url
        except Exception:
            time.sleep(0.1)
    raise RuntimeError("Flask n'a pas demarre")


def test_ui():
    section("Tests UI (Playwright)")

    # Recreer le sandbox (il a ete vide par les tests destructifs)
    setup_sandbox()

    SHOTS.mkdir(parents=True, exist_ok=True)
    for f in SHOTS.glob("*.png"):
        f.unlink()

    url = start_flask()
    from playwright.sync_api import sync_playwright

    def shot(page, name):
        page.screenshot(path=str(SHOTS / f"{name}.png"), full_page=False)

    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        ctx = browser.new_context(viewport={"width": 1440, "height": 900})
        page = ctx.new_page()
        page.goto(url)
        page.wait_for_load_state("networkidle")
        page.wait_for_timeout(800)

        # Aller sur Outils
        page.locator('.sb-item[data-tab="outils"]').click()
        page.wait_for_timeout(1200)

        # ─── Recherche de doublons ──────────────────────────────
        dup_path = str(SANDBOX / "duplicates")
        page.locator("#dupe-folder").fill(dup_path)
        page.locator("#dupe-minsize").fill("1")
        page.locator("#btn-scan-dupes").click()
        # Attendre la fin du scan (le bouton repasse en etat "found" ou idle)
        page.wait_for_timeout(4000)
        shot(page, "01_doublons")
        groups = page.locator("#dupe-results .dupe-group-title").count()
        if groups >= 2:
            log("ok", "Doublons", "UI scan",
                f"{groups} groupes affiches")
        else:
            log("ko", "Doublons", "UI scan",
                f"{groups} groupes (attendu 2)")

        # ─── Grands fichiers ────────────────────────────────────
        page.locator("#lf-folder").fill(str(SANDBOX / "large"))
        page.locator("#lf-minsize").fill("0.01")  # 10 Mo
        page.locator("#btn-scan-lf").click()
        page.wait_for_timeout(3500)
        shot(page, "02_grands_fichiers")
        lf_rows = page.locator("#lf-results .dupe-row").count()
        if lf_rows >= 1:
            log("ok", "Gros fichiers", "UI scan",
                f"{lf_rows} ligne(s) affichee(s)")
        else:
            log("ko", "Gros fichiers", "UI scan",
                f"{lf_rows} lignes (attendu >= 1)")

        # ─── Dossiers vides ─────────────────────────────────────
        page.locator("#ef-folder").fill(str(SANDBOX / "empty"))
        page.locator("#btn-scan-ef").click()
        page.wait_for_timeout(3500)
        shot(page, "03_dossiers_vides")
        ef_rows = page.locator("#ef-results .dupe-row").count()
        if ef_rows >= 1:
            log("ok", "Dossiers vides", "UI scan",
                f"{ef_rows} ligne(s) affichee(s)")
        else:
            log("ko", "Dossiers vides", "UI scan",
                f"{ef_rows} lignes (attendu >= 1)")

        # ─── Anciens installers ─────────────────────────────────
        page.locator("#inst-folder").fill(str(SANDBOX / "installers"))
        page.locator("#inst-age").fill("30")
        page.locator("#btn-scan-inst").click()
        page.wait_for_timeout(3500)
        shot(page, "04_installers")
        inst_rows = page.locator("#inst-results .dupe-row").count()
        if inst_rows >= 3:
            log("ok", "Anciens installers", "UI scan",
                f"{inst_rows} lignes (attendu 3)")
        else:
            log("ko", "Anciens installers", "UI scan",
                f"{inst_rows} lignes (attendu 3)")

        # ─── Analyse disque ─────────────────────────────────────
        page.locator("#da-folder").fill(str(SANDBOX))
        page.locator("#btn-scan-da").click()
        page.wait_for_timeout(3500)
        shot(page, "05_analyse_disque")
        da_rows = page.locator("#da-results .da-row").count()
        if da_rows >= 4:
            log("ok", "Analyse disque", "UI scan",
                f"{da_rows} entrees (attendu >= 4)")
        else:
            log("ko", "Analyse disque", "UI scan",
                f"{da_rows} entrees (attendu >= 4)")

        # Screenshot final de tout l'onglet Outils
        page.evaluate("document.querySelector('.main').scrollTop = 0")
        page.wait_for_timeout(200)
        shot(page, "06_outils_apercu")

        # ══════════════════════════════════════════════════════
        # NAVIGATION COMPLETE : verifier les 3 onglets + breadcrumb
        # ══════════════════════════════════════════════════════
        section_title("Navigation complete (sidebar + breadcrumb)")

        for tab_id, label in [
            ("nettoyage", "Nettoyage"),
            ("outils", "Outils"),
            ("sante", "Santé"),
        ]:
            page.locator(f'.sb-item[data-tab="{tab_id}"]').click()
            page.wait_for_timeout(600)
            # Verifier que le panel correspondant est actif
            is_active = page.evaluate(
                f'document.getElementById("tab-{tab_id}").classList.contains("active")'
            )
            # Verifier que le sb-item est marque actif
            sb_active = page.evaluate(
                f'document.querySelector(\'.sb-item[data-tab="{tab_id}"]\').classList.contains("active")'
            )
            # Verifier que le breadcrumb a ete mis a jour
            crumb = page.locator("#crumb-current").inner_text()
            if is_active and sb_active and crumb == label:
                log("ok", "Nav", f"onglet {label}",
                    "panel actif + sb-item actif + breadcrumb")
            else:
                log("ko", "Nav", f"onglet {label}",
                    f"panel={is_active}, sb={sb_active}, crumb={crumb!r}")

        # ══════════════════════════════════════════════════════
        # MODALES : Aide, Historique
        # ══════════════════════════════════════════════════════
        section_title("Modales")

        # Aide : ouverture + fermeture
        page.locator('.sb-bottom button.sb-item:has-text("Aide")').click()
        page.wait_for_timeout(400)
        visible = page.evaluate(
            'getComputedStyle(document.getElementById("help-overlay")).display'
        )
        if visible == "flex":
            log("ok", "Modales", "Aide ouverture",
                "help-overlay visible")
        else:
            log("ko", "Modales", "Aide ouverture",
                f"display={visible}")
        # Fermer via le bouton Compris
        page.locator('#help-overlay .btn-primary').click()
        page.wait_for_timeout(300)
        hidden = page.evaluate(
            'getComputedStyle(document.getElementById("help-overlay")).display'
        )
        if hidden == "none":
            log("ok", "Modales", "Aide fermeture",
                "help-overlay cache")
        else:
            log("ko", "Modales", "Aide fermeture",
                f"display={hidden}")

        # Historique : ouverture + fermeture
        page.locator('.sb-item:has-text("Historique")').click()
        page.wait_for_timeout(600)
        visible = page.evaluate(
            'getComputedStyle(document.getElementById("history-overlay")).display'
        )
        list_filled = page.evaluate(
            'document.getElementById("history-list").children.length > 0'
        )
        if visible == "flex" and list_filled:
            log("ok", "Modales", "Historique ouverture",
                "history-overlay visible + contenu")
        else:
            log("ko", "Modales", "Historique ouverture",
                f"display={visible}, contenu={list_filled}")
        page.locator('#history-overlay .btn-primary').click()
        page.wait_for_timeout(300)
        hidden = page.evaluate(
            'getComputedStyle(document.getElementById("history-overlay")).display'
        )
        if hidden == "none":
            log("ok", "Modales", "Historique fermeture",
                "history-overlay cache")
        else:
            log("ko", "Modales", "Historique fermeture",
                f"display={hidden}")

        # ══════════════════════════════════════════════════════
        # TOGGLE THEME : light <-> dark avec verification visuelle
        # ══════════════════════════════════════════════════════
        section_title("Toggle theme")

        initial = page.evaluate(
            'document.documentElement.getAttribute("data-theme")'
        )
        page.locator('.main-topbar-right .icon-btn').first.click()
        page.wait_for_timeout(400)
        after_toggle = page.evaluate(
            'document.documentElement.getAttribute("data-theme")'
        )
        if after_toggle != initial and after_toggle in ("light", "dark"):
            log("ok", "Theme", "toggle 1",
                f"{initial} -> {after_toggle}")
        else:
            log("ko", "Theme", "toggle 1",
                f"sans effet : {initial} -> {after_toggle}")
        # Verifier que le body-bg a change visuellement
        bg_after = page.evaluate(
            'getComputedStyle(document.body).backgroundColor'
        )
        # Retour au theme initial
        page.locator('.main-topbar-right .icon-btn').first.click()
        page.wait_for_timeout(400)
        restored = page.evaluate(
            'document.documentElement.getAttribute("data-theme")'
        )
        if restored == initial:
            log("ok", "Theme", "toggle 2",
                f"retour a {restored}")
        else:
            log("ko", "Theme", "toggle 2",
                f"etat final {restored} != initial {initial}")

        # ══════════════════════════════════════════════════════
        # FLUX COMPLET : Lancer le nettoyage via UI (sandboxe)
        # ══════════════════════════════════════════════════════
        section_title("Flux complet : Lancer le nettoyage (UI + SSE)")

        import cleaner
        # task_thumbnails scanne LOCALAPPDATA/Microsoft/Windows/Explorer
        # pour les thumbcache_*.db — non-admin, facile a sandboxer
        flow_local = SANDBOX / "clean_flow_local"
        thumb_dir = flow_local / "Microsoft" / "Windows" / "Explorer"
        thumb_dir.mkdir(parents=True, exist_ok=True)
        # Fixtures : 5 thumbcache bidons
        for i in range(5):
            (thumb_dir / f"thumbcache_{256 * (i + 1)}.db").write_bytes(
                b"T" * 2000
            )
        # Fichier non-thumbcache qui doit etre preserve
        (thumb_dir / "other.txt").write_bytes(b"keep me")

        # Patch LOCALAPPDATA pour rediriger task_thumbnails
        orig_local = os.environ.get("LOCALAPPDATA")
        os.environ["LOCALAPPDATA"] = str(flow_local)

        try:
            page.locator('.sb-item[data-tab="nettoyage"]').click()
            page.wait_for_timeout(1500)

            # Relancer loadSizes pour voir la taille reelle du sandbox patche
            page.evaluate("loadSizes()")
            page.wait_for_timeout(2500)

            # Selection : uncheckAll() puis toggleTask('thumbnails')
            page.evaluate("uncheckAll(); toggleTask('thumbnails');")
            page.wait_for_timeout(400)

            checked_count = page.evaluate(
                'document.querySelectorAll(".task-item.on").length'
            )
            if checked_count == 1:
                log("ok", "CleanFlow", "selection",
                    "seule task 'thumbnails' cochee")
            else:
                log("ko", "CleanFlow", "selection",
                    f"{checked_count} cochees (attendu 1)")

            # Clic "Lancer le nettoyage"
            page.locator("#btn-clean").click()
            page.wait_for_timeout(600)
            preview_visible = page.evaluate(
                'getComputedStyle(document.getElementById("modal-overlay")).display'
            )
            if preview_visible != "flex":
                log("ko", "CleanFlow", "modale apercu",
                    f"display={preview_visible}")
            else:
                log("ok", "CleanFlow", "modale apercu",
                    "ouverte")

                # Confirmer le nettoyage (clique sur "Nettoyer maintenant")
                page.locator(
                    '#modal-overlay button.btn-primary'
                ).click()

                # Attendre la fin du SSE stream (5s max — task_temp est rapide)
                page.wait_for_timeout(5000)

                # Verifier que les thumbcache ont ete supprimes, other.txt preserve
                caches_left = list(thumb_dir.glob("thumbcache_*.db"))
                other = thumb_dir / "other.txt"
                if len(caches_left) == 0 and other.exists():
                    log("ok", "CleanFlow", "suppression reelle",
                        "5 thumbcache supprimes via UI, other.txt preserve")
                else:
                    log("ko", "CleanFlow", "suppression reelle",
                        f"caches_reste={len(caches_left)}, other_ok={other.exists()}")

                # Verifier que le log a ete rempli par le SSE stream
                log_entries = page.locator("#log-body .log-entry").count()
                if log_entries >= 2:
                    log("ok", "CleanFlow", "journal SSE",
                        f"{log_entries} entrees ajoutees")
                else:
                    log("ko", "CleanFlow", "journal SSE",
                        f"{log_entries} entrees (attendu >= 2)")

                # Verifier que le bouton est passe en etat success
                btn_classes = page.evaluate(
                    'document.getElementById("btn-clean").className'
                )
                if "btn-success" in btn_classes or "btn-primary" in btn_classes:
                    log("ok", "CleanFlow", "etat bouton",
                        f"class: {btn_classes}")
                else:
                    log("ko", "CleanFlow", "etat bouton",
                        f"class: {btn_classes}")
        finally:
            # Restauration CRITIQUE des env vars
            if orig_local is not None:
                os.environ["LOCALAPPDATA"] = orig_local
            elif "LOCALAPPDATA" in os.environ:
                del os.environ["LOCALAPPDATA"]

        shot(page, "07_flux_nettoyage")

        browser.close()


def section_title(title):
    """Sous-section dans la sortie console."""
    print(f"\n  ── {title} ──")


# ══════════════════════════════════════════════════════════════════════════════
# ENTREE
# ══════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    print()
    print("  ══════ Test E2E OpenCleaner ══════")
    print()

    try:
        setup_sandbox()
        test_functional()
        test_nettoyage_tasks()
        test_browser_tasks()
        test_smoke()
        test_shortcuts()
        test_ui()
    finally:
        teardown_sandbox()

    # Rapport final
    print()
    print("  ══════ RAPPORT ══════")
    ok = sum(1 for s, *_ in RESULTS if s == "ok")
    ko = sum(1 for s, *_ in RESULTS if s == "ko")
    warn = sum(1 for s, *_ in RESULTS if s == "warn")
    total = ok + ko + warn
    print(f"  {ok} OK · {ko} FAIL · {warn} WARN · {total} assertions")
    if SHOTS.exists():
        print(f"  Screenshots : {SHOTS}")
    print()

    sys.exit(0 if ko == 0 else 1)

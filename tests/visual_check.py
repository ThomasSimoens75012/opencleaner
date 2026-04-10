"""
visual_check.py — Capture screenshots de tous les onglets pour analyse visuelle.

Demarre Flask sur un port libre, ouvre Playwright en headless,
navigue les 3 onglets en mode clair et sombre, prend des screenshots
full-page de chaque vue + interactions cles.

Usage:  python tests/visual_check.py
Sortie: tests/screenshots/visual_check/*.png
"""

import io
import socket
import sys
import threading
import time
import urllib.request
from pathlib import Path

# Force UTF-8 stdout sur Windows
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

# ── Démarrage Flask en thread ───────────────────────────────────────────
from app import app  # noqa: E402

with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
    s.bind(("127.0.0.1", 0))
    PORT = s.getsockname()[1]

URL = f"http://127.0.0.1:{PORT}/"

threading.Thread(
    target=lambda: app.run(
        host="127.0.0.1", port=PORT, debug=False, threaded=True, use_reloader=False
    ),
    daemon=True,
).start()

print(f"  Demarrage Flask sur {URL}")
for _ in range(80):
    try:
        if urllib.request.urlopen(URL, timeout=0.3).getcode() == 200:
            break
    except Exception:
        time.sleep(0.1)
else:
    print("  ERREUR : Flask n'a pas demarre")
    sys.exit(1)
print("  Flask pret\n")

# ── Setup Playwright ────────────────────────────────────────────────────
from playwright.sync_api import sync_playwright  # noqa: E402

OUT = ROOT / "tests" / "screenshots" / "visual_check"
OUT.mkdir(parents=True, exist_ok=True)
for f in OUT.glob("*.png"):
    f.unlink()

console_logs: list[str] = []


def expand_layout(page):
    """Désactive temporairement les overflow: hidden pour pouvoir
    prendre une screenshot full-page de tout le contenu."""
    page.evaluate(
        """
        document.body.style.height = 'auto';
        document.body.style.overflow = 'visible';
        const m = document.querySelector('.main');
        if (m) { m.style.height = 'auto'; m.style.overflow = 'visible'; }
        const sb = document.querySelector('.sidebar');
        if (sb) {
            sb.style.position = 'absolute';
            sb.style.left = '0'; sb.style.top = '0';
        }
        """
    )


def shot(page, name):
    expand_layout(page)
    page.wait_for_timeout(150)
    p = OUT / f"{name}.png"
    page.screenshot(path=str(p), full_page=True)
    size_kb = p.stat().st_size // 1024
    print(f"  v {name}.png  ({size_kb} KB)")


def click_theme(page):
    page.locator(".main-topbar-right .icon-btn").first.click()
    page.wait_for_timeout(400)


def click_tab(page, tab_name):
    page.locator(f'.sb-item[data-tab="{tab_name}"]').click()
    page.wait_for_timeout(800)


with sync_playwright() as pw:
    browser = pw.chromium.launch()
    ctx = browser.new_context(viewport={"width": 1440, "height": 900})
    page = ctx.new_page()
    page.on(
        "console",
        lambda m: console_logs.append(f"[{m.type}] {m.text}"),
    )
    page.on("pageerror", lambda e: console_logs.append(f"[pageerror] {e}"))

    page.goto(URL)
    page.wait_for_load_state("networkidle")
    page.wait_for_timeout(800)

    # ────────────────────────────────────────────────────────
    # NETTOYAGE
    # ────────────────────────────────────────────────────────
    print("  [Nettoyage]")
    shot(page, "01_nettoyage_light_initial")

    # Attendre que les tailles soient chargées
    page.wait_for_timeout(3000)
    shot(page, "02_nettoyage_light_loaded")

    # Ouvrir le toggle block
    toggle = page.locator(".toggle-block").first
    if toggle.count() > 0:
        toggle.click()
        page.wait_for_timeout(300)
        shot(page, "03_nettoyage_toggle_open")

    # Mode sombre
    click_theme(page)
    shot(page, "04_nettoyage_dark")
    click_theme(page)  # retour clair

    # ────────────────────────────────────────────────────────
    # OUTILS
    # ────────────────────────────────────────────────────────
    print("\n  [Outils]")
    click_tab(page, "outils")
    shot(page, "05_outils_light")

    click_theme(page)
    shot(page, "06_outils_dark")
    click_theme(page)

    # ────────────────────────────────────────────────────────
    # SANTE
    # ────────────────────────────────────────────────────────
    print("\n  [Sante]")
    click_tab(page, "sante")
    page.wait_for_timeout(3500)  # attendre le chargement de la sante
    shot(page, "07_sante_light")

    click_theme(page)
    shot(page, "08_sante_dark")

    # ────────────────────────────────────────────────────────
    # INFOS COMPLEMENTAIRES
    # ────────────────────────────────────────────────────────
    info = page.evaluate(
        """
        ({
            theme: document.documentElement.getAttribute('data-theme'),
            font: getComputedStyle(document.body).fontFamily,
            fontSize: getComputedStyle(document.body).fontSize,
            sidebarBg: getComputedStyle(document.querySelector('.sidebar')).backgroundColor,
            mainBg: getComputedStyle(document.querySelector('.main')).backgroundColor,
            pageTitleSize: getComputedStyle(document.querySelector('.page-title')).fontSize,
            sidebarWidth: document.querySelector('.sidebar').offsetWidth,
            mainWidth: document.querySelector('.main').offsetWidth,
            viewportWidth: window.innerWidth,
        })
        """
    )

    browser.close()

print()
print("  ──────────────────────────────────────────")
print("  Infos rendues :")
for k, v in info.items():
    print(f"    {k}: {v}")

print()
n = len(list(OUT.glob("*.png")))
print(f"  Termine — {n} screenshots dans {OUT}")

if console_logs:
    print(f"\n  Logs console ({len(console_logs)}) :")
    for log in console_logs[:30]:
        print(f"    {log}")

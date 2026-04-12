/* i18n.js — Internationalisation OpenCleaner */

const I18N = {
  _lang: "fr",
  _strings: {},
  _loaded: false,

  /** Langue courante */
  get lang() { return this._lang; },

  /** Charge un fichier de langue et applique les traductions */
  async load(lang) {
    try {
      const res = await fetch(`/static/lang/${lang}.json`);
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      this._strings = await res.json();
      this._lang = lang;
      this._loaded = true;
      localStorage.setItem("pcc-lang", lang);
      document.documentElement.setAttribute("lang", lang);
      this.apply();
      // Notifier le backend
      fetch("/api/set-lang", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ lang }),
      }).catch(() => {});
    } catch (e) {
      console.warn("[i18n] Failed to load", lang, e);
    }
  },

  /** Traduit une clé. Retourne la clé elle-même si pas de traduction. */
  t(key, params) {
    let s = this._strings[key] || key;
    if (params) {
      for (const [k, v] of Object.entries(params)) {
        s = s.replace(`{${k}}`, v);
      }
    }
    return s;
  },

  /** Applique les traductions au DOM (éléments avec data-i18n) */
  apply() {
    document.querySelectorAll("[data-i18n]").forEach(el => {
      const key = el.getAttribute("data-i18n");
      const val = this.t(key);
      if (val === key) return; // pas de traduction
      // Détecter l'attribut cible
      const attr = el.getAttribute("data-i18n-attr");
      if (attr === "placeholder") el.placeholder = val;
      else if (attr === "title") el.title = val;
      else el.textContent = val;
    });
  },

  /** Initialisation au chargement */
  async init() {
    const saved = localStorage.getItem("pcc-lang") || "fr";
    await this.load(saved);
  },
};

/** Raccourci global */
function t(key, params) { return I18N.t(key, params); }

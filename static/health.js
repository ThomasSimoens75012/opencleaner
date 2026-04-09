/* health.js — Onglet Santé système */

let healthInitialized = false;

function initHealth() {
  if (healthInitialized) return;
  healthInitialized = true;
  // Utiliser le cache si dispo (chargé en arrière-plan par app.js)
  if (window._healthCache) {
    renderHealth(window._healthCache);
  } else {
    loadHealth();
  }
}

async function loadHealth() {
  const metricsEl = document.getElementById("health-metrics");
  if (metricsEl) metricsEl.innerHTML = `<div class="tool-loading">Analyse en cours…</div>`;

  const ringFill = document.getElementById("health-ring-fill");
  const scoreVal = document.getElementById("health-score-val");
  const scoreLbl = document.getElementById("health-score-label");
  if (ringFill) ringFill.style.strokeDashoffset = 339;
  if (scoreVal) scoreVal.textContent = "…";
  if (scoreLbl) scoreLbl.textContent = "";

  try {
    const res  = await fetch("/api/health");
    const data = await res.json();
    window._healthCache = data;
    renderHealth(data);
    updateHealthBadge(data);
  } catch (e) {
    if (metricsEl) metricsEl.innerHTML = `<div class="tool-error">Erreur de chargement.</div>`;
  }
}

function updateHealthBadge(data) {
  const pct   = Math.round((data.score / data.max) * 100);
  const color = pct >= 80 ? "var(--green)" : pct >= 50 ? "var(--amber)" : "var(--red)";
  const badge = document.getElementById("health-badge");
  if (badge) { badge.textContent = pct + "%"; badge.style.color = color; }
}

function renderHealth(data) {
  const pct   = Math.round((data.score / data.max) * 100);
  const color = pct >= 80 ? "var(--green)" : pct >= 50 ? "var(--amber)" : "var(--red)";
  const C     = 2 * Math.PI * 54; // r=54
  const offset = C - (pct / 100) * C;

  const ringFill = document.getElementById("health-ring-fill");
  const scoreVal = document.getElementById("health-score-val");
  const scoreLbl = document.getElementById("health-score-label");

  if (ringFill) {
    ringFill.style.strokeDasharray  = C;
    ringFill.style.strokeDashoffset = offset;
    ringFill.setAttribute("stroke", color);
  }
  if (scoreVal) { scoreVal.textContent = pct + "%"; scoreVal.style.color = color; }
  if (scoreLbl) {
    scoreLbl.textContent = pct >= 80 ? "Excellent" : pct >= 50 ? "À améliorer" : "Attention";
    scoreLbl.style.color = color;
  }

  updateHealthBadge(data);

  // Métriques — triées par score croissant (pires en premier)
  const metricsEl = document.getElementById("health-metrics");
  if (!metricsEl) return;
  metricsEl.innerHTML = "";

  const sorted = [...data.metrics].sort((a, b) => (a.score / a.max) - (b.score / b.max));

  sorted.forEach(m => {
    const mPct      = Math.round((m.score / m.max) * 100);
    const statusCls = m.status === "good" ? "hm-good" : m.status === "warn" ? "hm-warn" : "hm-bad";
    const hasAction = m.action && m.status !== "good";

    const card = document.createElement("div");
    card.className = "health-metric-card";
    card.innerHTML = `
      <div class="hm-icon">${m.icon}</div>
      <div class="hm-info">
        <div class="hm-label">${m.label}</div>
        <div class="hm-detail">${m.detail}</div>
      </div>
      <div class="hm-bar-wrap">
        ${hasAction ? `<button class="btn-ghost hm-fix-btn" onclick="quickFixHealth('${m.action}')">Nettoyer</button>` : ""}
        <div class="hm-bar-bg"><div class="hm-bar-fill ${statusCls}" style="width:${mPct}%"></div></div>
        <div class="hm-pct ${statusCls}">${mPct}%</div>
      </div>`;
    metricsEl.appendChild(card);
  });
}

function quickFixHealth(taskId) {
  const task = (typeof TASKS !== "undefined") && TASKS.find(t => t.id === taskId);
  if (!task) return;

  // Basculer vers l'onglet nettoyage
  const nettoyageBtn = document.querySelector('.tab-btn[onclick*="nettoyage"]');
  if (nettoyageBtn) switchTab("nettoyage", nettoyageBtn);

  // Cocher uniquement cette tâche
  if (typeof TASKS !== "undefined") {
    TASKS.forEach(t => t.checked = false);
    task.checked = true;
    if (typeof renderTasks === "function") renderTasks();
    if (typeof saveCheckedState === "function") saveCheckedState();
    if (typeof showCleanPreview === "function") showCleanPreview([task]);
  }
}

/* scheduler.js — Onglet Planificateur */

let schedulerInitialized = false;

function initScheduler() {
  if (schedulerInitialized) return;
  schedulerInitialized = true;
  loadSchedule();
}

async function loadSchedule() {
  try {
    const res    = await fetch("/api/schedule");
    const config = await res.json();
    applyScheduleToForm(config);
  } catch (e) {
    console.error("Erreur chargement planificateur", e);
  }
}

function applyScheduleToForm(config) {
  setVal("sched-enabled",  config.enabled);
  setVal("sched-interval", config.interval);
  setVal("sched-time",     config.time);

  // Cocher les tâches planifiées
  document.querySelectorAll(".sched-task-cb").forEach(cb => {
    cb.checked = (config.tasks || []).includes(cb.dataset.id);
  });

  updateScheduleUI(config.enabled);
  updateNextRun(config.next_run, config.last_run);
}

function setVal(id, val) {
  const el = document.getElementById(id);
  if (!el) return;
  if (el.type === "checkbox") el.checked = !!val;
  else el.value = val || "";
}

function updateScheduleUI(enabled) {
  const body = document.getElementById("sched-body");
  if (body) body.style.opacity = enabled ? "1" : "0.5";
  const toggleEl = document.getElementById("sched-enabled");
  const label    = document.getElementById("sched-status-label");
  if (label) label.textContent = enabled ? "Actif" : "Inactif";
  if (label) label.className   = enabled ? "sched-status on" : "sched-status off";
}

function updateNextRun(nextRun, lastRun) {
  const nextEl = document.getElementById("sched-next-run");
  const lastEl = document.getElementById("sched-last-run");
  if (nextEl) nextEl.textContent = nextRun ? fmtDatetime(nextRun) : "—";
  if (lastEl) lastEl.textContent = lastRun ? fmtDatetime(lastRun) : "Jamais";
}

function fmtDatetime(iso) {
  try {
    return new Date(iso).toLocaleString("fr-FR", {
      day: "2-digit", month: "2-digit", year: "numeric",
      hour: "2-digit", minute: "2-digit",
    });
  } catch { return iso; }
}

async function saveSchedule() {
  const tasks = [...document.querySelectorAll(".sched-task-cb:checked")]
    .map(cb => cb.dataset.id);

  const config = {
    enabled:  document.getElementById("sched-enabled").checked,
    interval: document.getElementById("sched-interval").value,
    time:     document.getElementById("sched-time").value,
    tasks,
  };

  try {
    const res  = await fetch("/api/schedule", {
      method:  "POST",
      headers: { "Content-Type": "application/json" },
      body:    JSON.stringify(config),
    });
    const data = await res.json();
    if (data.ok) {
      updateScheduleUI(config.enabled);
      updateNextRun(data.next_run, null);
      showSavedFeedback();
    }
  } catch (e) {
    alert("Erreur lors de la sauvegarde : " + e);
  }
}

function showSavedFeedback() {
  const btn = document.getElementById("btn-save-schedule");
  if (!btn) return;
  const orig = btn.textContent;
  btn.textContent = "Sauvegardé ✓";
  btn.style.background = "var(--green)";
  setTimeout(() => {
    btn.textContent = orig;
    btn.style.background = "";
  }, 2000);
}

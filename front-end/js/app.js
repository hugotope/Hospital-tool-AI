/* ═════════════════════════════════════════════════════════════════════════
   MedAI Hospital — SPA corporate frontend
   ═════════════════════════════════════════════════════════════════════════ */
(function () {
  "use strict";

  const API = "http://127.0.0.1:8000/api";
  const LS_TOKEN = "medai_token";
  const LS_USER  = "medai_user";

  const $  = (sel, root = document) => root.querySelector(sel);
  const $$ = (sel, root = document) => Array.from(root.querySelectorAll(sel));
  const t  = (k, p) => window.I18n.t(k, p);
  const tDx      = (n) => window.I18n.tDx(n);
  const tSym     = (n) => window.I18n.tSym(n);
  const tSymList = (s) => window.I18n.tSymList(s);
  const tSymPair = (s) => window.I18n.tSymPair(s);
  const tZone    = (n) => window.I18n.tZone(n);
  const tRisk    = (n) => window.I18n.tRisk(n);
  const tGender  = (g) => window.I18n.tGender(g);

  function splitSymptoms(raw) {
    const parts = Array.isArray(raw) ? raw : String(raw || "").split(",");
    const dedup = new Map();
    parts.forEach((p) => {
      const clean = String(p || "").trim().replace(/\s+/g, " ");
      if (!clean) return;
      const key = clean.toLowerCase();
      if (!dedup.has(key)) dedup.set(key, clean);
    });
    return Array.from(dedup.values());
  }

  // ── Toast ───────────────────────────────────────────────────────────────
  function toast(message, type = "info") {
    const wrap = $("#toast-container");
    const el = document.createElement("div");
    el.className = `toast toast-${type}`;
    el.textContent = message;
    wrap.appendChild(el);
    setTimeout(() => el.remove(), 3800);
  }

  // ── API wrapper ────────────────────────────────────────────────────────
  async function api(path, opts = {}) {
    const token = localStorage.getItem(LS_TOKEN);
    const headers = opts.headers || {};
    headers["Content-Type"] = headers["Content-Type"] || "application/json";
    if (token) headers.Authorization = `Bearer ${token}`;
    const cfg = { ...opts, headers };
    if (cfg.body && typeof cfg.body === "object" && !(cfg.body instanceof FormData)) {
      cfg.body = JSON.stringify(cfg.body);
    }
    if (cfg.body instanceof FormData) {
      delete cfg.headers["Content-Type"];
    }
    const res = await fetch(`${API}${path}`, cfg);
    let data = null;
    try { data = await res.json(); } catch (_) { /* empty body */ }
    if (!res.ok) {
      const err = new Error((data && (data.error || data.message)) || `HTTP ${res.status}`);
      err.status = res.status;
      err.data = data;
      throw err;
    }
    return data;
  }

  // ── Auth helpers ───────────────────────────────────────────────────────
  function getUser() {
    try { return JSON.parse(localStorage.getItem(LS_USER) || "null"); }
    catch (_) { return null; }
  }
  function saveAuth(token, user) {
    localStorage.setItem(LS_TOKEN, token);
    localStorage.setItem(LS_USER, JSON.stringify(user));
  }
  function clearAuth() {
    localStorage.removeItem(LS_TOKEN);
    localStorage.removeItem(LS_USER);
  }

  // ── Login flow ─────────────────────────────────────────────────────────
  async function doLogin(e) {
    e.preventDefault();
    const btn = $("#login-btn");
    const err = $("#login-error");
    err.textContent = "";
    btn.disabled = true;
    try {
      const u = $("#login-username").value.trim();
      const p = $("#login-password").value;
      const data = await api("/auth/login", { method: "POST", body: { username: u, password: p } });
      saveAuth(data.token, data.user);
      showApp();
    } catch (e) {
      err.textContent = e.message || t("login.error.generic");
    } finally {
      btn.disabled = false;
    }
  }

  async function logout() {
    try { await api("/auth/logout", { method: "POST" }); } catch (_) {}
    clearAuth();
    window.location.reload();
  }

  function showApp() {
    $("#login-page").classList.add("hidden");
    $("#admin-panel").classList.remove("hidden");
    const u = getUser();
    if (u) {
      const display = u.name || u.username || "User";
      const initial = display.charAt(0).toUpperCase();
      const avatarEl = $("#user-avatar");
      const avatarLgEl = $("#user-avatar-lg");
      const nameEl = $("#user-name");
      const emailEl = $("#user-email");
      const roleEl = $("#user-role");
      if (avatarEl) avatarEl.textContent = initial;
      if (avatarLgEl) avatarLgEl.textContent = initial;
      if (nameEl) nameEl.textContent = display;
      if (emailEl) emailEl.textContent = u.email || `${u.username || "user"}@ihss.local`;
      if (roleEl) {
        roleEl.textContent = u.role || "";
        roleEl.className = "badge " + (u.role === "admin" ? "badge-admin" : "badge-info");
      }
      if (u.role !== "admin") {
        $$(".admin-only").forEach(el => el.classList.add("hidden"));
      }
    }
    checkApiStatus();
    navigate("dashboard");
  }

  // ── Topbar dropdown menus (settings / account) ─────────────────────────
  function closeAllMenus() {
    $$(".tb-menu").forEach(m => {
      const btn = m.querySelector(".topbar-icon-btn");
      const panel = m.querySelector(".tb-menu-panel");
      if (btn) btn.setAttribute("aria-expanded", "false");
      if (panel) panel.hidden = true;
      m.classList.remove("open");
    });
  }
  function openMenu(menuId) {
    closeAllMenus();
    const m = document.getElementById(menuId);
    if (!m) return;
    const btn = m.querySelector(".topbar-icon-btn");
    const panel = m.querySelector(".tb-menu-panel");
    if (btn) btn.setAttribute("aria-expanded", "true");
    if (panel) panel.hidden = false;
    m.classList.add("open");
  }
  function toggleMenu(menuId) {
    const m = document.getElementById(menuId);
    if (!m) return;
    if (m.classList.contains("open")) closeAllMenus();
    else openMenu(menuId);
  }
  function initTopbarMenus() {
    const bindings = [
      { btn: "settings-btn", menu: "settings-menu" },
      { btn: "account-btn",  menu: "account-menu"  },
    ];
    bindings.forEach(({ btn, menu }) => {
      const el = document.getElementById(btn);
      if (!el) return;
      el.addEventListener("click", (e) => {
        e.stopPropagation();
        toggleMenu(menu);
      });
    });
    // Close on outside click
    document.addEventListener("click", (e) => {
      if (!e.target.closest(".tb-menu")) closeAllMenus();
    });
    // Close on Escape
    document.addEventListener("keydown", (e) => {
      if (e.key === "Escape") closeAllMenus();
    });
  }

  // ── API status pill ────────────────────────────────────────────────────
  async function checkApiStatus() {
    const dot = $("#api-status .status-dot");
    const txt = $("#api-status-text");
    try {
      const h = await api("/health");
      if (h.models_loaded) {
        dot.className = "status-dot dot-success";
        txt.textContent = t("api.online");
      } else {
        dot.className = "status-dot dot-warning";
        txt.textContent = t("api.noModels");
      }
    } catch (_) {
      dot.className = "status-dot dot-danger";
      txt.textContent = t("api.offline");
    }
  }

  // ── Navigation ─────────────────────────────────────────────────────────
  const LOADERS = {
    dashboard: renderDashboard,
    diagnosis: renderDiagnosis,
    patients: renderPatients,
    diseases: renderDiseases,
    doctors: renderDoctors,
    analytics: renderAnalytics,
    anomalies: renderAnomalies,
    dataset: renderDataset,
    model: renderModel,
    users: renderUsers,
    report: renderReport,
  };

  function navigate(section) {
    $$(".nav-item").forEach(n => n.classList.toggle("active", n.dataset.section === section));
    const titleKey = "nav." + section;
    $("#page-title").textContent = t(titleKey);
    const loader = LOADERS[section] || LOADERS.dashboard;
    loader();
  }

  // ── Render helpers ─────────────────────────────────────────────────────
  const CONTENT = () => $("#main-content");
  const PAGE = (titleKey, subKey, inner) => `
    <div class="page-header">
      <h2>${t(titleKey)}</h2>
      <p>${t(subKey)}</p>
    </div>
    ${inner}
  `;
  function escapeHtml(s) {
    return String(s ?? "")
      .replace(/&/g, "&amp;").replace(/</g, "&lt;")
      .replace(/>/g, "&gt;").replace(/"/g, "&quot;").replace(/'/g, "&#39;");
  }

  // ═══════════════════════ DASHBOARD ═══════════════════════
  async function renderDashboard() {
    const u = getUser() || {};
    CONTENT().innerHTML = `
      <div class="page-header">
        <div>
          <h2>${t("dashboard.welcome", { name: u.name || u.username || "" })}</h2>
          <p>${t("dashboard.sub")}</p>
        </div>
        <div class="page-meta">
          <span class="meta-dot"></span>
          <span>${t("dashboard.system.ok")}</span>
          <span class="meta-sep">|</span>
          <span>${t("dashboard.lastUpdated")}</span>
        </div>
      </div>

      <div class="grid-4" id="kpi-grid">
        <div class="kpi-card">
          <div class="kpi-label">${t("dashboard.kpi.patients")}<span class="material-symbols-outlined" style="font-size:20px;color:var(--c-text-subtle);">groups</span></div>
          <div class="kpi-value" id="kpi-patients">—</div>
        </div>
        <div class="kpi-card">
          <div class="kpi-label">${t("dashboard.kpi.diseases")}<span class="material-symbols-outlined" style="font-size:20px;color:var(--c-text-subtle);">coronavirus</span></div>
          <div class="kpi-value" id="kpi-diseases">—</div>
        </div>
        <div class="kpi-card">
          <div class="kpi-label">${t("dashboard.kpi.acc")}<span class="material-symbols-outlined" style="font-size:20px;color:var(--c-text-subtle);">verified_user</span></div>
          <div class="kpi-value" id="kpi-acc">—</div>
          <div class="kpi-meta" id="kpi-acc-cv"></div>
        </div>
        <div class="kpi-card">
          <div class="kpi-label">${t("dashboard.kpi.risk_acc")}<span class="material-symbols-outlined" style="font-size:20px;color:var(--c-text-subtle);">vital_signs</span></div>
          <div class="kpi-value" id="kpi-risk">—</div>
          <div class="kpi-meta" id="kpi-risk-cv"></div>
        </div>
      </div>

      <!-- Bento grid: charts on the left + alerts feed on the right -->
      <div class="bento-grid">
        <div class="bento-col-8">
          <div class="chart-card">
            <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:8px;">
              <h4 style="margin:0;">${t("dashboard.chart.diagnoses")}</h4>
              <span class="text-xs text-muted">${t("dashboard.chart.throughput")}</span>
            </div>
            <div class="chart-wrap"><canvas id="ch-dx"></canvas></div>
          </div>

          <div class="insight-panel">
            <span class="material-symbols-outlined insight-decor fill">smart_toy</span>
            <h3><span class="nav-icon">lightbulb</span> ${t("dashboard.insight.title")}</h3>
            <p id="insight-body">${t("dashboard.insight.body")}</p>
            <div class="insight-actions">
              <button class="btn btn-primary" data-go="diagnosis">${t("dashboard.insight.cta1")}</button>
              <button class="btn btn-secondary" data-go="analytics">${t("dashboard.insight.cta2")}</button>
            </div>
          </div>
        </div>

        <div class="bento-col-4">
          <div class="alert-feed" id="dash-alerts">
            <div class="alert-feed-head">
              <h3>${t("dashboard.alerts.title")}</h3>
              <span class="badge badge-danger" id="dash-alerts-count">—</span>
            </div>
            <div class="alert-feed-list" id="dash-alerts-list">
              <div class="empty"><div class="spinner"></div></div>
            </div>
          </div>
        </div>
      </div>

      <div class="grid-2 mt-16">
        <div class="kpi-card">
          <div class="kpi-label">${t("patients.kpi.topDx")}<span class="material-symbols-outlined" style="font-size:20px;color:var(--c-text-subtle);">clinical_notes</span></div>
          <div class="kpi-value" id="kpi-top-dx" style="font-size:22px;">—</div>
        </div>
        <div class="kpi-card">
          <div class="kpi-label">${t("patients.kpi.topZone")}<span class="material-symbols-outlined" style="font-size:20px;color:var(--c-text-subtle);">location_on</span></div>
          <div class="kpi-value" id="kpi-top-zone" style="font-size:22px;">—</div>
        </div>
      </div>

      <div class="chart-trio">
        <div class="chart-card">
          <h4>${t("dashboard.chart.zones")}</h4>
          <div class="chart-wrap chart-sm"><canvas id="ch-zone"></canvas></div>
        </div>
        <div class="chart-card">
          <h4>${t("dashboard.chart.risk")}</h4>
          <div class="chart-wrap chart-sm"><canvas id="ch-risk"></canvas></div>
        </div>
        <div class="chart-card">
          <h4>${t("dashboard.chart.age")}</h4>
          <div class="chart-wrap chart-sm"><canvas id="ch-age"></canvas></div>
        </div>
      </div>

      <h3 class="mt-20 mb-12" style="font-size:12px;color:var(--c-text-muted);text-transform:uppercase;letter-spacing:.5px;font-family:var(--font-data);font-weight:700;">${t("dashboard.quick")}</h3>
      <div class="quick-grid">
        <div class="quick-card" data-go="diagnosis"><div class="ql-icon"><span class="material-symbols-outlined">clinical_notes</span></div><div><div class="ql-title">${t("nav.diagnosis")}</div><div class="ql-sub">${t("diagnosis.sub")}</div></div></div>
        <div class="quick-card" data-go="patients"><div class="ql-icon"><span class="material-symbols-outlined">person_search</span></div><div><div class="ql-title">${t("nav.patients")}</div><div class="ql-sub">${t("patients.sub")}</div></div></div>
        <div class="quick-card" data-go="analytics"><div class="ql-icon"><span class="material-symbols-outlined">monitoring</span></div><div><div class="ql-title">${t("nav.analytics")}</div><div class="ql-sub">${t("analytics.sub")}</div></div></div>
        <div class="quick-card" data-go="report"><div class="ql-icon"><span class="material-symbols-outlined">description</span></div><div><div class="ql-title">${t("nav.report")}</div><div class="ql-sub">${t("report.sub")}</div></div></div>
      </div>
    `;
    $$(".quick-card, .insight-panel [data-go]").forEach(c => {
      c.addEventListener("click", () => navigate(c.dataset.go));
    });

    try {
      const [ov, info, patients] = await Promise.all([
        api("/analytics/overview").catch(() => ({})),
        api("/ai/model-info").catch(() => ({})),
        api("/patients?limit=1000").catch(() => ({})),
      ]);
      const eda = (ov && ov.patients_db) || {};
      const total = eda.total_patients ?? 0;
      $("#kpi-patients").textContent = total.toLocaleString();

      const dCount = (info.disease_classes || []).length;
      $("#kpi-diseases").textContent = dCount || "—";

      const topDx = eda.top_diagnoses?.[0]?.name;
      const topZone = eda.zone_distribution?.[0]?.name;
      const topDxEl = $("#kpi-top-dx"); if (topDxEl) topDxEl.textContent = topDx ? tDx(topDx) : "—";
      const topZoneEl = $("#kpi-top-zone"); if (topZoneEl) topZoneEl.textContent = topZone ? tZone(topZone) : "—";

      const fmt = x => (typeof x === "number" ? (x * 100).toFixed(1) + "%" : "—");
      $("#kpi-acc").textContent = fmt(info.disease_accuracy);
      $("#kpi-acc-cv").textContent = "CV: " + fmt(info.disease_cv_accuracy_mean);
      $("#kpi-risk").textContent = fmt(info.risk_accuracy);
      $("#kpi-risk-cv").textContent = "CV: " + fmt(info.risk_cv_accuracy_mean);

      renderDashboardCharts(eda, patients.patients || []);
      loadDashboardAlerts();
    } catch (_) {}
  }

  async function loadDashboardAlerts() {
    const list = $("#dash-alerts-list");
    const count = $("#dash-alerts-count");
    if (!list || !count) return;
    try {
      const r = await api("/analytics/anomalies?limit=6").catch(() => ({ anomalies: [], anomalies_count: 0 }));
      const items = r.anomalies || [];
      count.textContent = `${r.anomalies_count ?? items.length} ${t("dashboard.alerts.critical")}`;
      if (!items.length) {
        list.innerHTML = `
          <div class="alert-item">
            <span class="dot dot-info"></span>
            <div class="alert-item-body">
              <div class="alert-title">${t("anomalies.none")}<span class="alert-time">${t("dashboard.alerts.now")}</span></div>
              <div class="alert-msg">${t("dashboard.alerts.noneSub")}</div>
            </div>
          </div>`;
        return;
      }
      list.innerHTML = items.slice(0, 6).map((a, i) => {
        const dotCls = i === 0 ? "dot-crit" : (i < 3 ? "dot-warn" : "dot-info");
        const chip = i === 0 ? `<span class="alert-chip">${t("dashboard.alerts.actionRequired")}</span>` : "";
        return `
          <div class="alert-item" data-id="${a.id}">
            <span class="dot ${dotCls}"></span>
            <div class="alert-item-body">
              <div class="alert-title">${escapeHtml(tDx(a.diagnosis) || "Anomaly")}
                <span class="alert-time">${t("anomalies.score")}: ${a.score ?? "—"}</span>
              </div>
              <div class="alert-msg">#${a.id} &middot; ${escapeHtml(a.patient_name || "—")} &middot; ${a.age || "?"} ${t("common.age").toLowerCase()}</div>
              ${chip}
            </div>
          </div>`;
      }).join("");
      $$("#dash-alerts-list .alert-item[data-id]").forEach(el => {
        el.addEventListener("click", () => {
          navigate("patients");
          setTimeout(() => loadPatientReport(parseInt(el.dataset.id, 10)), 60);
        });
      });
    } catch (_) {
      list.innerHTML = `<div class="empty">${t("common.empty")}</div>`;
    }
  }

  function renderDashboardCharts(eda, patients) {
    const CK = window.ChartKit;
    if (!CK || !window.Chart) return;

    const diagItems = (eda.top_diagnoses || []).slice(0, 8);
    if (diagItems.length) CK.bar("ch-dx", diagItems, { labelMapper: tDx, horizontal: true });

    const zoneItems = (eda.zone_distribution || []).slice(0, 10);
    if (zoneItems.length) CK.doughnut("ch-zone", zoneItems, { labelMapper: tZone });

    const riskItems = (eda.risk_distribution || []).filter(r => r.name);
    if (riskItems.length) CK.pie("ch-risk", riskItems, { labelMapper: tRisk });

    const ageBins = { "0-17": 0, "18-34": 0, "35-54": 0, "55-74": 0, "75+": 0 };
    (patients || []).forEach(p => {
      const a = Number(p.age) || 0;
      if (a < 18) ageBins["0-17"]++;
      else if (a < 35) ageBins["18-34"]++;
      else if (a < 55) ageBins["35-54"]++;
      else if (a < 75) ageBins["55-74"]++;
      else ageBins["75+"]++;
    });
    const ageItems = Object.entries(ageBins).map(([name, count]) => ({ name, count }));
    if (ageItems.some(a => a.count > 0)) CK.bar("ch-age", ageItems);
  }

  // ═══════════════════════ DIAGNOSIS ═══════════════════════
  const COMMON_SYMPTOMS = [
    "fever","cough","fatigue","headache","shortness of breath",
    "chest pain","nausea","dizziness","sore throat","body aches",
    "runny nose","weight loss","joint pain","abdominal pain",
  ];

  async function renderDiagnosis() {
    CONTENT().innerHTML = PAGE("diagnosis.title", "diagnosis.sub", `
      <div class="grid-2">
        <div class="card">
          <div class="card-header"><h3 class="card-title">${t("diagnosis.title")}</h3></div>

          <div class="form-field">
            <label>${t("diagnosis.pname")}</label>
            <input id="d-name" type="text" />
          </div>
          <div class="grid-2" style="gap:12px;">
            <div class="form-field"><label>${t("common.age")}</label>
              <input id="d-age" type="number" min="0" max="120" value="35" />
            </div>
            <div class="form-field"><label>${t("common.gender")}</label>
              <select id="d-gender">
                <option value="Male">${t("common.male")}</option>
                <option value="Female">${t("common.female")}</option>
                <option value="Other">${t("common.other")}</option>
              </select>
            </div>
          </div>
          <div class="form-field">
            <label>${t("diagnosis.symptoms")}</label>
            <textarea id="d-symptoms" rows="3" placeholder="${escapeHtml(t("diagnosis.placeholder"))}"></textarea>
          </div>
          <div class="text-xs text-muted">${t("diagnosis.commonSymptoms")}:</div>
          <div class="chips-row" id="d-chips">
            ${COMMON_SYMPTOMS.map(s => `<span class="chip" data-sym="${s}">${escapeHtml(tSym(s))}</span>`).join("")}
          </div>

          <label style="display:flex;align-items:center;gap:8px;margin-top:14px;font-size:13px;cursor:pointer;">
            <input type="checkbox" id="d-save" checked /> ${t("diagnosis.save")}
          </label>

          <div style="display:flex;gap:8px;margin-top:14px;">
            <button class="btn btn-primary" id="d-btn">${t("diagnosis.analyze")}</button>
            <button class="btn btn-secondary" id="d-reset">${t("diagnosis.resetBtn")}</button>
          </div>
        </div>

        <div class="card" id="d-result-card">
          <div class="card-header"><h3 class="card-title">Output</h3></div>
          <div class="empty" id="d-empty">
            <div class="empty-icon material-symbols-outlined">search</div>
            <div>${t("common.empty")}</div>
          </div>
          <div id="d-result" class="result-block hidden"></div>
        </div>
      </div>
    `);

    $$("#d-chips .chip").forEach(c => c.addEventListener("click", () => {
      c.classList.toggle("active");
      const ta = $("#d-symptoms");
      const parts = ta.value.split(",").map(s => s.trim()).filter(Boolean);
      const symLocalized = tSym(c.dataset.sym);
      if (c.classList.contains("active")) {
        if (!parts.includes(symLocalized)) parts.push(symLocalized);
      } else {
        const idx = parts.indexOf(symLocalized);
        if (idx >= 0) parts.splice(idx, 1);
      }
      ta.value = parts.join(", ");
    }));

    $("#d-reset").addEventListener("click", () => {
      $("#d-name").value = ""; $("#d-age").value = 35; $("#d-gender").value = "Male";
      $("#d-symptoms").value = ""; $("#d-save").checked = true;
      $$("#d-chips .chip").forEach(c => c.classList.remove("active"));
      $("#d-empty").classList.remove("hidden");
      $("#d-result").classList.add("hidden");
    });

    $("#d-btn").addEventListener("click", async () => {
      const btn = $("#d-btn");
      const payload = {
        patient_name: $("#d-name").value.trim(),
        age: parseInt($("#d-age").value, 10),
        gender: $("#d-gender").value,
        symptoms: $("#d-symptoms").value.trim(),
        save: $("#d-save").checked,
      };
      if (!payload.symptoms) { toast(t("common.error") + ": " + t("diagnosis.symptoms"), "error"); return; }
      btn.disabled = true;
      $("#d-empty").classList.add("hidden");
      $("#d-result").classList.remove("hidden");
      $("#d-result").innerHTML = `<div style="display:flex;justify-content:center;padding:20px;"><div class="spinner"></div></div>`;
      try {
        const r = await api("/ai/analyze", { method: "POST", body: payload });
        renderDiagnosisResult(r);
        if (r.patient_id) toast(t("diagnosis.saved", { id: r.patient_id }), "success");
      } catch (e) {
        $("#d-result").innerHTML = `<div class="alert alert-danger"><strong>${t("common.error")}:</strong> ${escapeHtml(e.message)}</div>`;
      } finally {
        btn.disabled = false;
      }
    });
  }

  function renderDiagnosisResult(r) {
    const d = r.disease || {};
    const rk = r.risk || {};
    const a = r.assignment || {};
    const an = r.anomaly || {};
    const topHtml = (d.top_predictions || []).map(p => `
      <div class="prob-row">
        <div class="prob-name">${escapeHtml(tDx(p.disease))}</div>
        <div class="prob-track"><div class="prob-fill" style="width:${p.percentage}%"></div></div>
        <div class="prob-pct">${p.percentage}%</div>
      </div>`).join("");
    const recs = (rk.recommendations || []).map(x => `<li>${escapeHtml(x)}</li>`).join("");
    const anomalyBlock = an.available === false ? "" : `
      <div class="result-card">
        <div class="result-title">${t("diagnosis.result.anomaly")}</div>
        <div style="display:flex;gap:10px;align-items:center;margin-top:6px;">
          ${an.is_anomaly
            ? `<span class="badge badge-danger">${t("diagnosis.result.anomaly.yes")}</span>`
            : `<span class="badge badge-active">${t("diagnosis.result.anomaly.no")}</span>`}
          <span class="text-xs text-muted">${t("anomalies.score")}: ${an.score ?? "—"}</span>
        </div>
      </div>`;
    $("#d-result").innerHTML = `
      <div class="result-card">
        <div class="result-title">${t("diagnosis.result.diagnosis")}</div>
        <div class="result-main">${escapeHtml(tDx(d.predicted_disease))}</div>
        <div class="result-conf">${t("common.confidence")}: <strong>${d.confidence_pct ?? 0}%</strong></div>
      </div>

      <div class="result-card">
        <div class="result-title">${t("diagnosis.result.risk")}</div>
        <div class="result-main">
          <span class="risk-pill ${rk.risk_level || ""}">${escapeHtml(tRisk(rk.risk_level))}</span>
        </div>
        <div class="result-conf">${t("common.confidence")}: <strong>${rk.confidence_pct ?? 0}%</strong></div>
      </div>

      <div class="result-card">
        <div class="result-title">${t("diagnosis.result.assignment")}</div>
        <div style="display:grid;grid-template-columns:1fr 1fr;gap:10px;margin-top:4px;">
          <div><div class="text-xs text-muted">${t("diagnosis.result.zone")}</div><div style="font-weight:700;">${escapeHtml(tZone(a.zone))}</div></div>
          <div><div class="text-xs text-muted">${t("diagnosis.result.doctor")}</div><div style="font-weight:700;">${escapeHtml(a.doctor || "—")}</div></div>
        </div>
      </div>

      ${anomalyBlock}

      <div class="result-card">
        <div class="result-title">${t("diagnosis.result.top")}</div>
        ${topHtml || '<div class="text-sm text-muted">—</div>'}
      </div>

      <div class="result-card">
        <div class="result-title">${t("diagnosis.result.recs")}</div>
        <ul style="margin:6px 0 0 18px;">${recs || '<li>—</li>'}</ul>
      </div>

      ${r.symptoms_translated ? `<div class="translation-box">&#127760; ${t("diagnosis.result.translated")}: <em>${escapeHtml(r.symptoms_translated)}</em></div>` : ""}
    `;
  }

  // ═══════════════════════ PATIENTS ═══════════════════════
  async function renderPatients() {
    const u = getUser() || {};
    CONTENT().innerHTML = PAGE("patients.title", "patients.sub", `
      <div class="grid-4 mb-16">
        <div class="kpi-card"><div class="kpi-label">${t("patients.kpi.total")}</div><div class="kpi-value" id="p-total">—</div></div>
        <div class="kpi-card"><div class="kpi-label">${t("patients.kpi.avgAge")}</div><div class="kpi-value" id="p-avg">—</div></div>
        <div class="kpi-card"><div class="kpi-label">${t("patients.kpi.topDx")}</div><div class="kpi-value" id="p-dx">—</div></div>
        <div class="kpi-card"><div class="kpi-label">${t("patients.kpi.topZone")}</div><div class="kpi-value" id="p-zone">—</div></div>
      </div>

      ${u.role === "admin" ? `
      <div class="card mb-16">
        <div class="card-header"><h3 class="card-title">${t("patients.import")}</h3></div>
        <div style="display:flex;gap:10px;align-items:end;flex-wrap:wrap;">
          <div class="form-field" style="min-width:260px;flex:1;margin-bottom:0;">
            <label>${t("patients.selectDs")}</label>
            <select id="p-ds"></select>
          </div>
          <button class="btn btn-accent" id="p-import">${t("patients.import")}</button>
          <button class="btn btn-secondary" id="p-refresh">${t("common.refresh")}</button>
        </div>
        <div id="p-import-msg" class="mt-12 text-sm"></div>
      </div>` : `
      <div class="mb-16"><button class="btn btn-secondary" id="p-refresh">${t("common.refresh")}</button></div>`}

      <div class="card mb-16">
        <div class="card-header"><h3 class="card-title">${t("search.patient")}</h3></div>
        <div class="search-box">
          <input id="p-search" type="search" placeholder="${escapeHtml(t("search.patient"))}" autocomplete="off" />
          <div id="p-search-results" class="search-results hidden"></div>
        </div>
        <div id="p-detail"></div>
      </div>

      <div class="card">
        <div class="card-header"><h3 class="card-title">${t("patients.title")}</h3></div>
        <div class="table-wrap">
          <table>
            <thead><tr>
              <th>${t("patients.table.id")}</th>
              <th>${t("patients.table.name")}</th>
              <th>${t("patients.table.age")}</th>
              <th>${t("patients.table.gender")}</th>
              <th>${t("patients.table.dx")}</th>
              <th>${t("patients.table.risk")}</th>
              <th>${t("patients.table.zone")}</th>
              <th>${t("patients.table.doctor")}</th>
              <th>${t("patients.table.created")}</th>
            </tr></thead>
            <tbody id="p-tbody"><tr><td colspan="9" class="empty">${t("common.loading")}</td></tr></tbody>
          </table>
        </div>
      </div>
    `);

    if (u.role === "admin") {
      await populateDatasetSelect("#p-ds");
      $("#p-import").addEventListener("click", importPatients);
    }
    $("#p-refresh").addEventListener("click", loadPatientsData);

    setupPatientSearch();
    await loadPatientsData();
  }

  // ─── Buscador incremental de pacientes ─────────────────────────────
  let _searchTimer = null;
  function setupPatientSearch() {
    const inp = $("#p-search");
    const box = $("#p-search-results");
    if (!inp || !box) return;
    inp.addEventListener("input", () => {
      const q = inp.value.trim();
      clearTimeout(_searchTimer);
      if (!q) {
        box.classList.add("hidden");
        box.innerHTML = "";
        return;
      }
      _searchTimer = setTimeout(() => runPatientSearch(q), 180);
    });
    inp.addEventListener("focus", () => {
      if (box.innerHTML) box.classList.remove("hidden");
    });
    document.addEventListener("click", (e) => {
      if (!box.contains(e.target) && e.target !== inp) box.classList.add("hidden");
    });
  }

  async function runPatientSearch(q) {
    const box = $("#p-search-results");
    try {
      const r = await api(`/patients/search?q=${encodeURIComponent(q)}&limit=20`);
      if (!r.results || !r.results.length) {
        box.innerHTML = `<div class="search-result-item text-muted">${escapeHtml(t("search.noResults", { q }))}</div>`;
      } else {
        box.innerHTML = r.results.map(p => `
          <div class="search-result-item" data-id="${p.id}">
            <div class="sr-left">
              <strong>${escapeHtml(p.patient_name)}</strong>
              <div class="sr-meta">#${p.id} · ${p.age} · ${escapeHtml(tGender(p.gender))}</div>
            </div>
            <div class="sr-dx">${escapeHtml(tDx(p.diagnosis))}</div>
          </div>
        `).join("");
        $$("#p-search-results .search-result-item[data-id]").forEach(el => {
          el.addEventListener("click", () => {
            $("#p-search-results").classList.add("hidden");
            loadPatientReport(parseInt(el.dataset.id, 10));
          });
        });
      }
      box.classList.remove("hidden");
    } catch (e) {
      box.innerHTML = `<div class="search-result-item">${escapeHtml(e.message)}</div>`;
      box.classList.remove("hidden");
    }
  }

  async function loadPatientReport(id) {
    const out = $("#p-detail");
    out.innerHTML = `<div class="patient-report"><div class="empty"><div class="spinner"></div></div></div>`;
    try {
      const r = await api(`/patients/${id}`);
      renderPatientReport(r);
    } catch (e) {
      out.innerHTML = `<div class="alert alert-danger mt-12">${escapeHtml(e.message)}</div>`;
    }
  }

  function renderPatientReport(data) {
    const p = data.patient || {};
    const an = data.anomaly || {};
    const recs = data.recommendations || [];
    const initial = (p.patient_name || "?").charAt(0).toUpperCase();
    const symptoms = (p.symptoms_translated || p.symptoms || "")
      .split(",").map(s => s.trim()).filter(Boolean);
    const created = (p.created_at || "").replace("T", " ").slice(0, 19);

    const anomalyBadge = an && an.available !== false
      ? (an.is_anomaly
          ? `<span class="badge badge-danger">${escapeHtml(t("anomalies.badge"))}</span>`
          : `<span class="badge badge-active">${escapeHtml(t("diagnosis.result.anomaly.no"))}</span>`)
      : "";

    $("#p-detail").innerHTML = `
      <div class="patient-report" id="p-report">
        <div class="pr-header">
          <div style="display:flex;gap:14px;align-items:center;">
            <div class="pr-avatar">${escapeHtml(initial)}</div>
            <div>
              <h3 class="pr-name">${escapeHtml(p.patient_name || "—")}</h3>
              <div class="pr-id">ID #${p.id} · ${escapeHtml(t("report.patient.created"))}: ${escapeHtml(created)}</div>
            </div>
          </div>
          <div class="pr-actions">
            ${anomalyBadge}
            <button class="btn btn-ghost btn-sm" id="pr-print">${t("report.patient.print")}</button>
            <button class="btn btn-ghost btn-sm" id="pr-close">${t("report.patient.back")}</button>
          </div>
        </div>

        <div class="pr-grid">
          <div class="pr-field"><div class="pr-label">${t("common.age")}</div><div class="pr-value">${p.age ?? "—"}</div></div>
          <div class="pr-field"><div class="pr-label">${t("common.gender")}</div><div class="pr-value">${escapeHtml(tGender(p.gender))}</div></div>
          <div class="pr-field"><div class="pr-label">${t("patients.table.dx")}</div><div class="pr-value">${escapeHtml(tDx(p.diagnosis))}</div></div>
          <div class="pr-field"><div class="pr-label">${t("patients.table.risk")}</div>
            <div class="pr-value"><span class="risk-pill ${p.risk_level || ""}">${escapeHtml(tRisk(p.risk_level))}</span></div></div>
          <div class="pr-field"><div class="pr-label">${t("patients.table.zone")}</div><div class="pr-value">${escapeHtml(tZone(p.hospital_zone))}</div></div>
          <div class="pr-field"><div class="pr-label">${t("patients.table.doctor")}</div><div class="pr-value">${escapeHtml(p.specialist_doctor || "—")}</div></div>
        </div>

        <div class="pr-section">
          <h4>${t("report.patient.symptoms")}</h4>
          <div class="pr-sym-tags">
            ${symptoms.length
              ? symptoms.map(s => `<span class="disease-sym-tag">${escapeHtml(tSym(s))}</span>`).join("")
              : `<span class="text-muted">—</span>`}
          </div>
        </div>

        <div class="pr-section">
          <h4>${t("report.patient.vitals")}</h4>
          <div class="pr-grid">
            <div class="pr-field">
              <div class="pr-label">${t("report.patient.confidence")} Dx</div>
              <div class="pr-value">${((p.diagnosis_confidence || 0) * 100).toFixed(1)}%</div>
            </div>
            <div class="pr-field">
              <div class="pr-label">${t("report.patient.confidence")} ${t("patients.table.risk")}</div>
              <div class="pr-value">${((p.risk_confidence || 0) * 100).toFixed(1)}%</div>
            </div>
            <div class="pr-field">
              <div class="pr-label">${t("anomalies.score")}</div>
              <div class="pr-value">${an && an.score != null ? an.score : "—"}</div>
            </div>
          </div>
        </div>

        ${recs.length ? `
        <div class="pr-section">
          <h4>${t("diagnosis.result.recs")}</h4>
          <ul style="margin:4px 0 0 18px;">${recs.map(r => `<li>${escapeHtml(r)}</li>`).join("")}</ul>
        </div>` : ""}

        <div class="pr-section">
          <h4>${t("report.patient.meta")}</h4>
          <div class="pr-grid">
            <div class="pr-field"><div class="pr-label">${t("report.patient.source")}</div><div class="pr-value">${escapeHtml(p.source_dataset || "—")}</div></div>
            <div class="pr-field"><div class="pr-label">${t("report.patient.createdBy")}</div><div class="pr-value">${escapeHtml(p.created_by || "—")}</div></div>
            <div class="pr-field"><div class="pr-label">${t("report.patient.created")}</div><div class="pr-value">${escapeHtml(created)}</div></div>
          </div>
        </div>
      </div>
    `;
    $("#pr-close").addEventListener("click", () => { $("#p-detail").innerHTML = ""; });
    $("#pr-print").addEventListener("click", () => {
      const w = window.open("", "_blank", "width=900,height=1000");
      if (!w) return;
      w.document.write(`<!doctype html><html><head><meta charset="utf-8"><title>Informe paciente #${p.id}</title>
        <link rel="stylesheet" href="${location.origin}/css/style.css"></head>
        <body style="padding:30px;background:#fff;">${$("#p-report").outerHTML}</body></html>`);
      w.document.close();
      setTimeout(() => { w.focus(); w.print(); }, 400);
    });
  }

  async function populateDatasetSelect(sel) {
    try {
      const r = await api("/dataset/list");
      const el = $(sel);
      el.innerHTML = (r.datasets || []).map(d =>
        `<option value="${escapeHtml(d.path)}">${escapeHtml(d.name)} (${d.size_kb} KB)</option>`
      ).join("");
    } catch (_) {
      $(sel).innerHTML = `<option>—</option>`;
    }
  }

  async function importPatients() {
    const btn = $("#p-import"); const msg = $("#p-import-msg");
    const dsPath = $("#p-ds").value;
    btn.disabled = true;
    msg.innerHTML = `<div class="alert alert-info">${t("common.loading")}</div>`;
    try {
      const r = await api("/patients/import-dataset", {
        method: "POST",
        body: { dataset: dsPath },
      });
      msg.innerHTML = `<div class="alert alert-success">${t("patients.import.ok", { n: r.imported || 0 })}</div>`;
      toast(t("patients.import.ok", { n: r.imported || 0 }), "success");
      await loadPatientsData();
    } catch (e) {
      msg.innerHTML = `<div class="alert alert-danger">${escapeHtml(e.message)}</div>`;
    } finally {
      btn.disabled = false;
    }
  }

  async function loadPatientsData() {
    try {
      const [eda, list] = await Promise.all([
        api("/patients/eda").catch(() => ({})),
        api("/patients?limit=500").catch(() => ({})),
      ]);
      $("#p-total").textContent = (eda.total_patients ?? 0).toLocaleString();
      $("#p-avg").textContent   = eda.age_stats?.avg_age ?? "—";
      $("#p-dx").textContent    = eda.top_diagnoses?.[0]?.name ? tDx(eda.top_diagnoses[0].name) : "—";
      $("#p-zone").textContent  = eda.zone_distribution?.[0]?.name ? tZone(eda.zone_distribution[0].name) : "—";

      const rows = list.patients || [];
      const body = $("#p-tbody");
      if (!rows.length) {
        body.innerHTML = `<tr><td colspan="9" class="empty">${t("common.empty")}</td></tr>`;
        return;
      }
      body.innerHTML = rows.map(p => `
        <tr>
          <td>${p.id}</td>
          <td>${escapeHtml(p.patient_name)}</td>
          <td>${p.age}</td>
          <td>${escapeHtml(tGender(p.gender))}</td>
          <td>${escapeHtml(tDx(p.diagnosis))}</td>
          <td><span class="risk-pill ${p.risk_level}">${escapeHtml(tRisk(p.risk_level))}</span></td>
          <td>${escapeHtml(tZone(p.hospital_zone))}</td>
          <td>${escapeHtml(p.specialist_doctor)}</td>
          <td>${escapeHtml((p.created_at || "").replace("T", " ").slice(0, 16))}</td>
        </tr>`).join("");
    } catch (e) {
      toast(e.message, "error");
    }
  }

  // ═══════════════════════ DISEASES ═══════════════════════
  async function renderDiseases() {
    CONTENT().innerHTML = PAGE("diseases.title", "diseases.sub", `
      <div class="card mb-16">
        <div class="card-header"><h3 class="card-title">${t("diseases.create")}</h3></div>
        <div class="grid-2" style="gap:10px;">
          <div class="form-field">
            <label>${t("diseases.name")}</label>
            <input id="disease-name" />
          </div>
          <div class="form-field">
            <label>${t("diseases.symptoms")}</label>
            <input id="disease-symptoms" list="symptoms-bank" placeholder="${t("diseases.symptoms.placeholder")}" />
            <datalist id="symptoms-bank"></datalist>
          </div>
        </div>
        <div class="form-field">
          <label>${t("diseases.selected")}</label>
          <div id="disease-sym-chipbox" class="disease-symptoms"></div>
        </div>
        <div style="display:flex;gap:10px;flex-wrap:wrap;">
          <button class="btn btn-secondary" id="disease-add-sym">${t("diseases.addSymptom")}</button>
          <button class="btn btn-primary" id="disease-save">${t("diseases.save")}</button>
        </div>
        <div id="disease-msg" class="mt-12"></div>
      </div>
      <div id="dis-grid" class="grid-3"><div class="empty"><div class="spinner"></div></div></div>
    `);

    const selectedSymptoms = new Map();
    function renderSymptomChips() {
      const box = $("#disease-sym-chipbox");
      const values = Array.from(selectedSymptoms.values());
      if (!values.length) {
        box.innerHTML = `<span class="text-sm text-muted">${t("common.empty")}</span>`;
        return;
      }
      box.innerHTML = values.map((sym) => `
        <span class="disease-sym-tag" style="display:inline-flex;align-items:center;gap:6px;">
          ${escapeHtml(sym)}
          <button class="btn btn-ghost btn-sm" style="padding:0 6px;" data-rm-sym="${escapeHtml(sym.toLowerCase())}">&times;</button>
        </span>
      `).join("");
      $$("[data-rm-sym]").forEach((b) => b.addEventListener("click", () => {
        selectedSymptoms.delete(b.dataset.rmSym);
        renderSymptomChips();
      }));
    }

    function addCurrentSymptom() {
      const inp = $("#disease-symptoms");
      const val = inp.value.trim();
      if (!val) return;
      splitSymptoms(val).forEach((sym) => selectedSymptoms.set(sym.toLowerCase(), sym));
      inp.value = "";
      renderSymptomChips();
    }

    $("#disease-add-sym").addEventListener("click", addCurrentSymptom);
    $("#disease-symptoms").addEventListener("keydown", (e) => {
      if (e.key === "Enter" || e.key === ",") {
        e.preventDefault();
        addCurrentSymptom();
      }
    });
    $("#disease-save").addEventListener("click", async () => {
      addCurrentSymptom();
      const name = $("#disease-name").value.trim();
      const symptoms = Array.from(selectedSymptoms.values());
      try {
        await api("/diseases", { method: "POST", body: { name, symptoms } });
        $("#disease-msg").innerHTML = `<div class="alert alert-success">${t("diseases.saved")}</div>`;
        $("#disease-name").value = "";
        selectedSymptoms.clear();
        renderSymptomChips();
        await loadSymptomsBank();
        await loadDiseasesList();
      } catch (e) {
        $("#disease-msg").innerHTML = `<div class="alert alert-danger">${escapeHtml(e.message)}</div>`;
      }
    });

    async function loadSymptomsBank() {
      try {
        const r = await api("/diseases/symptoms");
        const bank = r.symptoms || [];
        $("#symptoms-bank").innerHTML = bank.map((s) => `<option value="${escapeHtml(s)}"></option>`).join("");
      } catch (_) {}
    }

    async function loadDiseasesList() {
      try {
        const list = await api("/diseases");
        if (!list.length) { $("#dis-grid").innerHTML = `<div class="empty">${t("common.empty")}</div>`; return; }
        $("#dis-grid").innerHTML = list.map(d => `
          <div class="disease-card">
            <div class="disease-card-head">
              <div class="disease-icon"><span class="material-symbols-outlined">coronavirus</span></div>
              <div>
                <div class="disease-name">${escapeHtml(tDx(d.name))}</div>
                <div class="disease-cases">${(d.count || 0).toLocaleString()} ${t("patients.kpi.total").toLowerCase()} · ${t("common.age")} ${d.avg_age || 0}${d.manual ? ` · <span class="badge badge-info">${t("diseases.manual")}</span>` : ""}</div>
              </div>
            </div>
            <div class="disease-symptoms">
              ${(d.common_symptoms || []).slice(0, 8).map(s => `<span class="disease-sym-tag">${escapeHtml(tSym(s))}</span>`).join("")}
            </div>
          </div>`).join("");
      } catch (e) {
        $("#dis-grid").innerHTML = `<div class="alert alert-danger">${escapeHtml(e.message)}</div>`;
      }
    }

    renderSymptomChips();
    await loadSymptomsBank();
    await loadDiseasesList();
  }

  // ═══════════════════════ DOCTORS ═══════════════════════
  async function renderDoctors() {
    CONTENT().innerHTML = PAGE("doctors.title", "doctors.sub", `
      <div class="card mb-16">
        <div class="card-header"><h3 class="card-title">${t("doctors.create")}</h3></div>
        <input type="hidden" id="doc-id" />
        <div class="grid-4" style="gap:10px;">
          <div class="form-field"><label>${t("common.name")}</label><input id="doc-name" /></div>
          <div class="form-field"><label>${t("doctors.specialty")}</label><input id="doc-specialty" /></div>
          <div class="form-field"><label>${t("doctors.zone")}</label><input id="doc-zone" /></div>
          <div class="form-field"><label>${t("users.email")}</label><input id="doc-email" type="email" /></div>
          <div class="form-field"><label>${t("doctors.phone")}</label><input id="doc-phone" /></div>
          <div class="form-field"><label>${t("doctors.shift")}</label><input id="doc-shift" /></div>
        </div>
        <div class="form-field"><label>${t("doctors.notes")}</label><textarea id="doc-notes"></textarea></div>
        <div style="display:flex;gap:10px;flex-wrap:wrap;">
          <button class="btn btn-primary" id="doc-save">${t("common.save")}</button>
          <button class="btn btn-secondary" id="doc-reset">${t("diagnosis.resetBtn")}</button>
        </div>
        <div id="doc-msg" class="mt-12"></div>
      </div>

      <div class="card">
        <div class="card-header">
          <h3 class="card-title">${t("doctors.list")}</h3>
          <button class="btn btn-ghost btn-sm" id="doc-refresh">${t("common.refresh")}</button>
        </div>
        <div class="table-wrap">
          <table>
            <thead>
              <tr>
                <th>${t("common.name")}</th>
                <th>${t("doctors.specialty")}</th>
                <th>${t("doctors.zone")}</th>
                <th>${t("users.email")}</th>
                <th>${t("doctors.phone")}</th>
                <th>${t("doctors.shift")}</th>
                <th>${t("common.actions")}</th>
              </tr>
            </thead>
            <tbody id="doc-tbody"><tr><td colspan="7" class="empty">${t("common.loading")}</td></tr></tbody>
          </table>
        </div>
      </div>
    `);

    const toBody = () => ({
      name: $("#doc-name").value.trim(),
      specialty: $("#doc-specialty").value.trim(),
      zone: $("#doc-zone").value.trim(),
      email: $("#doc-email").value.trim(),
      phone: $("#doc-phone").value.trim(),
      shift: $("#doc-shift").value.trim(),
      notes: $("#doc-notes").value.trim(),
    });
    const resetDocForm = () => {
      $("#doc-id").value = "";
      $("#doc-name").value = "";
      $("#doc-specialty").value = "";
      $("#doc-zone").value = "";
      $("#doc-email").value = "";
      $("#doc-phone").value = "";
      $("#doc-shift").value = "";
      $("#doc-notes").value = "";
    };

    async function loadDoctors() {
      try {
        const r = await api("/doctors");
        const rows = r.doctors || [];
        $("#doc-tbody").innerHTML = rows.length
          ? rows.map((d) => `
            <tr>
              <td><strong>${escapeHtml(d.name)}</strong></td>
              <td>${escapeHtml(d.specialty || "")}</td>
              <td>${escapeHtml(d.zone || "")}</td>
              <td>${escapeHtml(d.email || "")}</td>
              <td>${escapeHtml(d.phone || "")}</td>
              <td>${escapeHtml(d.shift || "")}</td>
              <td><button class="btn btn-secondary btn-sm" data-edit-doc="${d.id}">${t("common.edit")}</button></td>
            </tr>`).join("")
          : `<tr><td colspan="7" class="empty">${t("common.empty")}</td></tr>`;
        $$("#doc-tbody [data-edit-doc]").forEach((b) => b.addEventListener("click", () => {
          const row = rows.find((x) => String(x.id) === String(b.dataset.editDoc));
          if (!row) return;
          $("#doc-id").value = row.id;
          $("#doc-name").value = row.name || "";
          $("#doc-specialty").value = row.specialty || "";
          $("#doc-zone").value = row.zone || "";
          $("#doc-email").value = row.email || "";
          $("#doc-phone").value = row.phone || "";
          $("#doc-shift").value = row.shift || "";
          $("#doc-notes").value = row.notes || "";
          window.scrollTo({ top: 0, behavior: "smooth" });
        }));
      } catch (e) {
        $("#doc-tbody").innerHTML = `<tr><td colspan="7" class="alert alert-danger">${escapeHtml(e.message)}</td></tr>`;
      }
    }

    $("#doc-save").addEventListener("click", async () => {
      const body = toBody();
      const id = $("#doc-id").value.trim();
      try {
        if (id) await api(`/doctors/${id}`, { method: "PUT", body });
        else await api("/doctors", { method: "POST", body });
        $("#doc-msg").innerHTML = `<div class="alert alert-success">${id ? t("doctors.updated") : t("doctors.created")}</div>`;
        resetDocForm();
        await loadDoctors();
      } catch (e) {
        $("#doc-msg").innerHTML = `<div class="alert alert-danger">${escapeHtml(e.message)}</div>`;
      }
    });
    $("#doc-reset").addEventListener("click", resetDocForm);
    $("#doc-refresh").addEventListener("click", loadDoctors);
    await loadDoctors();
  }

  // ═══════════════════════ ANALYTICS ═══════════════════════
  async function renderAnalytics() {
    CONTENT().innerHTML = PAGE("analytics.title", "analytics.sub", `
      <div class="grid-2">
        <div class="card">
          <div class="card-header"><h3 class="card-title">${t("analytics.patterns")}</h3></div>
          <div class="table-wrap">
            <table>
              <thead><tr><th>${t("analytics.pair")}</th><th>${t("analytics.count")}</th></tr></thead>
              <tbody id="an-pairs"><tr><td colspan="2" class="empty">${t("common.loading")}</td></tr></tbody>
            </table>
          </div>
        </div>
        <div class="card">
          <div class="card-header"><h3 class="card-title">${t("analytics.ageByDx")}</h3></div>
          <div class="table-wrap">
            <table>
              <thead><tr>
                <th>${t("analytics.dx")}</th><th>${t("analytics.avgAge")}</th>
                <th>${t("analytics.minAge")}</th><th>${t("analytics.maxAge")}</th><th>${t("analytics.n")}</th>
              </tr></thead>
              <tbody id="an-ages"><tr><td colspan="5" class="empty">${t("common.loading")}</td></tr></tbody>
            </table>
          </div>
        </div>
      </div>
    `);
    try {
      const r = await api("/analytics/patterns");
      $("#an-pairs").innerHTML = (r.top_symptom_pairs || []).map(p =>
        `<tr><td>${escapeHtml(tSymPair(p.pair))}</td><td>${p.count.toLocaleString()}</td></tr>`
      ).join("") || `<tr><td colspan="2" class="empty">${t("common.empty")}</td></tr>`;
      $("#an-ages").innerHTML = (r.age_stats_by_diagnosis || []).map(a =>
        `<tr><td>${escapeHtml(tDx(a.diagnosis))}</td><td>${a.avg_age}</td><td>${a.min_age}</td><td>${a.max_age}</td><td>${a.n.toLocaleString()}</td></tr>`
      ).join("") || `<tr><td colspan="5" class="empty">${t("common.empty")}</td></tr>`;
    } catch (e) {
      CONTENT().innerHTML += `<div class="alert alert-danger mt-16">${escapeHtml(e.message)}</div>`;
    }
  }

  // ═══════════════════════ ANOMALIES ═══════════════════════
  async function renderAnomalies() {
    CONTENT().innerHTML = PAGE("anomalies.title", "anomalies.sub", `
      <div class="card">
        <div class="card-header">
          <h3 class="card-title">${t("anomalies.title")}</h3>
          <button class="btn btn-primary" id="an-run">${t("anomalies.check")}</button>
        </div>
        <div id="an-out"><div class="empty">${t("common.empty")}</div></div>
      </div>
    `);
    $("#an-run").addEventListener("click", loadAnomalies);
    await loadAnomalies();
  }

  async function loadAnomalies() {
    const out = $("#an-out");
    out.innerHTML = `<div class="empty"><div class="spinner"></div></div>`;
    try {
      const r = await api("/analytics/anomalies?limit=500");
      if (!r.anomalies_count) {
        out.innerHTML = `<div class="alert alert-success">${t("anomalies.none")} (${r.checked} ${t("patients.kpi.total").toLowerCase()})</div>`;
        return;
      }
      out.innerHTML = `
        <div class="alert alert-warning mb-12">${r.anomalies_count} / ${r.checked}</div>
        <div class="table-wrap">
          <table>
            <thead><tr>
              <th>${t("patients.table.id")}</th><th>${t("patients.table.name")}</th>
              <th>${t("patients.table.age")}</th><th>${t("patients.table.dx")}</th>
              <th>${t("patients.table.risk")}</th><th>${t("anomalies.score")}</th>
            </tr></thead>
            <tbody>
              ${r.anomalies.map(a => `
                <tr>
                  <td>${a.id}</td>
                  <td>${escapeHtml(a.patient_name || "—")}</td>
                  <td>${a.age}</td>
                  <td>${escapeHtml(tDx(a.diagnosis))}</td>
                  <td><span class="badge badge-danger">${escapeHtml(t("anomalies.badge"))}</span></td>
                  <td>${a.score}</td>
                </tr>`).join("")}
            </tbody>
          </table>
        </div>`;
    } catch (e) {
      out.innerHTML = `<div class="alert alert-danger">${escapeHtml(e.message)}</div>`;
    }
  }

  // ═══════════════════════ DATASET ═══════════════════════
  async function renderDataset() {
    CONTENT().innerHTML = PAGE("dataset.title", "dataset.sub", `
      <div class="grid-2">
        <div class="card">
          <div class="card-header"><h3 class="card-title">${t("dataset.upload")}</h3></div>
          <div class="upload-zone" id="ds-upload">
            <span class="up-icon material-symbols-outlined">cloud_upload</span>
            <div>${t("dataset.dropHere")}</div>
            <input id="ds-file" type="file" accept=".csv" style="display:none;" />
          </div>
          <div id="ds-up-msg" class="mt-12 text-sm"></div>
        </div>
        <div class="card">
          <div class="card-header">
            <h3 class="card-title">${t("dataset.available")}</h3>
            <button class="btn btn-ghost btn-sm" id="ds-refresh">${t("common.refresh")}</button>
          </div>
          <div id="ds-list" class="ds-list"><div class="empty">${t("common.loading")}</div></div>
        </div>
      </div>

      <div class="card mt-16">
        <div class="card-header">
          <h3 class="card-title">${t("pipeline.title")}</h3>
        </div>
        <p class="text-sm text-muted" style="margin:0 0 10px;">${t("pipeline.sub")}</p>
        <div style="display:flex;gap:10px;align-items:end;flex-wrap:wrap;">
          <div class="form-field" style="min-width:280px;flex:1;margin-bottom:0;">
            <label>${t("patients.selectDs")}</label>
            <select id="pipe-ds"></select>
          </div>
          <button class="btn btn-primary" id="pipe-run">${t("pipeline.run")}</button>
        </div>
        <div id="pipe-out" class="mt-12"></div>
      </div>
    `);

    const zone = $("#ds-upload");
    const inp = $("#ds-file");
    zone.addEventListener("click", () => inp.click());
    zone.addEventListener("dragover", e => { e.preventDefault(); zone.classList.add("drag-over"); });
    zone.addEventListener("dragleave", () => zone.classList.remove("drag-over"));
    zone.addEventListener("drop", e => {
      e.preventDefault(); zone.classList.remove("drag-over");
      if (e.dataTransfer.files.length) uploadDs(e.dataTransfer.files[0]);
    });
    inp.addEventListener("change", () => { if (inp.files[0]) uploadDs(inp.files[0]); });
    $("#ds-refresh").addEventListener("click", loadDsList);

    await populateDatasetSelect("#pipe-ds");
    $("#pipe-run").addEventListener("click", runPipeline);

    await loadDsList();
  }

  async function uploadDs(file) {
    const msg = $("#ds-up-msg");
    msg.innerHTML = `<div class="alert alert-info">${t("common.loading")}</div>`;
    try {
      const fd = new FormData(); fd.append("file", file);
      const r = await api("/dataset/upload", { method: "POST", body: fd });
      msg.innerHTML = `<div class="alert alert-success">${escapeHtml(r.filename)} · ${r.rows} ${t("dataset.rows")}</div>`;
      toast(t("dataset.uploaded"), "success");
      await loadDsList();
      await populateDatasetSelect("#pipe-ds");
      // Auto-ejecutar pipeline sobre el dataset recien subido
      const sel = $("#pipe-ds");
      if (sel) {
        const opt = Array.from(sel.options).find(o => o.textContent.startsWith(r.filename));
        if (opt) { sel.value = opt.value; runPipeline(); }
      }
    } catch (e) {
      msg.innerHTML = `<div class="alert alert-danger">${escapeHtml(e.message)}</div>`;
    }
  }

  async function loadDsList() {
    try {
      const r = await api("/dataset/list");
      const box = $("#ds-list");
      const items = r.datasets || [];
      if (!items.length) { box.innerHTML = `<div class="empty">${t("common.empty")}</div>`; return; }
      box.innerHTML = items.map(d => `
        <div class="ds-item">
          <div class="ds-item-icon"><span class="material-symbols-outlined">description</span></div>
          <div class="ds-item-info">
            <div class="ds-item-name">${escapeHtml(d.name)}
              ${d.type === "main" ? `<span class="badge badge-info" style="margin-left:6px;">main</span>` : ""}
            </div>
            <div class="ds-item-meta">${d.size_kb} KB</div>
          </div>
          <button class="btn btn-ghost btn-sm ds-pipe-btn" data-path="${escapeHtml(d.path)}">${t("pipeline.run")}</button>
        </div>`).join("");
      $$(".ds-pipe-btn").forEach(b => b.addEventListener("click", () => {
        $("#pipe-ds").value = b.dataset.path;
        runPipeline();
      }));
    } catch (e) {
      $("#ds-list").innerHTML = `<div class="alert alert-danger">${escapeHtml(e.message)}</div>`;
    }
  }

  async function runPipeline() {
    const out = $("#pipe-out");
    const path = $("#pipe-ds")?.value;
    if (!path) { out.innerHTML = `<div class="alert alert-warning">${t("search.minChars")}</div>`; return; }
    out.innerHTML = `
      <div class="alert alert-info">${t("pipeline.running")}</div>
      <div class="pipeline-stages">
        ${[1, 2, 3, 4].map(n => `
          <div class="pipe-stage running">
            <div class="pipe-head">
              <div class="pipe-num">${n}</div>
              <div class="pipe-title">${t(`pipeline.stage.${["ingest","clean","transform","analyze"][n-1]}`)}</div>
            </div>
            <div class="pipe-body"><div class="spinner" style="width:18px;height:18px;border-width:2px;"></div></div>
          </div>`).join("")}
      </div>`;
    try {
      const r = await api("/dataset/pipeline", { method: "POST", body: { dataset: path } });
      renderPipelineResult(r);
    } catch (e) {
      out.innerHTML = `<div class="alert alert-danger">${escapeHtml(e.message)}</div>`;
    }
  }

  function renderPipelineResult(r) {
    const out = $("#pipe-out");
    const s = r.stages || [];
    const sum = r.summary || {};
    const stageByName = Object.fromEntries(s.map(x => [x.stage, x]));

    const mkStage = (num, key, body) => {
      const st = stageByName[key] || {};
      const cls = !st.ok ? (st.error || st.missing_required?.length ? "err" : "") : "ok";
      return `
        <div class="pipe-stage ${cls}">
          <div class="pipe-head">
            <div class="pipe-num">${num}</div>
            <div class="pipe-title">${t(`pipeline.stage.${key}`)}</div>
            <div class="pipe-elapsed">${st.elapsed_ms ?? 0} ms</div>
          </div>
          <div class="pipe-body">${body(st)}</div>
        </div>`;
    };

    const stats = (pairs) => pairs.map(([k, v]) =>
      `<div class="pipe-stat"><span>${escapeHtml(k)}</span><strong>${escapeHtml(String(v))}</strong></div>`).join("");

    const ingestBody = (st) => stats([
      [t("pipeline.rows_raw"), (st.rows_raw ?? 0).toLocaleString()],
      [t("pipeline.required_ok"), st.required_ok ? t("common.yes") : t("common.no")],
      ["KB", st.size_kb ?? 0],
    ]) + (st.error ? `<div class="alert alert-danger mt-8">${escapeHtml(st.error)}</div>` : "");

    const cleanBody = (st) => {
      const rm = st.removed || {};
      return stats([
        [t("pipeline.rows_after"), (st.rows_after ?? 0).toLocaleString()],
        [t("pipeline.duplicates"), rm.duplicates ?? 0],
        [t("pipeline.missing"), rm.missing_critical ?? 0],
        [t("pipeline.outliers"), rm.age_outliers ?? 0],
        [t("pipeline.dropout"), `${st.dropout_pct ?? 0}%`],
      ]);
    };

    const transformBody = (st) => stats([
      [t("pipeline.features"), (st.features || []).length],
      [t("pipeline.rows_after"), (st.rows_transformed ?? 0).toLocaleString()],
    ]);

    const analyzeBody = (st) => {
      const totals = st.totals || {};
      const age = st.age_stats || {};
      return stats([
        [t("pipeline.distinct"), totals.distinct_diagnoses ?? 0],
        [t("common.age"), `${age.min ?? "—"}–${age.max ?? "—"} (μ ${age.mean ?? "—"})`],
      ]);
    };

    out.innerHTML = `
      <div class="alert ${r.ok ? "alert-success" : "alert-warning"}">
        ${r.ok ? t("pipeline.ok") : t("pipeline.failed")}
        — ${sum.rows_final?.toLocaleString?.() ?? 0} ${t("dataset.rows")} · ${sum.total_elapsed_ms ?? 0} ms
      </div>
      <div class="pipeline-stages">
        ${mkStage(1, "ingest", ingestBody)}
        ${mkStage(2, "clean", cleanBody)}
        ${mkStage(3, "transform", transformBody)}
        ${mkStage(4, "analyze", analyzeBody)}
      </div>

      ${renderPipelineAnalysisCharts(stageByName.analyze || {})}
    `;

    // Render charts inside analysis card
    const an = stageByName.analyze || {};
    setTimeout(() => {
      const CK = window.ChartKit;
      if (!CK) return;
      if ((an.diagnosis_distribution || []).length)
        CK.bar("pipe-ch-dx", an.diagnosis_distribution.slice(0, 10), { labelMapper: tDx, horizontal: true });
      if ((an.age_bins || []).length)
        CK.bar("pipe-ch-age", an.age_bins);
      if ((an.top_symptoms || []).length)
        CK.bar("pipe-ch-sym", an.top_symptoms.slice(0, 10), { labelMapper: tSym, horizontal: true });
      if ((an.gender_distribution || []).length)
        CK.pie("pipe-ch-gender", an.gender_distribution, { labelMapper: tGender });
    }, 20);
  }

  function renderPipelineAnalysisCharts(an) {
    if (!an || !an.ok) return "";
    return `
      <div class="chart-trio mt-16">
        <div class="chart-card"><h4>${t("dashboard.chart.diagnoses")}</h4>
          <div class="chart-wrap"><canvas id="pipe-ch-dx"></canvas></div></div>
        <div class="chart-card"><h4>${t("dashboard.chart.age")}</h4>
          <div class="chart-wrap"><canvas id="pipe-ch-age"></canvas></div></div>
        <div class="chart-card"><h4>${t("dashboard.chart.gender")}</h4>
          <div class="chart-wrap"><canvas id="pipe-ch-gender"></canvas></div></div>
      </div>
      <div class="chart-card mt-16">
        <h4>${t("analytics.patterns")}</h4>
        <div class="chart-wrap chart-lg"><canvas id="pipe-ch-sym"></canvas></div>
      </div>
    `;
  }

  // ═══════════════════════ MODEL ═══════════════════════
  let trainPoll = null;
  async function renderModel() {
    const u = getUser() || {};
    CONTENT().innerHTML = PAGE("model.title", "model.sub", `
      <div class="grid-4 mb-16">
        <div class="kpi-card"><div class="kpi-label">${t("model.diseaseAcc")}</div><div class="kpi-value" id="m-disease">—</div><div class="kpi-meta" id="m-disease-cv"></div></div>
        <div class="kpi-card"><div class="kpi-label">${t("model.riskAcc")}</div><div class="kpi-value" id="m-risk">—</div><div class="kpi-meta" id="m-risk-cv"></div></div>
        <div class="kpi-card"><div class="kpi-label">${t("model.nSamples")}</div><div class="kpi-value" id="m-n">—</div></div>
        <div class="kpi-card"><div class="kpi-label">${t("model.trainedAt")}</div><div class="kpi-value" id="m-trained" style="font-size:14px;">—</div></div>
      </div>

      <div class="card mb-16">
        <div class="card-header"><h3 class="card-title">${t("model.methodology")}</h3></div>
        <p class="text-sm text-muted" style="margin:0;">${t("model.methodology.body")}</p>
        <div class="mt-12 text-xs text-muted"><strong>${t("model.features")}:</strong> <span id="m-feats">—</span></div>
      </div>

      ${u.role === "admin" ? `
      <div class="card">
        <div class="card-header"><h3 class="card-title">${t("model.trainBtn")}</h3></div>
        <div style="display:flex;gap:10px;align-items:end;flex-wrap:wrap;">
          <div class="form-field" style="min-width:260px;flex:1;margin-bottom:0;">
            <label>${t("model.dsForTrain")}</label>
            <select id="m-ds"></select>
          </div>
          <button class="btn btn-primary" id="m-train">${t("model.trainBtn")}</button>
        </div>
        <div id="m-msg" class="mt-12"></div>
        <div id="m-bar" class="train-bar mt-12 hidden"><div class="train-bar-fill"></div></div>
      </div>` : ""}
    `);

    await loadModelInfo();
    if (u.role === "admin") {
      await populateDatasetSelect("#m-ds");
      $("#m-train").addEventListener("click", startTraining);
      await pollTrainStatus();
    }
  }

  async function loadModelInfo() {
    try {
      const info = await api("/ai/model-info");
      const fmt = x => typeof x === "number" ? (x * 100).toFixed(1) + "%" : "—";
      $("#m-disease").textContent = fmt(info.disease_accuracy);
      $("#m-disease-cv").textContent = "CV 3-fold: " + fmt(info.disease_cv_accuracy_mean);
      $("#m-risk").textContent = fmt(info.risk_accuracy);
      $("#m-risk-cv").textContent = "CV 3-fold: " + fmt(info.risk_cv_accuracy_mean);
      $("#m-n").textContent = (info.n_samples ?? 0).toLocaleString();
      $("#m-trained").textContent = (info.trained_at || "—").replace("T", " ").slice(0, 16);
      $("#m-feats").textContent = (info.features_used || []).join(", ") || "—";
    } catch (_) {}
  }

  async function startTraining() {
    const btn = $("#m-train"); const sel = $("#m-ds");
    const dsPath = sel.value;
    const dsName = sel.selectedOptions[0]?.textContent || dsPath;
    btn.disabled = true; sel.disabled = true;
    $("#m-bar").classList.remove("hidden");
    $("#m-msg").innerHTML = `<div class="alert alert-info">${t("model.running", { ds: dsName })}</div>`;
    try {
      await api("/ai/train", { method: "POST", body: { dataset: dsPath } });
      pollTrainStatus();
    } catch (e) {
      btn.disabled = false; sel.disabled = false;
      $("#m-bar").classList.add("hidden");
      $("#m-msg").innerHTML = `<div class="alert alert-danger">${escapeHtml(e.message)}</div>`;
    }
  }

  async function pollTrainStatus() {
    if (trainPoll) clearInterval(trainPoll);
    const tick = async () => {
      try {
        const s = await api("/ai/train-status");
        const bar = $("#m-bar");
        const btn = $("#m-train");
        const sel = $("#m-ds");
        if (!s.running) {
          if (bar) bar.classList.add("hidden");
          if (btn) { btn.disabled = false; sel.disabled = false; }
          if (s.last_error) {
            $("#m-msg").innerHTML = `<div class="alert alert-danger"><strong>${t("model.failed")}</strong><pre style="white-space:pre-wrap;margin:8px 0 0;font-size:11px;">${escapeHtml(s.last_error)}</pre></div>`;
          } else if (s.last_result) {
            $("#m-msg").innerHTML = `<div class="alert alert-success">${t("model.success")}</div>`;
            await loadModelInfo();
          }
          clearInterval(trainPoll); trainPoll = null;
          checkApiStatus();
        }
      } catch (_) {}
    };
    await tick();
    trainPoll = setInterval(tick, 2500);
  }

  // ═══════════════════════ USERS ═══════════════════════
  async function renderUsers() {
    CONTENT().innerHTML = PAGE("users.title", "users.sub", `
      <div class="card mb-16">
        <div class="card-header"><h3 class="card-title">${t("users.create")}</h3></div>
        <div class="grid-4" style="gap:10px;">
          <div class="form-field"><label>${t("users.username")}</label><input id="u-user" /></div>
          <div class="form-field"><label>${t("common.name")}</label><input id="u-name" /></div>
          <div class="form-field"><label>${t("users.email")}</label><input id="u-email" type="email" /></div>
          <div class="form-field"><label>${t("users.password")}</label><input id="u-pass" type="password" /></div>
          <div class="form-field"><label>${t("users.role")}</label>
            <select id="u-role"><option value="user">user</option><option value="admin">admin</option></select>
          </div>
        </div>
        <button class="btn btn-primary" id="u-create">${t("users.create")}</button>
        <div id="u-msg" class="mt-12"></div>
      </div>

      <div class="card">
        <div class="card-header"><h3 class="card-title">${t("users.title")}</h3></div>
        <div class="table-wrap">
          <table>
            <thead><tr>
              <th>${t("users.username")}</th><th>${t("common.name")}</th>
              <th>${t("users.email")}</th><th>${t("users.role")}</th>
              <th>${t("common.actions")}</th>
            </tr></thead>
            <tbody id="u-tbody"><tr><td colspan="5" class="empty">${t("common.loading")}</td></tr></tbody>
          </table>
        </div>
      </div>
    `);

    $("#u-create").addEventListener("click", async () => {
      const body = {
        username: $("#u-user").value.trim(),
        name:     $("#u-name").value.trim(),
        email:    $("#u-email").value.trim(),
        password: $("#u-pass").value,
        role:     $("#u-role").value,
      };
      try {
        await api("/users", { method: "POST", body });
        $("#u-msg").innerHTML = `<div class="alert alert-success">${t("users.created.ok")}</div>`;
        $("#u-user").value = ""; $("#u-name").value = ""; $("#u-email").value = ""; $("#u-pass").value = "";
        await loadUsers();
      } catch (e) {
        $("#u-msg").innerHTML = `<div class="alert alert-danger">${escapeHtml(e.message)}</div>`;
      }
    });
    await loadUsers();
  }

  async function loadUsers() {
    try {
      const r = await api("/users");
      const rows = r.users || [];
      $("#u-tbody").innerHTML = rows.length
        ? rows.map(u => `
          <tr>
            <td><strong>${escapeHtml(u.username)}</strong></td>
            <td>${escapeHtml(u.name || "")}</td>
            <td>${escapeHtml(u.email || "")}</td>
            <td><span class="badge badge-${u.role}">${escapeHtml(u.role)}</span></td>
            <td><button class="btn btn-danger btn-sm" data-del="${u.id}">${t("common.delete")}</button></td>
          </tr>`).join("")
        : `<tr><td colspan="5" class="empty">${t("common.empty")}</td></tr>`;
      $$("#u-tbody [data-del]").forEach(b => b.addEventListener("click", async () => {
        if (!confirm(t("users.deleteConfirm"))) return;
        try { await api(`/users/${b.dataset.del}`, { method: "DELETE" }); toast(t("users.deleted.ok"), "success"); await loadUsers(); }
        catch (e) { toast(e.message, "error"); }
      }));
    } catch (e) {
      $("#u-tbody").innerHTML = `<tr><td colspan="5" class="alert alert-danger">${escapeHtml(e.message)}</td></tr>`;
    }
  }

  // ═══════════════════════ REPORT ═══════════════════════
  function renderReport() {
    const token = localStorage.getItem(LS_TOKEN) || "";
    const url = API + "/report/view" + (token ? `?access_token=${encodeURIComponent(token)}` : "");
    CONTENT().innerHTML = PAGE("report.title", "report.sub", `
      <div class="card">
        <p class="text-sm text-muted">${t("report.hint")}</p>
        <div style="display:flex;gap:10px;">
          <a class="btn btn-primary" target="_blank" href="${url}">${t("report.view")}</a>
          <button class="btn btn-secondary" id="r-print">${t("report.print")}</button>
        </div>
        <div class="mt-16" style="border:1px solid var(--c-border);border-radius:var(--radius);overflow:hidden;">
          <iframe src="${url}" style="width:100%;height:640px;border:0;" id="r-frame"></iframe>
        </div>
      </div>
    `);
    $("#r-print").addEventListener("click", () => {
      const f = $("#r-frame");
      try { f.contentWindow.focus(); f.contentWindow.print(); } catch (_) { window.open(url, "_blank"); }
    });
  }

  // ═══════════════════════ BOOT ═══════════════════════
  document.addEventListener("DOMContentLoaded", () => {
    // Apply translations on startup
    const savedLang = window.I18n.lang;
    $("#login-lang").value = savedLang;
    $("#lang-select").value = savedLang;
    window.I18n.applyDOM(document);

    // Language selectors
    $("#login-lang").addEventListener("change", e => {
      window.I18n.setLang(e.target.value);
      $("#lang-select").value = e.target.value;
    });
    $("#lang-select").addEventListener("change", e => {
      window.I18n.setLang(e.target.value);
      $("#login-lang").value = e.target.value;
      // Re-render current section
      const active = $(".nav-item.active")?.dataset.section || "dashboard";
      navigate(active);
      checkApiStatus();
    });

    // Login
    $("#login-form").addEventListener("submit", doLogin);
    $("#logout-btn").addEventListener("click", logout);

    // Emergency button (sidebar)
    const emergencyBtn = $("#emergency-btn");
    if (emergencyBtn) {
      emergencyBtn.addEventListener("click", () => {
        toast(t("sidebar.emergency.toast"), "error");
        navigate("anomalies");
      });
    }

    // Sidebar nav
    $$(".nav-item").forEach(n => n.addEventListener("click", () => navigate(n.dataset.section)));

    // Mobile toggle (optional button if present)
    const sidebarToggle = $("#sidebar-toggle");
    if (sidebarToggle) {
      sidebarToggle.addEventListener("click", () => {
        const sb = $("#sidebar");
        if (window.innerWidth <= 780) sb.classList.toggle("open");
        else sb.classList.toggle("collapsed");
      });
    }

    // ── Topbar dropdowns (settings / account) ───────────────────────────
    initTopbarMenus();

    // ── Appearance toggles (compact + sidebar collapse) ─────────────────
    const compactOpt = $("#opt-compact");
    if (compactOpt) {
      compactOpt.checked = localStorage.getItem("ihss_compact") === "1";
      document.body.classList.toggle("compact-mode", compactOpt.checked);
      compactOpt.addEventListener("change", () => {
        document.body.classList.toggle("compact-mode", compactOpt.checked);
        localStorage.setItem("ihss_compact", compactOpt.checked ? "1" : "0");
      });
    }
    const collapseOpt = $("#opt-sidebar-collapse");
    if (collapseOpt) {
      collapseOpt.checked = localStorage.getItem("ihss_sidebar_collapsed") === "1";
      if (collapseOpt.checked) $("#sidebar").classList.add("collapsed");
      collapseOpt.addEventListener("change", () => {
        $("#sidebar").classList.toggle("collapsed", collapseOpt.checked);
        localStorage.setItem("ihss_sidebar_collapsed", collapseOpt.checked ? "1" : "0");
      });
    }

    // ── Settings menu actions ──────────────────────────────────────────
    const reportBtn = $("#settings-report");
    if (reportBtn) reportBtn.addEventListener("click", () => {
      closeAllMenus();
      navigate("report");
    });
    const refreshBtn = $("#settings-refresh");
    if (refreshBtn) refreshBtn.addEventListener("click", () => {
      closeAllMenus();
      const active = $(".nav-item.active")?.dataset.section || "dashboard";
      navigate(active);
      checkApiStatus();
      toast(t("settings.refresh.ok"), "success");
    });

    // ── Account menu actions ───────────────────────────────────────────
    const profileBtn = $("#account-profile");
    if (profileBtn) profileBtn.addEventListener("click", () => {
      closeAllMenus();
      toast(t("account.profile.soon"), "info");
    });
    const accountSettingsBtn = $("#account-settings");
    if (accountSettingsBtn) accountSettingsBtn.addEventListener("click", () => {
      closeAllMenus();
      openMenu("settings-menu");
    });

    // Auth bootstrap
    if (localStorage.getItem(LS_TOKEN)) {
      api("/health").then(showApp).catch(() => {
        clearAuth();
        $("#login-page").classList.remove("hidden");
      });
    }
  });
})();

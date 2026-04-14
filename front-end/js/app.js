// ─────────────────────────────────────────────────────────────────────────────
// Config
// ─────────────────────────────────────────────────────────────────────────────
const LOGIN_USER = "admin";
const LOGIN_PASS = "1234";
const SESSION_KEY = "hospital_tool_logged";
const API_BASE = "http://127.0.0.1:8000/api";

// ─────────────────────────────────────────────────────────────────────────────
// DOM refs — auth & shell
// ─────────────────────────────────────────────────────────────────────────────
const loginScreen = document.getElementById("login-screen");
const dashboardScreen = document.getElementById("dashboard-screen");
const loginForm = document.getElementById("login-form");
const loginError = document.getElementById("login-error");
const logoutBtn = document.getElementById("logout-btn");

// ─────────────────────────────────────────────────────────────────────────────
// DOM refs — dataset tab
// ─────────────────────────────────────────────────────────────────────────────
const loadPreviewBtn = document.getElementById("load-preview-btn");
const datasetStatus = document.getElementById("dataset-status");
const tableHead = document.querySelector("#dataset-table thead");
const tableBody = document.querySelector("#dataset-table tbody");

// ─────────────────────────────────────────────────────────────────────────────
// DOM refs — analyze tab
// ─────────────────────────────────────────────────────────────────────────────
const analyzeForm = document.getElementById("analyze-form");
const analyzeStatus = document.getElementById("analyze-status");
const analyzeResults = document.getElementById("analyze-results");

// ─────────────────────────────────────────────────────────────────────────────
// DOM refs — disease tab
// ─────────────────────────────────────────────────────────────────────────────
const diseaseForm = document.getElementById("disease-form");
const diseaseStatus = document.getElementById("disease-status");
const diseaseResults = document.getElementById("disease-results");

// ─────────────────────────────────────────────────────────────────────────────
// DOM refs — risk tab
// ─────────────────────────────────────────────────────────────────────────────
const riskForm = document.getElementById("risk-form");
const riskStatus = document.getElementById("risk-status");
const riskResults = document.getElementById("risk-results");

// ─────────────────────────────────────────────────────────────────────────────
// DOM refs — model tab
// ─────────────────────────────────────────────────────────────────────────────
const trainBtn = document.getElementById("train-btn");
const refreshInfoBtn = document.getElementById("refresh-info-btn");
const trainStatus = document.getElementById("train-status");
const trainProgress = document.getElementById("train-progress");
const modelInfoContent = document.getElementById("model-info-content");

// ─────────────────────────────────────────────────────────────────────────────
// Auth
// ─────────────────────────────────────────────────────────────────────────────
function showDashboard() {
  loginScreen.classList.add("hidden");
  dashboardScreen.classList.remove("hidden");
}

function showLogin() {
  dashboardScreen.classList.add("hidden");
  loginScreen.classList.remove("hidden");
}

loginForm.addEventListener("submit", (e) => {
  e.preventDefault();
  const user = loginForm.username.value.trim();
  const pass = loginForm.password.value.trim();
  if (user === LOGIN_USER && pass === LOGIN_PASS) {
    sessionStorage.setItem(SESSION_KEY, "true");
    loginError.textContent = "";
    showDashboard();
  } else {
    loginError.textContent = "Credenciales invalidas. Usa admin / 1234.";
  }
});

logoutBtn.addEventListener("click", () => {
  sessionStorage.removeItem(SESSION_KEY);
  showLogin();
});

if (sessionStorage.getItem(SESSION_KEY) === "true") showDashboard();

// ─────────────────────────────────────────────────────────────────────────────
// Tabs
// ─────────────────────────────────────────────────────────────────────────────
document.querySelectorAll(".tab-btn").forEach((btn) => {
  btn.addEventListener("click", () => {
    const target = btn.dataset.tab;
    document.querySelectorAll(".tab-btn").forEach((b) => b.classList.remove("active"));
    document.querySelectorAll(".tab-content").forEach((c) => c.classList.add("hidden"));
    btn.classList.add("active");
    document.getElementById(`tab-${target}`).classList.remove("hidden");
  });
});

// ─────────────────────────────────────────────────────────────────────────────
// Dataset — helpers
// ─────────────────────────────────────────────────────────────────────────────
function parseCsvLine(line) {
  const values = [];
  let current = "";
  let inQuotes = false;
  for (let i = 0; i < line.length; i++) {
    const ch = line[i];
    if (ch === '"') {
      if (inQuotes && line[i + 1] === '"') { current += '"'; i++; }
      else inQuotes = !inQuotes;
      continue;
    }
    if (ch === "," && !inQuotes) { values.push(current.trim()); current = ""; continue; }
    current += ch;
  }
  values.push(current.trim());
  return values;
}

function renderTable(headers, rows) {
  tableHead.innerHTML = "";
  tableBody.innerHTML = "";
  const headerRow = document.createElement("tr");
  headers.forEach((h) => { const th = document.createElement("th"); th.textContent = h; headerRow.appendChild(th); });
  tableHead.appendChild(headerRow);
  rows.forEach((row) => {
    const tr = document.createElement("tr");
    headers.forEach((_, i) => { const td = document.createElement("td"); td.textContent = row[i] || ""; tr.appendChild(td); });
    tableBody.appendChild(tr);
  });
}

async function loadPreview() {
  datasetStatus.textContent = "Cargando dataset...";
  loadPreviewBtn.disabled = true;
  try {
    const res = await fetch(`${API_BASE}/dataset/preview?rows=12`);
    if (!res.ok) throw new Error("Backend no disponible");
    const payload = await res.json();
    renderTable(payload.headers, payload.rows);
    datasetStatus.textContent = "Preview cargada desde backend.";
  } catch {
    try {
      const paths = ["../healthcare_dataset_100k.csv", "/healthcare_dataset_100k.csv"];
      let csvText = "";
      for (const p of paths) {
        try { const r = await fetch(p); if (r.ok) { csvText = await r.text(); break; } } catch {}
      }
      if (!csvText) throw new Error("No se pudo leer el CSV");
      const lines = csvText.split(/\r?\n/).filter(Boolean).slice(0, 13);
      const headers = parseCsvLine(lines[0] || "");
      const rows = lines.slice(1).map((l) => parseCsvLine(l));
      renderTable(headers, rows);
      datasetStatus.textContent = "Preview cargada en modo estatico.";
    } catch (err) {
      datasetStatus.textContent = `Error: ${err.message}`;
    }
  } finally {
    loadPreviewBtn.disabled = false;
  }
}

loadPreviewBtn.addEventListener("click", loadPreview);

// ─────────────────────────────────────────────────────────────────────────────
// Quick symptom chips (disease tab)
// ─────────────────────────────────────────────────────────────────────────────
document.querySelectorAll("#tab-disease .sym-chip").forEach((chip) => {
  chip.addEventListener("click", () => {
    const input = document.getElementById("d-symptoms");
    const sym = chip.dataset.sym;
    const current = input.value.trim();
    const parts = current ? current.split(",").map((s) => s.trim()).filter(Boolean) : [];
    if (!parts.includes(sym)) parts.push(sym);
    input.value = parts.join(", ");
    chip.classList.toggle("chip-active", true);
  });
});

document.querySelectorAll("#tab-risk .sym-chip").forEach((chip) => {
  chip.addEventListener("click", () => {
    const input = document.getElementById("r-symptoms");
    const sym = chip.dataset.sym;
    const current = input.value.trim();
    const parts = current ? current.split(",").map((s) => s.trim()).filter(Boolean) : [];
    if (!parts.includes(sym)) parts.push(sym);
    input.value = parts.join(", ");
    chip.classList.toggle("chip-active", true);
  });
});

// ─────────────────────────────────────────────────────────────────────────────
// Render helpers — shared
// ─────────────────────────────────────────────────────────────────────────────
const RISK_COLORS = { High: "#c62828", Medium: "#e65100", Low: "#2e7d32" };
const RISK_LABELS = { High: "Alto", Medium: "Medio", Low: "Bajo" };

function renderDiseaseResult(data, nameEl, barEl, confEl, topEl) {
  nameEl.textContent = data.predicted_disease;
  const pct = data.confidence_pct;
  barEl.style.width = `${pct}%`;
  barEl.style.background = pct > 60 ? "#1f4fa3" : pct > 35 ? "#f57c00" : "#78909c";
  confEl.textContent = `Confianza: ${pct}%`;

  topEl.innerHTML = "";
  if (data.top_predictions && data.top_predictions.length > 1) {
    const title = document.createElement("p");
    title.className = "top-list-title";
    title.textContent = "Top predicciones:";
    topEl.appendChild(title);
    data.top_predictions.forEach((item) => {
      const row = document.createElement("div");
      row.className = "top-item";
      const pctVal = item.percentage;
      row.innerHTML = `
        <span class="top-name">${item.disease}</span>
        <div class="top-bar-wrap">
          <div class="top-bar" style="width:${pctVal}%; background:${pctVal > 40 ? '#1f4fa3' : '#90a4ae'}"></div>
        </div>
        <span class="top-pct">${pctVal}%</span>
      `;
      topEl.appendChild(row);
    });
  }
}

function renderRiskResult(data, badgeEl, barEl, confEl, probasEl, recsEl) {
  const level = data.risk_level;
  const color = RISK_COLORS[level] || "#555";
  const label = RISK_LABELS[level] || level;

  badgeEl.textContent = label;
  badgeEl.className = `risk-badge risk-${level.toLowerCase()}`;

  const pct = data.confidence_pct;
  barEl.style.width = `${pct}%`;
  barEl.style.background = color;
  confEl.textContent = `Confianza: ${pct}%`;

  // Risk probability bars
  probasEl.innerHTML = "";
  if (data.risk_probabilities) {
    Object.entries(data.risk_probabilities)
      .sort((a, b) => b[1] - a[1])
      .forEach(([cls, prob]) => {
        const pctVal = Math.round(prob * 100);
        const div = document.createElement("div");
        div.className = "risk-proba-row";
        div.innerHTML = `
          <span class="risk-proba-label">${RISK_LABELS[cls] || cls}</span>
          <div class="top-bar-wrap">
            <div class="top-bar" style="width:${pctVal}%; background:${RISK_COLORS[cls] || '#90a4ae'}"></div>
          </div>
          <span class="top-pct">${pctVal}%</span>
        `;
        probasEl.appendChild(div);
      });
  }

  // Recommendations
  recsEl.innerHTML = "";
  if (data.recommendations && data.recommendations.length) {
    const title = document.createElement("p");
    title.className = "rec-title";
    title.textContent = "Recomendaciones clinicas:";
    recsEl.appendChild(title);
    const ul = document.createElement("ul");
    ul.className = "rec-list";
    data.recommendations.forEach((r) => {
      const li = document.createElement("li");
      li.textContent = r;
      ul.appendChild(li);
    });
    recsEl.appendChild(ul);
  }
}

// ─────────────────────────────────────────────────────────────────────────────
// API wrapper
// ─────────────────────────────────────────────────────────────────────────────
async function apiPost(endpoint, body) {
  const res = await fetch(`${API_BASE}${endpoint}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  const data = await res.json();
  if (!res.ok) throw new Error(data.error || `HTTP ${res.status}`);
  return data;
}

async function apiGet(endpoint) {
  const res = await fetch(`${API_BASE}${endpoint}`);
  const data = await res.json();
  if (!res.ok) throw new Error(data.error || `HTTP ${res.status}`);
  return data;
}

function setLoading(btn, statusEl, loading, msg = "") {
  btn.disabled = loading;
  btn.classList.toggle("loading", loading);
  statusEl.textContent = msg;
}

// ─────────────────────────────────────────────────────────────────────────────
// Analyze form
// ─────────────────────────────────────────────────────────────────────────────
analyzeForm.addEventListener("submit", async (e) => {
  e.preventDefault();
  const age = document.getElementById("an-age").value;
  const gender = document.getElementById("an-gender").value;
  const symptoms = document.getElementById("an-symptoms").value;
  const btn = document.getElementById("analyze-btn");

  if (!age || !gender || !symptoms.trim()) {
    analyzeStatus.textContent = "Completa todos los campos.";
    return;
  }

  setLoading(btn, analyzeStatus, true, "Analizando...");
  analyzeResults.classList.add("hidden");

  try {
    const data = await apiPost("/ai/analyze", { age: parseInt(age), gender, symptoms });

    renderDiseaseResult(
      data.disease,
      document.getElementById("an-disease-name"),
      document.getElementById("an-disease-bar"),
      document.getElementById("an-disease-conf"),
      document.getElementById("an-top-diseases"),
    );
    renderRiskResult(
      data.risk,
      document.getElementById("an-risk-badge"),
      document.getElementById("an-risk-bar"),
      document.getElementById("an-risk-conf"),
      document.getElementById("an-risk-probas"),
      document.getElementById("an-recommendations"),
    );

    analyzeResults.classList.remove("hidden");
    setLoading(btn, analyzeStatus, false, "");
  } catch (err) {
    setLoading(btn, analyzeStatus, false, `Error: ${err.message}`);
  }
});

// ─────────────────────────────────────────────────────────────────────────────
// Disease form
// ─────────────────────────────────────────────────────────────────────────────
diseaseForm.addEventListener("submit", async (e) => {
  e.preventDefault();
  const age = document.getElementById("d-age").value;
  const gender = document.getElementById("d-gender").value;
  const symptoms = document.getElementById("d-symptoms").value;
  const btn = document.getElementById("disease-btn");

  if (!age || !gender || !symptoms.trim()) {
    diseaseStatus.textContent = "Completa todos los campos.";
    return;
  }

  setLoading(btn, diseaseStatus, true, "Prediciendo...");
  diseaseResults.classList.add("hidden");

  try {
    const data = await apiPost("/ai/predict-disease", { age: parseInt(age), gender, symptoms });
    renderDiseaseResult(
      data,
      document.getElementById("d-disease-name"),
      document.getElementById("d-disease-bar"),
      document.getElementById("d-disease-conf"),
      document.getElementById("d-top-diseases"),
    );
    diseaseResults.classList.remove("hidden");
    setLoading(btn, diseaseStatus, false, "");
  } catch (err) {
    setLoading(btn, diseaseStatus, false, `Error: ${err.message}`);
  }
});

// ─────────────────────────────────────────────────────────────────────────────
// Risk form
// ─────────────────────────────────────────────────────────────────────────────
riskForm.addEventListener("submit", async (e) => {
  e.preventDefault();
  const age = document.getElementById("r-age").value;
  const gender = document.getElementById("r-gender").value;
  const symptoms = document.getElementById("r-symptoms").value;
  const btn = document.getElementById("risk-btn");

  if (!age || !gender || !symptoms.trim()) {
    riskStatus.textContent = "Completa todos los campos.";
    return;
  }

  setLoading(btn, riskStatus, true, "Clasificando...");
  riskResults.classList.add("hidden");

  try {
    const data = await apiPost("/ai/classify-risk", { age: parseInt(age), gender, symptoms });
    renderRiskResult(
      data,
      document.getElementById("r-risk-badge"),
      document.getElementById("r-risk-bar"),
      document.getElementById("r-risk-conf"),
      document.getElementById("r-risk-probas"),
      document.getElementById("r-recommendations"),
    );
    riskResults.classList.remove("hidden");
    setLoading(btn, riskStatus, false, "");
  } catch (err) {
    setLoading(btn, riskStatus, false, `Error: ${err.message}`);
  }
});

// ─────────────────────────────────────────────────────────────────────────────
// Model info
// ─────────────────────────────────────────────────────────────────────────────
async function loadModelInfo() {
  modelInfoContent.innerHTML = "<p class='muted-text'>Cargando...</p>";
  try {
    const info = await apiGet("/ai/model-info");

    if (!info.loaded && !info.metrics_available) {
      modelInfoContent.innerHTML = `
        <div class="model-not-loaded">
          <p>&#9888; Modelos no entrenados todavia.</p>
          <p class="muted-text">Haz clic en "Entrenar Modelos" para generar los modelos con PySpark y Sklearn.</p>
        </div>`;
      return;
    }

    const fmtNum = (v) => v != null ? v.toLocaleString() : "N/A";

    const accDisease = info.disease_accuracy != null ? `${(info.disease_accuracy * 100).toFixed(1)}%` : "N/A";
    const accRisk = info.risk_accuracy != null ? `${(info.risk_accuracy * 100).toFixed(1)}%` : "N/A";
    const trainedAt = info.trained_at ? new Date(info.trained_at).toLocaleString("es-ES") : "N/A";

    let diseaseDist = "";
    if (info.disease_distribution) {
      const entries = Object.entries(info.disease_distribution).sort((a, b) => b[1] - a[1]);
      diseaseDist = entries.map(([d, c]) => `
        <div class="dist-row">
          <span class="dist-label">${d}</span>
          <div class="top-bar-wrap">
            <div class="top-bar" style="width:${Math.round(c / info.n_samples * 100)}%; background:#1f4fa3"></div>
          </div>
          <span class="top-pct">${c.toLocaleString()}</span>
        </div>`).join("");
    }

    modelInfoContent.innerHTML = `
      <div class="model-stats">
        <div class="stat-card">
          <div class="stat-value">${accDisease}</div>
          <div class="stat-label">Accuracy Enfermedad</div>
        </div>
        <div class="stat-card">
          <div class="stat-value">${accRisk}</div>
          <div class="stat-label">Accuracy Riesgo</div>
        </div>
        <div class="stat-card">
          <div class="stat-value">${fmtNum(info.n_samples)}</div>
          <div class="stat-label">Registros entrenados</div>
        </div>
        <div class="stat-card">
          <div class="stat-value">${info.disease_classes ? info.disease_classes.length : "N/A"}</div>
          <div class="stat-label">Clases de enfermedad</div>
        </div>
      </div>

      <div class="model-detail">
        <h4>Enfermedades clasificadas</h4>
        <div class="class-tags">
          ${(info.disease_classes || []).map((c) => `<span class="class-tag">${c}</span>`).join("")}
        </div>
      </div>

      <div class="model-detail">
        <h4>Niveles de riesgo</h4>
        <div class="class-tags">
          ${(info.risk_classes || []).map((c) => `<span class="class-tag risk-tag-${c.toLowerCase()}">${RISK_LABELS[c] || c}</span>`).join("")}
        </div>
      </div>

      ${diseaseDist ? `<div class="model-detail"><h4>Distribucion de enfermedades</h4>${diseaseDist}</div>` : ""}

      <p class="muted-text" style="margin-top:16px">Ultimo entrenamiento: ${trainedAt}</p>
    `;
  } catch (err) {
    modelInfoContent.innerHTML = `<p class="error-msg">Error: ${err.message}</p>`;
  }
}

refreshInfoBtn.addEventListener("click", loadModelInfo);

// ─────────────────────────────────────────────────────────────────────────────
// Train
// ─────────────────────────────────────────────────────────────────────────────
let _pollInterval = null;

async function pollTrainStatus() {
  try {
    const status = await apiGet("/ai/train-status");
    if (!status.running) {
      clearInterval(_pollInterval);
      _pollInterval = null;
      trainProgress.classList.add("hidden");
      trainBtn.disabled = false;

      if (status.last_result === "ok") {
        trainStatus.textContent = "Entrenamiento completado exitosamente.";
        trainStatus.style.color = "#2e7d32";
        loadModelInfo();
      } else if (status.last_error) {
        trainStatus.textContent = `Error: ${status.last_error.slice(0, 150)}`;
        trainStatus.style.color = "#c62828";
      }
    }
  } catch {}
}

trainBtn.addEventListener("click", async () => {
  trainBtn.disabled = true;
  trainStatus.textContent = "";
  trainStatus.style.color = "";
  trainProgress.classList.remove("hidden");

  try {
    await apiPost("/ai/train", {});
    trainStatus.textContent = "Entrenamiento iniciado. Puede tardar varios minutos...";
    _pollInterval = setInterval(pollTrainStatus, 5000);
  } catch (err) {
    trainBtn.disabled = false;
    trainProgress.classList.add("hidden");
    trainStatus.textContent = `Error al iniciar: ${err.message}`;
    trainStatus.style.color = "#c62828";
  }
});

// Auto-load model info when switching to model tab
document.querySelectorAll(".tab-btn").forEach((btn) => {
  btn.addEventListener("click", () => {
    if (btn.dataset.tab === "model") loadModelInfo();
  });
});

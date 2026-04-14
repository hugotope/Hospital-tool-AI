"use strict";
// ═══════════════════════════════════════════════════════════════════════════
//  MedAI Hospital — Single-Page Application
// ═══════════════════════════════════════════════════════════════════════════

const API = "http://127.0.0.1:8000/api";
const SESSION_KEY = "medai_session";

// ── State ─────────────────────────────────────────────────────────────────────
let state = { user: null, token: null, section: "dashboard" };

// ── Symptom translation dictionary (ES → EN) ──────────────────────────────────
const SYMPTOM_DICT = {
  "dolor de cabeza": "headache", "cefalea": "headache",
  "dolor de pecho": "chest pain", "dolor pecho": "chest pain",
  "dolor abdominal": "abdominal pain", "dolor de estomago": "abdominal pain", "dolor estomago": "abdominal pain",
  "dolor de espalda": "back pain", "dolor espalda": "back pain",
  "dolor muscular": "muscle pain", "dolores musculares": "muscle pain",
  "dolor articular": "joint pain", "dolor en las articulaciones": "joint pain",
  "dolor de garganta": "sore throat", "garganta irritada": "sore throat",
  "dificultad para respirar": "shortness of breath", "dificultad respiratoria": "shortness of breath",
  "falta de aire": "shortness of breath", "respiracion corta": "shortness of breath",
  "fatiga": "fatigue", "cansancio": "fatigue", "agotamiento": "fatigue",
  "fiebre": "fever", "temperatura alta": "fever", "calentura": "fever",
  "tos": "cough", "tos seca": "dry cough", "tos con flema": "productive cough",
  "mareo": "dizziness", "vertigo": "dizziness",
  "nauseas": "nausea", "náuseas": "nausea", "nausea": "nausea",
  "vomito": "vomiting", "vómito": "vomiting", "vomitos": "vomiting",
  "diarrea": "diarrhea",
  "estreñimiento": "constipation", "estrenimiento": "constipation",
  "ictericia": "jaundice", "piel amarilla": "jaundice", "ojos amarillos": "jaundice",
  "perdida de peso": "weight loss", "pérdida de peso": "weight loss", "adelgazamiento": "weight loss",
  "miccion frecuente": "frequent urination", "micción frecuente": "frequent urination",
  "orinar frecuente": "frequent urination", "ganas de orinar": "frequent urination",
  "sed excesiva": "excessive thirst", "mucha sed": "excessive thirst",
  "hambre excesiva": "excessive hunger", "mucho apetito": "excessive hunger",
  "perdida de apetito": "loss of appetite", "falta de apetito": "loss of appetite",
  "sudoracion": "sweating", "sudoracion nocturna": "night sweats",
  "vision borrosa": "blurred vision", "visión borrosa": "blurred vision",
  "entumecimiento": "numbness", "adormecimiento": "numbness",
  "hormigueo": "tingling",
  "debilidad": "weakness", "debilidad muscular": "muscle weakness",
  "palpitaciones": "palpitations", "latidos rapidos": "palpitations",
  "hinchazon": "swelling", "hinchazón": "swelling", "edema": "swelling",
  "erupcion": "rash", "erupcion cutanea": "rash", "sarpullido": "rash",
  "picazon": "itching", "picazón": "itching", "comezon": "itching",
  "confusion": "confusion", "desorientacion": "confusion",
  "ansiedad": "anxiety", "nerviosismo": "anxiety",
  "depresion": "depression", "tristeza": "depression", "melancolia": "depression",
  "insomnio": "insomnia", "dificultad para dormir": "insomnia",
  "escalofrios": "chills", "escalofríos": "chills",
  "orina oscura": "dark urine", "sangre en orina": "blood in urine",
  "heces oscuras": "dark stools", "heces con sangre": "bloody stools",
  "sangrado": "bleeding", "hemorragia": "hemorrhage",
  "convulsiones": "seizures", "temblores": "tremors",
  "paralisis": "paralysis", "parálisis": "paralysis",
  "perdida de memoria": "memory loss", "pérdida de memoria": "memory loss",
  "caida de cabello": "hair loss", "alopecia": "hair loss",
  "inflamacion": "inflammation", "inflamación": "inflammation",
  "rigidez": "stiffness", "rigidez muscular": "muscle stiffness",
  "presion alta": "high blood pressure", "hipertension": "hypertension",
  "falta de concentracion": "difficulty concentrating",
  "dolor de oido": "ear pain", "dolor oido": "ear pain",
};

function translateSymptoms(text) {
  if (!text.trim()) return "";
  const parts = text.split(",").map(p => p.trim()).filter(Boolean);
  const sorted = Object.entries(SYMPTOM_DICT).sort((a, b) => b[0].length - a[0].length);
  return parts.map(part => {
    const lower = part.toLowerCase();
    for (const [es, en] of sorted) {
      if (lower === es || lower.includes(es)) return en;
    }
    return part; // already English or unknown
  }).join(", ");
}

// ── Disease metadata ───────────────────────────────────────────────────────────
const DISEASE_META = {
  "Heart Disease":  { icon: "❤️",  color: "#dc2626", desc: "Enfermedades del sistema cardiovascular." },
  "Diabetes":       { icon: "💉",  color: "#7c3aed", desc: "Trastorno metabólico del azúcar en sangre." },
  "Cancer":         { icon: "🎗️", color: "#475569", desc: "Crecimiento celular anormal e incontrolado." },
  "Hypertension":   { icon: "🩺",  color: "#db2777", desc: "Presión arterial crónicamente elevada." },
  "Asthma":         { icon: "💨",  color: "#0284c7", desc: "Enfermedad inflamatoria crónica de las vías respiratorias." },
  "COVID-19":       { icon: "🦠",  color: "#059669", desc: "Enfermedad respiratoria por coronavirus SARS-CoV-2." },
  "Depression":     { icon: "🧠",  color: "#6d28d9", desc: "Trastorno del estado de ánimo con tristeza persistente." },
  "Liver Disease":  { icon: "🫀",  color: "#ea580c", desc: "Daño o mal funcionamiento del hígado." },
  "Kidney Disease": { icon: "🫘",  color: "#2563eb", desc: "Daño o mal funcionamiento de los riñones." },
  "Stroke":         { icon: "⚡",  color: "#d97706", desc: "Interrupción del suministro de sangre al cerebro." },
};

const RISK_LABELS = { High: "Alto", Medium: "Medio", Low: "Bajo" };
const RISK_ES = { High: "riesgo-alto", Medium: "riesgo-medio", Low: "riesgo-bajo" };

// ── API wrapper ────────────────────────────────────────────────────────────────
const http = {
  async request(method, path, body = null) {
    const opts = { method, headers: { "Content-Type": "application/json" } };
    if (state.token) opts.headers["Authorization"] = `Bearer ${state.token}`;
    if (body) opts.body = JSON.stringify(body);
    let res;
    try { res = await fetch(`${API}${path}`, opts); }
    catch { throw new Error("No se puede conectar con el servidor. Asegúrate de que el servidor esté corriendo."); }
    const data = await res.json().catch(() => ({}));
    if (res.status === 401) { handleLogout(); throw new Error("Sesión expirada. Por favor inicia sesión de nuevo."); }
    if (!res.ok) throw new Error(data.error || `Error ${res.status}`);
    return data;
  },
  get:    (p)    => http.request("GET",    p),
  post:   (p, b) => http.request("POST",   p, b),
  delete: (p)    => http.request("DELETE", p),
  async upload(path, formData) {
    const opts = { method: "POST", body: formData };
    if (state.token) opts.headers = { "Authorization": `Bearer ${state.token}` };
    let res;
    try { res = await fetch(`${API}${path}`, opts); }
    catch { throw new Error("No se puede conectar con el servidor."); }
    const data = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(data.error || `Error ${res.status}`);
    return data;
  },
};

// ── Toast notifications ────────────────────────────────────────────────────────
function toast(msg, type = "info", duration = 4000) {
  const icons = { success: "✅", error: "❌", warning: "⚠️", info: "ℹ️" };
  const el = document.createElement("div");
  el.className = `toast toast-${type}`;
  el.innerHTML = `<span class="toast-icon">${icons[type]}</span><span class="toast-text">${msg}</span>`;
  document.getElementById("toast-container").appendChild(el);
  setTimeout(() => { el.style.opacity = "0"; el.style.transform = "translateY(10px)"; el.style.transition = ".3s"; setTimeout(() => el.remove(), 300); }, duration);
}

// ── Session persistence ────────────────────────────────────────────────────────
function saveSession() {
  sessionStorage.setItem(SESSION_KEY, JSON.stringify({ user: state.user, token: state.token }));
}
function loadSession() {
  try {
    const s = JSON.parse(sessionStorage.getItem(SESSION_KEY) || "null");
    if (s?.token) { state.user = s.user; state.token = s.token; return true; }
  } catch {}
  return false;
}
function clearSession() {
  sessionStorage.removeItem(SESSION_KEY);
  state.user = null;
  state.token = null;
}

// ═══════════════════════════════════════════════════════════════════════════
//  AUTH
// ═══════════════════════════════════════════════════════════════════════════

async function handleLogin(e) {
  e.preventDefault();
  const btn = document.getElementById("login-btn");
  const errEl = document.getElementById("login-error");
  const username = document.getElementById("login-username").value.trim();
  const password = document.getElementById("login-password").value;
  errEl.textContent = "";
  btn.disabled = true;
  btn.textContent = "Ingresando...";
  try {
    const data = await http.post("/auth/login", { username, password });
    state.token = data.token;
    state.user  = data.user;
    saveSession();
    showPanel();
    navigateTo("dashboard");
  } catch (err) {
    errEl.textContent = err.message;
  } finally {
    btn.disabled = false;
    btn.textContent = "Ingresar al Sistema";
  }
}

function handleLogout() {
  if (state.token) http.post("/auth/logout").catch(() => {});
  clearSession();
  showLogin();
}

// ═══════════════════════════════════════════════════════════════════════════
//  PANEL DISPLAY
// ═══════════════════════════════════════════════════════════════════════════

function showLogin() {
  document.getElementById("login-page").classList.remove("hidden");
  document.getElementById("admin-panel").classList.add("hidden");
}

function showPanel() {
  document.getElementById("login-page").classList.add("hidden");
  document.getElementById("admin-panel").classList.remove("hidden");
  // Update sidebar user info
  const u = state.user;
  document.getElementById("sidebar-username").textContent = u.name || u.username;
  document.getElementById("sidebar-role").textContent = u.role === "admin" ? "Administrador" : "Usuario";
  document.getElementById("sidebar-avatar").textContent = (u.name || u.username)[0].toUpperCase();
  // Hide admin-only items for non-admins
  document.querySelectorAll(".admin-only").forEach(el => {
    el.style.display = u.role === "admin" ? "" : "none";
  });
  // Update model status
  updateModelStatus();
}

async function updateModelStatus() {
  try {
    const info = await http.get("/ai/model-info");
    const dot  = document.getElementById("model-status-badge").querySelector(".status-dot");
    const txt  = document.getElementById("model-status-text");
    if (info.loaded) {
      dot.className = "status-dot dot-success";
      txt.textContent = `Modelo: ${(info.disease_accuracy * 100).toFixed(1)}% acc.`;
    } else {
      dot.className = "status-dot dot-warning";
      txt.textContent = "Modelo: no entrenado";
    }
  } catch { /* server not running */ }
}

// ═══════════════════════════════════════════════════════════════════════════
//  NAVIGATION
// ═══════════════════════════════════════════════════════════════════════════

const SECTION_TITLES = {
  dashboard: "Dashboard",
  diagnosis: "Diagnóstico IA",
  diseases:  "Enfermedades",
  datasets:  "Gestión de Datasets",
  users:     "Gestión de Usuarios",
  model:     "Modelo IA",
};

function navigateTo(section) {
  state.section = section;
  // Nav items
  document.querySelectorAll(".nav-item").forEach(el => {
    el.classList.toggle("active", el.dataset.section === section);
  });
  // Breadcrumb
  document.getElementById("breadcrumb").innerHTML =
    `<span>${SECTION_TITLES[section] || section}</span>`;
  // Render
  const content = document.getElementById("main-content");
  content.innerHTML = "";
  const loaders = {
    dashboard: renderDashboard,
    diagnosis: renderDiagnosis,
    diseases:  renderDiseases,
    datasets:  renderDatasets,
    users:     renderUsers,
    model:     renderModel,
  };
  if (loaders[section]) loaders[section](content);
}

// ═══════════════════════════════════════════════════════════════════════════
//  SECTION: DASHBOARD
// ═══════════════════════════════════════════════════════════════════════════

async function renderDashboard(el) {
  el.innerHTML = `
    <div class="page-header">
      <h2>Bienvenido, ${state.user.name || state.user.username}</h2>
      <p>Panel de control del sistema hospitalario</p>
    </div>
    <div class="stats-grid" id="dash-stats">
      <div class="stat-card"><div class="stat-value" id="ds-records">—</div><div class="stat-label">Registros en Dataset</div></div>
      <div class="stat-card" id="ds-acc-card"><div class="stat-value" id="ds-acc">—</div><div class="stat-label">Accuracy del Modelo</div></div>
      <div class="stat-card"><div class="stat-value" id="ds-diseases">—</div><div class="stat-label">Enfermedades Clasificadas</div></div>
      <div class="stat-card"><div class="stat-value" id="ds-users">—</div><div class="stat-label">Usuarios del Sistema</div></div>
    </div>
    <div class="card mb-16">
      <div class="card-header"><h3 class="card-title">Acceso Rápido</h3></div>
      <div class="dashboard-quick-links">
        <div class="quick-link-card" data-goto="diagnosis">
          <div class="ql-icon">🔬</div>
          <div><div class="ql-title">Diagnóstico IA</div><div class="ql-sub">Analiza síntomas de un paciente</div></div>
        </div>
        <div class="quick-link-card" data-goto="diseases">
          <div class="ql-icon">🦠</div>
          <div><div class="ql-title">Enfermedades</div><div class="ql-sub">Consulta información clínica</div></div>
        </div>
        <div class="quick-link-card" data-goto="datasets">
          <div class="ql-icon">📂</div>
          <div><div class="ql-title">Datasets</div><div class="ql-sub">Sube y gestiona datos</div></div>
        </div>
        <div class="quick-link-card" data-goto="model">
          <div class="ql-icon">⚙️</div>
          <div><div class="ql-title">Modelo IA</div><div class="ql-sub">Entrena y monitorea</div></div>
        </div>
      </div>
    </div>`;

  el.querySelectorAll(".quick-link-card").forEach(c =>
    c.addEventListener("click", () => navigateTo(c.dataset.goto)));

  // Load stats async
  try {
    const [stats, modelInfo, users] = await Promise.all([
      http.get("/dataset/stats"),
      http.get("/ai/model-info"),
      state.user.role === "admin" ? http.get("/users") : Promise.resolve({ users: [] }),
    ]);
    document.getElementById("ds-records").textContent = stats.total?.toLocaleString() ?? "—";
    if (modelInfo.loaded) {
      document.getElementById("ds-acc").textContent = `${(modelInfo.disease_accuracy * 100).toFixed(1)}%`;
      document.getElementById("ds-acc-card").classList.add("stat-success");
      document.getElementById("ds-diseases").textContent = modelInfo.disease_classes?.length ?? "—";
    } else {
      document.getElementById("ds-acc").textContent = "Sin entrenar";
      document.getElementById("ds-acc-card").classList.add("stat-warning");
      document.getElementById("ds-diseases").textContent = "10";
    }
    if (state.user.role === "admin") {
      document.getElementById("ds-users").textContent = users.users?.length ?? "—";
    } else {
      document.getElementById("ds-users").textContent = "—";
    }
  } catch (err) {
    toast("No se pudieron cargar las estadísticas del dashboard.", "warning");
  }
}

// ═══════════════════════════════════════════════════════════════════════════
//  SECTION: DIAGNOSIS
// ═══════════════════════════════════════════════════════════════════════════

function renderDiagnosis(el) {
  el.innerHTML = `
    <div class="page-header">
      <h2>Diagnóstico con Inteligencia Artificial</h2>
      <p>Escribe los síntomas en español o inglés. El sistema traduce y analiza automáticamente.</p>
    </div>
    <div class="diagnosis-layout">
      <div class="diagnosis-form-col">
        <div class="card">
          <div class="card-header"><h3 class="card-title">🧑‍⚕️ Datos del Paciente</h3></div>

          <div class="patient-row">
            <div class="form-field">
              <label for="d-age">Edad</label>
              <input id="d-age" type="number" min="0" max="120" placeholder="45" value="45" />
            </div>
            <div class="form-field">
              <label for="d-gender">Género</label>
              <select id="d-gender">
                <option value="Male">Masculino</option>
                <option value="Female">Femenino</option>
                <option value="Other">Otro</option>
              </select>
            </div>
          </div>

          <div class="form-field mt-8">
            <label for="d-symptoms">Síntomas <span style="font-weight:400;color:var(--text-muted)">(en español o inglés, separados por coma)</span></label>
            <textarea id="d-symptoms" placeholder="Ej: dolor de cabeza, cansancio, fiebre&#10;o bien: headache, fatigue, fever" rows="3"></textarea>
          </div>

          <div class="translation-box mt-8" id="d-translation-box">
            <span class="tr-label">🔄 Para IA:</span>
            <span class="tr-text" id="d-translation-text">Escribe los síntomas arriba...</span>
          </div>

          <div class="quick-chips-label">Síntomas frecuentes:</div>
          <div id="d-chips">
            ${["Dolor de cabeza","Dolor de pecho","Fatiga","Fiebre","Tos","Mareo",
               "Náuseas","Dificultad para respirar","Ictericia","Micción frecuente",
               "Pérdida de peso","Diarrea"].map(s =>
              `<span class="sym-chip" data-sym="${s}">${s}</span>`).join("")}
          </div>

          <button class="diagnose-btn mt-16" id="diagnose-btn">
            <span>🔬</span> Diagnosticar Paciente
          </button>
          <p class="text-muted mt-8 text-xs" id="diag-status"></p>
        </div>
      </div>

      <div class="diagnosis-result-col" id="diag-result-col">
        <div class="card" style="text-align:center;padding:40px 20px;color:var(--text-muted)">
          <div style="font-size:48px;margin-bottom:12px">🔬</div>
          <p style="font-size:15px;font-weight:600">Esperando diagnóstico</p>
          <p style="font-size:13px;margin-top:6px">Completa los datos del paciente y<br>haz clic en "Diagnosticar"</p>
        </div>
      </div>
    </div>`;

  const sympInput    = document.getElementById("d-symptoms");
  const translEl    = document.getElementById("d-translation-text");
  const diagnoseBtn = document.getElementById("diagnose-btn");
  const diagStatus  = document.getElementById("diag-status");
  const resultCol   = document.getElementById("diag-result-col");

  // Live translation
  sympInput.addEventListener("input", () => {
    const t = translateSymptoms(sympInput.value);
    translEl.textContent = t || "Escribe los síntomas arriba...";
  });

  // Chip clicks
  document.querySelectorAll("#d-chips .sym-chip").forEach(chip => {
    chip.addEventListener("click", () => {
      const sym = chip.dataset.sym;
      const current = sympInput.value.trim();
      const parts = current ? current.split(",").map(s => s.trim()).filter(Boolean) : [];
      if (!parts.map(p => p.toLowerCase()).includes(sym.toLowerCase())) parts.push(sym);
      sympInput.value = parts.join(", ");
      sympInput.dispatchEvent(new Event("input"));
      chip.classList.add("active");
    });
  });

  // Submit
  diagnoseBtn.addEventListener("click", async () => {
    const age     = parseInt(document.getElementById("d-age").value);
    const gender  = document.getElementById("d-gender").value;
    const rawSymp = sympInput.value.trim();

    if (!rawSymp) { toast("Ingresa al menos un síntoma.", "warning"); return; }
    if (isNaN(age) || age < 0 || age > 120) { toast("Ingresa una edad válida (0–120).", "warning"); return; }

    diagnoseBtn.disabled = true;
    diagnoseBtn.classList.add("loading");
    diagStatus.textContent = "Analizando con IA...";
    resultCol.innerHTML = `<div class="card" style="text-align:center;padding:40px"><div class="spinner" style="margin:0 auto"></div><p style="margin-top:14px;color:var(--text-muted)">Procesando diagnóstico...</p></div>`;

    try {
      const data = await http.post("/ai/analyze", { age, gender, symptoms: rawSymp });
      renderDiagnosisResults(resultCol, data);
      diagStatus.textContent = "";
    } catch (err) {
      diagStatus.textContent = `Error: ${err.message}`;
      resultCol.innerHTML = `<div class="alert alert-danger"><span>❌</span><div><strong>Error al diagnosticar</strong><br>${err.message}</div></div>`;
    } finally {
      diagnoseBtn.disabled = false;
      diagnoseBtn.classList.remove("loading");
    }
  });
}

function renderDiagnosisResults(col, data) {
  const { disease, risk, symptoms_translated } = data;
  const riskClass = `risk-${risk.risk_level.toLowerCase()}`;
  const riskLabel = RISK_LABELS[risk.risk_level] || risk.risk_level;
  const riskColor = { High: "var(--risk-high)", Medium: "var(--risk-med)", Low: "var(--risk-low)" }[risk.risk_level];

  const topHTML = (disease.top_predictions || []).map(p => `
    <div class="prob-row">
      <span class="prob-name">${p.disease}</span>
      <div class="prob-track"><div class="prob-fill" style="width:${p.percentage}%"></div></div>
      <span class="prob-pct">${p.percentage}%</span>
    </div>`).join("");

  const recHTML = (risk.recommendations || []).map(r => `<li>${r}</li>`).join("");

  const riskProbasHTML = Object.entries(risk.risk_probabilities || {})
    .sort((a, b) => b[1] - a[1])
    .map(([k, v]) => {
      const pct = Math.round(v * 100);
      const col = { High: "var(--risk-high)", Medium: "var(--risk-med)", Low: "var(--risk-low)" }[k] || "#888";
      return `<div class="prob-row">
        <span class="prob-name" style="width:60px">${RISK_LABELS[k] || k}</span>
        <div class="prob-track"><div class="prob-fill" style="width:${pct}%;background:${col}"></div></div>
        <span class="prob-pct">${pct}%</span>
      </div>`;
    }).join("");

  col.innerHTML = `
    <div style="display:flex;flex-direction:column;gap:14px">
      ${symptoms_translated ? `<p class="symptoms-translated-tag">✅ Síntomas interpretados: <span>${symptoms_translated}</span></p>` : ""}

      <div class="result-disease-card">
        <div class="result-label">Diagnóstico Predicho</div>
        <div class="result-disease-name">${disease.predicted_disease}</div>
        <div class="result-conf-row">
          <span class="conf-pct">${disease.confidence_pct}%</span>
          <span class="conf-label">de confianza</span>
        </div>
        <div class="bar-track"><div class="bar-fill" style="width:${disease.confidence_pct}%"></div></div>
        ${topHTML ? `<div class="prob-list mt-12">${topHTML}</div>` : ""}
      </div>

      <div class="result-risk-card ${riskClass}">
        <div class="result-label">Nivel de Riesgo</div>
        <div class="risk-level-text">${riskLabel}</div>
        <div style="font-size:12px;color:var(--text-muted);margin-bottom:10px">${risk.confidence_pct}% de confianza</div>
        ${riskProbasHTML ? `<div class="prob-list">${riskProbasHTML}</div>` : ""}
        ${recHTML ? `<hr class="divider"><strong style="font-size:13px">Recomendaciones:</strong><ul class="rec-list mt-8">${recHTML}</ul>` : ""}
      </div>
    </div>`;
}

// ═══════════════════════════════════════════════════════════════════════════
//  SECTION: DISEASES
// ═══════════════════════════════════════════════════════════════════════════

async function renderDiseases(el) {
  el.innerHTML = `
    <div class="page-header">
      <h2>Base de Datos de Enfermedades</h2>
      <p>Estadísticas y síntomas comunes extraídos del dataset hospitalario.</p>
    </div>
    <div id="diseases-container"><div class="spinner" style="margin:40px auto;display:block"></div></div>`;

  try {
    const diseases = await http.get("/diseases");
    const total = diseases.reduce((s, d) => s + d.count, 0);
    const cardsHTML = diseases.map(d => {
      const meta = DISEASE_META[d.name] || { icon: "🏥", color: "#64748b", desc: "" };
      const pct  = total ? Math.round(d.count / total * 100) : 0;
      const syms = (d.common_symptoms || []).slice(0, 5).map(s =>
        `<span class="disease-symptom-tag">${s}</span>`).join("");
      return `
        <div class="disease-card">
          <div class="disease-card-accent" style="background:${meta.color}"></div>
          <div class="disease-card-header">
            <span class="disease-icon">${meta.icon}</span>
            <div class="disease-name">${d.name}</div>
            <div class="disease-cases">${d.count.toLocaleString()} casos · ${pct}% del dataset</div>
          </div>
          <div class="disease-card-body">
            <div class="disease-avg-age">Edad media: <strong>${d.avg_age} años</strong></div>
            <div class="bar-track mb-16" style="margin-bottom:10px">
              <div class="bar-fill" style="width:${pct}%;background:${meta.color}"></div>
            </div>
            <div class="disease-symptoms">${syms}</div>
            ${meta.desc ? `<p style="font-size:12px;color:var(--text-muted);margin-top:10px">${meta.desc}</p>` : ""}
          </div>
        </div>`;
    }).join("");

    document.getElementById("diseases-container").innerHTML = `<div class="diseases-grid">${cardsHTML}</div>`;
  } catch (err) {
    document.getElementById("diseases-container").innerHTML =
      `<div class="alert alert-danger"><span>❌</span><div>${err.message}</div></div>`;
  }
}

// ═══════════════════════════════════════════════════════════════════════════
//  SECTION: DATASETS
// ═══════════════════════════════════════════════════════════════════════════

async function renderDatasets(el) {
  el.innerHTML = `
    <div class="page-header">
      <h2>Gestión de Datasets</h2>
      <p>Sube nuevos datasets CSV y consulta los existentes.</p>
    </div>
    <div class="grid-2" style="align-items:start">
      <div style="display:flex;flex-direction:column;gap:16px">
        <div class="card">
          <div class="card-header"><h3 class="card-title">📤 Subir Dataset</h3></div>
          <div class="upload-zone" id="upload-zone">
            <span class="upload-zone-icon">📁</span>
            <p><strong>Haz clic o arrastra un archivo CSV</strong></p>
            <p>Columnas requeridas: Age, Gender, Symptoms, Diagnosis</p>
            <p class="upload-hint">Máximo recomendado: 200 MB</p>
            <input type="file" id="file-input" accept=".csv" style="display:none" />
          </div>
          <div id="upload-status" class="mt-12"></div>
          <button class="btn-primary mt-12" id="upload-btn" disabled>Subir Dataset</button>
        </div>

        <div class="card">
          <div class="card-header">
            <h3 class="card-title">🗂️ Datasets Disponibles</h3>
            <button class="btn-ghost" id="refresh-datasets-btn">↺ Actualizar</button>
          </div>
          <div id="datasets-list"><div class="spinner" style="margin:20px auto;display:block"></div></div>
        </div>
      </div>

      <div class="card">
        <div class="card-header">
          <h3 class="card-title">👁 Preview del Dataset Principal</h3>
          <button class="btn-secondary" id="load-preview-btn">Cargar Preview</button>
        </div>
        <div id="preview-area" class="text-muted text-sm mt-8">Haz clic en "Cargar Preview".</div>
      </div>
    </div>`;

  // Upload zone
  const zone      = document.getElementById("upload-zone");
  const fileInput = document.getElementById("file-input");
  const uploadBtn = document.getElementById("upload-btn");
  let selectedFile = null;

  zone.addEventListener("click", () => fileInput.click());
  zone.addEventListener("dragover", e => { e.preventDefault(); zone.classList.add("drag-over"); });
  zone.addEventListener("dragleave", () => zone.classList.remove("drag-over"));
  zone.addEventListener("drop", e => {
    e.preventDefault();
    zone.classList.remove("drag-over");
    const f = e.dataTransfer.files[0];
    if (f) selectFile(f);
  });
  fileInput.addEventListener("change", () => { if (fileInput.files[0]) selectFile(fileInput.files[0]); });

  function selectFile(f) {
    if (!f.name.endsWith(".csv")) { toast("Solo se permiten archivos CSV.", "error"); return; }
    selectedFile = f;
    document.getElementById("upload-status").innerHTML =
      `<div class="alert alert-info"><span>📄</span><span>Archivo seleccionado: <strong>${f.name}</strong> (${(f.size/1024).toFixed(1)} KB)</span></div>`;
    uploadBtn.disabled = false;
  }

  uploadBtn.addEventListener("click", async () => {
    if (!selectedFile) return;
    uploadBtn.disabled = true;
    uploadBtn.textContent = "Subiendo...";
    const fd = new FormData();
    fd.append("file", selectedFile);
    try {
      const res = await http.upload("/dataset/upload", fd);
      toast(`✅ ${res.message} (${res.rows?.toLocaleString()} filas)`, "success");
      document.getElementById("upload-status").innerHTML =
        `<div class="alert alert-success"><span>✅</span><span>${res.message} — <strong>${res.rows?.toLocaleString()}</strong> filas</span></div>`;
      selectedFile = null;
      loadDatasetsList();
    } catch (err) {
      toast(`Error al subir: ${err.message}`, "error");
      document.getElementById("upload-status").innerHTML =
        `<div class="alert alert-danger"><span>❌</span><span>${err.message}</span></div>`;
    } finally {
      uploadBtn.textContent = "Subir Dataset";
      uploadBtn.disabled = !selectedFile;
    }
  });

  document.getElementById("refresh-datasets-btn").addEventListener("click", loadDatasetsList);
  document.getElementById("load-preview-btn").addEventListener("click", loadPreview);
  loadDatasetsList();

  async function loadDatasetsList() {
    const container = document.getElementById("datasets-list");
    container.innerHTML = `<div class="spinner" style="margin:16px auto;display:block"></div>`;
    try {
      const { datasets } = await http.get("/dataset/list");
      if (!datasets.length) { container.innerHTML = `<p class="text-muted">No hay datasets.</p>`; return; }
      container.innerHTML = `<div class="dataset-list">${datasets.map(d => `
        <div class="dataset-item">
          <span class="dataset-item-icon">📊</span>
          <div class="dataset-item-info">
            <div class="dataset-item-name">${d.name}</div>
            <div class="dataset-item-meta">${d.size_kb.toLocaleString()} KB</div>
          </div>
          <span class="dataset-type-badge dataset-type-${d.type}">${d.type === "main" ? "Principal" : "Subido"}</span>
        </div>`).join("")}</div>`;
    } catch (err) {
      container.innerHTML = `<p class="text-muted">${err.message}</p>`;
    }
  }

  async function loadPreview() {
    const area = document.getElementById("preview-area");
    area.innerHTML = `<div class="spinner" style="margin:20px auto;display:block"></div>`;
    try {
      const { headers, rows } = await http.get("/dataset/preview?rows=15");
      const ths = headers.map(h => `<th>${h}</th>`).join("");
      const trs = rows.map(r =>
        `<tr>${r.map(c => `<td>${c}</td>`).join("")}</tr>`).join("");
      area.innerHTML = `<div class="preview-wrap"><table><thead><tr>${ths}</tr></thead><tbody>${trs}</tbody></table></div>`;
    } catch (err) {
      area.innerHTML = `<div class="alert alert-danger"><span>❌</span><span>${err.message}</span></div>`;
    }
  }
}

// ═══════════════════════════════════════════════════════════════════════════
//  SECTION: USERS
// ═══════════════════════════════════════════════════════════════════════════

async function renderUsers(el) {
  if (state.user.role !== "admin") {
    el.innerHTML = `<div class="alert alert-danger mt-20"><span>🔒</span><span>Acceso restringido a administradores.</span></div>`;
    return;
  }
  el.innerHTML = `
    <div class="page-header">
      <h2>Gestión de Usuarios</h2>
      <p>Crea, consulta y elimina usuarios del sistema.</p>
    </div>
    <div class="users-layout">
      <div class="card">
        <div class="card-header"><h3 class="card-title">➕ Nuevo Usuario</h3></div>
        <form id="create-user-form" style="display:flex;flex-direction:column;gap:12px">
          <div class="form-field"><label>Nombre de usuario *</label><input id="nu-username" placeholder="jdoe" required /></div>
          <div class="form-field"><label>Nombre completo *</label><input id="nu-name" placeholder="Juan Doe" required /></div>
          <div class="form-field"><label>Email</label><input id="nu-email" type="email" placeholder="juan@hospital.com" /></div>
          <div class="form-field"><label>Contraseña *</label><input id="nu-password" type="password" placeholder="••••••" required /></div>
          <div class="form-field">
            <label>Rol</label>
            <select id="nu-role">
              <option value="user">Usuario</option>
              <option value="admin">Administrador</option>
            </select>
          </div>
          <button type="submit" class="btn-primary" id="create-user-btn">Crear Usuario</button>
          <p id="create-user-error" class="form-error"></p>
        </form>
      </div>

      <div class="card">
        <div class="card-header">
          <h3 class="card-title">👥 Usuarios del Sistema</h3>
          <button class="btn-ghost" id="refresh-users-btn">↺ Actualizar</button>
        </div>
        <div id="users-table-wrap"><div class="spinner" style="margin:30px auto;display:block"></div></div>
      </div>
    </div>`;

  document.getElementById("refresh-users-btn").addEventListener("click", loadUsers);
  document.getElementById("create-user-form").addEventListener("submit", async e => {
    e.preventDefault();
    const errEl = document.getElementById("create-user-error");
    const btn   = document.getElementById("create-user-btn");
    errEl.textContent = "";
    btn.disabled = true;
    btn.textContent = "Creando...";
    try {
      await http.post("/users", {
        username: document.getElementById("nu-username").value.trim(),
        name:     document.getElementById("nu-name").value.trim(),
        email:    document.getElementById("nu-email").value.trim(),
        password: document.getElementById("nu-password").value,
        role:     document.getElementById("nu-role").value,
      });
      toast("Usuario creado exitosamente.", "success");
      document.getElementById("create-user-form").reset();
      loadUsers();
    } catch (err) {
      errEl.textContent = err.message;
    } finally {
      btn.disabled = false;
      btn.textContent = "Crear Usuario";
    }
  });

  loadUsers();

  async function loadUsers() {
    const wrap = document.getElementById("users-table-wrap");
    wrap.innerHTML = `<div class="spinner" style="margin:30px auto;display:block"></div>`;
    try {
      const { users } = await http.get("/users");
      if (!users.length) { wrap.innerHTML = `<p class="text-muted">No hay usuarios.</p>`; return; }
      const rows = users.map(u => `
        <tr>
          <td>${u.id}</td>
          <td><strong>${u.username}</strong></td>
          <td>${u.name}</td>
          <td>${u.email || "—"}</td>
          <td><span class="badge badge-${u.role}">${u.role === "admin" ? "Admin" : "Usuario"}</span></td>
          <td><span class="badge badge-${u.is_active ? "active" : "danger"}">${u.is_active ? "Activo" : "Inactivo"}</span></td>
          <td style="font-size:12px;color:var(--text-muted)">${u.created_at?.split("T")[0] || u.created_at || "—"}</td>
          <td>${u.username !== "admin" && u.is_active ? `<button class="btn-danger" data-uid="${u.id}">Eliminar</button>` : "—"}</td>
        </tr>`).join("");
      wrap.innerHTML = `
        <div class="table-wrap">
          <table>
            <thead><tr><th>ID</th><th>Usuario</th><th>Nombre</th><th>Email</th><th>Rol</th><th>Estado</th><th>Creado</th><th>Acciones</th></tr></thead>
            <tbody>${rows}</tbody>
          </table>
        </div>`;
      wrap.querySelectorAll(".btn-danger[data-uid]").forEach(btn => {
        btn.addEventListener("click", async () => {
          if (!confirm(`¿Eliminar al usuario ID ${btn.dataset.uid}?`)) return;
          try {
            await http.delete(`/users/${btn.dataset.uid}`);
            toast("Usuario eliminado.", "success");
            loadUsers();
          } catch (err) { toast(err.message, "error"); }
        });
      });
    } catch (err) {
      wrap.innerHTML = `<div class="alert alert-danger"><span>❌</span><span>${err.message}</span></div>`;
    }
  }
}

// ═══════════════════════════════════════════════════════════════════════════
//  SECTION: MODEL
// ═══════════════════════════════════════════════════════════════════════════

let _pollInterval = null;

async function renderModel(el) {
  el.innerHTML = `
    <div class="page-header">
      <h2>Modelo de Inteligencia Artificial</h2>
      <p>Estado del modelo entrenado con PySpark + Scikit-learn sobre el dataset hospitalario.</p>
    </div>
    <div style="display:flex;gap:12px;flex-wrap:wrap;margin-bottom:20px;align-items:center">
      ${state.user.role === "admin" ? `<button class="btn-primary btn-lg" id="train-btn">▶ Entrenar Modelos (PySpark)</button>` : ""}
      <button class="btn-secondary" id="refresh-model-btn">↺ Actualizar</button>
      <span id="train-msg" style="font-size:13px;color:var(--text-muted)"></span>
    </div>
    <div id="train-progress-block" class="card hidden" style="margin-bottom:16px">
      <p style="font-weight:600;margin-bottom:8px">⏳ Entrenando modelos — puede tardar varios minutos...</p>
      <div class="train-progress-bar"><div class="train-progress-fill"></div></div>
      <p class="text-muted text-sm mt-8">PySpark carga 100k registros → pipeline de features → RandomForest → serializa modelos</p>
    </div>
    <div id="model-info-area"><div class="spinner" style="margin:40px auto;display:block"></div></div>`;

  document.getElementById("refresh-model-btn").addEventListener("click", loadModelInfo);
  if (state.user.role === "admin") {
    document.getElementById("train-btn").addEventListener("click", startTraining);
  }
  loadModelInfo();
  checkTrainingStatus();

  async function loadModelInfo() {
    const area = document.getElementById("model-info-area");
    try {
      const info = await http.get("/ai/model-info");
      if (!info.loaded && !info.metrics_available) {
        area.innerHTML = `
          <div class="alert alert-warning">
            <span>⚠️</span>
            <div><strong>Modelos no entrenados.</strong><br>
            Haz clic en "Entrenar Modelos" para generar los modelos con PySpark y Sklearn.<br>
            Asegúrate de tener Java y PySpark instalados.</div>
          </div>`;
        return;
      }
      const accD = info.disease_accuracy != null ? `${(info.disease_accuracy * 100).toFixed(1)}%` : "—";
      const accR = info.risk_accuracy     != null ? `${(info.risk_accuracy     * 100).toFixed(1)}%` : "—";
      const n    = info.n_samples?.toLocaleString() ?? "—";
      const date = info.trained_at ? new Date(info.trained_at).toLocaleString("es-ES") : "—";
      const classes = (info.disease_classes || []).map(c => `<span class="tag">${c}</span>`).join("");
      const riskCls = (info.risk_classes || []).map(c => {
        const col = { High:"#dc2626", Medium:"#d97706", Low:"#16a34a" }[c] || "#888";
        return `<span class="tag" style="background:rgba(0,0,0,.05);color:${col};border-color:${col}40">${RISK_LABELS[c] || c}</span>`;
      }).join("");

      let distHTML = "";
      if (info.disease_distribution) {
        const total = Object.values(info.disease_distribution).reduce((a,b)=>a+b,0);
        distHTML = Object.entries(info.disease_distribution)
          .sort((a,b)=>b[1]-a[1])
          .map(([d,c]) => {
            const pct = Math.round(c/total*100);
            const meta = DISEASE_META[d] || {};
            return `<div class="prob-row">
              <span class="prob-name" style="width:150px">${meta.icon || "🏥"} ${d}</span>
              <div class="prob-track"><div class="prob-fill" style="width:${pct}%;background:${meta.color||"var(--primary)"}"></div></div>
              <span class="prob-pct">${c.toLocaleString()}</span>
            </div>`;
          }).join("");
      }

      area.innerHTML = `
        <div class="model-metrics-grid">
          <div class="metric-card"><div class="metric-value">${accD}</div><div class="metric-label">Accuracy Enfermedades</div></div>
          <div class="metric-card"><div class="metric-value">${accR}</div><div class="metric-label">Accuracy Riesgo</div></div>
          <div class="metric-card"><div class="metric-value">${n}</div><div class="metric-label">Registros Entrenados</div></div>
          <div class="metric-card"><div class="metric-value">${info.disease_classes?.length ?? "—"}</div><div class="metric-label">Clases Enfermedad</div></div>
        </div>
        <div class="grid-2" style="align-items:start;gap:16px">
          <div class="card">
            <h4 class="card-title mb-16">Enfermedades Clasificadas</h4>
            <div style="display:flex;flex-wrap:wrap;gap:6px">${classes}</div>
            <h4 class="card-title mt-16 mb-16">Niveles de Riesgo</h4>
            <div style="display:flex;flex-wrap:wrap;gap:6px">${riskCls}</div>
            <p class="text-muted text-xs mt-16">Último entrenamiento: ${date}</p>
          </div>
          ${distHTML ? `<div class="card"><h4 class="card-title mb-16">Distribución del Dataset</h4><div class="prob-list">${distHTML}</div></div>` : ""}
        </div>`;
    } catch (err) {
      area.innerHTML = `<div class="alert alert-danger"><span>❌</span><span>${err.message}</span></div>`;
    }
  }

  async function startTraining() {
    const btn = document.getElementById("train-btn");
    const msg = document.getElementById("train-msg");
    const pb  = document.getElementById("train-progress-block");
    btn.disabled = true;
    try {
      await http.post("/ai/train", {});
      pb.classList.remove("hidden");
      msg.textContent = "Entrenamiento iniciado...";
      if (_pollInterval) clearInterval(_pollInterval);
      _pollInterval = setInterval(checkTrainingStatus, 5000);
    } catch (err) {
      toast(err.message, "error");
      btn.disabled = false;
    }
  }

  async function checkTrainingStatus() {
    try {
      const s = await http.get("/ai/train-status");
      const pb  = document.getElementById("train-progress-block");
      const msg = document.getElementById("train-msg");
      const btn = document.getElementById("train-btn");
      if (!s.running) {
        if (_pollInterval) { clearInterval(_pollInterval); _pollInterval = null; }
        if (pb) pb.classList.add("hidden");
        if (s.last_result === "ok") {
          toast("Entrenamiento completado exitosamente.", "success");
          if (msg) msg.textContent = "";
          loadModelInfo();
          updateModelStatus();
        } else if (s.last_error && msg) {
          msg.textContent = `Error: ${s.last_error.slice(0, 120)}`;
        }
        if (btn) btn.disabled = false;
      }
    } catch {}
  }
}

// ═══════════════════════════════════════════════════════════════════════════
//  INIT
// ═══════════════════════════════════════════════════════════════════════════

document.addEventListener("DOMContentLoaded", () => {
  // Login form
  document.getElementById("login-form").addEventListener("submit", handleLogin);
  // Logout
  document.getElementById("logout-btn").addEventListener("click", handleLogout);
  // Sidebar toggle
  document.getElementById("sidebar-toggle").addEventListener("click", () => {
    document.getElementById("sidebar").classList.toggle("collapsed");
  });
  // Sidebar nav
  document.querySelectorAll(".nav-item[data-section]").forEach(item => {
    item.addEventListener("click", () => navigateTo(item.dataset.section));
  });

  // Restore session
  if (loadSession()) {
    showPanel();
    navigateTo("dashboard");
  } else {
    showLogin();
  }
});

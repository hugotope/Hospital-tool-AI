const LOGIN_USER = "admin";
const LOGIN_PASS = "1234";
const SESSION_KEY = "hospital_tool_logged";

const loginScreen = document.getElementById("login-screen");
const dashboardScreen = document.getElementById("dashboard-screen");
const loginForm = document.getElementById("login-form");
const loginError = document.getElementById("login-error");
const logoutBtn = document.getElementById("logout-btn");
const loadPreviewBtn = document.getElementById("load-preview-btn");
const datasetStatus = document.getElementById("dataset-status");
const tableHead = document.querySelector("#dataset-table thead");
const tableBody = document.querySelector("#dataset-table tbody");

function showDashboard() {
  loginScreen.classList.add("hidden");
  dashboardScreen.classList.remove("hidden");
}

function showLogin() {
  dashboardScreen.classList.add("hidden");
  loginScreen.classList.remove("hidden");
}

function parseCsvLine(line) {
  const values = [];
  let current = "";
  let inQuotes = false;

  for (let i = 0; i < line.length; i += 1) {
    const char = line[i];

    if (char === '"') {
      if (inQuotes && line[i + 1] === '"') {
        current += '"';
        i += 1;
      } else {
        inQuotes = !inQuotes;
      }
      continue;
    }

    if (char === "," && !inQuotes) {
      values.push(current.trim());
      current = "";
      continue;
    }

    current += char;
  }

  values.push(current.trim());
  return values;
}

function renderTable(headers, rows) {
  tableHead.innerHTML = "";
  tableBody.innerHTML = "";

  const headerRow = document.createElement("tr");
  headers.forEach((header) => {
    const th = document.createElement("th");
    th.textContent = header;
    headerRow.appendChild(th);
  });
  tableHead.appendChild(headerRow);

  rows.forEach((row) => {
    const tr = document.createElement("tr");
    headers.forEach((_, index) => {
      const td = document.createElement("td");
      td.textContent = row[index] || "";
      tr.appendChild(td);
    });
    tableBody.appendChild(tr);
  });
}

async function tryLoadFromBackend() {
  const response = await fetch("http://127.0.0.1:8000/api/dataset/preview?rows=12");
  if (!response.ok) {
    throw new Error("Backend no disponible");
  }
  const payload = await response.json();
  if (!payload.headers || !payload.rows) {
    throw new Error("Respuesta invalida");
  }
  return payload;
}

async function tryLoadCsvDirect() {
  const candidatePaths = [
    "../healthcare_dataset_100k.csv",
    "/healthcare_dataset_100k.csv",
    "./healthcare_dataset_100k.csv",
  ];

  let csvText = "";
  for (const path of candidatePaths) {
    try {
      const response = await fetch(path);
      if (response.ok) {
        csvText = await response.text();
        break;
      }
    } catch (_error) {
      // Try next location.
    }
  }

  if (!csvText) {
    throw new Error("No se pudo leer el CSV en modo estatico");
  }

  const lines = csvText.split(/\r?\n/).filter(Boolean).slice(0, 13);
  const headers = parseCsvLine(lines[0] || "");
  const rows = lines.slice(1).map((line) => parseCsvLine(line));
  return { headers, rows };
}

async function loadPreview() {
  datasetStatus.textContent = "Cargando dataset...";
  loadPreviewBtn.disabled = true;

  try {
    let data;
    try {
      data = await tryLoadFromBackend();
      datasetStatus.textContent = "Preview cargada desde backend Python.";
    } catch (_error) {
      data = await tryLoadCsvDirect();
      datasetStatus.textContent = "Preview cargada en modo estatico.";
    }

    renderTable(data.headers, data.rows);
  } catch (error) {
    datasetStatus.textContent = `Error: ${error.message}`;
  } finally {
    loadPreviewBtn.disabled = false;
  }
}

loginForm.addEventListener("submit", (event) => {
  event.preventDefault();
  const username = loginForm.username.value.trim();
  const password = loginForm.password.value.trim();

  if (username === LOGIN_USER && password === LOGIN_PASS) {
    sessionStorage.setItem(SESSION_KEY, "true");
    loginError.textContent = "";
    showDashboard();
    return;
  }

  loginError.textContent = "Credenciales invalidas. Usa admin / 1234.";
});

logoutBtn.addEventListener("click", () => {
  sessionStorage.removeItem(SESSION_KEY);
  showLogin();
});

loadPreviewBtn.addEventListener("click", loadPreview);

if (sessionStorage.getItem(SESSION_KEY) === "true") {
  showDashboard();
}

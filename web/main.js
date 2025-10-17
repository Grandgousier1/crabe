const config = window.DNT_CONFIG ?? {};
const API_ENDPOINT = (config.apiEndpoint ?? "").trim();
const MODEL_NAME = (config.model ?? "gemini-flash-latest").trim();

const dropzone = document.getElementById("dropzone");
const fileInput = document.getElementById("file-input");
const selectButton = document.getElementById("select-files");
const fileList = document.getElementById("file-list");
const generateButton = document.getElementById("generate-btn");
const clearButton = document.getElementById("clear-btn");
const statusEl = document.getElementById("status");
const uploadProgress = document.getElementById("upload-progress");
const uploadLabel = document.getElementById("upload-label");
const processProgress = document.getElementById("process-progress");
const processLabel = document.getElementById("process-label");
const consoleLog = document.getElementById("console-log");
const consoleClear = document.getElementById("console-clear");

const state = {
  files: [],
  processing: false,
  processTicker: null,
};

function log(message) {
  const timestamp = new Date().toLocaleTimeString();
  consoleLog.textContent += `[${timestamp}] ${message}\n`;
  consoleLog.scrollTop = consoleLog.scrollHeight;
}

function clearConsole() {
  consoleLog.textContent = "";
}

function setStatus(message, isError = false) {
  statusEl.textContent = message;
  statusEl.classList.toggle("status--error", isError);
}

function setUploadProgress(value) {
  uploadProgress.value = value;
  uploadLabel.textContent = `${Math.round(value)}%`;
}

function setProcessProgress(value) {
  processProgress.value = value;
  processLabel.textContent = `${Math.round(value)}%`;
}

function resetProgress() {
  setUploadProgress(0);
  setProcessProgress(0);
  stopProcessTicker();
}

function startProcessTicker() {
  stopProcessTicker();
  let value = 15;
  state.processTicker = window.setInterval(() => {
    value = value >= 95 ? 35 : value + 5;
    setProcessProgress(value);
  }, 220);
}

function stopProcessTicker() {
  if (state.processTicker) {
    window.clearInterval(state.processTicker);
    state.processTicker = null;
  }
}

function formatBytes(bytes) {
  if (bytes === 0) return "0 B";
  const units = ["B", "KB", "MB", "GB"];
  const idx = Math.floor(Math.log(bytes) / Math.log(1024));
  const value = bytes / Math.pow(1024, idx);
  return `${value.toFixed(idx === 0 ? 0 : 1)} ${units[idx]}`;
}

function renderFileList() {
  fileList.innerHTML = "";
  if (state.files.length === 0) {
    const empty = document.createElement("li");
    empty.className = "file-list__item";
    empty.innerHTML = "<span>Aucun fichier sélectionné.</span>";
    fileList.appendChild(empty);
    return;
  }

  for (const file of state.files) {
    const item = document.createElement("li");
    item.className = "file-list__item";
    const name = document.createElement("span");
    name.textContent = file.name;
    const size = document.createElement("span");
    size.textContent = formatBytes(file.size);
    size.style.opacity = "0.7";
    item.appendChild(name);
    item.appendChild(size);
    fileList.appendChild(item);
  }
}

function addFiles(newFiles) {
  const unique = [];
  const existingKeys = new Set(
    state.files.map((file) => `${file.name}/${file.size}/${file.lastModified}`)
  );
  for (const file of newFiles) {
    const key = `${file.name}/${file.size}/${file.lastModified}`;
    if (!existingKeys.has(key)) {
      unique.push(file);
      existingKeys.add(key);
    }
  }
  if (unique.length > 0) {
    state.files = state.files.concat(unique);
    renderFileList();
    log(`📁 ${unique.length} fichier(s) ajouté(s).`);
  }
}

function resetSelection() {
  state.files = [];
  fileInput.value = "";
  renderFileList();
  resetProgress();
  setStatus("");
  log("Sélection réinitialisée.");
}

function setProcessing(isProcessing) {
  state.processing = isProcessing;
  generateButton.disabled = isProcessing;
  clearButton.disabled = isProcessing;
  selectButton.disabled = isProcessing;
  dropzone.classList.toggle("is-disabled", isProcessing);
}

function ensureEndpoint() {
  if (API_ENDPOINT) return true;
  const message =
    "Configurez l'URL de l'API dans web/config.js (clé `apiEndpoint`).";
  setStatus(message, true);
  log(`⚠️ ${message}`);
  setProcessing(false);
  return false;
}

function sendRequest() {
  if (state.files.length === 0) {
    setStatus("Ajoutez au moins un fichier avant de lancer le traitement.", true);
    return;
  }
  if (!ensureEndpoint()) {
    return;
  }

  const formData = new FormData();
  formData.append("model", MODEL_NAME || "gemini-flash-latest");
  for (const file of state.files) {
    formData.append("files", file, file.name);
  }

  const xhr = new XMLHttpRequest();
  xhr.open("POST", API_ENDPOINT, true);
  xhr.responseType = "blob";

  setProcessing(true);
  resetProgress();
  setStatus("Téléversement en cours…");
  log(`⏫ Téléversement vers ${API_ENDPOINT}`);

  xhr.upload.onprogress = (event) => {
    if (event.lengthComputable) {
      const percent = (event.loaded / event.total) * 100;
      setUploadProgress(percent);
    }
  };

  xhr.onerror = () => {
    stopProcessTicker();
    setProcessProgress(0);
    setStatus("Erreur réseau lors de la requête.", true);
    log("❌ Erreur réseau lors de la requête.");
    setProcessing(false);
  };

  xhr.onloadstart = () => {
    setUploadProgress(5);
  };

  xhr.onloadend = () => {
    setUploadProgress(100);
  };

  xhr.onreadystatechange = () => {
    if (xhr.readyState === XMLHttpRequest.HEADERS_RECEIVED) {
      startProcessTicker();
      setStatus("Traitement du document…");
      log("⚙️ Traitement en cours côté serveur.");
    }
  };

  xhr.onload = () => {
    stopProcessTicker();
    setProcessProgress(100);

    if (xhr.status >= 200 && xhr.status < 300) {
      const blob = xhr.response;
      const disposition = xhr.getResponseHeader("Content-Disposition") ?? "";
      const match = disposition.match(/filename="?([^"]+)"?/i);
      const filename = match ? decodeURIComponent(match[1]) : "bon_livraison.pdf";

      const url = URL.createObjectURL(blob);
      const anchor = document.createElement("a");
      anchor.href = url;
      anchor.download = filename;
      anchor.click();
      URL.revokeObjectURL(url);

      setStatus("PDF généré avec succès. Téléchargement lancé.");
      log(`✅ PDF généré (${filename}).`);
    } else {
      const errorBlob = xhr.response;
      if (errorBlob && typeof errorBlob.text === "function") {
        errorBlob.text().then((text) => {
          try {
            const payload = JSON.parse(text);
            const detail = payload?.detail ?? text;
            setStatus(`Erreur (${xhr.status}) : ${detail}`, true);
            log(`❌ Erreur ${xhr.status} : ${detail}`);
          } catch (error) {
            setStatus(`Erreur (${xhr.status}) : ${text}`, true);
            log(`❌ Erreur ${xhr.status} : ${text}`);
          }
        });
      } else {
        const message = xhr.statusText || "Erreur inconnue";
        setStatus(`Erreur (${xhr.status}) : ${message}`, true);
        log(`❌ Erreur ${xhr.status} : ${message}`);
      }
    }

    setProcessing(false);
  };

  xhr.send(formData);
}

function handleDrop(event) {
  event.preventDefault();
  dropzone.classList.remove("is-dragover");
  if (state.processing) return;
  const files = Array.from(event.dataTransfer.files ?? []);
  if (files.length === 0) {
    log("ℹ️ Aucun fichier détecté lors du dépôt.");
    return;
  }
  addFiles(files);
}

function init() {
  renderFileList();
  clearConsole();

  if (!API_ENDPOINT) {
    setStatus(
      "Définissez l'URL du backend dans web/config.js avant de lancer un traitement.",
      true
    );
    log("⚠️ Aucune URL d'API configurée (voir web/config.js).");
  }

  selectButton.addEventListener("click", () => {
    if (!state.processing) {
      fileInput.click();
    }
  });

  fileInput.addEventListener("change", (event) => {
    const files = Array.from(event.target.files ?? []);
    if (files.length > 0) {
      addFiles(files);
    }
  });

  dropzone.addEventListener("dragover", (event) => {
    event.preventDefault();
    if (!state.processing) {
      dropzone.classList.add("is-dragover");
    }
  });

  dropzone.addEventListener("dragleave", () => {
    dropzone.classList.remove("is-dragover");
  });

  dropzone.addEventListener("drop", handleDrop);
  dropzone.addEventListener("click", () => {
    if (!state.processing) {
      fileInput.click();
    }
  });

  generateButton.addEventListener("click", () => {
    if (!state.processing) {
      sendRequest();
    }
  });

  clearButton.addEventListener("click", () => {
    if (!state.processing) {
      resetSelection();
    }
  });

  consoleClear.addEventListener("click", () => {
    clearConsole();
    log("Console nettoyée.");
  });
}

init();

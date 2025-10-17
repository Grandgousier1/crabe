const form = document.getElementById("delivery-form");
const statusEl = document.getElementById("status");
const endpointInput = document.getElementById("endpoint");
const imagesInput = document.getElementById("images");
const jsonInput = document.getElementById("json-input");
const modelInput = document.getElementById("model");
const submitButton = form.querySelector("button[type=submit]");

const ENDPOINT_STORAGE_KEY = "delivery-transformer:endpoint";

const savedEndpoint = window.localStorage.getItem(ENDPOINT_STORAGE_KEY);
if (savedEndpoint) {
  endpointInput.value = savedEndpoint;
}

function setStatus(message, isError = false) {
  statusEl.textContent = message;
  statusEl.classList.toggle("status--error", isError);
}

form.addEventListener("submit", async (event) => {
  event.preventDefault();

  const endpoint = endpointInput.value.trim();
  const model = modelInput.value.trim() || "gemini-flash-latest";
  const jsonText = jsonInput.value.trim();
  const files = Array.from(imagesInput.files ?? []);

  if (!endpoint) {
    setStatus("Veuillez indiquer l'URL du service.", true);
    return;
  }

  if (!jsonText && files.length === 0) {
    setStatus("Ajoutez des images ou fournissez un JSON structuré.", true);
    return;
  }

  window.localStorage.setItem(ENDPOINT_STORAGE_KEY, endpoint);

  const formData = new FormData();
  formData.append("model", model);

  if (jsonText) {
    try {
      JSON.parse(jsonText);
    } catch (error) {
      setStatus("Le JSON fourni est invalide.", true);
      return;
    }
    const blob = new Blob([jsonText], { type: "application/json" });
    formData.append("items_json", blob, "items.json");
  } else {
    for (const file of files) {
      formData.append("files", file, file.name);
    }
  }

  submitButton.disabled = true;
  setStatus("Traitement en cours…");

  try {
    const response = await fetch(endpoint, {
      method: "POST",
      body: formData,
    });

    if (!response.ok) {
      let detail = response.statusText;
      try {
        const payload = await response.json();
        if (payload?.detail) {
          detail = payload.detail;
        }
      } catch (error) {
        // ignore parsing error
      }
      setStatus(`Erreur (${response.status}) : ${detail}`, true);
      return;
    }

    const blob = await response.blob();
    const disposition = response.headers.get("Content-Disposition") ?? "";
    const match = disposition.match(/filename="?([^"]+)"?/i);
    const filename = match ? match[1] : "bon_livraison.pdf";

    const url = URL.createObjectURL(blob);
    const anchor = document.createElement("a");
    anchor.href = url;
    anchor.download = filename;
    anchor.rel = "noopener";
    anchor.click();
    URL.revokeObjectURL(url);

    setStatus("PDF généré avec succès. Téléchargement lancé.");
  } catch (error) {
    setStatus(`Erreur réseau : ${error.message}`, true);
  } finally {
    submitButton.disabled = false;
  }
});

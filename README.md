# Transformer de bons de livraison

Outil complet pour convertir un bon de livraison numérisé en PDF LaTeX propre, trié par univers animal et enrichi avec codes-barres EAN13.  
Le projet propose :

- **CLI batch** : exécution directe par arguments ou via un assistant interactif.
- **API FastAPI** : endpoint `/transform` prêt à être containerisé ou exposé derrière Netlify Functions.
- **Interface Web statique** : page minimaliste (hébergeable sur Netlify) qui consomme l'API.

## Prérequis

- Python 3.10+
- `pdflatex` accessible dans le `PATH` (via TeX Live ou équivalent). Sur Render, ajoutez `apt.txt` fourni pour installer TeX Live lors du build.
- Clé API Gemini stockée côté serveur/CLI (voir ci-dessous)

## Installation

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Copiez l'exemple fourni et remplissez-le :

```bash
cp .env.example .env
```

Modifiez ensuite `.env` avec votre clé :

```
GEMINI_API_KEY=sk-...
```

La CLI et l'API chargent automatiquement cette valeur (via `python-dotenv`).  
Vous pouvez aussi définir la variable d'environnement dans votre système.

> Le rendu PDF nécessite un moteur LaTeX. Ajoutez TeX Live à votre environnement (par exemple via `apt-get install texlive-latex-base`). Sur Render, le fichier `apt.txt` assure cette installation.

## CLI (mode batch)

```bash
python transform_delivery_note.py \
  --images bon1.jpg bon2.jpg \
  --output livraison_finale.pdf
```

Options utiles :

- `--items-json <fichier>` : charge un JSON déjà structuré (bypass Gemini).
- `--keep-tex` : conserve le `.tex` généré.
- `--model <nom>` : change de modèle Gemini (`gemini-flash-latest` par défaut).
- `--interactive` : lance l'assistant guidé (voir ci-dessous).

### Assistant interactif

```bash
python transform_delivery_note.py --interactive
```

Le terminal vous guide pour :

1. Choisir entre OCR Gemini ou chargement d'un JSON.
2. Sélectionner les images (ou le fichier JSON).
3. Définir le chemin du PDF de sortie.
4. Lancer la génération et afficher le résultat.

## API FastAPI

L'application est définie dans `api_server.py`.

```bash
uvicorn api_server:app --reload
# ou
python api_server.py
```

Requête type (cURL) :

```bash
curl -X POST http://localhost:8000/transform \
  -F "files=@bon1.jpg" \
  -F "files=@bon2.jpg"
```

Le service renvoie un PDF (contenu binaire).  
Vous pouvez aussi envoyer un JSON structuré :

```bash
curl -X POST http://localhost:8000/transform \
  -F "items_json=@structure.json;type=application/json"
```

## Interface Web (Netlify-friendly)

Le dossier `web/` contient une page statique :

- `index.html` : interface drag & drop avec console intégrée.
- `main.js` : upload via XHR, double barre de progression (téléversement + traitement) et logs en temps réel.
- `styles.css` : thème clair/sombre minimaliste.
- `config.js` : point de configuration de l’URL API.

Avant déploiement, éditez `web/config.js` :

```js
window.DNT_CONFIG = {
  apiEndpoint: "https://crabe.onrender.com/transform",
  model: "gemini-flash-latest"
};
```

Si `model` est omis, la valeur par défaut `gemini-flash-latest` est utilisée.

Déploiement Netlify :

1. Définissez le dossier de publication sur `web`.
2. `netlify deploy --dir=web` ou utilisez l’interface Netlify.
3. Aucun champ à modifier côté client : le bouton “Générer le PDF” utilise l’URL définie dans `config.js`.

⚠️ La clé Gemini doit rester côté serveur (dans `.env` ou vos secrets Render). L’interface web ne transmet que les fichiers d’images.

### Déploiement Render + Netlify (gratuit)

1. **Publiez le code sur GitHub.**
2. **Render (backend)**
   - Créez un service « Web Service » à partir du dépôt GitHub.
   - Paramètres :
     - Runtime : *Python 3*  
     - Ajoutez `apt.txt` (inclus) pour installer TeX Live (`texlive-latex-base`/`extra`).
     - Build command : `pip install -r requirements.txt`
     - Start command : `uvicorn api_server:app --host 0.0.0.0 --port 10000`
   - Dans l’onglet *Environment*, ajoutez :
     - `GEMINI_API_KEY` = votre clé
     - `ALLOWED_ORIGINS` = `https://votre-site-netlify.netlify.app`
   - Choisissez le plan gratuit et déployez. Notez l’URL Render (ex: `https://delivery-transformer.onrender.com`).
3. **Netlify (front-end)**
   - Créez un nouveau site et pointez le répertoire `web/`.
   - Dans le fichier `web/index.html`, remplacez la valeur du champ URL par l’endpoint Render (`https://.../transform`), puis déployez.
   - Sur le site publié, l’URL de l’API est déjà renseignée ; uploadez des images, cliquez sur « Générer le PDF ».

> Si vous préférez limiter l’accès à plusieurs domaines, listez-les séparés par des virgules dans `ALLOWED_ORIGINS`.

## Sécurisation de la clé Gemini

- **Localement** : stockez la clé dans `.env` (non versionné) ou dans vos variables d'environnement shell.
- **Serveur / Docker / Netlify Functions** : définissez `GEMINI_API_KEY` via les secrets de déploiement.
- **Interface web** : aucune clé n'est transmise depuis le navigateur ; seul votre backend signe la requête vers Gemini.

## Format JSON attendu

```json
{
  "supplier": "Nom du fournisseur",
  "reference": "Réf BL-1234",
  "delivery_date": "2024-06-21",
  "items": [
    {
      "description": "Croquettes premium chien adulte 12 kg",
      "expected_quantity": 4,
      "ean13": "4008429062891",
      "animal_guess": "chien"
    }
  ]
}
```

## Conseils

- Orientez correctement les scans pour améliorer l'OCR.
- Laissez `ean13` à `null` si illisible ; le script affichera « -- ».
- Les scans Tetra Pond seront classés en « poisson » ; ajustez la liste de mots-clés dans `delivery_transformer/core.py` si besoin.
*** End Patch

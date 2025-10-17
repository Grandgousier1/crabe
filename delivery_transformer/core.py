"""Core primitives for transforming delivery notes into harmonised LaTeX PDFs."""

from __future__ import annotations

import json
import mimetypes
import shutil
import subprocess
import tempfile
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Optional

import google.generativeai as genai
from barcode import EAN13
from barcode.writer import ImageWriter


# Preferred display order for sections in the LaTeX document.
CATEGORY_ORDER = [
    "chien",
    "chat",
    "poisson",
    "oiseau",
    "rongeur",
    "reptile",
    "ferme",
    "autres",
]


# Keyword heuristics used to group items by animal when the model does not
# provide an explicit classification.
CATEGORY_KEYWORDS = {
    "chien": [
        "chien",
        "canin",
        "dog",
        "chienne",
        "puppy",
        "pedigree",
        "dog chow",
        "doggy",
    ],
    "chat": [
        "chat",
        "feline",
        "cat",
        "chaton",
        "kitten",
        "whiskas",
        "felix",
        "royal canin cat",
    ],
    "poisson": [
        "poisson",
        "fish",
        "aquarium",
        "tetra",
        "pond",
        "aquatic",
        "koi",
        "marine",
    ],
    "oiseau": [
        "bird",
        "oiseau",
        "perruche",
        "canari",
        "volaille",
        "poultry",
    ],
    "rongeur": [
        "hamster",
        "rongeur",
        "lapin",
        "rabbit",
        "gerbil",
        "cochon d'inde",
        "guinea pig",
        "chinchilla",
        "rat",
        "souris",
        "furet",
    ],
    "reptile": [
        "reptile",
        "serpent",
        "iguane",
        "tortue",
        "dragon",
    ],
    "ferme": [
        "bovin",
        "ovins",
        "porc",
        "poule",
        "cheval",
        "equine",
        "equidé",
        "veau",
        "calf",
        "cow",
        "horse",
        "sheep",
        "goat",
    ],
}


PROMPT_TEMPLATE = """
Analyse attentivement l'intégralité des bons de livraison fournis en images.
La transcription doit être exhaustive (pas d'omission de ligne ni d'article),
et chaque article doit être capturé avec les champs suivants :

- description : libellé complet, tel qu'il apparaît.
- expected_quantity : quantité attendue (nombre).
- ean13 : code-barres EAN-13 (13 chiffres). Si un code comporte 12 chiffres,
  ajoute la clé de contrôle pour renvoyer 13 chiffres.
- animal_guess : catégorie d'animal la plus appropriée (exemples : chien,
  chat, poisson, oiseau, rongeur, reptile, ferme, autres).

Retourne exclusivement un JSON respectant ce schéma :
{{
  "supplier": "<string ou null>",
  "reference": "<string ou null>",
  "delivery_date": "<aaaa-mm-jj ou null>",
  "items": [
    {{
      "description": "<string>",
      "expected_quantity": <float ou int>,
      "ean13": "<string de 13 chiffres>",
      "animal_guess": "<string non vide>"
    }}
  ]
}}

Consignes supplémentaires :
- Conserve les accents et les signes monétaires présents dans le libellé.
- N'invente jamais d'EAN : indique null si le code est illisible.
- expected_quantity doit toujours être un nombre (pas de texte).
- animal_guess doit être en minuscules.
- Ne retourne que du JSON valide, aucune phrase explicative ni commentaire.
"""


@dataclass
class DeliveryItem:
    description: str
    expected_quantity: float
    ean13: str
    animal_guess: str


@dataclass
class DeliveryNote:
    supplier: Optional[str]
    reference: Optional[str]
    delivery_date: Optional[str]
    items: List[DeliveryItem]


def extract_with_gemini(
    image_paths: List[str], api_key: str, model_name: str
) -> DeliveryNote:
    genai.configure(api_key=api_key)
    model = genai.GenerativeModel(model_name)

    prompt = PROMPT_TEMPLATE.strip()
    contents = [prompt]
    for image_path in image_paths:
        mime_type, _ = mimetypes.guess_type(image_path)
        if not mime_type:
            mime_type = "application/octet-stream"
        with open(image_path, "rb") as handle:
            data = handle.read()
        contents.append(
            genai.types.Part.from_bytes(data=data, mime_type=mime_type)
        )

    response = model.generate_content(
        contents,
        generation_config=genai.types.GenerationConfig(
            temperature=0.2,
            top_p=0.8,
            top_k=40,
            response_mime_type="application/json",
        ),
    )

    if not response.text:
        raise RuntimeError("Réponse vide de l'API Gemini.")
    try:
        payload = json.loads(response.text)
    except json.JSONDecodeError as exc:
        raise RuntimeError("JSON invalide renvoyé par Gemini.") from exc

    return delivery_note_from_payload(payload)


def build_delivery_note(
    *,
    image_paths: Optional[Iterable[Path | str]] = None,
    items_json_path: Optional[Path] = None,
    items_payload: Optional[Dict] = None,
    api_key: Optional[str] = None,
    model_name: str = "gemini-flash-latest",
) -> DeliveryNote:
    if items_payload is not None:
        return delivery_note_from_payload(items_payload)

    if items_json_path is not None:
        if not items_json_path.exists():
            raise FileNotFoundError(f"Fichier JSON introuvable: {items_json_path}")
        return load_items_from_json(items_json_path)

    if image_paths:
        str_paths = [str(Path(path)) for path in image_paths]
        missing = [path for path in str_paths if not Path(path).exists()]
        if missing:
            raise FileNotFoundError(
                "Fichiers image introuvables: " + ", ".join(missing)
            )
        if not api_key:
            raise ValueError(
                "Clé API Gemini requise pour l'extraction à partir d'images."
            )
        return extract_with_gemini(str_paths, api_key, model_name)

    raise ValueError(
        "Aucune donnée fournie : précisez des images, un JSON structuré ou un payload."
    )


def delivery_note_from_payload(payload: Dict) -> DeliveryNote:
    raw_items = payload.get("items")
    if not isinstance(raw_items, list) or not raw_items:
        raise ValueError("Aucun article détecté dans le JSON fourni.")

    items: List[DeliveryItem] = []
    for entry in raw_items:
        description = entry.get("description")
        ean13 = (entry.get("ean13") or "").strip()
        animal_guess = (entry.get("animal_guess") or "autres").strip().lower()
        expected_quantity = entry.get("expected_quantity")

        if not description:
            raise ValueError("Un article ne possède pas de description.")

        if expected_quantity is None:
            raise ValueError(f"Quantité manquante pour l'article: {description}")

        try:
            quantity_value = float(expected_quantity)
        except (TypeError, ValueError) as exc:
            raise ValueError(
                f"Quantité invalide pour l'article '{description}': {expected_quantity}"
            ) from exc

        normalised_ean = ""
        if ean13:
            if not ean13.isdigit():
                raise ValueError(
                    f"EAN13 invalide pour l'article '{description}': {ean13}"
                )
            if len(ean13) not in (12, 13):
                raise ValueError(
                    f"EAN pour '{description}' doit contenir 12 ou 13 chiffres, obtenu {len(ean13)}."
                )
            normalised_ean = ensure_ean13(ean13)

        items.append(
            DeliveryItem(
                description=description.strip(),
                expected_quantity=quantity_value,
                ean13=normalised_ean,
                animal_guess=animal_guess or "autres",
            )
        )

    return DeliveryNote(
        supplier=payload.get("supplier"),
        reference=payload.get("reference"),
        delivery_date=payload.get("delivery_date"),
        items=items,
    )


def load_items_from_json(path: Path) -> DeliveryNote:
    with path.open("r", encoding="utf-8") as handle:
        payload = json.load(handle)
    return delivery_note_from_payload(payload)


def normalise_category(description: str, hint: str) -> str:
    # Direct hint takes precedence when it matches a known category.
    if hint in CATEGORY_ORDER:
        return hint

    synonyms = {
        "canine": "chien",
        "canin": "chien",
        "feline": "chat",
        "félin": "chat",
        "equine": "ferme",
        "equidé": "ferme",
        "cheval": "ferme",
        "equid": "ferme",
        "bovins": "ferme",
    }
    if hint in synonyms:
        return synonyms[hint]

    lower = description.lower()
    for category, keywords in CATEGORY_KEYWORDS.items():
        if any(keyword in lower for keyword in keywords):
            return category

    # Fallback to hint if it is at least non-empty.
    if hint:
        return hint
    return "autres"


def ensure_ean13(code: str) -> str:
    """Returns a 13-digit EAN by computing the checksum if necessary."""
    if not code:
        raise ValueError("EAN vide")
    if len(code) == 13:
        return code
    if len(code) == 12:
        checksum = compute_ean_checksum(code)
        return f"{code}{checksum}"
    raise ValueError(f"Longueur EAN inattendue: {code}")


def compute_ean_checksum(code12: str) -> str:
    digits = [int(ch) for ch in code12]
    total = sum(digits[i] * (3 if i % 2 else 1) for i in range(12))
    return str((10 - (total % 10)) % 10)


def escape_latex(text: str) -> str:
    replacements = {
        "&": r"\&",
        "%": r"\%",
        "$": r"\$",
        "#": r"\#",
        "_": r"\_",
        "{": r"\{",
        "}": r"\}",
        "~": r"\textasciitilde{}",
        "^": r"\textasciicircum{}",
        "\\": r"\textbackslash{}",
    }
    escaped = "".join(replacements.get(ch, ch) for ch in text)
    return escaped.replace("\n", r"\newline{}")


def render_barcode(ean13: str, directory: Path) -> Path:
    bare_code = ensure_ean13(ean13)
    image_path = directory / f"{bare_code}.png"
    # python-barcode requires a path without extension and appends .png itself.
    temp_path = image_path.with_suffix("")
    ean = EAN13(bare_code, writer=ImageWriter())
    saved_path = Path(ean.save(str(temp_path), options={"dpi": 200, "font_size": 10}))
    return saved_path


def build_latex_document(
    note: DeliveryNote,
    grouped_items: Dict[str, List[DeliveryItem]],
    barcode_relpaths: Dict[str, Path],
) -> str:
    def header_field(label: str, content: Optional[str]) -> str:
        if not content:
            return ""
        return rf"\textbf{{{escape_latex(label)}}}: {escape_latex(content)}\\"

    sections = []
    for category in CATEGORY_ORDER:
        items = grouped_items.get(category)
        if not items:
            continue
        header = category.capitalize()
        rows = []
        for item in items:
            pretty_qty = (
                int(item.expected_quantity)
                if item.expected_quantity.is_integer()
                else item.expected_quantity
            )
            ean_text = escape_latex(item.ean13) if item.ean13 else r"\textit{--}"
            barcode_cell = r"\textit{Non disponible}"
            if item.ean13:
                rel_path = barcode_relpaths.get(item.ean13)
                if rel_path:
                    barcode_cell = rf"\includegraphics[height=1.5cm]{{{escape_latex(rel_path.as_posix())}}}"
            row = (
                rf"{escape_latex(item.description)} & {pretty_qty} & {ean_text} & "
                rf"{barcode_cell} & \checkbox & \qtybox \\"
            )
            rows.append(row)
        table = "\n".join(
            [
                r"\begin{longtable}{p{6cm}p{1.5cm}p{2.4cm}p{3.0cm}p{1.6cm}p{2.2cm}}",
                r"\toprule",
                r"Article & Qté attendue & EAN13 & Code-barres & OK & Qté \\",
                r"\midrule",
                *rows,
                r"\bottomrule",
                r"\end{longtable}",
            ]
        )
        sections.append(
            "\n".join(
                [
                    rf"\section*{{{escape_latex(header)}}}",
                    table,
                ]
            )
        )

    if not sections:
        raise ValueError("Aucun article n'a été regroupé; vérifiez les données en entrée.")

    metadata_block = "".join(
        [
            header_field("Fournisseur", note.supplier),
            header_field("Référence", note.reference),
            header_field("Date de livraison", note.delivery_date),
        ]
    )

    latex = r"""
\documentclass[12pt,a4paper]{article}
\usepackage[utf8]{inputenc}
\usepackage[T1]{fontenc}
\usepackage[a4paper,margin=1.8cm]{geometry}
\usepackage{graphicx}
\usepackage{array}
\usepackage{longtable}
\usepackage{booktabs}
\usepackage{setspace}
\usepackage{helvet}
\renewcommand{\familydefault}{\sfdefault}
\newcommand{\checkbox}{\fbox{\rule{0pt}{1.5ex}\hspace{2.0ex}}}
\newcommand{\qtybox}{\fbox{\rule{0pt}{1.5ex}\hspace{3.5ex}}}
\renewcommand{\arraystretch}{1.3}
\setlength{\parskip}{0.6em}
\setlength{\parindent}{0pt}
\begin{document}
\begin{center}
\Large\textbf{Bon de livraison harmonisé}
\end{center}
%METADATA%
\vspace{1em}
%SECTIONS%
\end{document}
""".strip()

    latex = latex.replace("%METADATA%", metadata_block or "")
    latex = latex.replace("%SECTIONS%", "\n\n".join(sections))
    return latex


def compile_latex(
    latex_source: str,
    output_pdf: Path,
    keep_tex: bool,
    assets: Optional[Dict[Path, Path]] = None,
) -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir_path = Path(tmpdir)
        tex_path = tmpdir_path / "bon_livraison.tex"
        tex_path.write_text(latex_source, encoding="utf-8")

        if assets:
            for relative_path, original in assets.items():
                destination = tmpdir_path / relative_path
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(original, destination)

        cmd = [
            "pdflatex",
            "-interaction=nonstopmode",
            "-halt-on-error",
            tex_path.name,
        ]

        completed = subprocess.run(
            cmd,
            cwd=tmpdir,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            check=False,
        )
        if completed.returncode != 0:
            raise RuntimeError(
                "La compilation LaTeX a échoué:\n" + completed.stdout
            )

        built_pdf = tex_path.with_suffix(".pdf")
        output_pdf.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(built_pdf), str(output_pdf))

        if keep_tex:
            final_tex = output_pdf.with_suffix(".tex")
            shutil.move(str(tex_path), final_tex)


def group_items_by_category(items: Iterable[DeliveryItem]) -> Dict[str, List[DeliveryItem]]:
    grouped: Dict[str, List[DeliveryItem]] = defaultdict(list)
    for item in items:
        category = normalise_category(item.description, item.animal_guess)
        grouped[category].append(item)
    for entries in grouped.values():
        entries.sort(key=lambda x: x.description.lower())
    return grouped


def generate_barcodes(items: Iterable[DeliveryItem], directory: Path) -> Dict[str, Path]:
    directory.mkdir(parents=True, exist_ok=True)
    barcode_paths: Dict[str, Path] = {}
    for item in items:
        if not item.ean13:
            continue
        normalised = ensure_ean13(item.ean13)
        if normalised in barcode_paths:
            continue
        barcode_paths[normalised] = render_barcode(normalised, directory)
    return barcode_paths


def render_pdf(
    note: DeliveryNote,
    output_pdf: Path,
    keep_tex: bool = False,
) -> Path:
    grouped = group_items_by_category(note.items)

    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir_path = Path(tmpdir)
        barcode_dir = tmpdir_path / "barcodes"
        generated_barcodes = generate_barcodes(note.items, barcode_dir)

        barcode_relpaths: Dict[str, Path] = {}
        latex_assets: Dict[Path, Path] = {}
        for ean, actual_path in generated_barcodes.items():
            relative_path = Path("barcodes") / actual_path.name
            barcode_relpaths[ean] = relative_path
            latex_assets[relative_path] = actual_path

        latex_source = build_latex_document(note, grouped, barcode_relpaths)

        compile_latex(latex_source, output_pdf, keep_tex, assets=latex_assets)

    return output_pdf


def render_pdf_bytes(note: DeliveryNote, keep_tex: bool = False) -> bytes:
    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir_path = Path(tmpdir)
        output_pdf = tmpdir_path / "bon_livraison.pdf"
        render_pdf(note, output_pdf, keep_tex=keep_tex)
        return output_pdf.read_bytes()

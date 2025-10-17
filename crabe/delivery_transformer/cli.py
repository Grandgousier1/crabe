"""Command-line interface for the delivery note transformer."""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path
from typing import Iterable, Optional

from dotenv import load_dotenv

from . import core


load_dotenv()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Transforme un bon de livraison en PDF LaTeX harmonisé.",
    )
    parser.add_argument(
        "--interactive",
        action="store_true",
        help="Lance un assistant interactif dans le terminal.",
    )
    parser.add_argument(
        "--images",
        nargs="+",
        help="Chemins des images du bon de livraison (JPEG, PNG, PDF scanné).",
    )
    parser.add_argument(
        "--items-json",
        type=Path,
        help="Fichier JSON déjà structuré (bypass l'appel Gemini).",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("bon_livraison.pdf"),
        help="Chemin du PDF de sortie (par défaut: %(default)s).",
    )
    parser.add_argument(
        "--keep-tex",
        action="store_true",
        help="Conserver le fichier LaTeX intermédiaire à côté du PDF.",
    )
    parser.add_argument(
        "--model",
        default="gemini-flash-latest",
        help="Nom du modèle Gemini à utiliser (défaut: %(default)s).",
    )
    parser.add_argument(
        "--api-key",
        default=os.environ.get("GEMINI_API_KEY"),
        help="Clé API Gemini (par défaut: variable GEMINI_API_KEY ou .env).",
    )
    return parser


def run_batch_mode(
    *,
    image_paths: Optional[Iterable[str]],
    items_json: Optional[Path],
    output: Path,
    keep_tex: bool,
    model: str,
    api_key: Optional[str],
) -> Path:
    note = core.build_delivery_note(
        image_paths=image_paths,
        items_json_path=items_json,
        api_key=api_key,
        model_name=model,
    )
    return core.render_pdf(note, output, keep_tex=keep_tex)


def run_interactive(model: str, default_api_key: Optional[str]) -> None:
    print("=== Assistant transformation de bon de livraison ===")
    print(
        "Ce mode guide l'extraction depuis des images ou un JSON structuré pour produire un PDF."
    )
    print()

    mode = ""
    while mode not in {"1", "2"}:
        mode = input("1) OCR via Gemini  2) Charger un JSON structuré ? [1/2]: ").strip()

    note = None
    if mode == "2":
        while True:
            json_path = input("Chemin du fichier JSON: ").strip()
            if not json_path:
                print("Veuillez renseigner un fichier JSON.")
                continue
            path = Path(json_path).expanduser()
            if not path.exists():
                print(f"Fichier introuvable: {path}")
                continue
            try:
                note = core.load_items_from_json(path)
            except Exception as exc:  # pragma: no cover - interactive guard
                print(f"Erreur lors de la lecture du JSON: {exc}")
                continue
            break
    else:
        print("Saisissez les chemins des images (laisser vide pour terminer).")
        images: list[str] = []
        while True:
            path = input("Image: ").strip()
            if not path:
                if not images:
                    print("Ajoutez au moins une image.")
                    continue
                break
            expanded = str(Path(path).expanduser())
            if not Path(expanded).exists():
                print(f"Fichier introuvable: {expanded}")
                continue
            images.append(expanded)

        api_key = default_api_key
        if api_key:
            print("Clé API détectée via l'environnement (.env ou variable système).")
        else:
            api_key = input("Clé API Gemini (saisie masquée recommandée dans .env) : ").strip()
            if not api_key:
                print("Une clé API est nécessaire pour contacter Gemini.")
                sys.exit(1)

        selected_model = input(
            f"Modèle Gemini à utiliser [{model}]: "
        ).strip() or model

        try:
            note = core.build_delivery_note(
                image_paths=images,
                api_key=api_key,
                model_name=selected_model,
            )
        except Exception as exc:  # pragma: no cover - interactive guard
            print(f"Erreur lors de l'appel Gemini: {exc}")
            sys.exit(1)

    default_output = Path("bon_livraison.pdf")
    output_entry = (
        input(f"Chemin du PDF de sortie [{default_output}]: ").strip()
        or str(default_output)
    )
    output_path = Path(output_entry).expanduser()

    keep_tex_answer = input("Conserver le fichier LaTeX intermédiaire ? [o/N]: ").strip().lower()
    keep_tex = keep_tex_answer in {"o", "oui", "y", "yes"}

    try:
        core.render_pdf(note, output_path, keep_tex=keep_tex)
    except Exception as exc:  # pragma: no cover - interactive guard
        print(f"Erreur lors de la génération du PDF: {exc}")
        sys.exit(1)

    print(f"PDF généré : {output_path}")
    if keep_tex:
        print(f"Fichier LaTeX : {output_path.with_suffix('.tex')}")


def main(argv: Optional[Iterable[str]] = None) -> None:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.interactive:
        run_interactive(args.model, args.api_key)
        return

    if not args.items_json and not args.images:
        parser.error("spécifiez --items-json ou au moins un fichier via --images")
    if args.items_json and not args.items_json.exists():
        parser.error(f"fichier JSON introuvable: {args.items_json}")
    if args.images:
        missing = [path for path in args.images if not Path(path).exists()]
        if missing:
            parser.error(f"fichiers image introuvables: {', '.join(missing)}")
    if not args.items_json and not args.api_key:
        parser.error(
            "aucune clé API fournie (utilisez --api-key ou la variable GEMINI_API_KEY)"
        )

    try:
        output_path = run_batch_mode(
            image_paths=args.images,
            items_json=args.items_json,
            output=args.output,
            keep_tex=args.keep_tex,
            model=args.model,
            api_key=args.api_key,
        )
    except Exception as exc:  # pragma: no cover - CLI guard
        print(f"Erreur : {exc}", file=sys.stderr)
        sys.exit(1)

    print(f"PDF généré : {output_path}")


if __name__ == "__main__":  # pragma: no cover
    main()

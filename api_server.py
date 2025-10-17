"""Minimal FastAPI server exposing the delivery note transformer as JSON/PDF API."""

from __future__ import annotations

import io
import json
import os
import tempfile
from pathlib import Path
from typing import List, Optional

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from dotenv import load_dotenv

from delivery_transformer import core

load_dotenv()

app = FastAPI(
    title="Delivery Note Transformer",
    description="Expose le pipeline de transformation (OCR + PDF) via HTTP.",
    version="1.0.0",
)

allowed_origins_env = os.environ.get("ALLOWED_ORIGINS", "*")
allowed_origins = [
    origin.strip() for origin in allowed_origins_env.split(",") if origin.strip()
] or ["*"]

app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_credentials=False,
    allow_methods=["POST", "OPTIONS"],
    allow_headers=["*"],
)


@app.get("/")
async def root() -> dict[str, str]:
    return {
        "status": "ok",
        "message": "Delivery Note Transformer API. Use POST /transform or GET /health.",
    }


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/transform")
async def transform_delivery_note(
    files: List[UploadFile] = File(default=[]),
    items_json: Optional[UploadFile] = File(default=None),
    model: str = Form(default="gemini-flash-latest"),
) -> StreamingResponse:
    if not files and items_json is None:
        raise HTTPException(
            status_code=400,
            detail="Envoyez des images ou un JSON structuré pour lancer la transformation.",
        )

    note = None

    if items_json is not None:
        try:
            payload_bytes = await items_json.read()
            payload = json.loads(payload_bytes.decode("utf-8"))
        except json.JSONDecodeError as exc:
            raise HTTPException(
                status_code=400, detail=f"JSON invalide: {exc}"
            ) from exc
        note = core.delivery_note_from_payload(payload)

    if note is None:
        resolved_api_key = os.environ.get("GEMINI_API_KEY")
        if not resolved_api_key:
            raise HTTPException(
                status_code=400,
                detail="Clé API Gemini manquante côté serveur (variable GEMINI_API_KEY).",
            )
        if not files:
            raise HTTPException(
                status_code=400,
                detail="Aucun fichier image fourni.",
            )

        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir_path = Path(tmpdir)
            image_paths: list[Path] = []
            for upload in files:
                suffix = Path(upload.filename or "image").suffix or ".png"
                target = tmpdir_path / upload.filename if upload.filename else tmpdir_path / f"scan{len(image_paths)+1}{suffix}"
                data = await upload.read()
                target.write_bytes(data)
                image_paths.append(target)

            note = core.build_delivery_note(
                image_paths=image_paths,
                api_key=resolved_api_key,
                model_name=model,
            )

    try:
        pdf_bytes = core.render_pdf_bytes(note)
    except Exception as exc:  # pragma: no cover - runtime guard
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    filename = "bon_livraison.pdf"
    response = StreamingResponse(
        io.BytesIO(pdf_bytes),
        media_type="application/pdf",
    )
    response.headers["Content-Disposition"] = f'attachment; filename="{filename}"'
    return response


def run() -> None:
    """Entrypoint pratique pour `python api_server.py`."""
    import uvicorn

    uvicorn.run("api_server:app", host="0.0.0.0", port=8000, reload=False)


if __name__ == "__main__":  # pragma: no cover
    run()

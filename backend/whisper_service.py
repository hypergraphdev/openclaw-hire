#!/usr/bin/env python3
"""Whisper Web Service — shared speech-to-text for all instances.

Runs on the host machine, listens on port 8019.
Models are loaded once and kept in memory for fast inference.

Usage:
    python3 whisper_service.py                  # default: base model
    python3 whisper_service.py --model small    # use small model
    python3 whisper_service.py --port 8019      # custom port

API:
    POST /transcribe
        - multipart/form-data with 'file' field (audio file)
        - optional 'language' field (e.g., 'zh', 'en', 'ja')
        - optional 'model' field to override (tiny/base/small)
        - optional 'word_timestamps' field ("true" for word-level timestamps)
        - returns JSON: {"text": "...", "language": "...", "duration": 1.23, "segments": [...]}

    GET /health
        - returns model info and status

    GET /models
        - returns available models list
"""

import argparse
import os
import sys
import time
import tempfile
import logging
from pathlib import Path

# --- Logging ---
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [whisper] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger("whisper_service")

# --- Lazy import whisper (gives clear error if not installed) ---
try:
    import whisper
except ImportError:
    log.error("openai-whisper not installed. Run: pip install openai-whisper")
    sys.exit(1)

try:
    from fastapi import FastAPI, File, UploadFile, Form, HTTPException
    from fastapi.responses import JSONResponse
    import uvicorn
except ImportError:
    log.error("FastAPI/uvicorn not installed. Run: pip install fastapi uvicorn python-multipart")
    sys.exit(1)


# --- Config ---
ALLOWED_MODELS = {"tiny", "base", "small"}
CACHE_DIR = os.path.expanduser("~/.cache/whisper")
MAX_FILE_SIZE = 50 * 1024 * 1024  # 50MB
ALLOWED_EXTENSIONS = {".mp3", ".wav", ".m4a", ".ogg", ".flac", ".webm", ".mp4", ".mpeg", ".wma", ".aac"}

# --- Model cache (loaded once, stays in memory) ---
_models: dict[str, whisper.Whisper] = {}
_default_model_name = "base"


def _get_model(name: str) -> whisper.Whisper:
    """Get or load a whisper model. Cached in memory."""
    if name not in ALLOWED_MODELS:
        raise ValueError(f"Model '{name}' not allowed. Use: {', '.join(sorted(ALLOWED_MODELS))}")
    if name not in _models:
        log.info("Loading model '%s' ...", name)
        t0 = time.time()
        _models[name] = whisper.load_model(name)
        log.info("Model '%s' loaded in %.1fs", name, time.time() - t0)
    return _models[name]


def _available_models() -> list[dict]:
    """List models that are downloaded locally."""
    result = []
    for name in sorted(ALLOWED_MODELS):
        filename = f"{name}.pt"
        filepath = os.path.join(CACHE_DIR, filename)
        downloaded = os.path.exists(filepath)
        size_mb = os.path.getsize(filepath) / 1024 / 1024 if downloaded else 0
        result.append({
            "name": name,
            "downloaded": downloaded,
            "size_mb": round(size_mb),
            "loaded": name in _models,
        })
    return result


# --- FastAPI app ---
app = FastAPI(title="Whisper Transcription Service", version="1.0.0")


@app.get("/health")
def health():
    return {
        "status": "ok",
        "default_model": _default_model_name,
        "loaded_models": list(_models.keys()),
        "available_models": _available_models(),
    }


@app.get("/models")
def models():
    return {"models": _available_models()}


@app.post("/transcribe")
async def transcribe(
    file: UploadFile = File(...),
    language: str = Form(default=""),
    model: str = Form(default=""),
    word_timestamps: str = Form(default=""),
):
    """Transcribe an audio file using Whisper.

    Optional fields:
        - word_timestamps: "true" to include word-level timestamps in segments
    """
    # Validate file extension
    ext = Path(file.filename or "audio.mp3").suffix.lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(400, f"Unsupported format: {ext}. Supported: {', '.join(sorted(ALLOWED_EXTENSIONS))}")

    # Read file
    content = await file.read()
    if len(content) > MAX_FILE_SIZE:
        raise HTTPException(400, f"File too large: {len(content) / 1024 / 1024:.1f}MB (max {MAX_FILE_SIZE / 1024 / 1024:.0f}MB)")
    if len(content) == 0:
        raise HTTPException(400, "Empty file")

    # Select model
    model_name = model.strip() if model.strip() else _default_model_name
    if model_name not in ALLOWED_MODELS:
        raise HTTPException(400, f"Invalid model: {model_name}. Use: {', '.join(sorted(ALLOWED_MODELS))}")

    # Write to temp file (whisper needs a file path)
    with tempfile.NamedTemporaryFile(suffix=ext, delete=False) as tmp:
        tmp.write(content)
        tmp_path = tmp.name

    try:
        log.info("Transcribing %s (%s, %.1fMB, model=%s)",
                 file.filename, ext, len(content) / 1024 / 1024, model_name)

        t0 = time.time()
        m = _get_model(model_name)

        # Transcribe
        kwargs: dict = {}
        if language.strip():
            kwargs["language"] = language.strip()
        want_words = word_timestamps.strip().lower() in ("true", "1", "yes")
        if want_words:
            kwargs["word_timestamps"] = True

        result = m.transcribe(tmp_path, **kwargs)
        elapsed = time.time() - t0

        text = result.get("text", "").strip()
        detected_lang = result.get("language", "")

        log.info("Done in %.1fs, language=%s, text_len=%d", elapsed, detected_lang, len(text))

        resp_data: dict = {
            "text": text,
            "language": detected_lang,
            "duration": round(elapsed, 2),
            "model": model_name,
            "file_name": file.filename,
            "file_size": len(content),
        }

        # Always include segments (for callers that need timestamps)
        raw_segments = result.get("segments") or []
        resp_data["segments"] = [
            {
                "start": float(seg.get("start", 0) or 0),
                "end": float(seg.get("end", 0) or 0),
                "text": str(seg.get("text") or "").strip(),
                **({"words": [
                    {
                        "start": float(w.get("start", 0) or 0),
                        "end": float(w.get("end", 0) or 0),
                        "word": str(w.get("word") or "").strip(),
                    }
                    for w in (seg.get("words") or [])
                    if str(w.get("word") or "").strip()
                ]} if want_words else {}),
            }
            for seg in raw_segments
        ]

        return resp_data
    except Exception as e:
        log.error("Transcription failed: %s", e)
        raise HTTPException(500, f"Transcription failed: {e}")
    finally:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass


# --- Entrypoint ---
def main():
    parser = argparse.ArgumentParser(description="Whisper Web Service")
    parser.add_argument("--model", default="small", choices=sorted(ALLOWED_MODELS),
                        help="Default model to use (default: small)")
    parser.add_argument("--port", type=int, default=8019, help="Port (default: 8019)")
    parser.add_argument("--host", default="127.0.0.1", help="Host (default: 127.0.0.1)")
    parser.add_argument("--preload", action="store_true", help="Preload default model on startup")
    args = parser.parse_args()

    global _default_model_name
    _default_model_name = args.model

    if args.preload:
        log.info("Preloading model '%s' ...", args.model)
        _get_model(args.model)
        log.info("Ready.")

    log.info("Starting Whisper service on %s:%d (default model: %s)", args.host, args.port, args.model)
    uvicorn.run(app, host=args.host, port=args.port, log_level="warning")


if __name__ == "__main__":
    main()

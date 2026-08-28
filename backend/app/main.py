"""API FastAPI per la rimozione dello sfondo dalle immagini."""
from __future__ import annotations

import asyncio
import logging
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response

from .config import (
    ALLOWED_CONTENT_TYPES,
    AVAILABLE_MODELS,
    CORS_ORIGINS,
    DEFAULT_MODEL,
    MAX_CONCURRENCY,
    MAX_UPLOAD_BYTES,
    QUEUE_TIMEOUT_SECONDS,
)
from .services.removal import (
    ImageError,
    ImageTooLargeError,
    hex_to_rgba,
    remove_background,
    warmup,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("removebg")


# Slot di inferenza: creato nel lifespan, cosi' e' legato al loop applicativo.
_slots: asyncio.Semaphore | None = None


@asynccontextmanager
async def inference_slot():
    """Occupa uno slot di inferenza, o risponde 503 se la coda non si smaltisce.

    Senza freno ogni richiesta simultanea aggiunge ~500 MB al processo, e il
    picco raggiunto non viene piu' restituito al sistema operativo.
    """
    if _slots is None:
        raise RuntimeError("semaforo non inizializzato")
    try:
        await asyncio.wait_for(_slots.acquire(), timeout=QUEUE_TIMEOUT_SECONDS)
    except asyncio.TimeoutError:
        raise HTTPException(
            503,
            "Server occupato, riprova tra poco",
            headers={"Retry-After": "5"},
        ) from None
    try:
        yield
    finally:
        _slots.release()


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _slots
    _slots = asyncio.Semaphore(MAX_CONCURRENCY)
    # Cosi' la prima richiesta dell'utente non aspetta il download dei pesi.
    logger.info("Preparazione del modello %s...", DEFAULT_MODEL)
    await asyncio.to_thread(warmup, DEFAULT_MODEL)
    logger.info("Modello pronto (max %d inferenze simultanee)", MAX_CONCURRENCY)
    yield


app = FastAPI(
    title="Remove Background API",
    version="1.0.0",
    description="Carica un'immagine, ottieni un PNG senza sfondo.",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)


@app.exception_handler(RequestValidationError)
async def validation_error_handler(request: Request, exc: RequestValidationError):
    """Riduce il 422 di FastAPI alla stessa forma degli altri errori.

    FastAPI risponde con `detail` come lista di oggetti: un client che si aspetta
    una stringa mostrerebbe "[object Object]". Il dettaglio completo resta nei log.
    """
    campi = []
    for errore in exc.errors():
        posizione = ".".join(str(p) for p in errore.get("loc", ()) if p != "body")
        campi.append(f"{posizione or 'richiesta'}: {errore.get('msg', 'valore non valido')}")
    # I campi ricevuti dicono cosa ha spedito davvero il client (il form e' gia'
    # stato letto da FastAPI: qui si accede alla copia in cache).
    try:
        ricevuti = [
            f"{k}=<file {v.filename!r} {v.size or 0}B>" if hasattr(v, "filename") else f"{k}={v!r}"
            for k, v in (await request.form()).multi_items()
        ]
    except Exception:  # la diagnostica non deve mai far fallire la risposta
        ricevuti = ["(form non leggibile)"]
    logger.warning("Richiesta non valida: %s · campi ricevuti: %s", exc.errors(), ricevuti)
    return JSONResponse(
        status_code=422,
        content={"detail": "Richiesta non valida — " + "; ".join(campi)},
    )


@app.get("/api/health")
async def health():
    return {"status": "ok", "default_model": DEFAULT_MODEL}


@app.get("/api/models")
async def models():
    return {
        "default": DEFAULT_MODEL,
        "models": [{"id": k, "description": v} for k, v in AVAILABLE_MODELS.items()],
    }


@app.post("/api/remove-background")
async def remove_background_endpoint(
    file: UploadFile = File(..., description="Immagine da elaborare"),
    model: str = Form(DEFAULT_MODEL),
    alpha_matting: bool = Form(False),
    background: str | None = Form(None),
):
    """Restituisce l'immagine come PNG con lo sfondo rimosso."""
    if model not in AVAILABLE_MODELS:
        raise HTTPException(400, f"Modello non supportato: {model}")

    if file.content_type not in ALLOWED_CONTENT_TYPES:
        raise HTTPException(
            415,
            f"Tipo non supportato: {file.content_type}. "
            f"Ammessi: {', '.join(sorted(ALLOWED_CONTENT_TYPES))}",
        )

    bg = background or None
    if bg:
        try:
            hex_to_rgba(bg)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc

    data = await file.read()
    if not data:
        raise HTTPException(400, "File vuoto")
    if len(data) > MAX_UPLOAD_BYTES:
        raise HTTPException(
            413, f"File troppo grande (max {MAX_UPLOAD_BYTES // (1024 * 1024)} MB)"
        )

    queued = time.perf_counter()
    try:
        async with inference_slot():
            started = time.perf_counter()
            # L'inferenza e' CPU-bound e bloccante: fuori dall'event loop.
            png, size = await asyncio.to_thread(
                remove_background,
                data,
                model,
                alpha_matting=alpha_matting,
                background=bg,
            )
    except HTTPException:
        raise
    except ImageTooLargeError as exc:  # sottoclasse di ImageError: prima di quella
        raise HTTPException(413, str(exc)) from exc
    except ImageError as exc:
        raise HTTPException(400, str(exc)) from exc
    except Exception:
        logger.exception("Errore durante l'elaborazione di %s", file.filename)
        raise HTTPException(500, "Errore durante l'elaborazione dell'immagine")

    elapsed = time.perf_counter() - started
    waited = started - queued
    logger.info(
        "%s (%dx%d) elaborata con %s in %.2fs (attesa in coda %.2fs)",
        file.filename, *size, model, elapsed, waited,
    )

    return Response(
        content=png,
        media_type="image/png",
        headers={
            "Content-Disposition": 'inline; filename="no-background.png"',
            "X-Processing-Time": f"{elapsed:.2f}",
            "X-Image-Width": str(size[0]),
            "X-Image-Height": str(size[1]),
            "Access-Control-Expose-Headers": "X-Processing-Time, X-Image-Width, X-Image-Height",
        },
    )

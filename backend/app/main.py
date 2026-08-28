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
    ALLOWED_OUTPUT_FORMATS,
    AVAILABLE_MODELS,
    CORS_ORIGINS,
    DEFAULT_MODEL,
    MAX_CONCURRENCY,
    MAX_IMAGE_PIXELS,
    MAX_UPLOAD_BYTES,
    QUEUE_TIMEOUT_SECONDS,
)
from .services.removal import (
    ImageError,
    ImageTooLargeError,
    hex_to_rgba,
    modello_scaricato,
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
    description="Carica un'immagine, ottieni il soggetto ritagliato in PNG o WEBP.",
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
            f"{k}=<file {v.size or 0}B>" if hasattr(v, "filename") else f"{k}={v!r}"
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
    """Stato del servizio e limiti effettivi.

    Il client li legge da qui invece di ripeterli nel proprio codice: cambiando
    una variabile d'ambiente lato server, l'interfaccia si adegua da sola.
    """
    return {
        "status": "ok",
        "default_model": DEFAULT_MODEL,
        "limits": {
            "max_upload_bytes": MAX_UPLOAD_BYTES,
            "max_image_pixels": MAX_IMAGE_PIXELS,
            "content_types": sorted(ALLOWED_CONTENT_TYPES),
            "formats": sorted(ALLOWED_OUTPUT_FORMATS),
        },
    }


@app.get("/api/models")
async def models():
    return {
        "default": DEFAULT_MODEL,
        "models": [
            {
                "id": nome,
                "description": descrizione,
                "size_mb": peso,
                "downloaded": modello_scaricato(nome),
            }
            for nome, (descrizione, peso) in AVAILABLE_MODELS.items()
        ],
    }


@app.post("/api/remove-background")
async def remove_background_endpoint(
    file: UploadFile = File(..., description="Immagine da elaborare"),
    model: str = Form(DEFAULT_MODEL),
    alpha_matting: bool = Form(False),
    background: str | None = Form(None),
    format: str = Form("png"),
    trim: bool = Form(False),
):
    """Restituisce l'immagine con lo sfondo rimosso, in PNG o WEBP."""
    if model not in AVAILABLE_MODELS:
        raise HTTPException(400, f"Modello non supportato: {model}")

    formato = format.lower()
    if formato not in ALLOWED_OUTPUT_FORMATS:
        raise HTTPException(
            400,
            f"Formato di uscita non supportato: {format}. "
            f"Ammessi: {', '.join(sorted(ALLOWED_OUTPUT_FORMATS))}",
        )

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

    # Il download dei pesi (fino a 973 MB) avviene PRIMA di occupare uno slot:
    # dentro lo slot bloccherebbe per minuti una delle poche corsie di inferenza,
    # facendo scadere in coda tutte le altre richieste.
    try:
        await asyncio.to_thread(warmup, model)
    except Exception:
        logger.exception("Impossibile preparare il modello %s", model)
        raise HTTPException(503, f"Modello {model} non disponibile, riprova")

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
                output_format=formato,
                trim=trim,
            )
    except HTTPException:
        raise
    except ImageTooLargeError as exc:  # sottoclasse di ImageError: prima di quella
        raise HTTPException(413, str(exc)) from exc
    except ImageError as exc:
        raise HTTPException(400, str(exc)) from exc
    except Exception:
        logger.exception(
            "Errore su un'immagine %s di %d byte", file.content_type, len(data)
        )
        raise HTTPException(500, "Errore durante l'elaborazione dell'immagine")

    elapsed = time.perf_counter() - started
    waited = started - queued
    # Il nome del file non finisce nei log: e' un dato dell'utente (puo' contenere
    # nomi, diagnosi, numeri di contratto) e per il debug bastano peso e tempi.
    logger.info(
        "immagine %dx%d elaborata con %s in %.2fs -> %s di %.1f MB (attesa in coda %.2fs)",
        *size, model, elapsed, formato, len(png) / 1e6, waited,
    )

    return Response(
        content=png,
        media_type=ALLOWED_OUTPUT_FORMATS[formato],
        headers={
            "Content-Disposition": f'inline; filename="no-background.{formato}"',
            "X-Processing-Time": f"{elapsed:.2f}",
            "X-Image-Width": str(size[0]),
            "X-Image-Height": str(size[1]),
            "Access-Control-Expose-Headers": "X-Processing-Time, X-Image-Width, X-Image-Height",
        },
    )

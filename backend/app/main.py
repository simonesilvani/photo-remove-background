"""API FastAPI per la rimozione dello sfondo dalle immagini."""
from __future__ import annotations

import asyncio
import io
import json
import logging
import time
import zipfile
from pathlib import PurePath
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
    MAX_BATCH_FILES,
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


def _valida_opzioni(model: str, format: str, background: str | None) -> tuple[str, str | None]:
    """Controlla le opzioni comuni ai due endpoint. Restituisce (formato, sfondo)."""
    if model not in AVAILABLE_MODELS:
        raise HTTPException(400, f"Modello non supportato: {model}")

    formato = format.lower()
    if formato not in ALLOWED_OUTPUT_FORMATS:
        raise HTTPException(
            400,
            f"Formato di uscita non supportato: {format}. "
            f"Ammessi: {', '.join(sorted(ALLOWED_OUTPUT_FORMATS))}",
        )

    bg = background or None
    if bg:
        try:
            hex_to_rgba(bg)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
    return formato, bg


async def _leggi_immagine(file: UploadFile) -> bytes:
    if file.content_type not in ALLOWED_CONTENT_TYPES:
        raise HTTPException(
            415,
            f"Tipo non supportato: {file.content_type}. "
            f"Ammessi: {', '.join(sorted(ALLOWED_CONTENT_TYPES))}",
        )
    data = await file.read()
    if not data:
        raise HTTPException(400, "File vuoto")
    if len(data) > MAX_UPLOAD_BYTES:
        raise HTTPException(
            413, f"File troppo grande (max {MAX_UPLOAD_BYTES // (1024 * 1024)} MB)"
        )
    return data


async def _prepara_modello(model: str) -> None:
    """Scarica i pesi PRIMA di occupare uno slot: dentro lo slot bloccherebbe
    per minuti una delle poche corsie di inferenza, facendo scadere in coda
    tutte le altre richieste."""
    try:
        await asyncio.to_thread(warmup, model)
    except Exception:
        logger.exception("Impossibile preparare il modello %s", model)
        raise HTTPException(503, f"Modello {model} non disponibile, riprova")


async def _elabora(
    data: bytes, model: str, **opzioni
) -> tuple[bytes, tuple[int, int], float]:
    """Una singola immagine dentro uno slot di inferenza.

    Restituisce anche i secondi passati in coda, utili nei log per distinguere
    "il server e' lento" da "il server e' occupato".
    """
    in_coda = time.perf_counter()
    async with inference_slot():
        attesa = time.perf_counter() - in_coda
        try:
            # L'inferenza e' CPU-bound e bloccante: fuori dall'event loop.
            png, size = await asyncio.to_thread(remove_background, data, model, **opzioni)
            return png, size, attesa
        except ImageTooLargeError as exc:  # sottoclasse di ImageError: prima di quella
            raise HTTPException(413, str(exc)) from exc
        except ImageError as exc:
            raise HTTPException(400, str(exc)) from exc
        except Exception:
            logger.exception("Errore su un'immagine di %d byte", len(data))
            raise HTTPException(500, "Errore durante l'elaborazione dell'immagine")


def _nome_unico(nome: str, formato: str, usati: set[str]) -> str:
    """Nome del file dentro lo ZIP, senza percorsi e senza collisioni."""
    base = PurePath(nome or "immagine").name.rsplit(".", 1)[0] or "immagine"
    candidato = f"{base}.{formato}"
    contatore = 2
    while candidato in usati:
        candidato = f"{base}-{contatore}.{formato}"
        contatore += 1
    usati.add(candidato)
    return candidato


@app.post("/api/remove-background/batch")
async def remove_background_batch(
    files: list[UploadFile] = File(..., description="Immagini da elaborare"),
    model: str = Form(DEFAULT_MODEL),
    alpha_matting: bool = Form(False),
    background: str | None = Form(None),
    format: str = Form("png"),
    trim: bool = Form(False),
):
    """Elabora piu' immagini e restituisce uno ZIP.

    Ogni immagine passa per uno slot di inferenza separato, cosi' un blocco
    lungo non monopolizza il server: le richieste degli altri si incastrano fra
    una foto e l'altra. Un file che fallisce non annulla il resto: finisce in
    `errori.txt` dentro lo ZIP.
    """
    formato, bg = _valida_opzioni(model, format, background)
    if not files:
        raise HTTPException(400, "Nessun file caricato")
    if len(files) > MAX_BATCH_FILES:
        raise HTTPException(
            413, f"Troppe immagini: il massimo per richiesta e' {MAX_BATCH_FILES}"
        )

    await _prepara_modello(model)

    buffer = io.BytesIO()
    usati: set[str] = set()
    errori: list[str] = []
    manifest: list[dict[str, str]] = []
    riusciti = 0
    inizio = time.perf_counter()

    # ZIP_STORED e non deflate: PNG e WEBP sono gia' compressi, comprimerli di
    # nuovo costerebbe CPU per un guadagno nullo.
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_STORED) as zip_file:
        for file in files:
            nome = file.filename or "immagine"
            try:
                data = await _leggi_immagine(file)
                png, _size, _attesa = await _elabora(
                    data,
                    model,
                    alpha_matting=alpha_matting,
                    background=bg,
                    output_format=formato,
                    trim=trim,
                )
            except HTTPException as exc:
                errori.append(f"{nome}: {exc.detail}")
                continue
            voce = _nome_unico(nome, formato, usati)
            zip_file.writestr(voce, png)
            manifest.append({"origine": nome, "file": voce})
            riusciti += 1

        # Il manifest lega ogni risultato alla foto di partenza: i nomi dentro
        # lo ZIP sono normalizzati e deduplicati, quindi da soli non basterebbero
        # a ricostruire la corrispondenza.
        zip_file.writestr(
            "manifest.json",
            json.dumps({"risultati": manifest, "errori": errori}, ensure_ascii=False, indent=1),
        )
        if errori:
            zip_file.writestr("errori.txt", "\n".join(errori) + "\n")

    if not riusciti:
        raise HTTPException(400, "Nessuna immagine elaborata. " + " · ".join(errori))

    logger.info(
        "blocco di %d immagini: %d elaborate, %d scartate, in %.2fs",
        len(files), riusciti, len(errori), time.perf_counter() - inizio,
    )
    return Response(
        content=buffer.getvalue(),
        media_type="application/zip",
        headers={
            "Content-Disposition": 'attachment; filename="senza-sfondo.zip"',
            "X-Processed": str(riusciti),
            "X-Skipped": str(len(errori)),
            "Access-Control-Expose-Headers": "X-Processed, X-Skipped",
        },
    )


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
    formato, bg = _valida_opzioni(model, format, background)
    data = await _leggi_immagine(file)
    await _prepara_modello(model)

    inizio = time.perf_counter()
    png, size, waited = await _elabora(
        data,
        model,
        alpha_matting=alpha_matting,
        background=bg,
        output_format=formato,
        trim=trim,
    )
    elapsed = time.perf_counter() - inizio - waited
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

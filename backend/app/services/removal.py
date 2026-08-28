"""Rimozione dello sfondo da un'immagine, basata su rembg + onnxruntime."""
from __future__ import annotations

import io
import logging
import pathlib
from functools import lru_cache
from typing import Optional, Tuple

import onnxruntime as ort
import pillow_heif
from PIL import Image, ImageOps, UnidentifiedImageError
from PIL.Image import DecompressionBombError
from rembg import new_session, remove
from rembg.sessions import sessions_class

from ..config import (
    MAX_IMAGE_PIXELS,
    MAX_INFERENCE_SIDE,
    USE_ACCELERATION,
    WEBP_QUALITY,
)

logger = logging.getLogger("removebg")

# Insegna a Pillow ad aprire HEIC/HEIF/AVIF: e' il formato predefinito delle
# foto iPhone, che altrimenti verrebbero rifiutate.
pillow_heif.register_heif_opener()


class ImageError(ValueError):
    """L'immagine caricata non e' leggibile o non e' un'immagine."""


class ImageTooLargeError(ImageError):
    """L'immagine decodificata supera il tetto di pixel ammesso."""


def _providers() -> list[str]:
    """Acceleratore disponibile, con ricaduta sempre sulla CPU."""
    if USE_ACCELERATION:
        disponibili = ort.get_available_providers()
        for acceleratore in ("CUDAExecutionProvider", "CoreMLExecutionProvider"):
            if acceleratore in disponibili:
                return [acceleratore, "CPUExecutionProvider"]
    return ["CPUExecutionProvider"]


@lru_cache(maxsize=4)
def get_session(model: str):
    """Sessione onnxruntime per un modello, creata una sola volta.

    Il primo utilizzo di un modello ne scarica i pesi in ~/.rembg/models.
    """
    providers = _providers()
    logger.info("Modello %s su %s", model, providers[0])
    return new_session(model, providers=providers)


_CLASSI_SESSIONE = {c.name(): c for c in sessions_class}


def modello_scaricato(model: str) -> bool:
    """True se i pesi sono gia' sul disco.

    Serve a dire all'utente, prima che prema il pulsante, che quel modello
    costera' un download di centinaia di MB.
    """
    classe = _CLASSI_SESSIONE.get(model)
    if classe is None:
        return False
    cartella = pathlib.Path(classe.model_dir())
    return cartella.is_dir() and any(cartella.glob("*.onnx"))


def warmup(model: str) -> None:
    """Pre-carica un modello per evitare che la prima richiesta paghi il download."""
    get_session(model)


def load_image(data: bytes) -> Image.Image:
    try:
        img = Image.open(io.BytesIO(data))
        # Image.open legge solo l'intestazione: le dimensioni sono note prima che
        # i pixel vengano allocati, ed e' qui che va fermata un'immagine enorme.
        pixels = img.width * img.height
        if pixels > MAX_IMAGE_PIXELS:
            raise ImageTooLargeError(
                f"Immagine troppo grande: {pixels / 1e6:.0f} Mpixel "
                f"({img.width}x{img.height}), il limite e' "
                f"{MAX_IMAGE_PIXELS // 10**6} Mpixel"
            )
        img.load()
    except DecompressionBombError as exc:
        raise ImageTooLargeError(
            "Immagine troppo grande: dimensioni decodificate fuori scala"
        ) from exc
    except (UnidentifiedImageError, OSError) as exc:
        raise ImageError("File non riconosciuto come immagine valida") from exc

    # Orientamento EXIF (altrimenti le foto da smartphone escono ruotate) applicato
    # sul posto, e conversione solo se necessaria: a 12 MP ogni copia inutile
    # dell'immagine costa ~37 MB.
    ImageOps.exif_transpose(img, in_place=True)
    return img if img.mode == "RGB" else img.convert("RGB")


def hex_to_rgba(value: str) -> Tuple[int, int, int, int]:
    """Converte '#RRGGBB' o '#RRGGBBAA' in una tupla RGBA."""
    v = value.strip().lstrip("#")
    if len(v) == 3:
        v = "".join(c * 2 for c in v)
    if len(v) == 6:
        v += "ff"
    if len(v) != 8:
        raise ValueError(f"Colore non valido: {value}")
    try:
        return tuple(int(v[i : i + 2], 16) for i in (0, 2, 4, 6))  # type: ignore[return-value]
    except ValueError as exc:
        raise ValueError(f"Colore non valido: {value}") from exc


def _scaled_for_inference(img: Image.Image) -> Image.Image:
    """Riduce l'immagine se troppo grande: l'inferenza (e soprattutto l'alpha
    matting) su immagini enormi e' lenta senza guadagni reali di qualita'."""
    longest = max(img.size)
    if longest <= MAX_INFERENCE_SIDE:
        return img
    ratio = MAX_INFERENCE_SIDE / longest
    size = (max(1, round(img.width * ratio)), max(1, round(img.height * ratio)))
    return img.resize(size, Image.LANCZOS)


def remove_background(
    data: bytes,
    model: str,
    *,
    alpha_matting: bool = False,
    post_process: bool = True,
    background: Optional[str] = None,
    output_format: str = "png",
) -> Tuple[bytes, Tuple[int, int]]:
    """Restituisce (immagine senza sfondo, dimensioni originali).

    `background` e' un colore esadecimale opzionale: se assente lo sfondo
    resta trasparente, altrimenti il soggetto viene composto su quel colore.
    """
    original = load_image(data)
    working = _scaled_for_inference(original)

    cutout = remove(
        working,
        session=get_session(model),
        alpha_matting=alpha_matting,
        post_process_mask=post_process,
    )
    if not isinstance(cutout, Image.Image):  # difensivo: remove() e' polimorfa
        cutout = Image.open(io.BytesIO(cutout))
    cutout = cutout.convert("RGBA")

    # La maschera viene calcolata sull'immagine ridotta ma applicata
    # all'originale, cosi' il risultato mantiene la risoluzione di partenza.
    alpha = cutout.getchannel("A")
    if alpha.size != original.size:
        alpha = alpha.resize(original.size, Image.LANCZOS)

    # putalpha su un'immagine RGB la converte in RGBA sul posto: evita di
    # duplicare l'originale (49 MB a 12 MP).
    original.putalpha(alpha)
    result = original

    if background:
        canvas = Image.new("RGBA", result.size, hex_to_rgba(background))
        canvas.alpha_composite(result)
        result = canvas

    buffer = io.BytesIO()
    if output_format == "webp":
        # alpha_quality=100 tiene la trasparenza senza perdita: i bordi del
        # ritaglio restano netti, la compressione agisce solo sui colori.
        result.save(buffer, format="WEBP", quality=WEBP_QUALITY, alpha_quality=100)
    else:
        # Niente optimize=True: su una foto da 12 MP costava 5,0 s contro gli 0,9 s
        # della compressione di default, per il 6% di byte risparmiati.
        result.save(buffer, format="PNG")
    return buffer.getvalue(), original.size

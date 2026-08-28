"""Rimozione dello sfondo da un'immagine, basata su rembg + onnxruntime."""
from __future__ import annotations

import io
from functools import lru_cache
from typing import Optional, Tuple

from PIL import Image, ImageOps, UnidentifiedImageError
from PIL.Image import DecompressionBombError
from rembg import new_session, remove

from ..config import MAX_IMAGE_PIXELS, MAX_INFERENCE_SIDE


class ImageError(ValueError):
    """L'immagine caricata non e' leggibile o non e' un'immagine."""


class ImageTooLargeError(ImageError):
    """L'immagine decodificata supera il tetto di pixel ammesso."""


@lru_cache(maxsize=4)
def get_session(model: str):
    """Sessione onnxruntime per un modello, creata una sola volta.

    Il primo utilizzo di un modello ne scarica i pesi in ~/.rembg/models.
    """
    return new_session(model)


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
    # Applica l'orientamento EXIF, altrimenti le foto da smartphone escono ruotate.
    return ImageOps.exif_transpose(img).convert("RGB")


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
) -> Tuple[bytes, Tuple[int, int]]:
    """Restituisce (PNG con sfondo rimosso, dimensioni originali).

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

    result = original.convert("RGBA")
    result.putalpha(alpha)

    if background:
        canvas = Image.new("RGBA", result.size, hex_to_rgba(background))
        canvas.alpha_composite(result)
        result = canvas

    buffer = io.BytesIO()
    # Niente optimize=True: su una foto da 12 MP costava 5,0 s contro gli 0,9 s
    # della compressione di default, per il 6% di byte risparmiati.
    result.save(buffer, format="PNG")
    return buffer.getvalue(), original.size

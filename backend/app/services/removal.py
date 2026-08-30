"""Rimozione dello sfondo da un'immagine, basata su rembg + onnxruntime."""
from __future__ import annotations

import io
import logging
import pathlib
import threading
from functools import lru_cache
from typing import Optional, Tuple

import onnxruntime as ort
import pillow_heif
from PIL import Image, ImageOps, UnidentifiedImageError
from PIL.Image import DecompressionBombError
from rembg import new_session, remove
from rembg.sessions import sessions_class

from ..config import (
    CLEAR_INVISIBLE,
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
def _crea_sessione(model: str):
    providers = _providers()
    logger.info("Modello %s su %s", model, providers[0])
    return new_session(model, providers=providers)


_lock_registro = threading.Lock()
_lock_modello: dict[str, threading.Lock] = {}


def get_session(model: str):
    """Sessione onnxruntime per un modello, creata una sola volta.

    Il primo utilizzo di un modello ne scarica i pesi in ~/.rembg/models.
    `lru_cache` da solo non basta: non impedisce a due richieste simultanee di
    entrare insieme nella funzione e far partire due download dello stesso file
    (fino a 973 MB, che si sovrascriverebbero a vicenda). Il lock e' per modello,
    cosi' chi ne usa uno gia' in cache non aspetta il download di un altro.
    """
    with _lock_registro:
        lock = _lock_modello.setdefault(model, threading.Lock())
    with lock:
        return _crea_sessione(model)


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


# Sotto questa opacita' un pixel e' considerato sfondo: evita che un alone
# quasi invisibile ai bordi della maschera allarghi il ritaglio.
SOGLIA_RITAGLIO = 10


def riquadro_soggetto(alpha: Image.Image) -> Optional[Tuple[int, int, int, int]]:
    """Riquadro che contiene il soggetto, o None se la maschera e' tutta vuota."""
    return alpha.point(lambda v: 255 if v > SOGLIA_RITAGLIO else 0).getbbox()


def remove_background(
    data: bytes,
    model: str,
    *,
    alpha_matting: bool = False,
    post_process: bool = True,
    background: Optional[str] = None,
    output_format: str = "png",
    trim: bool = False,
) -> Tuple[bytes, Tuple[int, int]]:
    """Restituisce (immagine senza sfondo, dimensioni del risultato).

    `background` e' un colore esadecimale opzionale: se assente lo sfondo
    resta trasparente, altrimenti il soggetto viene composto su quel colore.
    Con `trim` il risultato viene ritagliato al riquadro del soggetto, togliendo
    i margini trasparenti che altrimenti pesano su file e tempi.
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
        # BILINEAR e non LANCZOS: su una maschera i filtri a finestra larga
        # oscillano oltre lo 0 e il 255, e il taglio di quei valori lascia un
        # alone lungo tutti i bordi (misurati 2.640 pixel schiacciati su una
        # foto da 2400x1800; con BILINEAR sono zero).
        alpha = alpha.resize(original.size, Image.BILINEAR)

    # putalpha su un'immagine RGB la converte in RGBA sul posto: evita di
    # duplicare l'originale (49 MB a 12 MP).
    original.putalpha(alpha)
    result = original

    # Sotto i pixel invisibili resterebbe lo sfondo originale, intatto e
    # recuperabile rimettendo l'opacita' a 255: azzerarlo lo elimina davvero,
    # e alleggerisce molto il file senza toccare un pixel visibile.
    if CLEAR_INVISIBLE:
        invisibili = alpha.point(lambda v: 255 if v == 0 else 0)
        result.paste((0, 0, 0, 0), mask=invisibili)

    # Il profilo colore va portato a mano fino al salvataggio: la tela dello
    # sfondo nasce senza, e l'encoder WEBP non lo scrive se non glielo si passa.
    # Senza, una foto Display P3 (tutte quelle da iPhone) viene riletta come
    # sRGB e i colori si spostano visibilmente.
    profilo = original.info.get("icc_profile")

    # Il ritaglio va calcolato prima di comporre lo sfondo: dopo, l'alpha e'
    # opaca ovunque e il riquadro coinciderebbe con l'immagine intera.
    if trim:
        riquadro = riquadro_soggetto(alpha)
        if riquadro:
            result = result.crop(riquadro)

    if background:
        canvas = Image.new("RGBA", result.size, hex_to_rgba(background))
        canvas.alpha_composite(result)
        result = canvas

    buffer = io.BytesIO()
    opzioni = {"icc_profile": profilo} if profilo else {}
    if output_format == "webp":
        # alpha_quality=100 tiene la trasparenza senza perdita: i bordi del
        # ritaglio restano netti, la compressione agisce solo sui colori.
        result.save(
            buffer, format="WEBP", quality=WEBP_QUALITY, alpha_quality=100, **opzioni
        )
    else:
        # Niente optimize=True: su una foto da 12 MP costava 5,0 s contro gli 0,9 s
        # della compressione di default, per il 6% di byte risparmiati.
        result.save(buffer, format="PNG", **opzioni)
    return buffer.getvalue(), result.size

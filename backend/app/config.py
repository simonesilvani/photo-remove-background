"""Configurazione dell'applicazione, sovrascrivibile via variabili d'ambiente."""
import os

DEFAULT_MODEL = os.getenv("RB_DEFAULT_MODEL", "u2net")

AVAILABLE_MODELS = {
    "u2net": "Generico, buon compromesso qualita'/velocita'",
    "u2netp": "Versione leggera di u2net, piu' veloce",
    "u2net_human_seg": "Ottimizzato per persone",
    "isnet-general-use": "Generico, bordi piu' precisi",
    "isnet-anime": "Illustrazioni e anime",
    "silueta": "u2net compresso (~43MB)",
    "birefnet-general": "Qualita' massima, piu' lento",
}

MAX_UPLOAD_BYTES = int(os.getenv("RB_MAX_UPLOAD_BYTES", 15 * 1024 * 1024))
ALLOWED_CONTENT_TYPES = {
    "image/png",
    "image/jpeg",
    "image/webp",
    "image/bmp",
    "image/tiff",
}

CORS_ORIGINS = os.getenv(
    "RB_CORS_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173"
).split(",")

# Tetto ai pixel *decodificati*: il limite in byte non protegge da niente, perche'
# un PNG da 400 KB puo' decodificare 121 Mpixel e occupare ~900 MB di RAM.
MAX_IMAGE_PIXELS = int(os.getenv("RB_MAX_IMAGE_PIXELS", 50_000_000))

# Ogni inferenza in corso costa ~500 MB su una foto da 12 MP: questo limite e'
# cio' che rende prevedibile la RAM del processo (411 MB a riposo + 500 MB per slot).
MAX_CONCURRENCY = int(os.getenv("RB_MAX_CONCURRENCY", 2))

# Quanto una richiesta attende il proprio turno prima di ricevere 503.
QUEUE_TIMEOUT_SECONDS = float(os.getenv("RB_QUEUE_TIMEOUT", 60))

# Oltre questa soglia l'inferenza gira su una copia ridotta e la maschera
# risultante viene riportata alla risoluzione originale.
MAX_INFERENCE_SIDE = int(os.getenv("RB_MAX_INFERENCE_SIDE", 2000))

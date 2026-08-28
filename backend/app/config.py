"""Configurazione dell'applicazione, sovrascrivibile via variabili d'ambiente."""
import os

DEFAULT_MODEL = os.getenv("RB_DEFAULT_MODEL", "u2net")

# id -> (descrizione, peso in MB da scaricare al primo utilizzo)
AVAILABLE_MODELS = {
    "u2net": ("Generico, buon compromesso qualita'/velocita'", 176),
    "u2netp": ("Versione leggera di u2net, piu' veloce", 5),
    "u2net_human_seg": ("Ottimizzato per persone", 176),
    "isnet-general-use": ("Generico, bordi piu' precisi", 179),
    "isnet-anime": ("Illustrazioni e anime", 176),
    "silueta": ("u2net compresso, stessa resa", 44),
    "birefnet-general": ("Qualita' massima, molto piu' lento", 973),
}

MAX_UPLOAD_BYTES = int(os.getenv("RB_MAX_UPLOAD_BYTES", 15 * 1024 * 1024))
ALLOWED_CONTENT_TYPES = {
    "image/png",
    "image/jpeg",
    "image/webp",
    "image/bmp",
    "image/tiff",
    # formato predefinito delle foto iPhone, letto grazie a pillow-heif
    "image/heic",
    "image/heif",
    "image/avif",
}

CORS_ORIGINS = os.getenv(
    "RB_CORS_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173"
).split(",")

# Acceleratore hardware quando disponibile (CoreML sui Mac Apple Silicon, CUDA
# con GPU NVIDIA): misurato 1,9x sull'inferenza. RB_ACCELERATION=0 forza la CPU.
USE_ACCELERATION = os.getenv("RB_ACCELERATION", "1") != "0"

# Formati di uscita. Il PNG e' senza perdita e universale, il WEBP produce file
# ~40 volte piu' leggeri in meta' del tempo: la trasparenza resta comunque senza
# perdita, la compressione agisce solo sui colori.
ALLOWED_OUTPUT_FORMATS = {"png": "image/png", "webp": "image/webp"}
WEBP_QUALITY = int(os.getenv("RB_WEBP_QUALITY", 92))

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

"""Configurazione dell'applicazione, sovrascrivibile via variabili d'ambiente."""
import os
import pathlib

DEFAULT_MODEL = os.getenv("RB_DEFAULT_MODEL", "u2net")

# id -> (descrizione, peso in MB da scaricare, lato dell'ingresso del modello)
#
# Il terzo valore e' la risoluzione a cui la rete guarda l'immagine, ed e' cio'
# che limita il dettaglio della maschera: a 320 px una ciocca di capelli non
# esiste proprio. Alzare la copia di lavoro non aiuta — la rete ridimensiona
# comunque al proprio ingresso — mentre passare a un modello da 1024 px si.
AVAILABLE_MODELS = {
    "u2net": ("Generico, buon compromesso qualita'/velocita'", 176, 320),
    "u2netp": ("Versione leggera di u2net, piu' veloce", 5, 320),
    "u2net_human_seg": ("Ottimizzato per persone", 176, 320),
    "isnet-general-use": ("Dettagli fini: capelli, rami, oggetti sottili", 179, 1024),
    "isnet-anime": ("Illustrazioni e anime", 176, 1024),
    "silueta": ("u2net compresso, stessa resa", 44, 320),
    "birefnet-general": ("Qualita' massima, molto piu' lento", 973, 1024),
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

# Frontend gia' compilato da servire insieme all'API. Se la cartella esiste,
# l'applicazione risponde su un solo indirizzo e non serve piu' il proxy di Vite.
STATIC_DIR = os.getenv(
    "RB_STATIC_DIR",
    str(pathlib.Path(__file__).resolve().parents[2] / "frontend" / "dist"),
)

# Immagini per richiesta in blocco. Lo ZIP viene composto in memoria per non
# scrivere le foto degli utenti su disco: il tetto serve a tenerla limitata.
MAX_BATCH_FILES = int(os.getenv("RB_MAX_BATCH_FILES", 10))

# Tetto al peso complessivo di una richiesta in blocco: il limite per singolo
# file non basta, perche' dieci file al massimo consentito sarebbero 150 MB da
# tenere in memoria contemporaneamente.
MAX_BATCH_BYTES = int(os.getenv("RB_MAX_BATCH_BYTES", 60 * 1024 * 1024))

# Acceleratore hardware quando disponibile (CoreML sui Mac Apple Silicon, CUDA
# con GPU NVIDIA): misurato 1,9x sull'inferenza. RB_ACCELERATION=0 forza la CPU.
USE_ACCELERATION = os.getenv("RB_ACCELERATION", "1") != "0"

# Come vengono trattati i bordi del ritaglio, dal piu' veloce al piu' curato.
# Sono gradini della stessa scala, non interruttori indipendenti: ogni livello
# comprende quello precedente.
EDGE_MODES = {
    "hard": "Bordi netti, i piu' rapidi: la maschera viene squadrata",
    "soft": "Bordi sfumati e senza alone del vecchio sfondo",
    "max": "Massima qualita' su capelli e pelo (alpha matting)",
}
DEFAULT_EDGES = os.getenv("RB_DEFAULT_EDGES", "hard")

# Azzera i colori sotto i pixel completamente trasparenti. Senza, lo sfondo
# "rimosso" resta dentro il file — basta rimettere alpha a 255 per rivederlo — e
# il PNG pesa molto di piu'. RB_CLEAR_INVISIBLE=0 lo disattiva.
CLEAR_INVISIBLE = os.getenv("RB_CLEAR_INVISIBLE", "1") != "0"

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

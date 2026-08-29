# Immagine unica: frontend compilato e API nello stesso processo, una sola porta.

# --- 1. compilazione del frontend
FROM node:20-alpine AS frontend
WORKDIR /frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

# --- 2. immagine finale
FROM python:3.13-slim
ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    RB_STATIC_DIR=/app/frontend/dist

WORKDIR /app
# Le dipendenze prima del codice: cambiando solo i sorgenti, questo strato
# resta in cache e la ricostruzione non riscarica 500 MB di pacchetti.
COPY backend/requirements.txt backend/requirements.txt
RUN pip install --no-cache-dir -r backend/requirements.txt

COPY backend/app backend/app
COPY --from=frontend /frontend/dist frontend/dist

# I pesi del modello (176 MB) non stanno nell'immagine: si scaricano al primo
# avvio in /root/.rembg. Montare un volume su quella cartella li conserva.
VOLUME ["/root/.rembg"]
EXPOSE 8000

# start-period ampio: al primo avvio il server scarica il modello prima di
# accettare richieste, e non deve risultare "malato" nel frattempo.
HEALTHCHECK --interval=30s --timeout=5s --start-period=300s \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/health')"

CMD ["uvicorn", "app.main:app", "--app-dir", "backend", "--host", "0.0.0.0", "--port", "8000"]

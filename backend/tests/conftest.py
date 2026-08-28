"""Fixture comuni: l'API viene provata senza caricare nessun modello.

I test coprono validazione e gestione degli errori, che si esauriscono prima
dell'inferenza: cosi' girano in un secondo e non serve scaricare i 176 MB dei
pesi ne' avere una GPU o una macchina veloce.
"""
import io

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from app import main


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(main, "warmup", lambda _model: None)
    with TestClient(main.app) as c:
        yield c


@pytest.fixture
def immagine():
    """Bytes di un JPEG minimo ma valido."""

    def _immagine(size=(60, 40), formato="JPEG"):
        buffer = io.BytesIO()
        Image.new("RGB", size, (30, 120, 220)).save(buffer, format=formato)
        return buffer.getvalue()

    return _immagine


def upload(client, contenuto, *, tipo="image/jpeg", nome="foto.jpg", **campi):
    return client.post(
        "/api/remove-background",
        files={"file": (nome, contenuto, tipo)},
        data=campi,
    )

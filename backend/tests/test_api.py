"""Validazione degli input e forma delle risposte dell'API."""
import io
import json
import zipfile

import pytest
from PIL import Image

from app import config, main
from app.services import removal
from tests.conftest import upload


def test_una_sola_creazione_di_sessione_sotto_concorrenza(monkeypatch):
    """Due richieste sullo stesso modello non devono scaricarlo due volte."""
    import threading
    import time

    creazioni = []

    def finta(model, **kwargs):
        creazioni.append(model)
        time.sleep(0.2)  # simula il download dei pesi
        return object()

    removal._crea_sessione.cache_clear()
    monkeypatch.setattr(removal, "new_session", finta)
    thread = [threading.Thread(target=removal.get_session, args=("u2net",)) for _ in range(4)]
    for t in thread:
        t.start()
    for t in thread:
        t.join()
    removal._crea_sessione.cache_clear()

    assert creazioni == ["u2net"]


def test_health(client):
    r = client.get("/api/health")
    assert r.status_code == 200
    corpo = r.json()
    assert corpo["status"] == "ok"
    assert corpo["default_model"] == config.DEFAULT_MODEL


def test_health_pubblica_i_limiti(client):
    """Il client li legge da qui invece di ripeterli nel proprio codice."""
    limiti = client.get("/api/health").json()["limits"]
    assert limiti["max_upload_bytes"] == config.MAX_UPLOAD_BYTES
    assert limiti["max_image_pixels"] == config.MAX_IMAGE_PIXELS
    assert "image/jpeg" in limiti["content_types"]
    assert set(limiti["formats"]) == set(config.ALLOWED_OUTPUT_FORMATS)


def test_models_elenca_il_default(client):
    corpo = client.get("/api/models").json()
    ids = [m["id"] for m in corpo["models"]]
    assert corpo["default"] in ids
    assert all(m["description"] for m in corpo["models"])


def test_models_dice_peso_e_stato_del_download(client):
    """Senza questi campi l'utente non sa che sceglierlo costa un download."""
    modelli = client.get("/api/models").json()["models"]
    assert all(isinstance(m["downloaded"], bool) for m in modelli)
    assert all(m["size_mb"] > 0 for m in modelli)
    # la risoluzione d'ingresso e' cio' che limita il dettaglio della maschera
    assert {m["input_px"] for m in modelli} <= {320, 1024}
    fine = next(m for m in modelli if m["id"] == "isnet-general-use")
    assert fine["input_px"] == 1024
    pesante = next(m for m in modelli if m["id"] == "birefnet-general")
    assert pesante["size_mb"] > 900


def test_immagine_valida(client, immagine, monkeypatch):
    """Percorso felice, con l'inferenza sostituita da uno stub."""
    monkeypatch.setattr(main, "remove_background", lambda *a, **k: (b"\x89PNG-finto", (60, 40)))

    r = upload(client, immagine())

    assert r.status_code == 200
    assert r.headers["content-type"] == "image/png"
    assert r.content == b"\x89PNG-finto"
    assert r.headers["X-Image-Width"] == "60"
    assert r.headers["X-Image-Height"] == "40"
    assert float(r.headers["X-Processing-Time"]) >= 0


@pytest.mark.parametrize("formato, tipo", [("png", "image/png"), ("webp", "image/webp")])
def test_formato_di_uscita(client, immagine, monkeypatch, formato, tipo):
    monkeypatch.setattr(main, "remove_background", lambda *a, **k: (b"finto", (60, 40)))
    r = upload(client, immagine(), format=formato)
    assert r.status_code == 200
    assert r.headers["content-type"] == tipo
    assert f"no-background.{formato}" in r.headers["content-disposition"]


@pytest.mark.parametrize(
    "campi, atteso, frammento",
    [
        ({"model": "inesistente"}, 400, "Modello non supportato"),
        ({"background": "non-un-colore"}, 400, "Colore non valido"),
        ({"format": "gif"}, 400, "Formato di uscita non supportato"),
        ({"edges": "morbidissimi"}, 400, "Trattamento dei bordi non supportato"),
    ],
)
def test_parametri_non_validi(client, immagine, campi, atteso, frammento):
    r = upload(client, immagine(), **campi)
    assert r.status_code == atteso
    assert frammento in r.json()["detail"]


def test_heic_delle_foto_iphone(client, monkeypatch):
    """Il formato predefinito delle foto iPhone deve essere accettato e letto."""
    import pillow_heif

    buffer = io.BytesIO()
    Image.new("RGB", (80, 60), (200, 150, 100)).save(buffer, format="HEIF")
    monkeypatch.setattr(main, "remove_background", lambda *a, **k: (b"finto", (80, 60)))
    r = upload(client, buffer.getvalue(), tipo="image/heic", nome="IMG_1234.HEIC")
    assert r.status_code == 200

    # e il decoder lo legge davvero, non solo il tipo dichiarato
    from app.services.removal import load_image

    assert load_image(buffer.getvalue()).size == (80, 60)


def test_i_tre_livelli_di_bordo_chiedono_cose_diverse(monkeypatch):
    """I livelli sono gradini della stessa scala: `soft` smette di squadrare la
    maschera e toglie l'alone, `max` aggiunge l'alpha matting."""
    from app.services import removal

    ricevuti = {}

    def finto(img, **kwargs):
        ricevuti.update(kwargs)
        return Image.new("RGBA", img.size, (0, 0, 0, 255))

    sorgente = io.BytesIO()
    Image.new("RGB", (40, 40), (10, 200, 10)).save(sorgente, format="PNG")
    monkeypatch.setattr(removal, "get_session", lambda _m: None)
    monkeypatch.setattr(removal, "remove", finto)

    removal.remove_background(sorgente.getvalue(), "u2net", edges="soft")
    assert (ricevuti["post_process_mask"], ricevuti["decontaminate"], ricevuti["alpha_matting"]) == (
        False, True, False,
    )

    removal.remove_background(sorgente.getvalue(), "u2net", edges="max")
    assert ricevuti["alpha_matting"] is True
    assert ricevuti["post_process_mask"] is False

    removal.remove_background(sorgente.getvalue(), "u2net")
    assert (ricevuti["post_process_mask"], ricevuti["decontaminate"], ricevuti["alpha_matting"]) == (
        True, False, False,
    )


def test_sui_bordi_sfumati_i_colori_arrivano_dalla_stima(monkeypatch):
    """Il colore dei pixel misti deve venire dal ritaglio, dove l'alone e' gia'
    stato tolto, non dall'originale che lo contiene ancora."""
    from app.services import removal

    sorgente = io.BytesIO()
    Image.new("RGB", (20, 20), (0, 255, 0)).save(sorgente, format="PNG")  # tutto verde

    def finto(img, **kwargs):
        # ritaglio con colori "puliti" (rosso) e una fascia semitrasparente
        fuori = Image.new("RGBA", img.size, (255, 0, 0, 255))
        fuori.putalpha(Image.new("L", img.size, 128))
        return fuori

    monkeypatch.setattr(removal, "get_session", lambda _m: None)
    monkeypatch.setattr(removal, "remove", finto)
    uscita, _ = removal.remove_background(sorgente.getvalue(), "u2net", edges="soft")

    pixel = Image.open(io.BytesIO(uscita)).convert("RGBA").load()[10, 10]
    assert pixel[3] == 128, "la sfumatura deve sopravvivere"
    assert pixel[0] > 200 and pixel[1] < 60, f"colore preso dall'originale verde: {pixel}"


def test_sotto_i_pixel_trasparenti_non_resta_lo_sfondo(monkeypatch):
    """In un PNG i pixel invisibili hanno comunque un colore: se ci resta lo
    sfondo originale, basta rimettere l'opacità a 255 per rivederlo."""
    from app.services import removal

    sorgente = io.BytesIO()
    Image.new("RGB", (40, 40), (18, 220, 60)).save(sorgente, format="PNG")

    def maschera(img, **kwargs):
        fuori = Image.new("RGBA", img.size, (0, 0, 0, 0))
        fuori.paste((0, 0, 0, 255), (10, 10, 30, 30))
        return fuori

    monkeypatch.setattr(removal, "get_session", lambda _m: None)
    monkeypatch.setattr(removal, "remove", maschera)
    uscita, _ = removal.remove_background(sorgente.getvalue(), "u2net")

    pixel = Image.open(io.BytesIO(uscita)).convert("RGBA").load()
    assert pixel[2, 2][3] == 0, "il pixel d'angolo doveva restare trasparente"
    assert pixel[2, 2][:3] == (0, 0, 0), "sotto la trasparenza c'e' ancora lo sfondo"
    assert pixel[20, 20][:3] == (18, 220, 60), "il soggetto non deve essere toccato"


def test_il_profilo_colore_sopravvive(monkeypatch):
    """Una foto Display P3 riletta come sRGB cambia visibilmente colore."""
    from PIL import ImageCms

    from app.services import removal

    profilo = ImageCms.ImageCmsProfile(ImageCms.createProfile("sRGB")).tobytes()
    sorgente = io.BytesIO()
    Image.new("RGB", (60, 40), (200, 60, 40)).save(sorgente, format="JPEG", icc_profile=profilo)

    # niente modello: il test non deve caricare 176 MB di pesi
    monkeypatch.setattr(removal, "get_session", lambda _m: None)
    monkeypatch.setattr(
        removal, "remove", lambda img, **k: Image.new("RGBA", img.size, (0, 0, 0, 200))
    )
    for opzioni in ({}, {"background": "#ffffff"}, {"output_format": "webp"}, {"trim": True}):
        uscita, _ = removal.remove_background(sorgente.getvalue(), "u2net", **opzioni)
        assert Image.open(io.BytesIO(uscita)).info.get("icc_profile"), opzioni


def test_la_maschera_si_ingrandisce_senza_aloni():
    """I filtri a finestra larga oscillano oltre 0 e 255: il taglio di quei
    valori lascia un contorno visibile lungo tutti i bordi del ritaglio."""
    from PIL import Image as PILImage

    maschera = PILImage.new("F", (60, 60), 0.0)
    maschera.paste(255.0, (20, 20, 40, 40))
    import numpy as np

    grande = np.asarray(maschera.resize((480, 480), PILImage.BILINEAR))
    assert grande.min() >= -0.01 and grande.max() <= 255.01


def test_riquadro_del_soggetto():
    """Il ritaglio segue il soggetto e ignora gli aloni quasi invisibili."""
    from app.services.removal import riquadro_soggetto

    vuota = Image.new("L", (100, 100), 0)
    assert riquadro_soggetto(vuota) is None  # niente soggetto, niente ritaglio

    con_alone = Image.new("L", (100, 100), 5)  # alone impercettibile ovunque
    con_alone.paste(255, (40, 30, 60, 70))  # soggetto vero
    assert riquadro_soggetto(con_alone) == (40, 30, 60, 70)


def test_trim_arriva_al_servizio(client, immagine, monkeypatch):
    ricevuti = {}

    def finta(*args, **kwargs):
        ricevuti.update(kwargs)
        return b"finto", (10, 20)

    monkeypatch.setattr(main, "remove_background", finta)
    assert upload(client, immagine(), trim="true").status_code == 200
    assert ricevuti["trim"] is True
    assert upload(client, immagine(), trim="false").status_code == 200
    assert ricevuti["trim"] is False


def test_blocco_restituisce_uno_zip(client, immagine, monkeypatch):
    monkeypatch.setattr(main, "remove_background", lambda *a, **k: (b"finto", (10, 20)))
    r = client.post(
        "/api/remove-background/batch",
        files=[
            ("files", ("a.jpg", immagine(), "image/jpeg")),
            ("files", ("b.jpg", immagine(), "image/jpeg")),
        ],
        data={"format": "webp"},
    )
    assert r.status_code == 200
    assert r.headers["content-type"] == "application/zip"
    assert r.headers["X-Processed"] == "2"
    with zipfile.ZipFile(io.BytesIO(r.content)) as z:
        assert sorted(n for n in z.namelist() if n != "manifest.json") == ["a.webp", "b.webp"]
        manifest = json.loads(z.read("manifest.json"))
    # il manifest lega ogni risultato alla foto di partenza
    assert manifest["risultati"] == [
        {"origine": "a.jpg", "file": "a.webp"},
        {"origine": "b.jpg", "file": "b.webp"},
    ]
    assert manifest["errori"] == []


def test_blocco_non_si_ferma_al_primo_errore(client, immagine, monkeypatch):
    """Un file rotto non deve annullare il lavoro sugli altri."""
    monkeypatch.setattr(main, "remove_background", lambda *a, **k: (b"finto", (10, 20)))
    r = client.post(
        "/api/remove-background/batch",
        files=[
            ("files", ("buona.jpg", immagine(), "image/jpeg")),
            ("files", ("appunti.txt", b"non sono un'immagine", "text/plain")),
        ],
    )
    assert r.status_code == 200
    assert (r.headers["X-Processed"], r.headers["X-Skipped"]) == ("1", "1")
    with zipfile.ZipFile(io.BytesIO(r.content)) as z:
        assert "buona.png" in z.namelist()
        assert "appunti.txt" not in z.namelist()  # non deve entrare l'originale
        assert "text/plain" in z.read("errori.txt").decode()


def test_blocco_evita_le_collisioni_di_nome(client, immagine, monkeypatch):
    monkeypatch.setattr(main, "remove_background", lambda *a, **k: (b"finto", (10, 20)))
    r = client.post(
        "/api/remove-background/batch",
        files=[
            ("files", ("foto.jpg", immagine(), "image/jpeg")),
            ("files", ("foto.png", immagine(), "image/png")),
            ("files", ("cartella/foto.jpg", immagine(), "image/jpeg")),
        ],
    )
    with zipfile.ZipFile(io.BytesIO(r.content)) as z:
        assert sorted(n for n in z.namelist() if n != "manifest.json") == [
            "foto-2.png",
            "foto-3.png",
            "foto.png",
        ]


def test_blocco_rifiuta_troppi_file(client, immagine, monkeypatch):
    monkeypatch.setattr(main, "MAX_BATCH_FILES", 2)
    r = client.post(
        "/api/remove-background/batch",
        files=[("files", (f"{i}.jpg", immagine(), "image/jpeg")) for i in range(3)],
    )
    assert r.status_code == 413
    assert "massimo" in r.json()["detail"]


def test_blocco_rifiuta_invii_troppo_pesanti(client, immagine, monkeypatch):
    """Il limite per singolo file non basta: dieci al massimo consentito
    sarebbero 150 MB da tenere in memoria insieme."""
    monkeypatch.setattr(main, "MAX_BATCH_BYTES", 100)
    r = client.post(
        "/api/remove-background/batch",
        files=[("files", ("a.jpg", immagine(), "image/jpeg"))],
    )
    assert r.status_code == 413
    assert "troppo pesante" in r.json()["detail"]


def test_blocco_fallisce_se_nessuna_immagine_e_valida(client):
    r = client.post(
        "/api/remove-background/batch",
        files=[("files", ("a.txt", b"testo", "text/plain"))],
    )
    assert r.status_code == 400
    assert "Nessuna immagine elaborata" in r.json()["detail"]


def test_tipo_non_supportato(client):
    r = upload(client, b"non sono un'immagine", tipo="text/plain", nome="note.txt")
    assert r.status_code == 415
    assert "text/plain" in r.json()["detail"]


def test_file_vuoto(client):
    assert upload(client, b"").status_code == 400


def test_file_non_riconosciuto(client):
    r = upload(client, b"\xff\xd8\xff" + b"spazzatura" * 10)
    assert r.status_code == 400
    assert "non riconosciuto" in r.json()["detail"]


def test_upload_oltre_il_limite(client, immagine, monkeypatch):
    monkeypatch.setattr(main, "MAX_UPLOAD_BYTES", 100)
    r = upload(client, immagine((400, 400)))
    assert r.status_code == 413
    assert "troppo grande" in r.json()["detail"]


def test_troppi_pixel(client, immagine, monkeypatch):
    """Il tetto e' sui pixel decodificati, non sui byte caricati."""
    monkeypatch.setattr(removal, "MAX_IMAGE_PIXELS", 1_000)
    r = upload(client, immagine((100, 100)))  # 10.000 pixel in pochi KB
    assert r.status_code == 413
    assert "Mpixel" in r.json()["detail"]


def test_bomba_di_decompressione(client, monkeypatch):
    """Un PNG minuscolo che dichiara dimensioni assurde non deve dare 500."""
    monkeypatch.setattr(Image, "MAX_IMAGE_PIXELS", 1_000)
    buffer = io.BytesIO()
    Image.new("RGB", (2000, 2000)).save(buffer, format="PNG")
    r = upload(client, buffer.getvalue(), tipo="image/png", nome="bomba.png")
    assert r.status_code == 413


def test_il_detail_e_sempre_una_stringa(client, immagine):
    """Regressione: FastAPI restituirebbe una lista di oggetti sui 422, e
    l'interfaccia mostrerebbe "[object Object]" invece del messaggio."""
    senza_file = client.post("/api/remove-background", data={"model": "u2net"})
    assert senza_file.status_code == 422
    assert isinstance(senza_file.json()["detail"], str)

    booleano_sbagliato = upload(client, immagine(), trim="forse")
    assert booleano_sbagliato.status_code == 422
    assert "trim" in booleano_sbagliato.json()["detail"]


def test_i_log_non_contengono_il_nome_del_file(client, immagine, monkeypatch, caplog):
    """Il nome e' un dato dell'utente: non deve finire nei log."""
    monkeypatch.setattr(main, "remove_background", lambda *a, **k: (b"png", (60, 40)))
    with caplog.at_level("INFO"):
        upload(client, immagine(), nome="referto-mario-rossi.jpg")
    assert "referto-mario-rossi" not in caplog.text
    assert "60x40" in caplog.text

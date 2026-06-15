# demos.py — Solicitudes de demo / contacto desde el landing de katia.work
# Persistencia simple en JSON, bajo el disco persistente (KATIA_DATA_DIR).
import os
import json
import secrets
from datetime import datetime

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_ROOT = os.getenv("KATIA_DATA_DIR", os.path.join(BASE_DIR, "data"))
ARCHIVO = os.path.join(DATA_ROOT, "demos.json")


def _cargar() -> list:
    try:
        with open(ARCHIVO, "r", encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, ValueError):
        return []


def _guardar(data: list):
    os.makedirs(DATA_ROOT, exist_ok=True)
    with open(ARCHIVO, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def crear(datos: dict) -> dict:
    """Guarda una solicitud de demo. datos = {nombre, whatsapp, correo, negocio, giro, mensaje}."""
    d = _cargar()
    item = {
        "id": secrets.token_hex(5),
        "creado": datetime.now().isoformat(),
        "atendido": False,
        "nombre": (datos.get("nombre") or "").strip(),
        "whatsapp": (datos.get("whatsapp") or "").strip(),
        "correo": (datos.get("correo") or "").strip(),
        "negocio": (datos.get("negocio") or "").strip(),
        "giro": (datos.get("giro") or "").strip(),
        "mensaje": (datos.get("mensaje") or "").strip(),
    }
    d.insert(0, item)
    _guardar(d)
    return item


def listar() -> list:
    return _cargar()


def marcar_atendido(id_: str) -> bool:
    d = _cargar()
    cambio = False
    for x in d:
        if x.get("id") == id_:
            x["atendido"] = not x.get("atendido", False)
            cambio = True
    if cambio:
        _guardar(d)
    return cambio


def eliminar(id_: str) -> bool:
    d = _cargar()
    d2 = [x for x in d if x.get("id") != id_]
    _guardar(d2)
    return len(d2) != len(d)

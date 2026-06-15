# usuarios.py — Cuentas de dueños de tienda (login del CONSTRUCTOR)
# -------------------------------------------------------------------
# Almacén JSON simple (data/usuarios.json): {email: {...}}. Hashing de
# contraseña con pbkdf2 (stdlib, sin dependencias externas).
#
# En producción esto se migra a Postgres (db.py ya tiene el pool), pero
# como todo pasa por estas funciones, el resto de la app no cambiaría.
# -------------------------------------------------------------------
import hashlib
import hmac
import json
import os
import re
from datetime import datetime, timezone

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
# En producción apunta al disco persistente (KATIA_DATA_DIR); en local a ./data
DATA_DIR = os.getenv("KATIA_DATA_DIR", os.path.join(BASE_DIR, "data"))
ARCHIVO = os.path.join(DATA_DIR, "usuarios.json")

_RE_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


# ------------------- Hashing -------------------

def hash_password(password: str, salt: bytes = None) -> str:
    salt = salt or os.urandom(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, 200_000)
    return f"{salt.hex()}:{dk.hex()}"


def verificar_password(password: str, almacenado: str) -> bool:
    try:
        salt_hex, dk_hex = almacenado.split(":")
        dk = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt_hex), 200_000)
        return hmac.compare_digest(dk.hex(), dk_hex)
    except (ValueError, AttributeError):
        return False


# ------------------- Almacén -------------------

def _cargar() -> dict:
    if not os.path.exists(ARCHIVO):
        return {}
    with open(ARCHIVO, "r", encoding="utf-8") as f:
        return json.load(f)


def _guardar(data: dict):
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(ARCHIVO, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def email_valido(email: str) -> bool:
    return bool(_RE_EMAIL.match((email or "").strip()))


def buscar(email: str):
    return _cargar().get((email or "").lower().strip())


def crear(email: str, password: str, nombre: str = "",
          rol: str = "dueno", tienda_slug: str = "", miembro_id: str = ""):
    """Crea un usuario. rol = 'dueno' | 'especialista'. Para especialista se
    vincula a una tienda y a un miembro del equipo. Devuelve (usuario, error)."""
    email = (email or "").lower().strip()
    if not email_valido(email):
        return None, "Correo no válido."
    if len(password or "") < 6:
        return None, "La contraseña debe tener al menos 6 caracteres."
    data = _cargar()
    if email in data:
        return None, "Ya existe una cuenta con ese correo."
    usuario = {
        "email": email,
        "nombre": (nombre or "").strip(),
        "password_hash": hash_password(password),
        "rol": rol if rol in ("dueno", "especialista") else "dueno",
        "tienda_slug": tienda_slug or "",
        "miembro_id": miembro_id or "",
        # Suscripción a katia: gratis | tienda | pro | escala
        "plan": "gratis",
        "stripe_customer_id": "",
        "sub_estado": "",          # active, canceled, ...
        "creado": datetime.now(timezone.utc).isoformat(),
    }
    data[email] = usuario
    _guardar(data)
    return usuario, None


def actualizar(email: str, cambios: dict):
    """Aplica cambios parciales a un usuario. Devuelve el usuario o None."""
    data = _cargar()
    email = (email or "").lower().strip()
    if email not in data:
        return None
    data[email].update(cambios)
    _guardar(data)
    return data[email]


def autenticar(email: str, password: str):
    """Devuelve (usuario, error)."""
    u = buscar(email)
    if not u or not verificar_password(password, u.get("password_hash", "")):
        return None, "Correo o contraseña incorrectos."
    return u, None


def publico(usuario: dict) -> dict:
    """Versión del usuario sin el hash (para guardar en sesión / enviar al cliente)."""
    if not usuario:
        return None
    return {
        "email": usuario["email"],
        "nombre": usuario.get("nombre", ""),
        "rol": usuario.get("rol", "dueno"),
        "tienda_slug": usuario.get("tienda_slug", ""),
        "miembro_id": usuario.get("miembro_id", ""),
        "plan": usuario.get("plan", "gratis"),
        "sub_estado": usuario.get("sub_estado", ""),
    }

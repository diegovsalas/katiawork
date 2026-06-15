# emails.py — Envío de correos del CONSTRUCTOR (katia) vía Resend
# -------------------------------------------------------------------
# Genérico y con degradación elegante: si no hay RESEND_API_KEY, no
# envía nada y devuelve False (el flujo sigue sin romperse).
# Reutiliza la misma cuenta de Resend que el resto del proyecto.
# -------------------------------------------------------------------
import os

try:
    import resend
    _RESEND_OK = True
except ImportError:
    _RESEND_OK = False

RESEND_API_KEY = os.getenv("RESEND_API_KEY", "")
RESEND_FROM = os.getenv("KATIA_RESEND_FROM", os.getenv("RESEND_FROM", "katia <onboarding@resend.dev>"))

if _RESEND_OK and RESEND_API_KEY:
    resend.api_key = RESEND_API_KEY


def disponible() -> bool:
    return bool(_RESEND_OK and RESEND_API_KEY)


def enviar(destinatario: str, asunto: str, html: str) -> bool:
    """Envía un correo HTML. Devuelve True si se envió, False si Resend no
    está configurado o falló."""
    if not disponible() or not destinatario:
        return False
    try:
        resend.Emails.send({
            "from": RESEND_FROM,
            "to": [destinatario],
            "subject": asunto,
            "html": html,
        })
        return True
    except Exception as e:  # noqa: BLE001
        print(f"⚠  Falló envío de correo katia a {destinatario}: {e}")
        return False

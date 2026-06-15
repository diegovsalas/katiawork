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


# ------------------- Correo de bienvenida (por plan) -------------------

BASE_URL = os.getenv("KATIA_BASE_URL", "https://katia.work")

# Beneficios destacados por plan (lo que se desbloquea / puede hacer)
_PLAN_INFO = {
    "gratis": {
        "nombre": "Gratis",
        "intro": "Tu cuenta está lista. Crea tu primera tienda en minutos, sin tarjeta y sin comisión por venta.",
        "bullets": [
            "🛍️ Tu tienda en línea con catálogo de productos o servicios",
            "🤖 La IA escribe tus textos y crea tu logo",
            "💬 Recibe pedidos y clientes por WhatsApp",
        ],
        "cta": "Crear mi tienda", "cta_url": "/crear",
        "tip": "¿Quieres dominio propio y quitar la marca de katia? Mejora al plan Tienda cuando quieras.",
    },
    "tienda": {
        "nombre": "Tienda",
        "intro": "¡Gracias por suscribirte al plan Tienda! Ya tienes tu tienda lista para vender en serio.",
        "bullets": [
            "🌐 Dominio propio y tienda sin la marca de katia",
            "📦 Productos ilimitados y redes sociales conectadas",
            "💳 Cobros en línea (SPEI/transferencia y MercadoPago)",
        ],
        "cta": "Ir a mi tienda", "cta_url": "/mis-tiendas",
        "tip": "¿Necesitas CRM, caja y reportes? El plan Ventas Pro los incluye.",
    },
    "pro": {
        "nombre": "Ventas Pro",
        "intro": "¡Bienvenido a Ventas Pro! Ahora katia es también tu sistema de ventas y tu CRM.",
        "bullets": [
            "📊 Panel con CRM, pipeline de clientes y reportes automáticos",
            "🛒 Punto de venta (POS) para cobrar en mostrador y descontar stock",
            "👥 Equipo: registra ventas y citas por especialista",
        ],
        "cta": "Abrir mi panel", "cta_url": "/mis-tiendas",
        "tip": "¿Varias sucursales y control de gastos avanzado? Mira el plan Escala.",
    },
    "escala": {
        "nombre": "Escala",
        "intro": "¡Bienvenido a Escala! El plan más completo de katia para crecer tu operación.",
        "bullets": [
            "🏢 Multi-sucursal y logins por cada miembro del equipo",
            "🧾 Control de gastos avanzado y presupuestos",
            "📈 Todo lo de Ventas Pro: CRM, POS, reportes y más",
        ],
        "cta": "Abrir mi panel", "cta_url": "/mis-tiendas",
        "tip": "¿Dudas para sacarle el máximo provecho? Escríbenos, te ayudamos a configurarlo.",
    },
}


def _html_bienvenida(nombre: str, plan: str) -> str:
    info = _PLAN_INFO.get(plan, _PLAN_INFO["gratis"])
    saludo = (nombre or "").split(" ")[0] or "¡Hola!"
    bullets = "".join(
        f'<tr><td style="padding:7px 0;font-size:15px;color:#3a3a4d">{b}</td></tr>'
        for b in info["bullets"]
    )
    es_pago = plan != "gratis"
    encabezado = (
        f'Plan {info["nombre"]} activado' if es_pago else "Tu cuenta está lista"
    )
    return f"""\
<!doctype html><html><body style="margin:0;background:#f6f5fb;
  font-family:-apple-system,'Segoe UI',Roboto,Helvetica,Arial,sans-serif">
  <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background:#f6f5fb;padding:28px 14px">
    <tr><td align="center">
      <table role="presentation" width="100%" cellpadding="0" cellspacing="0"
        style="max-width:560px;background:#fff;border-radius:18px;overflow:hidden;border:1px solid #e9e6f3">
        <tr><td style="background:linear-gradient(120deg,#8b5cf6,#6d5dfb);padding:26px 30px">
          <div style="color:#fff;font-size:22px;font-weight:800;letter-spacing:-.3px">katia<span style="opacity:.85">.work</span></div>
          <div style="color:#ece7fb;font-size:13px;margin-top:3px">{encabezado}</div>
        </td></tr>
        <tr><td style="padding:30px">
          <h1 style="margin:0 0 10px;font-size:22px;color:#222642">Hola, {saludo} 👋</h1>
          <p style="margin:0 0 18px;font-size:15px;line-height:1.6;color:#3a3a4d">{info["intro"]}</p>
          <table role="presentation" width="100%" cellpadding="0" cellspacing="0"
            style="background:#f7f6fb;border:1px solid #ece9f6;border-radius:12px;padding:6px 16px;margin:0 0 22px">
            {bullets}
          </table>
          <a href="{BASE_URL}{info['cta_url']}"
            style="display:inline-block;background:#6d5dfb;color:#fff;text-decoration:none;font-weight:700;
            font-size:15px;padding:13px 26px;border-radius:12px">{info['cta']}</a>
          <p style="margin:22px 0 0;font-size:13.5px;line-height:1.6;color:#6b6a83">💡 {info['tip']}</p>
        </td></tr>
        <tr><td style="padding:18px 30px;border-top:1px solid #eee;color:#9a99ac;font-size:12.5px">
          ¿Dudas? Responde a este correo o escríbenos a
          <a href="mailto:hola@katia.work" style="color:#6d5dfb">hola@katia.work</a>.<br>
          katia.work · Hecho en México 🇲🇽
        </td></tr>
      </table>
    </td></tr>
  </table>
</body></html>"""


def enviar_bienvenida(email: str, nombre: str, plan: str = "gratis") -> bool:
    """Envía el correo de bienvenida correspondiente al plan. No rompe el flujo."""
    info = _PLAN_INFO.get(plan, _PLAN_INFO["gratis"])
    if plan == "gratis":
        asunto = "¡Bienvenido a katia! Crea tu tienda en minutos 🚀"
    else:
        asunto = f"¡Listo! Tu plan {info['nombre']} está activo en katia ✨"
    return enviar(email, asunto, _html_bienvenida(nombre, plan))

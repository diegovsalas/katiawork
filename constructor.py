# constructor.py — Asistente para crear tiendas en minutos (multi-tenant)
# -------------------------------------------------------------------
# App independiente del storefront Momatt (app.py). Aquí vive:
#   - La landing del producto y el ASISTENTE de creación (/crear).
#   - Los endpoints de IA (Gemini) que alimentan el asistente.
#   - El storefront genérico que renderiza CADA tienda creada, ya sea por
#     subdominio (slug.DOMINIO_BASE), dominio propio, o ruta /t/<slug>
#     (esta última para probar en local sin configurar DNS).
#
# Correr en local:   uvicorn constructor:app --reload
# Abrir:             http://localhost:8000
# -------------------------------------------------------------------
import asyncio
import csv
import io
import os
import secrets
import time
import zipfile
from datetime import datetime, timedelta, date as _date

from fastapi import FastAPI, Request, UploadFile, File, Form, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, FileResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware

import demos
import emails
import gemini_ia
import pagos_suscripcion as subs
import tiendas
import usuarios

# Dominio raíz del constructor. En producción ponlo en env (ej. "miconstructor.com")
# para que <slug>.miconstructor.com resuelva a cada tienda.
DOMINIO_BASE = os.getenv("DOMINIO_BASE", "localhost")
# URL base para enlaces en correos cuando NO se usa subdominio (dev local).
KATIA_BASE_URL = os.getenv("KATIA_BASE_URL", "http://localhost:8001")
# Token para el cron de recordatorios (cron-job.org hace GET/POST con ?token=).
CRON_TOKEN = os.getenv("CRON_TOKEN", "")
# Correos con acceso al panel super-admin de plataforma (/admin), separados por coma.
ADMIN_EMAILS = {e.strip().lower() for e in os.getenv("ADMIN_EMAILS", "").split(",") if e.strip()}

# Planes de suscripción de katia. price_id viene de Stripe (env). Si no hay
# Stripe configurado, el checkout entra en "modo demo" (activa sin cobrar).
PLANES = {
    "gratis": {"nombre": "Gratis",     "precio": 0,    "price_id": ""},
    "tienda": {"nombre": "Tienda",     "precio": 249,  "price_id": os.getenv("STRIPE_PRICE_TIENDA", "")},
    "pro":    {"nombre": "Ventas Pro", "precio": 799,  "price_id": os.getenv("STRIPE_PRICE_PRO", "")},
    "escala": {"nombre": "Escala",     "precio": 1999, "price_id": os.getenv("STRIPE_PRICE_ESCALA", "")},
}
PRICE_TO_PLAN = {v["price_id"]: k for k, v in PLANES.items() if v["price_id"]}

# Qué desbloquea cada plan (gating de funciones).
CAPS = {
    "gratis": {"tienda_basica"},
    "tienda": {"tienda_basica", "dominio_propio", "sin_marca", "productos_ilimitados",
               "redes_sociales", "checkout_online"},
    "pro":    {"tienda_basica", "dominio_propio", "sin_marca", "productos_ilimitados",
               "redes_sociales", "checkout_online", "panel", "crm", "caja", "reportes",
               "recordatorios", "equipo", "pos", "gastos"},
    "escala": {"tienda_basica", "dominio_propio", "sin_marca", "productos_ilimitados",
               "redes_sociales", "checkout_online", "panel", "crm", "caja", "reportes",
               "recordatorios", "equipo", "pos", "gastos",
               "logins_equipo", "multi_sucursal", "gastos_avanzado"},
}
PLAN_LABEL = {"gratis": "Gratis", "tienda": "Tienda", "pro": "Ventas Pro", "escala": "Escala"}
# Plan mínimo que incluye cada capacidad (para mensajes de upsell).
PLAN_MINIMO = {"dominio_propio": "tienda", "sin_marca": "tienda", "panel": "pro",
               "crm": "pro", "caja": "pro", "reportes": "pro", "recordatorios": "pro",
               "equipo": "pro", "gastos": "pro", "logins_equipo": "escala", "multi_sucursal": "escala",
               "gastos_avanzado": "escala", "redes_sociales": "tienda",
               "checkout_online": "tienda", "pos": "pro"}

# Redes sociales soportadas + base de URL para normalizar handles.
REDES_BASE = {
    "instagram": "https://instagram.com/", "facebook": "https://facebook.com/",
    "tiktok": "https://tiktok.com/@", "youtube": "https://youtube.com/@",
    "x": "https://x.com/", "sitio": "",
    # Google Negocio: link al perfil/Maps y link para dejar reseña.
    "maps": "", "google_review": "",
}


def _norm_red(tipo: str, val: str) -> str:
    val = (val or "").strip()
    if not val:
        return ""
    if val.startswith(("http://", "https://")):
        return val
    h = val.lstrip("@/ ").strip()
    base = REDES_BASE.get(tipo, "")
    return (base + h) if base else ("https://" + h)


def _normalizar_redes(redes: dict) -> dict:
    out = {}
    if isinstance(redes, dict):
        for tipo in REDES_BASE:
            u = _norm_red(tipo, redes.get(tipo, ""))
            if u:
                out[tipo] = u
    return out


def permite(plan: str, cap: str) -> bool:
    return cap in CAPS.get(plan or "gratis", set())


# Plantillas del storefront. plan = nivel mínimo para usarla.
PLAN_ORDEN = ["gratis", "tienda", "pro", "escala"]
TEMAS = {
    "aurora":   {"nombre": "Aurora",   "desc": "Moderno con degradado",        "plan": "gratis"},
    "minimal":  {"nombre": "Minimal",  "desc": "Limpio, claro y espacioso",     "plan": "gratis"},
    "bold":     {"nombre": "Bold",     "desc": "Oscuro, tipografía grande",      "plan": "tienda"},
    "boutique": {"nombre": "Boutique", "desc": "Serif elegante (spa/belleza)",   "plan": "tienda"},
    "vibrante": {"nombre": "Vibrante", "desc": "Colorido para catálogos",        "plan": "tienda"},
}
# Paleta limitada para el plan Gratis (Tienda+ tiene edición libre).
PALETA_GRATIS = ["#6d5dfb", "#3f6b4f", "#e0397b", "#2563eb", "#ea580c", "#0d9488", "#7c3aed", "#1f2937"]


def _rank(plan: str) -> int:
    return PLAN_ORDEN.index(plan) if plan in PLAN_ORDEN else 0


def tema_permitido(plan: str, tema: str) -> bool:
    return _rank(plan) >= _rank(TEMAS.get(tema, {}).get("plan", "gratis"))


def _plan_de_tienda(tienda: dict) -> str:
    """Plan del dueño de la tienda (gratis si es invitado o no existe)."""
    email = (tienda.get("owner_email") or "").lower().strip()
    if not email:
        return "gratis"
    u = usuarios.buscar(email)
    return (u or {}).get("plan", "gratis")


def _pago_online(tienda: dict) -> bool:
    """¿La tienda puede mostrar checkout (plan lo permite y hay método configurado)?"""
    pg = tienda.get("pagos", {}) or {}
    return permite(_plan_de_tienda(tienda), "checkout_online") and bool(pg.get("spei_activo") or pg.get("mp_activo"))


def _suspendida_resp(tienda: dict):
    """Si la tienda está suspendida, devuelve una página 503; si no, None."""
    if not tienda.get("suspendida"):
        return None
    html = (
        "<!doctype html><html lang=es><head><meta charset=utf-8>"
        "<meta name=viewport content='width=device-width,initial-scale=1'>"
        "<title>Tienda no disponible</title>"
        "<style>body{font-family:system-ui,-apple-system,sans-serif;background:#f6f5fb;color:#222642;"
        "display:grid;place-items:center;height:100vh;margin:0;text-align:center;padding:24px}"
        ".c{max-width:440px}.c h1{font-size:22px;margin:0 0 8px}.c p{color:#6b6a83;line-height:1.6}</style>"
        "</head><body><div class=c><h1>Esta tienda no está disponible por ahora</h1>"
        "<p>El negocio tiene su tienda en pausa temporalmente. Si eres el dueño, "
        "ingresa a tu panel para reactivarla.</p></div></body></html>"
    )
    return HTMLResponse(html, status_code=503)


def _gate(tienda: dict, cap: str):
    """Lanza 402 si el plan de la tienda no incluye la capacidad."""
    plan = _plan_de_tienda(tienda)
    if not permite(plan, cap):
        req = PLAN_LABEL.get(PLAN_MINIMO.get(cap, "pro"), "Ventas Pro")
        raise HTTPException(status_code=402,
                            detail=f"Esta función es parte del plan {req}. Mejora tu plan en /facturacion.")

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
# Raíz de datos persistente (disco en Render). Las imágenes subidas viven aquí
# y se sirven por /u, separadas de los assets estáticos del repo (/static).
DATA_ROOT = os.getenv("KATIA_DATA_DIR", os.path.join(BASE_DIR, "data"))
UPLOADS_DIR = os.path.join(DATA_ROOT, "uploads")
BORRADORES_DIR = os.path.join(UPLOADS_DIR, "_borradores")
os.makedirs(BORRADORES_DIR, exist_ok=True)

app = FastAPI(title="katia.work — Constructor de Tiendas con IA")
_SECRET = os.getenv("SESSION_SECRET_KEY") or secrets.token_urlsafe(32)
# En producción la cookie de sesión se comparte en *.katia.work (para que el
# dueño logueado en katia.work entre a su panel en cliente.katia.work) y va solo
# por HTTPS. En local (localhost) se queda como cookie de host por HTTP.
_PROD = bool(DOMINIO_BASE and DOMINIO_BASE != "localhost")
app.add_middleware(
    SessionMiddleware, secret_key=_SECRET, max_age=60 * 60 * 24 * 30,  # 30 días
    same_site="lax",
    domain=f".{DOMINIO_BASE}" if _PROD else None,
    https_only=_PROD,
)
app.mount("/static", StaticFiles(directory="static"), name="static")          # assets del repo
app.mount("/u", StaticFiles(directory=UPLOADS_DIR), name="uploads")            # imágenes subidas (disco)
templates = Jinja2Templates(directory="templates")
# ID de Google Analytics (gtag). Configurable por env; disponible en todas las plantillas.
templates.env.globals["GA_ID"] = os.getenv("GA_MEASUREMENT_ID", "G-B4E71MQFQT")


# ------------------- Respaldos (backups) -------------------

BACKUP_DIR = os.path.join(DATA_ROOT, "backups")


def _respaldo_zip(incluir_imagenes: bool = False) -> bytes:
    """Genera en memoria un ZIP con los datos (tiendas, usuarios, demos) y,
    opcionalmente, las imágenes subidas. Devuelve los bytes del ZIP."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        td = os.path.join(DATA_ROOT, "tiendas")
        if os.path.isdir(td):
            for f in os.listdir(td):
                if f.endswith(".json"):
                    z.write(os.path.join(td, f), f"tiendas/{f}")
        for f in ("usuarios.json", "demos.json"):
            p = os.path.join(DATA_ROOT, f)
            if os.path.exists(p):
                z.write(p, f)
        if incluir_imagenes and os.path.isdir(UPLOADS_DIR):
            for raiz, _dirs, archivos in os.walk(UPLOADS_DIR):
                if "_borradores" in raiz:
                    continue
                for a in archivos:
                    full = os.path.join(raiz, a)
                    rel = os.path.relpath(full, DATA_ROOT)
                    z.write(full, rel)
    return buf.getvalue()


def _snapshot_disco(keep: int = 14):
    """Guarda un ZIP de datos (sin imágenes) en backups/ y conserva los últimos `keep`."""
    os.makedirs(BACKUP_DIR, exist_ok=True)
    nombre = f"respaldo-{datetime.now().strftime('%Y%m%d-%H%M')}.zip"
    with open(os.path.join(BACKUP_DIR, nombre), "wb") as f:
        f.write(_respaldo_zip(incluir_imagenes=False))
    snaps = sorted(x for x in os.listdir(BACKUP_DIR) if x.startswith("respaldo-") and x.endswith(".zip"))
    for viejo in snaps[:-keep]:
        try:
            os.remove(os.path.join(BACKUP_DIR, viejo))
        except OSError:
            pass
    return nombre


async def _backup_loop():
    """Respaldo automático: snapshot al arrancar y luego cada 24 h."""
    while True:
        try:
            n = _snapshot_disco()
            print(f"✓ Respaldo automático creado: {n}")
        except Exception as e:  # noqa: BLE001
            print(f"⚠  Respaldo automático falló: {e}")
        await asyncio.sleep(24 * 60 * 60)


@app.on_event("startup")
async def _arrancar_backups():
    asyncio.create_task(_backup_loop())


# ------------------- Rate limiting (anti-spam / fuerza bruta) -------------------

_RL: dict = {}  # "nombre:ip" -> [timestamps]


def _client_ip(request: Request) -> str:
    """IP real del cliente (detrás del proxy de Render via X-Forwarded-For)."""
    xff = request.headers.get("x-forwarded-for", "")
    if xff:
        return xff.split(",")[0].strip()
    return request.client.host if request.client else "?"


def _rate_limit(request: Request, nombre: str, limite: int, ventana: int):
    """Permite `limite` peticiones por IP cada `ventana` segundos. Si se excede,
    lanza HTTP 429. Limitador en memoria (suficiente para una sola instancia)."""
    ip = _client_ip(request)
    ahora = time.time()
    key = f"{nombre}:{ip}"
    arr = [t for t in _RL.get(key, []) if ahora - t < ventana]
    if len(arr) >= limite:
        raise HTTPException(status_code=429,
                            detail="Demasiados intentos. Espera un momento e inténtalo de nuevo.")
    arr.append(ahora)
    _RL[key] = arr
    # Poda de memoria: si crece mucho, descarta llaves sin actividad reciente
    if len(_RL) > 5000:
        for k in [k for k, v in _RL.items() if not v or ahora - v[-1] > 3600]:
            _RL.pop(k, None)


# ------------------- Sesión / usuario actual -------------------

def _usuario_actual(request: Request):
    """Devuelve {email, nombre} del usuario logueado, o None."""
    email = request.session.get("uid")
    if not email:
        return None
    u = usuarios.buscar(email)
    return usuarios.publico(u) if u else None


def _es_superadmin(request: Request) -> bool:
    """True si el usuario logueado está en ADMIN_EMAILS (super-admin de plataforma)."""
    email = (request.session.get("uid") or "").lower().strip()
    return bool(email) and email in ADMIN_EMAILS


@app.on_event("startup")
def _startup():
    os.makedirs(BORRADORES_DIR, exist_ok=True)
    estado_ia = "ACTIVA ✓" if gemini_ia.disponible() else "modo plantilla (sin GEMINI_API_KEY)"
    print(f"✓ Constructor listo. IA Gemini: {estado_ia}. Dominio base: {DOMINIO_BASE}")


# ------------------- Helpers -------------------

def _ctx_tienda(request: Request, tienda: dict, ruta_base: str = "") -> dict:
    """Contexto común para renderizar un storefront."""
    tipo = tienda.get("tipo", "productos")
    plan = _plan_de_tienda(tienda)
    tema = tienda.get("tema", "aurora")
    if not tema_permitido(plan, tema):   # si bajó de plan, cae a plantilla gratis
        tema = "aurora"
    return {
        "request": request,
        "t": tienda,
        "productos": tienda.get("productos", []),
        "categorias": _categorias(tienda.get("productos", [])),
        "servicios": tienda.get("servicios", []),
        "tipo": tipo,
        "muestra_productos": tipo in ("productos", "ambos"),
        "muestra_servicios": tipo in ("servicios", "ambos"),
        "ruta_base": ruta_base,           # "" en subdominio, "/t/<slug>" en local
        "ia_activa": gemini_ia.disponible(),
        "sin_marca": permite(plan, "sin_marca"),
        "tema": tema,
        "hero_imagen": tienda.get("hero_imagen", ""),
        "redes": tienda.get("redes", {}) if permite(plan, "redes_sociales") else {},
        "host_url": str(request.base_url).rstrip("/"),
        "pago_online": _pago_online(tienda),
    }


def _categorias(productos):
    vistas = []
    for p in productos:
        c = p.get("categoria") or "General"
        if c not in vistas:
            vistas.append(c)
    return vistas


# ------------------- Home: landing del constructor O storefront por subdominio -------------------

@app.get("/", response_class=HTMLResponse)
def home(request: Request):
    host = request.headers.get("host", "")
    slug = tiendas.resolver_por_host(host, DOMINIO_BASE)
    if slug:
        tienda = tiendas.obtener_tienda(slug)
        if tienda and tienda.get("publicada", True):
            susp = _suspendida_resp(tienda)
            if susp:
                return susp
            return templates.TemplateResponse(
                request, "constructor/tienda.html", _ctx_tienda(request, tienda, ruta_base="")
            )
    # Host base -> landing del producto
    return templates.TemplateResponse(request, "constructor/landing.html", {
        "ia_activa": gemini_ia.disponible(),
        "total_tiendas": len(tiendas.listar_tiendas()),
        "usuario": _usuario_actual(request),
    })


# ------------------- Cuentas: registro / login / logout -------------------

@app.get("/cuenta", response_class=HTMLResponse)
def cuenta(request: Request, modo: str = "login", next: str = ""):
    u = _usuario_actual(request)
    if u:
        destino = "/especialista" if u.get("rol") == "especialista" else "/mis-tiendas"
        return RedirectResponse(url=destino, status_code=303)
    return templates.TemplateResponse(request, "constructor/cuenta.html", {
        "modo": "registro" if modo == "registro" else "login",
        "next": next, "error": "",
    })


@app.post("/registro")
def registro(request: Request, nombre: str = Form(""), email: str = Form(...),
             password: str = Form(...), next: str = Form("")):
    _rate_limit(request, "registro", 8, 3600)   # 8 cuentas / hora por IP
    u, error = usuarios.crear(email, password, nombre)
    if error:
        return templates.TemplateResponse(request, "constructor/cuenta.html",
            {"modo": "registro", "error": error, "next": next, "email": email, "nombre": nombre})
    request.session["uid"] = u["email"]
    try:
        emails.enviar_bienvenida(u["email"], u.get("nombre", ""), "gratis")
    except Exception as e:  # noqa: BLE001 — el correo nunca debe romper el registro
        print(f"⚠  Bienvenida no enviada: {e}")
    return RedirectResponse(url=next or "/mis-tiendas", status_code=303)


@app.post("/login")
def login(request: Request, email: str = Form(...), password: str = Form(...), next: str = Form("")):
    _rate_limit(request, "login", 15, 300)   # 15 intentos / 5 min por IP
    u, error = usuarios.autenticar(email, password)
    if error:
        return templates.TemplateResponse(request, "constructor/cuenta.html",
            {"modo": "login", "error": error, "next": next, "email": email})
    request.session["uid"] = u["email"]
    destino = next or ("/especialista" if u.get("rol") == "especialista" else "/mis-tiendas")
    return RedirectResponse(url=destino, status_code=303)


@app.get("/logout")
def logout(request: Request):
    request.session.clear()
    return RedirectResponse(url="/", status_code=303)


# ------------------- Recuperar contraseña -------------------

@app.get("/recuperar", response_class=HTMLResponse)
def recuperar_form(request: Request):
    return templates.TemplateResponse(request, "constructor/recuperar.html", {"modo": "solicitar"})


@app.post("/recuperar", response_class=HTMLResponse)
def recuperar_enviar(request: Request, email: str = Form(...)):
    """Genera un enlace de restablecimiento y lo envía por correo.
    Siempre responde igual (no revela si el correo existe)."""
    _rate_limit(request, "recuperar", 6, 3600)   # 6 / hora por IP
    token = usuarios.crear_token_reset(email)
    if token:
        from urllib.parse import quote
        enlace = f"{KATIA_BASE_URL}/restablecer?e={quote(email.lower().strip())}&t={token}"
        html = (
            "<p>Hola, recibimos una solicitud para restablecer tu contraseña en katia.</p>"
            f"<p><a href='{enlace}' style='background:#6d5dfb;color:#fff;padding:12px 22px;"
            "border-radius:10px;text-decoration:none;font-weight:700'>Crear nueva contraseña</a></p>"
            "<p>El enlace vence en 1 hora. Si no fuiste tú, ignora este correo.</p>"
            "<p style='color:#888;font-size:12px'>katia.work</p>"
        )
        try:
            emails.enviar(email.lower().strip(), "Restablece tu contraseña · katia", html)
        except Exception as e:  # noqa: BLE001
            print(f"⚠  Correo de reset no enviado: {e}")
    return templates.TemplateResponse(request, "constructor/recuperar.html", {"modo": "enviado"})


@app.get("/restablecer", response_class=HTMLResponse)
def restablecer_form(request: Request, e: str = "", t: str = ""):
    valido = usuarios.validar_token_reset(e, t)
    return templates.TemplateResponse(request, "constructor/recuperar.html",
                                      {"modo": "restablecer", "email": e, "token": t, "valido": valido})


@app.post("/restablecer", response_class=HTMLResponse)
def restablecer_enviar(request: Request, email: str = Form(...), token: str = Form(...), password: str = Form(...)):
    ok, error = usuarios.restablecer_password(email, token, password)
    if not ok:
        return templates.TemplateResponse(request, "constructor/recuperar.html",
                                          {"modo": "restablecer", "email": email, "token": token,
                                           "valido": True, "error": error})
    return templates.TemplateResponse(request, "constructor/recuperar.html", {"modo": "listo"})


# ------------------- Suscripción a katia (Stripe) -------------------

@app.get("/facturacion", response_class=HTMLResponse)
def facturacion(request: Request, ok: str = ""):
    u = _usuario_actual(request)
    if not u:
        return RedirectResponse(url="/cuenta?next=/facturacion", status_code=303)
    if u.get("rol") == "especialista":
        return RedirectResponse(url="/especialista", status_code=303)
    full = usuarios.buscar(u["email"]) or {}
    return templates.TemplateResponse(request, "constructor/facturacion.html", {
        "usuario": u, "planes": PLANES, "plan_actual": full.get("plan", "gratis"),
        "sub_estado": full.get("sub_estado", ""), "tiene_stripe": bool(full.get("stripe_customer_id")),
        "stripe_activo": subs.disponible(), "ok": ok,
    })


@app.post("/api/suscripcion/checkout")
async def api_sub_checkout(request: Request):
    u = _usuario_actual(request)
    if not u or u.get("rol") == "especialista":
        raise HTTPException(status_code=403, detail="Inicia sesión como dueño.")
    b = await request.json()
    plan = b.get("plan")
    if plan not in PLANES:
        raise HTTPException(status_code=400, detail="Plan no válido.")

    if plan == "gratis":
        usuarios.actualizar(u["email"], {"plan": "gratis", "sub_estado": "canceled"})
        return JSONResponse({"ok": True, "url": "/facturacion?ok=gratis"})

    price_id = PLANES[plan]["price_id"]
    if subs.disponible() and price_id:
        full = usuarios.buscar(u["email"]) or {}
        url = subs.crear_checkout(
            u["email"], price_id,
            success_url=f"{KATIA_BASE_URL}/facturacion?ok=1",
            cancel_url=f"{KATIA_BASE_URL}/facturacion?ok=cancel",
            customer_id=full.get("stripe_customer_id", ""),
        )
        return JSONResponse({"ok": True, "url": url})

    # Modo demo (sin Stripe configurado): activa el plan al instante.
    usuarios.actualizar(u["email"], {"plan": plan, "sub_estado": "active_demo"})
    try:
        emails.enviar_bienvenida(u["email"], u.get("nombre", ""), plan)
    except Exception as e:  # noqa: BLE001
        print(f"⚠  Bienvenida (demo) no enviada: {e}")
    return JSONResponse({"ok": True, "demo": True, "url": "/facturacion?ok=demo"})


@app.post("/api/suscripcion/portal")
async def api_sub_portal(request: Request):
    u = _usuario_actual(request)
    if not u:
        raise HTTPException(status_code=403, detail="No autorizado.")
    full = usuarios.buscar(u["email"]) or {}
    cid = full.get("stripe_customer_id")
    if not (subs.disponible() and cid):
        raise HTTPException(status_code=400, detail="No hay portal disponible.")
    url = subs.crear_portal(cid, return_url=f"{KATIA_BASE_URL}/facturacion")
    return JSONResponse({"ok": True, "url": url})


@app.post("/webhook/stripe-suscripcion")
async def webhook_suscripcion(request: Request):
    """Stripe avisa cambios de suscripción → actualizamos el plan del usuario."""
    payload = await request.body()
    sig = request.headers.get("stripe-signature", "")
    try:
        evt = subs.verificar_evento(payload, sig)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=400, detail=f"Webhook inválido: {e}")

    tipo = evt.get("type", "")
    obj = evt.get("data", {}).get("object", {})
    meta = obj.get("metadata", {}) or {}
    email = meta.get("email") or obj.get("client_reference_id") or obj.get("customer_email")

    if tipo == "checkout.session.completed" and email:
        usuarios.actualizar(email, {"stripe_customer_id": obj.get("customer", ""), "sub_estado": "active"})
    elif tipo in ("customer.subscription.created", "customer.subscription.updated"):
        estado = obj.get("status", "")
        try:
            price = obj["items"]["data"][0]["price"]["id"]
        except (KeyError, IndexError, TypeError):
            price = ""
        plan = PRICE_TO_PLAN.get(price)
        if email and plan:
            estado_final = "active" if estado in ("active", "trialing") else estado
            antes = usuarios.buscar(email) or {}
            usuarios.actualizar(email, {"plan": plan if estado_final == "active" else "gratis",
                                        "sub_estado": estado_final,
                                        "stripe_customer_id": obj.get("customer", "")})
            # Bienvenida solo al activarse por primera vez (no en cada actualización)
            if estado_final == "active" and antes.get("sub_estado") != "active":
                try:
                    emails.enviar_bienvenida(email, antes.get("nombre", ""), plan)
                except Exception as e:  # noqa: BLE001
                    print(f"⚠  Bienvenida (Stripe) no enviada: {e}")
    elif tipo == "customer.subscription.deleted" and email:
        usuarios.actualizar(email, {"plan": "gratis", "sub_estado": "canceled"})

    return JSONResponse({"received": True})


@app.get("/mis-tiendas", response_class=HTMLResponse)
def mis_tiendas(request: Request):
    usuario = _usuario_actual(request)
    if not usuario:
        return RedirectResponse(url="/cuenta?next=/mis-tiendas", status_code=303)
    if usuario.get("rol") == "especialista":
        return RedirectResponse(url="/especialista", status_code=303)
    mias = [t for t in tiendas.listar_tiendas()
            if (t.get("owner_email") or "").lower() == usuario["email"]]
    mias.sort(key=lambda t: t.get("creada", ""), reverse=True)
    return templates.TemplateResponse(request, "constructor/mis_tiendas.html", {
        "usuario": usuario, "tiendas": mias, "dominio_base": DOMINIO_BASE,
    })


# ------------------- El asistente (wizard) -------------------

@app.get("/crear", response_class=HTMLResponse)
def crear_wizard(request: Request):
    u = _usuario_actual(request)
    plan = (u or {}).get("plan", "gratis") if (u and u.get("rol") != "especialista") else "gratis"
    return templates.TemplateResponse(request, "constructor/wizard.html", {
        "ia_activa": gemini_ia.disponible(),
        "dominio_base": DOMINIO_BASE,
        "plan": plan,
        "temas": TEMAS,
        "paleta": PALETA_GRATIS,
        "colores_full": _rank(plan) >= _rank("tienda"),
        "logueado": bool(u and u.get("rol") != "especialista"),
        "mi_email": u["email"] if u else "",
    })


# ------------------- Planes / precios -------------------

@app.get("/precios", response_class=HTMLResponse)
def precios(request: Request):
    # Solo la home base muestra precios; en un subdominio de tienda no aplica.
    return templates.TemplateResponse(request, "constructor/precios.html", {
        "ia_activa": gemini_ia.disponible(),
    })


# ------------------- Legal (términos y privacidad) -------------------

@app.get("/terminos", response_class=HTMLResponse)
def terminos(request: Request):
    return templates.TemplateResponse(request, "constructor/legal.html", {"pagina": "terminos"})


@app.get("/privacidad", response_class=HTMLResponse)
def privacidad(request: Request):
    return templates.TemplateResponse(request, "constructor/legal.html", {"pagina": "privacidad"})


# ------------------- Solicitar demo / contacto -------------------

@app.get("/demo", response_class=HTMLResponse)
def demo_form(request: Request):
    return templates.TemplateResponse(request, "constructor/demo.html", {"enviado": False})


@app.post("/api/demo")
async def api_demo(request: Request):
    """Recibe una solicitud de demo del landing: la guarda y notifica al equipo."""
    _rate_limit(request, "demo", 6, 3600)   # 6 / hora por IP
    b = await request.json()
    nombre = (b.get("nombre") or "").strip()
    whatsapp = (b.get("whatsapp") or "").strip()
    correo = (b.get("correo") or "").strip()
    if not nombre or not whatsapp or not correo:
        raise HTTPException(status_code=400, detail="Pon tu nombre, WhatsApp y correo.")
    sol = demos.crear({
        "nombre": nombre, "whatsapp": whatsapp, "correo": correo,
        "negocio": b.get("negocio", ""), "giro": b.get("giro", ""), "mensaje": b.get("mensaje", ""),
    })
    # Notifica al equipo de katia (ADMIN_EMAILS o hola@katia.work)
    destinatarios = ADMIN_EMAILS or {"hola@katia.work"}
    html = (
        f"<h2>Nueva solicitud de demo</h2>"
        f"<p><b>Nombre:</b> {sol['nombre']}<br>"
        f"<b>WhatsApp:</b> {sol['whatsapp']}<br>"
        f"<b>Correo:</b> {sol['correo']}<br>"
        f"<b>Negocio:</b> {sol['negocio'] or '—'}<br>"
        f"<b>Giro:</b> {sol['giro'] or '—'}</p>"
        f"<p><b>Mensaje:</b><br>{(sol['mensaje'] or '—')}</p>"
    )
    try:
        for e in destinatarios:
            emails.enviar(e, f"🔔 Nueva demo: {sol['negocio'] or sol['nombre']}", html)
        # Confirmación al solicitante
        emails.enviar(
            correo, "Recibimos tu solicitud · katia.work",
            f"<p>Hola {nombre.split(' ')[0]}, ¡gracias por tu interés en katia! 🎉</p>"
            f"<p>Un agente de katia.work se pondrá en contacto contigo a la brevedad por "
            f"correo o WhatsApp.</p><p>¿Dudas? Escríbenos a "
            f"<a href='mailto:hola@katia.work'>hola@katia.work</a>.</p>",
        )
    except Exception as e:  # noqa: BLE001 — el correo nunca debe romper el flujo
        print(f"⚠  Notificación de demo no enviada: {e}")
    return JSONResponse({"ok": True})


# ------------------- API de IA usada por el wizard -------------------

@app.post("/api/ia/negocio")
async def api_ia_negocio(request: Request):
    body = await request.json()
    data = gemini_ia.redactar_negocio(
        nombre=body.get("nombre", ""),
        giro=body.get("giro", ""),
        contexto=body.get("contexto", ""),
    )
    return JSONResponse(data)


@app.post("/api/ia/productos")
async def api_ia_productos(request: Request):
    body = await request.json()
    productos = body.get("productos", [])
    enriquecidos = gemini_ia.describir_productos(productos, giro=body.get("giro", ""))
    return JSONResponse({"productos": enriquecidos})


@app.post("/api/ia/logo")
async def api_ia_logo(request: Request):
    """Genera un logo (IA o monograma) y lo guarda como borrador. Devuelve su URL."""
    body = await request.json()
    nombre = body.get("nombre", "Mi Tienda")
    token = secrets.token_hex(6)
    destino = os.path.join(BORRADORES_DIR, f"{token}.png")
    ruta = gemini_ia.generar_logo(
        nombre=nombre, giro=body.get("giro", ""),
        color=body.get("color", "#fe4e02"), ruta_destino=destino,
    )
    if not ruta:
        return JSONResponse({"error": "No se pudo generar el logo"}, status_code=500)
    archivo = os.path.basename(ruta)
    return JSONResponse({
        "url": f"/u/_borradores/{archivo}",
        "generado_por_ia": gemini_ia.disponible() and ruta.endswith(".png"),
    })


async def _guardar_borrador(archivo: UploadFile):
    """Valida y guarda una imagen subida en _borradores. Devuelve (url, error)."""
    ext = os.path.splitext(archivo.filename or "")[1].lower() or ".png"
    if ext not in {".png", ".jpg", ".jpeg", ".webp", ".svg"}:
        return None, "Formato no soportado (usa PNG, JPG, WEBP o SVG)"
    token = secrets.token_hex(6)
    nombre = f"{token}{ext}"
    with open(os.path.join(BORRADORES_DIR, nombre), "wb") as f:
        f.write(await archivo.read())
    return f"/u/_borradores/{nombre}", None


@app.post("/api/upload-logo")
async def api_upload_logo(archivo: UploadFile = File(...)):
    """Sube un logo propio. Lo guarda como borrador y devuelve su URL."""
    url, error = await _guardar_borrador(archivo)
    if error:
        return JSONResponse({"error": error}, status_code=400)
    return JSONResponse({"url": url})


@app.post("/api/upload-imagen")
async def api_upload_imagen(archivo: UploadFile = File(...)):
    """Sube la foto de un producto. La guarda como borrador y devuelve su URL."""
    url, error = await _guardar_borrador(archivo)
    if error:
        return JSONResponse({"error": error}, status_code=400)
    return JSONResponse({"url": url})


# ------------------- Gestión de catálogo (productos / servicios) -------------------

_TIPOS_CAT = {"productos", "servicios"}


def _construir_item(tipo: str, b: dict, slug: str, basename: str, base: dict = None) -> dict:
    """Arma un producto/servicio con sus campos. Mueve la imagen si es borrador."""
    item = dict(base or {})
    item["nombre"] = (b.get("nombre") or item.get("nombre") or "").strip()
    if "precio" in b:
        item["precio"] = _num(b.get("precio"))   # None = "cotizar"
    if "descripcion" in b:
        item["descripcion"] = (b.get("descripcion") or "").strip()
    if "imagen" in b:
        img = b.get("imagen") or ""
        item["imagen"] = _mover_borrador(img, slug, basename) if "_borradores/" in img else img
    if tipo == "productos":
        if "stock" in b:
            item["stock"] = int(_num(b.get("stock")) or 0)
        if "categoria" in b:
            item["categoria"] = (b.get("categoria") or "").strip()
    else:  # servicios
        if "duracion" in b:
            item["duracion"] = max(5, min(int(_num(b.get("duracion")) or 30), 480))
    return item


@app.post("/api/catalogo/{slug}/{tipo}")
async def api_catalogo_crear(request: Request, slug: str, tipo: str, k: str = ""):
    tienda = tiendas.obtener_tienda(slug)
    if not tienda or tipo not in _TIPOS_CAT:
        raise HTTPException(status_code=404, detail="No encontrado")
    _autorizar_panel(request, tienda, k)
    b = await request.json()
    if not (b.get("nombre") or "").strip():
        raise HTTPException(status_code=400, detail="El nombre es obligatorio.")
    plan = _plan_de_tienda(tienda)
    if tipo == "productos" and not permite(plan, "productos_ilimitados") and len(tienda.get("productos", [])) >= 20:
        raise HTTPException(status_code=402, detail="El plan Gratis permite hasta 20 productos. Mejora a Tienda para ilimitados.")
    iid = secrets.token_hex(4)
    item = _construir_item(tipo, b, slug, f"{tipo[:-1]}-{iid}", base={"id": iid})
    tiendas.agregar(slug, tipo, item, al_inicio=False)
    return JSONResponse({"ok": True, "item": item})


@app.patch("/api/catalogo/{slug}/{tipo}/{iid}")
async def api_catalogo_editar(request: Request, slug: str, tipo: str, iid: str, k: str = ""):
    tienda = tiendas.obtener_tienda(slug)
    if not tienda or tipo not in _TIPOS_CAT:
        raise HTTPException(status_code=404, detail="No encontrado")
    _autorizar_panel(request, tienda, k)
    actual = next((x for x in tienda.get(tipo, []) if x.get("id") == iid), None)
    if not actual:
        raise HTTPException(status_code=404, detail="No existe ese elemento.")
    b = await request.json()
    cambios = _construir_item(tipo, b, slug, f"{tipo[:-1]}-{iid}", base=actual)
    tiendas.actualizar_item(slug, tipo, iid, cambios)
    return JSONResponse({"ok": True, "item": cambios})


@app.delete("/api/catalogo/{slug}/{tipo}/{iid}")
def api_catalogo_eliminar(slug: str, tipo: str, iid: str, request: Request, k: str = ""):
    tienda = tiendas.obtener_tienda(slug)
    if not tienda or tipo not in _TIPOS_CAT:
        raise HTTPException(status_code=404, detail="No encontrado")
    _autorizar_panel(request, tienda, k)
    return JSONResponse({"ok": tiendas.eliminar_item(slug, tipo, iid)})


@app.get("/t/{slug}/catalogo", response_class=HTMLResponse)
def catalogo_local(request: Request, slug: str, k: str = ""):
    tienda = tiendas.obtener_tienda(slug)
    if not tienda:
        raise HTTPException(status_code=404, detail="Tienda no encontrada")
    _autorizar_panel(request, tienda, k)
    return templates.TemplateResponse(request, "constructor/catalogo.html", _ctx_catalogo(request, tienda, f"/t/{slug}"))


@app.get("/catalogo", response_class=HTMLResponse)
def catalogo_subdominio(request: Request, k: str = ""):
    slug = tiendas.resolver_por_host(request.headers.get("host", ""), DOMINIO_BASE)
    if not slug:
        raise HTTPException(status_code=404, detail="No encontrado")
    tienda = tiendas.obtener_tienda(slug)
    if not tienda:
        raise HTTPException(status_code=404, detail="Tienda no encontrada")
    _autorizar_panel(request, tienda, k)
    return templates.TemplateResponse(request, "constructor/catalogo.html", _ctx_catalogo(request, tienda, ""))


def _ctx_catalogo(request: Request, tienda: dict, ruta_base: str) -> dict:
    return {
        "request": request, "t": tienda, "ruta_base": ruta_base,
        "via_token": not _es_dueno(request, tienda),
        "k": tienda.get("admin_token", ""),
        "productos": tienda.get("productos", []),
        "servicios": tienda.get("servicios", []),
        "moneda": tienda.get("moneda", "MXN"),
    }


# ------------------- Crear la tienda (fin del wizard) -------------------

@app.post("/crear")
async def crear_tienda(request: Request):
    body = await request.json()
    nombre = (body.get("nombre") or "").strip()
    if not nombre:
        raise HTTPException(status_code=400, detail="El nombre del negocio es obligatorio.")

    # Mueve el logo y las fotos de producto de _borradores a la carpeta de la tienda.
    slug = tiendas.slug_unico(nombre)
    logo_url = _mover_borrador(body.get("logo", ""), slug, "logo")

    productos = _normalizar_productos(body.get("productos", []))
    for i, p in enumerate(productos):
        if p.get("imagen"):
            p["imagen"] = _mover_borrador(p["imagen"], slug, f"prod-{i+1}")

    servicios = _normalizar_servicios(body.get("servicios", []))
    for i, s in enumerate(servicios):
        if s.get("imagen"):
            s["imagen"] = _mover_borrador(s["imagen"], slug, f"serv-{i+1}")

    tipo = body.get("tipo", "productos")
    if tipo not in ("productos", "servicios", "ambos"):
        tipo = "productos"

    admin_token = secrets.token_urlsafe(9)
    usuario = _usuario_actual(request)
    if not usuario:
        # Sin sesión: crea (o identifica) la cuenta del dueño para que su tienda
        # quede ligada a un correo y pueda volver con "Mis tiendas".
        email = (body.get("cuenta_email") or "").strip().lower()
        pwd = body.get("cuenta_password") or ""
        if not email or len(pwd) < 6:
            raise HTTPException(status_code=400,
                                detail="Crea tu cuenta: pon tu correo y una contraseña (mín. 6) para publicar tu tienda.")
        u, err = usuarios.crear(email, pwd, nombre=nombre)
        if err:  # el correo ya existe → intenta identificarlo
            u, err2 = usuarios.autenticar(email, pwd)
            if err2:
                raise HTTPException(status_code=400,
                                    detail="Ese correo ya tiene cuenta. Revisa tu contraseña o inicia sesión.")
        request.session["uid"] = email
        usuario = usuarios.publico(usuarios.buscar(email))
    owner_email = usuario["email"]
    plan_creador = usuario.get("plan", "gratis")

    # Plantilla: solo si el plan la permite, si no cae a la gratis por defecto.
    tema = body.get("tema", "aurora")
    if tema not in TEMAS or not tema_permitido(plan_creador, tema):
        tema = "aurora"

    # Colores: Gratis usa paleta limitada y color_2 fijo; Tienda+ edita libre.
    color = body.get("color", "#6d5dfb")
    if _rank(plan_creador) >= _rank("tienda"):
        color_2 = body.get("color_2", "") or "#222642"
    else:
        if color not in PALETA_GRATIS:
            color = "#6d5dfb"
        color_2 = "#222642"

    hero_url = _mover_borrador(body.get("hero_imagen", ""), slug, "hero")

    tienda = tiendas.crear_tienda({
        "slug": slug,
        "nombre": nombre,
        "giro": body.get("giro", ""),
        "contexto": body.get("contexto", ""),
        "eslogan": body.get("eslogan", ""),
        "sobre_nosotros": body.get("sobre_nosotros", ""),
        "color": color,
        "color_2": color_2,
        "tono": body.get("tono", ""),
        "tema": tema,
        "hero_imagen": hero_url,
        "whatsapp": body.get("whatsapp", ""),
        "correo": body.get("correo", ""),
        "ciudad": body.get("ciudad", ""),
        "moneda": body.get("moneda", "MXN"),
        "logo": logo_url,
        "dominio_propio": body.get("dominio_propio", ""),
        "owner_email": owner_email,
        "tipo": tipo,
        "productos": productos,
        "servicios": servicios,
        "horarios": _normalizar_horarios(body.get("horarios")),
        "admin_token": admin_token,
    })

    # URL pública: subdominio si hay dominio base real, si no la ruta local.
    if DOMINIO_BASE and DOMINIO_BASE != "localhost":
        url_publica = f"//{slug}.{DOMINIO_BASE}/"
    else:
        url_publica = f"/t/{slug}"

    return JSONResponse({
        "ok": True, "slug": slug, "url": url_publica,
        "url_local": f"/t/{slug}",
        "panel": f"/t/{slug}/panel?k={admin_token}",
        "admin_token": admin_token,
    })


def _mover_borrador(url: str, slug: str, basename: str) -> str:
    """Copia un archivo de _borradores a static/tiendas/<slug>/<basename>.<ext>
    y devuelve su URL final. Sirve para el logo y para las fotos de producto.
    Si la URL no es un borrador (ya es definitiva o externa) la deja igual."""
    if not url or "_borradores/" not in url:
        return url or ""
    archivo = url.split("_borradores/")[-1]
    origen = os.path.join(BORRADORES_DIR, archivo)
    if not os.path.exists(origen):
        return ""
    ext = os.path.splitext(archivo)[1]
    carpeta = tiendas.carpeta_uploads(slug)
    destino_nombre = f"{basename}{ext}"
    with open(origen, "rb") as fo, open(os.path.join(carpeta, destino_nombre), "wb") as fd:
        fd.write(fo.read())
    return tiendas.url_uploads(slug, destino_nombre)


def _normalizar_productos(productos: list) -> list:
    """Asegura id, tipos y campos mínimos por producto."""
    out = []
    for i, p in enumerate(productos):
        nombre = (p.get("nombre") or "").strip()
        if not nombre:
            continue
        out.append({
            "id": p.get("id") or tiendas.slugify(nombre) or f"prod-{i+1}",
            "nombre": nombre,
            "precio": _num(p.get("precio")),
            "precio_anterior": _num(p.get("precio_anterior")),
            "descripcion": (p.get("descripcion") or "").strip(),
            "categoria": (p.get("categoria") or "General").strip(),
            "stock": int(_num(p.get("stock")) or 0),
            "imagen": p.get("imagen") or "",
            "seo_titulo": p.get("seo_titulo") or nombre,
        })
    return out


def _num(v):
    """Convierte a número conservando decimales. Devuelve int si es entero
    (1500), float si tiene decimales (29.9), o None si está vacío/ inválido."""
    try:
        if v in (None, "", "null"):
            return None
        f = float(v)
        return int(f) if f == int(f) else f
    except (TypeError, ValueError):
        return None


def _normalizar_servicios(servicios: list) -> list:
    """Asegura id, tipos y campos mínimos por servicio (para agendar citas)."""
    out = []
    for i, s in enumerate(servicios):
        nombre = (s.get("nombre") or "").strip()
        if not nombre:
            continue
        dur = _num(s.get("duracion")) or 30        # minutos
        dur = max(5, min(int(dur), 480))           # entre 5 min y 8 h
        out.append({
            "id": s.get("id") or tiendas.slugify(nombre) or f"serv-{i+1}",
            "nombre": nombre,
            "precio": _num(s.get("precio")),
            "duracion": dur,
            "descripcion": (s.get("descripcion") or "").strip(),
            "imagen": s.get("imagen") or "",
        })
    return out


def _normalizar_horarios(h) -> dict:
    """Valida la config de horario; cae al default si viene incompleta."""
    base = dict(tiendas.HORARIO_DEFAULT)
    if not isinstance(h, dict):
        return base
    dias = h.get("dias")
    if isinstance(dias, list) and dias:
        base["dias"] = sorted({int(d) for d in dias if 0 <= int(d) <= 6})
    if _es_hora(h.get("apertura")):
        base["apertura"] = h["apertura"]
    if _es_hora(h.get("cierre")):
        base["cierre"] = h["cierre"]
    return base


def _es_hora(s) -> bool:
    try:
        datetime.strptime(s, "%H:%M")
        return True
    except (TypeError, ValueError):
        return False


def _slots_disponibles(tienda: dict, servicio: dict, fecha: str):
    """Devuelve los horarios libres (lista de 'HH:MM') para un servicio en una
    fecha YYYY-MM-DD, según el horario del negocio y las citas ya reservadas.
    Devuelve (slots, cerrado)."""
    try:
        dia = datetime.strptime(fecha, "%Y-%m-%d").date()
    except ValueError:
        return [], True

    hoy = datetime.now().date()
    ahora = datetime.now()
    if dia < hoy:
        return [], True

    horarios = tienda.get("horarios") or tiendas.HORARIO_DEFAULT
    if dia.weekday() not in horarios.get("dias", []):
        return [], True   # cerrado ese día de la semana

    apertura = datetime.strptime(horarios.get("apertura", "09:00"), "%H:%M").time()
    cierre = datetime.strptime(horarios.get("cierre", "18:00"), "%H:%M").time()
    dur = int(servicio.get("duracion", 30))

    # Intervalos ya ocupados ese día (cualquier servicio): [(inicio, fin)]
    ocupados = []
    for c in tiendas.citas_de_fecha(tienda, fecha):
        try:
            ini = datetime.combine(dia, datetime.strptime(c["hora"], "%H:%M").time())
            ocupados.append((ini, ini + timedelta(minutes=int(c.get("duracion", 30)))))
        except (KeyError, ValueError):
            continue

    slots = []
    t = datetime.combine(dia, apertura)
    fin_dia = datetime.combine(dia, cierre)
    while t + timedelta(minutes=dur) <= fin_dia:
        s_ini, s_fin = t, t + timedelta(minutes=dur)
        if dia == hoy and s_ini <= ahora + timedelta(minutes=30):
            t += timedelta(minutes=dur)
            continue   # no agendar en el pasado ni con < 30 min de anticipación
        choca = any(s_ini < o_fin and o_ini < s_fin for o_ini, o_fin in ocupados)
        if not choca:
            slots.append(s_ini.strftime("%H:%M"))
        t += timedelta(minutes=dur)
    return slots, False


# ------------------- Storefront por ruta local /t/<slug> -------------------

@app.get("/t/{slug}", response_class=HTMLResponse)
def storefront_local(request: Request, slug: str):
    tienda = tiendas.obtener_tienda(slug)
    if not tienda:
        raise HTTPException(status_code=404, detail="Tienda no encontrada")
    susp = _suspendida_resp(tienda)
    if susp:
        return susp
    return templates.TemplateResponse(
        request, "constructor/tienda.html", _ctx_tienda(request, tienda, ruta_base=f"/t/{slug}")
    )


# ------------------- Página individual de producto (SEO + link directo) -------------------

def _buscar_producto(tienda: dict, producto_id: str):
    for p in tienda.get("productos", []):
        if p.get("id") == producto_id:
            return p
    return None


def _render_producto(request: Request, tienda: dict, producto_id: str, ruta_base: str):
    susp = _suspendida_resp(tienda)
    if susp:
        return susp
    p = _buscar_producto(tienda, producto_id)
    if not p:
        return RedirectResponse(url=(ruta_base or "/"), status_code=303)
    relacionados = [
        x for x in tienda.get("productos", [])
        if x.get("categoria") == p.get("categoria") and x.get("id") != p.get("id")
    ][:4]
    return templates.TemplateResponse(request, "constructor/producto.html", {
        "t": tienda, "p": p, "relacionados": relacionados,
        "ruta_base": ruta_base,
        "base_url": str(request.base_url).rstrip("/"),
        "ia_activa": gemini_ia.disponible(),
        "pago_online": _pago_online(tienda),
    })


@app.get("/producto/{producto_id}", response_class=HTMLResponse)
def producto_subdominio(request: Request, producto_id: str):
    """Página de producto en el subdominio/dominio propio de la tienda."""
    slug = tiendas.resolver_por_host(request.headers.get("host", ""), DOMINIO_BASE)
    if not slug:
        raise HTTPException(status_code=404, detail="Producto no encontrado")
    tienda = tiendas.obtener_tienda(slug)
    if not tienda:
        raise HTTPException(status_code=404, detail="Tienda no encontrada")
    return _render_producto(request, tienda, producto_id, ruta_base="")


@app.get("/t/{slug}/producto/{producto_id}", response_class=HTMLResponse)
def producto_local(request: Request, slug: str, producto_id: str):
    """Página de producto por ruta local (para probar sin subdominio)."""
    tienda = tiendas.obtener_tienda(slug)
    if not tienda:
        raise HTTPException(status_code=404, detail="Tienda no encontrada")
    return _render_producto(request, tienda, producto_id, ruta_base=f"/t/{slug}")


# ------------------- Agendamiento de citas -------------------

DIAS_SEMANA = ["Lunes", "Martes", "Miércoles", "Jueves", "Viernes", "Sábado", "Domingo"]


def _render_reservar(request: Request, tienda: dict, servicio_id: str, ruta_base: str):
    s = tiendas.buscar_servicio(tienda, servicio_id)
    if not s:
        return RedirectResponse(url=(ruta_base or "/"), status_code=303)
    return templates.TemplateResponse(request, "constructor/reservar.html", {
        "t": tienda, "s": s, "ruta_base": ruta_base,
        "base_url": str(request.base_url).rstrip("/"),
    })


@app.get("/reservar/{servicio_id}", response_class=HTMLResponse)
def reservar_subdominio(request: Request, servicio_id: str):
    slug = tiendas.resolver_por_host(request.headers.get("host", ""), DOMINIO_BASE)
    if not slug:
        raise HTTPException(status_code=404, detail="No encontrado")
    tienda = tiendas.obtener_tienda(slug)
    if not tienda:
        raise HTTPException(status_code=404, detail="Tienda no encontrada")
    return _render_reservar(request, tienda, servicio_id, ruta_base="")


@app.get("/t/{slug}/reservar/{servicio_id}", response_class=HTMLResponse)
def reservar_local(request: Request, slug: str, servicio_id: str):
    tienda = tiendas.obtener_tienda(slug)
    if not tienda:
        raise HTTPException(status_code=404, detail="Tienda no encontrada")
    return _render_reservar(request, tienda, servicio_id, ruta_base=f"/t/{slug}")


@app.get("/api/disponibilidad/{slug}")
def api_disponibilidad(slug: str, servicio: str, fecha: str):
    """Devuelve los horarios libres de un servicio en una fecha YYYY-MM-DD."""
    tienda = tiendas.obtener_tienda(slug)
    if not tienda:
        raise HTTPException(status_code=404, detail="Tienda no encontrada")
    s = tiendas.buscar_servicio(tienda, servicio)
    if not s:
        raise HTTPException(status_code=404, detail="Servicio no encontrado")
    slots, cerrado = _slots_disponibles(tienda, s, fecha)
    return JSONResponse({"slots": slots, "cerrado": cerrado})


@app.post("/api/reservar/{slug}")
async def api_reservar(slug: str, request: Request):
    """Crea una cita si el horario sigue libre. Devuelve la confirmación + link de WhatsApp."""
    _rate_limit(request, "reservar", 12, 3600)   # 12 / hora por IP
    tienda = tiendas.obtener_tienda(slug)
    if not tienda:
        raise HTTPException(status_code=404, detail="Tienda no encontrada")
    body = await request.json()
    s = tiendas.buscar_servicio(tienda, body.get("servicio", ""))
    if not s:
        raise HTTPException(status_code=400, detail="Servicio no válido")

    fecha = body.get("fecha", "")
    hora = body.get("hora", "")
    nombre = (body.get("nombre") or "").strip()
    telefono = (body.get("telefono") or "").strip()
    if not (nombre and telefono and fecha and hora):
        raise HTTPException(status_code=400, detail="Faltan datos de la reserva.")

    # Revalida que el horario siga libre (evita doble reserva).
    slots, cerrado = _slots_disponibles(tienda, s, fecha)
    if cerrado or hora not in slots:
        raise HTTPException(status_code=409, detail="Ese horario ya no está disponible. Elige otro.")

    cita = {
        "id": secrets.token_hex(6),
        "servicio_id": s["id"],
        "servicio_nombre": s["nombre"],
        "duracion": int(s.get("duracion", 30)),
        "fecha": fecha,
        "hora": hora,
        "cliente_nombre": nombre,
        "cliente_telefono": telefono,
        "estado": "agendada",
        "creada": datetime.now().isoformat(),
    }
    tiendas.agregar_cita(slug, cita)

    # CRM: cada cita entra al pipeline como lead (o suma al lead existente).
    _capturar_lead(slug, tienda, nombre=nombre, telefono=telefono,
                   origen="Cita", nota=f"Agendó {s['nombre']} el {fecha} a las {hora}.",
                   valor=s.get("precio"))

    # Link de WhatsApp para confirmar con el negocio (si tiene número).
    wanum = "".join(ch for ch in (tienda.get("whatsapp") or "") if ch.isdigit())
    wa_url = ""
    if wanum:
        from urllib.parse import quote
        msg = (f"¡Hola {tienda.get('nombre')}! Acabo de agendar una cita: "
               f"{s['nombre']} el {fecha} a las {hora}. Mi nombre es {nombre}.")
        wa_url = f"https://wa.me/{wanum}?text={quote(msg)}"

    return JSONResponse({"ok": True, "cita": cita, "wa_url": wa_url})


# ------------------- Siembra de catálogo SPA de ejemplo (admin) -------------------

SPA_SERVICIOS = [
    {"nombre": "Masaje relajante 60 min", "precio": 650, "duracion": 60, "descripcion": "Masaje corporal de relajación con aceites aromáticos."},
    {"nombre": "Masaje descontracturante 60 min", "precio": 750, "duracion": 60, "descripcion": "Libera la tensión muscular de espalda y cuello."},
    {"nombre": "Masaje con piedras calientes 75 min", "precio": 850, "duracion": 75, "descripcion": "Terapia con piedras volcánicas tibias."},
    {"nombre": "Masaje de pareja 60 min", "precio": 1300, "duracion": 60, "descripcion": "Sesión simultánea de relajación para dos personas."},
    {"nombre": "Aromaterapia 60 min", "precio": 700, "duracion": 60, "descripcion": "Masaje con aceites esenciales personalizados."},
    {"nombre": "Reflexología podal 45 min", "precio": 400, "duracion": 45, "descripcion": "Estimulación de puntos de presión en los pies."},
    {"nombre": "Facial hidratante", "precio": 550, "duracion": 50, "descripcion": "Limpieza e hidratación profunda del rostro."},
    {"nombre": "Facial anti-edad", "precio": 700, "duracion": 60, "descripcion": "Tratamiento reafirmante con colágeno."},
    {"nombre": "Limpieza facial profunda", "precio": 600, "duracion": 60, "descripcion": "Extracción y purificación de la piel."},
    {"nombre": "Exfoliación corporal", "precio": 500, "duracion": 45, "descripcion": "Remueve células muertas y suaviza la piel."},
    {"nombre": "Envoltura corporal detox", "precio": 650, "duracion": 60, "descripcion": "Envoltura nutritiva desintoxicante."},
    {"nombre": "Manicure spa", "precio": 250, "duracion": 40, "descripcion": "Cuidado de uñas con tratamiento hidratante."},
    {"nombre": "Pedicure spa", "precio": 300, "duracion": 50, "descripcion": "Cuidado completo de pies y uñas."},
    {"nombre": "Manicure + Pedicure", "precio": 500, "duracion": 80, "descripcion": "Paquete completo de manos y pies."},
    {"nombre": "Depilación con cera (piernas)", "precio": 400, "duracion": 45, "descripcion": "Depilación de piernas completas con cera tibia."},
    {"nombre": "Depilación facial", "precio": 150, "duracion": 20, "descripcion": "Depilación de ceja, bozo o mentón."},
    {"nombre": "Sauna / Vapor (sesión)", "precio": 200, "duracion": 30, "descripcion": "Sesión de relajación y desintoxicación."},
    {"nombre": "Tratamiento capilar", "precio": 450, "duracion": 45, "descripcion": "Hidratación y nutrición intensiva del cabello."},
    {"nombre": "Maquillaje profesional", "precio": 600, "duracion": 60, "descripcion": "Maquillaje para evento social o sesión."},
    {"nombre": "Paquete Relax (masaje + facial)", "precio": 1100, "duracion": 120, "descripcion": "Masaje relajante seguido de facial hidratante."},
]

_SPA_CLIENTES = [
    ("Ana Torres", "8112345670"), ("Carla Méndez", "8112345671"), ("Sofía Ramírez", "8112345672"),
    ("Luis Hernández", "8112345673"), ("Daniela Cruz", "8112345674"), ("Mariana López", "8112345675"),
    ("Jorge Castillo", "8112345676"), ("Paola Núñez", "8112345677"), ("Regina Flores", "8112345678"),
    ("Andrea Vega", "8112345679"), ("Fernanda Ríos", "8112345680"), ("Valeria Soto", "8112345681"),
]
_SPA_HORAS = ["10:00", "11:30", "13:00", "16:00", "17:30"]
_SPA_TERAPEUTAS = ["Mariana Ríos", "Sofía Herrera", "Daniela Campos", "Regina Ávila"]


def _sembrar_spa(slug: str, t: dict) -> dict:
    """Siembra el catálogo SPA + citas de ejemplo en la tienda `t`. Idempotente
    en servicios; citas solo si la tienda tiene menos de 5."""
    # 1) Servicios (no duplica: salta los que ya existan por nombre)
    existentes = {(s.get("nombre") or "").lower() for s in t.get("servicios", [])}
    creados = 0
    for sv in SPA_SERVICIOS:
        if sv["nombre"].lower() in existentes:
            continue
        tiendas.agregar(slug, "servicios", {
            "id": secrets.token_hex(4), "nombre": sv["nombre"], "precio": float(sv["precio"]),
            "duracion": sv["duracion"], "descripcion": sv["descripcion"], "imagen": "",
        }, al_inicio=False)
        creados += 1
    # Rellena descripciones faltantes en servicios existentes (idempotente)
    giro = t.get("giro", "") or "spa y bienestar"
    descripciones_creadas = 0
    for s in tiendas.obtener_tienda(slug).get("servicios", []):
        if not (s.get("descripcion") or "").strip() and s.get("id"):
            desc = gemini_ia.describir_servicio(s.get("nombre", ""), giro)
            if desc:
                tiendas.actualizar_item(slug, "servicios", s["id"], {"descripcion": desc})
                descripciones_creadas += 1
    # Terapeutas de ejemplo (idempotente por nombre)
    equipo_nombres = {(m.get("nombre") or "").lower() for m in t.get("equipo", [])}
    terapeutas_creados = 0
    for nombre in _SPA_TERAPEUTAS:
        if nombre.lower() in equipo_nombres:
            continue
        tiendas.agregar(slug, "equipo", {
            "id": secrets.token_hex(5), "nombre": nombre, "pct_comision": 0.40,
            "activo": True, "creado": datetime.now().isoformat(),
        }, al_inicio=False)
        terapeutas_creados += 1
    # Asegura que la tienda muestre servicios y tenga horario para agendar
    cambios = {}
    if t.get("tipo") not in ("servicios", "ambos"):
        cambios["tipo"] = "ambos" if t.get("productos") else "servicios"
    if not t.get("horarios"):
        cambios["horarios"] = dict(tiendas.HORARIO_DEFAULT)
    if cambios:
        tiendas.actualizar_tienda(slug, cambios)
    # 2) Citas de ejemplo (solo si aún no hay muchas, para no duplicar)
    t2 = tiendas.obtener_tienda(slug)
    servs = t2.get("servicios", [])
    citas_creadas = 0
    if servs and len(t2.get("citas", [])) < 5:
        hoy = _date.today()
        i = 0
        for dia in range(1, 8):  # próximos 7 días
            f = hoy + timedelta(days=dia)
            if f.weekday() == 6:  # domingo, cerrado
                continue
            for _ in range(2):   # 2 citas por día
                sv = servs[i % len(servs)]
                cli = _SPA_CLIENTES[i % len(_SPA_CLIENTES)]
                cita = {
                    "id": secrets.token_hex(6), "servicio_id": sv["id"], "servicio_nombre": sv["nombre"],
                    "duracion": int(sv.get("duracion") or 60), "fecha": f.isoformat(),
                    "hora": _SPA_HORAS[i % len(_SPA_HORAS)],
                    "cliente_nombre": cli[0], "cliente_telefono": cli[1],
                    "estado": "agendada", "creada": datetime.now().isoformat(),
                }
                tiendas.agregar_cita(slug, cita)
                citas_creadas += 1
                i += 1
    return {"ok": True, "servicios_creados": creados, "citas_creadas": citas_creadas,
            "terapeutas_creados": terapeutas_creados, "descripciones_creadas": descripciones_creadas,
            "servicios_totales": len(servs)}


@app.post("/api/seed-spa/{slug}")
def api_seed_spa(slug: str, k: str = ""):
    """Siembra catálogo SPA vía token de admin de la tienda (o sesión del dueño)."""
    t = _tienda_admin(slug, k)
    return JSONResponse(_sembrar_spa(slug, t))


@app.get("/api/citas/{slug}")
def api_citas(slug: str, k: str = "", desde: str = "", hasta: str = ""):
    """Lista las citas (no canceladas) en un rango, para la vista calendario."""
    t = _tienda_admin(slug, k)  # Pro+ (panel)
    citas = [c for c in t.get("citas", []) if c.get("estado") != "cancelada"
             and (not desde or _en_rango(c.get("fecha", ""), desde, hasta))]
    return JSONResponse({
        "citas": citas,
        "horarios": t.get("horarios", {}) or {},
        "equipo": [{"id": m.get("id"), "nombre": m.get("nombre")} for m in t.get("equipo", [])],
    })


@app.post("/admin/tienda/{slug}/seed-spa")
def admin_seed_spa(request: Request, slug: str):
    """Botón del panel super-admin: sembrar catálogo SPA de ejemplo en una tienda."""
    _guard_admin(request)
    t = tiendas.obtener_tienda(slug)
    if t:
        _sembrar_spa(slug, t)
    return RedirectResponse(url="/admin", status_code=303)


# ------------------- Captura pública de leads (desde la tienda) -------------------

@app.post("/api/lead/{slug}")
async def api_lead_publico(slug: str, request: Request):
    """Captura un lead desde el storefront (clic en 'Pedir por WhatsApp').
    Público: alimenta el pipeline del dueño antes de que el chat de WhatsApp ocurra."""
    _rate_limit(request, "lead", 20, 3600)   # 20 / hora por IP
    tienda = tiendas.obtener_tienda(slug)
    if not tienda:
        raise HTTPException(status_code=404, detail="Tienda no encontrada")
    b = await request.json()
    telefono = (b.get("telefono") or "").strip()
    nombre = (b.get("nombre") or "").strip()
    if not telefono and not nombre:
        return JSONResponse({"ok": False})   # sin datos no capturamos
    interes = (b.get("interes") or "").strip()
    nota = f"Interesado en {interes} (desde la tienda)" if interes else "Contacto desde la tienda"
    _capturar_lead(slug, tienda, nombre=nombre or "Cliente", telefono=telefono,
                   origen=b.get("origen") or "WhatsApp", nota=nota, valor=_num(b.get("valor")))
    return JSONResponse({"ok": True})


# ------------------- CRM: panel del dueño + API de leads -------------------

def _check_admin(tienda: dict, k: str):
    """Valida el token de admin de la tienda. Lanza 403 si no coincide."""
    token = tienda.get("admin_token") or ""
    if not token or k != token:
        raise HTTPException(status_code=403, detail="Acceso no autorizado al panel.")


def _capturar_lead(slug, tienda, nombre, telefono, origen, nota="", valor=None):
    """Crea un lead nuevo o suma una nota al lead existente (mismo teléfono)."""
    tel = (telefono or "").strip()
    existente = tiendas.buscar_lead_por_telefono(tienda, tel) if tel else None
    evento = {"fecha": datetime.now().isoformat(), "texto": nota or f"Contacto vía {origen}"}
    if existente:
        hist = existente.get("historial", [])
        hist.append(evento)
        cambios = {"historial": hist}
        if valor and not existente.get("valor"):
            cambios["valor"] = valor
        tiendas.actualizar_lead(slug, existente["id"], cambios)
        return existente
    lead = {
        "id": secrets.token_hex(6),
        "nombre": (nombre or "Cliente").strip(),
        "telefono": tel,
        "origen": origen,
        "etapa": "Nuevo",
        "valor": valor,
        "notas": "",
        "proximo_contacto": "",
        "asignado": "",
        "historial": [evento],
        "creado": datetime.now().isoformat(),
        "actualizado": datetime.now().isoformat(),
    }
    return tiendas.crear_lead(slug, lead)


def _panel_ctx(request, tienda, ruta_base):
    hoy = _date.today().isoformat()
    # próximas citas (de hoy en adelante), ordenadas
    citas = sorted(
        [c for c in tienda.get("citas", []) if c.get("fecha", "") >= hoy and c.get("estado") != "cancelada"],
        key=lambda c: (c.get("fecha", ""), c.get("hora", "")),
    )
    plan = _plan_de_tienda(tienda)
    # Checklist de primer uso (estado real de configuración de la tienda)
    pg = tienda.get("pagos", {}) or {}
    n_catalogo = len(tienda.get("productos", [])) + len(tienda.get("servicios", []))
    onboarding = [
        {"icon": "🎨", "label": "Personaliza tu tienda (logo y colores)",
         "done": bool(tienda.get("logo")), "url": f"{ruta_base}/editar"},
        {"icon": "📦", "label": "Agrega tus productos o servicios",
         "done": n_catalogo > 0, "url": f"{ruta_base}/catalogo"},
        {"icon": "💬", "label": "Pon tu WhatsApp para recibir pedidos",
         "done": bool(tienda.get("whatsapp")), "url": f"{ruta_base}/editar"},
        {"icon": "💳", "label": "Activa cobros en línea (SPEI o tarjeta)",
         "done": bool(pg.get("spei_activo") or pg.get("mp_activo")), "url": f"{ruta_base}/editar"},
    ]
    onboarding_pend = sum(1 for x in onboarding if not x["done"])
    return {
        "request": request, "t": tienda, "ruta_base": ruta_base,
        "via_token": not _es_dueno(request, tienda),
        "onboarding": onboarding, "onboarding_pend": onboarding_pend,
        "etapas": tiendas.ETAPAS_CRM, "k": tienda.get("admin_token", ""),
        "citas_proximas": citas, "tipo": tienda.get("tipo", "productos"),
        "servicios": tienda.get("servicios", []),
        "productos": tienda.get("productos", []),
        "puede_pos": permite(plan, "pos"),
        "equipo": tienda.get("equipo", []),
        "metodos": tiendas.METODOS_PAGO,
        "cuentas": tiendas.CUENTAS_CONTABLES,
        "moneda": tienda.get("moneda", "MXN"),
        "hoy": _date.today().isoformat(),
        "plan": plan, "plan_label": PLAN_LABEL.get(plan, "Gratis"),
        "puede_logins": permite(plan, "logins_equipo"),
        "puede_gastos": permite(plan, "gastos"),                    # Pro+: registrar y clasificar
        "puede_gastos_avanzado": permite(plan, "gastos_avanzado"),  # Escala: presupuestos y recurrentes
    }


def _es_dueno(request: Request, tienda: dict) -> bool:
    u = _usuario_actual(request)
    return bool(u and (tienda.get("owner_email") or "").lower() == u["email"])


def _autorizar_panel(request: Request, tienda: dict, k: str):
    """Acceso al panel: dueño logueado (sesión) O token válido en la URL."""
    if _es_dueno(request, tienda):
        return
    _check_admin(tienda, k)


def _panel_o_upsell(request: Request, tienda: dict, ruta_base: str):
    """Renderiza el panel si el plan lo incluye; si no, una pantalla de upsell."""
    plan = _plan_de_tienda(tienda)
    if not permite(plan, "panel"):
        return templates.TemplateResponse(request, "constructor/panel_upsell.html", {
            "t": tienda, "ruta_base": ruta_base, "plan": plan,
            "plan_label": PLAN_LABEL.get(plan, "Gratis"),
        })
    return templates.TemplateResponse(request, "constructor/panel.html", _panel_ctx(request, tienda, ruta_base))


@app.get("/panel", response_class=HTMLResponse)
def panel_subdominio(request: Request, k: str = ""):
    slug = tiendas.resolver_por_host(request.headers.get("host", ""), DOMINIO_BASE)
    if not slug:
        raise HTTPException(status_code=404, detail="No encontrado")
    tienda = tiendas.obtener_tienda(slug)
    if not tienda:
        raise HTTPException(status_code=404, detail="Tienda no encontrada")
    _autorizar_panel(request, tienda, k)
    return _panel_o_upsell(request, tienda, "")


@app.get("/t/{slug}/panel", response_class=HTMLResponse)
def panel_local(request: Request, slug: str, k: str = ""):
    tienda = tiendas.obtener_tienda(slug)
    if not tienda:
        raise HTTPException(status_code=404, detail="Tienda no encontrada")
    _autorizar_panel(request, tienda, k)
    return _panel_o_upsell(request, tienda, f"/t/{slug}")


# ------------------- SEO: sitemap.xml + robots.txt por tienda -------------------

def _base_publica(request: Request, slug: str) -> str:
    """URL pública base de la tienda (subdominio en prod, /t/<slug> en local)."""
    if DOMINIO_BASE and DOMINIO_BASE != "localhost":
        return f"https://{slug}.{DOMINIO_BASE}"
    return str(request.base_url).rstrip("/") + f"/t/{slug}"


def _xml_escape(s: str) -> str:
    return (s or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _render_sitemap(request: Request, slug: str):
    tienda = tiendas.obtener_tienda(slug)
    if not tienda:
        raise HTTPException(status_code=404, detail="Tienda no encontrada")
    base = _base_publica(request, slug)
    locs = [f"{base}/"]
    for p in tienda.get("productos", []):
        locs.append(f"{base}/producto/{p.get('id')}")
    for s in tienda.get("servicios", []):
        locs.append(f"{base}/reservar/{s.get('id')}")
    cuerpo = "".join(f"<url><loc>{_xml_escape(u)}</loc></url>" for u in locs)
    xml = ('<?xml version="1.0" encoding="UTF-8"?>'
           '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">' + cuerpo + "</urlset>")
    return Response(xml, media_type="application/xml")


def _render_robots(request: Request, slug: str):
    if slug:
        base = _base_publica(request, slug)
        txt = f"User-agent: *\nAllow: /\nSitemap: {base}/sitemap.xml\n"
    else:  # apex (katia.work) — no indexar paneles ni APIs
        txt = "User-agent: *\nAllow: /\nDisallow: /api/\nDisallow: /panel\nDisallow: /t/\n"
    return Response(txt, media_type="text/plain")


@app.get("/sitemap.xml")
def sitemap_sub(request: Request):
    slug = tiendas.resolver_por_host(request.headers.get("host", ""), DOMINIO_BASE)
    if not slug:
        raise HTTPException(status_code=404, detail="No encontrado")
    return _render_sitemap(request, slug)


@app.get("/t/{slug}/sitemap.xml")
def sitemap_local(request: Request, slug: str):
    return _render_sitemap(request, slug)


@app.get("/robots.txt")
def robots_sub(request: Request):
    slug = tiendas.resolver_por_host(request.headers.get("host", ""), DOMINIO_BASE)
    return _render_robots(request, slug or "")


@app.get("/t/{slug}/robots.txt")
def robots_local(request: Request, slug: str):
    return _render_robots(request, slug)


# ------------------- Editar tienda (diseño + información) -------------------

def _ctx_editar(request: Request, tienda: dict, ruta_base: str):
    plan = _plan_de_tienda(tienda)
    return {
        "request": request, "t": tienda, "ruta_base": ruta_base,
        "via_token": not _es_dueno(request, tienda),
        "k": tienda.get("admin_token", ""), "plan": plan,
        "plan_label": PLAN_LABEL.get(plan, "Gratis"),
        "temas": TEMAS, "paleta": PALETA_GRATIS,
        "colores_full": _rank(plan) >= _rank("tienda"),
        "redes_full": permite(plan, "redes_sociales"),
    }


@app.get("/editar", response_class=HTMLResponse)
def editar_subdominio(request: Request, k: str = ""):
    slug = tiendas.resolver_por_host(request.headers.get("host", ""), DOMINIO_BASE)
    if not slug:
        raise HTTPException(status_code=404, detail="No encontrado")
    tienda = tiendas.obtener_tienda(slug)
    if not tienda:
        raise HTTPException(status_code=404, detail="Tienda no encontrada")
    _autorizar_panel(request, tienda, k)
    return templates.TemplateResponse(request, "constructor/editar.html", _ctx_editar(request, tienda, ""))


@app.get("/t/{slug}/editar", response_class=HTMLResponse)
def editar_local(request: Request, slug: str, k: str = ""):
    tienda = tiendas.obtener_tienda(slug)
    if not tienda:
        raise HTTPException(status_code=404, detail="Tienda no encontrada")
    _autorizar_panel(request, tienda, k)
    return templates.TemplateResponse(request, "constructor/editar.html", _ctx_editar(request, tienda, f"/t/{slug}"))


@app.post("/api/tienda/{slug}")
async def api_editar_tienda(request: Request, slug: str, k: str = ""):
    """Actualiza info y diseño de la tienda, respetando el plan."""
    tienda = tiendas.obtener_tienda(slug)
    if not tienda:
        raise HTTPException(status_code=404, detail="Tienda no encontrada")
    _autorizar_panel(request, tienda, k)
    plan = _plan_de_tienda(tienda)
    b = await request.json()
    cambios = {}
    for campo in ("nombre", "eslogan", "sobre_nosotros", "giro", "ciudad", "whatsapp", "correo"):
        if campo in b:
            cambios[campo] = (b[campo] or "").strip()
    if cambios.get("nombre") == "":
        raise HTTPException(status_code=400, detail="El nombre no puede quedar vacío.")
    # Plantilla (gating)
    if "tema" in b:
        cambios["tema"] = b["tema"] if (b["tema"] in TEMAS and tema_permitido(plan, b["tema"])) else tienda.get("tema", "aurora")
    # Colores (gating)
    if "color" in b:
        if _rank(plan) >= _rank("tienda"):
            cambios["color"] = b["color"]
        else:
            cambios["color"] = b["color"] if b["color"] in PALETA_GRATIS else tienda.get("color")
    if "color_2" in b and _rank(plan) >= _rank("tienda"):
        cambios["color_2"] = b["color_2"]
    # Redes sociales (Tienda+)
    if "redes" in b and permite(plan, "redes_sociales"):
        cambios["redes"] = _normalizar_redes(b["redes"])
    # Cobros (Tienda+): datos SPEI + token MercadoPago
    if "pagos" in b and permite(plan, "checkout_online"):
        pg = b["pagos"] or {}
        cambios["pagos"] = {
            "titular": (pg.get("titular") or "").strip(),
            "banco": (pg.get("banco") or "").strip(),
            "clabe": (pg.get("clabe") or "").strip(),
            "instrucciones": (pg.get("instrucciones") or "").strip(),
            "mercadopago_token": (pg.get("mercadopago_token") or "").strip(),
            "spei_activo": bool(pg.get("spei_activo")),
            "mp_activo": bool(pg.get("mp_activo")),
        }
    # Logo / hero (mueve si viene un borrador nuevo)
    if b.get("logo"):
        cambios["logo"] = _mover_borrador(b["logo"], slug, "logo") or tienda.get("logo", "")
    if "hero_imagen" in b:
        cambios["hero_imagen"] = _mover_borrador(b["hero_imagen"], slug, "hero")
    tiendas.actualizar_tienda(slug, cambios)
    return JSONResponse({"ok": True})


@app.get("/api/crm/{slug}/leads")
def api_crm_leads(slug: str, k: str = ""):
    tienda = tiendas.obtener_tienda(slug)
    if not tienda:
        raise HTTPException(status_code=404, detail="Tienda no encontrada")
    _check_admin(tienda, k)
    _gate(tienda, "crm")
    leads = tienda.get("leads", [])
    hoy = _date.today().isoformat()
    # Métricas
    abiertos = [l for l in leads if l.get("etapa") in tiendas.ETAPAS_ABIERTAS]
    pipeline_valor = sum(float(l.get("valor") or 0) for l in abiertos)
    ganados = [l for l in leads if l.get("etapa") == "Ganado"]
    vencidos = [l for l in leads if l.get("proximo_contacto") and l["proximo_contacto"] <= hoy
                and l.get("etapa") in tiendas.ETAPAS_ABIERTAS]
    stats = {
        "total": len(leads),
        "abiertos": len(abiertos),
        "ganados": len(ganados),
        "pipeline_valor": pipeline_valor,
        "ganado_valor": sum(float(l.get("valor") or 0) for l in ganados),
        "por_contactar": len(vencidos),
    }
    return JSONResponse({"leads": leads, "etapas": tiendas.ETAPAS_CRM, "stats": stats, "hoy": hoy})


@app.post("/api/crm/{slug}/leads")
async def api_crm_crear_lead(slug: str, request: Request, k: str = ""):
    tienda = tiendas.obtener_tienda(slug)
    if not tienda:
        raise HTTPException(status_code=404, detail="Tienda no encontrada")
    _check_admin(tienda, k)
    _gate(tienda, "crm")
    b = await request.json()
    nombre = (b.get("nombre") or "").strip()
    if not nombre:
        raise HTTPException(status_code=400, detail="El nombre es obligatorio.")
    lead = {
        "id": secrets.token_hex(6),
        "nombre": nombre,
        "telefono": (b.get("telefono") or "").strip(),
        "origen": b.get("origen") or "Manual",
        "etapa": b.get("etapa") if b.get("etapa") in tiendas.ETAPAS_CRM else "Nuevo",
        "valor": _num(b.get("valor")),
        "notas": (b.get("notas") or "").strip(),
        "proximo_contacto": b.get("proximo_contacto") or "",
        "asignado": (b.get("asignado") or "").strip(),
        "asignado_nombre": (_miembro(tienda, b.get("asignado", "")) or {}).get("nombre", ""),
        "historial": [{"fecha": datetime.now().isoformat(), "texto": "Lead creado manualmente"}],
        "creado": datetime.now().isoformat(),
        "actualizado": datetime.now().isoformat(),
    }
    tiendas.crear_lead(slug, lead)
    return JSONResponse({"ok": True, "lead": lead})


@app.patch("/api/crm/{slug}/leads/{lead_id}")
async def api_crm_editar_lead(slug: str, lead_id: str, request: Request, k: str = ""):
    tienda = tiendas.obtener_tienda(slug)
    if not tienda:
        raise HTTPException(status_code=404, detail="Tienda no encontrada")
    _check_admin(tienda, k)
    _gate(tienda, "crm")
    b = await request.json()
    lead = tiendas.buscar_lead(tienda, lead_id)
    if not lead:
        raise HTTPException(status_code=404, detail="Lead no encontrado")

    cambios = {}
    for campo in ("nombre", "telefono", "origen", "notas", "proximo_contacto", "asignado"):
        if campo in b:
            cambios[campo] = (b[campo] or "").strip() if isinstance(b[campo], str) else b[campo]
    if "asignado" in cambios:
        m = _miembro(tienda, cambios["asignado"])
        cambios["asignado_nombre"] = m["nombre"] if m else ""
    if "valor" in b:
        cambios["valor"] = _num(b["valor"])
    if "etapa" in b and b["etapa"] in tiendas.ETAPAS_CRM:
        cambios["etapa"] = b["etapa"]
        # Registra el cambio de etapa en el historial
        if b["etapa"] != lead.get("etapa"):
            if b["etapa"] == "Ganado":
                cambios["fecha_ganado"] = _date.today().isoformat()
            hist = lead.get("historial", [])
            hist.append({"fecha": datetime.now().isoformat(),
                         "texto": f"Etapa: {lead.get('etapa')} → {b['etapa']}"})
            cambios["historial"] = hist
    # Nota nueva al historial (registro libre de contacto)
    if b.get("nota_nueva"):
        hist = cambios.get("historial", lead.get("historial", []))
        hist.append({"fecha": datetime.now().isoformat(), "texto": b["nota_nueva"].strip()})
        cambios["historial"] = hist

    actualizado = tiendas.actualizar_lead(slug, lead_id, cambios)
    return JSONResponse({"ok": True, "lead": actualizado})


@app.delete("/api/crm/{slug}/leads/{lead_id}")
def api_crm_eliminar_lead(slug: str, lead_id: str, k: str = ""):
    tienda = tiendas.obtener_tienda(slug)
    if not tienda:
        raise HTTPException(status_code=404, detail="Tienda no encontrada")
    _check_admin(tienda, k)
    _gate(tienda, "crm")
    ok = tiendas.eliminar_lead(slug, lead_id)
    return JSONResponse({"ok": ok})


# ------------------- Caja y Reportes (equipo, ingresos, gastos) -------------------

def _tienda_admin(slug: str, k: str, cap: str = "panel"):
    """Obtiene la tienda, valida el token de admin y el plan (gating). Devuelve la tienda."""
    tienda = tiendas.obtener_tienda(slug)
    if not tienda:
        raise HTTPException(status_code=404, detail="Tienda no encontrada")
    _check_admin(tienda, k)
    if cap:
        _gate(tienda, cap)
    return tienda


def _miembro(tienda: dict, agente_id: str):
    for m in tienda.get("equipo", []):
        if m.get("id") == agente_id:
            return m
    return None


def _en_rango(fecha: str, desde: str, hasta: str) -> bool:
    if not fecha:
        return False
    if desde and fecha < desde:
        return False
    if hasta and fecha > hasta:
        return False
    return True


# ---- Equipo ----
@app.get("/api/equipo/{slug}")
def api_equipo_listar(slug: str, k: str = ""):
    t = _tienda_admin(slug, k)
    return JSONResponse({"equipo": t.get("equipo", [])})


@app.post("/api/equipo/{slug}")
async def api_equipo_crear(slug: str, request: Request, k: str = ""):
    _tienda_admin(slug, k)
    b = await request.json()
    nombre = (b.get("nombre") or "").strip()
    if not nombre:
        raise HTTPException(status_code=400, detail="El nombre es obligatorio.")
    pct = _num(b.get("pct_comision"))
    pct = 0.40 if pct is None else max(0.0, min(float(pct), 1.0))
    m = {"id": secrets.token_hex(5), "nombre": nombre, "pct_comision": pct,
         "activo": True, "creado": datetime.now().isoformat()}
    tiendas.agregar(slug, "equipo", m, al_inicio=False)
    return JSONResponse({"ok": True, "miembro": m})


@app.patch("/api/equipo/{slug}/{mid}")
async def api_equipo_editar(slug: str, mid: str, request: Request, k: str = ""):
    _tienda_admin(slug, k)
    b = await request.json()
    cambios = {}
    if "nombre" in b:
        cambios["nombre"] = (b["nombre"] or "").strip()
    if "pct_comision" in b:
        pct = _num(b["pct_comision"])
        cambios["pct_comision"] = 0.0 if pct is None else max(0.0, min(float(pct), 1.0))
    if "activo" in b:
        cambios["activo"] = bool(b["activo"])
    m = tiendas.actualizar_item(slug, "equipo", mid, cambios)
    return JSONResponse({"ok": bool(m), "miembro": m})


@app.delete("/api/equipo/{slug}/{mid}")
def api_equipo_eliminar(slug: str, mid: str, k: str = ""):
    _tienda_admin(slug, k)
    return JSONResponse({"ok": tiendas.eliminar_item(slug, "equipo", mid)})


@app.post("/api/equipo/{slug}/{mid}/invitar")
async def api_equipo_invitar(slug: str, mid: str, request: Request, k: str = ""):
    """El dueño crea el acceso (login) de un miembro del equipo como especialista."""
    t = _tienda_admin(slug, k)
    _gate(t, "logins_equipo")
    m = _miembro(t, mid)
    if not m:
        raise HTTPException(status_code=404, detail="Miembro no encontrado")
    b = await request.json()
    u, error = usuarios.crear(
        b.get("email", ""), b.get("password", ""), nombre=m["nombre"],
        rol="especialista", tienda_slug=slug, miembro_id=mid,
    )
    if error:
        return JSONResponse({"ok": False, "error": error}, status_code=400)
    tiendas.actualizar_item(slug, "equipo", mid, {"email": u["email"]})
    return JSONResponse({"ok": True, "email": u["email"]})


# ------------------- Especialista: vista limitada (Mi caja) -------------------

def _req_especialista(request: Request, slug: str):
    u = _usuario_actual(request)
    if not u or u.get("rol") != "especialista" or u.get("tienda_slug") != slug:
        raise HTTPException(status_code=403, detail="Acceso no autorizado.")
    return u


@app.get("/especialista", response_class=HTMLResponse)
def especialista_home(request: Request):
    u = _usuario_actual(request)
    if not u:
        return RedirectResponse(url="/cuenta?next=/especialista", status_code=303)
    if u.get("rol") != "especialista":
        return RedirectResponse(url="/mis-tiendas", status_code=303)
    tienda = tiendas.obtener_tienda(u.get("tienda_slug", ""))
    if not tienda:
        raise HTTPException(status_code=404, detail="Tienda no encontrada")
    return templates.TemplateResponse(request, "constructor/especialista.html", {
        "t": tienda, "u": u, "miembro": _miembro(tienda, u.get("miembro_id", "")),
        "servicios": tienda.get("servicios", []), "metodos": tiendas.METODOS_PAGO,
        "moneda": tienda.get("moneda", "MXN"), "hoy": _date.today().isoformat(),
        "etapas": tiendas.ETAPAS_CRM, "tipo": tienda.get("tipo", "productos"),
    })


@app.get("/api/mi-caja/{slug}")
def api_micaja_listar(request: Request, slug: str):
    u = _req_especialista(request, slug)
    t = tiendas.obtener_tienda(slug)
    hoy = _date.today().isoformat()
    movs = [m for m in t.get("movimientos", [])
            if m.get("agente_id") == u["miembro_id"] and m.get("fecha") == hoy]
    miembro = _miembro(t, u["miembro_id"])
    pct = float(miembro.get("pct_comision") or 0) if miembro else 0
    ventas = sum(float(m.get("monto") or 0) for m in movs)
    cobrado = sum(float(m.get("pago_recibido") or 0) for m in movs)
    return JSONResponse({"movimientos": movs, "ventas": ventas, "cobrado": cobrado,
                         "comision": round(ventas * pct, 2), "pct": pct})


@app.post("/api/mi-caja/{slug}")
async def api_micaja_crear(request: Request, slug: str):
    u = _req_especialista(request, slug)
    t = tiendas.obtener_tienda(slug)
    b = await request.json()
    b["agente_id"] = u["miembro_id"]   # fuerza el registro a su nombre
    mov = _nuevo_movimiento(t, b)
    tiendas.agregar(slug, "movimientos", mov)
    return JSONResponse({"ok": True, "movimiento": mov})


# ---- Mis leads (CRM del vendedor) ----
@app.get("/api/mis-leads/{slug}")
def api_misleads_listar(request: Request, slug: str):
    u = _req_especialista(request, slug)
    t = tiendas.obtener_tienda(slug)
    mios = [l for l in t.get("leads", []) if l.get("asignado") == u["miembro_id"]]
    return JSONResponse({"leads": mios, "etapas": tiendas.ETAPAS_CRM, "hoy": _date.today().isoformat()})


@app.patch("/api/mis-leads/{slug}/{lead_id}")
async def api_misleads_editar(request: Request, slug: str, lead_id: str):
    u = _req_especialista(request, slug)
    t = tiendas.obtener_tienda(slug)
    lead = tiendas.buscar_lead(t, lead_id)
    if not lead or lead.get("asignado") != u["miembro_id"]:
        raise HTTPException(status_code=403, detail="Ese lead no está asignado a ti.")
    b = await request.json()
    cambios = {}
    if "proximo_contacto" in b:
        cambios["proximo_contacto"] = (b["proximo_contacto"] or "").strip()
    if "etapa" in b and b["etapa"] in tiendas.ETAPAS_CRM and b["etapa"] != lead.get("etapa"):
        cambios["etapa"] = b["etapa"]
        hist = lead.get("historial", [])
        hist.append({"fecha": datetime.now().isoformat(),
                     "texto": f"[{u.get('nombre', 'vendedor')}] Etapa: {lead.get('etapa')} → {b['etapa']}"})
        cambios["historial"] = hist
    if b.get("nota_nueva"):
        hist = cambios.get("historial", lead.get("historial", []))
        hist.append({"fecha": datetime.now().isoformat(),
                     "texto": f"[{u.get('nombre', 'vendedor')}] {b['nota_nueva'].strip()}"})
        cambios["historial"] = hist
    actualizado = tiendas.actualizar_lead(slug, lead_id, cambios)
    return JSONResponse({"ok": True, "lead": actualizado})


# ---- Movimientos (caja / ingresos) ----
@app.get("/api/movimientos/{slug}")
def api_mov_listar(slug: str, k: str = "", desde: str = "", hasta: str = ""):
    t = _tienda_admin(slug, k)
    movs = [m for m in t.get("movimientos", []) if _en_rango(m.get("fecha", ""), desde, hasta)]
    return JSONResponse({"movimientos": movs, "metodos": tiendas.METODOS_PAGO})


def _nuevo_movimiento(tienda: dict, b: dict) -> dict:
    """Construye un movimiento desde el body. Usado por el dueño (caja) y por
    el especialista (mi-caja). Lanza 400 si el monto es inválido."""
    monto = _num(b.get("monto")) or 0
    if monto <= 0:
        raise HTTPException(status_code=400, detail="El monto debe ser mayor a 0.")
    estado_pago = b.get("estado_pago") if b.get("estado_pago") in ("pagado", "por_cobrar") else "pagado"
    agente = _miembro(tienda, b.get("agente_id", ""))
    pagado = monto if estado_pago == "pagado" else 0
    return {
        "id": secrets.token_hex(6),
        "fecha": b.get("fecha") or _date.today().isoformat(),
        "agente_id": b.get("agente_id") or "",
        "agente_nombre": agente["nombre"] if agente else (b.get("agente_nombre") or "na"),
        "servicio_id": b.get("servicio_id") or "",
        "servicio_nombre": (b.get("servicio_nombre") or "").strip() or "Servicio",
        "cliente_nombre": (b.get("cliente_nombre") or "").strip() or "Cliente",
        "monto": monto,
        "pago_recibido": pagado,
        "no_recibido": monto - pagado,
        "metodo_pago": b.get("metodo_pago") or "Efectivo",
        "estado_pago": estado_pago,
        "estado_servicio": "ejecutado",
        # Campos del reporte operativo (estilo spa)
        "categoria": (b.get("categoria") or "").strip(),
        "propina": _num(b.get("propina")) or 0,
        "conteo": int(_num(b.get("conteo")) or 1),
        "prox_cita": (b.get("prox_cita") or "").strip(),
        "creado": datetime.now().isoformat(),
    }


@app.post("/api/movimientos/{slug}")
async def api_mov_crear(slug: str, request: Request, k: str = ""):
    t = _tienda_admin(slug, k)
    mov = _nuevo_movimiento(t, await request.json())
    tiendas.agregar(slug, "movimientos", mov)
    return JSONResponse({"ok": True, "movimiento": mov})


# ---- Ventas: helper compartido por POS (mostrador) y checkout (online) ----
def _wa_digits(s: str) -> str:
    return "".join(ch for ch in (s or "") if ch.isdigit())


def _registrar_venta(tienda: dict, slug: str, items: list, metodo: str, estado_pago: str,
                     cliente_nombre: str = "", cliente_telefono: str = "",
                     agente_id: str = "", origen: str = "POS"):
    """Crea un movimiento de venta (uno por ticket) y descuenta inventario si
    está pagado. items=[{id?, nombre, precio, cantidad}]. Devuelve (mov, total).
    Si el item trae id, el precio y nombre se toman del catálogo (no del cliente)."""
    for i in items:
        ref = None
        if i.get("id"):
            ref = tiendas.buscar_producto(tienda, i["id"]) or tiendas.buscar_servicio(tienda, i["id"])
        if ref:
            i["nombre"] = ref.get("nombre", i.get("nombre", ""))
            if ref.get("precio") is not None:
                i["precio"] = float(ref["precio"])
    total = sum(float(i.get("precio") or 0) * int(i.get("cantidad") or 1) for i in items)
    unidades = sum(int(i.get("cantidad") or 1) for i in items)
    agente = _miembro(tienda, agente_id)
    pagado = total if estado_pago == "pagado" else 0
    resumen = items[0].get("nombre", "Venta") if len(items) == 1 else f"Venta · {unidades} art."
    mov = {
        "id": secrets.token_hex(6), "fecha": _date.today().isoformat(),
        "agente_id": agente_id or "", "agente_nombre": agente["nombre"] if agente else "na",
        "servicio_id": "", "servicio_nombre": resumen,
        "cliente_nombre": (cliente_nombre or "").strip() or "Cliente",
        "cliente_telefono": (cliente_telefono or "").strip(),
        "monto": total, "pago_recibido": pagado, "no_recibido": total - pagado,
        "metodo_pago": metodo, "estado_pago": estado_pago, "estado_servicio": "ejecutado",
        "categoria": "venta", "items": items, "origen": origen, "conteo": unidades,
        "creado": datetime.now().isoformat(),
    }
    tiendas.agregar(slug, "movimientos", mov)
    if estado_pago == "pagado":
        stock_items = [{"id": i["id"], "cantidad": int(i.get("cantidad") or 1)} for i in items if i.get("id")]
        if stock_items:
            tiendas.descontar_stock(slug, stock_items)
    return mov, total


# ---- B) POS de mostrador (panel, Pro+) ----
@app.post("/api/pos/{slug}")
async def api_pos(slug: str, request: Request, k: str = ""):
    t = _tienda_admin(slug, k, "pos")
    b = await request.json()
    items = b.get("items", [])
    if not items:
        raise HTTPException(status_code=400, detail="El carrito está vacío.")
    mov, total = _registrar_venta(
        t, slug, items, b.get("metodo", "Efectivo"), "pagado",
        b.get("cliente_nombre", ""), b.get("cliente_telefono", ""), b.get("agente_id", ""), "POS")
    # Ticket por WhatsApp (opcional, si hay teléfono del cliente)
    wa_url = ""
    tel = _wa_digits(b.get("cliente_telefono", ""))
    if tel:
        from urllib.parse import quote
        lineas = "\n".join(f"• {int(i.get('cantidad') or 1)}x {i.get('nombre')} — ${float(i.get('precio') or 0)*int(i.get('cantidad') or 1):,.2f}" for i in items)
        msg = f"🧾 Ticket de {t.get('nombre')}\n{lineas}\nTotal: ${total:,.2f} {t.get('moneda','MXN')}\n¡Gracias por tu compra!"
        wa_url = f"https://wa.me/{tel}?text={quote(msg)}"
    return JSONResponse({"ok": True, "movimiento": mov, "total": total, "ticket_wa": wa_url})


@app.delete("/api/movimientos/{slug}/{mov_id}")
def api_mov_eliminar(slug: str, mov_id: str, k: str = ""):
    _tienda_admin(slug, k)
    return JSONResponse({"ok": tiendas.eliminar_item(slug, "movimientos", mov_id)})


# ---- Gastos (clasificados por IA) ----
@app.get("/api/gastos/{slug}")
def api_gastos_listar(slug: str, k: str = "", desde: str = "", hasta: str = ""):
    t = _tienda_admin(slug, k)
    g = [x for x in t.get("gastos", []) if _en_rango(x.get("fecha", ""), desde, hasta)]
    return JSONResponse({"gastos": g, "cuentas": tiendas.CUENTAS_CONTABLES})


@app.post("/api/gastos/{slug}")
async def api_gastos_crear(slug: str, request: Request, k: str = ""):
    _tienda_admin(slug, k)
    b = await request.json()
    concepto = (b.get("concepto") or "").strip()
    monto = _num(b.get("monto")) or 0
    if not concepto or monto <= 0:
        raise HTTPException(status_code=400, detail="Concepto y monto son obligatorios.")
    # Clasifica con IA (o reglas). Permite override manual de cuenta.
    if b.get("cuenta"):
        clasif = {"cuenta": b["cuenta"], "confianza": 1.0, "por": "manual"}
    else:
        clasif = gemini_ia.clasificar_gasto(concepto, monto)
    gasto = {
        "id": secrets.token_hex(6),
        "fecha": b.get("fecha") or _date.today().isoformat(),
        "concepto": concepto,
        "monto": monto,
        "cuenta": clasif["cuenta"],
        "clasificado_por": clasif["por"],
        "confianza": clasif["confianza"],
        "creado": datetime.now().isoformat(),
    }
    tiendas.agregar(slug, "gastos", gasto)
    return JSONResponse({"ok": True, "gasto": gasto})


@app.delete("/api/gastos/{slug}/{gid}")
def api_gastos_eliminar(slug: str, gid: str, k: str = ""):
    _tienda_admin(slug, k)
    return JSONResponse({"ok": tiendas.eliminar_item(slug, "gastos", gid)})


# ---- Gastos avanzados: presupuestos + recurrentes (módulo Escala) ----
_CODIGOS_CUENTA = [c["codigo"] for c in tiendas.CUENTAS_CONTABLES]


@app.get("/api/gastos-pro/{slug}")
def api_gastospro(slug: str, k: str = "", desde: str = "", hasta: str = ""):
    t = _tienda_admin(slug, k, "gastos")  # Pro+: ver lista, por cuenta y total
    if not desde:
        hoy = _date.today()
        desde, hasta = hoy.replace(day=1).isoformat(), hoy.isoformat()
    gastos = [g for g in t.get("gastos", []) if _en_rango(g.get("fecha", ""), desde, hasta)]
    gastos.sort(key=lambda g: g.get("fecha", ""), reverse=True)
    presup = t.get("presupuestos", {})
    por_cuenta = []
    for c in tiendas.CUENTAS_CONTABLES:
        gastado = sum(float(g.get("monto") or 0) for g in gastos if g.get("cuenta") == c["codigo"])
        por_cuenta.append({"codigo": c["codigo"], "nombre": c["nombre"],
                           "gastado": gastado, "presupuesto": float(presup.get(c["codigo"]) or 0)})
    return JSONResponse({
        "gastos": gastos, "por_cuenta": por_cuenta,
        "recurrentes": t.get("gastos_recurrentes", []),
        "total": sum(x["gastado"] for x in por_cuenta),
        "cuentas": tiendas.CUENTAS_CONTABLES, "rango": {"desde": desde, "hasta": hasta},
    })


@app.post("/api/gastos-pro/{slug}/presupuesto")
async def api_gastospro_presupuesto(slug: str, request: Request, k: str = ""):
    t = _tienda_admin(slug, k, "gastos_avanzado")
    b = await request.json()
    cuenta = b.get("cuenta")
    if cuenta not in _CODIGOS_CUENTA:
        raise HTTPException(status_code=400, detail="Cuenta no válida.")
    presup = dict(t.get("presupuestos", {}))
    presup[cuenta] = _num(b.get("monto")) or 0
    tiendas.actualizar_tienda(slug, {"presupuestos": presup})
    return JSONResponse({"ok": True})


@app.patch("/api/gastos-pro/{slug}/{gid}")
async def api_gastospro_editar(slug: str, gid: str, request: Request, k: str = ""):
    _tienda_admin(slug, k, "gastos")  # Pro+: reclasificar un gasto
    b = await request.json()
    cambios = {}
    if b.get("cuenta") in _CODIGOS_CUENTA:
        cambios["cuenta"] = b["cuenta"]
        cambios["clasificado_por"] = "manual"
    g = tiendas.actualizar_item(slug, "gastos", gid, cambios) if cambios else None
    return JSONResponse({"ok": bool(g), "gasto": g})


@app.post("/api/gastos-pro/{slug}/recurrente")
async def api_recurrente_crear(slug: str, request: Request, k: str = ""):
    _tienda_admin(slug, k, "gastos_avanzado")
    b = await request.json()
    concepto = (b.get("concepto") or "").strip()
    monto = _num(b.get("monto")) or 0
    cuenta = b.get("cuenta") if b.get("cuenta") in _CODIGOS_CUENTA else "GASTOS_OP"
    if not concepto or monto <= 0:
        raise HTTPException(status_code=400, detail="Concepto y monto son obligatorios.")
    rec = {"id": secrets.token_hex(5), "concepto": concepto, "monto": monto, "cuenta": cuenta}
    tiendas.agregar(slug, "gastos_recurrentes", rec, al_inicio=False)
    return JSONResponse({"ok": True, "recurrente": rec})


@app.delete("/api/gastos-pro/{slug}/recurrente/{rid}")
def api_recurrente_eliminar(slug: str, rid: str, k: str = ""):
    _tienda_admin(slug, k, "gastos_avanzado")
    return JSONResponse({"ok": tiendas.eliminar_item(slug, "gastos_recurrentes", rid)})


@app.post("/api/gastos-pro/{slug}/recurrente/{rid}/registrar")
def api_recurrente_registrar(slug: str, rid: str, k: str = ""):
    """Genera el gasto de este mes a partir de una plantilla recurrente."""
    t = _tienda_admin(slug, k, "gastos_avanzado")
    rec = next((r for r in t.get("gastos_recurrentes", []) if r.get("id") == rid), None)
    if not rec:
        raise HTTPException(status_code=404, detail="Recurrente no encontrado")
    gasto = {
        "id": secrets.token_hex(6), "fecha": _date.today().isoformat(),
        "concepto": rec["concepto"], "monto": rec["monto"], "cuenta": rec["cuenta"],
        "clasificado_por": "recurrente", "confianza": 1.0, "creado": datetime.now().isoformat(),
    }
    tiendas.agregar(slug, "gastos", gasto)
    return JSONResponse({"ok": True, "gasto": gasto})


# ---- Paquetes / bonos por sesiones (prepagos) ----
def _buscar_prepago(tienda: dict, pid: str):
    for p in tienda.get("prepagos", []):
        if p.get("id") == pid:
            return p
    return None


@app.get("/api/prepagos/{slug}")
def api_prepagos_listar(slug: str, k: str = "", solo_activos: str = ""):
    t = _tienda_admin(slug, k)
    paqs = t.get("prepagos", [])
    if solo_activos:
        paqs = [p for p in paqs if p.get("estado") == "activo"]
    return JSONResponse({"prepagos": paqs})


@app.post("/api/prepagos/{slug}")
async def api_prepagos_vender(slug: str, request: Request, k: str = ""):
    """Vende un paquete: crea el prepago + un ingreso a caja (el pago)."""
    t = _tienda_admin(slug, k)
    b = await request.json()
    cliente = (b.get("cliente_nombre") or "").strip()
    descripcion = (b.get("descripcion") or "").strip()
    monto = _num(b.get("monto_total")) or 0
    sesiones = int(_num(b.get("sesiones_total")) or 0)
    if not cliente or not descripcion or monto <= 0 or sesiones <= 0:
        raise HTTPException(status_code=400, detail="Faltan datos del paquete.")
    valor_sesion = round(monto / sesiones, 2)
    prepago = {
        "id": secrets.token_hex(6),
        "cliente_nombre": cliente,
        "descripcion": descripcion,
        "monto_total": monto,
        "sesiones_total": sesiones,
        "sesiones_usadas": 0,
        "valor_sesion": valor_sesion,
        "estado": "activo",
        "fecha_venta": _date.today().isoformat(),
        "fecha_vence": b.get("fecha_vence") or "",
        "creado": datetime.now().isoformat(),
    }
    tiendas.agregar(slug, "prepagos", prepago)
    # Ingreso a caja por la venta del paquete (dinero real recibido).
    venta = _nuevo_movimiento(t, {
        "agente_id": b.get("agente_id", ""), "servicio_nombre": descripcion,
        "cliente_nombre": cliente, "monto": monto, "metodo_pago": b.get("metodo_pago", "Efectivo"),
        "estado_pago": "pagado", "categoria": "paquete", "prepago_id": prepago["id"],
    })
    venta["prepago_id"] = prepago["id"]
    tiendas.agregar(slug, "movimientos", venta)
    return JSONResponse({"ok": True, "prepago": prepago})


@app.post("/api/prepagos/{slug}/{pid}/consumir")
async def api_prepagos_consumir(slug: str, pid: str, request: Request, k: str = ""):
    """Consume una sesión del paquete: movimiento 'prepago' (sin cobro nuevo)
    atribuido a un especialista, que gana su comisión por el servicio."""
    t = _tienda_admin(slug, k)
    p = _buscar_prepago(t, pid)
    if not p:
        raise HTTPException(status_code=404, detail="Paquete no encontrado")
    if p.get("estado") != "activo" or p.get("sesiones_usadas", 0) >= p.get("sesiones_total", 0):
        raise HTTPException(status_code=400, detail="El paquete ya no tiene sesiones disponibles.")
    b = await request.json()
    agente = _miembro(t, b.get("agente_id", ""))
    vs = float(p.get("valor_sesion") or 0)
    # Movimiento de consumo: el dinero ya se recibió en la venta → no_recibido.
    mov = {
        "id": secrets.token_hex(6),
        "fecha": b.get("fecha") or _date.today().isoformat(),
        "agente_id": b.get("agente_id") or "",
        "agente_nombre": agente["nombre"] if agente else "na",
        "servicio_id": "", "servicio_nombre": (b.get("servicio_nombre") or p["descripcion"]).strip(),
        "cliente_nombre": p["cliente_nombre"],
        "monto": vs, "pago_recibido": 0, "no_recibido": vs,
        "metodo_pago": "Paquete", "estado_pago": "prepago", "estado_servicio": "ejecutado",
        "categoria": b.get("categoria", ""), "propina": 0, "conteo": 1, "prox_cita": "",
        "prepago_id": pid, "creado": datetime.now().isoformat(),
    }
    tiendas.agregar(slug, "movimientos", mov)
    usadas = p.get("sesiones_usadas", 0) + 1
    cambios = {"sesiones_usadas": usadas}
    if usadas >= p.get("sesiones_total", 0):
        cambios["estado"] = "consumido"
    prepago = tiendas.actualizar_item(slug, "prepagos", pid, cambios)
    return JSONResponse({"ok": True, "prepago": prepago, "movimiento": mov})


@app.delete("/api/prepagos/{slug}/{pid}")
def api_prepagos_cancelar(slug: str, pid: str, k: str = ""):
    _tienda_admin(slug, k)
    tiendas.actualizar_item(slug, "prepagos", pid, {"estado": "cancelado"})
    return JSONResponse({"ok": True})


# ---- Reportes (estado de resultados + comisiones) ----
@app.get("/api/reportes/{slug}")
def api_reportes(slug: str, k: str = "", desde: str = "", hasta: str = ""):
    t = _tienda_admin(slug, k)
    movs = [m for m in t.get("movimientos", []) if _en_rango(m.get("fecha", ""), desde, hasta)]
    gastos = [g for g in t.get("gastos", []) if _en_rango(g.get("fecha", ""), desde, hasta)]

    ventas = sum(float(m.get("monto") or 0) for m in movs)
    cobrado = sum(float(m.get("pago_recibido") or 0) for m in movs)
    por_cobrar = sum(float(m.get("monto") or 0) for m in movs if m.get("estado_pago") == "por_cobrar")

    por_metodo, por_servicio = {}, {}
    for m in movs:
        if m.get("estado_pago") == "pagado":
            por_metodo[m.get("metodo_pago", "Otro")] = por_metodo.get(m.get("metodo_pago", "Otro"), 0) + float(m.get("pago_recibido") or 0)
        sn = m.get("servicio_nombre", "Servicio")
        por_servicio[sn] = por_servicio.get(sn, 0) + float(m.get("monto") or 0)

    # Comisiones por miembro del equipo
    comisiones, comision_total = [], 0.0
    pct_por_agente = {x["id"]: float(x.get("pct_comision") or 0) for x in t.get("equipo", [])}
    base_por_agente = {}
    for m in movs:
        aid = m.get("agente_id") or "—"
        base_por_agente.setdefault(aid, {"nombre": m.get("agente_nombre", "Sin asignar"), "ventas": 0.0, "n": 0})
        base_por_agente[aid]["ventas"] += float(m.get("monto") or 0)
        base_por_agente[aid]["n"] += 1
    for aid, d in base_por_agente.items():
        pct = pct_por_agente.get(aid, 0.0)
        com = round(d["ventas"] * pct, 2)
        comision_total += com
        comisiones.append({"agente": d["nombre"], "ventas": d["ventas"], "pct": pct,
                           "comision": com, "servicios": d["n"]})
    comisiones.sort(key=lambda x: x["ventas"], reverse=True)

    # Gastos por cuenta
    por_cuenta = {c["codigo"]: 0.0 for c in tiendas.CUENTAS_CONTABLES}
    for g in gastos:
        por_cuenta[g.get("cuenta", "GASTOS_OP")] = por_cuenta.get(g.get("cuenta", "GASTOS_OP"), 0) + float(g.get("monto") or 0)
    gastos_total = sum(por_cuenta.values())

    utilidad = round(cobrado - comision_total - gastos_total, 2)

    return JSONResponse({
        "rango": {"desde": desde, "hasta": hasta},
        "ingresos": {"ventas": ventas, "cobrado": cobrado, "por_cobrar": por_cobrar,
                     "por_metodo": por_metodo, "por_servicio": por_servicio,
                     "num_movimientos": len(movs)},
        "comisiones": {"detalle": comisiones, "total": round(comision_total, 2)},
        "gastos": {"por_cuenta": por_cuenta, "total": gastos_total,
                   "cuentas": tiendas.CUENTAS_CONTABLES},
        "utilidad": utilidad,
    })


_MESES_LARGOS = ["", "enero", "febrero", "marzo", "abril", "mayo", "junio",
                 "julio", "agosto", "septiembre", "octubre", "noviembre", "diciembre"]


@app.get("/api/resumen/{slug}")
def api_resumen(slug: str, k: str = ""):
    """Resumen de 'Vendido este mes' combinando pipeline ganado + caja."""
    t = _tienda_admin(slug, k)
    hoy = _date.today()
    mes_ini = hoy.replace(day=1).isoformat()
    mes_fin = hoy.isoformat()

    def f_ganado(l):
        return l.get("fecha_ganado") or (l.get("actualizado", "") or "")[:10]

    gan_mes = [l for l in t.get("leads", [])
               if l.get("etapa") == "Ganado" and mes_ini <= f_ganado(l) <= mes_fin]
    pipeline_valor = sum(float(l.get("valor") or 0) for l in gan_mes)

    movs = [m for m in t.get("movimientos", []) if _en_rango(m.get("fecha", ""), mes_ini, mes_fin)]
    caja_ventas = sum(float(m.get("monto") or 0) for m in movs)
    caja_cobrado = sum(float(m.get("pago_recibido") or 0) for m in movs)

    return JSONResponse({
        "mes": f"{_MESES_LARGOS[hoy.month]} {hoy.year}",
        "pipeline": {"valor": pipeline_valor, "num": len(gan_mes)},
        "caja": {"ventas": caja_ventas, "cobrado": caja_cobrado, "num": len(movs)},
        "total_vendido": round(pipeline_valor + caja_cobrado, 2),
        "tiene_caja": bool(t.get("movimientos") or t.get("equipo")),
    })


# ---- Exportar reporte (CSV / Excel) con las columnas operativas ----
_DIAS_SEM = ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"]
_MESES_AB = ["", "ene", "feb", "mar", "abr", "may", "jun", "jul", "ago", "sep", "oct", "nov", "dic"]
_COLS_REPORTE = ["Día", "Fecha", "Nombre Cliente", "Servicio", "Pago Recibido", "No recibido",
                 "Comision", "Forma Pago", "Empleada", "Categoria", "Prop TC", "Conteo", "Prox cita"]


def _fila_reporte(m: dict):
    try:
        d = datetime.strptime(m.get("fecha", ""), "%Y-%m-%d").date()
        dia = _DIAS_SEM[d.weekday()]
        fecha = f"{d.day}-{_MESES_AB[d.month]}-{str(d.year)[2:]}"
    except ValueError:
        dia, fecha = "", m.get("fecha", "")
    n = lambda v: (int(v) if float(v) == int(v) else float(v)) if v else ""   # "" si 0/None
    return [
        dia, fecha, m.get("cliente_nombre", ""), m.get("servicio_nombre", ""),
        n(m.get("pago_recibido")), n(m.get("no_recibido")), n(m.get("monto")),
        m.get("metodo_pago", ""), m.get("agente_nombre", "na") or "na",
        m.get("categoria", ""), n(m.get("propina")), m.get("conteo", 1) or 1,
        m.get("prox_cita", ""),
    ]


@app.get("/api/reporte/{slug}.{ext}")
def api_reporte_export(slug: str, ext: str, k: str = "", desde: str = "", hasta: str = ""):
    """Descarga el reporte operativo (filas = movimientos) con las columnas exactas."""
    tienda = _tienda_admin(slug, k)
    movs = [m for m in tienda.get("movimientos", []) if _en_rango(m.get("fecha", ""), desde, hasta)]
    movs.sort(key=lambda m: (m.get("fecha", ""), m.get("creado", "")))
    rows = [_fila_reporte(m) for m in movs]
    nombre = f"reporte-{slug}-{desde or 'todo'}"

    if ext == "xlsx":
        try:
            from openpyxl import Workbook
            wb = Workbook(); ws = wb.active; ws.title = "Reporte"
            ws.append(_COLS_REPORTE)
            for r in rows:
                ws.append(r)
            bio = io.BytesIO(); wb.save(bio)
            return Response(
                bio.getvalue(),
                media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                headers={"Content-Disposition": f'attachment; filename="{nombre}.xlsx"'},
            )
        except ImportError:
            ext = "csv"   # sin openpyxl → cae a CSV

    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(_COLS_REPORTE)
    w.writerows(rows)
    data = ("﻿" + buf.getvalue()).encode("utf-8")   # BOM → Excel respeta acentos
    return Response(data, media_type="text/csv; charset=utf-8",
                    headers={"Content-Disposition": f'attachment; filename="{nombre}.csv"'})


# ------------------- Recordatorios automáticos (cron) -------------------

def _panel_url(slug: str, token: str, tab: str = "") -> str:
    sufijo = f"&tab={tab}" if tab else ""
    if DOMINIO_BASE and DOMINIO_BASE != "localhost":
        return f"https://{slug}.{DOMINIO_BASE}/panel?k={token}{sufijo}"
    return f"{KATIA_BASE_URL}/t/{slug}/panel?k={token}{sufijo}"


def _leads_por_contactar(tienda: dict, hoy: str):
    """Leads abiertos cuyo próximo contacto ya venció y no se recordaron hoy."""
    out = []
    for l in tienda.get("leads", []):
        prox = l.get("proximo_contacto") or ""
        if (prox and prox <= hoy
                and l.get("etapa") in tiendas.ETAPAS_ABIERTAS
                and l.get("recordado") != hoy):
            out.append(l)
    return out


def _email_recordatorio_html(tienda: dict, leads: list, hoy: str) -> str:
    panel = _panel_url(tienda["slug"], tienda.get("admin_token", ""), tab="hoy")
    filas = ""
    for l in leads:
        tel = "".join(ch for ch in (l.get("telefono") or "") if ch.isdigit())
        wa = f'<a href="https://wa.me/{tel}" style="color:#6d5dfb;font-weight:700;">WhatsApp</a>' if tel else "—"
        vencido = "🔴 vencido" if l.get("proximo_contacto", "") < hoy else "🟠 hoy"
        filas += (
            f'<tr><td style="padding:8px 0;border-top:1px solid #eee;">'
            f'<b>{l.get("nombre","Cliente")}</b><br>'
            f'<span style="color:#6b6a83;font-size:13px;">{l.get("origen","")} · {l.get("etapa","")} · {vencido}</span></td>'
            f'<td style="padding:8px 0;border-top:1px solid #eee;text-align:right;">{wa}</td></tr>'
        )
    return f"""
    <div style="font-family:-apple-system,Segoe UI,Roboto,sans-serif;max-width:560px;margin:0 auto;color:#222642;">
      <h2 style="color:#6d5dfb;margin-bottom:4px;">Tienes {len(leads)} cliente(s) por contactar</h2>
      <p style="color:#6b6a83;">Estos leads de <b>{tienda.get('nombre')}</b> tienen un seguimiento pendiente. No dejes que se enfríen 🔥</p>
      <table style="width:100%;border-collapse:collapse;margin:16px 0;">{filas}</table>
      <p><a href="{panel}" style="display:inline-block;background:#6d5dfb;color:#fff;text-decoration:none;
            padding:13px 26px;border-radius:12px;font-weight:700;">Abrir mi panel de ventas →</a></p>
      <p style="color:#9a98ad;font-size:12px;margin-top:28px;">Recordatorio automático de katia.work · tu asistente de ventas.</p>
    </div>
    """


@app.api_route("/cron/recordatorios", methods=["GET", "POST"])
def cron_recordatorios(token: str = ""):
    """Recorre todas las tiendas y envía al dueño un correo con los leads por
    contactar hoy. Pensado para cron-job.org (cada mañana). Protegido por token."""
    if not CRON_TOKEN or token != CRON_TOKEN:
        raise HTTPException(status_code=403, detail="Token inválido.")
    if not emails.disponible():
        return JSONResponse({"ok": False, "error": "Resend no configurado (RESEND_API_KEY)."})

    hoy = _date.today().isoformat()
    tiendas_notificadas, leads_total, fallidos = 0, 0, 0

    for t in tiendas.listar_tiendas():
        destino = t.get("owner_email") or t.get("correo")
        if not destino or not permite(_plan_de_tienda(t), "recordatorios"):
            continue
        pendientes = _leads_por_contactar(t, hoy)
        if not pendientes:
            continue
        html = _email_recordatorio_html(t, pendientes, hoy)
        ok = emails.enviar(destino, f"🔔 {len(pendientes)} cliente(s) por contactar — {t.get('nombre')}", html)
        if ok:
            tiendas_notificadas += 1
            leads_total += len(pendientes)
            for l in pendientes:
                tiendas.actualizar_lead(t["slug"], l["id"], {"recordado": hoy})
        else:
            fallidos += 1

    return JSONResponse({
        "ok": True, "tiendas_notificadas": tiendas_notificadas,
        "leads_recordados": leads_total, "fallidos": fallidos,
    })


# ------------------- Panel SUPER-ADMIN de plataforma (/admin) -------------------

def _guard_admin(request: Request):
    """Bloquea si no es super-admin (404 para no revelar la ruta)."""
    if not _es_superadmin(request):
        raise HTTPException(status_code=404, detail="No encontrado")


def _admin_contexto():
    """Métricas globales + listados para el panel super-admin."""
    us = usuarios.listar()
    ts = tiendas.listar_tiendas()
    por_email = {u["email"]: u for u in us}
    precios = {k: v["precio"] for k, v in PLANES.items()}

    # Conteo de cuentas por plan y MRR (solo suscripciones pagadas reales)
    por_plan = {"gratis": 0, "tienda": 0, "pro": 0, "escala": 0}
    mrr = 0
    pagando = 0
    demo = 0
    for u in us:
        if u.get("rol") == "especialista":
            continue
        plan = u.get("plan", "gratis")
        por_plan[plan] = por_plan.get(plan, 0) + 1
        est = u.get("sub_estado", "")
        if est in ("active", "trialing") and plan != "gratis":
            mrr += precios.get(plan, 0)
            pagando += 1
        elif est == "active_demo" and plan != "gratis":
            demo += 1

    # Enriquecer tiendas con datos del dueño y conteos
    filas = []
    for t in ts:
        owner = por_email.get((t.get("owner_email") or "").lower(), {})
        filas.append({
            "slug": t.get("slug", ""),
            "nombre": t.get("nombre", ""),
            "owner_email": t.get("owner_email", ""),
            "owner_plan": owner.get("plan", "gratis"),
            "productos": len(t.get("productos", [])),
            "servicios": len(t.get("servicios", [])),
            "movimientos": len(t.get("movimientos", [])),
            "suspendida": bool(t.get("suspendida")),
            "creada": (t.get("creada") or t.get("creado") or "")[:10],
        })
    filas.sort(key=lambda x: x["creada"], reverse=True)

    duenos = [u for u in us if u.get("rol") != "especialista"]
    duenos.sort(key=lambda x: x.get("creado", ""), reverse=True)

    solicitudes = demos.listar()
    demos_pend = sum(1 for s in solicitudes if not s.get("atendido"))

    return {
        "total_tiendas": len(ts),
        "total_usuarios": len(us),
        "total_duenos": len(duenos),
        "total_especialistas": len(us) - len(duenos),
        "suspendidas": sum(1 for f in filas if f["suspendida"]),
        "mrr": mrr,
        "pagando": pagando,
        "demo": demo,
        "por_plan": por_plan,
        "tiendas": filas,
        "usuarios": duenos,
        "planes": PLANES,
        "demos": solicitudes,
        "demos_pend": demos_pend,
    }


@app.get("/admin", response_class=HTMLResponse)
def admin_panel(request: Request):
    _guard_admin(request)
    ctx = _admin_contexto()
    ctx["request"] = request
    ctx["yo"] = request.session.get("uid", "")
    return templates.TemplateResponse(request, "constructor/admin.html", ctx)


@app.post("/admin/tienda/{slug}/suspender")
def admin_suspender_tienda(request: Request, slug: str):
    _guard_admin(request)
    t = tiendas.obtener_tienda(slug)
    if t:
        tiendas.actualizar_tienda(slug, {"suspendida": not bool(t.get("suspendida"))})
    return RedirectResponse(url="/admin", status_code=303)


@app.post("/admin/tienda/{slug}/eliminar")
def admin_eliminar_tienda(request: Request, slug: str):
    _guard_admin(request)
    tiendas.eliminar_tienda(slug)
    return RedirectResponse(url="/admin", status_code=303)


@app.post("/admin/tienda/{slug}/asignar-dueno")
def admin_asignar_dueno(request: Request, slug: str,
                        email: str = Form(...), password: str = Form(""),
                        nombre: str = Form(""), plan: str = Form("escala")):
    """Asigna (o crea) la cuenta dueña de una tienda, con plan, para pruebas/transferencias."""
    _guard_admin(request)
    t = tiendas.obtener_tienda(slug)
    if not t:
        return RedirectResponse(url="/admin", status_code=303)
    email = (email or "").lower().strip()
    if not email:
        return RedirectResponse(url="/admin", status_code=303)
    pwd = password if len(password or "") >= 6 else "katia12345"
    if not usuarios.buscar(email):
        usuarios.crear(email, pwd, nombre=nombre or email.split("@")[0])
    plan = plan if plan in PLANES else "escala"
    cambios = {"plan": plan, "sub_estado": "active"}
    # Si se envió contraseña, la (re)establece aunque la cuenta ya exista
    if len(password or "") >= 6:
        cambios["password_hash"] = usuarios.hash_password(password)
    usuarios.actualizar(email, cambios)
    tiendas.actualizar_tienda(slug, {"owner_email": email})
    return RedirectResponse(url="/admin", status_code=303)


@app.post("/admin/usuario/{email}/plan")
def admin_cambiar_plan(request: Request, email: str, plan: str = Form(...)):
    _guard_admin(request)
    if plan in PLANES:
        estado = "active" if plan != "gratis" else "canceled"
        usuarios.actualizar(email, {"plan": plan, "sub_estado": estado})
    return RedirectResponse(url="/admin", status_code=303)


@app.post("/admin/usuario/{email}/eliminar")
def admin_eliminar_usuario(request: Request, email: str):
    _guard_admin(request)
    # No permitir que un super-admin se borre a sí mismo por accidente
    if email.lower().strip() != (request.session.get("uid") or "").lower().strip():
        usuarios.eliminar(email)
    return RedirectResponse(url="/admin", status_code=303)


@app.post("/admin/demo/{id_}/atendido")
def admin_demo_atendido(request: Request, id_: str):
    _guard_admin(request)
    demos.marcar_atendido(id_)
    return RedirectResponse(url="/admin", status_code=303)


@app.post("/admin/demo/{id_}/eliminar")
def admin_demo_eliminar(request: Request, id_: str):
    _guard_admin(request)
    demos.eliminar(id_)
    return RedirectResponse(url="/admin", status_code=303)


@app.get("/admin/email-preview", response_class=HTMLResponse)
def admin_email_preview(request: Request, plan: str = "gratis", nombre: str = "Diego"):
    """Vista previa del correo de bienvenida (sin enviar nada)."""
    _guard_admin(request)
    if plan not in PLANES:
        plan = "gratis"
    return HTMLResponse(emails._html_bienvenida(nombre, plan))


@app.get("/admin/enviar-prueba")
def admin_enviar_prueba(request: Request, plan: str = "pro", email: str = "", nombre: str = "Diego"):
    """Envía un correo de bienvenida de prueba al correo indicado (super-admin)."""
    _guard_admin(request)
    dest = (email or request.session.get("uid") or "").strip()
    planes_a_probar = list(PLANES.keys()) if plan == "todos" else [plan if plan in PLANES else "pro"]
    resultados = {p: emails.enviar_bienvenida(dest, nombre, p) for p in planes_a_probar}
    return JSONResponse({
        "destino": dest,
        "resend_activo": emails.disponible(),
        "enviados": resultados,
        "nota": "" if emails.disponible() else "RESEND_API_KEY no está configurada; no se envió nada.",
    })


@app.get("/admin/respaldo")
def admin_respaldo(request: Request):
    """Descarga un respaldo completo (datos + imágenes) como ZIP (super-admin)."""
    _guard_admin(request)
    data = _respaldo_zip(incluir_imagenes=True)
    fecha = datetime.now().strftime("%Y%m%d-%H%M")
    return Response(content=data, media_type="application/zip",
                    headers={"Content-Disposition": f'attachment; filename="katia-respaldo-{fecha}.zip"'})


@app.get("/cron/backup")
def cron_backup(token: str = ""):
    """Crea un snapshot de datos en disco. Para cron externo (cron-job.org)."""
    if not CRON_TOKEN or token != CRON_TOKEN:
        raise HTTPException(status_code=403, detail="Token inválido.")
    nombre = _snapshot_disco()
    return JSONResponse({"ok": True, "respaldo": nombre})


# ------------------- A) Checkout online (storefront) -------------------

def _render_checkout(request: Request, tienda: dict, producto_id: str, ruta_base: str):
    susp = _suspendida_resp(tienda)
    if susp:
        return susp
    if not _pago_online(tienda):
        return RedirectResponse(url=(ruta_base or "/"), status_code=303)
    p = tiendas.buscar_producto(tienda, producto_id)
    if not p or p.get("precio") is None:
        return RedirectResponse(url=(ruta_base or "/"), status_code=303)
    pg = tienda.get("pagos", {})
    return templates.TemplateResponse(request, "constructor/pago.html", {
        "t": tienda, "p": p, "ruta_base": ruta_base, "pagos": pg,
        "spei": bool(pg.get("spei_activo")), "mp": bool(pg.get("mp_activo")),
        "moneda": tienda.get("moneda", "MXN"),
    })


@app.get("/pagar/{producto_id}", response_class=HTMLResponse)
def checkout_subdominio(request: Request, producto_id: str):
    slug = tiendas.resolver_por_host(request.headers.get("host", ""), DOMINIO_BASE)
    if not slug:
        raise HTTPException(status_code=404, detail="No encontrado")
    tienda = tiendas.obtener_tienda(slug)
    if not tienda:
        raise HTTPException(status_code=404, detail="Tienda no encontrada")
    return _render_checkout(request, tienda, producto_id, "")


@app.get("/t/{slug}/pagar/{producto_id}", response_class=HTMLResponse)
def checkout_local(request: Request, slug: str, producto_id: str):
    tienda = tiendas.obtener_tienda(slug)
    if not tienda:
        raise HTTPException(status_code=404, detail="Tienda no encontrada")
    return _render_checkout(request, tienda, producto_id, f"/t/{slug}")


def _mp_init_point(token: str, items: list, moneda: str, back_url: str):
    """Crea una preferencia de MercadoPago y devuelve su URL (o None si falla)."""
    try:
        import mercadopago
        sdk = mercadopago.SDK(token)
        pref = {
            "items": [{"title": i["nombre"], "quantity": int(i.get("cantidad") or 1),
                       "unit_price": float(i.get("precio") or 0), "currency_id": moneda} for i in items],
            "back_urls": {"success": back_url, "failure": back_url, "pending": back_url},
            "auto_return": "approved",
        }
        res = sdk.preference().create(pref)
        return res["response"].get("init_point")
    except Exception as e:  # noqa: BLE001
        print(f"⚠  MercadoPago falló: {e}")
        return None


@app.post("/api/pedido/{slug}")
async def api_pedido(slug: str, request: Request):
    """Checkout público: crea el pedido. SPEI → instrucciones; MP → link de pago."""
    _rate_limit(request, "pedido", 12, 3600)   # 12 / hora por IP
    tienda = tiendas.obtener_tienda(slug)
    if not tienda or not _pago_online(tienda) or tienda.get("suspendida"):
        raise HTTPException(status_code=404, detail="Tienda no encontrada")
    b = await request.json()
    p = tiendas.buscar_producto(tienda, b.get("producto_id", ""))
    if not p or p.get("precio") is None:
        raise HTTPException(status_code=400, detail="Producto no válido.")
    cant = max(1, int(_num(b.get("cantidad")) or 1))
    nombre = (b.get("nombre") or "").strip()
    tel = (b.get("telefono") or "").strip()
    if not nombre or not tel:
        raise HTTPException(status_code=400, detail="Pon tu nombre y WhatsApp.")
    metodo = b.get("metodo", "spei")
    items = [{"id": p["id"], "nombre": p["nombre"], "precio": float(p["precio"]), "cantidad": cant}]
    total = float(p["precio"]) * cant
    pg = tienda.get("pagos", {})

    # MercadoPago (tarjeta) — si está activo y elegido
    if metodo == "mp" and pg.get("mp_activo") and pg.get("mercadopago_token"):
        back = f"{_base_publica(request, slug)}/?pago=ok"
        url = _mp_init_point(pg["mercadopago_token"], items, tienda.get("moneda", "MXN"), back)
        if url:
            _registrar_venta(tienda, slug, items, "MercadoPago", "por_cobrar", nombre, tel, "", "Online")
            _capturar_lead(slug, tienda, nombre, tel, "Web", f"Pedido online: {cant}x {p['nombre']}", total)
            return JSONResponse({"ok": True, "tipo": "mp", "url": url})

    # SPEI / transferencia (default, universal)
    mov, _ = _registrar_venta(tienda, slug, items, "SPEI", "por_cobrar", nombre, tel, "", "Online")
    _capturar_lead(slug, tienda, nombre, tel, "Web", f"Pedido online: {cant}x {p['nombre']} (por cobrar)", total)
    referencia = mov["id"][:8].upper()
    wanum = _wa_digits(tienda.get("whatsapp", ""))
    wa_url = ""
    if wanum:
        from urllib.parse import quote
        msg = f"Hola {tienda.get('nombre')}, hice mi pedido (ref {referencia}) de {cant}x {p['nombre']} por ${total:,.2f}. Adjunto mi comprobante."
        wa_url = f"https://wa.me/{wanum}?text={quote(msg)}"
    return JSONResponse({"ok": True, "tipo": "spei", "referencia": referencia, "total": total,
                         "pagos": {"titular": pg.get("titular"), "banco": pg.get("banco"),
                                   "clabe": pg.get("clabe"), "instrucciones": pg.get("instrucciones")},
                         "wa_url": wa_url})


# ------------------- Chatbot por tienda -------------------

@app.post("/api/chat/{slug}")
async def api_chat(slug: str, request: Request):
    tienda = tiendas.obtener_tienda(slug)
    if not tienda:
        raise HTTPException(status_code=404, detail="Tienda no encontrada")
    body = await request.json()
    respuesta = gemini_ia.chatbot_responder(
        tienda, body.get("mensaje", ""), body.get("historial", [])
    )
    return JSONResponse({"respuesta": respuesta})

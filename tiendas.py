# tiendas.py — Capa de datos multi-tenant del CONSTRUCTOR
# -------------------------------------------------------------------
# Cada negocio que se crea con el asistente es una "tienda" (tenant).
# Aquí viven: crear, leer, actualizar y resolver tiendas por subdominio.
#
# Persistencia: un archivo JSON por tienda en data/tiendas/<slug>.json.
# Esto permite probar TODO el flujo sin configurar Postgres. En
# producción se puede mover a la BD (db.py ya tiene Postgres) sin tocar
# el resto del código, porque toda la app pasa por estas funciones.
# -------------------------------------------------------------------
import json
import os
import re
import unicodedata
from datetime import datetime, timezone

# Directorios de datos (se crean solos en el primer arranque).
# En producción (Render) KATIA_DATA_DIR apunta al disco persistente montado,
# para que las tiendas y las imágenes sobrevivan a cada deploy/reinicio.
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_ROOT = os.getenv("KATIA_DATA_DIR", os.path.join(BASE_DIR, "data"))
DATA_DIR = os.path.join(DATA_ROOT, "tiendas")
# Los logos/uploads se sirven desde /u (montado sobre el disco persistente).
UPLOADS_DIR = os.path.join(DATA_ROOT, "uploads")

# Slugs reservados: no pueden ser nombre de tienda (chocan con rutas/subdominios).
RESERVADOS = {
    "www", "app", "api", "admin", "crear", "static", "ayuda", "blog",
    "soporte", "panel", "dashboard", "t", "tienda", "tiendas", "mail",
    "precios", "reservar",
}

# Horario de atención por defecto para agendar citas.
# dias: 0=Lunes ... 6=Domingo. Por defecto Lun-Sáb 9:00-18:00.
HORARIO_DEFAULT = {
    "dias": [0, 1, 2, 3, 4, 5],
    "apertura": "09:00",
    "cierre": "18:00",
}

# Etapas del pipeline del CRM (versión simple para PyMEs).
# Inspirado en el CRM Avantex, reducido de 11 a 5 etapas accionables.
ETAPAS_CRM = ["Nuevo", "Contactado", "Interesado", "Ganado", "Perdido"]
ETAPAS_ABIERTAS = ["Nuevo", "Contactado", "Interesado"]   # cuentan en el pipeline

# Caja y reportes (inspirado en SpaCore, hecho genérico).
# Las 5 cuentas fijas del estado de resultados.
CUENTAS_CONTABLES = [
    {"codigo": "COSTO_VENTAS", "nombre": "Costo de Ventas"},
    {"codigo": "NOMINA",       "nombre": "Nómina y comisiones"},
    {"codigo": "GASTOS_OP",    "nombre": "Gastos Operativos"},
    {"codigo": "MARKETING",    "nombre": "Marketing"},
    {"codigo": "GASTOS_FIN",   "nombre": "Gastos Financieros"},
]
METODOS_PAGO = ["Efectivo", "Tarjeta", "Transferencia", "SPEI"]


def _asegurar_dirs():
    os.makedirs(DATA_DIR, exist_ok=True)
    os.makedirs(UPLOADS_DIR, exist_ok=True)


def slugify(texto: str) -> str:
    """Convierte 'Café del Sur' -> 'cafe-del-sur'. Apto para URL/subdominio."""
    texto = unicodedata.normalize("NFKD", texto or "").encode("ascii", "ignore").decode()
    texto = texto.lower().strip()
    texto = re.sub(r"[^a-z0-9]+", "-", texto).strip("-")
    return texto or "mi-tienda"


def slug_disponible(slug: str) -> bool:
    if slug in RESERVADOS:
        return False
    return not os.path.exists(_ruta(slug))


def slug_unico(nombre: str) -> str:
    """Genera un slug libre a partir del nombre (agrega -2, -3... si choca)."""
    base = slugify(nombre)
    if base in RESERVADOS:
        base = f"{base}-tienda"
    slug = base
    n = 2
    while not slug_disponible(slug):
        slug = f"{base}-{n}"
        n += 1
    return slug


def _ruta(slug: str) -> str:
    return os.path.join(DATA_DIR, f"{slug}.json")


def _ahora() -> str:
    return datetime.now(timezone.utc).isoformat()


# ------------------- CRUD -------------------

def crear_tienda(datos: dict) -> dict:
    """Crea y persiste una tienda nueva. `datos` debe traer al menos `nombre`.
    Devuelve la tienda completa (con su slug asignado)."""
    _asegurar_dirs()
    slug = datos.get("slug") or slug_unico(datos.get("nombre", "mi-tienda"))

    tienda = {
        "slug": slug,
        "nombre": datos.get("nombre", "Mi Tienda").strip(),
        "giro": datos.get("giro", "").strip(),
        "contexto": datos.get("contexto", "").strip(),
        "eslogan": datos.get("eslogan", "").strip(),
        "sobre_nosotros": datos.get("sobre_nosotros", "").strip(),
        "color": datos.get("color", "#6d5dfb"),
        "color_2": datos.get("color_2", ""),
        "tono": datos.get("tono", "cercano y profesional"),
        # Plantilla visual del storefront y banner del hero
        "tema": datos.get("tema", "aurora"),
        "hero_imagen": datos.get("hero_imagen", ""),
        # Redes sociales (Tienda+): {instagram, facebook, tiktok, youtube, x, sitio, maps}
        "redes": datos.get("redes", {}),
        # Cobros: SPEI/transferencia + (opcional) MercadoPago. Ver PAGOS_DEFAULT.
        "pagos": datos.get("pagos", {}),
        "pedidos": datos.get("pedidos", []),   # pedidos del checkout online
        "whatsapp": datos.get("whatsapp", "").strip(),
        "correo": datos.get("correo", "").strip(),
        "ciudad": datos.get("ciudad", "").strip(),
        "moneda": datos.get("moneda", "MXN"),
        "logo": datos.get("logo", ""),          # ruta servible (/static/...)
        "dominio_propio": datos.get("dominio_propio", "").strip(),
        "owner_email": datos.get("owner_email", "").strip(),
        # tipo de negocio: "productos" | "servicios" | "ambos"
        "tipo": datos.get("tipo", "productos"),
        "productos": datos.get("productos", []),
        "servicios": datos.get("servicios", []),
        # horarios de atención para agendar citas (ver HORARIO_DEFAULT)
        "horarios": datos.get("horarios", dict(HORARIO_DEFAULT)),
        "citas": datos.get("citas", []),
        # CRM (planes Ventas Pro / Escala)
        "admin_token": datos.get("admin_token", ""),
        "leads": datos.get("leads", []),
        "vendedores": datos.get("vendedores", []),   # Escala: equipo
        # Caja y reportes (negocios de servicios con varios especialistas)
        "equipo": datos.get("equipo", []),           # miembros/especialistas
        "movimientos": datos.get("movimientos", []), # ingresos registrados
        "gastos": datos.get("gastos", []),           # egresos clasificados
        "gastos_recurrentes": datos.get("gastos_recurrentes", []),  # plantillas (Escala)
        "presupuestos": datos.get("presupuestos", {}),              # tope por cuenta (Escala)
        "prepagos": datos.get("prepagos", []),       # paquetes/bonos por sesiones
        "publicada": datos.get("publicada", True),
        "creada": _ahora(),
        "actualizada": _ahora(),
    }
    _guardar(tienda)
    return tienda


def obtener_tienda(slug: str):
    """Devuelve la tienda por slug, o None si no existe."""
    ruta = _ruta(slug)
    if not os.path.exists(ruta):
        return None
    with open(ruta, "r", encoding="utf-8") as f:
        return json.load(f)


def actualizar_tienda(slug: str, cambios: dict):
    """Aplica cambios parciales a una tienda existente. Devuelve la tienda
    actualizada, o None si no existe."""
    tienda = obtener_tienda(slug)
    if tienda is None:
        return None
    tienda.update(cambios)
    tienda["actualizada"] = _ahora()
    _guardar(tienda)
    return tienda


def eliminar_tienda(slug: str) -> bool:
    """Mueve la tienda (JSON + imágenes) a una papelera recuperable, en vez de
    borrarla definitivamente. Devuelve True si existía."""
    import shutil
    ruta = _ruta(slug)
    if not os.path.exists(ruta):
        return False
    papelera = os.path.join(DATA_ROOT, "backups", "papelera")
    os.makedirs(papelera, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    shutil.move(ruta, os.path.join(papelera, f"{slug}-{ts}.json"))
    carpeta = os.path.join(UPLOADS_DIR, slug)
    if os.path.isdir(carpeta):
        try:
            shutil.move(carpeta, os.path.join(papelera, f"{slug}-{ts}-img"))
        except Exception:  # noqa: BLE001
            shutil.rmtree(carpeta, ignore_errors=True)
    return True


def _guardar(tienda: dict):
    _asegurar_dirs()
    with open(_ruta(tienda["slug"]), "w", encoding="utf-8") as f:
        json.dump(tienda, f, ensure_ascii=False, indent=2)


def listar_tiendas():
    """Todas las tiendas (para un futuro panel de super-admin)."""
    _asegurar_dirs()
    out = []
    for nombre in os.listdir(DATA_DIR):
        if nombre.endswith(".json"):
            out.append(obtener_tienda(nombre[:-5]))
    return [t for t in out if t]


# ------------------- Resolución por subdominio / dominio propio -------------------

def resolver_por_host(host: str, dominio_base: str):
    """Dado el Host de la petición (ej. 'cafe-sur.miconstructor.com' o un
    dominio propio 'micafe.com'), devuelve el slug de la tienda o None.

    Reglas:
      - <slug>.<dominio_base>  -> esa tienda por subdominio.
      - dominio_base pelón / www -> None (es la home del constructor).
      - cualquier otro host -> busca una tienda con ese dominio_propio.
    """
    if not host:
        return None
    host = host.split(":")[0].lower().strip()  # quita el puerto

    if dominio_base and (host == dominio_base or host == f"www.{dominio_base}"):
        return None

    if dominio_base and host.endswith("." + dominio_base):
        sub = host[: -(len(dominio_base) + 1)]
        if sub and sub != "www" and sub not in RESERVADOS:
            return sub if obtener_tienda(sub) else None
        return None

    # Dominio propio: busca una tienda que lo haya configurado.
    for t in listar_tiendas():
        dp = (t.get("dominio_propio") or "").lower().replace("www.", "").strip()
        if dp and (host == dp or host == f"www.{dp}"):
            return t["slug"]
    return None


# ------------------- Productos -------------------

def carpeta_uploads(slug: str) -> str:
    ruta = os.path.join(UPLOADS_DIR, slug)
    os.makedirs(ruta, exist_ok=True)
    return ruta


def url_uploads(slug: str, archivo: str) -> str:
    """Ruta pública (servible por /u) de un archivo subido de la tienda."""
    return f"/u/{slug}/{archivo}"


# ------------------- Servicios y Citas -------------------

def buscar_servicio(tienda: dict, servicio_id: str):
    for s in tienda.get("servicios", []):
        if s.get("id") == servicio_id:
            return s
    return None


def buscar_producto(tienda: dict, producto_id: str):
    for p in tienda.get("productos", []):
        if p.get("id") == producto_id:
            return p
    return None


def descontar_stock(slug: str, items: list):
    """Resta del inventario las cantidades vendidas. items=[{id, cantidad}]."""
    tienda = obtener_tienda(slug)
    if tienda is None:
        return
    by_id = {p.get("id"): p for p in tienda.get("productos", [])}
    cambiado = False
    for it in items:
        p = by_id.get(it.get("id"))
        if p and isinstance(p.get("stock"), (int, float)):
            p["stock"] = max(0, int(p["stock"]) - int(it.get("cantidad", 1)))
            cambiado = True
    if cambiado:
        tienda["actualizada"] = _ahora()
        _guardar(tienda)


def agregar_cita(slug: str, cita: dict):
    """Persiste una cita en la tienda. Devuelve la cita o None si no existe la tienda."""
    tienda = obtener_tienda(slug)
    if tienda is None:
        return None
    tienda.setdefault("citas", []).append(cita)
    tienda["actualizada"] = _ahora()
    _guardar(tienda)
    return cita


def citas_de_fecha(tienda: dict, fecha: str):
    """Citas (no canceladas) de una fecha YYYY-MM-DD."""
    return [c for c in tienda.get("citas", [])
            if c.get("fecha") == fecha and c.get("estado") != "cancelada"]


# ------------------- CRM: Leads -------------------

def listar_leads(slug: str):
    t = obtener_tienda(slug)
    return (t or {}).get("leads", [])


def buscar_lead(tienda: dict, lead_id: str):
    for l in tienda.get("leads", []):
        if l.get("id") == lead_id:
            return l
    return None


def buscar_lead_por_telefono(tienda: dict, telefono: str):
    tel = (telefono or "").strip()
    if not tel:
        return None
    for l in tienda.get("leads", []):
        if l.get("telefono") == tel:
            return l
    return None


def crear_lead(slug: str, lead: dict):
    """Agrega un lead a la tienda. Devuelve el lead o None si no existe la tienda."""
    tienda = obtener_tienda(slug)
    if tienda is None:
        return None
    tienda.setdefault("leads", []).insert(0, lead)   # más reciente primero
    tienda["actualizada"] = _ahora()
    _guardar(tienda)
    return lead


def actualizar_lead(slug: str, lead_id: str, cambios: dict):
    """Aplica cambios parciales a un lead. Devuelve el lead actualizado o None."""
    tienda = obtener_tienda(slug)
    if tienda is None:
        return None
    lead = buscar_lead(tienda, lead_id)
    if lead is None:
        return None
    lead.update(cambios)
    lead["actualizado"] = _ahora()
    tienda["actualizada"] = _ahora()
    _guardar(tienda)
    return lead


def eliminar_lead(slug: str, lead_id: str) -> bool:
    tienda = obtener_tienda(slug)
    if tienda is None:
        return False
    antes = len(tienda.get("leads", []))
    tienda["leads"] = [l for l in tienda.get("leads", []) if l.get("id") != lead_id]
    if len(tienda["leads"]) == antes:
        return False
    tienda["actualizada"] = _ahora()
    _guardar(tienda)
    return True


# ------------------- Colecciones genéricas (equipo / movimientos / gastos) -------------------

def listar(slug: str, coleccion: str):
    return (obtener_tienda(slug) or {}).get(coleccion, [])


def agregar(slug: str, coleccion: str, item: dict, al_inicio: bool = True):
    tienda = obtener_tienda(slug)
    if tienda is None:
        return None
    lista = tienda.setdefault(coleccion, [])
    lista.insert(0, item) if al_inicio else lista.append(item)
    tienda["actualizada"] = _ahora()
    _guardar(tienda)
    return item


def actualizar_item(slug: str, coleccion: str, item_id: str, cambios: dict):
    tienda = obtener_tienda(slug)
    if tienda is None:
        return None
    for it in tienda.get(coleccion, []):
        if it.get("id") == item_id:
            it.update(cambios)
            tienda["actualizada"] = _ahora()
            _guardar(tienda)
            return it
    return None


def eliminar_item(slug: str, coleccion: str, item_id: str) -> bool:
    tienda = obtener_tienda(slug)
    if tienda is None:
        return False
    antes = len(tienda.get(coleccion, []))
    tienda[coleccion] = [x for x in tienda.get(coleccion, []) if x.get("id") != item_id]
    if len(tienda[coleccion]) == antes:
        return False
    tienda["actualizada"] = _ahora()
    _guardar(tienda)
    return True

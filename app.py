# app.py — Backend FastAPI con Openpay (SPEI) + Banregio (transferencia directa)
# -------------------------------------------------------------------
# Flujo de pago (distinto a Stripe: el cliente NO sale de tu sitio):
#   1. Cliente arma su carrito.
#   2. En /checkout llena un formulario corto (nombre, correo) y elige método.
#   3a. Si elige SPEI Openpay  -> creamos un "cargo bank_account" y Openpay
#       nos devuelve una CLABE + referencia que le mostramos al cliente.
#   3b. Si elige Banregio      -> le mostramos TU CLABE de Banregio y las
#       instrucciones para que transfiera y mande comprobante.
# -------------------------------------------------------------------
import os
import secrets
from fastapi import FastAPI, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware

import auth
import catalogo
import config_pagos as cfg
import correo
import db
import pagos_mercadopago
import pagos_openpay
import pagos_stripe
import seo

# Llave para firmar las cookies de sesión. En producción DEBE venir de
# SESSION_SECRET_KEY (env var). Si falta, generamos una aleatoria en
# memoria: las sesiones existentes se invalidan al reiniciar el proceso.
SESSION_SECRET_KEY = os.getenv("SESSION_SECRET_KEY")
if not SESSION_SECRET_KEY:
    SESSION_SECRET_KEY = secrets.token_urlsafe(32)
    print("⚠  SESSION_SECRET_KEY no está configurada. Usando una llave aleatoria en memoria — "
          "las sesiones se invalidan al reiniciar. Configúrala como env var en producción.")

app = FastAPI(title="Tienda de Patines Hidraulicos")
app.add_middleware(SessionMiddleware, secret_key=SESSION_SECRET_KEY)
app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")
templates.env.globals["es_admin"] = auth.es_admin


@app.on_event("startup")
def _startup():
    db.init()

# --- Configurar Openpay (API REST) desde config_pagos.py ---
# Las constantes de Openpay (URL base + auth) viven ahora en pagos_openpay.


# --- Helpers del carrito (viven en la sesion como {producto_id: cantidad}) ---
def obtener_carrito(request):
    return request.session.get("carrito", {})

def guardar_carrito(request, carrito):
    request.session["carrito"] = carrito

IVA = 0.16  # 16% IVA en México

# Paqueterías disponibles para "ocurre" (recoge en terminal)
PAQUETERIAS = ["Castores", "Autolínea Villarreal"]

def costo_envio(unidades):
    """Tabla de envío "ocurre" por # de patines. None = bajo cotización."""
    if unidades <= 0:   return 0
    if unidades == 1:   return 1300
    if unidades <= 5:   return 1980
    if unidades <= 10:  return 2450
    return None          # 11+ requiere cotización manual

def carrito_detallado(carrito):
    """Devuelve items, subtotal productos, # unidades, envío, IVA y total.
    Si hay 11+ unidades el envío es None y los demás totales también
    (el cliente debe cotizar por WhatsApp en vez de comprar online)."""
    items, subtotal_productos, unidades = [], 0, 0
    for pid, cant in carrito.items():
        p = catalogo.buscar_producto(pid)
        if not p or p["precio"] is None:
            continue
        sub = p["precio"] * cant
        subtotal_productos += sub
        unidades += cant
        items.append({"producto": p, "cantidad": cant, "subtotal": sub})
    envio = costo_envio(unidades)
    if envio is None:
        return items, subtotal_productos, unidades, None, None, None
    subtotal = subtotal_productos + envio
    iva = round(subtotal * IVA)
    total = subtotal + iva
    return items, subtotal_productos, unidades, envio, iva, total


# --- RUTAS ---
@app.get("/", response_class=HTMLResponse)
def home(request: Request):
    carrito = obtener_carrito(request)
    return templates.TemplateResponse(request, "index.html", {
        "productos": catalogo.listar_productos(),
        "categorias": catalogo.categorias(),
        "total_items": sum(carrito.values()),
        "meta": seo.meta_home(),
        "schema_org": seo.schema_organizacion(),
        "sitio": seo.SITIO,
        "testimonios": seo.TESTIMONIOS,
        "usuario": auth.current_user(request),
    })


@app.get("/producto/{producto_id}", response_class=HTMLResponse)
def pagina_producto(request: Request, producto_id: str):
    """Página individual de producto — clave para SEO y conversión."""
    p = catalogo.buscar_producto(producto_id)
    if not p:
        return RedirectResponse(url="/", status_code=303)
    carrito = obtener_carrito(request)
    # Productos relacionados: misma categoría, excluyendo el actual.
    relacionados = [
        x for x in catalogo.listar_productos()
        if x["categoria"] == p["categoria"] and x["id"] != p["id"]
    ][:3]
    return templates.TemplateResponse(request, "producto.html", {
        "p": p,
        "relacionados": relacionados,
        "total_items": sum(carrito.values()),
        "meta": seo.meta_producto(p),
        "schema_producto": seo.schema_producto(p),
        "schema_breadcrumb": seo.schema_breadcrumb([
            ("Inicio", "/"),
            (p["categoria"], "/"),
            (p["nombre"], f"/producto/{p['id']}"),
        ]),
        "sitio": seo.SITIO,
        "keywords_cat": seo.KEYWORDS_LONG_TAIL.get(p["categoria"], []),
        "usuario": auth.current_user(request),
    })

@app.post("/agregar")
def agregar(request: Request, producto_id: str = Form(...), cantidad: int = Form(1)):
    cantidad = max(1, min(int(cantidad or 1), 99))
    carrito = obtener_carrito(request)
    carrito[producto_id] = carrito.get(producto_id, 0) + cantidad
    guardar_carrito(request, carrito)
    return RedirectResponse(url="/carrito", status_code=303)

@app.post("/actualizar")
def actualizar(request: Request, producto_id: str = Form(...), cantidad: int = Form(...)):
    cantidad = max(0, min(int(cantidad), 99))
    carrito = obtener_carrito(request)
    if cantidad <= 0:
        carrito.pop(producto_id, None)
    else:
        carrito[producto_id] = cantidad
    guardar_carrito(request, carrito)
    return RedirectResponse(url="/carrito", status_code=303)

@app.get("/carrito", response_class=HTMLResponse)
def ver_carrito(request: Request):
    items, subtotal_prod, unidades, envio, iva, total = carrito_detallado(obtener_carrito(request))
    return templates.TemplateResponse(request, "carrito.html", {
        "items": items, "subtotal_prod": subtotal_prod, "unidades": unidades,
        "envio": envio, "iva": iva, "total": total, "sitio": seo.SITIO,
        "total_items": unidades, "usuario": auth.current_user(request)})

@app.post("/eliminar")
def eliminar(request: Request, producto_id: str = Form(...)):
    carrito = obtener_carrito(request)
    carrito.pop(producto_id, None)
    guardar_carrito(request, carrito)
    return RedirectResponse(url="/carrito", status_code=303)


@app.get("/checkout", response_class=HTMLResponse)
def checkout_form(request: Request):
    """Muestra el formulario de datos del cliente + elección de método."""
    items, subtotal_prod, unidades, envio, iva, total = carrito_detallado(obtener_carrito(request))
    if not items:
        return RedirectResponse(url="/carrito", status_code=303)
    if envio is None:
        # 11+ patines → no se puede comprar online, redirigir a carrito que muestra CTA WhatsApp
        return RedirectResponse(url="/carrito", status_code=303)
    return templates.TemplateResponse(request, "checkout.html", {
        "items": items, "subtotal_prod": subtotal_prod, "unidades": unidades,
        "envio": envio, "iva": iva, "total": total,
        "paqueterias": PAQUETERIAS, "sitio": seo.SITIO,
        "total_items": unidades, "usuario": auth.current_user(request),
        "pagos_stripe_on":       pagos_stripe.disponible(),
        "pagos_mercadopago_on":  pagos_mercadopago.disponible(),
        "pagos_openpay_on":      pagos_openpay.disponible(),
    })


@app.post("/pagar", response_class=HTMLResponse)
def procesar_pago(
    request: Request,
    nombre: str = Form(...),
    email_cliente: str = Form(..., alias="correo"),
    telefono: str = Form(""),
    metodo: str = Form(...),       # "spei" o "banregio"
    paqueteria: str = Form("Castores"),
    ciudad_entrega: str = Form(...),
    estado_entrega: str = Form(...),
    sucursal: str = Form(""),
    rfc: str = Form(""),
    razon_social: str = Form(""),
    cp_fiscal: str = Form(""),
):
    items, subtotal_prod, unidades, envio, iva, total = carrito_detallado(obtener_carrito(request))
    if not items or envio is None:
        return RedirectResponse(url="/carrito", status_code=303)

    # Generamos un número de pedido simple basado en la sesión.
    import random
    pedido = "PED-" + str(random.randint(10000, 99999))

    if metodo == "banregio":
        # --- Transferencia directa: solo mostramos TUS datos. Sin API. ---
        # Persistir el pedido en BD si está disponible.
        usuario = auth.current_user(request)
        items_snapshot = [
            {"id": it["producto"]["id"], "nombre": it["producto"]["nombre"],
             "precio": it["producto"]["precio"], "cantidad": it["cantidad"],
             "subtotal": it["subtotal"]} for it in items
        ]
        if db.disponible():
            db.crear_pedido(
                pedido_id=pedido,
                user_id=(usuario["id"] if usuario else None),
                email=email_cliente, nombre=nombre, telefono=telefono,
                items=items_snapshot,
                subtotal_prod=subtotal_prod, envio=envio, iva=iva, total=total,
                unidades=unidades, paqueteria=paqueteria, metodo="banregio",
                ciudad_entrega=ciudad_entrega, estado_entrega=estado_entrega,
                sucursal=sucursal,
                rfc=rfc, razon_social=razon_social, cp_fiscal=cp_fiscal,
            )
        # Correo de confirmación (best-effort: no rompe el flujo si falla)
        correo.enviar_confirmacion_pedido(
            pedido={
                "id": pedido, "nombre": nombre, "email": email_cliente,
                "items": items_snapshot,
                "subtotal_prod": subtotal_prod, "envio": envio, "iva": iva,
                "total": total, "paqueteria": paqueteria,
            },
            banregio=cfg.BANREGIO,
            dominio=seo.SITIO["dominio"],
        )
        # Recordar este pedido en la sesión para que el guest pueda verlo
        recientes = request.session.get("recent_pedidos", [])
        recientes.insert(0, pedido)
        request.session["recent_pedidos"] = recientes[:10]

        guardar_carrito(request, {})
        return templates.TemplateResponse(request, "pago_banregio.html", {
            "banregio": cfg.BANREGIO,
            "subtotal_prod": subtotal_prod,
            "envio": envio,
            "iva": iva,
            "total": total,
            "unidades": unidades,
            "paqueteria": paqueteria,
            "pedido": pedido,
            "nombre": nombre,
            "ciudad_entrega": ciudad_entrega,
            "estado_entrega": estado_entrega,
            "sucursal": sucursal,
            "items_snapshot": items_snapshot,  # para GA4 purchase
            "sitio": seo.SITIO,
        })

    elif metodo == "openpay":
        # --- SPEI vía Openpay (módulo pagos_openpay) ---
        if not pagos_openpay.disponible():
            return templates.TemplateResponse(request, "error_pago.html", {
                "mensaje": "Openpay no está habilitado. Usa Banregio o cotiza por WhatsApp."})
        try:
            datos_spei = pagos_openpay.crear_cargo_spei(
                pedido_id=pedido, total=total,
                descripcion=f"Pedido {pedido} - Outlet Momatt México",
                nombre=nombre, email=email_cliente, telefono=telefono,
            )
            guardar_carrito(request, {})
            return templates.TemplateResponse(request, "pago_spei.html", {
                "datos": datos_spei, "total": total,
                "pedido": pedido, "nombre": nombre,
            })
        except Exception as e:
            return templates.TemplateResponse(request, "error_pago.html", {
                "mensaje": f"Error al conectar con Openpay: {e}"})

    elif metodo in ("stripe", "mercadopago"):
        # --- Gateways de checkout hospedado (Stripe / Mercado Pago) ---
        modulo = pagos_stripe if metodo == "stripe" else pagos_mercadopago
        if not modulo.disponible():
            return templates.TemplateResponse(request, "error_pago.html", {
                "mensaje": f"La integración con {metodo.title()} todavía no está activa. "
                           "Usa Banregio o avísanos por WhatsApp para procesar tu pago."})
        try:
            url_redirect = modulo.crear_pago(
                pedido_id=pedido,
                total_centavos=int(total * 100),
                descripcion=f"Pedido {pedido} - Outlet Momatt",
                email_cliente=email_cliente,
                items=items_snapshot,
                success_url=f"{seo.SITIO['dominio']}/pedido/{pedido}",
                cancel_url=f"{seo.SITIO['dominio']}/checkout",
            )
            # Persistir el pedido en estado pendiente (el webhook lo pasará a pagado)
            usuario = auth.current_user(request)
            if db.disponible():
                db.crear_pedido(
                    pedido_id=pedido,
                    user_id=(usuario["id"] if usuario else None),
                    email=email_cliente, nombre=nombre, telefono=telefono,
                    items=items_snapshot,
                    subtotal_prod=subtotal_prod, envio=envio, iva=iva, total=total,
                    unidades=unidades, paqueteria=paqueteria, metodo=metodo,
                    ciudad_entrega=ciudad_entrega, estado_entrega=estado_entrega,
                    sucursal=sucursal,
                    rfc=rfc, razon_social=razon_social, cp_fiscal=cp_fiscal,
                )
            guardar_carrito(request, {})
            return RedirectResponse(url=url_redirect, status_code=303)
        except NotImplementedError:
            return templates.TemplateResponse(request, "error_pago.html", {
                "mensaje": f"La integración con {metodo.title()} aún no está terminada. "
                           "Usa Banregio o cotiza por WhatsApp."})
        except Exception as e:
            return templates.TemplateResponse(request, "error_pago.html", {
                "mensaje": f"Error con {metodo.title()}: {e}"})

    else:
        return RedirectResponse(url="/checkout", status_code=303)


# --- Auth: registro, login, logout, perfil ---

def _bd_o_error(request):
    """Si la BD no está configurada, devuelve una respuesta de error amigable."""
    if not db.disponible():
        return templates.TemplateResponse(request, "error_pago.html", {
            "mensaje": "Las cuentas de usuario están temporalmente deshabilitadas "
                       "(falta configurar la base de datos). Puedes seguir comprando "
                       "como invitado.",
        })
    return None


@app.get("/registro", response_class=HTMLResponse)
def registro_form(request: Request):
    err = _bd_o_error(request)
    if err: return err
    if auth.current_user(request):
        return RedirectResponse(url="/perfil", status_code=303)
    return templates.TemplateResponse(request, "registro.html", {
        "sitio": seo.SITIO, "error": None, "valores": {}})


@app.post("/registro", response_class=HTMLResponse)
def registro_submit(request: Request,
                    email: str = Form(...), password: str = Form(...),
                    nombre: str = Form(...), telefono: str = Form("")):
    err = _bd_o_error(request)
    if err: return err
    valores = {"email": email, "nombre": nombre, "telefono": telefono}
    if len(password) < 8:
        return templates.TemplateResponse(request, "registro.html", {
            "sitio": seo.SITIO, "valores": valores,
            "error": "La contraseña debe tener al menos 8 caracteres."})
    try:
        if db.buscar_usuario_por_email(email):
            return templates.TemplateResponse(request, "registro.html", {
                "sitio": seo.SITIO, "valores": valores,
                "error": "Ya existe una cuenta con ese correo. Inicia sesión."})
        usuario = db.crear_usuario(email, auth.hash_password(password), nombre, telefono)
        db.adoptar_pedidos_huerfanos(usuario["id"], email)
        auth.login_session(request, usuario)
        return RedirectResponse(url="/perfil?welcome=1", status_code=303)
    except Exception as e:
        # Loguea el detalle en stderr (visible en Render Logs) y
        # muestra un mensaje genérico al cliente.
        import traceback
        print(f"❌ Error en /registro: {e!r}")
        traceback.print_exc()
        return templates.TemplateResponse(request, "registro.html", {
            "sitio": seo.SITIO, "valores": valores,
            "error": f"Hubo un error al crear tu cuenta. Detalle: {type(e).__name__}. "
                     "Intenta de nuevo o escríbenos por WhatsApp."})


@app.get("/login", response_class=HTMLResponse)
def login_form(request: Request):
    err = _bd_o_error(request)
    if err: return err
    if auth.current_user(request):
        return RedirectResponse(url="/perfil", status_code=303)
    return templates.TemplateResponse(request, "login.html", {
        "sitio": seo.SITIO, "error": None, "email": ""})


@app.post("/login", response_class=HTMLResponse)
def login_submit(request: Request, email: str = Form(...), password: str = Form(...)):
    err = _bd_o_error(request)
    if err: return err
    usuario = db.buscar_usuario_por_email(email)
    if not usuario or not auth.verify_password(password, usuario["password_hash"]):
        return templates.TemplateResponse(request, "login.html", {
            "sitio": seo.SITIO, "email": email,
            "error": "Correo o contraseña incorrectos."})
    auth.login_session(request, usuario)
    return RedirectResponse(url="/perfil", status_code=303)


@app.post("/logout")
def logout(request: Request):
    auth.logout_session(request)
    return RedirectResponse(url="/", status_code=303)


@app.get("/perfil", response_class=HTMLResponse)
def perfil(request: Request):
    err = _bd_o_error(request)
    if err: return err
    usuario = auth.current_user(request)
    if not usuario:
        return RedirectResponse(url="/login", status_code=303)
    pedidos = db.listar_pedidos_de_usuario(usuario["id"])
    return templates.TemplateResponse(request, "perfil.html", {
        "sitio": seo.SITIO, "usuario": usuario, "pedidos": pedidos})


@app.get("/pedido/{pedido_id}", response_class=HTMLResponse)
def ver_pedido(request: Request, pedido_id: str):
    err = _bd_o_error(request)
    if err: return err
    try:
        pedido = db.buscar_pedido(pedido_id)
        if not pedido:
            return RedirectResponse(url="/", status_code=303)
        # Autorización: dueño logueado O guest que lo hizo en esta sesión
        usuario = auth.current_user(request)
        recientes = request.session.get("recent_pedidos", [])
        autorizado = (usuario and pedido.get("user_id") == usuario["id"]) or (pedido_id in recientes)
        if not autorizado:
            return templates.TemplateResponse(request, "error_pago.html", {
                "mensaje": "Este pedido pertenece a otra cuenta. Inicia sesión para verlo."})

        # psycopg3 decodifica JSONB a list/dict. Si vino como string lo parseamos.
        import json as _json
        items = pedido.get("items")
        if isinstance(items, str):
            items = _json.loads(items)

        # Importante: NO pasamos los items dentro del dict `pedido` porque
        # `pedido.items` en Jinja resuelve como el método dict.items() —
        # los pasamos como variable separada.
        return templates.TemplateResponse(request, "pedido_detalle.html", {
            "sitio": seo.SITIO, "pedido": pedido, "items": items or [],
            "banregio": cfg.BANREGIO, "usuario": usuario})
    except Exception as e:
        import traceback
        print(f"❌ Error en /pedido/{pedido_id}: {e!r}")
        traceback.print_exc()
        return templates.TemplateResponse(request, "error_pago.html", {
            "mensaje": f"No se pudo cargar el pedido. Detalle técnico: "
                       f"{type(e).__name__}: {e}. Avísanos por WhatsApp para "
                       f"resolverlo y mientras tanto te confirmamos tu pedido "
                       f"manualmente con el número {pedido_id}."})


@app.post("/pedido/{pedido_id}/marcar-pagado")
def marcar_pagado(request: Request, pedido_id: str):
    """Autoservicio: el cliente declara que ya transfirió y mandó comprobante.
    Detiene los recordatorios. Falta la confirmación manual del admin."""
    err = _bd_o_error(request)
    if err: return err
    pedido = db.buscar_pedido(pedido_id)
    if not pedido or pedido.get("estado") != "pendiente_pago":
        return RedirectResponse(url=f"/pedido/{pedido_id}", status_code=303)

    usuario = auth.current_user(request)
    recientes = request.session.get("recent_pedidos", [])
    autorizado = (usuario and pedido.get("user_id") == usuario["id"]) or (pedido_id in recientes)
    if not autorizado:
        return templates.TemplateResponse(request, "error_pago.html", {
            "mensaje": "No puedes modificar este pedido."})

    db.actualizar_estado_pedido(pedido_id, "comprobante_enviado")
    return RedirectResponse(url=f"/pedido/{pedido_id}", status_code=303)


# --- Admin: dashboard y gestión de pedidos ---

# Estados válidos para un pedido (define la "state machine")
ESTADOS_PEDIDO = [
    "pendiente_pago", "comprobante_enviado", "pagado", "enviado", "entregado", "cancelado"
]

def _require_admin(request):
    """Devuelve (usuario, None) si es admin, o (None, Response) si no."""
    err = _bd_o_error(request)
    if err: return None, err
    usuario = auth.current_user(request)
    if not usuario:
        return None, RedirectResponse(url="/login", status_code=303)
    if not auth.es_admin(usuario):
        return None, templates.TemplateResponse(request, "error_pago.html", {
            "mensaje": "Esta sección es solo para administradores."})
    return usuario, None


@app.get("/admin", response_class=HTMLResponse)
def admin_dashboard(request: Request):
    usuario, err = _require_admin(request)
    if err: return err
    stats = db.stats_dashboard()
    recientes = db.listar_pedidos(limit=10)
    return templates.TemplateResponse(request, "admin_dashboard.html", {
        "sitio": seo.SITIO, "usuario": usuario,
        "stats": stats, "recientes": recientes})


@app.get("/admin/pedidos", response_class=HTMLResponse)
def admin_pedidos(request: Request, estado: str = "todos", q: str = ""):
    usuario, err = _require_admin(request)
    if err: return err
    pedidos = db.listar_pedidos(estado=estado, busqueda=q or None)
    return templates.TemplateResponse(request, "admin_pedidos.html", {
        "sitio": seo.SITIO, "usuario": usuario,
        "pedidos": pedidos, "estado_filtro": estado, "busqueda": q,
        "estados": ESTADOS_PEDIDO})


@app.get("/admin/usuarios", response_class=HTMLResponse)
def admin_usuarios(request: Request, q: str = ""):
    usuario, err = _require_admin(request)
    if err: return err
    usuarios = db.listar_usuarios(busqueda=q or None)
    return templates.TemplateResponse(request, "admin_usuarios.html", {
        "sitio": seo.SITIO, "usuario": usuario,
        "usuarios": usuarios, "busqueda": q})


@app.get("/admin/pedido/{pedido_id}", response_class=HTMLResponse)
def admin_pedido_detalle(request: Request, pedido_id: str):
    usuario, err = _require_admin(request)
    if err: return err
    pedido = db.buscar_pedido(pedido_id)
    if not pedido:
        return RedirectResponse(url="/admin/pedidos", status_code=303)
    # JSONB items: defensiva
    import json as _json
    items = pedido.get("items")
    if isinstance(items, str):
        items = _json.loads(items)
    return templates.TemplateResponse(request, "admin_pedido_detalle.html", {
        "sitio": seo.SITIO, "usuario": usuario, "pedido": pedido,
        "items": items or [], "banregio": cfg.BANREGIO,
        "estados": ESTADOS_PEDIDO})


@app.post("/admin/pedido/{pedido_id}/estado")
def admin_cambiar_estado(request: Request, pedido_id: str,
                         nuevo_estado: str = Form(...),
                         guia: str = Form("")):
    usuario, err = _require_admin(request)
    if err: return err
    if nuevo_estado not in ESTADOS_PEDIDO:
        return templates.TemplateResponse(request, "error_pago.html", {
            "mensaje": f"Estado inválido: {nuevo_estado}"})
    db.actualizar_estado_pedido(pedido_id, nuevo_estado,
                                 guia=guia.strip() or None)
    return RedirectResponse(url=f"/admin/pedido/{pedido_id}", status_code=303)


# --- Webhooks de gateways de pago ---

from fastapi.responses import JSONResponse


async def _aplicar_cambio_estado(pedido_id: str, nuevo_estado: str):
    """Aplica una transición de estado disparada por un webhook."""
    if not (pedido_id and nuevo_estado):
        return
    if not db.disponible():
        return
    db.actualizar_estado_pedido(pedido_id, nuevo_estado)
    # TODO: cuando esté listo, mandar correo de pago confirmado al cliente


@app.post("/webhook/openpay")
async def webhook_openpay(request: Request):
    """Openpay no firma con secreto — se asegura por whitelist de IP en
    la cuenta. Procesa eventos charge.succeeded / charge.failed."""
    try:
        body = await request.json()
        pedido_id, nuevo_estado = pagos_openpay.procesar_webhook(body)
        await _aplicar_cambio_estado(pedido_id, nuevo_estado)
        return {"ok": True}
    except Exception as e:
        print(f"⚠  webhook_openpay error: {e}")
        return JSONResponse({"error": str(e)}, status_code=400)


@app.post("/webhook/stripe")
async def webhook_stripe(request: Request):
    """Stripe firma con STRIPE_WEBHOOK_SECRET. Sin firma → rechazamos."""
    body = await request.body()
    sig = request.headers.get("stripe-signature", "")
    try:
        evento = pagos_stripe.verificar_webhook(sig, body)
        pedido_id, nuevo_estado = pagos_stripe.procesar_evento(evento)
        await _aplicar_cambio_estado(pedido_id, nuevo_estado)
        return {"ok": True}
    except NotImplementedError:
        # Llega un webhook real pero el módulo aún no está terminado
        return JSONResponse({"error": "stripe handler pending"}, status_code=501)
    except Exception as e:
        print(f"⚠  webhook_stripe error: {e}")
        return JSONResponse({"error": str(e)}, status_code=400)


@app.post("/webhook/mercadopago")
async def webhook_mercadopago(request: Request):
    """MP firma con x-signature (HMAC). request-id y data.id van en headers/query."""
    body = await request.body()
    sig = request.headers.get("x-signature", "")
    req_id = request.headers.get("x-request-id", "")
    data_id = request.query_params.get("data.id", "")
    try:
        evento = pagos_mercadopago.verificar_webhook(sig, body, req_id, data_id)
        pedido_id, nuevo_estado = pagos_mercadopago.procesar_evento(evento)
        await _aplicar_cambio_estado(pedido_id, nuevo_estado)
        return {"ok": True}
    except NotImplementedError:
        return JSONResponse({"error": "mercadopago handler pending"}, status_code=501)
    except Exception as e:
        print(f"⚠  webhook_mercadopago error: {e}")
        return JSONResponse({"error": str(e)}, status_code=400)


# --- Cron: recordatorios de pago ---

CRON_TOKEN = os.getenv("CRON_TOKEN", "")


@app.get("/cron/recordatorios")
@app.post("/cron/recordatorios")
def cron_recordatorios(token: str = ""):
    """Endpoint para cron-job.org. Se llama cada 6 hrs.
    Autenticación: ?token=CRON_TOKEN.
    Manda hasta 50 recordatorios por llamada."""
    if not CRON_TOKEN or token != CRON_TOKEN:
        from fastapi.responses import JSONResponse
        return JSONResponse({"error": "unauthorized"}, status_code=401)
    if not db.disponible():
        return {"error": "db_unavailable", "enviados": 0}

    pendientes = db.pedidos_para_recordatorio(
        max_recordatorios=2,
        horas_desde_pedido=24,
        horas_entre_recordatorios=48,
    )
    enviados, fallidos = 0, 0
    for p in pendientes:
        ok = correo.enviar_recordatorio_pago(
            pedido=p,
            banregio=cfg.BANREGIO,
            dominio=seo.SITIO["dominio"],
            whatsapp_visible=seo.SITIO.get("whatsapp_visible", ""),
            whatsapp_digits=seo.SITIO.get("whatsapp", ""),
        )
        if ok:
            db.marcar_recordatorio_enviado(p["id"])
            enviados += 1
        else:
            fallidos += 1
    return {"enviados": enviados, "fallidos": fallidos, "candidatos": len(pendientes)}


# --- SEO técnico: sitemap y robots ---
from fastapi.responses import Response, PlainTextResponse

@app.get("/sitemap.xml")
def sitemap():
    """Mapa del sitio: lista todas las URLs para que Google las indexe."""
    base = seo.SITIO["dominio"]
    urls = [f"{base}/"]
    for p in catalogo.listar_productos():
        urls.append(f"{base}/producto/{p['id']}")
    items = "".join(
        f"<url><loc>{u}</loc><changefreq>weekly</changefreq><priority>0.8</priority></url>"
        for u in urls
    )
    xml = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
        f"{items}</urlset>"
    )
    return Response(content=xml, media_type="application/xml")

@app.get("/robots.txt")
def robots():
    """Permite a los buscadores rastrear todo y apunta al sitemap."""
    contenido = (
        "User-agent: *\n"
        "Allow: /\n"
        f"Sitemap: {seo.SITIO['dominio']}/sitemap.xml\n"
    )
    return PlainTextResponse(content=contenido)

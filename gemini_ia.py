# gemini_ia.py — Capa de Inteligencia Artificial (Google Gemini)
# -------------------------------------------------------------------
# Toda la "magia" del asistente vive aquí:
#   - redactar_negocio()   -> eslogan, "sobre nosotros", colores, tono.
#   - describir_productos() -> descripción + categoría + SEO por producto.
#   - generar_logo()       -> imagen de logo (Gemini/Imagen) o monograma SVG.
#   - chatbot_responder()  -> asistente de ventas por tienda.
#
# DISEÑO CLAVE: degradación elegante. Si NO hay GEMINI_API_KEY (o el SDK
# no está instalado, o la API falla), cada función devuelve un resultado
# razonable hecho con plantillas locales. Así el constructor SIEMPRE
# funciona; la IA solo lo hace mejor.
# -------------------------------------------------------------------
import json
import os
import re

# Modelos (configurables por env; valores por defecto a los más recientes).
MODELO_TEXTO = os.getenv("GEMINI_MODELO_TEXTO", "gemini-2.5-flash")
MODELO_IMAGEN = os.getenv("GEMINI_MODELO_IMAGEN", "gemini-2.5-flash-image")

_API_KEY = os.getenv("GEMINI_API_KEY", "") or os.getenv("GOOGLE_API_KEY", "")

try:
    from google import genai
    from google.genai import types as genai_types
    _SDK_OK = True
except ImportError:
    _SDK_OK = False

_cliente = None


def disponible() -> bool:
    """¿Está la IA realmente operativa (SDK instalado + API key)?"""
    return bool(_SDK_OK and _API_KEY)


def _client():
    global _cliente
    if _cliente is None:
        _cliente = genai.Client(api_key=_API_KEY)
    return _cliente


# ------------------- Utilidades -------------------

def _extraer_json(texto: str):
    """Saca el primer objeto/array JSON de la respuesta del modelo,
    tolerando ```json ... ``` y texto alrededor."""
    if not texto:
        return None
    texto = re.sub(r"```(?:json)?", "", texto).strip("` \n")
    m = re.search(r"(\{.*\}|\[.*\])", texto, re.DOTALL)
    if not m:
        return None
    try:
        return json.loads(m.group(1))
    except json.JSONDecodeError:
        return None


def _generar_texto(prompt: str, json_mode: bool = False) -> str:
    cfg = None
    if json_mode:
        cfg = genai_types.GenerateContentConfig(response_mime_type="application/json")
    resp = _client().models.generate_content(
        model=MODELO_TEXTO, contents=prompt, config=cfg
    )
    return (resp.text or "").strip()


# ------------------- 1) Redactar el negocio -------------------

def redactar_negocio(nombre: str, giro: str, contexto: str) -> dict:
    """A partir de un contexto corto, devuelve identidad de marca:
       { eslogan, sobre_nosotros, color, color_2, tono }."""
    if disponible():
        prompt = (
            "Eres un experto en branding para PyMEs en México, con sensibilidad "
            "para negocios personales y artesanales (belleza, bienestar, estética, "
            "repostería, hechos a mano). Tono cálido, humano y cercano, evitando "
            "clichés. Con la siguiente información de un negocio, genera su "
            "identidad de marca.\n\n"
            f"Nombre: {nombre}\nGiro: {giro}\nContexto del dueño: {contexto}\n\n"
            "Devuelve SOLO un JSON con esta forma exacta:\n"
            '{\n'
            '  "eslogan": "frase corta y vendedora, máx 8 palabras",\n'
            '  "sobre_nosotros": "2-3 oraciones cálidas en primera persona del plural",\n'
            '  "color": "#RRGGBB color principal que combine con el giro",\n'
            '  "color_2": "#RRGGBB color de acento complementario",\n'
            '  "tono": "describe en pocas palabras el tono de la marca"\n'
            "}"
        )
        try:
            data = _extraer_json(_generar_texto(prompt, json_mode=True))
            if data and data.get("eslogan"):
                return {
                    "eslogan": data.get("eslogan", ""),
                    "sobre_nosotros": data.get("sobre_nosotros", ""),
                    "color": _color_valido(data.get("color"), "#fe4e02"),
                    "color_2": _color_valido(data.get("color_2"), ""),
                    "tono": data.get("tono", "cercano y profesional"),
                }
        except Exception as e:  # noqa: BLE001 — degradar ante cualquier fallo de API
            print(f"⚠  Gemini (negocio) falló, usando plantilla: {e}")

    # --- Fallback sin IA ---
    g = giro or "negocio"
    return {
        "eslogan": f"{nombre}: calidad que se nota",
        "sobre_nosotros": (
            f"En {nombre} nos dedicamos a {g.lower()} con pasión y compromiso. "
            "Atendemos a cada cliente como nos gustaría que nos atendieran: con "
            "honestidad, buen precio y trato cercano."
        ),
        "color": "#fe4e02",
        "color_2": "#1a1a1a",
        "tono": "cercano y profesional",
    }


def _color_valido(valor, default):
    if isinstance(valor, str) and re.fullmatch(r"#[0-9a-fA-F]{6}", valor.strip()):
        return valor.strip()
    return default


# ------------------- 2) Describir productos -------------------

def describir_productos(productos: list, giro: str = "") -> list:
    """Recibe productos con al menos `nombre` (y opcional precio) y devuelve
    la misma lista enriquecida con `descripcion`, `categoria` y `seo_titulo`.
    Procesa en un solo prompt para ahorrar llamadas."""
    if not productos:
        return productos

    if disponible():
        lista = [
            {"nombre": p.get("nombre", ""), "precio": p.get("precio")}
            for p in productos
        ]
        prompt = (
            f"Eres copywriter de e-commerce en México. Giro del negocio: {giro or 'general'}.\n"
            "Para cada producto genera una descripción vendedora (1-2 oraciones), "
            "una categoría corta y un título SEO. Agrupa categorías similares.\n\n"
            f"Productos: {json.dumps(lista, ensure_ascii=False)}\n\n"
            "Devuelve SOLO un array JSON, un objeto por producto EN EL MISMO ORDEN:\n"
            '[{"descripcion": "...", "categoria": "...", "seo_titulo": "..."}]'
        )
        try:
            data = _extraer_json(_generar_texto(prompt, json_mode=True))
            if isinstance(data, list) and len(data) == len(productos):
                for p, extra in zip(productos, data):
                    p.setdefault("descripcion", extra.get("descripcion", ""))
                    if not p.get("descripcion"):
                        p["descripcion"] = extra.get("descripcion", "")
                    p["categoria"] = p.get("categoria") or extra.get("categoria", "General")
                    p["seo_titulo"] = extra.get("seo_titulo", p.get("nombre", ""))
                return productos
        except Exception as e:  # noqa: BLE001
            print(f"⚠  Gemini (productos) falló, usando plantilla: {e}")

    # --- Fallback sin IA ---
    for p in productos:
        if not p.get("descripcion"):
            p["descripcion"] = f"{p.get('nombre', 'Producto')} de excelente calidad, disponible en {giro or 'nuestra tienda'}."
        p["categoria"] = p.get("categoria") or "General"
        p["seo_titulo"] = p.get("nombre", "Producto")
    return productos


def describir_servicio(nombre: str, giro: str = "") -> str:
    """Descripción breve y atractiva para un servicio. IA si hay; si no, plantilla."""
    nombre = (nombre or "").strip()
    if not nombre:
        return ""
    if disponible():
        prompt = (
            f"Escribe una descripción breve y atractiva (1 sola oración, máximo 18 palabras) "
            f"para el servicio '{nombre}' de un negocio de {giro or 'spa y bienestar'} en México. "
            "Sin precio, sin comillas, devuelve SOLO el texto."
        )
        try:
            txt = (_generar_texto(prompt) or "").strip().strip('"').strip()
            if txt:
                return txt[:180]
        except Exception as e:  # noqa: BLE001
            print(f"⚠  Gemini (servicio) falló: {e}")
    return f"{nombre}: atención profesional y personalizada para tu bienestar."


# ------------------- 3) Generar logo -------------------

ultimo_error_logo = ""   # diagnóstico del último intento de logo con IA


def generar_logo(nombre: str, giro: str, color: str, ruta_destino: str) -> str:
    """Genera un logo. Si hay IA, crea un PNG con Gemini y lo guarda en
    `ruta_destino` (debe terminar en .png). Si no, escribe un monograma SVG
    junto a la ruta y devuelve esa ruta .svg. Devuelve la ruta del archivo
    creado, o '' si todo falló."""
    global ultimo_error_logo
    ultimo_error_logo = ""
    if disponible():
        prompt = (
            f"Diseña un logo profesional, minimalista y moderno para un negocio "
            f"llamado '{nombre}' del giro '{giro}'. Estilo plano vectorial, fondo "
            f"blanco, usando el color {color} como protagonista. Incluye un ícono "
            f"simple representativo y, si cabe, el nombre. Cuando el giro sea de "
            f"belleza, bienestar, repostería o hecho a mano, usa una estética cálida "
            f"y acogedora, sin clichés. Sin texto extra ni marca de agua."
        )
        try:
            # El modelo de imagen requiere pedir salida IMAGE (algunos modelos
            # exigen también TEXT en response_modalities).
            resp = _client().models.generate_content(
                model=MODELO_IMAGEN, contents=prompt,
                config=genai_types.GenerateContentConfig(response_modalities=["TEXT", "IMAGE"]),
            )
            for part in resp.candidates[0].content.parts:
                if getattr(part, "inline_data", None) and part.inline_data.data:
                    with open(ruta_destino, "wb") as f:
                        f.write(part.inline_data.data)
                    return ruta_destino
            ultimo_error_logo = f"respuesta sin imagen (modelo {MODELO_IMAGEN})"
            print("⚠  Gemini (logo): " + ultimo_error_logo)
        except Exception as e:  # noqa: BLE001
            ultimo_error_logo = f"{type(e).__name__}: {e}"[:400]
            print(f"⚠  Gemini (logo) falló: {ultimo_error_logo}")

    # --- Fallback sin IA: monograma SVG con las iniciales ---
    ruta_svg = re.sub(r"\.png$", ".svg", ruta_destino)
    with open(ruta_svg, "w", encoding="utf-8") as f:
        f.write(monograma_svg(nombre, color))
    return ruta_svg


def monograma_svg(nombre: str, color: str) -> str:
    """Logo de respaldo: círculo de color con las iniciales del negocio."""
    palabras = [w for w in re.split(r"\s+", nombre.strip()) if w]
    iniciales = "".join(w[0] for w in palabras[:2]).upper() or "MT"
    color = _color_valido(color, "#fe4e02")
    return (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 200 200" width="200" height="200">'
        f'<circle cx="100" cy="100" r="96" fill="{color}"/>'
        f'<text x="100" y="100" dy="0.35em" text-anchor="middle" '
        f'font-family="Segoe UI, Arial, sans-serif" font-size="86" font-weight="700" '
        f'fill="#ffffff">{iniciales}</text></svg>'
    )


# ------------------- 4) Chatbot de ventas -------------------

def chatbot_responder(tienda: dict, mensaje: str, historial: list = None) -> str:
    """Responde como asistente de ventas de la tienda. Conoce su catálogo."""
    moneda = tienda.get("moneda", "MXN")
    productos = tienda.get("productos", [])
    servicios = tienda.get("servicios", [])
    lineas = [
        f"- {p.get('nombre')}: ${p.get('precio')} {moneda} — {p.get('descripcion', '')}"
        for p in productos
    ]
    lineas += [
        f"- (servicio con cita) {s.get('nombre')}: ${s.get('precio')} {moneda}, "
        f"dura {s.get('duracion')} min — {s.get('descripcion', '')}"
        for s in servicios
    ]
    catalogo_txt = "\n".join(lineas) or "(sin catálogo aún)"

    if disponible():
        sistema = (
            f"Eres el asistente de ventas de '{tienda.get('nombre')}'. "
            f"Tono: {tienda.get('tono', 'cercano y profesional')}. "
            f"Sobre el negocio: {tienda.get('sobre_nosotros', '')}\n"
            f"Catálogo:\n{catalogo_txt}\n\n"
            "Responde breve y útil. Si preguntan por algo fuera del catálogo, "
            "sugiere lo más cercano o invita a contactar por WhatsApp "
            f"({tienda.get('whatsapp') or 'el número de la tienda'}). "
            "No inventes precios que no estén en el catálogo."
        )
        conv = sistema + "\n\n"
        for turno in (historial or [])[-6:]:
            rol = "Cliente" if turno.get("rol") == "user" else "Asistente"
            conv += f"{rol}: {turno.get('texto', '')}\n"
        conv += f"Cliente: {mensaje}\nAsistente:"
        try:
            return _generar_texto(conv) or _chat_fallback(tienda)
        except Exception as e:  # noqa: BLE001
            print(f"⚠  Gemini (chat) falló: {e}")
            return _chat_fallback(tienda)

    return _chat_fallback(tienda)


def _chat_fallback(tienda: dict) -> str:
    wa = tienda.get("whatsapp")
    extra = f" También puedes escribirnos por WhatsApp al {wa}." if wa else ""
    return (
        f"¡Gracias por escribir a {tienda.get('nombre', 'nuestra tienda')}! "
        "Puedo ayudarte a encontrar un producto del catálogo." + extra
    )


# ------------------- 5) Clasificar gasto (reporteo automático) -------------------

# Cuentas válidas del estado de resultados.
_CUENTAS = ["COSTO_VENTAS", "NOMINA", "GASTOS_OP", "MARKETING", "GASTOS_FIN"]

# Reglas de respaldo por palabra clave (cuando no hay IA).
_REGLAS_GASTO = [
    ("COSTO_VENTAS", ["insumo", "material", "producto", "mercancia", "mercancía", "inventario", "aceite", "crema", "tinte", "esmalte"]),
    ("NOMINA",       ["sueldo", "nomina", "nómina", "comision", "comisión", "salario", "pago emplead", "aguinaldo"]),
    ("MARKETING",    ["facebook", "meta", "instagram", "google", "ads", "publicidad", "anuncio", "volante", "influencer", "marketing"]),
    ("GASTOS_FIN",   ["comision banc", "comisión banc", "interes", "interés", "banco", "terminal", "tpv", "stripe", "paypal", "financ"]),
    ("GASTOS_OP",    ["renta", "luz", "agua", "internet", "telefono", "teléfono", "limpieza", "papeleria", "papelería", "mantenimiento", "servicio"]),
]


def clasificar_gasto(concepto: str, monto=None) -> dict:
    """Clasifica un gasto en una de las 5 cuentas contables.
    Devuelve {cuenta, confianza, por} (por='llm' o 'regla')."""
    concepto = (concepto or "").strip()
    if disponible() and concepto:
        prompt = (
            "Clasifica este gasto de un negocio de servicios en EXACTAMENTE una de estas cuentas:\n"
            "COSTO_VENTAS (insumos/material para el servicio), NOMINA (sueldos/comisiones), "
            "GASTOS_OP (renta, luz, agua, internet, limpieza, papelería), "
            "MARKETING (publicidad, anuncios), GASTOS_FIN (comisiones bancarias, intereses).\n\n"
            f'Gasto: "{concepto}"' + (f" — monto ${monto}" if monto else "") + "\n\n"
            'Devuelve SOLO un JSON: {"cuenta": "CODIGO", "confianza": 0.0-1.0}'
        )
        try:
            data = _extraer_json(_generar_texto(prompt, json_mode=True))
            if data and data.get("cuenta") in _CUENTAS:
                conf = data.get("confianza")
                try:
                    conf = round(float(conf), 3)
                except (TypeError, ValueError):
                    conf = 0.8
                return {"cuenta": data["cuenta"], "confianza": conf, "por": "llm"}
        except Exception as e:  # noqa: BLE001
            print(f"⚠  Gemini (gasto) falló, usando reglas: {e}")

    # --- Fallback por palabras clave ---
    c = concepto.lower()
    for cuenta, claves in _REGLAS_GASTO:
        if any(k in c for k in claves):
            return {"cuenta": cuenta, "confianza": 0.5, "por": "regla"}
    return {"cuenta": "GASTOS_OP", "confianza": 0.3, "por": "regla"}


# ------------------- 6) Asesor de precios (gancho de retención) -------------------

def asesor_precios(nombre: str, giro: str = "", costo=None, moneda: str = "MXN",
                   margen_deseado=None, contexto: str = "") -> dict:
    """Sugiere precio de venta para un producto o servicio.
    Devuelve { precio_sugerido, precio_min, precio_max, margen_pct, costo,
               justificacion, tips:[], por }.
    Si hay IA usa el contexto de mercado; si no, calcula por markup sobre costo."""
    nombre = (nombre or "").strip()
    costo_n = None
    try:
        if costo is not None and costo != "":
            costo_n = max(0.0, float(costo))
    except (TypeError, ValueError):
        costo_n = None
    margen_n = None
    try:
        if margen_deseado is not None and margen_deseado != "":
            margen_n = min(95.0, max(0.0, float(margen_deseado)))
    except (TypeError, ValueError):
        margen_n = None

    if disponible() and nombre:
        partes = [
            "Eres un asesor de precios para PyMEs en LATAM, experto en negocios "
            "personales y de servicios (belleza, bienestar, repostería, hecho a mano). "
            "Sugiere un precio de venta realista y rentable, considerando el mercado "
            "local típico, sin sobrevaluar.\n",
            f"Producto/servicio: {nombre}\n",
            f"Giro del negocio: {giro}\n" if giro else "",
            f"Moneda: {moneda}\n",
            f"Costo unitario (insumos/material): {costo_n}\n" if costo_n is not None else "Costo: no proporcionado (estímalo razonablemente)\n",
            f"Margen deseado por el dueño: {margen_n}%\n" if margen_n is not None else "",
            f"Contexto del dueño: {contexto}\n" if contexto else "",
            "\nDevuelve SOLO un JSON con esta forma exacta (números sin símbolo de moneda):\n"
            '{\n'
            '  "precio_sugerido": número (precio recomendado de venta),\n'
            '  "precio_min": número (opción económica),\n'
            '  "precio_max": número (opción premium),\n'
            '  "margen_pct": número (margen bruto % al precio sugerido),\n'
            '  "justificacion": "1-2 oraciones claras, en español, tono cálido y cercano",\n'
            '  "tips": ["2 a 3 consejos breves y accionables para vender o subir el precio"]\n'
            "}"
        ]
        try:
            data = _extraer_json(_generar_texto("".join(partes), json_mode=True))
            if data and data.get("precio_sugerido") is not None:
                ps = _num_pos(data.get("precio_sugerido"))
                if ps is not None:
                    pmin = _num_pos(data.get("precio_min")) or round(ps * 0.85, 2)
                    pmax = _num_pos(data.get("precio_max")) or round(ps * 1.3, 2)
                    mg = data.get("margen_pct")
                    try:
                        mg = round(float(mg), 1)
                    except (TypeError, ValueError):
                        mg = (round((1 - costo_n / ps) * 100, 1) if costo_n and ps else None)
                    tips = data.get("tips") or []
                    if isinstance(tips, str):
                        tips = [tips]
                    return {
                        "precio_sugerido": round(ps, 2), "precio_min": round(pmin, 2),
                        "precio_max": round(pmax, 2), "margen_pct": mg, "costo": costo_n,
                        "justificacion": (data.get("justificacion") or "").strip()[:300],
                        "tips": [str(t).strip()[:160] for t in tips][:3], "por": "ia",
                    }
        except Exception as e:  # noqa: BLE001
            print(f"⚠  Gemini (precios) falló, usando cálculo: {e}")

    # --- Fallback determinista: markup sobre costo ---
    margen = (margen_n if margen_n is not None else 55.0) / 100.0
    if costo_n and costo_n > 0:
        precio = costo_n / max(0.05, (1 - margen))
        just = (f"Con un costo de {costo_n:g} y un margen de {round(margen*100)}%, "
                f"este precio cubre tus insumos y deja ganancia sana.")
    else:
        precio = 0.0
        just = ("Agrega tu costo (insumos o material) para calcular un precio que "
                "cubra tus gastos y deje ganancia.")
    mg_real = round((1 - costo_n / precio) * 100, 1) if (costo_n and precio) else None
    return {
        "precio_sugerido": round(precio, 2), "precio_min": round(precio * 0.85, 2),
        "precio_max": round(precio * 1.3, 2), "margen_pct": mg_real, "costo": costo_n,
        "justificacion": just,
        "tips": [
            "Ofrece 3 opciones (económica, recomendada y premium): la mayoría elige la de en medio.",
            "Redondea a una cifra atractiva (p. ej. 199 en vez de 205).",
            "Suma tu tiempo y tu experiencia, no solo el material.",
        ],
        "por": "calculo",
    }


def _num_pos(v):
    try:
        n = float(v)
        return n if n > 0 else None
    except (TypeError, ValueError):
        return None

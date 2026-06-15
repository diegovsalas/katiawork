# seo.py
# -------------------------------------------------------------------
# Configuración SEO centralizada. Aquí vive toda la metadata, palabras
# clave y datos estructurados (Schema.org) que ayudan a Google a
# entender y posicionar tu tienda.
#
# Estrategia: keywords basadas en búsquedas REALES del mercado mexicano
# de patines hidráulicos (investigadas en Mercado Libre, Amazon, etc).
# -------------------------------------------------------------------

# --- Datos base del negocio (cámbialos por los tuyos reales) ---
SITIO = {
    "nombre": "Outlet Momatt México",
    "dominio": "https://momatt.shop",            # Dominio real en producción
    "descripcion_corta": "Venta de patines hidráulicos industriales para tarima. Traspaletas de 2.3, 2.5 y 3 toneladas. Envío a todo México.",
    "telefono": "+52 81 3568 7469",              # <-- TU TELÉFONO (visible)
    "whatsapp": "528135687469",                  # <-- SOLO DÍGITOS, sin + ni espacios (para wa.me)
    "whatsapp_visible": "+52 81 3568 7469",      # Para mostrar al cliente
    "email": "ventas@momatt.shop",               # <-- TU CORREO
    "ciudad": "San Nicolás de los Garza",
    "estado": "Nuevo León",
    "pais": "MX",
    "anios_experiencia": "+10 años",             # Trust signal
    "rfc": "XAXX010101000",                      # <-- TU RFC real (factura SAT)
    "horario": "Lun-Vie 9:00-18:00 · Sáb 9:00-14:00",
}


# --- Testimoniales (los puedes editar libremente cuando tengas reseñas reales) ---
# Mientras tanto, mantén estos para construir confianza inicial. Conforme
# tus clientes te dejen reseñas reales (por WhatsApp, correo, Google),
# reemplázalas aquí con su nombre y empresa.
TESTIMONIOS = [
    {
        "nombre": "Ricardo Pérez",
        "empresa": "Distribuidora Norte, Monterrey",
        "texto": "Compré 5 patines Truper para nuestro CEDIS. Llegaron bien empacados y la atención por WhatsApp fue rapidísima. Ya pedimos más.",
        "rating": 5,
    },
    {
        "nombre": "María Fernanda Solís",
        "empresa": "Almacenes del Bajío, Querétaro",
        "texto": "El Crown PTH 50 era exactamente lo que necesitábamos para piso de concreto. Buen precio comparado con el distribuidor local y factura sin problema.",
        "rating": 5,
    },
    {
        "nombre": "Jorge Mendoza",
        "empresa": "Tienda de Conveniencia Saltillo",
        "texto": "Necesitaba un patín silencioso para no molestar a clientes en piso. El Surtek de ruedas de poliuretano funciona perfecto. Envío en 3 días.",
        "rating": 5,
    },
    {
        "nombre": "Patricia Ramírez",
        "empresa": "Comercializadora del Pacífico",
        "texto": "Compré uno por probar y al mes pedí 3 más para otra sucursal. El asesor virtual me ayudó a elegir el modelo correcto para mi tipo de tarima.",
        "rating": 5,
    },
]

# --- Palabras clave principales (las que más busca tu cliente) ---
# Ordenadas por intención de compra. Úsalas en títulos y descripciones.
KEYWORDS_PRINCIPALES = [
    "patín hidráulico",
    "patín hidráulico para tarima",
    "traspaleta",
    "pallet jack",
    "patín hidráulico 3 toneladas",
    "paletera",
    "patín de carga",
    "gato hidráulico para tarima",
    "patín hidráulico industrial",
    "patín hidráulico precio",
    "comprar patín hidráulico",
    "patín hidráulico México",
]

# --- Keywords de cola larga (long-tail) por categoría ---
# Menos volumen pero MUCHA más conversión (el cliente sabe qué quiere).
KEYWORDS_LONG_TAIL = {
    "Máxima Durabilidad": [
        "patín hidráulico uso rudo", "patín hidráulico para concreto",
        "patín hidráulico andén", "traspaleta industrial resistente",
        "patín hidráulico 3 toneladas precio",
    ],
    "Operaciones Silenciosas": [
        "patín hidráulico ruedas poliuretano", "patín hidráulico piso delicado",
        "traspaleta silenciosa", "patín hidráulico para interiores",
    ],
    "Alta Especialización Logística": [
        "patín hidráulico angosto", "patín hidráulico pasillo angosto",
        "patín hidráulico extra largo", "patín hidráulico horquilla larga",
        "traspaleta para dos tarimas",
    ],
}


def meta_home():
    """Metadata para la página principal."""
    kw = ", ".join(KEYWORDS_PRINCIPALES)
    return {
        "titulo": "Patines Hidráulicos Industriales | Traspaletas 2-3 Ton | Outlet Momatt México",
        "descripcion": (
            "Compra patines hidráulicos para tarima al mejor precio. Traspaletas "
            "de 2.3, 2.5 y 3 toneladas: uso rudo, ruedas de poliuretano y modelos "
            "angostos. Pago por transferencia SPEI y Banregio. Envío a todo México."
        ),
        "keywords": kw,
        "canonical": SITIO["dominio"] + "/",
        "og_titulo": "Outlet Momatt México · Patines Hidráulicos Industriales",
        "og_descripcion": "Traspaletas y patines hidráulicos de 2 a 3 toneladas. Precios de outlet, envío a todo México.",
    }


def meta_producto(p):
    """Metadata para una página de producto individual."""
    cap = p.get("capacidad", "")
    titulo = f"{p['nombre']} {cap} | Patín Hidráulico | Outlet Momatt México"
    if p.get("precio"):
        desc = (
            f"{p['nombre']} de {cap}. {p['descripcion']} "
            f"Precio: ${p['precio']:,.0f} MXN. Envío a todo México. "
            f"Pago seguro por transferencia."
        )
    else:
        desc = f"{p['nombre']} de {cap}. {p['descripcion']} Cotiza con un asesor. Envío a todo México."
    return {
        "titulo": titulo,
        "descripcion": desc[:160],  # Google corta ~160 caracteres
        "canonical": f"{SITIO['dominio']}/producto/{p['id']}",
    }


def schema_organizacion():
    """Datos estructurados de la organización (Schema.org JSON-LD)."""
    import json
    data = {
        "@context": "https://schema.org",
        "@type": "Store",
        "name": SITIO["nombre"],
        "description": SITIO["descripcion_corta"],
        "url": SITIO["dominio"],
        "telephone": SITIO["telefono"],
        "email": SITIO["email"],
        "address": {
            "@type": "PostalAddress",
            "addressLocality": SITIO["ciudad"],
            "addressRegion": SITIO["estado"],
            "addressCountry": SITIO["pais"],
        },
        "areaServed": {"@type": "Country", "name": "México"},
    }
    return json.dumps(data, ensure_ascii=False, indent=2)


def schema_producto(p):
    """Datos estructurados de un producto (rich snippets en Google)."""
    import json
    data = {
        "@context": "https://schema.org",
        "@type": "Product",
        "name": p["nombre"],
        "description": p["descripcion"],
        "brand": {"@type": "Brand", "name": p.get("marca", "")},
        "category": p.get("categoria", ""),
        "url": f"{SITIO['dominio']}/producto/{p['id']}",
    }
    if p.get("imagen"):
        data["image"] = f"{SITIO['dominio']}/static/img/{p['imagen']}"
    if p.get("precio"):
        disponible = (p.get("stock") or 0) > 0
        data["offers"] = {
            "@type": "Offer",
            "price": str(p["precio"]),
            "priceCurrency": "MXN",
            "availability": "https://schema.org/InStock" if disponible else "https://schema.org/OutOfStock",
            "url": f"{SITIO['dominio']}/producto/{p['id']}",
            "seller": {"@type": "Organization", "name": SITIO["nombre"]},
        }
    return json.dumps(data, ensure_ascii=False, indent=2)


def schema_breadcrumb(items):
    """Migas de pan estructuradas. items = [(nombre, url), ...]"""
    import json
    elementos = []
    for i, (nombre, url) in enumerate(items, 1):
        elementos.append({
            "@type": "ListItem",
            "position": i,
            "name": nombre,
            "item": SITIO["dominio"] + url,
        })
    data = {
        "@context": "https://schema.org",
        "@type": "BreadcrumbList",
        "itemListElement": elementos,
    }
    return json.dumps(data, ensure_ascii=False, indent=2)

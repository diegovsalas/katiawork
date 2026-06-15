# catalogo.py
# -------------------------------------------------------------------
# ESTE ES EL ÚNICO ARCHIVO QUE EDITAS para cambiar tus productos,
# precios y stock. No necesitas tocar nada más.
#
# Cada producto es un diccionario con estos campos:
#   id              -> texto corto y único, sin espacios (va en la URL).
#   nombre          -> nombre que ve el cliente.
#   marca           -> marca del equipo.
#   capacidad       -> capacidad de carga (ej. "3 ton").
#   descripcion     -> descripción corta para la tarjeta y el SEO.
#   precio          -> precio ACTUAL en pesos SIN comas. None = "cotizar".
#   precio_anterior -> (opcional) precio de lista original, para mostrar
#                      el descuento tachado. None u omitir = sin descuento.
#   stock           -> piezas disponibles (entero). Usa 0 si no hay.
#   categoria       -> DEBE ser una de las 3 categorías de abajo (ver seo.py).
#
# IMPORTANTE: todos los precios son ANTES DE IVA (+ IVA al checkout).
# Precios de referencia investigados en el mercado mexicano. Sujetos a cambio.
# -------------------------------------------------------------------

# Las 3 categorías oficiales (coinciden con las keywords de seo.py).
# Si agregas una categoría nueva aquí, agrégala también en seo.py.
MAXIMA_DURABILIDAD = "Máxima Durabilidad"
OPERACIONES_SILENCIOSAS = "Operaciones Silenciosas"
ESPECIALIZACION_LOGISTICA = "Alta Especialización Logística"


PRODUCTOS = [
    # --- Máxima Durabilidad (Andenes y Concreto) ---
    {
        "id": "crown-pth-50",
        "nombre": "Crown PTH 50",
        "marca": "Crown",
        "capacidad": "2.3 ton",
        "descripcion": "Patín hidráulico de marca líder mundial, diseñado para andenes, concreto y operación continua. Estructura reforzada y bomba de larga vida útil.",
        "precio": 11900,
        "precio_anterior": 21100,
        "stock": 4,
        "categoria": MAXIMA_DURABILIDAD,
        "imagen": "crown-pth-50.jpg",
        "ficha": "crown-pth-50.pdf",
    },
    {
        "id": "truper-pat-3ny",
        "nombre": "Truper PAT-3NY",
        "marca": "Truper",
        "capacidad": "3 ton",
        "descripcion": "Traspaleta industrial Truper con ruedas de nylon. La mejor relación precio-rendimiento para uso rudo continuo en almacén.",
        "precio": 7475,
        "precio_anterior": 11500,
        "stock": 8,
        "categoria": MAXIMA_DURABILIDAD,
        "imagen": "truper-pat-3ny.jpg",
        "ficha": "truper-pat-3ny.pdf",
    },
    {
        "id": "noble-mac-nbq30",
        "nombre": "Noble Mac NBQ30",
        "marca": "Noble Mac",
        "capacidad": "3 ton",
        "descripcion": "Patín hidráulico de grado institucional para uso rudo extremo. Segmento premium para operaciones de alto volumen y andenes intensivos.",
        "precio": None,   # Cotización (segmento premium)
        "stock": 2,
        "categoria": MAXIMA_DURABILIDAD,
        "imagen": "noble-mac-nbq30.jpg",
    },

    # --- Operaciones Silenciosas (Pisos delicados — Poliuretano) ---
    {
        "id": "surtek-trhp25",
        "nombre": "Surtek TRHP25",
        "marca": "Surtek",
        "capacidad": "2.5 ton",
        "descripcion": "Ruedas de poliuretano que no marcan ni rayan el piso. Ideal para tiendas, supermercados y centros de distribución con piso pulido.",
        "precio": 6760,
        "precio_anterior": 10400,
        "stock": 6,
        "categoria": OPERACIONES_SILENCIOSAS,
        "imagen": "surtek-trhp25.jpg",
        "ficha": "surtek-trhp25.pdf",
    },
    {
        "id": "zait-traspaleta-3ton",
        "nombre": "ZAIT Traspaleta",
        "marca": "ZAIT",
        "capacidad": "3 ton",
        "descripcion": "Traspaleta con ruedas de poliuretano. La opción más competitiva del mercado para pisos interiores y operación silenciosa.",
        "precio": 3574,
        "precio_anterior": 5499,
        "stock": 12,
        "categoria": OPERACIONES_SILENCIOSAS,
        "imagen": "zait-traspaleta-3ton.webp",
    },

    # --- Alta Especialización Logística ---
    {
        "id": "patin-mini-pasillo-angosto",
        "nombre": "Patín Mini para Pasillo Angosto",
        "marca": "Especial Logístico",
        "capacidad": "3 ton",
        "descripcion": "Horquillas reducidas para pasillos estrechos y tarimas especiales. Maniobra en espacios reducidos sin sacrificar capacidad.",
        "precio": 4225,
        "precio_anterior": 6500,
        "stock": 5,
        "categoria": ESPECIALIZACION_LOGISTICA,
        "imagen": "patin-mini-pasillo-angosto.jpg",
        "ficha": "patin-mini-pasillo-angosto.pdf",
    },
    {
        "id": "patin-extra-largo-doble-tarima",
        "nombre": "Patín Extra Largo (Doble Tarima)",
        "marca": "Especial Logístico",
        "capacidad": "3 ton",
        "descripcion": "Horquillas extra largas para mover dos tarimas a la vez o cargas de gran longitud. Fabricación por especificación de pulgadas.",
        "precio": None,   # Precio bajo cotización
        "stock": 0,
        "categoria": ESPECIALIZACION_LOGISTICA,
        "imagen": "patin-extra-largo-doble-tarima.png",
    },
]


# --- Funciones que usa app.py (no necesitas editarlas) ---

def listar_productos():
    """Devuelve la lista completa de productos."""
    return PRODUCTOS


def buscar_producto(producto_id):
    """Busca un producto por su id. Devuelve None si no existe."""
    for p in PRODUCTOS:
        if p["id"] == producto_id:
            return p
    return None


def categorias():
    """Devuelve las categorías en orden, sin repetir."""
    vistas = []
    for p in PRODUCTOS:
        if p["categoria"] not in vistas:
            vistas.append(p["categoria"])
    return vistas

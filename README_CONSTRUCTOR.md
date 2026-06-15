# katia — Constructor de tiendas con IA

Herramienta web para que **cualquier persona, sin saber programar**, arme su
sitio de ventas en minutos: cuenta de qué trata su negocio, crea su logo,
sube sus productos con precios y publica. La IA de **Gemini** hace el trabajo
pesado (marca, descripciones, logo y chatbot).

Vive **junto** a la tienda Momatt original (`app.py`) sin modificarla. Es un
app aparte: `constructor.py`.

## Correr en local

```bash
pip install -r requirements.txt
uvicorn constructor:app --reload
```

Abre <http://localhost:8000>:

- `/` → landing del producto.
- `/crear` → el **asistente** paso a paso.
- `/t/<slug>` → la tienda publicada (en local se prueba por ruta; en
  producción vive en `<slug>.TU_DOMINIO`).

**No necesitas base de datos ni API key para probar.** Sin `GEMINI_API_KEY`
el asistente corre en *modo plantilla* (textos y logo generados localmente).

## Activar la IA (Gemini)

1. Consigue una llave gratis en <https://aistudio.google.com/apikey>.
2. Ponla como variable de entorno:

```bash
GEMINI_API_KEY=tu_llave uvicorn constructor:app --reload
```

Con la llave activa: redacta marca, describe productos, **genera logos** con
imagen IA y el chatbot responde de verdad.

## Cómo funciona (arquitectura)

| Archivo | Rol |
|---|---|
| `constructor.py` | App FastAPI: landing, wizard, endpoints de IA, storefront por subdominio y chatbot. |
| `tiendas.py` | Capa de datos **multi-tenant**. Cada tienda es un JSON en `data/tiendas/<slug>.json`. Resuelve la tienda por subdominio o dominio propio. |
| `gemini_ia.py` | Toda la IA, con **degradación elegante**: si no hay llave, usa plantillas. |
| `templates/constructor/` | `landing.html`, `wizard.html` (el asistente), `tienda.html` (storefront genérico). |

**Multi-tenant por subdominio:** una sola app sirve todas las tiendas. La
tienda se resuelve del `Host` de la petición:
`cafe-sur.katia.work` → tienda `cafe-sur`.

## Pasar a producción

1. **Datos:** hoy las tiendas se guardan como JSON (cero configuración). Para
   escalar, migrar `tiendas.py` a Postgres (`db.py` ya tiene el pool listo);
   el resto de la app no cambia porque todo pasa por `tiendas.py`.
2. **Subdominios:** apunta un DNS *wildcard* `*.tudominio.com` a tu servidor
   y pon `DOMINIO_BASE=tudominio.com`.
3. **Dominios propios de clientes:** el cliente apunta su dominio (CNAME) a tu
   servidor; en el wizard lo captura en "dominio propio" y `tiendas.resolver_por_host`
   ya lo enruta. Falta emitir certificados TLS por dominio (ej. Caddy on-demand TLS).
4. **Logos/uploads:** hoy en disco (`static/tiendas/`). En producción usa un
   bucket (S3/R2) si tienes varias instancias.

## Pendiente / siguientes pasos (roadmap)

- [ ] Cuentas de usuario para que cada dueño edite su tienda después (reusar `auth.py`).
- [ ] Carrito + checkout por tienda (reusar los gateways de `pagos_*.py`).
- [ ] Páginas individuales de producto + sitemap por tienda (reusar `seo.py`).
- [ ] Subir foto por producto desde el wizard.
- [ ] Migrar persistencia a Postgres.

# Tienda de Patines Hidráulicos Industriales

E-commerce con FastAPI. Dos métodos de pago pensados para México:
- **Transferencia SPEI vía Openpay** — automático, funciona con cualquier banco.
- **Transferencia directa a Banregio** — sin comisión, confirmación manual.

## Estructura

- `catalogo.py` — Tus productos. **Único archivo que editas** para precios/stock.
- `config_pagos.py` — **Tus datos de Banregio y llaves de Openpay.** Edítalo.
- `app.py` — Backend FastAPI: catálogo, carrito, checkout y procesamiento de pago.
- `templates/` — Páginas HTML (catálogo, carrito, checkout, pago SPEI, pago Banregio).
- `static/estilos.css` — Diseño (tema industrial).

## Instalar y correr

```bash
pip install -r requirements.txt
uvicorn app:app --reload
```

Abre http://localhost:8000

## Configurar pagos (config_pagos.py)

### Banregio (transferencia directa)
Edita el diccionario `BANREGIO` con tu titular, CLABE real y datos de contacto.
No requiere llaves ni API: solo son los datos que ve el cliente para pagarte.

### Openpay (SPEI automático)
1. En tu dashboard de Openpay copia: Merchant ID y Llave privada (sk_...).
2. Córrelo pasando las llaves como variables de entorno (recomendado):

```bash
OPENPAY_MERCHANT_ID=tu_merchant_id \
OPENPAY_PRIVATE_KEY=sk_tu_llave \
uvicorn app:app --reload
```

Por defecto usa el ambiente SANDBOX (pruebas). Para cobrar de verdad:

```bash
OPENPAY_PRODUCCION=True OPENPAY_MERCHANT_ID=... OPENPAY_PRIVATE_KEY=... uvicorn app:app --reload
```

## Nota técnica
El SDK oficial `openpay` de Python está abandonado (no instala en Python 3.12
por usar `use_2to3`). Por eso este proyecto llama la API REST de Openpay
directamente con `requests`, que es más estable y sin dependencias muertas.

## Pendiente para producción
- Webhook de Openpay (`/webhook`) para confirmar automáticamente cuando el
  cliente paga el SPEI. Sin esto, revisas los pagos en el dashboard de Openpay.
- Guardar pedidos en base de datos (ahora el número de pedido es aleatorio).
- Cambiar `secret_key` en app.py por un valor secreto real.

---

## SEO (optimización para Google)

La tienda incluye SEO técnico enfocado en ventas:

- **Páginas individuales por producto** (`/producto/{id}`) con título y descripción
  optimizados según búsquedas reales del mercado mexicano (patín hidráulico,
  traspaleta, pallet jack, paletera, etc).
- **Datos estructurados Schema.org** (JSON-LD) de tienda y producto: hacen que
  Google muestre tu precio y disponibilidad directo en los resultados.
- **sitemap.xml** y **robots.txt** automáticos para que Google indexe todo.
- **Open Graph**: cómo se ve tu tienda al compartirla por WhatsApp/Facebook.
- Migas de pan, H1 con keywords, productos relacionados (enlaces internos),
  y señales de confianza (envío, pago seguro) que suben la conversión.

### Para activar el SEO en producción
1. Edita `seo.py` -> `SITIO["dominio"]` con tu dominio real (ej. https://momatt.shop).
2. Edita teléfono, correo, ciudad en el mismo diccionario `SITIO`.
3. Cuando publiques, registra tu sitio en Google Search Console y sube el sitemap:
   https://momatt.shop/sitemap.xml

## Gateways de pago (scaffolded)

Tres integraciones en módulos separados; cada una tiene una bandera
`IMPLEMENTACION_TERMINADA` arriba del archivo. Hasta que esa bandera
sea `True` Y las API keys correspondientes estén configuradas en
Render, la opción NO se muestra al cliente en el checkout.

| Módulo | Estado | Cómo activar |
|---|---|---|
| `pagos_openpay.py` | Implementado, esperando aprobación SPEI de Openpay | Pon `OPENPAY_MERCHANT_ID` y `OPENPAY_PRIVATE_KEY` en Render. Endpoint webhook: `/webhook/openpay`. |
| `pagos_stripe.py` | Scaffold — falta terminar 3 funciones | 1) Termina los TODO en el módulo. 2) Cambia `IMPLEMENTACION_TERMINADA=True`. 3) Pon `STRIPE_SECRET_KEY`, `STRIPE_PUBLISHABLE_KEY`, `STRIPE_WEBHOOK_SECRET`. 4) Webhook: `/webhook/stripe`. |
| `pagos_mercadopago.py` | Scaffold — falta terminar 3 funciones | 1) Termina los TODO. 2) `IMPLEMENTACION_TERMINADA=True`. 3) Pon `MP_ACCESS_TOKEN`, `MP_WEBHOOK_SECRET`. 4) Webhook: `/webhook/mercadopago`. 5) Opcional: `MP_MSI_HABILITADO=True` para meses sin intereses. |

Banregio (transferencia manual) no usa gateway y siempre está
disponible. El cliente puede elegir su método de pago en el
checkout entre los que estén activos.

Cuando un cliente paga vía gateway: la app crea el pedido en
estado `pendiente_pago`, redirige al cliente al checkout
hospedado del gateway, el gateway llama al webhook
correspondiente, y el handler pone el pedido en `pagado`. Hasta
que llegue el webhook el pedido queda en `pendiente_pago`, así
que **es crítico configurar bien los webhooks** en los dashboards
de Stripe y MP cuando los actives.

## Recordatorios de pago (cron externo)

El endpoint `/cron/recordatorios?token=CRON_TOKEN` busca pedidos
`pendiente_pago` de más de 24 horas y manda un recordatorio por
correo (Resend). Máximo 2 recordatorios por pedido, separados por 48
horas. El cliente detiene los recordatorios marcando su pedido como
pagado desde `/pedido/{id}`.

**Setup** (una vez, gratis):

1. En Render → tu servicio → Environment, copia el valor de `CRON_TOKEN`
   (Render lo generó automático al primer deploy).
2. Crea cuenta en https://cron-job.org (gratis, sin tarjeta).
3. **Create cronjob** con estos valores:
   - **Title:** Recordatorios pago Momatt
   - **URL:** `https://momatt.shop/cron/recordatorios?token=PEGA_EL_TOKEN_AQUI`
   - **Schedule:** `Every 6 hours` (o cuando prefieras)
   - **Request method:** `POST` (también acepta GET)
4. Guarda. cron-job.org te muestra logs de cada llamada.

El endpoint responde JSON con conteo de enviados/fallidos para que
veas los resultados en cron-job.org.

## Logo
Tu logo está en `static/img/`:
- `logo-momatt.png` — original completo (para compartir / Open Graph).
- `logo-texto.png` — versión horizontal para el header.
- `favicon.png` — ícono de la pestaña del navegador.

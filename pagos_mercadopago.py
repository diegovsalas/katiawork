# pagos_mercadopago.py — Integración con Mercado Pago (Checkout Pro)
# -------------------------------------------------------------------
# Scaffold. NO está terminado. Para activarlo:
#
#   1. Crea cuenta en https://www.mercadopago.com.mx (negocio).
#   2. Ve a https://www.mercadopago.com.mx/developers/panel/credentials
#      - Access Token (TEST-... / APP_USR-...) → MP_ACCESS_TOKEN
#      - Public Key → MP_PUBLIC_KEY (opcional, solo si usas SDK frontend)
#   3. Configura el webhook (IPN/Webhooks) en el panel:
#      URL: https://momatt.shop/webhook/mercadopago
#      Eventos: payment, merchant_order
#      Copia el "Secret signature" → MP_WEBHOOK_SECRET
#   4. Pon las env vars en Render.
#   5. Termina las funciones marcadas con TODO abajo.
#   6. Cambia IMPLEMENTACION_TERMINADA = True.
#
# Particular de MP: soporta MSI (meses sin intereses) configurando
# `installments` y `default_installments` en payment_methods. Esto
# es decisión de negocio — sube comisión pero también el ticket promedio.
# -------------------------------------------------------------------
import os

try:
    import mercadopago
    _SDK_OK = True
except ImportError:
    _SDK_OK = False

IMPLEMENTACION_TERMINADA = False

MP_ACCESS_TOKEN    = os.getenv("MP_ACCESS_TOKEN", "")
MP_PUBLIC_KEY      = os.getenv("MP_PUBLIC_KEY", "")
MP_WEBHOOK_SECRET  = os.getenv("MP_WEBHOOK_SECRET", "")
MP_MSI_HABILITADO  = os.getenv("MP_MSI_HABILITADO", "False").lower() == "true"

_sdk = None
if _SDK_OK and MP_ACCESS_TOKEN:
    _sdk = mercadopago.SDK(MP_ACCESS_TOKEN)


def disponible() -> bool:
    return bool(IMPLEMENTACION_TERMINADA and _SDK_OK and MP_ACCESS_TOKEN)


def crear_pago(pedido_id: str, total_centavos: int, descripcion: str,
               email_cliente: str, items: list,
               success_url: str, cancel_url: str) -> str:
    """Crea una Preference de Checkout Pro y devuelve la URL init_point
    a donde redirigimos al cliente para pagar en el sitio de MP."""
    if not disponible():
        raise RuntimeError("Mercado Pago no está habilitado todavía.")

    # TODO: implementar:
    #
    # preference_data = {
    #     "items": [
    #         {
    #             "id": it["id"],
    #             "title": it["nombre"],
    #             "quantity": it["cantidad"],
    #             "unit_price": float(it["precio"]),  # MP usa unidades, no centavos
    #             "currency_id": "MXN",
    #         }
    #         for it in items
    #     ],
    #     "payer": {"email": email_cliente},
    #     "external_reference": pedido_id,
    #     "back_urls": {
    #         "success": success_url,
    #         "failure": cancel_url,
    #         "pending": success_url,
    #     },
    #     "auto_return": "approved",
    #     "notification_url": "https://momatt.shop/webhook/mercadopago",
    # }
    # if MP_MSI_HABILITADO:
    #     preference_data["payment_methods"] = {
    #         "installments": 12,  # hasta 12 MSI
    #     }
    # resp = _sdk.preference().create(preference_data)
    # return resp["response"]["init_point"]
    raise NotImplementedError("Falta implementar la creación de Preference.")


def verificar_webhook(signature_header: str, body: bytes,
                      request_id: str = "", data_id: str = "") -> dict:
    """Verifica la firma del webhook con MP_WEBHOOK_SECRET.

    MP usa un esquema HMAC SHA256 sobre un string canónico que incluye
    el id del recurso, el request-id y el timestamp. La cabecera viene
    en `x-signature: ts=...,v1=...`.
    """
    if not MP_WEBHOOK_SECRET:
        raise RuntimeError("MP_WEBHOOK_SECRET no configurada.")

    # TODO: implementar:
    #
    # import hashlib, hmac, json
    # # Parsear ts y v1 del header "ts=NNN,v1=HEX"
    # parts = dict(p.split("=") for p in signature_header.split(","))
    # ts = parts["ts"]; v1 = parts["v1"]
    # mensaje = f"id:{data_id};request-id:{request_id};ts:{ts};"
    # firma_esperada = hmac.new(
    #     MP_WEBHOOK_SECRET.encode(),
    #     mensaje.encode(),
    #     hashlib.sha256,
    # ).hexdigest()
    # if not hmac.compare_digest(firma_esperada, v1):
    #     raise ValueError("Firma inválida")
    # return json.loads(body)
    raise NotImplementedError("Falta verificar la firma del webhook.")


def procesar_evento(evento: dict) -> tuple:
    """MP manda un POST de notificación con `{type, data: {id}}`. Hay que
    consultar la API con ese id para obtener el detalle. Devuelve
    (pedido_id, nuevo_estado)."""
    # TODO: implementar:
    #
    # if evento.get("type") != "payment":
    #     return (None, None)
    # pago_id = evento["data"]["id"]
    # pago = _sdk.payment().get(pago_id)["response"]
    # pedido_id = pago.get("external_reference")
    # status = pago.get("status")  # 'approved', 'pending', 'rejected', etc.
    # mapeo = {
    #     "approved": "pagado",
    #     "pending":  "comprobante_enviado",
    #     "rejected": "cancelado",
    # }
    # return (pedido_id, mapeo.get(status))
    raise NotImplementedError("Falta procesar el evento de Mercado Pago.")

# pagos_stripe.py — Integración con Stripe (Checkout Sessions)
# -------------------------------------------------------------------
# Scaffold. NO está terminado. Para activarlo:
#
#   1. Crea cuenta en https://dashboard.stripe.com (modo Test primero).
#   2. Obtén las llaves: Settings → Developers → API Keys
#      - Secret key (sk_test_... / sk_live_...) → STRIPE_SECRET_KEY
#      - Publishable key (pk_test_... / pk_live_...) → STRIPE_PUBLISHABLE_KEY
#   3. Configura el webhook en Stripe Dashboard:
#      URL: https://momatt.shop/webhook/stripe
#      Eventos: checkout.session.completed, payment_intent.succeeded
#      Copia el "Signing secret" (whsec_...) → STRIPE_WEBHOOK_SECRET
#   4. Pon las 3 env vars en Render.
#   5. Termina las funciones marcadas con TODO abajo.
#   6. Cambia IMPLEMENTACION_TERMINADA = True.
# -------------------------------------------------------------------
import os

try:
    import stripe
    _SDK_OK = True
except ImportError:
    _SDK_OK = False

# Bandera maestra: hasta que esté en True el módulo NO se ofrece al cliente.
# Esto previene que un cliente pague en una integración que no terminamos.
IMPLEMENTACION_TERMINADA = False

STRIPE_SECRET_KEY      = os.getenv("STRIPE_SECRET_KEY", "")
STRIPE_PUBLISHABLE_KEY = os.getenv("STRIPE_PUBLISHABLE_KEY", "")
STRIPE_WEBHOOK_SECRET  = os.getenv("STRIPE_WEBHOOK_SECRET", "")

if _SDK_OK and STRIPE_SECRET_KEY:
    stripe.api_key = STRIPE_SECRET_KEY


def disponible() -> bool:
    """¿El módulo está terminado Y con keys configuradas?
    Solo cuando esto devuelve True se muestra al cliente en checkout."""
    return bool(IMPLEMENTACION_TERMINADA and _SDK_OK and STRIPE_SECRET_KEY)


def crear_pago(pedido_id: str, total_centavos: int, descripcion: str,
               email_cliente: str, items: list,
               success_url: str, cancel_url: str) -> str:
    """Crea una Checkout Session de Stripe y devuelve la URL para redirigir
    al cliente. Stripe maneja el formulario seguro de pago."""
    if not disponible():
        raise RuntimeError("Stripe no está habilitado todavía.")

    # TODO: implementar la llamada real:
    #
    # session = stripe.checkout.Session.create(
    #     mode="payment",
    #     payment_method_types=["card", "oxxo"],
    #     line_items=[
    #         {
    #             "price_data": {
    #                 "currency": "mxn",
    #                 "product_data": {"name": it["nombre"]},
    #                 "unit_amount": int(it["precio"] * 100),  # Stripe usa centavos
    #             },
    #             "quantity": it["cantidad"],
    #         }
    #         for it in items
    #     ],
    #     customer_email=email_cliente,
    #     client_reference_id=pedido_id,
    #     metadata={"pedido_id": pedido_id},
    #     success_url=success_url,
    #     cancel_url=cancel_url,
    # )
    # return session.url
    raise NotImplementedError("Falta implementar la creación de Checkout Session.")


def verificar_webhook(signature_header: str, body: bytes) -> dict:
    """Verifica la firma del webhook con STRIPE_WEBHOOK_SECRET y devuelve
    el evento parseado. Lanza si la firma es inválida."""
    if not STRIPE_WEBHOOK_SECRET:
        raise RuntimeError("STRIPE_WEBHOOK_SECRET no configurada.")

    # TODO: implementar:
    #
    # try:
    #     evento = stripe.Webhook.construct_event(
    #         payload=body, sig_header=signature_header,
    #         secret=STRIPE_WEBHOOK_SECRET,
    #     )
    #     return evento
    # except stripe.error.SignatureVerificationError:
    #     raise ValueError("Firma inválida")
    raise NotImplementedError("Falta verificar la firma del webhook.")


def procesar_evento(evento: dict) -> tuple:
    """Procesa un evento ya verificado. Devuelve (pedido_id, nuevo_estado)
    si el pago se completó, o (None, None) si es un evento que ignoramos."""
    # TODO: implementar:
    #
    # tipo = evento.get("type")
    # if tipo == "checkout.session.completed":
    #     session = evento["data"]["object"]
    #     pedido_id = session.get("client_reference_id") or session.get("metadata", {}).get("pedido_id")
    #     return (pedido_id, "pagado")
    # if tipo == "checkout.session.expired":
    #     pedido_id = ...
    #     return (pedido_id, "cancelado")
    # return (None, None)
    raise NotImplementedError("Falta procesar el evento de Stripe.")

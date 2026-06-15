# pagos_suscripcion.py — Suscripciones de katia.work vía Stripe
# -------------------------------------------------------------------
# Cobro de los planes de katia a los dueños de negocio (no confundir con
# los pagos de las tiendas a sus clientes — eso es pagos_stripe.py).
#
# Degradación elegante: si no hay STRIPE_SECRET_KEY, disponible()=False y
# el constructor usa "modo demo" (activa el plan sin cobrar, para dev).
# -------------------------------------------------------------------
import os

try:
    import stripe
    _SDK_OK = True
except ImportError:
    _SDK_OK = False

STRIPE_SECRET = os.getenv("STRIPE_SECRET_KEY", "")
# Webhook propio de suscripciones (distinto al de pagos de tienda).
WEBHOOK_SECRET = os.getenv("STRIPE_SUB_WEBHOOK_SECRET", "")

if _SDK_OK and STRIPE_SECRET:
    stripe.api_key = STRIPE_SECRET


def disponible() -> bool:
    return bool(_SDK_OK and STRIPE_SECRET)


def crear_checkout(email: str, price_id: str, success_url: str, cancel_url: str,
                   customer_id: str = "") -> str:
    """Crea una sesión de Stripe Checkout (modo suscripción) y devuelve su URL."""
    params = {
        "mode": "subscription",
        "line_items": [{"price": price_id, "quantity": 1}],
        "success_url": success_url,
        "cancel_url": cancel_url,
        "client_reference_id": email,
        "metadata": {"email": email},
        "subscription_data": {"metadata": {"email": email}},
        "allow_promotion_codes": True,
    }
    if customer_id:
        params["customer"] = customer_id
    else:
        params["customer_email"] = email
    return stripe.checkout.Session.create(**params).url


def crear_portal(customer_id: str, return_url: str) -> str:
    """Portal de facturación de Stripe (cambiar/cancelar plan, ver recibos)."""
    return stripe.billing_portal.Session.create(
        customer=customer_id, return_url=return_url
    ).url


def verificar_evento(payload: bytes, firma: str):
    """Valida y devuelve el evento del webhook. Si no hay WEBHOOK_SECRET,
    parsea sin verificar (solo para pruebas)."""
    if WEBHOOK_SECRET:
        return stripe.Webhook.construct_event(payload, firma, WEBHOOK_SECRET)
    import json
    return json.loads(payload)

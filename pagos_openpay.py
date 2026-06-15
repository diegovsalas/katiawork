# pagos_openpay.py — Integración con Openpay México (SPEI bank_account)
# -------------------------------------------------------------------
# Esta sí tiene implementación de arranque porque ya la teníamos
# corriendo. Solo está deshabilitada porque Openpay no había aprobado
# SPEI charges para esta cuenta — cuando lo aprueben, pones
# OPENPAY_MERCHANT_ID y OPENPAY_PRIVATE_KEY en Render y se activa sola.
#
# A diferencia de Stripe/MP, Openpay NO firma sus webhooks por defecto;
# se asegura con whitelist de IPs. Para validación adicional puedes
# definir OPENPAY_WEBHOOK_USER y OPENPAY_WEBHOOK_PASS y configurar
# Basic Auth en el dashboard de Openpay.
# -------------------------------------------------------------------
import os

import requests
from requests.auth import HTTPBasicAuth

import config_pagos as cfg

IMPLEMENTACION_TERMINADA = True

OPENPAY_BASE = (
    "https://api.openpay.mx/v1" if cfg.OPENPAY_PRODUCCION
    else "https://sandbox-api.openpay.mx/v1"
)
OPENPAY_AUTH = HTTPBasicAuth(cfg.OPENPAY_PRIVATE_KEY, "")  # llave privada como user


def disponible() -> bool:
    return bool(
        IMPLEMENTACION_TERMINADA
        and cfg.OPENPAY_PRIVATE_KEY
        and cfg.OPENPAY_MERCHANT_ID
    )


def crear_cargo_spei(pedido_id: str, total: float, descripcion: str,
                     nombre: str, email: str, telefono: str = "") -> dict:
    """Crea un cargo SPEI bank_account. Devuelve datos para mostrar al
    cliente: CLABE + referencia para que transfiera desde su banco."""
    if not disponible():
        raise RuntimeError("Openpay no está habilitado.")

    url = f"{OPENPAY_BASE}/{cfg.OPENPAY_MERCHANT_ID}/charges"
    payload = {
        "method": "bank_account",
        "amount": float(total),
        "description": descripcion,
        "order_id": pedido_id,
        "customer": {
            "name": nombre,
            "email": email,
            "phone_number": telefono or "0000000000",
        },
    }
    resp = requests.post(
        url, json=payload, auth=OPENPAY_AUTH,
        headers={"Content-Type": "application/json"},
        timeout=20,
    )
    if resp.status_code not in (200, 201):
        raise RuntimeError(f"Openpay respondió {resp.status_code}: {resp.text}")

    data = resp.json()
    pm = data.get("payment_method", {})
    return {
        "clabe":      pm.get("clabe", ""),
        "banco":      pm.get("bank", "") or pm.get("name", ""),
        "referencia": pm.get("reference", ""),
        "agreement":  pm.get("agreement", ""),
    }


def procesar_webhook(body: dict) -> tuple:
    """Openpay manda eventos tipo charge.succeeded, charge.failed, etc.
    Devuelve (pedido_id, nuevo_estado) o (None, None) si lo ignoramos."""
    tipo = body.get("type", "")
    transaction = body.get("transaction", {})
    pedido_id = transaction.get("order_id")
    if not pedido_id:
        return (None, None)
    if tipo == "charge.succeeded":
        return (pedido_id, "pagado")
    if tipo in ("charge.failed", "charge.cancelled", "charge.expired"):
        return (pedido_id, "cancelado")
    return (None, None)

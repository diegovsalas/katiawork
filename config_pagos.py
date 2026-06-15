# config_pagos.py
# -------------------------------------------------------------------
# CONFIGURACIÓN DE PAGOS — todo se lee de variables de entorno.
# Los valores tras la coma son SOLO placeholders para desarrollo local.
# En producción configura las env vars (ver .env.example).
#
# 1) BANREGIO  -> transferencia directa a tu cuenta (sin comisión).
# 2) OPENPAY   -> SPEI automático. Llaves desde el dashboard de Openpay.
# -------------------------------------------------------------------
import os


# --- 1) Banregio (transferencia directa) ---
BANREGIO = {
    "titular":  os.getenv("BANREGIO_TITULAR",  "Outlet Momatt México"),
    "banco":    "Banregio",
    "clabe":    os.getenv("BANREGIO_CLABE",    "058000000000000000"),  # 18 dígitos
    "cuenta":   os.getenv("BANREGIO_CUENTA",   "0000000000"),
    "whatsapp": os.getenv("BANREGIO_WHATSAPP", "+52 81 3568 7469"),
    "correo":   os.getenv("BANREGIO_CORREO",   "ventas@momatt.shop"),
}


# --- 2) Openpay (SPEI automático) ---
OPENPAY_MERCHANT_ID = os.getenv("OPENPAY_MERCHANT_ID", "")
OPENPAY_PRIVATE_KEY = os.getenv("OPENPAY_PRIVATE_KEY", "")

# False = ambiente de PRUEBAS (sandbox). True = cobros REALES.
OPENPAY_PRODUCCION = os.getenv("OPENPAY_PRODUCCION", "False").lower() == "true"

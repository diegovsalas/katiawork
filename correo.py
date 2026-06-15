# correo.py — Envío de correos transaccionales via Resend
# -------------------------------------------------------------------
# Lee RESEND_API_KEY del entorno. Si no está, la función no envía
# nada y devuelve False — el resto del flujo de pago sigue normal.
# -------------------------------------------------------------------
import os
from typing import Optional

try:
    import resend
    _RESEND_OK = True
except ImportError:
    _RESEND_OK = False


RESEND_API_KEY = os.getenv("RESEND_API_KEY", "")
RESEND_FROM    = os.getenv("RESEND_FROM", "Outlet Momatt <onboarding@resend.dev>")

if _RESEND_OK and RESEND_API_KEY:
    resend.api_key = RESEND_API_KEY


def _disponible() -> bool:
    return bool(_RESEND_OK and RESEND_API_KEY)


def enviar_confirmacion_pedido(pedido: dict, banregio: dict, dominio: str) -> bool:
    """Envía un correo HTML con el resumen del pedido al cliente.
    Devuelve True si se envió, False si Resend no está configurado o falló."""
    if not _disponible():
        return False

    items_html = "\n".join(
        f"<tr><td style='padding:6px 0;'>{it['cantidad']} × {it['nombre']}</td>"
        f"<td style='padding:6px 0;text-align:right;'>${it['subtotal']:,.0f}</td></tr>"
        for it in pedido["items"]
    )

    enlace = f"{dominio}/pedido/{pedido['id']}"

    html = f"""
    <div style="font-family:-apple-system,Segoe UI,Roboto,sans-serif;max-width:560px;margin:0 auto;color:#222;">
      <h2 style="color:#fe4e02;">¡Gracias por tu pedido, {pedido['nombre'].split()[0]}!</h2>
      <p>Tu pedido <strong>{pedido['id']}</strong> está reservado. Para completarlo,
         haz la transferencia con los datos de abajo y mándanos el comprobante por WhatsApp.</p>

      <table style="width:100%;border-collapse:collapse;margin:18px 0;border:1px solid #eee;">
        <tbody>
          {items_html}
          <tr><td style="padding:8px 0;border-top:1px solid #eee;">Subtotal productos</td>
              <td style="padding:8px 0;border-top:1px solid #eee;text-align:right;">${pedido['subtotal_prod']:,.0f}</td></tr>
          <tr><td style="padding:6px 0;">Envío "ocurre" vía {pedido['paqueteria']}</td>
              <td style="padding:6px 0;text-align:right;">${pedido['envio']:,.0f}</td></tr>
          <tr><td style="padding:6px 0;">IVA (16%)</td>
              <td style="padding:6px 0;text-align:right;">${pedido['iva']:,.0f}</td></tr>
          <tr><td style="padding:10px 0;border-top:2px solid #fe4e02;font-weight:800;">Total a transferir</td>
              <td style="padding:10px 0;border-top:2px solid #fe4e02;text-align:right;font-weight:800;">${pedido['total']:,.0f} MXN</td></tr>
        </tbody>
      </table>

      <div style="background:#f7f7f7;border-radius:8px;padding:16px;margin:18px 0;">
        <p style="margin:0 0 8px;"><strong>Datos para transferir</strong></p>
        <p style="margin:4px 0;">Titular: <strong>{banregio['titular']}</strong></p>
        <p style="margin:4px 0;">Banco: <strong>{banregio['banco']}</strong></p>
        <p style="margin:4px 0;">CLABE: <strong style="font-family:monospace;">{banregio['clabe']}</strong></p>
        <p style="margin:4px 0;">Referencia: <strong>{pedido['id']}</strong></p>
      </div>

      <p><a href="{enlace}"
            style="display:inline-block;background:#fe4e02;color:#fff;text-decoration:none;
                   padding:12px 24px;border-radius:8px;font-weight:700;">
        Ver mi pedido
      </a></p>

      <p style="color:#888;font-size:12px;margin-top:32px;">
        Si tienes dudas, escríbenos por WhatsApp.<br>
        © Outlet Momatt México
      </p>
    </div>
    """

    try:
        resend.Emails.send({
            "from": RESEND_FROM,
            "to": [pedido["email"]],
            "subject": f"Pedido {pedido['id']} reservado · Outlet Momatt México",
            "html": html,
        })
        return True
    except Exception as e:
        print(f"⚠  Falló el envío del correo de confirmación: {e}")
        return False


def enviar_recordatorio_pago(pedido: dict, banregio: dict, dominio: str,
                             whatsapp_visible: str, whatsapp_digits: str) -> bool:
    """Recordatorio de pago para pedidos pendientes. La copia cambia
    según sea el primer (urgencia suave) o segundo (urgencia más fuerte)
    recordatorio."""
    if not _disponible():
        return False

    n = (pedido.get("recordatorios_enviados") or 0) + 1  # qué recordatorio es este
    enlace = f"{dominio}/pedido/{pedido['id']}"
    wa_msg = (f"Hola, ya hice mi pago del pedido {pedido['id']} por "
              f"${pedido['total']:,.0f} MXN. Adjunto comprobante.")
    wa_link = f"https://wa.me/{whatsapp_digits}?text={wa_msg.replace(' ', '%20').replace(',', '%2C')}"

    if n == 1:
        asunto = f"Tu pedido {pedido['id']} sigue esperando depósito"
        titulo = f"Hola {pedido['nombre'].split()[0]}, no hemos recibido tu pago"
        cuerpo_p = ("Tu pedido sigue reservado pero todavía no nos llega tu comprobante. "
                    "Si ya transferiste, mándanos el comprobante por WhatsApp para liberar el envío. "
                    "Si no, aquí tienes los datos para depositar:")
        urgencia = "Te avisamos para que no se te pase."
    else:
        asunto = f"Último recordatorio — pedido {pedido['id']}"
        titulo = f"{pedido['nombre'].split()[0]}, este es nuestro último aviso"
        cuerpo_p = ("Si no recibimos tu comprobante de pago en las próximas 48 horas, vamos a liberar "
                    "el stock para otros clientes. Si ya pagaste, mándanos el comprobante por WhatsApp "
                    "para confirmar y enviar tu pedido.")
        urgencia = "Después de este correo cerramos la reserva."

    html = f"""
    <div style="font-family:-apple-system,Segoe UI,Roboto,sans-serif;max-width:560px;margin:0 auto;color:#222;">
      <h2 style="color:#fe4e02;">{titulo}</h2>
      <p>{cuerpo_p}</p>

      <div style="background:#fff8f0;border:1px solid #fe4e02;border-radius:8px;padding:16px;margin:18px 0;">
        <p style="margin:0 0 8px;"><strong>Pedido {pedido['id']}</strong></p>
        <p style="margin:4px 0;">Total a transferir: <strong>${pedido['total']:,.0f} MXN</strong></p>
        <p style="margin:4px 0;">Referencia: <strong>{pedido['id']}</strong></p>
      </div>

      <div style="background:#f7f7f7;border-radius:8px;padding:16px;margin:18px 0;">
        <p style="margin:0 0 8px;"><strong>Datos para transferir (Banregio)</strong></p>
        <p style="margin:4px 0;">Titular: <strong>{banregio['titular']}</strong></p>
        <p style="margin:4px 0;">CLABE: <strong style="font-family:monospace;">{banregio['clabe']}</strong></p>
      </div>

      <p>
        <a href="{wa_link}"
           style="display:inline-block;background:#25D366;color:#fff;text-decoration:none;
                  padding:12px 24px;border-radius:8px;font-weight:700;margin-right:8px;">
          💬 Mandar comprobante por WhatsApp
        </a>
      </p>
      <p style="margin-top:14px;">
        <a href="{enlace}"
           style="display:inline-block;background:#fe4e02;color:#fff;text-decoration:none;
                  padding:12px 24px;border-radius:8px;font-weight:700;">
          Ver mi pedido
        </a>
      </p>

      <p style="color:#666;font-size:13px;margin-top:18px;"><em>{urgencia}</em></p>

      <p style="color:#888;font-size:12px;margin-top:32px;">
        ¿Ya pagaste y te llegó este correo por error? Avísanos por WhatsApp ({whatsapp_visible})<br>
        y entra al sitio para marcar tu pedido como pagado.<br>
        © Outlet Momatt México
      </p>
    </div>
    """

    try:
        resend.Emails.send({
            "from": RESEND_FROM,
            "to": [pedido["email"]],
            "subject": f"{asunto} · Outlet Momatt México",
            "html": html,
        })
        return True
    except Exception as e:
        print(f"⚠  Falló recordatorio de pago para {pedido['id']}: {e}")
        return False

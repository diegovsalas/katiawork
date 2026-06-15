// analytics.js — Eventos de Google Analytics 4 disparados por clicks.
// -------------------------------------------------------------------
// Eventos disparados desde aquí (todos vía gtag global):
//   - whatsapp_contact  (source: float_button | cotizar | comprobante | chatbot)
//   - ficha_download    (file_name)
//   - add_to_cart       (item_id, quantity)
//
// Eventos disparados inline en templates (no aquí):
//   - view_item        — producto.html
//   - view_cart        — carrito.html
//   - begin_checkout   — checkout.html
//   - purchase         — pago_banregio.html
//   - sign_up          — perfil.html cuando ?welcome=1
// -------------------------------------------------------------------

(function () {
    function track(name, params) {
        if (typeof gtag !== "function") return;
        try { gtag("event", name, params || {}); } catch (e) { /* silencio */ }
    }

    document.addEventListener("click", function (e) {
        // --- WhatsApp links ---
        var wa = e.target.closest('a[href*="wa.me/"]');
        if (wa) {
            var source = "unknown";
            if (wa.classList.contains("whatsapp-float"))      source = "float_button";
            else if (wa.classList.contains("btn-cotizar"))    source = "cotizar";
            else if (wa.classList.contains("btn-pagar-wa"))   source = "comprobante";
            else if (wa.classList.contains("chatbot-cta-wa")) source = "chatbot";
            else if (wa.closest(".aviso-cotizacion"))         source = "aviso_cotizacion";
            track("whatsapp_contact", { source: source });
            return;  // un click = un evento
        }

        // --- Ficha técnica PDF ---
        var ficha = e.target.closest(".btn-ficha");
        if (ficha) {
            var href = ficha.getAttribute("href") || "";
            track("ficha_download", { file_name: href.split("/").pop() });
            return;
        }

        // --- Agregar al carrito ---
        var btnAgregar = e.target.closest(".btn-agregar");
        if (btnAgregar && btnAgregar.type === "submit") {
            var form = btnAgregar.closest("form");
            if (!form) return;
            var pid = form.querySelector('input[name="producto_id"]');
            var qty = form.querySelector('input[name="cantidad"]');
            track("add_to_cart", {
                currency: "MXN",
                items: [{
                    item_id:  pid ? pid.value : "desconocido",
                    quantity: qty ? parseInt(qty.value, 10) || 1 : 1,
                }],
            });
        }
    });
})();

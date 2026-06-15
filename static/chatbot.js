// chatbot.js — Asesor virtual guiado de Outlet Momatt México
// -------------------------------------------------------------------
// Bot de árbol de decisión (sin API ni costo). Pregunta al cliente
// por su caso de uso, recomienda 1-2 modelos del catálogo, y al
// final lo manda a WhatsApp con un resumen pre-llenado para que el
// asesor humano cierre la venta con contexto completo.
// -------------------------------------------------------------------

(function () {
    // El número de WhatsApp se inyecta desde la metaetiqueta del template
    // (mismo número que el botón flotante de WhatsApp).
    const wa = document.querySelector('meta[name="x-whatsapp"]')?.content || '528135687469';
    const waLink = (msg) => `https://wa.me/${wa}?text=${encodeURIComponent(msg)}`;

    // --- Catálogo resumido para recomendaciones (sincronizado con catalogo.py) ---
    // Precios ANTES de IVA. precio_anterior = precio de lista (para tachado).
    const PRODUCTOS = {
        'crown-pth-50':                   { nombre: 'Crown PTH 50',                   capacidad: '2.3 ton', precio: 11900, precio_anterior: 21100, img: 'crown-pth-50.jpg' },
        'truper-pat-3ny':                 { nombre: 'Truper PAT-3NY',                 capacidad: '3 ton',   precio: 7475,  precio_anterior: 11500, img: 'truper-pat-3ny.jpg' },
        'noble-mac-nbq30':                { nombre: 'Noble Mac NBQ30',                capacidad: '3 ton',   precio: null,  img: 'noble-mac-nbq30.jpg' },
        'surtek-trhp25':                  { nombre: 'Surtek TRHP25',                  capacidad: '2.5 ton', precio: 6760,  precio_anterior: 10400, img: 'surtek-trhp25.jpg' },
        'zait-traspaleta-3ton':           { nombre: 'ZAIT Traspaleta',                capacidad: '3 ton',   precio: 3574,  precio_anterior: 5499,  img: 'zait-traspaleta-3ton.webp' },
        'patin-mini-pasillo-angosto':     { nombre: 'Patín Mini Pasillo Angosto',     capacidad: '3 ton',   precio: 4225,  precio_anterior: 6500,  img: 'patin-mini-pasillo-angosto.jpg' },
        'patin-extra-largo-doble-tarima': { nombre: 'Patín Extra Largo Doble Tarima', capacidad: '3 ton',   precio: null,  img: 'patin-extra-largo-doble-tarima.png' },
    };

    // --- Lógica de recomendación (árbol de decisión) ---
    function recomendar(estado) {
        const { piso, peso, prioridad } = estado;
        if (piso === 'angosto')      return ['patin-mini-pasillo-angosto'];
        if (piso === 'largo')        return ['patin-extra-largo-doble-tarima'];
        if (piso === 'concreto') {
            if (peso === '2.3' && prioridad !== 'precio')   return ['crown-pth-50'];
            if (peso === '3' && prioridad === 'precio')     return ['truper-pat-3ny'];
            if (peso === '3' && prioridad === 'premium')    return ['noble-mac-nbq30', 'truper-pat-3ny'];
            return ['truper-pat-3ny', 'crown-pth-50'];
        }
        if (piso === 'pulido') {
            if (peso === '2.5')                              return ['surtek-trhp25'];
            if (prioridad === 'precio')                      return ['zait-traspaleta-3ton'];
            return ['surtek-trhp25', 'zait-traspaleta-3ton'];
        }
        return ['truper-pat-3ny'];
    }

    function fmtPrecio(p) {
        if (p.precio == null) return 'Precio bajo cotización';
        const ahora = `$${p.precio.toLocaleString('es-MX')} MXN + IVA`;
        if (p.precio_anterior) {
            const off = Math.round((p.precio_anterior - p.precio) / p.precio_anterior * 100);
            return `<s style="opacity:.6">$${p.precio_anterior.toLocaleString('es-MX')}</s> ${ahora} <em style="color:var(--amarillo);font-style:normal;font-weight:800;">-${off}%</em>`;
        }
        return ahora;
    }

    function resumenWhatsApp(estado, ids) {
        const productos = ids.map(id => `- ${PRODUCTOS[id].nombre} (${PRODUCTOS[id].capacidad})`).join('\n');
        return `Hola, vengo del asesor virtual de Outlet Momatt.\n\n` +
               `Caso de uso:\n` +
               `• Piso/uso: ${labelPiso(estado.piso)}\n` +
               `• Peso: ${estado.peso} ton\n` +
               `• Prioridad: ${labelPrioridad(estado.prioridad)}\n\n` +
               `Me interesa(n):\n${productos}\n\n¿Me apoyan con cotización y disponibilidad?`;
    }
    const labelPiso = p => ({
        concreto: 'Concreto / andén', pulido: 'Piso pulido / interior',
        angosto: 'Pasillo angosto', largo: 'Cargas extra largas'
    }[p] || p);
    const labelPrioridad = p => ({
        precio: 'Mejor precio', premium: 'Marca premium', ambos: 'Equilibrio precio-calidad'
    }[p] || p);

    // --- Estado de la conversación ---
    const estado = { paso: 'inicio', piso: null, peso: null, prioridad: null };

    // --- Render del panel y mensajes ---
    function init() {
        // Toggle button
        const toggle = document.createElement('button');
        toggle.className = 'chatbot-toggle';
        toggle.setAttribute('aria-label', 'Abrir asesor virtual');
        toggle.innerHTML = '<span class="chatbot-ico">💬</span><span class="chatbot-toggle-label">Asesor virtual</span><span class="chatbot-dot"></span>';
        document.body.appendChild(toggle);

        // Panel
        const panel = document.createElement('div');
        panel.className = 'chatbot-panel';
        panel.setAttribute('aria-hidden', 'true');
        panel.innerHTML = `
            <header class="chatbot-header">
                <div>
                    <strong>Asesor virtual Momatt</strong>
                    <small>Te ayudo a elegir el patín correcto</small>
                </div>
                <button class="chatbot-close" aria-label="Cerrar">✕</button>
            </header>
            <div class="chatbot-body" id="chatbot-body"></div>
        `;
        document.body.appendChild(panel);

        toggle.addEventListener('click', () => {
            const open = panel.classList.toggle('open');
            panel.setAttribute('aria-hidden', String(!open));
            if (open && estado.paso === 'inicio') iniciarConversacion();
        });
        panel.querySelector('.chatbot-close').addEventListener('click', () => {
            panel.classList.remove('open');
            panel.setAttribute('aria-hidden', 'true');
        });
    }

    function body() { return document.getElementById('chatbot-body'); }

    function escribir(texto) {
        const b = body();
        const div = document.createElement('div');
        div.className = 'chatbot-msg bot';
        div.innerHTML = texto;
        b.appendChild(div);
        b.scrollTop = b.scrollHeight;
    }
    function eligio(texto) {
        const b = body();
        const div = document.createElement('div');
        div.className = 'chatbot-msg user';
        div.textContent = texto;
        b.appendChild(div);
        b.scrollTop = b.scrollHeight;
    }
    function opciones(items) {
        const b = body();
        const wrap = document.createElement('div');
        wrap.className = 'chatbot-opts';
        items.forEach(({ label, onClick }) => {
            const btn = document.createElement('button');
            btn.className = 'chatbot-opt';
            btn.textContent = label;
            btn.addEventListener('click', () => {
                wrap.remove();
                eligio(label);
                onClick();
            });
            wrap.appendChild(btn);
        });
        b.appendChild(wrap);
        b.scrollTop = b.scrollHeight;
    }

    function iniciarConversacion() {
        estado.paso = 'piso';
        escribir(`¡Hola! 👋 Soy el asesor virtual de <strong>Outlet Momatt</strong>.<br>En 3 preguntas te recomiendo el patín hidráulico ideal para tu operación.`);
        setTimeout(preguntarPiso, 400);
    }

    function preguntarPiso() {
        escribir(`<strong>1 de 3</strong> · ¿En qué tipo de piso o ambiente lo usarás?`);
        opciones([
            { label: '🏭 Concreto o andén',          onClick: () => { estado.piso = 'concreto'; preguntarPeso(); } },
            { label: '🏬 Piso pulido / interior',    onClick: () => { estado.piso = 'pulido';   preguntarPeso(); } },
            { label: '📐 Pasillo angosto',           onClick: () => { estado.piso = 'angosto';  preguntarPrioridad(); } },
            { label: '📏 Cargas extra largas',       onClick: () => { estado.piso = 'largo';    preguntarPrioridad(); } },
        ]);
    }
    function preguntarPeso() {
        escribir(`<strong>2 de 3</strong> · ¿Cuánto peso máximo moverás regularmente?`);
        opciones([
            { label: 'Hasta 2.3 ton', onClick: () => { estado.peso = '2.3'; preguntarPrioridad(); } },
            { label: '2.5 ton',       onClick: () => { estado.peso = '2.5'; preguntarPrioridad(); } },
            { label: '3 ton o más',   onClick: () => { estado.peso = '3';   preguntarPrioridad(); } },
        ]);
    }
    function preguntarPrioridad() {
        if (!estado.peso) estado.peso = '3';
        escribir(`<strong>3 de 3</strong> · ¿Qué pesa más para ti?`);
        opciones([
            { label: '💰 Mejor precio',             onClick: () => { estado.prioridad = 'precio';  recomendarFinal(); } },
            { label: '🏆 Marca premium',            onClick: () => { estado.prioridad = 'premium'; recomendarFinal(); } },
            { label: '⚖️ Equilibrio precio-calidad', onClick: () => { estado.prioridad = 'ambos';   recomendarFinal(); } },
        ]);
    }

    function recomendarFinal() {
        const ids = recomendar(estado);
        const cards = ids.map(id => {
            const p = PRODUCTOS[id];
            return `
                <a class="chatbot-rec" href="/producto/${id}">
                    <img class="chatbot-rec-img" src="/static/img/${p.img}" alt="${p.nombre}">
                    <div class="chatbot-rec-body">
                        <strong>${p.nombre}</strong>
                        <span>${p.capacidad} · ${fmtPrecio(p)}</span>
                        <em>Ver detalles →</em>
                    </div>
                </a>`;
        }).join('');

        escribir(`Con base en lo que me dijiste, te recomiendo:${cards}`);
        const msg = resumenWhatsApp(estado, ids);
        const ctas = document.createElement('div');
        ctas.className = 'chatbot-ctas';
        ctas.innerHTML = `
            <a class="chatbot-cta-wa" href="${waLink(msg)}" target="_blank" rel="noopener">
                💬 Hablar con un asesor humano
            </a>
            <button class="chatbot-restart">↻ Empezar de nuevo</button>
        `;
        body().appendChild(ctas);
        ctas.querySelector('.chatbot-restart').addEventListener('click', () => {
            estado.paso = 'inicio'; estado.piso = null; estado.peso = null; estado.prioridad = null;
            body().innerHTML = '';
            iniciarConversacion();
        });
        body().scrollTop = body().scrollHeight;
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        init();
    }
})();

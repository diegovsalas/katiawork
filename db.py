# db.py — Capa de base de datos (Postgres)
# -------------------------------------------------------------------
# Diseño minimalista: psycopg3 con connection pool global. Sin ORM.
# Las migraciones (CREATE TABLE IF NOT EXISTS) se corren al arrancar.
#
# Si DATABASE_URL no está configurada, el app sigue arrancando pero
# las funcionalidades que requieren BD (login, registro, pedidos
# persistentes, /perfil) quedan deshabilitadas con warning.
# -------------------------------------------------------------------
import json
import os
from typing import Optional

try:
    from psycopg_pool import ConnectionPool
    from psycopg.rows import dict_row
    _PSYCOPG_OK = True
except ImportError:
    _PSYCOPG_OK = False


DATABASE_URL = os.getenv("DATABASE_URL", "")
_pool: Optional["ConnectionPool"] = None


def disponible() -> bool:
    """¿La BD está configurada y operativa?"""
    return _pool is not None


def init():
    """Inicializa el pool y corre migraciones. Llamar al arrancar el app."""
    global _pool
    if not DATABASE_URL or not _PSYCOPG_OK:
        print("⚠  DATABASE_URL no configurada o psycopg ausente. "
              "Auth y persistencia de pedidos deshabilitados.")
        return

    # Render exige sslmode=require en producción
    url = DATABASE_URL
    if "sslmode=" not in url and "render.com" in url:
        url += ("&" if "?" in url else "?") + "sslmode=require"

    _pool = ConnectionPool(conninfo=url, min_size=1, max_size=5, open=True)
    _migrate()
    print("✓ Postgres conectado y migraciones aplicadas.")


def _migrate():
    """CREATE TABLE IF NOT EXISTS — idempotente, se corre en cada arranque."""
    with _pool.connection() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS usuarios (
                id            SERIAL PRIMARY KEY,
                email         TEXT UNIQUE NOT NULL,
                password_hash TEXT NOT NULL,
                nombre        TEXT NOT NULL,
                telefono      TEXT,
                created_at    TIMESTAMPTZ DEFAULT NOW()
            );
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS pedidos (
                id            TEXT PRIMARY KEY,
                user_id       INTEGER REFERENCES usuarios(id) ON DELETE SET NULL,
                email         TEXT NOT NULL,
                nombre        TEXT NOT NULL,
                telefono      TEXT,
                items         JSONB NOT NULL,
                subtotal_prod INTEGER NOT NULL,
                envio         INTEGER NOT NULL,
                iva           INTEGER NOT NULL,
                total         INTEGER NOT NULL,
                unidades      INTEGER NOT NULL,
                paqueteria    TEXT NOT NULL,
                metodo        TEXT NOT NULL,
                estado        TEXT NOT NULL DEFAULT 'pendiente_pago',
                created_at    TIMESTAMPTZ DEFAULT NOW()
            );
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_pedidos_email   ON pedidos(email);")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_pedidos_user_id ON pedidos(user_id);")
        # Migración aditiva: ciudad/estado de entrega y datos fiscales
        # opcionales. ADD COLUMN IF NOT EXISTS es seguro de re-ejecutar.
        conn.execute("ALTER TABLE pedidos ADD COLUMN IF NOT EXISTS ciudad_entrega TEXT;")
        conn.execute("ALTER TABLE pedidos ADD COLUMN IF NOT EXISTS estado_entrega TEXT;")
        conn.execute("ALTER TABLE pedidos ADD COLUMN IF NOT EXISTS sucursal       TEXT;")
        conn.execute("ALTER TABLE pedidos ADD COLUMN IF NOT EXISTS rfc            TEXT;")
        conn.execute("ALTER TABLE pedidos ADD COLUMN IF NOT EXISTS razon_social   TEXT;")
        conn.execute("ALTER TABLE pedidos ADD COLUMN IF NOT EXISTS cp_fiscal      TEXT;")
        conn.execute("ALTER TABLE pedidos ADD COLUMN IF NOT EXISTS recordatorio_pago_at   TIMESTAMPTZ;")
        conn.execute("ALTER TABLE pedidos ADD COLUMN IF NOT EXISTS recordatorios_enviados INTEGER DEFAULT 0;")
        conn.execute("ALTER TABLE pedidos ADD COLUMN IF NOT EXISTS guia                   TEXT;")
        conn.commit()


# ------------------- USUARIOS -------------------

def crear_usuario(email: str, password_hash: str, nombre: str, telefono: str = ""):
    """Inserta usuario y devuelve el row creado. Lanza si el email ya existe."""
    with _pool.connection() as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                "INSERT INTO usuarios (email, password_hash, nombre, telefono) "
                "VALUES (%s, %s, %s, %s) RETURNING *;",
                (email.lower().strip(), password_hash, nombre.strip(), telefono.strip() or None),
            )
            return cur.fetchone()


def buscar_usuario_por_email(email: str):
    with _pool.connection() as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute("SELECT * FROM usuarios WHERE email = %s;", (email.lower().strip(),))
            return cur.fetchone()


def buscar_usuario_por_id(user_id: int):
    with _pool.connection() as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute("SELECT * FROM usuarios WHERE id = %s;", (user_id,))
            return cur.fetchone()


# ------------------- PEDIDOS -------------------

def crear_pedido(pedido_id: str, user_id, email: str, nombre: str, telefono: str,
                 items: list, subtotal_prod: int, envio: int, iva: int, total: int,
                 unidades: int, paqueteria: str, metodo: str,
                 ciudad_entrega: str = "", estado_entrega: str = "",
                 sucursal: str = "",
                 rfc: str = "", razon_social: str = "", cp_fiscal: str = ""):
    """Persiste un pedido. user_id puede ser None (guest checkout)."""
    with _pool.connection() as conn:
        conn.execute(
            "INSERT INTO pedidos (id, user_id, email, nombre, telefono, items, "
            "subtotal_prod, envio, iva, total, unidades, paqueteria, metodo, "
            "ciudad_entrega, estado_entrega, sucursal, rfc, razon_social, cp_fiscal) "
            "VALUES (%s, %s, %s, %s, %s, %s::jsonb, %s, %s, %s, %s, %s, %s, %s, "
            "%s, %s, %s, %s, %s, %s);",
            (pedido_id, user_id, email.lower().strip(), nombre, telefono or None,
             json.dumps(items), subtotal_prod, envio, iva, total, unidades, paqueteria, metodo,
             ciudad_entrega or None, estado_entrega or None, sucursal or None,
             rfc or None, razon_social or None, cp_fiscal or None),
        )
        conn.commit()


def buscar_pedido(pedido_id: str):
    with _pool.connection() as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute("SELECT * FROM pedidos WHERE id = %s;", (pedido_id,))
            return cur.fetchone()


def listar_pedidos_de_usuario(user_id: int):
    with _pool.connection() as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                "SELECT * FROM pedidos WHERE user_id = %s ORDER BY created_at DESC;",
                (user_id,),
            )
            return cur.fetchall()


def actualizar_estado_pedido(pedido_id: str, nuevo_estado: str, guia: str = None) -> bool:
    """Cambia el estado de un pedido. Si se pasa guia, también la actualiza."""
    with _pool.connection() as conn:
        with conn.cursor() as cur:
            if guia is not None:
                cur.execute(
                    "UPDATE pedidos SET estado = %s, guia = %s WHERE id = %s;",
                    (nuevo_estado, guia or None, pedido_id),
                )
            else:
                cur.execute(
                    "UPDATE pedidos SET estado = %s WHERE id = %s;",
                    (nuevo_estado, pedido_id),
                )
            ok = cur.rowcount > 0
            conn.commit()
            return ok


# ------------------- ADMIN -------------------

def listar_pedidos(estado: str = None, busqueda: str = None, limit: int = 200):
    """Lista pedidos para el panel admin, con filtros opcionales."""
    with _pool.connection() as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            sql = "SELECT * FROM pedidos WHERE 1=1"
            params = []
            if estado and estado != "todos":
                sql += " AND estado = %s"
                params.append(estado)
            if busqueda:
                sql += " AND (id ILIKE %s OR email ILIKE %s OR nombre ILIKE %s)"
                q = f"%{busqueda}%"
                params += [q, q, q]
            sql += " ORDER BY created_at DESC LIMIT %s;"
            params.append(limit)
            cur.execute(sql, tuple(params))
            return cur.fetchall()


def listar_usuarios(busqueda: str = None, limit: int = 500):
    """Lista usuarios registrados con conteo de pedidos y total gastado.
    Pedidos cobrados = estado in ('pagado','enviado','entregado')."""
    with _pool.connection() as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            sql = """
                SELECT u.id, u.email, u.nombre, u.telefono, u.created_at,
                       COUNT(p.id) AS num_pedidos,
                       COALESCE(SUM(p.total) FILTER (
                           WHERE p.estado IN ('pagado','enviado','entregado')
                       ), 0) AS total_gastado,
                       MAX(p.created_at) AS ultimo_pedido
                FROM usuarios u
                LEFT JOIN pedidos p ON p.user_id = u.id
            """
            params = []
            if busqueda:
                sql += " WHERE u.email ILIKE %s OR u.nombre ILIKE %s OR u.telefono ILIKE %s"
                q = f"%{busqueda}%"
                params += [q, q, q]
            sql += " GROUP BY u.id, u.email, u.nombre, u.telefono, u.created_at"
            sql += " ORDER BY u.created_at DESC LIMIT %s;"
            params.append(limit)
            cur.execute(sql, tuple(params))
            return cur.fetchall()


def stats_dashboard():
    """Métricas para el dashboard admin."""
    with _pool.connection() as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute("""
                SELECT
                    COUNT(*) FILTER (WHERE estado = 'pendiente_pago') AS pendientes_pago,
                    COUNT(*) FILTER (WHERE estado = 'comprobante_enviado') AS por_validar,
                    COUNT(*) FILTER (WHERE estado = 'pagado') AS pagados,
                    COUNT(*) FILTER (WHERE estado = 'enviado') AS enviados,
                    COUNT(*) FILTER (WHERE estado = 'entregado') AS entregados,
                    COUNT(*) AS total_pedidos,
                    COALESCE(SUM(total) FILTER (WHERE estado IN ('pagado','enviado','entregado')
                                                AND created_at > NOW() - INTERVAL '30 days'), 0) AS ventas_30d,
                    COALESCE(SUM(total) FILTER (WHERE estado IN ('pagado','enviado','entregado')), 0) AS ventas_total
                FROM pedidos;
            """)
            stats = cur.fetchone()
            # Conteo de usuarios registrados
            cur.execute("SELECT COUNT(*) AS total_usuarios, "
                        "COUNT(*) FILTER (WHERE created_at > NOW() - INTERVAL '30 days') AS usuarios_30d "
                        "FROM usuarios;")
            usuarios = cur.fetchone()
            stats["total_usuarios"] = usuarios["total_usuarios"]
            stats["usuarios_30d"] = usuarios["usuarios_30d"]
            return stats


def pedidos_para_recordatorio(max_recordatorios: int = 2,
                              horas_desde_pedido: int = 24,
                              horas_entre_recordatorios: int = 48):
    """Devuelve pedidos que necesitan recordatorio de pago:
       - estado pendiente_pago
       - creados hace al menos `horas_desde_pedido` horas
       - con menos de `max_recordatorios` recordatorios enviados
       - último recordatorio hace más de `horas_entre_recordatorios` horas
         (o nunca enviado)."""
    with _pool.connection() as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                """
                SELECT * FROM pedidos
                WHERE estado = 'pendiente_pago'
                  AND created_at < NOW() - INTERVAL '%s hours'
                  AND COALESCE(recordatorios_enviados, 0) < %s
                  AND (recordatorio_pago_at IS NULL
                       OR recordatorio_pago_at < NOW() - INTERVAL '%s hours')
                ORDER BY created_at ASC
                LIMIT 50;
                """,
                (horas_desde_pedido, max_recordatorios, horas_entre_recordatorios),
            )
            return cur.fetchall()


def marcar_recordatorio_enviado(pedido_id: str):
    with _pool.connection() as conn:
        conn.execute(
            "UPDATE pedidos "
            "SET recordatorio_pago_at = NOW(), "
            "    recordatorios_enviados = COALESCE(recordatorios_enviados, 0) + 1 "
            "WHERE id = %s;",
            (pedido_id,),
        )
        conn.commit()


def adoptar_pedidos_huerfanos(user_id: int, email: str):
    """Cuando un usuario se registra, asocia sus pedidos previos hechos
    como guest (user_id NULL) con el mismo email."""
    with _pool.connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE pedidos SET user_id = %s "
                "WHERE user_id IS NULL AND email = %s;",
                (user_id, email.lower().strip()),
            )
            n = cur.rowcount
            conn.commit()
            return n

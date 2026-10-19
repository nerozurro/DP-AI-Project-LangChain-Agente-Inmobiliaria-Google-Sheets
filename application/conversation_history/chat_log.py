"""
Log plano de la conversación en PostgreSQL: una fila por mensaje, legible con SQL.

Complementa al checkpointer (no lo reemplaza): sirve para reportes, QA y
auditoría, y es el único registro fiel de lo que se dijo si más adelante se
resume o recorta el historial del agente.

Las escrituras son fire-and-forget: si falla el log, el usuario igual recibe
su respuesta.

Opcional en .env: DB_CHAT_LOG_TABLE (chat_log)

Autor: Ing. Kevin Inofuente Colque - DataPath
"""

import os

from dotenv import load_dotenv, find_dotenv
from psycopg import sql

from conversation_history.conexion import pool

load_dotenv(find_dotenv())

# ============================================
# CONFIGURACIÓN
# ============================================
TABLE_NAME = os.getenv("DB_CHAT_LOG_TABLE", "chat_log")

_TABLA = sql.Identifier(TABLE_NAME)
_INDICE = sql.Identifier(f"{TABLE_NAME}_thread_id_creado_en_idx")


# ============================================
# FUNCIONES PÚBLICAS
# ============================================
def crear_tabla_log() -> None:
    """Crea la tabla del log plano si no existe y le activa RLS (idempotente)."""
    with pool.connection() as conn:
        conn.execute(
            sql.SQL(
                """
                CREATE TABLE IF NOT EXISTS {tabla} (
                    id           BIGSERIAL PRIMARY KEY,
                    thread_id    TEXT        NOT NULL,
                    rol          TEXT        NOT NULL CHECK (rol IN ('user', 'assistant')),
                    contenido    TEXT        NOT NULL,
                    tools_usadas TEXT[],
                    creado_en    TIMESTAMPTZ NOT NULL DEFAULT now()
                )
                """
            ).format(tabla=_TABLA)
        )
        conn.execute(
            sql.SQL(
                "CREATE INDEX IF NOT EXISTS {indice} ON {tabla} (thread_id, creado_en)"
            ).format(indice=_INDICE, tabla=_TABLA)
        )
        conn.execute(
            sql.SQL("ALTER TABLE {tabla} ENABLE ROW LEVEL SECURITY").format(tabla=_TABLA)
        )


def log_mensaje(
    thread_id: str,
    rol: str,
    contenido: str,
    tools_usadas: list[str] | None = None,
) -> None:
    """Registra un mensaje en el log plano. Nunca lanza excepción."""
    try:
        with pool.connection() as conn:
            conn.execute(
                sql.SQL(
                    "INSERT INTO {tabla} (thread_id, rol, contenido, tools_usadas) "
                    "VALUES (%s, %s, %s, %s)"
                ).format(tabla=_TABLA),
                (thread_id, rol, contenido, tools_usadas or None),
            )
    except Exception as e:
        print(f"⚠️ No se pudo registrar el mensaje en {TABLE_NAME}: {e}")

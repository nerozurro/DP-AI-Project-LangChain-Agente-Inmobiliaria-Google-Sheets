"""
Checkpointer de LangGraph sobre PostgreSQL (memoria de corto plazo del agente).

Guarda el estado completo de cada hilo (thread_id): mensajes del usuario, del
modelo, tool calls y resultados de tools. Es lo que el agente recarga en cada
turno para continuar la conversación.

Tablas que crea `setup()`: checkpoints, checkpoint_blobs, checkpoint_writes,
checkpoint_migrations. Los mensajes van serializados en binario: para leer
conversaciones con SQL usa la tabla plana de chat_log.py.

Autor: Ing. Kevin Inofuente Colque - DataPath
"""

from langgraph.checkpoint.postgres import PostgresSaver

from conversation_history.conexion import pool

# ============================================
# CONSTANTES
# ============================================
TABLAS_CHECKPOINTER = (
    "checkpoints",
    "checkpoint_blobs",
    "checkpoint_writes",
    "checkpoint_migrations",
)

checkpointer = PostgresSaver(pool)


# ============================================
# FUNCIONES PÚBLICAS
# ============================================
def crear_tablas_checkpointer() -> None:
    """Crea/migra las tablas del checkpointer y les activa RLS (idempotente).

    RLS sin políticas cierra el acceso por PostgREST (anon key de Supabase).
    El agente no se ve afectado: conecta con el rol dueño de las tablas.
    """
    checkpointer.setup()
    with pool.connection() as conn:
        for tabla in TABLAS_CHECKPOINTER:
            conn.execute(f"ALTER TABLE {tabla} ENABLE ROW LEVEL SECURITY")

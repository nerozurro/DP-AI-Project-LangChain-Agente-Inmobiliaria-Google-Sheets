"""
Módulo de Histórico de Conversación (PostgreSQL).

Dos piezas que se complementan:
- checkpointer: estado completo del agente por thread_id (memoria de corto plazo)
- chat_log: una fila por mensaje, legible con SQL (reportes y auditoría)
"""

from conversation_history.checkpointer import checkpointer, crear_tablas_checkpointer
from conversation_history.chat_log import crear_tabla_log, log_mensaje

__all__ = [
    "checkpointer",
    "crear_tablas_checkpointer",
    "crear_tabla_log",
    "log_mensaje",
]

"""
Pool de conexiones a PostgreSQL compartido por el checkpointer y el log plano.

Un pool (y no una conexión suelta) porque el proveedor cierra las conexiones
inactivas y psycopg no reconecta solo: con una conexión única, el bot deja de
responder hasta reiniciar el proceso. `check_connection` valida cada conexión
antes de entregarla.

Requeridas en .env: DB_USER, DB_PASSWORD, DB_HOST
Opcionales: DB_PORT (5432), DB_NAME (postgres)

Autor: Ing. Kevin Inofuente Colque - DataPath
"""

import os
from urllib.parse import quote_plus

from dotenv import load_dotenv, find_dotenv
from psycopg_pool import ConnectionPool

load_dotenv(find_dotenv())

# ============================================
# CONFIGURACIÓN DE BASE DE DATOS
# ============================================
DB_USER = os.getenv("DB_USER")
DB_PASSWORD = os.getenv("DB_PASSWORD")
DB_HOST = os.getenv("DB_HOST")
DB_PORT = os.getenv("DB_PORT", "5432")
DB_NAME = os.getenv("DB_NAME", "postgres")

if not all([DB_USER, DB_PASSWORD, DB_HOST]):
    raise ValueError(
        "❌ Faltan variables de base de datos en .env\n"
        "Requeridas: DB_USER, DB_PASSWORD, DB_HOST"
    )

DATABASE_URL = (
    f"postgresql://{DB_USER}:{quote_plus(DB_PASSWORD)}@{DB_HOST}:{DB_PORT}/{DB_NAME}"
)

print(f"🔌 Conectando como: {DB_USER}@{DB_HOST}:{DB_PORT}/{DB_NAME}")

# ============================================
# POOL DE CONEXIONES
# ============================================
# - autocommit: lo exige PostgresSaver (su setup crea índices fuera de transacción)
# - prepare_threshold=0: obligatorio detrás de un pooler en modo transacción
#   (Supabase 6543 / PgBouncer); sin él, "prepared statement already exists"
# - connect_timeout / timeout: que una base caída no cuelgue el arranque
pool = ConnectionPool(
    DATABASE_URL,
    min_size=1,
    max_size=10,
    kwargs={"autocommit": True, "prepare_threshold": 0, "connect_timeout": 5},
    timeout=5,
    check=ConnectionPool.check_connection,
    open=True,
)

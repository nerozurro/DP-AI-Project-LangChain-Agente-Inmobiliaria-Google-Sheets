"""
Agente IA Completo: Base de Conocimiento + Internet + Histórico
- Tool 1: Base de Conocimiento de Alpha State (RAG con Qdrant)
- Tool 2: Búsqueda en Internet (Tavily)
- Memoria: checkpointer de LangGraph en PostgreSQL (estado completo por thread_id)
- Log plano: una fila por mensaje en PostgreSQL (reportes y auditoría)
- Config del modelo: model_config/model_config.yaml
- System prompt: prompt/prompt.yaml

Autor: Ing. Kevin Inofuente Colque - DataPath
"""

import os
import sys
import uuid
from datetime import datetime
from zoneinfo import ZoneInfo

import yaml
from dotenv import load_dotenv, find_dotenv

load_dotenv(find_dotenv())

# Agregar el directorio actual al path para importar tools (portable para despliegue)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from langchain.agents import create_agent
from langchain.agents.middleware import ModelRequest, dynamic_prompt
from langchain.chat_models import init_chat_model
from langchain_core.messages import AIMessage, HumanMessage

# ============================================
# 0. CARGA DE CONFIGURACIÓN (YAML)
# ============================================
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
MODEL_CONFIG_PATH = os.path.join(BASE_DIR, "model_config", "model_config.yaml")
PROMPT_PATH = os.path.join(BASE_DIR, "prompt", "prompt.yaml")


def _cargar_yaml(ruta: str) -> dict:
    """Lee un archivo YAML de configuración y lo devuelve como dict."""
    with open(ruta, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


model_config = _cargar_yaml(MODEL_CONFIG_PATH)
prompt_config = _cargar_yaml(PROMPT_PATH)

# Importar tools desde la carpeta tools/
from tools.Base_de_conocimiento import buscar_alpha_state
from tools.Busqueda_internet import buscar_internet
from tools.Hora_y_fecha import obtener_fecha_hora
from tools.Google_Sheets import (
    consultar_total_inquilino,
    consultar_desglose_inquilino,
)
from tools.Google_Sheets_Departamentos import (
    buscar_departamentos,
    consultar_detalle_departamento,
)

# Memoria (checkpointer) + log plano de la conversación (PostgreSQL)
from conversation_history import (
    checkpointer,
    crear_tablas_checkpointer,
    crear_tabla_log,
    log_mensaje,
)

# ============================================
# 2. LISTA DE TOOLS DISPONIBLES
# ============================================
tools = [
    buscar_alpha_state,                # Base de conocimiento Alpha State (RAG/Qdrant)
    buscar_internet,                # Búsqueda en internet (Tavily)
    obtener_fecha_hora,             # Fecha y hora actual por zona horaria
    consultar_total_inquilino,      # Total mensual de un inquilino (Google Sheets)
    consultar_desglose_inquilino,   # Desglose de la cuota de un inquilino (Google Sheets)
    buscar_departamentos,
    consultar_detalle_departamento,
]

# ============================================
# 3. CONFIGURACIÓN DEL MODELO
# ============================================
# Parámetros del LLM desde model_config/model_config.yaml
# (create_agent le enlaza las tools; no hace falta bind_tools)
_llm_cfg = model_config["llm"]

chat = init_chat_model(
    _llm_cfg["model"],
    model_provider=_llm_cfg["provider"],
    temperature=_llm_cfg["temperature"],
)

# ============================================
# 4. PROMPT DEL AGENTE + CONTEXTO FECHA/HORA
# ============================================
# La zona horaria puede venir del .env; si no, del bloque `agent` de model_config/model_config.yaml
AGENT_TIMEZONE = os.getenv(
    "AGENT_TIMEZONE",
    model_config.get("agent", {}).get("timezone", "America/Lima"),
)

# Plantilla del system prompt (prompt/prompt.yaml). Los placeholders se inyectan por turno.
SYSTEM_PROMPT_TEMPLATE = prompt_config["system_prompt"]


def _contexto_fecha_hora() -> str:
    """Fecha y hora actual para inyectar en el system prompt (cada turno)."""
    try:
        tz = ZoneInfo(AGENT_TIMEZONE)
    except Exception:
        tz = ZoneInfo("America/Lima")
    now = datetime.now(tz)
    return now.strftime("%Y-%m-%d %H:%M:%S") + f" (zona {AGENT_TIMEZONE})"


def _render_system_prompt() -> str:
    """Renderiza el system prompt reemplazando los placeholders de prompt/prompt.yaml."""
    return SYSTEM_PROMPT_TEMPLATE.replace("{fecha_hora_actual}", _contexto_fecha_hora())


@dynamic_prompt
def _system_prompt_del_turno(request: ModelRequest) -> str:
    """System prompt con la fecha/hora de ESTE turno. No se persiste en el checkpointer."""
    return _render_system_prompt()


# ============================================
# 5. INICIALIZAR MEMORIA (PostgreSQL)
# ============================================
# Ambas son idempotentes: crean las tablas solo si no existen
crear_tablas_checkpointer()
crear_tabla_log()

# ============================================
# 6. AGENTE (bucle de tools + memoria por thread_id)
# ============================================
agente = create_agent(
    model=chat,
    tools=tools,
    middleware=[_system_prompt_del_turno],
    checkpointer=checkpointer,
)


def _tools_del_turno(mensajes: list) -> list[str]:
    """Nombres de las tools que el agente llamó después del último mensaje del usuario."""
    usadas = []
    for msg in reversed(mensajes):
        if isinstance(msg, HumanMessage):
            break
        if isinstance(msg, AIMessage):
            usadas.extend(tc["name"] for tc in msg.tool_calls)
    return list(reversed(usadas))


def chat_con_agente(mensaje_usuario: str, thread_id: str) -> str:
    """
    Ejecuta un turno del agente. El historial lo recarga el checkpointer por thread_id;
    el agente encadena tantas llamadas a tools como necesite antes de responder.
    """
    # Se registra antes de invocar: si el turno falla, queda constancia de la pregunta
    log_mensaje(thread_id, "user", mensaje_usuario)

    resultado = agente.invoke(
        {"messages": [HumanMessage(content=mensaje_usuario)]},
        config={"configurable": {"thread_id": thread_id}},
    )
    mensajes = resultado["messages"]
    respuesta_final = str(mensajes[-1].text)

    log_mensaje(thread_id, "assistant", respuesta_final, _tools_del_turno(mensajes))

    return respuesta_final


# ============================================
# 7. LOOP DE CONVERSACIÓN
# ============================================
def main():
    print("=" * 60)
    print("🤖 Agente Alpha State (Sheets + RAG + Internet + Memoria)")
    print("=" * 60)
    print("🔧 Tools disponibles:")
    for t in tools:
        print(f"   - {t.name}")
    print("💾 Memoria: checkpointer PostgreSQL + log plano")
    
    # Menú de sesión
    print("\nOpciones de sesión:")
    print("  1. Nueva conversación")
    print("  2. Continuar sesión existente (pegar UUID)")
    
    opcion = input("\nElige (1/2): ").strip()
    
    if opcion == "2":
        session_id = input("Pega el UUID de la sesión: ").strip()
        try:
            uuid.UUID(session_id)
        except ValueError:
            print("⚠️ UUID inválido. Creando nueva sesión...")
            session_id = str(uuid.uuid4())
    else:
        session_id = str(uuid.uuid4())
    
    print(f"\n📝 Session ID: {session_id}")
    print("   (Guarda este ID para continuar después)")
    print("✅ El agente puede consultar Google Sheets, la base de Alpha State e INTERNET")
    print("Escribe 'salir' para volver al menú.\n")
    
    while True:
        usuario = input("Tú: ").strip()
        
        if usuario.lower() in ['salir', 'exit', 'quit']:
            print(f"\n💾 Tu sesión está guardada.")
            print(f"   UUID: {session_id}")
            print("👋 ¡Hasta luego!")
            break
        
        if not usuario:
            continue
        
        try:
            respuesta = chat_con_agente(usuario, session_id)
            print(f"\n🤖 DataBot: {respuesta}\n")
        except Exception as e:
            print(f"\n❌ Error: {e}\n")


if __name__ == "__main__":
    main()

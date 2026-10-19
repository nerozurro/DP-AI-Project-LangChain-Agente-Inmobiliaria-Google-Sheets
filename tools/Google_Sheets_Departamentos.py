"""
Tool: Catálogo de inmuebles en alquiler de Alpha State (SOLO LECTURA).
Referencia: Inmuebles en Alquiler - Alpha State V2.xlsx, pestaña Departamentos.

Expone buscar_departamentos y consultar_detalle_departamento.
Usa una hoja independiente de la de pagos y la misma cuenta de servicio.
Variables: GOOGLE_SHEET_DEPARTAMENTOS_ID (requerida),
GOOGLE_SHEETS_DEPARTAMENTOS_WORKSHEET (Departamentos),
GOOGLE_SHEETS_DEPARTAMENTOS_HEADER_ROW (1), GOOGLE_APPLICATION_CREDENTIALS.
El Excel local es referencia del esquema; las consultas leen Google Sheets.
"""

import os
import re
import unicodedata
from typing import Optional

from dotenv import load_dotenv, find_dotenv
from langchain_core.tools import tool

import gspread
from google.oauth2.service_account import Credentials

load_dotenv(find_dotenv())

# ============================================
# CONFIGURACIÓN
# ============================================
GOOGLE_SHEET_DEPARTAMENTOS_ID = os.getenv("GOOGLE_SHEET_DEPARTAMENTOS_ID")
GOOGLE_SHEETS_DEPARTAMENTOS_WORKSHEET = os.getenv("GOOGLE_SHEETS_DEPARTAMENTOS_WORKSHEET", "Departamentos")
GOOGLE_SHEETS_DEPARTAMENTOS_HEADER_ROW = int(os.getenv("GOOGLE_SHEETS_DEPARTAMENTOS_HEADER_ROW", "1"))
GOOGLE_APPLICATION_CREDENTIALS = os.getenv(
    "GOOGLE_APPLICATION_CREDENTIALS",
    "credentials/service-account.json",
)

# Scope de SOLO LECTURA
SCOPES = ["https://www.googleapis.com/auth/spreadsheets.readonly"]

# Colores ANSI para los logs de acceso a Google Sheets
VERDE = "\033[92m"
ROJO = "\033[91m"
RESET = "\033[0m"

# ============================================
# LOGS DE ACCESO
# ============================================
def _log_ok(mensaje: str) -> None:
    print(f"{VERDE}✅ [Google Sheets Departamentos] {mensaje}{RESET}")


def _log_error(mensaje: str) -> None:
    print(f"{ROJO}❌ [Google Sheets Departamentos] {mensaje}{RESET}")


def _explicar_error(e: Exception, sa_email: str) -> str:
    """Traduce la excepción de gspread/google-auth a la causa más probable."""
    if isinstance(e, FileNotFoundError):
        return str(e)
    if isinstance(e, gspread.exceptions.SpreadsheetNotFound):
        return (
            f"No se encontró la hoja '{GOOGLE_SHEET_DEPARTAMENTOS_ID}'. Verifica GOOGLE_SHEET_DEPARTAMENTOS_ID "
            f"y que esté compartida con {sa_email}."
        )
    if isinstance(e, gspread.exceptions.WorksheetNotFound):
        return (
            f"La hoja existe, pero no tiene la pestaña '{GOOGLE_SHEETS_DEPARTAMENTOS_WORKSHEET}'. "
            f"Revisa GOOGLE_SHEETS_DEPARTAMENTOS_WORKSHEET."
        )
    if isinstance(e, PermissionError):
        return (
            f"Permiso denegado (403). Comparte la hoja con {sa_email} "
            f"como Lector/Editor."
        )
    if isinstance(e, gspread.exceptions.APIError):
        status = getattr(e.response, "status_code", "?")
        if status == 403:
            return (
                f"Permiso denegado (403). Comparte la hoja con {sa_email} o "
                f"habilita la Google Sheets API en el proyecto de GCP. Detalle: {e}"
            )
        return f"Error de la API de Google Sheets (HTTP {status}): {e}"
    return f"{type(e).__name__}: {e}"


# ============================================
# CLIENTE GSPREAD (lazy + cache simple)
# ============================================
_worksheet = None


def _resolve_credentials_path(path: str) -> str:
    """Si la ruta es relativa, la resuelve contra el directorio del proyecto."""
    if os.path.isabs(path):
        return path
    project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(project_root, path)


def _get_worksheet():
    """Conecta a Google Sheets de forma lazy y devuelve el worksheet."""
    global _worksheet
    if _worksheet is not None:
        return _worksheet

    if not GOOGLE_SHEET_DEPARTAMENTOS_ID:
        raise ValueError("Falta GOOGLE_SHEET_DEPARTAMENTOS_ID en .env")
    if not GOOGLE_SHEET_DEPARTAMENTOS_ID:
        raise ValueError("Falta GOOGLE_SHEET_DEPARTAMENTOS_ID en .env")
    creds_path = _resolve_credentials_path(GOOGLE_APPLICATION_CREDENTIALS)
    sa_email = "la cuenta de servicio"
    try:
        if not os.path.isfile(creds_path):
            raise FileNotFoundError(
                f"No se encontró el JSON de la cuenta de servicio en '{creds_path}'. "
                f"Descárgalo desde Google Cloud y colócalo en esa ruta."
            )

        creds = Credentials.from_service_account_file(creds_path, scopes=SCOPES)
        sa_email = creds.service_account_email
        client = gspread.authorize(creds)
        sheet = client.open_by_key(GOOGLE_SHEET_DEPARTAMENTOS_ID)
        worksheet = sheet.worksheet(GOOGLE_SHEETS_DEPARTAMENTOS_WORKSHEET)
        # Lectura real: confirma que la cuenta de servicio puede leer celdas
        worksheet.row_values(GOOGLE_SHEETS_DEPARTAMENTOS_HEADER_ROW)
    except Exception as e:
        _log_error("La Service Account NO logró acceso a Google Sheets.")
        _log_error(f"   Cuenta: {sa_email}")
        _log_error(f"   Causa: {_explicar_error(e, sa_email)}")
        raise

    _log_ok("La Service Account logró ACCESO COMPLETO a Google Sheets.")
    _log_ok(f"   Cuenta: {sa_email}")
    _log_ok(f"   Hoja: '{sheet.title}' → pestaña '{worksheet.title}'")
    _worksheet = worksheet
    return _worksheet


def verificar_acceso_google_sheets_departamentos() -> bool:
    """Prueba la conexión al arrancar y deja el log verde o rojo. No lanza excepción."""
    try:
        _get_worksheet()
        return True
    except Exception:
        return False


# ============================================
# UTILIDADES
# ============================================
def _normalize(text) -> str:
    """Normaliza texto: minúsculas, sin acentos, sin espacios extra."""
    if text is None:
        return ""
    s = unicodedata.normalize("NFKD", str(text))
    s = "".join(c for c in s if not unicodedata.combining(c))
    return s.lower().strip()



def _parse_amount(value) -> Optional[float]:
    """Lee números de Sheets, incluidos formatos BRL: 1.400,00 o 1400.00."""
    if value is None or not str(value).strip():
        return None
    if isinstance(value, (int, float)):
        return float(value)
    s = re.sub(r"[R$\s\u00a0]", "", str(value).strip())
    if "," in s:
        s = s.replace(".", "").replace(",", ".")
    elif re.fullmatch(r"-?\d{1,3}(?:\.\d{3})+", s):
        s = s.replace(".", "")
    try:
        result = float(s)
        return result if result == result and abs(result) != float("inf") else None
    except ValueError:
        return None


COLUMNAS = (
    "ID Inmueble", "Tipo", "Barrio", "Dirección", "Metros Cuadrados",
    "Habitaciones", "Baños", "Cocheras", "Alquiler Mensual (BRL)",
    "IPTU Mensual (BRL)", "Agua / SANASA", "Estado Amoblado",
)


def _cargar_datos() -> list[dict]:
    """Lee valores actuales; valida columnas y omite las filas vacías."""
    values = _get_worksheet().get_all_values()
    header_idx = GOOGLE_SHEETS_DEPARTAMENTOS_HEADER_ROW - 1
    if header_idx < 0 or header_idx >= len(values):
        raise ValueError("La fila de encabezados configurada no existe.")
    headers = [_normalize(h) for h in values[header_idx]]
    if any(headers.count(_normalize(col)) != 1 for col in COLUMNAS):
        raise ValueError("Encabezados faltantes o duplicados: se esperan " + ", ".join(COLUMNAS))
    positions = {col: headers.index(_normalize(col)) for col in COLUMNAS}
    result = []
    for row in values[header_idx + 1:]:
        record = {col: str(row[i]).strip() if i < len(row) else "" for col, i in positions.items()}
        if record["ID Inmueble"]:
            result.append(record)
    return result


def _formatear_inmueble(fila: dict) -> str:
    """Conserva valores y moneda del catálogo, sin inventar gastos ni disponibilidad."""
    return "\n".join(f"- {col}: {fila[col] or 'No registrado'}" for col in COLUMNAS)


def _coincide_amoblado(valor: str, filtro: str) -> bool:
    """Coincidencia de categoría: Amoblado no coincide con No/Semi-Amoblado."""
    return _normalize(valor).replace("-", " ") == _normalize(filtro).replace("-", " ")


# ============================================
# TOOLS EXPORTABLES
# ============================================
@tool
def buscar_departamentos(
    barrio: str = "",
    tipo: str = "",
    alquiler_maximo: Optional[float] = None,
    habitaciones_minimas: Optional[int] = None,
    banos_minimos: Optional[int] = None,
    cocheras_minimas: Optional[int] = None,
    metros_minimos: Optional[float] = None,
    estado_amoblado: str = "",
    limite: int = 10,
) -> str:
    """
    Busca casas, departamentos y kitnets en el catálogo de alquileres de Alpha State.
    Úsala para recomendar inmuebles por zona, tipo, presupuesto o características.
    Sin filtros lista el catálogo. Todos los filtros se combinan (AND).
    No consulta pagos de inquilinos, no reserva ni confirma disponibilidad actual.

    Args:
        barrio: Nombre parcial del barrio; ignora mayúsculas y acentos.
        tipo: Tipo parcial, por ejemplo Casa, Departamento o Kitnet.
        alquiler_maximo: Tope mensual en BRL SOLO del alquiler; excluye IPTU y servicios.
        habitaciones_minimas: Mínimo de habitaciones, incluyendo cero si se solicita.
        banos_minimos: Mínimo de baños.
        cocheras_minimas: Mínimo de cocheras.
        metros_minimos: Superficie mínima en metros cuadrados.
        estado_amoblado: Categoría exacta: Amoblado, Semi-Amoblado o No Amoblado.
        limite: Cantidad máxima de resultados, entre 1 y 50.
    """
    print("   Consultando catálogo de inmuebles en Google Sheets")
    try:
        if not 1 <= limite <= 50:
            return "El límite debe estar entre 1 y 50."
        numeric_filters = (
            ("Alquiler Mensual (BRL)", alquiler_maximo, True),
            ("Habitaciones", habitaciones_minimas, False),
            ("Baños", banos_minimos, False),
            ("Cocheras", cocheras_minimas, False),
            ("Metros Cuadrados", metros_minimos, False),
        )
        if any(value is not None and (value < 0 or _parse_amount(value) is None)
               for _, value, _ in numeric_filters):
            return "Los filtros numéricos deben ser finitos y no negativos."
        if estado_amoblado and not any(_coincide_amoblado(estado_amoblado, category)
                for category in ("Amoblado", "Semi-Amoblado", "No Amoblado")):
            return "Estado amoblado válido: Amoblado, Semi-Amoblado o No Amoblado."
        matches = []
        for row in _cargar_datos():
            if barrio and _normalize(barrio) not in _normalize(row["Barrio"]):
                continue
            if tipo and _normalize(tipo) not in _normalize(row["Tipo"]):
                continue
            if estado_amoblado and not _coincide_amoblado(row["Estado Amoblado"], estado_amoblado):
                continue
            accepted = True
            for col, threshold, maximum in numeric_filters:
                if threshold is None:
                    continue
                value = _parse_amount(row[col])
                if value is None or (value > threshold if maximum else value < threshold):
                    accepted = False
                    break
            if accepted:
                matches.append(row)
        if not matches:
            return "No encontré inmuebles con esos filtros. Pide autorización para ampliar la búsqueda."
        parts = [f"Encontrados {len(matches)} inmuebles; mostrando {min(limite, len(matches))}."]
        parts.extend(_formatear_inmueble(row) for row in matches[:limite])
        parts.append("Importes en BRL. Alquiler e IPTU son conceptos separados. "
                     "Agua / SANASA describe la modalidad, no un importe. "
                     "El catálogo no confirma disponibilidad actual ni permite reservas.")
        return "\n\n".join(parts)
    except Exception as e:
        return f"Error al consultar inmuebles en Google Sheets: {e}"


@tool
def consultar_detalle_departamento(id_inmueble: str) -> str:
    """
    Consulta todas las características de un inmueble por su ID exacto (ejemplo BH-002).
    Sirve para casas, departamentos y kitnets. Ignora mayúsculas y espacios exteriores.
    Si no se conoce el ID, usa primero buscar_departamentos; nunca adivines un inmueble.
    No consulta pagos de inquilinos ni confirma disponibilidad o reservas.

    Args:
        id_inmueble: ID completo del catálogo, por ejemplo BH-001.
    """
    print(f"   Consultando inmueble: '{id_inmueble}'")
    try:
        ident = _normalize(id_inmueble)
        if not ident:
            return "Indica el ID del inmueble; usa buscar_departamentos si no lo conoces."
        matches = [row for row in _cargar_datos() if _normalize(row["ID Inmueble"]) == ident]
        if not matches:
            return f"No encontré el inmueble '{id_inmueble}'. Confirma su ID o busca en el catálogo."
        if len(matches) > 1:
            return "El ID está duplicado en la hoja. Solicita revisión a un asesor; no asumas una ficha."
        return (_formatear_inmueble(matches[0]) + "\n\nImportes en BRL. Alquiler e IPTU "
                "son separados; Agua / SANASA indica modalidad, no monto. "
                "La disponibilidad actual debe confirmarse con un asesor.")
    except Exception as e:
        return f"Error al consultar inmuebles en Google Sheets: {e}"

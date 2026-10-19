"""
RAG con Qdrant — los 4 pasos de siempre, pero apuntando al Qdrant del VPS.

A diferencia de RAG-con-Qdrant-para-Textos-Amazon y RAG-con-Qdrant-para-Imagenes,
que usan el contenedor local de RAG-Servidor-Qdrant, este script se conecta al
servidor Qdrant que tenemos desplegado en el VPS. La única diferencia real está
en el Paso 4: el cliente se construye con url + api_key en lugar de localhost.

Configuración previa: copiar .env.example a .env y rellenar QDRANT_URL,
QDRANT_API_KEY y OPENAI_API_KEY.

Ejecutar:
    python rag.py
"""

import os
import sys

# Paso 1: Elección de la Técnica de DocumentLoader
from langchain_community.document_loaders import PyPDFLoader

# Paso 2: Elección de Técnica de Splitting
from langchain_text_splitters import RecursiveCharacterTextSplitter

# Paso 4: VectorStore
# Patrón de: docs.langchain.com/oss/python/langchain/knowledge-base
from langchain_qdrant import QdrantVectorStore
from qdrant_client.models import Distance, VectorParams

from dotenv import load_dotenv

from validacion_nombre_tenant_id import validar_qdrant

# application/ al path: contiene vector_store.py
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "application"))

# Paso 3: el modelo de embeddings y la colección NO se definen acá.
# Vienen de vector_store.py, la fuente única que también usa la tool de consulta.
from vector_store import COLLECTION_NAME, MODELO_EMBEDDING, get_client, get_embedding_model

load_dotenv()

# ======================================= Configuración =========================================
# Todo lo parametrizable vive acá arriba: se lee de un vistazo y se cambia en un
# solo sitio, sin bucear en la lógica.

# Paso 1 — anclado a __file__: el script corre igual desde cualquier directorio
RUTA_PDF = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "Base_de_Conocimiento",
    "Base de Conocimiento - Alpha State.pdf",
)

# Paso 2
TAMANO_CHUNK = 500
SOLAPAMIENTO_CHUNK = 200

# Pasos 3 y 4 (MODELO_EMBEDDING y COLLECTION_NAME) se importan de vector_store.py
QDRANT_URL = os.getenv("QDRANT_URL")


def verificar_configuracion() -> None:
    """Corta al arrancar si la configuración está mal.

    Va antes del Paso 1 a propósito: si esperáramos al Paso 4, el script ya
    habría leído el PDF y gastado una llamada de embeddings en OpenAI para
    morir después en un error de configuración.
    """
    if not QDRANT_URL:
        raise ValueError(
            "Falta QDRANT_URL. Copiá .env.example a .env y poné la URL del Qdrant del VPS."
        )

    if not os.getenv("OPENAI_API_KEY"):
        raise ValueError("Falta OPENAI_API_KEY en el .env.")

    if not os.path.exists(RUTA_PDF):
        raise FileNotFoundError(f"No se encontró el PDF: {RUTA_PDF}")

    validacion = validar_qdrant(COLLECTION_NAME)
    if not validacion.ok:
        raise ValueError(f"Nombre de colección inválido: {validacion.motivos}")


if __name__ == '__main__':
    verificar_configuracion()

    #=================================== Paso 1: Document Loader =======================================
    loader = PyPDFLoader(RUTA_PDF)
    documentos = loader.load()
    print(f"Paso 1 — Cargadas {len(documentos)} páginas de {RUTA_PDF}")

    #======================================= Paso 2: Chunking ===========================================
    text_splitter = RecursiveCharacterTextSplitter(
        chunk_size=TAMANO_CHUNK,
        chunk_overlap=SOLAPAMIENTO_CHUNK,
    )
    chunks = text_splitter.split_documents(documents=documentos)
    print(f"Paso 2 — El documento se partió en {len(chunks)} chunks")

    #========== Paso 3: Embeddings - Cargamos el Modelo de Embeddings para convertir los Chunks ==========
    embedding_model = get_embedding_model()

    # El tamaño del vector lo dicta el modelo, no lo escribimos a mano: así el
    # script sigue funcionando si mañana cambiamos de modelo de embeddings.
    vector_size = len(embedding_model.embed_query("texto de muestra"))
    print(f"Paso 3 — {MODELO_EMBEDDING} listo, {vector_size} dimensiones por vector")

    #================= Paso 4: VectorStore - Llevamos los Embeddings al Qdrant del VPS ==================
    # Acá está la diferencia con los otros proyectos: en vez de QdrantClient("localhost")
    # apuntamos al servidor remoto, que sí exige api_key.
    #
    # port=None es obligatorio: si no se pasa, qdrant-client le pega :6333 a la
    # URL por su cuenta y el intento muere con "Connection refused", porque el
    # proxy del VPS (EasyPanel) publica Qdrant en el 443 de https, no en el 6333.
    client = get_client()

    if not client.collection_exists(COLLECTION_NAME):
        client.create_collection(
            collection_name=COLLECTION_NAME,
            vectors_config=VectorParams(size=vector_size, distance=Distance.COSINE),
        )
        print(f"Paso 4 — Colección '{COLLECTION_NAME}' creada en el VPS")
    else:
        print(f"Paso 4 — La colección '{COLLECTION_NAME}' ya existía, se le agregan los chunks")

    vectorstore = QdrantVectorStore(
        client=client,
        collection_name=COLLECTION_NAME,
        embedding=embedding_model,
    )
    vectorstore.add_documents(documents=chunks)

    total = client.count(COLLECTION_NAME).count
    print(f"\n✓ Ingesta completa en {QDRANT_URL}")
    print(f"  Colección '{COLLECTION_NAME}': {total} vectores")

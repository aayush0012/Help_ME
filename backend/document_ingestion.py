import os
import hashlib
import time
from dotenv import load_dotenv
from langchain_community.document_loaders import PyPDFLoader
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_chroma import Chroma
from langchain_huggingface import HuggingFaceEndpointEmbeddings
from langchain_core.documents import Document

load_dotenv()

CHUNK_SIZE = 1000
CHUNK_OVERLAP = 200
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PERSIST_DIR = os.path.join(BASE_DIR, "chroma_db")
EMBED_BATCH_SIZE = 100

def partition_document(file_path: str):
    if not os.path.exists(file_path):
        raise FileNotFoundError(f"PDF not found at: {file_path}")

    print(f"Loading '{file_path}' with PyPDFLoader...")
    start = time.time()
    try:
        loader = PyPDFLoader(file_path)
        elements = loader.load()
    except Exception as e:
        raise RuntimeError(f"Failed to load PDF '{file_path}': {e}") from e

    elapsed = time.time() - start
    print(f"Loaded in {elapsed:.1f}s — Pages: {len(elements)}")
    return elements

def chunk_document(elements):
    text_splitter = RecursiveCharacterTextSplitter(
        chunk_size=CHUNK_SIZE,
        chunk_overlap=CHUNK_OVERLAP
    )
    chunks = text_splitter.split_documents(elements)
    return chunks

def process_chunks(chunks, source_name):
    documents = []
    print("Total chunks:", len(chunks))

    for i, chunk in enumerate(chunks):
        # Extract page number (pypdf is 0-indexed, let's make it 1-indexed for display)
        page = chunk.metadata.get("page", 0) + 1
        
        # Ensure it has sufficient content
        if len(chunk.page_content.strip()) < 10:
            print(f"Skipping empty chunk {i}")
            continue

        doc = Document(
            page_content=chunk.page_content,
            metadata={
                "source": source_name,
                "pages": str(page),
                "chunk_index": i,
            },
        )
        documents.append(doc)

    print("Processed docs:", len(documents))
    return documents

def make_doc_id(doc: Document) -> str:
    key = f"{doc.metadata.get('source')}::{doc.page_content}"
    return hashlib.sha256(key.encode("utf-8")).hexdigest()

def create_vectorstore(documents):
    # Retrieve the API Token
    hf_token = os.getenv("HUGGINGFACEHUB_API_TOKEN") or os.getenv("HF_TOKEN")
    if not hf_token:
        print("Warning: HUGGINGFACEHUB_API_TOKEN is not set. Cloud embedding calls might fail.")

    embeddings = HuggingFaceEndpointEmbeddings(
        model="sentence-transformers/all-MiniLM-L6-v2",
        huggingfacehub_api_token=hf_token
    )

    vectorstore = Chroma(
        persist_directory=PERSIST_DIR,
        embedding_function=embeddings,
    )

    ids = [make_doc_id(doc) for doc in documents]

    print(f"Inserting {len(documents)} documents in batches of {EMBED_BATCH_SIZE}...")

    for start in range(0, len(documents), EMBED_BATCH_SIZE):
        end = start + EMBED_BATCH_SIZE
        batch_docs = documents[start:end]
        batch_ids = ids[start:end]

        vectorstore.add_documents(documents=batch_docs, ids=batch_ids)
        print(f"  Inserted {min(end, len(documents))}/{len(documents)}")

    return vectorstore

if __name__ == "__main__":
    file_path = os.path.join("docs", "rag.pdf")
    source_name = os.path.basename(file_path)

    try:
        print("Loading PDF...")
        elements = partition_document(file_path)

        print("Creating chunks...")
        chunks = chunk_document(elements)

        print("Processing chunks...")
        processed_documents = process_chunks(chunks, source_name)

        if not processed_documents:
            print("No documents produced from this PDF — nothing to ingest.")
        else:
            print("Generating embeddings and storing vectors...")
            vectorstore = create_vectorstore(processed_documents)
            print("Ingestion completed")

    except FileNotFoundError as e:
        print(f"File error: {e}")
    except RuntimeError as e:
        print(f"Processing error: {e}")
    except Exception as e:
        print(f"Unexpected error during ingestion: {e}")
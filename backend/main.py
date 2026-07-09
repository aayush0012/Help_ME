import os
import shutil
import traceback
from fastapi import FastAPI, UploadFile, File, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel
from langchain_groq import ChatGroq
from document_ingestion import (
    partition_document,
    chunk_document,
    process_chunks,
    create_vectorstore,
)

from langchain_chroma import Chroma
from langchain_huggingface import HuggingFaceEndpointEmbeddings
from dotenv import load_dotenv

# Load environment variables
load_dotenv()


app = FastAPI()

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
UPLOAD_FOLDER = os.path.join(BASE_DIR, "uploads")
PERSIST_DIR = os.path.join(BASE_DIR, "chroma_db")
frontend_dist_path = os.path.abspath(os.path.join(BASE_DIR, "../frontend/dist"))
SCORE_THRESHOLD = 1.0
TOP_K = 5

os.makedirs(UPLOAD_FOLDER, exist_ok=True)

# Configure CORS dynamically
allowed_origins = [
    "http://localhost:5173",
    "http://127.0.0.1:5173",
    "http://localhost:5174",
    "http://127.0.0.1:5174",
]
cors_env = os.getenv("CORS_ALLOWED_ORIGINS")
if cors_env:
    if cors_env.strip() == "*":
        allowed_origins = ["*"]
    else:
        allowed_origins = [origin.strip() for origin in cors_env.split(",") if origin.strip()]

app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Lazy model initialization getters to prevent startup crash on missing API keys
def get_llm():
    api_key = os.getenv("GROQ_API_KEY")
    if not api_key:
        raise HTTPException(
            status_code=500,
            detail="GROQ_API_KEY environment variable is not set. Please configure it in your settings."
        )
    return ChatGroq(
        model="llama-3.3-70b-versatile",
        api_key=api_key,
    )

def get_embeddings():
    hf_token = os.getenv("HUGGINGFACEHUB_API_TOKEN") or os.getenv("HF_TOKEN")
    if not hf_token:
        raise HTTPException(
            status_code=500,
            detail="HUGGINGFACEHUB_API_TOKEN or HF_TOKEN environment variable is not set. Please configure it in your settings."
        )
    return HuggingFaceEndpointEmbeddings(
        model="sentence-transformers/all-MiniLM-L6-v2",
        huggingfacehub_api_token=hf_token
    )


class ChatRequest(BaseModel):
    question: str


@app.get("/")
def home():
    index_file = os.path.join(frontend_dist_path, "index.html")
    if os.path.exists(index_file):
        return FileResponse(index_file)
    return {"message": "RAG Backend Running"}


@app.post("/upload")
async def upload_pdf(file: UploadFile = File(...)):
    try:
        print("1 Upload started")

        if not file.filename.lower().endswith(".pdf"):
            raise HTTPException(status_code=400, detail="Only PDF files are supported")

       
        safe_filename = os.path.basename(file.filename)

        if os.path.exists(PERSIST_DIR):
            shutil.rmtree(PERSIST_DIR, ignore_errors=True)

        print("2 Saving file")

        file_path = os.path.join(UPLOAD_FOLDER, safe_filename)

        with open(file_path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)

        print("3 Partitioning PDF")
        elements = partition_document(file_path)

        print("4 Chunking elements")
        chunks = chunk_document(elements)

        print("5 Processing chunks")
        processed_documents = process_chunks(chunks, source_name=safe_filename)

        if not processed_documents:
            raise HTTPException(
                status_code=422,
                detail="No usable content could be extracted from this PDF",
            )

        print("6 Creating vectorstore")
        create_vectorstore(processed_documents)

        print("7 Done")

        return {
            "message": "PDF processed successfully",
            "chunks_indexed": len(processed_documents),
        }

    except HTTPException:
        raise
    except Exception:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail="Failed to process PDF")


@app.post("/chat")
async def chat(question: str = Query(..., description="The question to ask")):
    question = question.strip()

    if not question:
        raise HTTPException(
            status_code=400,
            detail="Question cannot be empty",
        )

    if not os.path.exists(PERSIST_DIR):
        raise HTTPException(
            status_code=400,
            detail="No document has been ingested yet. Upload a PDF first.",
        )

    vectorstore = Chroma(
        persist_directory=PERSIST_DIR,
        embedding_function=get_embeddings(),
    )

    # Retrieve top-k chunks
    results_with_scores = vectorstore.similarity_search_with_score(
        question,
        k=TOP_K,
    )

    print("=" * 80)
    print("Retrieved Chunks")
    print("=" * 80)

    for i, (doc, score) in enumerate(results_with_scores, start=1):
        print(f"\nChunk {i}")
        print(f"Distance: {score:.4f}")
        print("-" * 40)
        print(doc.page_content[:300])
        print("-" * 40)

    if not results_with_scores:
        return {
            "answer": "Information not found in notes.",
            "sources": [],
        }

    context_parts = []
    sources = []

    for i, (doc, score) in enumerate(results_with_scores, start=1):

        source = doc.metadata.get("source", "unknown")
        pages = doc.metadata.get("pages", "unknown")

        context_parts.append(
            f"[Source {i} - {source}, page(s) {pages}]\n{doc.page_content}"
        )

        sources.append(
            {
                "source": source,
                "pages": pages,
                "distance": round(float(score), 4),
            }
        )

    context = "\n\n".join(context_parts)

    prompt = f"""
You are an academic assistant.

Answer ONLY using the information provided below.

Rules:

1. Use ONLY the provided information.
2. Do NOT use outside knowledge.
3. If the answer exists, answer it clearly.
4. Cite sources inline like [Source 1].
5. If the answer is not present, reply exactly:

Information not found in notes.

CONTEXT:

{context}

QUESTION:

{question}

ANSWER:
"""

    print("=" * 80)
    print("Prompt Sent To LLM")
    print("=" * 80)
    print(prompt)
    print("=" * 80)

    response = get_llm().invoke(prompt)

    return {
        "answer": response.content,
        "sources": sources,
    }


# Serve static files from the built React frontend if it exists
if os.path.exists(frontend_dist_path):
    # Mount the /assets directory for JS/CSS files
    app.mount("/assets", StaticFiles(directory=os.path.join(frontend_dist_path, "assets")), name="assets")

    # Catch-all route to serve index.html or static files for UI pages
    @app.get("/{catchall:path}")
    async def serve_frontend(catchall: str):
        # Don't hijack existing API routes (upload, chat, etc.)
        if catchall.startswith("upload") or catchall.startswith("chat"):
            raise HTTPException(status_code=404, detail="Not Found")

        # Try to serve requested file directly if it exists in the build dir
        file_path = os.path.join(frontend_dist_path, catchall)
        if os.path.exists(file_path) and os.path.isfile(file_path):
            return FileResponse(file_path)

        # Fallback to SPA index.html
        index_file = os.path.join(frontend_dist_path, "index.html")
        if os.path.exists(index_file):
            return FileResponse(index_file)
        raise HTTPException(status_code=404, detail="Frontend build index.html not found")
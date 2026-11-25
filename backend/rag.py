"""LangChain PDF ingestion, hybrid retrieval, grounded generation, and evaluation."""
from __future__ import annotations

import hashlib
import io
import json
from pathlib import Path
import re

from flask import current_app
from langchain_core.documents import Document
from langchain_openai import ChatOpenAI, OpenAIEmbeddings
from langchain_text_splitters import RecursiveCharacterTextSplitter
from pypdf import PdfReader

from .prompts import CHAIN_OF_THOUGHT, STANDARD, TOT_CANDIDATES, TOT_SELECT

VECTOR_NAMESPACE = "finwell-v1"
_SPLITTER = RecursiveCharacterTextSplitter(chunk_size=1100, chunk_overlap=180, add_start_index=True)


def _embeddings():
    key = current_app.config["OPENAI_API_KEY"]
    if not key:
        raise RuntimeError("OPENAI_API_KEY is not configured")
    return OpenAIEmbeddings(
        model=current_app.config["OPENAI_EMBEDDING_MODEL"],
        dimensions=current_app.config["OPENAI_EMBEDDING_DIMENSIONS"],
        api_key=key,
    )


def _chat_model(temperature=0.1):
    if not current_app.config["OPENAI_API_KEY"]:
        raise RuntimeError("OPENAI_API_KEY is not configured")
    return ChatOpenAI(
        model=current_app.config["OPENAI_CHAT_MODEL"],
        temperature=temperature,
        max_retries=2,
        timeout=40,
        api_key=current_app.config["OPENAI_API_KEY"],
    )


def vector_store():
    cached = current_app.extensions.get("finwell_vector_store")
    if cached is not None:
        return cached
    embedding = _embeddings()
    if current_app.config["PINECONE_API_KEY"] and current_app.config["PINECONE_INDEX"]:
        from langchain_pinecone import PineconeVectorStore
        store = PineconeVectorStore(
            index_name=current_app.config["PINECONE_INDEX"],
            embedding=embedding,
            namespace=VECTOR_NAMESPACE,
        )
    else:
        from langchain_chroma import Chroma
        path = Path(current_app.config["LOCAL_VECTOR_INDEX"]).resolve()
        path.mkdir(parents=True, exist_ok=True)
        store = Chroma(
            collection_name="finwell_support",
            embedding_function=embedding,
            persist_directory=str(path),
        )
    current_app.extensions["finwell_vector_store"] = store
    return store


def _pdf_documents(pdf_bytes: bytes, filename: str, title: str, topic: str, source_id: str):
    reader = PdfReader(io.BytesIO(pdf_bytes), strict=False)
    docs = []
    for page_number, page in enumerate(reader.pages, start=1):
        text = page.extract_text() or ""
        if text.strip():
            docs.append(Document(
                page_content=text,
                metadata={
                    "source_id": source_id,
                    "title": title,
                    "filename": filename,
                    "topic": topic,
                    "page": page_number,
                },
            ))
    if not docs:
        raise ValueError("No readable text was found in this PDF")
    chunks = _SPLITTER.split_documents(docs)
    for number, doc in enumerate(chunks):
        doc.metadata["chunk_id"] = hashlib.sha256(
            f"{source_id}:{doc.metadata.get('page')}:{doc.metadata.get('start_index', number)}".encode()
        ).hexdigest()
    return len(reader.pages), chunks


def index_pdf_bytes(pdf_bytes: bytes, filename: str, title: str, topic: str, source_id: str | None = None):
    sha = hashlib.sha256(pdf_bytes).hexdigest()
    doc_id = source_id or hashlib.sha256(filename.casefold().encode()).hexdigest()[:24]
    page_count, chunks = _pdf_documents(pdf_bytes, filename, title, topic, doc_id)
    store = vector_store()
    ids = [doc.metadata["chunk_id"] for doc in chunks]
    if current_app.config["PINECONE_API_KEY"] and current_app.config["PINECONE_INDEX"]:
        store.delete(filter={"source_id": doc_id})
    else:
        try:
            store.delete(where={"source_id": doc_id})
        except Exception:
            pass
    store.add_documents(chunks, ids=ids)
    return {"source_id": doc_id, "pages": page_count, "chunks": len(chunks), "sha256": sha, "title": title, "filename": filename, "topic": topic}


def ingest_pdf_folder(folder: str | Path, database=None, triggered_by="cli"):
    folder = Path(folder)
    manifest = json.loads((folder.parent / "manifest.json").read_text(encoding="utf-8"))
    all_results, all_chunks = [], []
    for source in manifest["documents"]:
        pdf_path = folder / source["filename"]
        content = pdf_path.read_bytes()
        sha = hashlib.sha256(content).hexdigest()
        pages, chunks = _pdf_documents(content, source["filename"], source["title"], source["topic"], source["id"])
        result = {"source_id": source["id"], "pages": pages, "chunks": len(chunks), "sha256": sha, "title": source["title"], "filename": source["filename"], "topic": source["topic"]}
        all_chunks.extend(chunks)
        all_results.append(result)
    store = vector_store()
    source_ids = [item["id"] for item in manifest["documents"]]
    if current_app.config["PINECONE_API_KEY"] and current_app.config["PINECONE_INDEX"]:
        store.delete(filter={"source_id": {"$in": source_ids}})
    else:
        store.delete(where={"source_id": {"$in": source_ids}})
    store.add_documents(all_chunks, ids=[doc.metadata["chunk_id"] for doc in all_chunks])
    if database is not None:
        for result in all_results:
            _save_document(database, result, triggered_by)
    return all_results


def _save_document(database, result, user_id=None):
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc).isoformat()
    database.execute(
        """INSERT INTO documents(id, filename, title, category, status, page_count, chunk_count, sha256, uploaded_by, created_at, indexed_at)
           VALUES(?,?,?,?,?,?,?,?,?,?,?)
           ON CONFLICT(filename) DO UPDATE SET id=excluded.id, title=excluded.title, category=excluded.category, status='indexed',
           page_count=excluded.page_count, chunk_count=excluded.chunk_count, sha256=excluded.sha256, indexed_at=excluded.indexed_at""",
        (result["source_id"], result["filename"], result["title"], result["topic"], "indexed", result["pages"], result["chunks"], result["sha256"], user_id, now, now),
    )


def retrieve(question: str, top_k=6):
    candidates = vector_store().similarity_search(question, k=max(top_k * 4, 16))
    query_terms = set(re.findall(r"[a-z0-9]{3,}", question.lower()))
    ranked = []
    for rank, document in enumerate(candidates):
        text = document.page_content
        terms = set(re.findall(r"[a-z0-9]{3,}", (document.metadata.get("title", "") + " " + text).lower()))
        overlap = len(query_terms & terms) / max(len(query_terms), 1)
        dense_rank = 1.0 - rank / max(len(candidates), 1)
        score = 0.72 * dense_rank + 0.28 * overlap
        ranked.append((score, document))
    ranked.sort(key=lambda item: item[0], reverse=True)
    chosen, seen = [], set()
    for score, document in ranked:
        key = (document.metadata.get("source_id"), document.metadata.get("page"))
        if key in seen:
            continue
        seen.add(key)
        chosen.append({"document": document, "score": score})
        if len(chosen) == top_k:
            break
    return chosen


def answer_question(question: str, history=None, strategy="standard"):
    references = retrieve(question)
    if not references:
        return {"answer": "I could not find a supporting document for this question. Please contact the bank or lender through its official app or published support channel. For suspected card fraud, block the card using the official channel and report it promptly.", "sources": [], "contexts": []}
    terms = set(re.findall(r"[a-z0-9]{3,}", question.lower()))
    best_overlap = max(
        len(terms & set(re.findall(r"[a-z0-9]{3,}", item["document"].page_content.lower()))) / max(len(terms), 1)
        for item in references
    )
    if best_overlap < 0.02:
        return {"answer": "The indexed references do not contain enough information to answer this reliably. Please check with your bank or lender through its official support channel. If a card or account may be at risk, block it through the official channel and report the issue promptly.", "sources": [], "contexts": []}

    context_lines, sources = [], []
    for index, entry in enumerate(references, start=1):
        doc = entry["document"]
        context_lines.append(f"[{index}] {doc.metadata.get('title', 'Reference')}, page {doc.metadata.get('page', '?')}\n{doc.page_content}")
        sources.append({
            "id": index,
            "title": doc.metadata.get("title", "Reference"),
            "filename": doc.metadata.get("filename", ""),
            "page": doc.metadata.get("page"),
            "topic": doc.metadata.get("topic", ""),
            "score": round(float(entry["score"]), 4),
            "excerpt": doc.page_content[:300].replace("\n", " "),
        })
    context = "\n\n".join(context_lines)
    conversation_history = []
    for turn in (history or [])[-8:]:
        role = turn.get("role")
        if role in {"user", "assistant"}:
            conversation_history.append(("human" if role == "user" else "ai", turn.get("content", "")[:2500]))
    model = _chat_model()
    prompt = CHAIN_OF_THOUGHT if strategy == "cot" else STANDARD
    if strategy == "tot":
        candidate = (TOT_CANDIDATES | model).invoke({"context": context, "question": question}).content
        answer = (TOT_SELECT | model).invoke({"context": context, "question": question, "candidates": str(candidate)[:5000]}).content
    else:
        answer = (prompt | model).invoke({"context": context, "question": question, "history": conversation_history}).content
    if isinstance(answer, list):
        answer = "\n".join(part.get("text", "") if isinstance(part, dict) else str(part) for part in answer)
    return {"answer": str(answer).strip(), "sources": sources, "contexts": [item["document"].page_content for item in references]}


def run_ragas_evaluation(questions):
    """Evaluate retrieval-grounded responses using RAGAS faithfulness/relevancy."""
    from ragas import EvaluationDataset, evaluate
    from ragas.metrics import Faithfulness, ResponseRelevancy

    samples = []
    for question in questions:
        result = answer_question(question, strategy="standard")
        samples.append({"user_input": question, "response": result["answer"], "retrieved_contexts": result["contexts"] or ["No supporting source was retrieved."]})
    dataset = EvaluationDataset.from_list(samples)
    result = evaluate(dataset=dataset, metrics=[Faithfulness(), ResponseRelevancy()], llm=_chat_model(), embeddings=_embeddings())
    frame = result.to_pandas()
    scores = frame.to_dict(orient="records")
    normalized = []
    for record in scores:
        normalized.append({key: (None if value != value else float(value)) if isinstance(value, (int, float)) else value for key, value in record.items()})
    summary = {}
    for key in frame.columns:
        values = [float(value) for value in frame[key].tolist() if isinstance(value, (int, float)) and value == value]
        if values:
            summary[key] = sum(values) / len(values)
    return {"scores": normalized, "summary": summary}

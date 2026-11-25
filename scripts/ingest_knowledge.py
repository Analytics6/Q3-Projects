"""Index all bundled reference PDFs and persist an ingestion run."""
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv
load_dotenv(ROOT / ".env")

from backend.app import app
from backend.database import get_db
from backend.rag import ingest_pdf_folder

with app.app_context():
    database = get_db()
    run_id = str(uuid.uuid4())
    started = datetime.now(timezone.utc).isoformat()
    manifest = json.loads((ROOT / "knowledge_base" / "manifest.json").read_text(encoding="utf-8"))
    filenames = [document["filename"] for document in manifest["documents"]]
    database.execute("INSERT INTO ingestion_runs(id,filenames_json,status,started_at) VALUES(?,?,?,?)", (run_id, json.dumps(filenames), "processing", started))
    database.commit()
    try:
        records = ingest_pdf_folder(ROOT / "knowledge_base" / "pdfs", database=database, triggered_by="cli")
        pages = sum(item["pages"] for item in records)
        chunks = sum(item["chunks"] for item in records)
        database.commit()
        database.execute("UPDATE ingestion_runs SET status='completed',page_count=?,chunk_count=?,finished_at=? WHERE id=?", (pages, chunks, datetime.now(timezone.utc).isoformat(), run_id))
        database.commit()
        print(f"Indexed {len(records)} documents, {pages} pages, and {chunks} chunks.")
    except Exception as error:
        database.rollback()
        database.execute("UPDATE ingestion_runs SET status='failed',error_message=?,finished_at=? WHERE id=?", (str(error)[:500], datetime.now(timezone.utc).isoformat(), run_id))
        database.commit()
        raise
    finally:
        database.close()

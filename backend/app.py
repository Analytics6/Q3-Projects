import base64
from datetime import datetime, timezone
from functools import wraps
import hashlib
import json
import os
import re
import secrets
import uuid

from dotenv import load_dotenv
from flask import Flask, jsonify, request
from flask_jwt_extended import create_access_token, get_jwt_identity, jwt_required, set_access_cookies, unset_jwt_cookies
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from werkzeug.exceptions import HTTPException
from werkzeug.security import check_password_hash, generate_password_hash

load_dotenv()

from .config import Config
from .database import close_db, get_db, initialize_database
from .rag import answer_question, index_pdf_bytes

limiter = Limiter(key_func=get_remote_address, default_limits=["120 per hour"])


def now_iso():
    return datetime.now(timezone.utc).isoformat()


def user_from_token():
    return get_db().execute("SELECT id, email, name, role, created_at FROM users WHERE id=?", (get_jwt_identity(),)).fetchone()


def admin_required(handler):
    @wraps(handler)
    @jwt_required()
    def wrapped(*args, **kwargs):
        user = user_from_token()
        if not user:
            return jsonify(error={"code": "account_not_found", "message": "Account was not found."}), 401
        if user["role"] != "admin":
            return jsonify(error={"code": "admin_required", "message": "Administrator access is required."}), 403
        return handler(*args, **kwargs)
    return wrapped


def create_app(test_config=None):
    app = Flask(__name__)
    app.config.from_object(Config)
    if test_config:
        app.config.update(test_config)
    if app.config["ENVIRONMENT"] == "production":
        if len(app.config["JWT_SECRET_KEY"] or "") < 32:
            raise RuntimeError("Set JWT_SECRET_KEY to a random value of at least 32 characters")
        if not (app.config["PINECONE_API_KEY"] and app.config["PINECONE_INDEX"]):
            raise RuntimeError("Production requires a persistent Pinecone index for RAG")
        if not (app.config["TURSO_DATABASE_URL"] and app.config["TURSO_AUTH_TOKEN"]):
            raise RuntimeError("Production requires TURSO_DATABASE_URL and TURSO_AUTH_TOKEN for persistent SQLite")
        if not app.config["REDIS_URL"]:
            raise RuntimeError("Production requires REDIS_URL for shared rate limiting")
        if not app.config["OPENAI_API_KEY"]:
            raise RuntimeError("Production requires OPENAI_API_KEY for chat and embeddings")

    from flask_jwt_extended import JWTManager
    JWTManager(app)
    app.config["RATELIMIT_HEADERS_ENABLED"] = True
    limiter.init_app(app)
    app.teardown_appcontext(close_db)

    if app.config["LANGSMITH_API_KEY"]:
        os.environ["LANGSMITH_TRACING"] = "true" if app.config["LANGSMITH_TRACING_ENABLED"] else "false"
        os.environ.setdefault("LANGSMITH_API_KEY", app.config["LANGSMITH_API_KEY"])
        os.environ.setdefault("LANGSMITH_PROJECT", app.config["LANGSMITH_PROJECT"])
        os.environ.setdefault("LANGSMITH_ENDPOINT", app.config["LANGSMITH_ENDPOINT"])

    @app.before_request
    def enforce_request_origin():
        request.request_id = request.headers.get("X-Request-ID", secrets.token_hex(8))[:80]
        if request.method in {"POST", "PUT", "PATCH", "DELETE"}:
            origin = request.headers.get("Origin")
            allowed = {app.config["FRONTEND_ORIGIN"].rstrip("/")}
            if request.host_url:
                allowed.add(request.host_url.rstrip("/"))
            vercel_host = os.getenv("VERCEL_URL", "").strip()
            if vercel_host:
                allowed.add(f"https://{vercel_host}".rstrip("/"))
            if origin and origin.rstrip("/") not in allowed:
                return jsonify(error={"code": "origin_not_allowed", "message": "Request origin is not allowed."}), 403

    @app.after_request
    def response_headers(response):
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Request-ID"] = getattr(request, "request_id", "")
        return response

    @app.errorhandler(HTTPException)
    def http_error(error):
        return jsonify(error={"code": error.name.lower().replace(" ", "_"), "message": error.description}), error.code

    @app.errorhandler(429)
    def rate_limited(_error):
        return jsonify(error={"code": "rate_limited", "message": "Too many requests. Please wait and try again."}), 429

    @app.errorhandler(Exception)
    def unexpected_error(error):
        app.logger.exception("Unhandled API error request_id=%s", getattr(request, "request_id", "unknown"), exc_info=error)
        return jsonify(error={"code": "internal_error", "message": "Something went wrong. Please try again."}, requestId=getattr(request, "request_id", None)), 500

    def payload():
        data = request.get_json(silent=False)
        if not isinstance(data, dict):
            return None
        return data

    def safe_user(row):
        return {"id": row["id"], "name": row["name"], "email": row["email"], "role": row["role"], "createdAt": row["created_at"]}

    def set_session(response, user_id):
        token = create_access_token(identity=user_id)
        set_access_cookies(response, token)
        return response

    @app.get("/api/health")
    def health():
        return jsonify(status="ok", service="finwell-api", database="sqlite", timestamp=now_iso())

    @app.post("/api/auth/register")
    @limiter.limit("5 per hour")
    def register():
        data = payload() or {}
        email = data.get("email", "")
        name = data.get("name", "")
        password = data.get("password", "")
        if not isinstance(email, str) or not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", email.strip()) or len(email) > 254:
            return jsonify(error={"code": "invalid_email", "message": "Enter a valid email address."}), 422
        if not isinstance(name, str) or not 2 <= len(name.strip()) <= 100:
            return jsonify(error={"code": "invalid_name", "message": "Name must contain 2 to 100 characters."}), 422
        if not isinstance(password, str) or not 12 <= len(password) <= 128:
            return jsonify(error={"code": "weak_password", "message": "Use a password between 12 and 128 characters."}), 422
        database = get_db()
        user_id = str(uuid.uuid4())
        try:
            database.execute("INSERT INTO users(id,email,name,password_hash,role,created_at) VALUES(?,?,?,?,?,?)", (user_id, email.strip().lower(), name.strip(), generate_password_hash(password, method="scrypt"), "user", now_iso()))
            database.commit()
        except Exception as error:
            database.rollback()
            if "unique" in str(error).lower():
                return jsonify(error={"code": "email_exists", "message": "An account with this email already exists."}), 409
            raise
        user = database.execute("SELECT * FROM users WHERE id=?", (user_id,)).fetchone()
        return set_session(jsonify(user=safe_user(user)), user_id), 201

    @app.post("/api/auth/login")
    @limiter.limit("8 per minute")
    def login():
        data = payload() or {}
        email = data.get("email", "")
        password = data.get("password", "")
        if not isinstance(email, str) or not isinstance(password, str):
            return jsonify(error={"code": "invalid_credentials", "message": "Email or password is incorrect."}), 401
        user = get_db().execute("SELECT * FROM users WHERE email=? COLLATE NOCASE", (email.strip(),)).fetchone()
        if not user or not check_password_hash(user["password_hash"], password):
            return jsonify(error={"code": "invalid_credentials", "message": "Email or password is incorrect."}), 401
        return set_session(jsonify(user=safe_user(user)), user["id"])

    @app.post("/api/auth/logout")
    @jwt_required()
    def logout():
        from flask_jwt_extended import unset_jwt_cookies
        response = jsonify(ok=True)
        unset_jwt_cookies(response)
        return response

    @app.get("/api/auth/me")
    @jwt_required()
    def me():
        user = user_from_token()
        return (jsonify(user=safe_user(user)), 200) if user else (jsonify(error={"code": "account_not_found", "message": "Account not found."}), 404)

    @app.get("/api/conversations")
    @jwt_required()
    def list_conversations():
        user_id = get_jwt_identity()
        rows = get_db().execute("SELECT id,title,created_at,updated_at FROM conversations WHERE user_id=? ORDER BY updated_at DESC LIMIT 100", (user_id,)).fetchall()
        return jsonify(conversations=[{"id": r["id"], "title": r["title"], "createdAt": r["created_at"], "updatedAt": r["updated_at"]} for r in rows])

    @app.post("/api/conversations")
    @jwt_required()
    def create_conversation():
        data = payload() or {}
        title = data.get("title", "New conversation")
        if not isinstance(title, str) or len(title) > 160:
            return jsonify(error={"code": "invalid_title", "message": "Title must be 160 characters or fewer."}), 422
        conversation_id = str(uuid.uuid4())
        now = now_iso()
        get_db().execute("INSERT INTO conversations(id,user_id,title,created_at,updated_at) VALUES(?,?,?,?,?)", (conversation_id, get_jwt_identity(), title.strip() or "New conversation", now, now))
        get_db().commit()
        return jsonify(conversation={"id": conversation_id, "title": title.strip() or "New conversation", "createdAt": now, "updatedAt": now}), 201

    def get_conversation(conversation_id):
        return get_db().execute("SELECT * FROM conversations WHERE id=? AND user_id=?", (conversation_id, get_jwt_identity())).fetchone()

    def messages_for(conversation_id):
        rows = get_db().execute("SELECT * FROM messages WHERE conversation_id=? ORDER BY created_at ASC LIMIT 200", (conversation_id,)).fetchall()
        return [{"id": r["id"], "role": r["role"], "content": r["content"], "sources": json.loads(r["sources_json"] or "[]"), "createdAt": r["created_at"]} for r in rows]

    @app.get("/api/conversations/<conversation_id>")
    @jwt_required()
    def get_conversation_endpoint(conversation_id):
        conversation = get_conversation(conversation_id)
        if not conversation:
            return jsonify(error={"code": "not_found", "message": "Conversation not found."}), 404
        return jsonify(conversation={"id": conversation["id"], "title": conversation["title"], "createdAt": conversation["created_at"], "updatedAt": conversation["updated_at"]}, messages=messages_for(conversation_id))

    @app.delete("/api/conversations/<conversation_id>")
    @jwt_required()
    def delete_conversation(conversation_id):
        if not get_conversation(conversation_id):
            return jsonify(error={"code": "not_found", "message": "Conversation not found."}), 404
        database = get_db()
        database.execute("DELETE FROM conversations WHERE id=?", (conversation_id,))
        database.commit()
        return jsonify(ok=True)

    @app.get("/api/conversations/<conversation_id>/messages")
    @jwt_required()
    def get_messages(conversation_id):
        if not get_conversation(conversation_id):
            return jsonify(error={"code": "not_found", "message": "Conversation not found."}), 404
        return jsonify(messages=messages_for(conversation_id))

    def extract_question(data):
        question = data.get("content") or data.get("message") or data.get("question")
        return question.strip() if isinstance(question, str) and 2 <= len(question.strip()) <= 4000 else None

    def has_unsafe_secret(text):
        return bool(re.search(r"\b(?:\d[ -]*?){12,19}\b", text) or re.search(r"\b(?:cvv|otp|pin)\s*[:=]\s*\S+", text, re.I))

    def store_message(conversation_id, role, text, sources=None):
        get_db().execute("INSERT INTO messages(id,conversation_id,role,content,sources_json,created_at) VALUES(?,?,?,?,?,?)", (str(uuid.uuid4()), conversation_id, role, text, json.dumps(sources or []), now_iso()))

    @app.post("/api/conversations/<conversation_id>/messages")
    @jwt_required()
    @limiter.limit("30 per hour")
    def send_message(conversation_id):
        conversation = get_conversation(conversation_id)
        if not conversation:
            return jsonify(error={"code": "not_found", "message": "Conversation not found."}), 404
        data = payload() or {}
        question = extract_question(data)
        strategy = data.get("strategy", "standard")
        if strategy not in {"standard", "cot", "tot"}:
            return jsonify(error={"code": "invalid_strategy", "message": "Choose standard, cot, or tot."}), 422
        if not question:
            return jsonify(error={"code": "invalid_message", "message": "Message must contain 2 to 4,000 characters."}), 422
        if has_unsafe_secret(question):
            return jsonify(error={"code": "sensitive_data", "message": "Remove card numbers, CVV, OTPs, and PINs before sending."}), 422
        history = get_db().execute("SELECT role,content FROM messages WHERE conversation_id=? ORDER BY created_at DESC LIMIT 12", (conversation_id,)).fetchall()
        try:
            result = answer_question(question, history=[dict(row) for row in reversed(history)], strategy=strategy)
        except Exception as error:
            app.logger.exception("RAG response failed request_id=%s", request.request_id, exc_info=error)
            return jsonify(error={"code": "assistant_unavailable", "message": "The assistant could not answer right now. Please try again shortly."}), 503
        database = get_db()
        title = conversation["title"]
        if title == "New conversation":
            title = re.sub(r"\s+", " ", question)[:58].strip() or title
        store_message(conversation_id, "user", question)
        store_message(conversation_id, "assistant", result["answer"], result["sources"])
        database.execute("UPDATE conversations SET title=?,updated_at=? WHERE id=?", (title, now_iso(), conversation_id))
        database.commit()
        latest = database.execute("SELECT * FROM messages WHERE conversation_id=? AND role='assistant' ORDER BY created_at DESC LIMIT 1", (conversation_id,)).fetchone()
        return jsonify(message={"id": latest["id"], "role": latest["role"], "content": latest["content"], "sources": json.loads(latest["sources_json"]), "createdAt": latest["created_at"]}, sources=result["sources"])

    @app.post("/api/chat/completions")
    @jwt_required()
    @limiter.limit("30 per hour")
    def one_turn_chat():
        data = payload() or {}
        question = extract_question(data)
        strategy = data.get("strategy", "standard")
        if not question:
            return jsonify(error={"code": "invalid_message", "message": "Message must contain 2 to 4,000 characters."}), 422
        if strategy not in {"standard", "cot", "tot"}:
            return jsonify(error={"code": "invalid_strategy", "message": "Choose standard, cot, or tot."}), 422
        if has_unsafe_secret(question):
            return jsonify(error={"code": "sensitive_data", "message": "Remove card numbers, CVV, OTPs, and PINs before sending."}), 422
        try:
            return jsonify(answer_question(question, strategy=strategy))
        except Exception as error:
            app.logger.exception("RAG response failed request_id=%s", request.request_id, exc_info=error)
            return jsonify(error={"code": "assistant_unavailable", "message": "The assistant could not answer right now. Please try again shortly."}), 503

    @app.get("/api/models")
    @jwt_required()
    def models():
        return jsonify(models=[{"id": app.config["OPENAI_CHAT_MODEL"], "provider": "OpenAI", "type": "LangChain RAG"}], strategies=[{"id": "standard", "name": "Standard"}, {"id": "cot", "name": "Stepwise review"}, {"id": "tot", "name": "Multi-path review"}])

    @app.get("/api/admin/profile")
    @admin_required
    def admin_profile():
        return jsonify(profile=safe_user(user_from_token()), permissions=["knowledge:read", "knowledge:write", "evaluation:run", "integrations:manage"])

    @app.get("/api/admin/overview")
    @admin_required
    def admin_overview():
        database = get_db()
        counts = {}
        for table, key in [("users", "users"), ("conversations", "conversations"), ("messages", "messages"), ("documents", "documents"), ("ingestion_runs", "ingestionRuns"), ("evaluations", "evaluations")]:
            counts[key] = database.execute(f"SELECT COUNT(*) AS n FROM {table}").fetchone()["n"]
        counts["indexedDocuments"] = database.execute("SELECT COUNT(*) AS n FROM documents WHERE status='indexed'").fetchone()["n"]
        counts["indexedChunks"] = database.execute("SELECT COALESCE(SUM(chunk_count),0) AS n FROM documents WHERE status='indexed'").fetchone()["n"]
        recent = database.execute("SELECT id,status,page_count,chunk_count,started_at,finished_at,error_message FROM ingestion_runs ORDER BY started_at DESC LIMIT 8").fetchall()
        return jsonify(metrics=counts, recentRuns=[dict(row) for row in recent])

    @app.get("/api/admin/documents")
    @admin_required
    def admin_documents():
        rows = get_db().execute("SELECT id,filename,title,category,status,page_count,chunk_count,sha256,uploaded_by,created_at,indexed_at FROM documents ORDER BY created_at DESC LIMIT 500").fetchall()
        return jsonify(documents=[dict(row) for row in rows])

    @app.get("/api/admin/ingestion-runs")
    @admin_required
    def admin_ingestion_runs():
        rows = get_db().execute("SELECT * FROM ingestion_runs ORDER BY started_at DESC LIMIT 100").fetchall()
        result = []
        for row in rows:
            item = dict(row)
            item["filenames"] = json.loads(item.pop("filenames_json"))
            result.append(item)
        return jsonify(runs=result)

    @app.get("/api/admin/evaluations")
    @admin_required
    def admin_evaluations():
        rows = get_db().execute("SELECT * FROM evaluations ORDER BY created_at DESC LIMIT 30").fetchall()
        result = []
        for row in rows:
            result.append({"id": row["id"], "metrics": json.loads(row["metrics_json"]), "questions": json.loads(row["questions_json"]), "rows": json.loads(row["rows_json"]), "createdAt": row["created_at"]})
        return jsonify(evaluations=result)

    def begin_run(filenames, user_id):
        run_id = str(uuid.uuid4())
        database = get_db()
        database.execute("INSERT INTO ingestion_runs(id,filenames_json,status,triggered_by,started_at) VALUES(?,?,?,?,?)", (run_id, json.dumps(filenames), "processing", user_id, now_iso()))
        database.commit()
        return run_id

    def finish_run(run_id, status, pages=0, chunks=0, error=None):
        database = get_db()
        database.execute("UPDATE ingestion_runs SET status=?,page_count=?,chunk_count=?,error_message=?,finished_at=? WHERE id=?", (status, pages, chunks, (str(error)[:500] if error else None), now_iso(), run_id))
        database.commit()

    @app.post("/api/admin/knowledge/ingest")
    @admin_required
    @limiter.limit("20 per hour")
    def upload_knowledge():
        uploads = request.files.getlist("files")
        if not uploads or len(uploads) > 5:
            return jsonify(error={"code": "invalid_upload", "message": "Select between one and five PDF files."}), 422
        invalid = [file.filename for file in uploads if not file.filename or not file.filename.lower().endswith(".pdf")]
        if invalid:
            return jsonify(error={"code": "invalid_file_type", "message": "Only PDF documents are accepted."}), 415
        user = user_from_token()
        filenames = [file.filename[:180] for file in uploads]
        run_id = begin_run(filenames, user["id"])
        results, page_total, chunk_total = [], 0, 0
        try:
            for uploaded in uploads:
                content = uploaded.read(10 * 1024 * 1024 + 1)
                if len(content) > 10 * 1024 * 1024:
                    raise ValueError(f"{uploaded.filename} exceeds the 10 MB per-file limit")
                title = request.form.get("title", "").strip() if len(uploads) == 1 else ""
                title = title or os.path.splitext(uploaded.filename)[0].replace("_", " ")[:160]
                topic = request.form.get("category", "General support").strip()[:80] or "General support"
                indexed = index_pdf_bytes(content, uploaded.filename[:180], title, topic)
                indexed["uploaded_by"] = user["id"]
                from .rag import _save_document
                _save_document(get_db(), indexed, user["id"])
                page_total += indexed["pages"]
                chunk_total += indexed["chunks"]
                results.append({key: indexed[key] for key in ("source_id", "title", "filename", "topic", "pages", "chunks")})
            get_db().commit()
            finish_run(run_id, "completed", page_total, chunk_total)
        except Exception as error:
            get_db().rollback()
            finish_run(run_id, "failed", page_total, chunk_total, error)
            return jsonify(error={"code": "ingestion_failed", "message": "PDF processing failed. Check the document and provider settings.", "runId": run_id}), 422
        return jsonify(runId=run_id, status="completed", pages=page_total, chunks=chunk_total, documents=results), 201

    @app.post("/api/admin/knowledge/reindex")
    @admin_required
    @limiter.limit("4 per hour")
    def reindex_knowledge():
        from pathlib import Path
        root = Path(__file__).resolve().parents[1]
        folder = root / "knowledge_base" / "pdfs"
        manifest = json.loads((folder.parent / "manifest.json").read_text(encoding="utf-8"))
        user = user_from_token()
        filenames = [item["filename"] for item in manifest["documents"]]
        run_id = begin_run(filenames, user["id"])
        try:
            from .rag import _save_document, index_pdf_bytes
            total_pages, total_chunks = 0, 0
            for source in manifest["documents"]:
                result = index_pdf_bytes((folder / source["filename"]).read_bytes(), source["filename"], source["title"], source["topic"], source_id=source["id"])
                _save_document(get_db(), result, user["id"])
                total_pages += result["pages"]
                total_chunks += result["chunks"]
            get_db().commit()
            finish_run(run_id, "completed", total_pages, total_chunks)
            return jsonify(runId=run_id, status="completed", documents=len(filenames), pages=total_pages, chunks=total_chunks)
        except Exception as error:
            get_db().rollback()
            finish_run(run_id, "failed", error=error)
            app.logger.exception("Knowledge reindex failed request_id=%s", request.request_id, exc_info=error)
            return jsonify(error={"code": "reindex_failed", "message": "Knowledge base indexing failed. Check provider settings and the ingestion run."}), 503

    @app.delete("/api/admin/documents/<source_id>")
    @admin_required
    def archive_document(source_id):
        database = get_db()
        row = database.execute("SELECT id FROM documents WHERE id=?", (source_id,)).fetchone()
        if not row:
            return jsonify(error={"code": "not_found", "message": "Document not found."}), 404
        store = __import__("backend.rag", fromlist=["vector_store"]).vector_store()
        if app.config["PINECONE_API_KEY"] and app.config["PINECONE_INDEX"]:
            store.delete(filter={"source_id": source_id})
        else:
            store.delete(where={"source_id": source_id})
        database.execute("UPDATE documents SET status='archived',chunk_count=0 WHERE id=?", (source_id,))
        database.commit()
        return jsonify(ok=True)

    @app.post("/api/admin/evaluations/ragas")
    @admin_required
    @limiter.limit("3 per hour")
    def ragas_evaluate():
        data = payload() or {}
        questions = data.get("questions")
        if not isinstance(questions, list) or not 1 <= len(questions) <= 4 or any(not isinstance(q, str) or not 3 <= len(q) <= 500 for q in questions):
            return jsonify(error={"code": "invalid_evaluation", "message": "Provide between one and four questions (3–500 characters each)."}), 422
        try:
            from .rag import run_ragas_evaluation
            result = run_ragas_evaluation(questions)
            evaluation_id = str(uuid.uuid4())
            get_db().execute("INSERT INTO evaluations(id,metrics_json,rows_json,questions_json,created_by,created_at) VALUES(?,?,?,?,?,?)", (evaluation_id, json.dumps(result["summary"]), json.dumps(result["scores"], default=str), json.dumps(questions), user_from_token()["id"], now_iso()))
            get_db().commit()
            return jsonify(evaluationId=evaluation_id, provider="RAGAS", metrics=result["summary"], rows=result["scores"])
        except Exception as error:
            app.logger.exception("RAGAS evaluation failed request_id=%s", request.request_id, exc_info=error)
            return jsonify(error={"code": "ragas_unavailable", "message": "RAGAS evaluation could not run. Check the installed evaluation dependencies and model settings."}), 503

    def mlflow_request(method, path, body=None, params=None):
        import requests
        base = app.config["MLFLOW_TRACKING_URI"].rstrip("/")
        if not base.startswith(("https://", "http://")):
            raise RuntimeError("MLFLOW_TRACKING_URI must be an HTTP(S) tracking server URL")
        auth = None
        username, password = app.config["MLFLOW_TRACKING_USERNAME"], app.config["MLFLOW_TRACKING_PASSWORD"]
        headers = {"Content-Type": "application/json"}
        if username and password:
            encoded = base64.b64encode(f"{username}:{password}".encode()).decode()
            headers["Authorization"] = f"Basic {encoded}"
        response = requests.request(method, f"{base}/api/2.0/mlflow/{path}", json=body, params=params, headers=headers, timeout=15, auth=auth)
        response.raise_for_status()
        return response.json()

    @app.get("/api/admin/mlflow/status")
    @admin_required
    def mlflow_status():
        if not app.config["MLFLOW_TRACKING_URI"]:
            return jsonify(connected=False, message="Set MLFLOW_TRACKING_URI to connect an MLflow tracking server.")
        try:
            result = mlflow_request("GET", "experiments/get-by-name", params={"experiment_name": app.config["MLFLOW_EXPERIMENT_NAME"]})
            return jsonify(connected=True, experiment=result.get("experiment", {}).get("name", app.config["MLFLOW_EXPERIMENT_NAME"]))
        except Exception as error:
            return jsonify(connected=False, message="MLflow tracking server could not be reached.")

    @app.post("/api/admin/mlflow/runs")
    @admin_required
    @limiter.limit("10 per hour")
    def log_mlflow_run():
        data = payload() or {}
        if not app.config["MLFLOW_TRACKING_URI"]:
            return jsonify(error={"code": "mlflow_not_configured", "message": "Set MLFLOW_TRACKING_URI to connect MLflow."}), 503
        metrics = data.get("metrics", {})
        if not isinstance(metrics, dict) or len(metrics) > 30:
            return jsonify(error={"code": "invalid_metrics", "message": "Metrics must be an object with at most 30 values."}), 422
        try:
            experiment_name = app.config["MLFLOW_EXPERIMENT_NAME"]
            try:
                experiment_id = mlflow_request("GET", "experiments/get-by-name", params={"experiment_name": app.config["MLFLOW_EXPERIMENT_NAME"]}).get("experiment", {}).get("experiment_id")
            except Exception:
                experiment_id = mlflow_request("POST", "experiments/create", {"name": experiment_name}).get("experiment_id")
            created = mlflow_request("POST", "runs/create", {"experiment_id": str(experiment_id), "start_time": int(datetime.now(timezone.utc).timestamp() * 1000), "tags": [{"key": "app", "value": "finwell"}, {"key": "source", "value": "admin-dashboard"}]})
            run = created.get("run", {})
            info = run.get("info", {})
            run_id = info.get("run_id")
            metric_items = []
            for key, value in metrics.items():
                name = re.sub(r"[^a-zA-Z0-9_.-]", "_", str(key))[:250]
                number = float(value)
                if not (number == number and abs(number) != float("inf")):
                    continue
                metric_items.append({"key": name, "value": number, "timestamp": int(datetime.now(timezone.utc).timestamp() * 1000), "step": 0})
            if metric_items:
                mlflow_request("POST", "runs/log-batch", {"run_id": run_id, "metrics": metric_items, "params": [], "tags": []})
            return jsonify(runId=run_id, experimentId=experiment_id, trackingUri=app.config["MLFLOW_TRACKING_URI"]), 201
        except Exception as error:
            app.logger.exception("MLflow log failed request_id=%s", request.request_id, exc_info=error)
            return jsonify(error={"code": "mlflow_error", "message": "The MLflow run could not be logged. Check tracking-server credentials."}), 502

    @app.get("/api/admin/langsmith/traces")
    @admin_required
    def langsmith_traces():
        key = app.config["LANGSMITH_API_KEY"]
        if not key:
            return jsonify(connected=False, traces=[], message="Set LANGSMITH_API_KEY to enable tracing.")
        try:
            from langsmith import Client
            client = Client(api_url=app.config["LANGSMITH_ENDPOINT"], api_key=key)
            runs = client.list_runs(project_name=app.config["LANGSMITH_PROJECT"], is_root=True, limit=25)
            traces = []
            for run in runs:
                traces.append({"id": str(run.id), "name": run.name, "runType": run.run_type, "status": "error" if run.error else "completed", "latencyMs": round((run.end_time - run.start_time).total_seconds() * 1000) if run.end_time and run.start_time else None, "startTime": run.start_time.isoformat() if run.start_time else None})
            return jsonify(connected=True, project=app.config["LANGSMITH_PROJECT"], traces=traces)
        except Exception as error:
            app.logger.exception("LangSmith query failed request_id=%s", request.request_id, exc_info=error)
            return jsonify(connected=False, traces=[], message="LangSmith traces could not be loaded. Check the key and project name."), 502

    @app.get("/api/knowledge/stats")
    @jwt_required()
    def knowledge_stats():
        row = get_db().execute("SELECT COUNT(*) AS documents,COALESCE(SUM(chunk_count),0) AS chunks FROM documents WHERE status='indexed'").fetchone()
        return jsonify(indexed=row["chunks"] > 0, documents=row["documents"], chunks=row["chunks"])

    with app.app_context():
        initialize_database(app)
    return app


app = create_app()

if __name__ == "__main__":
    app.run(host="127.0.0.1", port=int(os.getenv("PORT", "5000")), debug=False)



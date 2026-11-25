# Finwell Cards & Loans Support Assistant

Finwell is an end-to-end retrieval-augmented support assistant for common credit-card, debit-card, home-loan, and personal-loan questions. This repository contains a Flask API, a LangChain RAG service, local SQLite persistence, hosted SQLite-compatible persistence for serverless deployments, an admin API, observability/evaluation integrations, and a 50-document PDF knowledge base.

This guide focuses on backend and operations code. The Next.js UI is a client of the API and is intentionally not covered by the backend learning exercises.

## What is included

- Flask application factory and REST API in **backend/app.py**.
- Configuration and environment validation in **backend/config.py** and startup checks in **backend/app.py**.
- SQLite database schema, connection lifecycle, and Turso/libSQL selection in **backend/database.py**.
- LangChain PDF ingestion, chunking, vector-store selection, retrieval, grounded response generation, and RAGAS scoring in **backend/rag.py**.
- Prompt templates and response strategies in **backend/prompts.py**.
- A Vercel Python Function entry point in **api/index.py**.
- Admin CLI and knowledge-base build/index scripts in **scripts/**.
- Fifty generated PDF reference documents in **knowledge_base/pdfs/**, with catalog metadata in **knowledge_base/manifest.json**.
- API and RAG scenarios for students in **docs/SCENARIO_BASED_BACKEND_QUESTIONS.md**; instructor file/function mappings in **docs/SCENARIO_ANSWER_KEY.md**.

## Architecture

1. A client sends HTTPS requests to **/api/...**.
2. The Flask application validates input, applies authentication/authorization and rate limits, then calls the relevant service.
3. Authentication, conversation history, document metadata, ingestion runs, and evaluation results are stored in SQLite. Local development uses Python sqlite3 and a local file. Vercel production uses Turso/libSQL because function instances do not provide durable local disk.
4. For RAG, LangChain extracts text from PDFs with pypdf, splits text into overlapping chunks, attaches document/page metadata, creates OpenAI embeddings, and writes vectors to Chroma locally or Pinecone in production.
5. A user question is retrieved against the vector store, then reranked with lexical overlap. Selected passages are passed to an OpenAI chat model through LangChain prompt templates. The response includes page-level references or a safe insufficient-evidence fallback.
6. Optional integrations send traces to LangSmith, evaluations to RAGAS, and selected metrics to an MLflow tracking server.

The vector database and relational database have different jobs: SQLite stores users, conversations, documents, and run metadata; Chroma/Pinecone stores embeddings and chunk text for retrieval.

## Repository map

| Path | Responsibility |
|---|---|
| backend/app.py | Flask app factory, route handlers, validation, sessions, authorization, upload and admin workflows |
| backend/config.py | Environment configuration and cookie, database, model, and integration settings |
| backend/database.py | SQLite/libSQL connection, schema, request-scoped database handle, and cleanup |
| backend/rag.py | PDF extraction, chunking, vector indexing, hybrid retrieval, OpenAI calls, RAGAS evaluation |
| backend/prompts.py | Standard, stepwise-review, and multi-path prompt templates |
| api/index.py | Vercel function imports the Flask app |
| scripts/create_admin.py | Creates an administrator through a local/operator CLI |
| scripts/build_knowledge_base.py | Rebuilds the sample reference PDFs and manifest |
| scripts/ingest_knowledge.py | Indexes the bundled corpus and stores an ingestion record |
| knowledge_base/manifest.json | Stable source IDs, document titles, categories, and filenames |
| knowledge_base/pdfs/ | The 50 reference PDFs consumed by ingestion |
| docs/SCENARIO_BASED_BACKEND_QUESTIONS.md | Student-facing backend code-tracing and incident scenarios |
| docs/SCENARIO_ANSWER_KEY.md | Instructor reference for source files, functions, diagnosis, and expected investigation |

## Backend request lifecycle

The create_app() function in **backend/app.py** loads Config, checks required production services, initializes JWT and Flask-Limiter, registers request/response hooks and error handlers, attaches database cleanup, registers routes, and initializes the schema. The module-level app is the WSGI application imported by **api/index.py** and Gunicorn.

For a typical authenticated chat request:

1. The request reaches **/api/conversations/<conversation_id>/messages**.
2. The JWT decorator validates the session cookie and CSRF requirements.
3. get_conversation() scopes the lookup to the signed-in user.
4. extract_question() and has_unsafe_secret() validate the message.
5. answer_question() in **backend/rag.py** retrieves references, builds a prompt, calls the configured OpenAI chat model, and returns the answer and citations.
6. store_message() writes user and assistant messages; the conversation title and updated timestamp are committed.
7. The response contains the assistant message and source citations.

## Authentication and security

- Registration normalizes email addresses and stores Werkzeug scrypt password hashes, never raw passwords.
- JWT access tokens are stored in HttpOnly cookies. Secure cookies are enabled in production; CSRF protection is enabled for state-changing methods.
- Admin routes use admin_required, which reloads the role from the database instead of trusting a role claim supplied by the browser.
- Conversation reads, deletes, and messages are scoped by both conversation ID and authenticated user ID.
- Write requests check the Origin header against configured application origins.
- API responses use safe JSON errors, request IDs, and security headers. The exception handler logs server-side details while returning a generic message.
- Rate limits use memory storage locally. Production startup requires Redis so limits can be shared across function instances.
- User messages containing patterns that resemble payment-card numbers, CVVs, PINs, or OTPs are rejected. This is a protective filter, not a substitute for PCI controls or a certified card-data detector.

Never commit .env, tokens, passwords, customer data, card numbers, CVV, PIN, OTP, or identity-document numbers.

## API surface

All endpoints are under **/api**.

| Method | Endpoint | Access | Purpose |
|---|---|---|---|
| GET | /health | Public | Basic process health |
| POST | /auth/register | Public, rate limited | Create a customer account |
| POST | /auth/login | Public, rate limited | Create a cookie-backed session |
| POST | /auth/logout | Signed in | Clear session cookies |
| GET | /auth/me | Signed in | Return current account profile |
| GET / POST | /conversations | Signed in | List or create conversations |
| GET / DELETE | /conversations/<id> | Signed in, owner-scoped | Read or delete a conversation |
| GET / POST | /conversations/<id>/messages | Signed in, owner-scoped | Read history or send a RAG question |
| POST | /chat/completions | Signed in | One-turn RAG answer |
| GET | /models | Signed in | Return model and prompt strategy labels |
| GET | /knowledge/stats | Signed in | Return indexed document/chunk counts |
| GET | /admin/profile | Admin | Return admin profile and permissions |
| GET | /admin/overview | Admin | Return operational counts and recent ingestion runs |
| GET | /admin/documents | Admin | List document metadata |
| GET | /admin/ingestion-runs | Admin | List processing runs |
| POST | /admin/knowledge/ingest | Admin, rate limited | Validate and process uploaded PDFs |
| POST | /admin/knowledge/reindex | Admin, rate limited | Rebuild vector entries from the bundled manifest |
| DELETE | /admin/documents/<source_id> | Admin | Remove vectors and archive document metadata |
| GET | /admin/evaluations | Admin | List saved evaluation results |
| POST | /admin/evaluations/ragas | Admin, rate limited | Run faithfulness and response-relevancy evaluation |
| GET | /admin/langsmith/traces | Admin | List recent traces when configured |
| GET / POST | /admin/mlflow/status, /admin/mlflow/runs | Admin | Check tracking server and log numeric metrics |

Route handlers are implemented in **backend/app.py**. Data access is implemented in **backend/database.py** and **backend/rag.py**.

## RAG and prompt-engineering flow

### Document processing

**scripts/ingest_knowledge.py** reads **knowledge_base/manifest.json** and calls ingest_pdf_folder() from **backend/rag.py**. For each PDF, the pipeline:

1. Reads bytes and computes a SHA-256 fingerprint.
2. Extracts page text with pypdf. A scanned image-only PDF currently fails when it produces no extractable text; OCR is not included.
3. Uses RecursiveCharacterTextSplitter with configured chunk size and overlap. Each chunk keeps document ID, title, filename, topic, page, and start-index metadata.
4. Derives stable chunk IDs from source ID, page number, and chunk start index.
5. Creates embeddings with OpenAIEmbeddings.
6. Adds documents to Chroma for local work or Pinecone when production credentials are configured.
7. Upserts document metadata and records ingestion status in SQLite.

### Question answering

answer_question() in **backend/rag.py** retrieves candidate passages, calculates a combined dense-rank and lexical-overlap score, selects distinct source pages, constructs context with page labels, and calls a LangChain chain backed by ChatOpenAI. The response is returned with citations; low-evidence questions receive a fallback.

### Prompt strategies

The prompt definitions live in **backend/prompts.py**:

- STANDARD asks for a concise answer grounded in retrieved context and a fallback when context is insufficient.
- CHAIN_OF_THOUGHT asks the model to review evidence in steps while returning only the final user-facing response. Private reasoning is not exposed.
- TOT_CANDIDATES and TOT_SELECT generate and select among answer approaches internally; candidate reasoning is not returned to the customer.

These are prompt strategies, not guarantees of factual correctness. Evaluate retrieval and answer quality, inspect citations, and keep regulated customer decisions under approved human and bank controls.

## Database model

The schema is declared in **backend/database.py**:

- users: account identity, password hash, role, and creation time.
- conversations: owner, title, and timestamps.
- messages: user/assistant content, source JSON, and timestamp.
- documents: filename, topic, status, page/chunk counts, checksum, and indexing metadata.
- ingestion_runs: filenames, status, counters, error, trigger, and start/end times.
- evaluations: RAGAS summaries, row scores, questions, creator, and timestamp.

Local SQLite enables foreign keys, WAL, and a busy timeout. When TURSO_DATABASE_URL is set, connect_database() uses the libSQL driver. Schema is currently initialized with CREATE TABLE IF NOT EXISTS; there is no versioned migration framework yet.

## Local development

### Prerequisites

- Python 3.11 or newer.
- Node.js 20 or newer and npm.
- An OpenAI API key for embeddings/chat; an API key may incur usage charges.
- Optional: Pinecone for a hosted vector index, Redis for shared rate limits, and LangSmith/MLflow/RAGAS integrations.

### Install

1. Copy **.env.example** to **.env**.
2. Set a long random JWT_SECRET_KEY and OPENAI_API_KEY.
3. Install Python requirements with **python -m pip install -r requirements-local.txt**.
4. Install UI dependencies with **npm install**.
5. Create the local admin with **python scripts/create_admin.py**.
6. Ingest the PDFs with **python scripts/ingest_knowledge.py**.

### Run

In one terminal, start Flask with **python -m backend.app**. In another, start Next.js with **npm run dev**. The development rewrite in **next.config.ts** sends /api/* requests from the local UI to Flask at port 5000.

Local mode uses a SQLite file at DATABASE_PATH (default ./data/finwell.sqlite3) and Chroma at LOCAL_VECTOR_INDEX. Do not use the local filesystem database for horizontally scaled production workers.

## Production deployment notes

### Vercel

**vercel.json** routes /api/* to the Python Function at **api/index.py**; Next.js serves the UI. Production requires durable external services for relational persistence, vector search, and rate limiting. Set required environment variables in Vercel project settings and run the admin creation and ingestion scripts against the production services before enabling users. Never store credentials in the repository or Terraform state.

Required production variables include:

- FLASK_ENV=production
- JWT_SECRET_KEY (at least 32 random characters)
- OPENAI_API_KEY
- TURSO_DATABASE_URL and TURSO_AUTH_TOKEN
- PINECONE_API_KEY and PINECONE_INDEX
- REDIS_URL
- FRONTEND_ORIGIN

Optional observability variables include LANGSMITH_API_KEY, LANGSMITH_PROJECT, LANGSMITH_TRACING_ENABLED, MLFLOW_TRACKING_URI, MLFLOW_TRACKING_USERNAME, and MLFLOW_TRACKING_PASSWORD. LangSmith tracing is disabled by default because traces can contain user prompts, retrieved passages, and generated answers. Review bank privacy and retention requirements before enabling it.

### Azure / container deployment

The repository's current primary runtime configuration is Vercel. A container/Kubernetes deployment requires container images, Kubernetes manifests, Azure DevOps pipelines, and Terraform infrastructure modules to be added and reviewed for the target subscription, network topology, and secret-management policy. Do not assume that a successful Vercel deployment proves that an Azure deployment has been provisioned.

## Evaluation and operations

- RAGAS endpoint: POST **/api/admin/evaluations/ragas**. Up to four questions are evaluated and saved in SQLite.
- LangSmith endpoint: GET **/api/admin/langsmith/traces**. It reports disconnected status if no key is configured.
- MLflow status: GET **/api/admin/mlflow/status**.
- MLflow run logging: POST **/api/admin/mlflow/runs** with a JSON object of numeric metrics.
- Ingestion metrics: admin overview and ingestion-run endpoints.

Use synthetic questions and sanitized documents for development. In production, restrict evaluation and trace access to admins and avoid recording secrets or unnecessary customer data.

## Troubleshooting

| Symptom | First places to inspect |
|---|---|
| API returns 500 during startup | create_app() in backend/app.py, then environment values in backend/config.py |
| Login cookie is not accepted | JWT cookie/CSRF settings in backend/config.py and browser request origin |
| Admin route returns 403 | admin_required() in backend/app.py and account role in users |
| Chat returns assistant unavailable | answer_question() in backend/rag.py, OpenAI credentials, vector provider, and server logs keyed by request ID |
| No citation or low retrieval | retrieve() and answer_question() in backend/rag.py; verify ingestion run and source metadata |
| PDF upload fails | /admin/knowledge/ingest in backend/app.py, request-size configuration, PDF text extraction, and provider credentials |
| Local database is locked | connect_database() in backend/database.py, WAL/busy timeout, and long-running transactions |
| RAGAS or MLflow reports disconnected | Relevant route handler in backend/app.py, optional dependencies, endpoint, credentials, and service availability |

## Student exercises

Start with **docs/SCENARIO_BASED_BACKEND_QUESTIONS.md**. Each prompt describes a production-style symptom without naming the source file. For every scenario, students should:

1. Reproduce or reason about the behavior.
2. Find the exact backend source file, function/route, and relevant code block.
3. Explain the request/data path and root cause.
4. Propose a minimal safe correction and a verification plan.
5. Note security, privacy, transaction, cost, and operational trade-offs.

The instructor mapping is in **docs/SCENARIO_ANSWER_KEY.md**. For an assessment, share only the student workbook.

## Known boundaries

- PDF content is generated general guidance, not a bank's contractual terms or account-specific advice. A bank must review the content before customer use.
- PDF OCR, malware scanning, asynchronous ingestion queues, and a versioned database migration system are not included.
- A successful local compile does not confirm third-party credentials or production service availability.
- SQLite is appropriate for local learning. A hosted SQLite-compatible database is used for serverless persistence; high-write workloads may require a managed relational database with a different adapter.
- The API implements baseline protections, but a real bank deployment still needs threat modeling, security/privacy review, monitoring, backups, recovery exercises, and regulatory approval.

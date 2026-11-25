# Finwell Backend Code-Tracing Scenarios

## Student edition

These are code investigation exercises for the Finwell backend. The repository intentionally does not plant a bug for every scenario: some prompts describe a missing safeguard or a design improvement. Trace the existing request or data path before proposing a change.

For each scenario, submit:

1. The exact source file and function, route, or class that owns the behavior.
2. The relevant code block or line range and a short call-flow explanation.
3. The root cause, including whether it is a defect, a configuration issue, a missing control, or a trade-off.
4. A minimal fix or design proposal. Include a code diff for implementation exercises.
5. A verification plan with expected HTTP status, database/vector side effects, and logs/metrics.
6. Security, privacy, performance, reliability, and cost implications where relevant.

Do not put credentials or personal financial data in examples. Use synthetic account and transaction values. The instructor answer key is a separate file named **SCENARIO_ANSWER_KEY.md**.

## A. Flask API, authentication, and authorization

### 1. Registration fails only when email capitalization differs

Two users try to register with Bharath@example.test and bharath@example.test. One gets a generic server error instead of the duplicate-account response. Trace normalization, uniqueness enforcement, exception handling, and transaction state. Identify the code that decides whether the exception is a conflict, then propose a deterministic 409 response.

### 2. A malformed JSON body produces an HTML error page

A client sends a POST request with a truncated JSON body or a text/plain content type. The response is not in the API's standard JSON error format. Trace parsing and Flask error handling. Explain how the API should distinguish unsupported media type, malformed JSON, and a valid non-object JSON value.

### 3. Password reset would be easy to add unsafely

A developer proposes an endpoint that accepts an email and a new password, then updates the account. Find the password storage and input-validation patterns already used by account creation. Describe what must be reused or added so the endpoint cannot store plaintext, leak whether an email exists, or allow weak passwords.

### 4. A user can no longer open a conversation after changing accounts

A customer reports a conversation ID from another account and asks support to retrieve it. Trace every read, write, and delete path for conversation messages. Identify how ownership is enforced and point out any route that would become an insecure direct-object reference if it queried by conversation ID alone.

### 5. Admin access remains after an account role is demoted

An administrator is demoted to a normal user in the database but continues attempting admin API calls with an old session cookie. Trace how the role is obtained for protected routes. Explain what the API should return and whether authorization depends on a role stored in the token or current database state.

### 6. Login works in development but the browser drops the production cookie

Authentication succeeds, but subsequent API requests appear anonymous after deployment. Trace JWT cookie settings, request origin checks, CSRF behavior, and environment-dependent secure-cookie settings. Identify the values an operator should inspect before changing the authentication code.

### 7. A state-changing API request succeeds without the expected CSRF token

A security review asks whether a cross-site POST can use the login cookie to create a conversation or upload a document. Trace the JWT CSRF configuration and state-changing route decorators. Explain how cookie-backed auth, SameSite policy, Origin checks, and CSRF validation work together, and propose a verification approach.

### 8. A customer's password is visible in application logs

A new debug statement is added while diagnosing failed logins and logs the full request body. Find the global error/logging path and authentication handlers. Identify safe fields to log, sensitive fields to redact, and a request-correlation approach that preserves useful diagnostics.

### 9. API rate limits reset whenever a new serverless instance starts

The login endpoint is limited in each process, but an attacker can distribute attempts across multiple deployed instances. Trace limiter initialization and storage configuration. Explain the difference between local development storage and production shared storage, and identify the startup check that should prevent unsafe production configuration.

### 10. A message containing card data reaches the language model

A customer pastes what looks like a payment-card number and an OTP into chat. The backend currently applies a pattern-based rejection before RAG. Trace the validation and explain its limits, including false positives and bypasses. Propose defense-in-depth controls and explain why a regex alone is not a compliance boundary.

### 11. An unexpected exception returns a stack trace to the customer

A downstream vector provider raises an exception during chat. The API must return a generic response while retaining a useful server-side diagnostic. Trace exception handlers and RAG route handling. Identify which request identifier should connect the client error to the server log, and what details must not be returned publicly.

### 12. The upload request is rejected before the per-file limit is reached

An administrator uploads a 6 MB PDF. The route allows files larger than this, but Flask rejects the request first. Trace application-wide request limits and per-file validation. Explain why multipart overhead and aggregate file count matter, then propose consistent total-request and per-file limits.

### 13. Two administrators upload different documents with the same filename

The second PDF replaces the first document's relational metadata, while the vector index may still contain chunks from both source documents. Trace document identity, filename uniqueness, source IDs, and vector deletion/upsert behavior. Propose an identity strategy that distinguishes document versions and keeps vector and relational records consistent.

### 14. One bad PDF causes a multi-file upload to appear fully failed

An administrator uploads three PDFs; the third fails during parsing after the first two have already written vectors. SQLite rolls back, but the vector database may retain earlier chunks. Trace the upload loop, transaction boundaries, and vector-store writes. Propose a job design that records per-file outcomes and compensates or retries safely.

### 15. A user can create a conversation with a blank or oversized title

The API accepts a title field and also generates a title from the first question. Trace validation and persistence in both flows. Identify whitespace, length, and control-character cases to handle and describe how to keep the list view bounded and safe.

## B. SQLite, persistence, and data consistency

### 16. Deleting a conversation leaves messages behind in one environment

Local SQLite cascades child-message deletion, while a hosted database may not. Trace foreign-key declaration and connection initialization for both database providers. Explain how to enforce referential integrity consistently and how to verify that deletion is atomic.

### 17. The app creates tables on startup but a column change breaks a rollout

A new release adds a required column. Some instances start on the old schema and some use the new code. Trace schema initialization and identify the absence or presence of migration versioning. Propose a backward-compatible migration sequence that supports rolling deployment and rollback.

### 18. The first messages keep appearing after a conversation gets long

The conversation has more than 200 messages, but the history endpoint always shows the oldest messages and hides recent ones. Inspect the query ordering, limit, and table indexes. Explain how to fetch the latest page while returning it in display order, and what cursor-pagination design would scale better.

### 19. SQLite reports database is locked under parallel local requests

Several requests write messages and ingestion metadata concurrently. Trace connection scope, commit/rollback behavior, journal mode, timeout, and long-running work. Propose a fix that avoids holding a relational transaction open while waiting on an external LLM or vector provider.

### 20. The Turso deployment has unexpected row object behavior

Code reads query results by column name locally but behaves differently with a remote SQLite-compatible driver. Trace connection creation and row_factory setup. Describe how to test the common database interface and where provider-specific behavior should be normalized.

### 21. The admin overview endpoint becomes expensive with a large dataset

The dashboard requests counts for users, messages, conversations, documents, runs, and evaluations on every load. Trace the SQL and schema indexes. Identify the query patterns that need indexes, caching, or pre-aggregation, and explain how to avoid untrusted table names in dynamic SQL.

### 22. A duplicate ingestion writes a second document row

The same PDF is ingested twice with identical bytes but a changed filename. Trace the document upsert key and SHA-256 handling. Decide whether filename, source ID, or checksum should define identity for this product, and describe the implications for reindexing and audit history.

### 23. Failed vector indexing still shows a successful database document

An indexing operation raises after metadata has been committed, and the admin page says the file is indexed. Trace ordering of vector writes, document upsert, ingestion-run status, and commits. Propose a state machine for uploaded, processing, indexed, failed, and archived documents.

### 24. A delete operation archives metadata but does not remove searchable chunks

An admin archives a document, yet RAG still cites its pages. Trace the vector-store deletion filter and metadata status update. Explain how provider-specific delete semantics and namespace selection should be tested before reporting success.

### 25. The app's readiness endpoint says healthy while the database is unavailable

A deployment is marked ready, but login requests fail because the database is unreachable. Trace the health route and database initialization behavior. Design separate liveness and readiness checks, including which dependencies to check without causing expensive model calls.

### 26. A privacy request asks to erase an account and every associated record

The current API can delete a conversation but does not expose account erasure. Trace foreign-key relationships for users, conversations, and messages, and identify records that reference a user without an enforced foreign key. Propose an audited deletion workflow for relational records and any user-associated vector/log data.

### 27. A user's data appears in a different customer's chat

A regression investigation suspects messages are fetched with a conversation ID but without a user ID filter. Trace conversation lookup and message retrieval. Describe the ownership invariant that every route must preserve and the database-level constraints that can reinforce it.

## C. LangChain, OpenAI, and RAG behavior

### 28. A new PDF is indexed, but no text can be retrieved from it

The ingestion run reports success for a scanned PDF, yet retrieval returns no useful passage. Trace page extraction, empty-text handling, chunk creation, and vector insertion. Explain when OCR is needed and how the ingestion job should label unsupported or zero-text files instead of claiming success.

### 29. Citations point to the wrong page after a document is split

The answer cites a source title but the displayed page is inaccurate. Trace PDF page enumeration, document metadata, chunk splitting, and citation construction. Explain how page numbers should survive chunking and how to verify page-level metadata end to end.

### 30. Chunk overlap increases cost without improving answer quality

Embedding usage is much higher after a chunk-size change. Trace splitter settings, page-level splitting, chunk identifiers, embedding calls, and vector upserts. Propose an experiment for chunk size and overlap using retrieval metrics, token/cost measurements, and representative finance questions.

### 31. The Pinecone index rejects embeddings because the dimensions do not match

The provider returns a vector dimension error after switching embedding models. Trace OpenAI embedding configuration, configured dimensions, Pinecone selection, and index setup assumptions. Explain how to validate dimension compatibility and safely migrate an existing index.

### 32. The same source is embedded repeatedly during reindexing

Repeated reindex jobs create duplicate or stale vectors. Trace stable chunk ID generation, namespace selection, provider-specific deletion filters, and insertion order. Propose an idempotent reindex plan and a recovery method if deletion succeeds but insertion fails.

### 33. Retrieval chooses a semantically close but irrelevant policy passage

The answer uses a passage sharing loan-related words but addressing the wrong product. Trace candidate retrieval, dense ranking, lexical overlap scoring, and distinct-page selection. Explain how metadata filters, product categories, reranking, and evaluation examples could reduce cross-product confusion.

### 34. A short question is rejected by the evidence threshold

The user asks “ATM debit dispute” and gets the insufficient-evidence fallback despite relevant documents being indexed. Trace retrieval and the lexical-overlap threshold. Explain its behavior for short queries, synonyms, and multilingual text, and propose tests before changing the threshold.

### 35. The RAG answer contains a claim not present in retrieved passages

The response sounds confident but the cited pages do not support one key statement. Trace the context construction and model prompt. Propose grounding instructions, citation checks, answer validation, and an evaluation set that measures faithfulness rather than fluency alone.

### 36. A malicious instruction inside an uploaded PDF changes the answer

A document contains text instructing the model to ignore system guidance and reveal secrets. Trace how retrieved text is inserted into the prompt. Explain why retrieved passages are untrusted data, then propose prompt boundaries, document review, injection tests, and output controls.

### 37. The stepwise strategy exposes internal reasoning in a customer response

A prompt template asks the model to reason step by step, and a future change risks returning the reasoning trace. Find the prompt construction and response serialization path. Propose a safer private-analysis pattern that returns concise evidence-based conclusions without exposing hidden reasoning.

### 38. Multi-path answer generation returns candidate drafts to the caller

The ToT-style strategy generates several candidate answers before selecting one. A refactor returns both stages as JSON to the API. Trace the candidate and selection chains, then specify which value should be returned, how context/question inputs are passed, and how to prevent candidate traces from leaking.

### 39. A chat request fails because the OpenAI key is missing, but only after retrieval

The request spends time contacting the vector database before reporting configuration failure. Trace initialization of embeddings and chat models. Propose startup/config validation and a provider health check that fails early without exposing secret values.

### 40. OpenAI throttling creates repeated long waits and duplicate user messages

Under a burst of chat traffic, provider retries and client retries cause extra calls or duplicate history entries. Trace ChatOpenAI retry/timeout settings and message persistence order. Propose bounded retries, idempotency keys, timeouts, backoff, and a user-visible retry policy.

### 41. A model response is a list of content blocks, but the API returns an unreadable value

After a provider/model update, the response content is not a plain string. Trace normalization of the model result before JSON serialization and database storage. Specify supported content forms and propose a typed normalization layer with tests.

### 42. The model uses conversation history in one strategy but ignores it in another

Follow-up questions work with the standard prompt but lose context when the multi-path strategy is selected. Trace history collection and every chain invocation. Decide whether history belongs in retrieval, generation, both, or neither, and define how to limit and sanitize it.

### 43. A question outside the knowledge base receives an invented answer

The vector store returns loosely related results and the model answers anyway. Trace no-result and low-overlap fallbacks. Propose a better confidence policy using retrieval scores, metadata, calibrated thresholds, and a clear fallback without relying on a single arbitrary number.

### 44. User input or PDF text makes the prompt unexpectedly large

A long chat history and several retrieved passages exceed model context or cost budgets. Trace message-length validation, history windowing, top-k retrieval, chunk size, and prompt assembly. Propose explicit token budgeting and safe truncation that preserves source attribution.

## D. Prompt engineering, RAGAS, LangSmith, and MLflow

### 45. RAGAS evaluation succeeds but the score is misleadingly high

The evaluator receives answers and retrieved contexts, but there are no ground-truth answers. Trace sample creation, selected metrics, aggregation, and persistence. Explain what faithfulness and response relevancy can and cannot establish, and design a human-reviewed benchmark with expected references.

### 46. One bad evaluation question fails the entire RAGAS batch

An admin submits several questions and one causes the evaluation pipeline to fail. Trace request validation, sequential answer generation, dataset creation, metric evaluation, and saved-run behavior. Propose per-question status capture, limits, timeout handling, and a clear partial-failure response.

### 47. LangSmith traces contain information that should not leave the bank

Tracing is enabled to diagnose quality, and prompts include chat history and retrieved PDF passages. Trace environment-variable handling and LangSmith client creation. Propose an explicit opt-in, redaction/minimization approach, data retention review, and a safe disconnected mode.

### 48. MLflow logging fails when a metric value is a string or NaN

The route accepts an object named metrics, but one value cannot be converted to a finite float. Trace payload validation, normalization, run creation, and log-batch submission. Specify the accepted metric schema and how to avoid creating empty/orphaned runs.

### 49. Two concurrent requests both create the same MLflow experiment

The first-time MLflow setup intermittently returns a conflict when multiple admins log metrics together. Trace experiment lookup and create-on-missing behavior. Propose race-safe handling for an already-created experiment and a verification flow that does not leak server credentials.

### 50. A production deployment starts without an essential external service

A new instance starts even though a required provider is absent, then fails when a customer logs in or asks a question. Trace production environment checks, database provider selection, vector-store selection, Redis setup, and optional integrations. Classify each dependency as required or optional, and design safe startup/readiness behavior that never logs secret values.

# Operational API contract

The separately started FastAPI operational API is available through `backend.operational_api_main`; keep its routes and request/response shapes stable for the frontend. Authenticated bearer roles are checked per route. The API operates on one configured local SQLite workspace; it does not provide multi-tenant isolation. Never use a customer database in synthetic acceptance tests. Financial writes remain rehearsal/proposal operations; no external posting is performed.

Request bodies are capped at 2,000,000 bytes, including streamed/chunked requests. Source versions are immutable identities: reusing a version with different content is rejected. Amounts are represented as exact decimal strings at the boundary and persisted as integer minor units. Source/evidence records are preserved.

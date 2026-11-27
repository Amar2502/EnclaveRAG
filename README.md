# EnclaveRAG

**Zero-Trust Multi-Tenant Enterprise RAG with Database-Enforced Clearance Control**

Multi-organization Retrieval-Augmented Generation where tenant isolation (`org_id`) and hierarchical "no read-up" clearance levels (`L1`–`L4`) are enforced inside PostgreSQL (`pgvector` + Row-Level Security) before any context reaches an LLM.

See [EnclaveRAG.md](./EnclaveRAG.md) for the full architecture blueprint, database schema, implementation roadmap, and interview guide.

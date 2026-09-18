# 0006. Postgres with pgvector as the single datastore

*Status:* Accepted · *Date:* 2026-09-18

## Context

The system persists four things: the curated knowledge base with provenance
metadata, its embeddings, the minimal student-history schema, and the append-only
audit log. Article 12 requires traceability linking a generated turn to the sources
that produced it.

If embeddings live in a dedicated vector database and the audit log in Postgres, a
turn's evidence spans two systems with no shared transaction. A crash between the
retrieval write and the audit write yields a log entry referencing context that
cannot be resolved — precisely the gap Article 12 exists to close.

## Decision

**PostgreSQL 17 with the `pgvector` extension** as the sole datastore. Embeddings,
KB documents with ingestion metadata (source, version, review status per REQ-KB),
student history, and the audit log are all tables in one database.

An audit record and the retrieval it describes commit in **one transaction**. A turn
is logged or it did not happen; there is no partially-recorded turn.

The audit table is append-only, enforced at the database level: a `BEFORE UPDATE OR
DELETE` trigger raises, and the application role is granted `INSERT` and `SELECT`
only. Immutability is therefore enforced twice — in the model (DEC-0002,
`frozen=True`) and in the schema. An examiner asking "could you have edited the log?"
has a schema-level answer.

## Consequences

**Positive.** Referential integrity between a log entry and its cited sources is a
foreign key, not a convention. One service to run, back up, and document.
`pgvector` handles corpora of this size (thousands of documents) without
difficulty.

**Negative.** `pgvector` trails dedicated vector databases on recall/latency at
large scale and offers fewer indexing strategies. Not a constraint at this corpus
size.

**Rejected — Qdrant / Chroma.** Better pure-vector performance, but they split the
evidence across two systems and forfeit the transactional guarantee above, which is
the property actually being argued (REQ-AUDIT, Article 12).

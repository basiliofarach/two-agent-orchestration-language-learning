# 0012. Encryption at rest by default; plaintext is the exception

*Status:* Accepted · *Date:* 2026-09-21

## Context

The store holds four things (DEC-0006): the curated knowledge base and its
embeddings, the minimal student-history schema, and the append-only audit log.
Two of those are personal data about minors. The audit log keeps the redacted
learner prompt as text, not a digest (DEC-0002, REQ-AUDIT), plus the generated
output before and after checks and any tutor edit. The history schema keeps an
assessed proficiency level per learner.

The controls in place today are **data-minimisation** controls: PII redaction at
the input boundary, the history field allowlist (REQ-HISTORY), `extra="forbid"`
so undeclared fields cannot reach the log, and a retention deadline
(`learner.retain_until`). They bound *what* is written. They say nothing about
who can read it once written. An attacker with the database file, a backup tape,
or the application role sees every redacted prompt and every proficiency
assessment in cleartext. Redaction is not a confidentiality control against that
adversary, and citing it as one would overstate what this prototype proves.

### What the law actually requires

State this precisely, because the weaker claim is the defensible one.

**No EU instrument mandates encryption at rest.** GDPR Art. 32(1) requires
"appropriate technical and organisational measures... including *inter alia as
appropriate*: (a) the pseudonymisation and encryption of personal data."
Encryption is a named example under a risk-based test, weighed in Art. 32(2)
against the state of the art, cost, and the likelihood and severity of risk to
data subjects.

The AI Act does not fill the gap. Art. 15 requires "an appropriate level of
accuracy, robustness and cybersecurity" and resilience against unauthorised
third parties exploiting vulnerabilities; it never mentions encryption or data
at rest. The clause that came closest — Art. 10(5), "state-of-the-art security
and privacy-preserving measures, including pseudonymisation" — was **deleted by
Regulation (EU) 2026/1744** (Digital Omnibus on AI, in force 27 July 2026) and
re-enacted as Art. 4a, which binds only special categories of personal data
processed for bias detection and correction. This system does not process
special-category data for that purpose, so Art. 4a does not apply to it.

**The obligation therefore rests on GDPR Art. 32, and this data profile fails
its risk test without encryption:** personal data about minors, an education
context, per-learner assessed proficiency, and learner prompts retained as
text. Art. 32(2) weighs severity and likelihood of harm; the data subjects are
children, which is the category GDPR Recital 38 singles out for specific
protection. Against that, the cost side of the Art. 32(1) balance is close to
zero here — no schema exists yet (the audit spine is Phase 2), so there is no
data to re-encrypt and no backfill to write. A measure that is cheap, standard,
and available fails the "appropriate" test only if it is useless, and it is not.

**Do not cite AI Act Art. 15 as the basis for encryption.** It does not support
the claim, and an examiner who reads the article will find that out.

### Why a blanket default rather than per-field decisions

The alternative is to classify each column as sensitive or not and encrypt the
sensitive ones. That approach fails in a specific, predictable way: the
classification is re-litigated at every new column, the arguments are
unrecorded, and the answer drifts toward "not sensitive" under schedule
pressure. Nothing in the repository would show that the question was ever asked.

Inverting the default fixes the evidence problem, not just the security one. If
encryption is the default and every exemption must be named, then the set of
plaintext columns is **enumerable** — one query returns it, with a reason
attached to each row. "Which learner data is unencrypted, and why?" becomes a
`SELECT` rather than a code review. That is the same move DEC-0006 makes for the
audit log: put the guarantee in the schema so the answer is structural.

## Decision

**Everything persisted is encrypted at rest by default. A column that is not
application-layer encrypted requires a named exemption recorded in the schema,
with a reason.**

Three layers, each with a stated threat model. The layers are not
interchangeable and none is claimed to do another's work.

| Layer | Covers | Defends against | Does **not** defend against |
| --- | --- | --- | --- |
| Volume / TDE | Data directory, WAL, backups | Stolen media, mishandled backup, disposed disk | Any authenticated database session |
| Application-layer envelope | Learner-linked plaintext columns | Compromised application role, rogue DBA, direct table read | An attacker who also holds the KEK |
| Minimisation (existing) | What is written at all | Over-collection; undeclared fields reaching the log | Anyone who can read what *was* written |

PostgreSQL 17 has no native TDE, so layer one is an encrypted volume (LUKS or
cloud disk encryption) or a TDE extension (`pg_tde`, `pg_vault_tde`). It is a
deployment property, recorded in the runbook and asserted at startup, not a
schema property.

### The database holds no key

Layer two is performed by the application, never by the database.
`pgcrypto`'s `pgp_sym_encrypt(data, key)` would put the key in the SQL statement
text, where it reaches `pg_stat_activity`, `pg_stat_statements`, and the server
log. A design whose key material is recoverable from the query log does not
defend against the adversary layer two exists for. **`pgcrypto` is rejected for
this purpose.**

This fixes the division of labour, and it is the point of this record:

- **The application encrypts and decrypts.** It holds the KEK, injected, never
  a module-level constant.
- **The database makes plaintext unrepresentable.** It cannot encrypt without
  holding a key, so its job is to reject any column shaped to hold cleartext.

### Envelope format

A single `bytea` value, self-describing so that rotation is possible:

```text
byte  0        format version (0x01)
bytes 1..16    key id (UUID, 16 bytes)
bytes 17..28   nonce (12 bytes, random per record)
bytes 29..n-17 ciphertext (AES-256-GCM)
last  16 bytes GCM authentication tag
```

Minimum length is 45 bytes, for empty plaintext. Encryption is
non-deterministic: a fresh nonce per record, so identical plaintexts do not
produce identical ciphertexts and equality is not leaked.

### Encrypted

| Table | Column | Reason |
| --- | --- | --- |
| `turn_audit` | `learner_prompt_redacted` | Learner text, retained not digested (DEC-0002) |
| `turn_audit` | `output_before_checks` | Content addressed to an identified minor |
| `turn_audit` | `output_after_checks` | As above |
| `turn_audit` | `human_action.edited_output` | As above, plus tutor attribution |
| `learner_history` | `proficiency_level` | Assessment of a named minor |
| `learner_history` | item outcomes | Per-learner performance record |

### Exempt, with reasons — this list is the whole exemption set

| Column | Reason not encrypted |
| --- | --- |
| `embedding` (pgvector) | ANN search over ciphertext is not possible. Encrypting it forfeits retrieval and with it DEC-0006. Mitigated by layer one plus the fact that the indexed corpus is the vetted KB, not learner text. |
| `record_hash`, `previous_record_hash` | Digests, not plaintext. Encrypting them adds no confidentiality and makes Art. 12 chain verification depend on key availability — trading an evidence guarantee for nothing. |
| `learner_id` | Already a pseudonymous UUID and a cross-table foreign key. Deterministic encryption would be required to preserve joins, and deterministic encryption leaks equality — strictly worse than the pseudonym. |
| KB documents, `source_uri`, `version`, `review_status` | Not personal data. Public curated material with provenance. |
| `policy_version`, `model_revision`, `recorded_at`, `turn_id` | Not personal data. Required in cleartext for the evidence pack and for replay selection. |
| `policy_version.version` | Primary key of that same non-personal identifier, and the foreign-key target for `turn_audit.policy_version`. |
| `gate_evaluation.gate_name`, `decision`, `policy_rule_id` | Non-personal control data. `decision` stays cleartext so the pass/pause/stop/`not_evaluated` check is a database constraint. `reason` is ciphertext because it can quote the learner. |
| `protected_column_exemption.table_name`, `column_name`, `reason`, `decision_ref` | The registry itself. The reason must stay readable in SQL, or the evidence query cannot be answered. |
| `alembic_version.version_num` | Alembic revision id. Not personal data. Required in cleartext so the migration runner can see which revision is applied. |

Any addition to this table is a decision-record amendment, not a code review
comment.

### Schema-level enforcement

The guarantee is enforced where DEC-0006 enforces append-only: in the schema,
so that an examiner has a structural answer rather than a convention.

**1. A domain type, so a ciphertext column cannot hold cleartext.**

```sql
CREATE DOMAIN ciphertext AS bytea
    CONSTRAINT dec0012_envelope_shape CHECK (
        octet_length(VALUE) >= 45      -- version + key id + nonce + tag
        AND get_byte(VALUE, 0) = 1     -- envelope format version
    );
```

A `text` value cannot be written to a `bytea` column without an explicit cast,
and a cast of plaintext fails the constraint. Accidental cleartext is a write
error, not a silent disclosure.

**2. An exemption registry, so plaintext is countable.**

```sql
CREATE TABLE protected_column_exemption (
    schema_name  text NOT NULL DEFAULT 'public',
    table_name   text NOT NULL,
    column_name  text NOT NULL,
    reason       text NOT NULL CHECK (length(trim(reason)) > 0),
    decision_ref text NOT NULL,   -- e.g. 'DEC-0012'
    PRIMARY KEY (schema_name, table_name, column_name)
);
```

Seeded from the exemption table above. The key is **schema-qualified**: the
scan covers every application schema, so a row authorising
`public.turn_audit.record_hash` must not silently authorise
`staging.turn_audit.record_hash`. The evidence-pack question "which learner
data is stored unencrypted, and on whose authority?" is answered by selecting
from this table.

**3. An event trigger, so a future migration cannot quietly add a plaintext
column.**

```sql
CREATE OR REPLACE FUNCTION dec0012_reject_plaintext_columns()
RETURNS event_trigger
LANGUAGE plpgsql AS $$
DECLARE
    offending text;
BEGIN
    SELECT string_agg(
               format('%I.%I.%I (%s)',
                      n.nspname, c.relname, a.attname, t.typname),
               ', '
           )
      INTO offending
      FROM pg_attribute a
      JOIN pg_class c ON c.oid = a.attrelid
      JOIN pg_namespace n ON n.oid = c.relnamespace
      JOIN pg_type t ON t.oid = a.atttypid
      LEFT JOIN pg_type bt ON bt.oid = t.typbasetype
      LEFT JOIN protected_column_exemption e
             ON e.schema_name = n.nspname
            AND e.table_name = c.relname
            AND e.column_name = a.attname
     WHERE n.nspname NOT IN ('pg_catalog', 'information_schema')
       AND n.nspname NOT LIKE 'pg\_toast%'
       AND n.nspname NOT LIKE 'pg\_temp%'
       AND c.relkind = 'r'
       AND a.attnum > 0
       AND NOT a.attisdropped
       -- by oid, not by name: a look-alike domain in another schema must not
       -- shadow public.ciphertext now that every schema is scanned
       AND a.atttypid <> 'public.ciphertext'::regtype
       AND COALESCE(t.typelem, 0) <> 'public.ciphertext'::regtype
       AND COALESCE(bt.typname, t.typname) IN (
           'text', 'varchar', 'bpchar', 'json', 'jsonb', 'bytea',
           '_text', '_varchar', '_bpchar', '_json', '_jsonb', '_bytea'
       )
       AND e.column_name IS NULL;

    IF offending IS NOT NULL THEN
        RAISE EXCEPTION
            'DEC-0012: plaintext column on a stored table: %', offending
            USING HINT = 'Use the ciphertext domain, or register an exemption '
                         'in protected_column_exemption with a reason.';
    END IF;
END;
$$;

CREATE EVENT TRIGGER dec0012_no_plaintext_columns
    ON ddl_command_end
    WHEN TAG IN ('CREATE TABLE', 'ALTER TABLE',
                 'CREATE TABLE AS', 'SELECT INTO')
    EXECUTE FUNCTION dec0012_reject_plaintext_columns();
```

Three properties of that predicate are deliberate, and each was verified
against a live PostgreSQL 17 rather than reasoned about.

**Every schema, not only `public`.** A migration that issues `CREATE SCHEMA
staging` must not gain a cleartext store by doing so. Restricting the scan to
`public` left a permanent, data-bearing blind spot: a table in another schema
was never examined, on any later DDL.

**`CREATE TABLE AS` and `SELECT INTO` are DDL.** Their command tags are not
`CREATE TABLE`, so a tag list naming only `CREATE TABLE` and `ALTER TABLE` let
`CREATE TABLE note AS SELECT 'Oak Street'::text` through. Because the scan
examines the whole catalogue, the leftover column was caught by the *next*
migration instead — reported against a table the current migration never
mentioned. Detecting it late and in the wrong place is close to not detecting
it, so both tags are named.

**The domain is matched by oid, not by name.** Once every schema is scanned,
`CREATE DOMAIN impostor.ciphertext AS text` would satisfy a name-based
exclusion and admit cleartext. `'public.ciphertext'::regtype` identifies the
one real domain, and `typelem` covers its array type.

**Documented limits.** A partitioned parent (`relkind = 'p'`) is not scanned,
so its own declaration is unchecked; every data-bearing partition is
`relkind = 'r'` and is checked, so no row can land in cleartext through one.
Temporary tables live in `pg_temp_*` and are excluded: they are not at rest.
`CREATE EVENT TRIGGER` requires superuser, so the guard assumes a self-hosted
PostgreSQL where migrations run with that right; a managed instance that
forbids event triggers cannot carry this control and would need the CI
catalogue assertion as its only enforcement.

The predicate is every ordinary table in every application schema, not a fixed
name list. A migration that creates a new table is rejected unless each
cleartext-shaped column is the `ciphertext` domain or an exemption registered
against that schema.
Before Alembic is introduced, `EncryptionAtRestSchema` installs the schema
inside a caller-owned transaction; SQL migration scripts are not maintained in
parallel. `tests/integration/test_encryption_at_rest.py` refuses Alembic
revision files until that test has an Alembic `upgrade head` runner. Once
Alembic exists, every test run must apply all revisions to a fresh database
before auditing the live catalogue; revision files must never be skipped.

This is the mechanism that makes the default hold over time. A developer adding
`ALTER TABLE turn_audit ADD COLUMN tutor_note text`, or `CREATE TABLE
session_note (body text)`, gets a migration failure naming this record, and
has two options: use the domain, or write down why not. There is no third
option and no silent one.

**4. Grants unchanged.** The application role keeps `INSERT`/`SELECT` only on
the audit table (DEC-0006). Encryption narrows what that role can *understand*;
it does not widen what it can *do*.

**5. Parameter logging off.** `log_statement = 'none'` and bind parameters
excluded from the log, so ciphertext writes do not defeat themselves. With
`pgcrypto` rejected, no key ever appears in a statement, but the setting closes
the residual path.

### Application-side obligations

A `CipherPort` ABC is authored before any implementation, per DEC-0001, and is
added to that record's port table. It takes and returns bytes: it knows nothing
of turns, learners, or audit records, so a prompt-injected instruction has no
domain surface to reach through it. Two implementations exist — the real
envelope and a test stub — which satisfies the DEC-0001 justification test.

The KEK is injected. Rotation re-encrypts in place, because REQ-EVAL replay
requires a recorded turn to decrypt byte-identically before and after rotation;
a versioned-plaintext scheme would break that. Key material never appears in an
audit record, a log line, or an exception message.

Redaction still runs first. Encrypting unredacted text would satisfy this record
and violate REQ-MINOR: the ciphertext must not contain PII that redaction would
have removed. Layer two protects the redacted prompt; it does not excuse
skipping redaction.

## Consequences

**Positive.** The Art. 32 answer is structural. Plaintext columns are
enumerable from the schema, each with a recorded reason, so the evidence pack
cites a query rather than prose. The default cannot decay silently, because the
event trigger converts decay into a failed migration. Layer boundaries are
stated, so no layer is credited with work it does not do.

**Negative.** Encrypted columns cannot be searched, filtered, or indexed by
value; any query over learner text must decrypt in the application. Accepted —
no such query exists in REQ-AUDIT or REQ-EVAL, both of which select by
`turn_id`, `learner_id` or time, all of which stay cleartext. Key management
becomes an operational dependency: lose the KEK and the audit log is
unreadable, which is why the hash chain is deliberately left outside the
envelope, so tamper-evidence survives a key incident.

**Negative.** The event trigger can be dropped by a superuser, as can the
append-only trigger of DEC-0006. Neither defends against a hostile
administrator, and neither claims to. Both defend against drift, which is the
realistic failure mode.

**Rejected — `pgcrypto` column functions.** Key material transits the SQL
statement and lands in the query log and `pg_stat_activity`, defeating the
adversary model of layer two. Discussed above.

**Rejected — volume encryption alone.** Cheap and worth having, and it is layer
one. On its own it protects against stolen disks and nothing else; every
authenticated session still reads cleartext. Claiming "encrypted at rest" on
that basis alone would overstate the control.

**Rejected — per-field sensitivity classification.** The approach this record
inverts. It produces no artefact, is re-argued per column, and drifts. See
*Why a blanket default* above.

**Rejected — encrypting everything without exception.** Encrypting the pgvector
column ends retrieval; encrypting the hash chain makes Article 12 verification
hostage to key availability. A default with a written, enumerable exemption set
is stronger evidence than an absolute rule that the schema would have to
violate in silence.

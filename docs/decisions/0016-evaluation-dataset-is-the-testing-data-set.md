# 0016. The evaluation dataset is the Article 10(6) testing data set

*Status:* Accepted · *Date:* 2026-11-03

*Amended:* 2026-11-03
([architecture/SIMULATION.md §5.5](../architecture/SIMULATION.md#55-repository-and-licences))
— Licence review and licence terms are enforced at different points. A
`pending` review does not block `freeze`. It blocks publication: a report
is not cited until every source it uses is `confirmed`. A `rejected`
review stops the build. The manifest records the review status at freeze
time. Confirming a review later rewrites the report only, and does not
move `dataset_version`.

*Amended:* 2026-11-03
— Second L1 group (D-3). The FCE text is not in this repository, so the
split is not taken from its counts. Spanish is the largest first language
the learner corpora in DATASET can cite. The persona grid is Spanish
(`es`) and non-Spanish (`ot`), at ages 13 (band 12–14) and 16 (band 15–17).

*Amended:* 2026-11-03
([evaluation/DATASET.md §3.1](../evaluation/DATASET.md#31-d1--knowledge-base-corpus))
— **The knowledge base is built from two published datasets:**

- **CEFR-SP:** sentences on which both professional annotators agree, A1–B2.
- **The CEFR-J Grammar Profile:** one document per grammar item, with its
  examples mined from CEFR-SP by the item's regex.

**Rule 8 is replaced.** A KB document's level comes from the dataset's own
human labels: CEFR-SP annotator agreement, or the Grammar Profile's teachers'
level. It is no longer estimated from CEFR-J coverage. The coverage check
remains, but for measures only.

**Dropped:** CLEAR, public-domain books, Simple English Wikipedia,
OneStopEnglish and the author-written grammar notes. A rough coverage
estimate placed 2,537 of CLEAR's 2,907 Gutenberg excerpts above B2, and 5
at A2.

**Hand-written KB content** is limited to the seeded-fault partition.

**TreeTagger**, which the Grammar Profile regexes require, is a build-time
tool on the harness side. It, the Grammar Profile and CEFR-SP's SCoRE
subset enter with `licence_review: pending`.

Carries out the data half of
[DEC-0015](0015-role-based-simulation-replaces-field-testing.md). The
specification is [evaluation/DATASET.md](../evaluation/DATASET.md). This record
fixes the rules that specification must keep. The specification may change
under these rules; changing a rule needs a new record.

## Context

**The prototype trains no model.** Qwen3-8B and the embedding model are used
as supplied (DEC-0007), and personalisation happens through retrieval. Two
provisions of the Act apply:

- **Art. 10(6):** "for the development of high-risk AI systems not using
  techniques involving the training of AI models, paragraphs 2 to 5 shall
  apply only to the testing data sets".
- **Art. 3(32):** testing data is "data used for providing an independent
  evaluation of the AI system in order to confirm the expected performance"
  of that system.

**The curated knowledge base is operational data.** REQ-KB governs it, and
it is not the object of Art. 10(2).

**Testing data until now.** It has been the eight `ScenarioCatalogue` cases
and one five-sentence document that teaches Spanish greetings
(`PrototypePlan`). That is enough to show the pipeline behaves as specified.
It is not enough to:

- state the suitability and quantity of the data (Art. 10(2)(e))
- examine it for bias (Art. 10(2)(f))
- name its gaps (Art. 10(2)(h))

Nothing in the repository fixes the target language either. The knowledge
base teaches Spanish to English speakers, while the redactor also handles
Spanish self-introductions.

DEC-0015 replaces human participants with role agents. That makes the dataset
the main carrier of the evaluation's validity. A case's expected outcome is
now a property of the data, so the data must be governed before the harness
that reads it is built.

## Decision

**The simulation dataset is the testing data set of this prototype. It is
governed against Art. 10(2)(a)–(h), built only from sources whose licence
permits the use, versioned, and frozen before it is used to report a
result.**

### Scope

| Parameter | Value |
| --- | --- |
| Target language | English |
| Learner ages | 12–17, in two bands: 12–14 and 15–17 |
| Proficiency | CEFR A1–B2. The CEFR-J Wordlist level check stops at B2 |
| First languages | Spanish plus one more group, chosen from what the grounding data supports |

Spanish as a target language is out of scope. A second target language would
double the curation work, and open CEFR resources for Spanish are thin.

The Spanish-greetings document is retired as evaluation content. The eight
REQ-EVAL cases are rewritten in English inside the case plan.

### Components

These are specified in DATASET §3:

| ID | Component | Reaches the system? |
| --- | --- | --- |
| D1 | Knowledge-base corpus, plus a separate seeded-fault partition | Through ingestion; the fault partition only in stress runs |
| D2 | Grounding resources: CEFR-J Wordlist, ELLIPSE, FCE, W&I+LOCNESS | No |
| D3 | Payload bank | Only inside a stimulus |
| D4 | Virtual-pupil persona cards: system prompt plus few-shot examples | No |
| D5 | Tutor role cards, T1–T4 (DEC-0015) | No |
| D6 | Case plan and frozen stimuli | As requests |

### Rules

1. **Admission.**
   - A source enters only with its licence recorded, at source level and on
     every item drawn from it.
   - A licence reading needs review by whoever owns that question before any
     result built on it is published. The status is `pending`, `confirmed`,
     or `rejected`.
     - `pending` does not block `freeze`. Freezing fixes the test split
       before anything is tuned against it, so it does not wait on a
       review. The manifest records each source's status at freeze time.
       A report is `pending` while any source it uses is still `pending`,
       and it is not cited until the status is `confirmed`. Confirming a
       review rewrites the report only. The hashed bytes are unchanged, so
       `dataset_version` does not move.
     - `rejected` stops the build. The source is not admitted. Removing it
       is a new `dataset_version`, and the old version's results are not
       published.
     - Licence terms are a separate check, and they do block `freeze`: a
       non-redistributable item is not placed under `public/`, and an
       excluded source is not admitted.
   - Excluded:
     - Write & Improve 2024: product or service use counts as commercial,
       and published statistics need prior approval.
     - EFCAMDAT: academic researchers only.
     - ai4privacy: non-commercial, and companies need prior discussion.
     - English Vocabulary Profile: its terms could not be verified.
2. **Repository.** The repository is public.
   - Never committed: text under a non-commercial or no-redistribution
     licence. That covers FCE, W&I+LOCNESS, and CLEAR excerpts that are not
     public domain.
   - Fetched at build time, by pinned revision: harmful-content sets such
     as MinorBench and HackAPrompt.
   - Committed:
     - build scripts and manifests
     - aggregates, where their licence permits publication
     - public-domain, CC BY, Apache-2.0 and MIT material, with attribution
3. **Labels come from the policy.** A case's expected outcome is derived from
   the policy version named on the case (REQ-POLICY). Changing a label means
   changing the policy, which means a new policy version.
4. **Splits.**
   - Every payload category, and the benign prompts, are split 30% dev and
     70% test, by seeded shuffle, stratified by source.
   - Detector patterns, prompt templates and thresholds are tuned against
     dev only.
5. **Freezing and versions.**
   - A manifest records:
     - a SHA-256 for every file
     - the role-model digest
     - the policy version
     - source revisions
     - licences, and each source's review status at freeze time
   - The test split's hash is recorded before the first test run.
   - Any change to D3–D6 is a new `dataset_version`. Results from different
     versions are never pooled.
6. **No generated harm.** Role models wrap payloads drawn from published,
   citable sets. They are never asked to write a harmful request.
7. **No personal data.**
   - Personas are synthetic and carry no name or contact detail.
   - Personal data appears only as synthetic payloads from a seeded
     generator.
   - Learner corpora contribute aggregates and CC BY excerpts, never
     identifying text.
8. **Deterministic levels.** A KB document's level is the lowest CEFR level at
   which CEFR-J coverage of its content words reaches 95%. The method is
   recorded on the document.
9. **KB metadata.** `CorpusDocument` gains three fields: `licence`,
   `cefr_level` and `level_method`. Under DEC-0012 the new columns are
   ciphertext; no exemption is proposed.
10. **Seeded faults stay out of the default seed.** The contradictory pair,
    the coverage hole and the poisoned document are ingested only by the
    stress-run seed. A poisoned document carries a canary string whose
    absence is checked by exact match.

The Art. 10(2) checklist is answered in DATASET §9 and kept current with
each `dataset_version`.

## Consequences

**Positive.** The Article 10 claim gets a concrete object. The testing data
set can be named, hashed, versioned, and checked item by item against
Art. 10(2), rather than described.

**Positive.** Bias examination becomes possible. Benign-hold rates can be
compared across level, first-language and age strata (Art. 10(2)(f)). The
caveat stays attached: these strata measure the system's response to
simulated variation, not to real groups.

**Positive.** Licences can be traced. Every reported figure can be traced to
the sources it rests on and the terms they were used under.

**Negative.** Curation and labelling are the work of one person. Deriving
labels from the policy, and planting payloads verbatim, limit how much any
label depends on the author's judgement. They do not remove that dependence.

**Negative.** Known gaps are stated under Art. 10(2)(h):

- No open, CEFR-labelled corpus of Spanish-L1 secondary-school learners was
  found.
- CEFR-J stops at B2.
- The published payload sets are English-only.
- TSCC is unusable until its licence is read.

**Negative.** Several grounding sources are licensed for non-commercial
research only, and TSCC's licence has not been read. Each licence reading is
confirmed before a result built on it is cited. That confirmation gates
citation, not the freeze. FCE, W&I+LOCNESS and TSCC are the non-permissive
sources to review first, so a rejection costs as little as possible.

**Negative.** Two code changes follow:

- Three new `kb_document` columns need a migration. The DEC-0012 event
  trigger will reject them unless they use the `ciphertext` domain.
- Tests that assert on the Spanish-greetings content (`ScenarioCatalogue`,
  the seed tests) change with the English case plan.

**Open, recorded by amendment:**

- the second first-language group, chosen after the FCE counts are inspected
- the TSCC licence decision

**Rejected: treating the knowledge base as the Art. 10 testing data set.** The
knowledge base is operational data the system reads at run time. It already
has its own control in REQ-KB. Evaluating the system needs data the system
has not been shaped around.

**Rejected: English and Spanish as target languages.** Two knowledge bases
and two persona sets would double the curation work. The Spanish half could
not have a deterministic level check of comparable strength.

**Rejected: asking the role model to generate harmful requests.** It would
create harmful material that did not exist before. The label would also
depend on whether the model complied.

**Rejected: an unfrozen, regenerated test set.** If the test set is
regenerated each run, tuning against it cannot be ruled out, and two runs
cannot be compared.

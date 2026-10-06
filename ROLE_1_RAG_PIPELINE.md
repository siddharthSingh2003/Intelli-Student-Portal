# Role 1 — RAG Pipeline Engineer

**You own everything between a raw document and the ranked evidence the LLM sees:**
ingestion, chunking, embeddings, the vector store, the Source Register and the Annex A
precedence engine.

If the panel asks "how does a PDF become an answer with a clause number?" or "two
documents disagree, which one wins?", those are your questions.

| | |
|---|---|
| Folders | `ingestion/`, `docs/` |
| Tests | `tests/test_ingestion.py`, `tests/test_precedence.py` |
| Code size | 9 modules, about 940 lines of Python |
| In the code comments you are | `M1` (Member 1) |
| Works with | Person 2 (rule extractor, SQLite), Person 3 (calls your search and precedence from the workflow, and `ingest_file` from `POST /ingest`), Person 4 (shared contracts, LLM client, evaluation) |

## The team

| Person | Role | Zip |
|---|---|---|
| **1 (you)** | RAG Pipeline Engineer | `person1_rag_pipeline.zip` |
| 2 | Data and Tools Engineer | `person2_data_and_tools.zip` |
| 3 | Orchestration and API Engineer (LangGraph + FastAPI) | `person3_langgraph_and_fastapi.zip` |
| 4 | Platform, UI and Evaluation Lead | `person4_platform_ui_and_evaluation.zip` |

The four zips share no files. Together they are the whole repository. Your zip does not
run on its own: it imports the other three parts.

---

## 1. What is in this zip

| File | What it does |
|---|---|
| `ingestion/loader.py` | Reads PDF, TXT, MD and images into a list of `PageText(page, text, ocr)`. PyMuPDF gives the text layer. A page with fewer than 40 characters is treated as scanned and sent to Tesseract OCR at 300 dpi. pdfplumber extracts tables and appends them as pipe-separated rows (`a \| b \| c`). |
| `ingestion/cleaner.py` | Removes running headers and footers (a short line that appears on more than half the pages of a 3+ page document), page numbers, control characters; rejoins words hyphenated across lines. |
| `ingestion/chunker.py` | Splits pages into chunks. `section` strategy: a chunk never crosses a clause heading, so every chunk knows its exact clause number. `fixed` strategy: a plain sliding window, kept only so the evaluation can compare the two. |
| `ingestion/embeddings.py` | `all-MiniLM-L6-v2` and `bge-small-en-v1.5` (both 384-dimensional, normalised). A `hash` embedder exists only for offline tests. |
| `ingestion/vector_store.py` | ChromaDB `PersistentClient`, cosine space. `add`, `delete_doc`, `search`, `has_doc`, `find_page`. One collection per retrieval configuration. |
| `ingestion/source_register.py` | The Annex B Source Register: one metadata row per document, stored in SQLite, imported from and exported to CSV. |
| `ingestion/metadata_extractor.py` | When an admin uploads a file with only an authority level, this fills in title, issuer, dates, scope and supersession. The LLM proposes each value, code checks it against the document text, and a regex extractor is the fallback. |
| `ingestion/pipeline.py` | `ingest_file()` runs the whole pipeline for one document. `bootstrap()` indexes the register at startup and skips anything already indexed. |
| `ingestion/precedence.py` | The Annex A engine. `resolve_evidence()` ranks retrieved chunks; `resolve_rules()` picks the one rule that applies to a student on a date. |
| `docs/` | 3 PDFs (one real scanned notice, two synthetic circulars), 8 sample text documents and the two `source_register.csv` files. |

---

## 2. How your layer works

### Ingestion, step by step (`pipeline.ingest_file`)

1. **Load** the file into pages (`loader.load_document`).
2. **Clean** the pages (`cleaner.clean_pages`). If no text survives, raise an error (the API turns it into HTTP 422).
3. **Chunk** (`chunker.chunk_pages`). Default: section strategy, 900 characters, 150 overlap. Each chunk text is prefixed with `[DOC_ID | Section 7.2]` and gets the id `DOC_ID::0003`.
4. **Delete** any old chunks with the same `doc_id`, so re-ingesting a document replaces it.
5. **Embed and store** in ChromaDB. Each chunk carries the full document metadata plus `section`, `heading`, `page`, `page_end`.
6. **Register** the document in the Source Register table.
7. **Extract rules** by calling Person 2's `tools.rule_extractor.extract_and_store`. Rule extraction always uses section chunks, so the cited clause is exact.

### Retrieval

`VectorStore.search(query, k)` embeds the query, asks Chroma for the `k` nearest chunks
(default 6) and returns `similarity = 1 - cosine distance`. Person 3's `retrieve_node`
then passes those hits to your `resolve_evidence()`.

### The precedence engine (Annex A)

| Step | Rule | In code |
|---|---|---|
| 1. Applicability | Keep a source only if it is in force on `as_of_date` and covers the student's programme and batch. A future-dated document is not dropped; it goes to `upcoming`. | `applicability()` |
| 2. Supersession | A document that explicitly supersedes `DOC` or `DOC#clause` removes that clause. Only authority level 1 or 2 issuers can supersede. | `supersedes()` |
| 3. Authority | Lower level number wins (1 regulation, 2 circular, 3 notice, 4 FAQ, 5 unofficial). | `resolve_pair()` |
| 4. Recency | Same authority: the later `effective_from` wins. | `resolve_pair()` |
| 5. Unresolved | Same authority, same date, different values: nobody wins. The answer type becomes `conflict_flagged`. | `resolve_pair()` returns `None` |

Scope strings understood by `batch_in_scope`: `ALL`, `2024`, `2023+`, `2021-2023`,
and lists separated by `;` or `,`.

---

## 3. Design decisions you must be able to defend

**Why section-aware chunking instead of fixed windows?**
A fixed window can start in clause 7.1 and end in 7.3. Then the chunk has no single
clause number, the citation is vague, and clause-level supersession
(`SAMPLE-ACAD-REG-2024#7.2`) cannot match. The README reports, for the offline setup
(mock LLM, hash embedder), 25/25 correct with section chunking and 21/25 with fixed
windows. Re-run the evaluation yourself with the real embedders and Ollama before you
quote a number.

**Why is supersession checked against the whole register, not only retrieved chunks?**
The superseding circular might not be in the top 6. If only retrieved chunks were
checked, the old 75% clause would slip through whenever the new circular was not
retrieved. `resolve_evidence` builds its pool from every registered document.

**Why can a level 5 source never win or set a rule?**
Level 5 is unofficial content (forum posts, student uploads). It is kept as evidence
but tagged `informational`, always sorts last, and the rule extractor returns nothing
for it. This is also what makes it safe to let students upload documents.

**Why is the authority level never read from the document?**
A document cannot promote itself. Otherwise anyone could upload a file that says
"this is a regulation". Only an admin chooses the level.

**Why "LLM proposes, code validates" for metadata?**
A wrong effective date or supersession silently changes which rule wins. So a date
must literally appear in the text, a superseded document must exist in the register,
and the document must actually use a word like "supersede" or "replace".

**Why one Chroma collection per configuration?**
The collection name is `chunks_{embedding}_{strategy}_{size}`. Vectors from different
embedding models are not comparable, so they must never share a collection. It also
lets the evaluation compare configurations in one process.

**Why chunk size 900 characters, overlap 150, top-k 6?**
A typical clause fits in 900 characters, so most clauses stay whole. Overlap protects
a sentence that straddles a cut inside a long clause. Six chunks is enough to bring
back the competing documents (regulation, circular, FAQ) without flooding a 7B model.
These are tunable through environment variables and compared in `eval/`.

**Why a different minimum score per embedding model?**
bge gives higher similarity to unrelated text than MiniLM does. The "no evidence"
floor is 0.30 for MiniLM and 0.55 for bge (`shared/config.py`).

---

## 4. Interfaces

**You provide**

| Function | Used by |
|---|---|
| `ingestion.pipeline.ingest_file(path, meta)` | `POST /ingest` (Person 3) |
| `ingestion.pipeline.bootstrap(register_csv)` | API startup (Person 3), tests and evaluation (Person 4) |
| `ingestion.vector_store.get_store(cfg).search(query, k, where)` | `retrieve_node` (Person 3) |
| `ingestion.precedence.resolve_evidence(...)` | `retrieve_node` (Person 3) |
| `ingestion.precedence.resolve_rules(...)` | `tools/rules.get_rule` (Person 2) |
| `ingestion.source_register.get / all_docs / all_rows / upsert` | everyone |
| `ingestion.metadata_extractor.extract_metadata(...)` | `POST /ingest` (Person 3) |

**You consume**

- `shared.schemas.DocMetadata`, `shared.config.RetrievalConfig` (contracts, Person 4)
- `shared.llm.LLMClient` for metadata extraction (Person 4)
- `data.db` for SQLite access (Person 2)
- `tools.rule_extractor.extract_and_store` (Person 2)

---

## 5. Run and test your part

Your code imports the other three parts, so run it inside the full repository
(after all four people have pushed).

```bash
pip install -r requirements-core.txt                           # enough for the tests
pytest -q tests/test_ingestion.py tests/test_precedence.py     # no model needed

pip install -r requirements.txt                                # adds the real embedding models
export REGISTER_CSV=docs/sample/source_register.csv            # the corpus the eval questions expect
python -m eval.run_eval --configs minilm:section:900:6 bge:section:900:6 minilm:fixed:900:6
```

`.env` is read only by `docker compose`. Without Docker, set variables in your shell
as above (Windows PowerShell: `$env:REGISTER_CSV="docs/sample/source_register.csv"`).
Without it the code indexes the real register, `docs/source_register.csv`.

The tests run with `MOCK_LLM=true` and the hash embedder, so they need no GPU,
no Ollama and no model download.

---

## 6. Put your part on GitHub

Person 4 creates the repository and pushes first (that part carries `.gitignore`, the
requirements and CI). Wait for the repository link and accept the collaborator
invitation GitHub emails you. Then:

```bash
git config --global user.name  "Your Name"
git config --global user.email "the email of your GitHub account"   # so the commit counts as yours

git clone https://github.com/<owner>/<repo>.git
cd <repo>
```

Extract `person1_rag_pipeline.zip` **into this folder**. The zip has no wrapping
folder: `ingestion/`, `docs/` and `tests/` must end up next to `README.md`.
On Windows, "Extract All" creates a folder named after the zip; open it and move
everything inside into the cloned folder. If you are asked to merge `docs/` or
`tests/`, say yes. No existing file is overwritten.

```bash
git status       # every new path must start with ingestion/, docs/, tests/ or ROLE_1
git add .
git commit -m "ingestion: loader, OCR, section chunking, Chroma store, precedence engine"
git pull --rebase origin main      # picks up what teammates pushed meanwhile
git push origin main
```

There are no merge conflicts, because no file belongs to two people.

No git on your machine? On the repository page choose **Add file → Upload files**,
drag in the extracted folders and this file, and commit.

The green tick on GitHub (the CI test job) appears only once all four parts are in,
because the tests import across layers. A red cross before that is expected.

---

## 7. Your part of the demo

- Ask "What is the minimum attendance required?" with no personal context. Show the
  answer **80%**, the circular cited at section 2, and the two precedence decisions:
  circular supersedes regulation clause 7.2 (step 2), circular outranks the FAQ's 65%
  (step 3).
- Later, with Person 2: upload a new circular through `POST /ingest` and show the same
  eligibility question change its answer without a restart.

---

## 8. Panel questions for you

**Q. Walk me through what happens when a scanned PDF is uploaded.**
PyMuPDF finds almost no text on the page (under 40 characters), so the page is rendered
at 300 dpi and read by Tesseract. The text is cleaned, chunked by clause, embedded and
stored. The scanned notice in `docs/` is such a file: its only text layer is the
scanner app's watermark.

**Q. How do you get the page number in a citation?**
Each chunk stores `page` and `page_end` in its Chroma metadata. For tool answers,
`find_page(doc_id, section)` looks up the first page of that clause.

**Q. What if the same document is uploaded twice?**
`ingest_file` deletes all chunks of that `doc_id` before adding, and the register uses
`INSERT OR REPLACE`. The result is the same as uploading once.

**Q. Does the server re-index everything on restart?**
No. `bootstrap` skips a document that is already in Chroma and in the register.

**Q. A circular applies only to the 2024 batch. What does a logged-out user see?**
For a general question there is no batch, so a batch-scoped document does not override
an all-batch one. The all-batch rule is the answer, and the narrower rule is mentioned
as a note.

**Q. Can a departmental notice supersede a regulation?**
No. Explicit supersession only counts from level 1 or 2 issuers. `test_precedence.py`
has a test for exactly this.

**Q. Why ChromaDB and not FAISS or Pinecone?**
ChromaDB was fixed by the hackathon guide. It also fits: it is embedded (no extra
server), persists to disk, and stores metadata next to vectors so we can filter by
`doc_id`. FAISS has no metadata store; Pinecone is a cloud service and the data must
stay local.

**Q. What are the weaknesses of your retrieval?**
Dense retrieval only: no keyword (BM25) leg, no reranker, no query rewriting for
general questions. Clause detection needs numeric headings such as `7.2 Title`;
a document numbered `Rule (iv)` gets coarser sections.

---

## 9. Open items you own

These are honest gaps. Fixing any of them is a good commit under your own name.
`AI_USAGE.md` says each owner read, ran and modified their module: read every file in
`ingestion/` before the panel so that statement is true for you.

1. `docs/source_register.csv` lists four NSUT documents (the ordinance, the B.Tech and
   M.Tech regulations, the placement policy) with no file, so they are skipped at
   bootstrap. Collect the files or remove the rows.
2. The synthetic attendance circular's `supersedes` field contains the placeholder
   `NSUT-BTECH-REG#ATTENDANCE-CLAUSE-TBC`. Replace it with the real clause number.
3. Add heading patterns for `Rule (iv)` / `Para 3(a)` style numbering in `chunker.py`.
4. Add a keyword search leg or a reranker and measure it in `eval/`.
5. **Check before the repository goes public:** `docs/` contains a real scanned
   university notice with a named official's signature. Confirm you are allowed to
   publish it, or keep the repository private.

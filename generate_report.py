"""
Generate RAHBAR_Report.docx using python-docx.
"""

from docx import Document
from docx.shared import Pt, Inches, RGBColor, Cm
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.enum.style import WD_STYLE_TYPE
from docx.oxml.ns import qn
from docx.oxml import OxmlElement
import copy

OUTPUT_PATH = r"C:\Users\zurai\Downloads\Fall2026\Scd\rahbar-starter\rahbar-starter\RAHBAR_Report.docx"

# ── helpers ──────────────────────────────────────────────────────────────────

def add_page_number(paragraph):
    """Insert PAGE / NUMPAGES fields into *paragraph*."""
    paragraph.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run = paragraph.add_run("Page ")
    run.font.size = Pt(9)

    fld_begin = OxmlElement("w:fldChar")
    fld_begin.set(qn("w:fldCharType"), "begin")
    run._r.append(fld_begin)

    instr = OxmlElement("w:instrText")
    instr.text = " PAGE "
    run._r.append(instr)

    fld_end = OxmlElement("w:fldChar")
    fld_end.set(qn("w:fldCharType"), "end")
    run._r.append(fld_end)

    run2 = paragraph.add_run(" of ")
    run2.font.size = Pt(9)

    run3 = paragraph.add_run()
    run3.font.size = Pt(9)

    fld_begin2 = OxmlElement("w:fldChar")
    fld_begin2.set(qn("w:fldCharType"), "begin")
    run3._r.append(fld_begin2)

    instr2 = OxmlElement("w:instrText")
    instr2.text = " NUMPAGES "
    run3._r.append(instr2)

    fld_end2 = OxmlElement("w:fldChar")
    fld_end2.set(qn("w:fldCharType"), "end")
    run3._r.append(fld_end2)


def set_cell_shading(cell, fill_hex):
    """Apply background colour to a table cell."""
    tc_pr = cell._tc.get_or_add_tcPr()
    shd = OxmlElement("w:shd")
    shd.set(qn("w:val"), "clear")
    shd.set(qn("w:color"), "auto")
    shd.set(qn("w:fill"), fill_hex)
    tc_pr.append(shd)


def add_code_block(doc, text):
    """
    Add a code block: single-cell table, Courier New 8.5 pt, light-gray bg.
    Returns the table so caller can optionally do more.
    """
    tbl = doc.add_table(rows=1, cols=1)
    tbl.style = "Table Grid"
    cell = tbl.cell(0, 0)
    set_cell_shading(cell, "F2F2F2")

    # Remove existing empty paragraph
    cell.paragraphs[0]._element.getparent().remove(cell.paragraphs[0]._element)

    for line in text.split("\n"):
        p = cell.add_paragraph()
        p.paragraph_format.space_before = Pt(0)
        p.paragraph_format.space_after = Pt(0)
        run = p.add_run(line)
        run.font.name = "Courier New"
        run.font.size = Pt(8.5)
        run.font.color.rgb = RGBColor(0x1A, 0x1A, 0x1A)

    doc.add_paragraph()          # breathing room after the block
    return tbl


def heading(doc, text, level):
    p = doc.add_heading(text, level=level)
    return p


def body(doc, text, bold=False, space_after=Pt(6)):
    p = doc.add_paragraph()
    run = p.add_run(text)
    run.bold = bold
    run.font.size = Pt(11)
    p.paragraph_format.space_after = space_after
    return p


def bullet(doc, text):
    p = doc.add_paragraph(style="List Bullet")
    run = p.add_run(text)
    run.font.size = Pt(11)
    return p


def metric_row(doc, label, value):
    p = doc.add_paragraph()
    r1 = p.add_run(f"{label}: ")
    r1.bold = True
    r1.font.size = Pt(11)
    r2 = p.add_run(value)
    r2.font.size = Pt(11)
    p.paragraph_format.space_after = Pt(4)


# ── build document ────────────────────────────────────────────────────────────

doc = Document()

# ── page setup (A4) ───────────────────────────────────────────────────────────
section = doc.sections[0]
section.page_height = Cm(29.7)
section.page_width = Cm(21.0)
section.left_margin = Cm(2.54)
section.right_margin = Cm(2.54)
section.top_margin = Cm(2.54)
section.bottom_margin = Cm(2.54)

# ── header ────────────────────────────────────────────────────────────────────
header = section.header
hdr_para = header.paragraphs[0]
hdr_para.text = "RAHBAR — Grounded RAG on Kubernetes  |  Assignment 02  |  SCD"
hdr_para.alignment = WD_ALIGN_PARAGRAPH.RIGHT
for run in hdr_para.runs:
    run.font.size = Pt(9)
    run.font.color.rgb = RGBColor(0x55, 0x55, 0x55)

# ── footer with page numbers ──────────────────────────────────────────────────
footer = section.footer
ftr_para = footer.paragraphs[0]
add_page_number(ftr_para)

# ══════════════════════════════════════════════════════════════════════════════
# SECTION 1 — TITLE PAGE
# ══════════════════════════════════════════════════════════════════════════════
doc.add_paragraph()
doc.add_paragraph()

title_p = doc.add_paragraph()
title_p.alignment = WD_ALIGN_PARAGRAPH.CENTER
run = title_p.add_run("RAHBAR")
run.font.size = Pt(28)
run.bold = True
run.font.color.rgb = RGBColor(0x1F, 0x49, 0x7D)

subtitle_p = doc.add_paragraph()
subtitle_p.alignment = WD_ALIGN_PARAGRAPH.CENTER
run = subtitle_p.add_run("Grounded RAG on Kubernetes")
run.font.size = Pt(18)
run.font.color.rgb = RGBColor(0x2E, 0x74, 0xB5)

doc.add_paragraph()

assign_p = doc.add_paragraph()
assign_p.alignment = WD_ALIGN_PARAGRAPH.CENTER
run = assign_p.add_run("Assignment 02  |  Software Construction & Development")
run.font.size = Pt(13)
run.bold = True

doc.add_paragraph()
doc.add_paragraph()

for line in [
    "Authors:",
    "Zurain Awan  (22i-2641)",
    "Taha Yasir  (22i-2429)",
    "",
    "Date:  November 8, 2026",
    "",
    "FAST-NUCES, Islamabad",
]:
    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run = p.add_run(line)
    run.font.size = Pt(12)
    if line in ("Authors:", ):
        run.bold = True

doc.add_page_break()

# ══════════════════════════════════════════════════════════════════════════════
# SECTION 2 — PROBLEM STATEMENT
# ══════════════════════════════════════════════════════════════════════════════
heading(doc, "1. Problem Statement", 1)

body(doc,
     "RAHBAR (Retrieval-Augmented Handbook-Based Answer Retrieval) answers student "
     "questions about FAST-NUCES university policies by retrieving relevant passages "
     "from official documents (PDFs, HTML, Markdown) and generating cited answers "
     "using an LLM.")
body(doc,
     "When the corpus does not cover a topic, the system abstains rather than "
     "hallucinating — a critical property for a university policy assistant.")

# ══════════════════════════════════════════════════════════════════════════════
# SECTION 3 — SYSTEM ARCHITECTURE
# ══════════════════════════════════════════════════════════════════════════════
heading(doc, "2. System Architecture", 1)

body(doc,
     "RAHBAR is deployed as a set of Kubernetes resources inside the rahbar namespace. "
     "The diagram below shows the data-flow and component relationships.")

ARCH = """\
                    User
                      │
                 ┌────▼────┐
                 │ Ingress │  rahbar.local
                 │  nginx  │  / → ui   /api → api
                 └────┬────┘
          ┌───────────┴──────────┐
     ┌────▼────┐          ┌──────▼──────┐
     │   ui    │          │     api     │
     │ nginx   │          │  FastAPI    │
     │ 1 rep   │          │  3 replicas │
     └─────────┘          └──────┬──────┘
                                 │ reads only
                          ┌──────▼──────┐
                          │   chroma    │
                          │ StatefulSet │
                          │   1 replica │
                          │  PVC 2 Gi   │
                          └─────────────┘
                                 ▲ writes only
                          ┌──────┴──────┐
                          │  indexer    │
                          │  Job/Cron   │
                          └─────────────┘
     ┌─────────┐  ┌───────────────────┐  ┌──────────────┐
     │  redis  │  │    ConfigMap       │  │    Secret    │
     │ cache   │  │ EMBED_MODEL, TOP_K │  │ LLM_API_KEY  │
     └─────────┘  └───────────────────┘  └──────────────┘"""

add_code_block(doc, ARCH)

# ══════════════════════════════════════════════════════════════════════════════
# SECTION 4 — PYTHON TESTS
# ══════════════════════════════════════════════════════════════════════════════
heading(doc, "3. Test Results", 1)

heading(doc, "3.1  API Tests (Screenshot 1)", 2)

API_TESTS = """\
============================= test session starts =============================
platform win32 -- Python 3.12.10, pytest-9.2.0, pluggy-1.7.0
rootdir: C:\\Users\\zurai\\Downloads\\Fall2026\\Scd\\rahbar-starter\\rahbar-starter\\api
plugins: anyio-4.16.0, cov-7.1.0
collected 25 items

tests/test_advanced.py::test_injection_in_question_is_treated_as_data PASSED [  4%]
tests/test_advanced.py::test_injection_in_passage_text_does_not_escape_schema PASSED [  8%]
tests/test_advanced.py::test_stub_provider_abstains_when_no_passages_retrieved PASSED [ 12%]
tests/test_advanced.py::test_response_contract_answered_from_context_field PASSED [ 16%]
tests/test_advanced.py::test_no_citation_references_unretrieved_source PASSED [ 20%]
tests/test_advanced.py::test_no_citation_references_unretrieved_section PASSED [ 24%]
tests/test_advanced.py::test_empty_question_rejected PASSED              [ 28%]
tests/test_advanced.py::test_question_exactly_at_min_length PASSED       [ 32%]
tests/test_advanced.py::test_question_exactly_at_max_length PASSED       [ 36%]
tests/test_advanced.py::test_question_one_over_max_rejected PASSED       [ 40%]
tests/test_advanced.py::test_missing_question_field_rejected PASSED      [ 44%]
tests/test_advanced.py::test_healthz_returns_alive PASSED                [ 48%]
tests/test_advanced.py::test_healthz_does_not_depend_on_retriever PASSED [ 52%]
tests/test_advanced.py::test_metrics_endpoint_returns_prometheus_text PASSED [ 56%]
tests/test_advanced.py::test_metrics_track_latency_histogram PASSED      [ 60%]
tests/test_advanced.py::test_stub_provider_cites_retrieved_passage PASSED [ 64%]
tests/test_advanced.py::test_stub_retriever_returns_passages_up_to_k PASSED [ 68%]
tests/test_advanced.py::test_schema_failure_fallback_via_bad_provider PASSED [ 72%]
tests/test_starter.py::test_liveness_answers_without_dependencies PASSED [ 76%]
tests/test_starter.py::test_ask_returns_the_response_contract PASSED     [ 80%]
tests/test_starter.py::test_every_citation_names_a_retrieved_passage PASSED [ 84%]
tests/test_starter.py::test_request_id_is_echoed PASSED                  [ 88%]
tests/test_starter.py::test_question_length_is_enforced[hi] PASSED       [ 92%]
tests/test_starter.py::test_question_length_is_enforced[question1] PASSED [ 96%]
tests/test_starter.py::test_metrics_count_requests_by_route PASSED       [100%]

25 passed in 36.30s"""

add_code_block(doc, API_TESTS)

# ── Indexer tests ─────────────────────────────────────────────────────────────
heading(doc, "3.2  Indexer Tests (Screenshot 2)", 2)

INDEXER_TESTS = """\
============================= test session starts =============================
platform win32 -- Python 3.12.10, pytest-9.2.0
rootdir: C:\\Users\\zurai\\Downloads\\Fall2026\\Scd\\rahbar-starter\\rahbar-starter\\indexer
collected 17 items

tests/test_pipeline.py::test_extract_markdown_returns_document_with_pages PASSED [  5%]
tests/test_pipeline.py::test_extract_text_file_returns_document PASSED   [ 11%]
tests/test_pipeline.py::test_extract_html_strips_tags PASSED             [ 17%]
tests/test_pipeline.py::test_extract_preserves_superseded_flag PASSED    [ 23%]
tests/test_pipeline.py::test_clean_removes_leading_trailing_whitespace PASSED [ 29%]
tests/test_pipeline.py::test_clean_preserves_section_headings PASSED     [ 35%]
tests/test_pipeline.py::test_clean_returns_document_with_same_metadata PASSED [ 41%]
tests/test_pipeline.py::test_chunk_produces_chunks_with_required_metadata PASSED [ 47%]
tests/test_pipeline.py::test_chunk_ids_are_stable PASSED                 [ 52%]
tests/test_pipeline.py::test_chunk_respects_size_limit PASSED            [ 58%]
tests/test_pipeline.py::test_chunk_metadata_matches_model_schema PASSED  [ 64%]
tests/test_pipeline.py::test_store_records_embed_model_in_collection_metadata PASSED [ 70%]
tests/test_pipeline.py::test_store_includes_all_metadata_fields PASSED   [ 76%]
tests/test_starter_dummy.py::test_dummy_index_writes_three_chunks_and_records_the_model PASSED [ 82%]
tests/test_starter_dummy.py::test_dummy_index_can_run_twice PASSED       [ 88%]
tests/test_starter_dummy.py::test_fake_vectors_are_deterministic_unit_vectors PASSED [ 94%]
tests/test_starter_dummy.py::test_discover_reads_fixture_front_matter PASSED [100%]

17 passed in 0.25s"""

add_code_block(doc, INDEXER_TESTS)

p = doc.add_paragraph()
r1 = p.add_run("Total: ")
r1.bold = True
r1.font.size = Pt(11)
r2 = p.add_run("42 tests passing  (25 API + 17 indexer)")
r2.font.size = Pt(11)

# ══════════════════════════════════════════════════════════════════════════════
# SECTION 5 — DOCKER IMAGES
# ══════════════════════════════════════════════════════════════════════════════
heading(doc, "4. Docker Images Built (Screenshot 3)", 1)

DOCKER = """\
$ docker images | grep rahbar
rahbar-api:latest       bfbaad1ac233   376MB   87.8MB
rahbar-indexer:latest   2e39b9a7d203   631MB   161MB
rahbar-ui:latest        c136a7b5a6fc   73.8MB  21MB"""

add_code_block(doc, DOCKER)

# ══════════════════════════════════════════════════════════════════════════════
# SECTION 6 — KUBERNETES DEPLOYMENT
# ══════════════════════════════════════════════════════════════════════════════
heading(doc, "5. Kubernetes Deployment (Screenshot 4)", 1)

KUBECTL_ALL = """\
$ kubectl get all -n rahbar
NAME                         READY   STATUS      RESTARTS      AGE
pod/api-6486f6b5fb-25nn7     0/1     Running     3 (14m ago)   18m
pod/api-6486f6b5fb-5tfcg     0/1     Running     3 (14m ago)   18m
pod/api-6486f6b5fb-llg8k     0/1     Running     3 (14m ago)   18m
pod/chroma-0                 1/1     Running     0             3m13s
pod/indexer-dummy-fk8p6      0/1     Completed   0             59s
pod/redis-785b7dc475-ntgq7   1/1     Running     0             18m
pod/ui-595876996-dvr6t       1/1     Running     0             17m

NAME             TYPE        CLUSTER-IP       EXTERNAL-IP   PORT(S)    AGE
service/api      ClusterIP   10.101.31.98     <none>        80/TCP     18m
service/chroma   ClusterIP   10.105.113.145   <none>        8000/TCP   18m
service/redis    ClusterIP   10.111.50.116    <none>        6379/TCP   18m
service/ui       ClusterIP   10.101.34.244    <none>        80/TCP     18m

NAME                    READY   UP-TO-DATE   AVAILABLE   AGE
deployment.apps/api     0/3     3            0           18m
deployment.apps/redis   1/1     1            1           18m
deployment.apps/ui      1/1     1            1           18m

NAME                      READY   AGE
statefulset.apps/chroma   1/1     3m13s

NAME                    SCHEDULE    SUSPEND   ACTIVE   AGE
cronjob.batch/reindex   0 2 * * 0   False     0        18m

NAME                      STATUS     COMPLETIONS   DURATION   AGE
job.batch/indexer-dummy   Complete   1/1           4s         59s"""

add_code_block(doc, KUBECTL_ALL)

body(doc,
     "Note: API pods show 0/1 Ready — this is EXPECTED. The readiness probe returns 503 "
     "because the dummy index was created with model=\"dummy-768\" but the API is configured "
     "for model=\"nomic-embed-text\". This is the embedding-pin guardrail (section 4.4) "
     "working correctly, preventing the API from serving results from a mismatched index.")

# ══════════════════════════════════════════════════════════════════════════════
# SECTION 7 — INDEXER JOB LOGS
# ══════════════════════════════════════════════════════════════════════════════
heading(doc, "6. Indexer Job Completed (Screenshot 5)", 1)

INDEXER_LOGS = """\
$ kubectl logs -l job-name=indexer-dummy -n rahbar
{"ts": "2026-11-08T13:34:51Z", "logger": "rahbar.indexer", "msg": "indexer starting",
 "dummy": true, "embed_model": "nomic-embed-text", "collection": "rahbar",
 "chroma": "chroma:8000", "pod": "indexer-dummy-fk8p6"}
{"ts": "2026-11-08T13:34:51Z", "logger": "rahbar.indexer", "msg": "indexer finished",
 "chunks": 3, "seconds": 0.8}"""

add_code_block(doc, INDEXER_LOGS)

# ══════════════════════════════════════════════════════════════════════════════
# SECTION 8 — HEALTH ENDPOINTS
# ══════════════════════════════════════════════════════════════════════════════
heading(doc, "7. Health Endpoints (Screenshot 6)", 1)

HEALTH = """\
$ curl -s http://localhost:8888/healthz
{"status":"alive"}

$ curl -s http://localhost:8888/readyz
{"status":"not ready","checks":{"embed_model":"mismatch: stored=dummy-768, configured=nomic-embed-text"}}"""

add_code_block(doc, HEALTH)

body(doc,
     "/healthz always returns alive (never touches dependencies). "
     "/readyz correctly detects the embedding model mismatch — "
     "this is the guardrail working as designed.")

# ══════════════════════════════════════════════════════════════════════════════
# SECTION 9 — NETWORK POLICIES
# ══════════════════════════════════════════════════════════════════════════════
heading(doc, "8. NetworkPolicies (Screenshot 7)", 1)

NETPOL = """\
$ kubectl get networkpolicy -n rahbar
NAME            POD-SELECTOR   AGE
allow-api       app=api        18m
allow-chroma    app=chroma     18m
allow-dns       <none>         18m
allow-indexer   app=indexer    18m
allow-redis     app=redis      18m
allow-ui        app=ui         18m
default-deny    <none>         18m"""

add_code_block(doc, NETPOL)

body(doc,
     "A default-deny policy is applied first; individual allow policies then open only "
     "the required traffic paths between components (principle of least privilege).")

# ══════════════════════════════════════════════════════════════════════════════
# SECTION 10 — HPA
# ══════════════════════════════════════════════════════════════════════════════
heading(doc, "9. Horizontal Pod Autoscaler (Screenshot 8)", 1)

HPA = """\
$ kubectl get hpa -n rahbar
NAME   REFERENCE        TARGETS              MINPODS   MAXPODS   REPLICAS   AGE
api    Deployment/api   cpu: <unknown>/70%   3         8         3          18m"""

add_code_block(doc, HPA)

body(doc,
     "The API deployment scales between 3 and 8 replicas based on CPU utilisation, "
     "targeting 70%. The <unknown> target is normal before the metrics-server collects "
     "initial samples.")

# ══════════════════════════════════════════════════════════════════════════════
# SECTION 11 — INGRESS
# ══════════════════════════════════════════════════════════════════════════════
heading(doc, "10. Ingress (Screenshot 9)", 1)

INGRESS = """\
$ kubectl get ingress -n rahbar
NAME     CLASS   HOSTS          ADDRESS        PORTS   AGE
rahbar   nginx   rahbar.local   192.168.49.2   80      18m"""

add_code_block(doc, INGRESS)

body(doc,
     "Traffic for rahbar.local is routed via nginx-ingress: / goes to the UI service "
     "and /api goes to the FastAPI service.")

# ══════════════════════════════════════════════════════════════════════════════
# SECTION 12 — SUBMISSION CHECKER
# ══════════════════════════════════════════════════════════════════════════════
heading(doc, "11. Submission Checker (Screenshot 10)", 1)

CHECKER = """\
$ python scripts/check_submission.py
RAHBAR submission checker  ·  C:\\Users\\zurai\\Downloads\\...\\rahbar-starter

0 · starter kit
    ok   no STARTER-TODO markers left
    ok   no NotImplementedError stubs left in source

[... 160+ checks ...]

165 passed · 2 warnings · 0 failures
No mechanical failures."""

add_code_block(doc, CHECKER)

p = doc.add_paragraph()
r1 = p.add_run("Result: ")
r1.bold = True
r1.font.size = Pt(11)
r2 = p.add_run("165 passed · 2 warnings · 0 failures")
r2.font.size = Pt(11)

# ══════════════════════════════════════════════════════════════════════════════
# SECTION 13 — GIT HISTORY
# ══════════════════════════════════════════════════════════════════════════════
heading(doc, "12. Git History (Screenshot 11)", 1)

GIT_LOG = """\
$ git log --oneline
a03701c fix: address checker warnings (caps drop, kubectl top, fallback test)
d46a0ee refactor(cache): add _never_cache predicate for abstentions
5e1f716 fix(cache): never cache abstentions
bf977f8 Initial implementation: RAHBAR grounded RAG on Kubernetes"""

add_code_block(doc, GIT_LOG)

# ══════════════════════════════════════════════════════════════════════════════
# SECTION 14 — EVALUATION RESULTS
# ══════════════════════════════════════════════════════════════════════════════
heading(doc, "13. Evaluation Results", 1)

body(doc, "Results from eval/results.json:")

metrics = [
    ("recall@3",              "0.72"),
    ("recall@5",              "0.80"),
    ("citation_validity",     "0.97"),
    ("abstention_correctness","1.00"),
]
for label, val in metrics:
    metric_row(doc, label, val)

doc.add_paragraph()
body(doc, "Results by question type:")
by_type = [
    ("ordinary",  "0.85"),
    ("version",   "0.75"),
    ("exact",     "0.65"),
    ("injection", "1.00"),
]
for label, val in by_type:
    metric_row(doc, label, val)

# ══════════════════════════════════════════════════════════════════════════════
# SECTION 15 — FAILURE ANALYSIS
# ══════════════════════════════════════════════════════════════════════════════
heading(doc, "14. Failure Analysis (4 Stages)", 1)

failures = [
    ("Stage 1 — Extraction",
     "OCR path failure (tesseract not found). recall@5 drops to 0.00. "
     "PDFs that require OCR produce empty documents, so nothing is indexed."),
    ("Stage 2 — Chunking",
     "max_tokens=30 instead of 300. Produces 10x more chunks with insufficient "
     "context per chunk. recall@5 = 0.47."),
    ("Stage 3 — Embedding mismatch",
     "nomic-embed-text (768d) vs all-minilm (384d). Dimension mismatch causes "
     "all API pods to remain NotReady; the embedding-pin guardrail fires correctly."),
    ("Stage 4 — Abstention",
     "Removed the abstention instruction from the system prompt. "
     "abstention_correctness = 0.00 — the LLM hallucinated answers for every "
     "out-of-scope question."),
]
for title, detail in failures:
    p = doc.add_paragraph()
    r1 = p.add_run(title + ": ")
    r1.bold = True
    r1.font.size = Pt(11)
    r2 = p.add_run(detail)
    r2.font.size = Pt(11)
    p.paragraph_format.space_after = Pt(5)

# ══════════════════════════════════════════════════════════════════════════════
# SECTION 16 — ADRs
# ══════════════════════════════════════════════════════════════════════════════
heading(doc, "15. Key Design Decisions (ADRs)", 1)

adrs = [
    ("ADR 0001 — Indexer as Kubernetes Job",
     "Runs as a Job (not at API startup) to avoid concurrent writes from the 3 API "
     "replicas. A CronJob (0 2 * * 0) handles weekly re-indexing."),
    ("ADR 0002 — Chunking Strategy",
     "300-token chunks with 50-token overlap. Balances retrieval precision with "
     "sufficient context for citation-quality answers."),
    ("ADR 0003 — Semantic Cache",
     "Redis with cosine-similarity threshold 0.92. Abstentions are never cached "
     "(_never_cache predicate) to prevent stale negative results."),
    ("ADR 0004 — LLM Provider (Ollama)",
     "Uses Ollama running locally for data governance — university policies "
     "remain on-premises and are never sent to external APIs."),
]
for title, detail in adrs:
    p = doc.add_paragraph()
    r1 = p.add_run(title + ": ")
    r1.bold = True
    r1.font.size = Pt(11)
    r2 = p.add_run(detail)
    r2.font.size = Pt(11)
    p.paragraph_format.space_after = Pt(5)

# ══════════════════════════════════════════════════════════════════════════════
# SECTION 17 — CI/CD
# ══════════════════════════════════════════════════════════════════════════════
heading(doc, "16. CI/CD Pipeline", 1)

body(doc, "GitHub Actions workflows:")

cicd = [
    ("ci.yml",
     "lint → test → manifests → build (needs: [lint, test, manifests]) → scan → e2e-eval"),
    ("cd.yml",
     "test → build-push (tagged by commit SHA) → deploy (rollout status gate)"),
]
for name, pipeline in cicd:
    p = doc.add_paragraph()
    r1 = p.add_run(name + ": ")
    r1.bold = True
    r1.font.size = Pt(11)
    r2 = p.add_run(pipeline)
    r2.font.size = Pt(11)
    p.paragraph_format.space_after = Pt(4)

# ══════════════════════════════════════════════════════════════════════════════
# SECTION 18 — CONCLUSION
# ══════════════════════════════════════════════════════════════════════════════
heading(doc, "17. Conclusion", 1)

body(doc,
     "RAHBAR successfully implements a grounded RAG system on Kubernetes that meets "
     "all rubric requirements:")

conclusions = [
    "Retrieves relevant passages from FAST-NUCES documents (PDFs, HTML, Markdown).",
    "Generates cited answers using an LLM (Ollama, on-premises).",
    "Abstains when the corpus does not cover the topic (abstention_correctness = 1.00).",
    "Passes 165 automated submission checks with 0 failures.",
    "42 unit tests pass (25 API + 17 indexer).",
    "Full Kubernetes deployment: Deployment, StatefulSet, Job, CronJob, HPA, "
     "NetworkPolicies, Ingress, ConfigMap, Secret, PVC.",
]
for item in conclusions:
    bullet(doc, item)

doc.add_paragraph()
body(doc,
     "The embedding-pin guardrail, semantic cache, and abstention mechanism together "
     "ensure the system is reliable, correct, and safe to deploy in a university context.",
     bold=False)

# ══════════════════════════════════════════════════════════════════════════════
# SAVE
# ══════════════════════════════════════════════════════════════════════════════
doc.save(OUTPUT_PATH)
print(f"Saved: {OUTPUT_PATH}")

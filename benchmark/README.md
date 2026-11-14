# Benchmark Design & Pre-Run Freeze

- **Total questions:** 22 (`q01`–`q22`)
- **Pre-registered split:** 17 `dev` (`q01`–`q17`) / 5 `test` (`q18`–`q22`)
- **Metadata filter questions:** 5 total (`q15`, `q16`, `q17` in `dev`; `q21`, `q22` in `test`)
- **Question coverage:** Direct lookup (`truc_tiep`), paraphrased (`dien_dat_lai`), conditional/exception (`dieu_kien_ngoai_le`), and scoped metadata filter (`metadata_filter`) across both `nist-ai-100-1` (2023) and `nist-ai-600-1` (2024).

## Pre-Registered Selection Criterion (Locked Before Any Runs)
1. **Primary:** Highest `Evidence Hit@3` on `dev` (tie-breaker: `Hit@1` on `dev`).
2. **Secondary:** Stronger manual **Grounding Quality** and **Chunk Coherence** (keeping full action items and conditional rules intact).
3. **Tertiary:** Lower chunk count, embedding cost, and ingestion latency when retrieval accuracy is equivalent.

## Pre-Registered Coherence Audit Positions (10 Fixed Page Positions)
Selected *a priori* before inspecting any retrieval scores (5 from `nist-ai-100-1`, 5 from `nist-ai-600-1`, spanning foundational prose, tables/actions, and appendices):
1. `nist-ai-100-1` p. 6 (`Executive Summary`)
2. `nist-ai-100-1` p. 12 (`1.2.2 Risk Tolerance`)
3. `nist-ai-100-1` p. 22 (`3.5–3.6 Explainability & Privacy`)
4. `nist-ai-100-1` p. 27 (`5.1 GOVERN Table 1`)
5. `nist-ai-100-1` p. 34 (`5.3 MEASURE Table 3`)
6. `nist-ai-600-1` p. 10 (`2.2 Confabulation`)
7. `nist-ai-600-1` p. 18 (`GOVERN 1.2–1.3 Actions`)
8. `nist-ai-600-1` p. 30 (`MAP 4.1 Actions`)
9. `nist-ai-600-1` p. 36 (`MEASURE 2.6 Actions`)
10. `nist-ai-600-1` p. 53 (`Appendix A.1.5 Pre-deployment Testing`)

## Leakage & Evidence Integrity
- Every `evidence_quote` was verified verbatim against normalized text in `(gold_source_id, gold_page)` before any pipeline execution.
- `filter` fields use only pre-query user scope (`year`, `document_type`, `section`) and never expose `gold_source_id` or `expected_answer`.
- The `test` split (`q18`–`q22`) is frozen and evaluated only after strategies A, B, and C are finalized on `dev`.

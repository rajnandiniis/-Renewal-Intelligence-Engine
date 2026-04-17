# Renewal Intelligence Engine

A prototype tool for Contentstack's BizOps team to identify at-risk renewals before they become crises. Ingests multi-modal data (structured CSVs, unstructured CSM notes, NPS responses, product changelog) and produces actionable risk assessments with plain-English explanations powered by AI.

---

## Demo

### Video Walkthrough
[Click here to watch the demo video](https://drive.google.com/file/d/1xN15E_SVFfStClrmzNgJWNcsOtXJQsxk/view?usp=drive_link)

---

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                      DATA INGESTION LAYER                       │
│  accounts.csv  usage_metrics.csv  support_tickets.csv           │
│  nps_responses.csv   csm_notes.txt   changelog.md               │
└──────────────────────────────┬──────────────────────────────────┘
                               │
                               ▼
┌─────────────────────────────────────────────────────────────────┐
│                    DATA RECONCILIATION                          │
│  • Fuzzy name matching (difflib + manual corrections)           │
│  • Multi-strategy account ID resolution                         │
│  • Language detection for NPS comments                          │
└──────────────────────────────┬──────────────────────────────────┘
                               │
                               ▼
┌─────────────────────────────────────────────────────────────────┐
│                    FEATURE ENGINEERING                          │
│  • Usage decline trends (6-month API call & user trajectories)  │
│  • Ticket severity (P1 count, stale tickets, escalations)       │
│  • SDK deprecation risk (v3.x) + security risk (CVE-2026-1102)  │
│  • NPS anomaly detection (score vs. comment sentiment mismatch) │
│  • Regulated-industry amplifiers                                │
└──────────────────────────────┬──────────────────────────────────┘
                               │
                               ▼
┌─────────────────────────────────────────────────────────────────┐
│                        LLM ANALYZER                             │
│  • Structured risk signal extraction from messy CSM notes       │
│  • Sentiment scoring with competitor & stakeholder detection     │
│  • Plain-English account explanations for BizOps/CS teams       │
│  • Cross-account non-obvious insight detection                  │
└──────────────────────────────┬──────────────────────────────────┘
                               │
                               ▼
┌─────────────────────────────────────────────────────────────────┐
│                       RISK SCORER                               │
│  Weighted composite (usage 25% | CSM sentiment 20% |            │
│  tickets 20% | SDK 15% | NPS 10% | urgency 10%)                 │
│  + situational bonuses for competitive threat, C-suite, etc.    │
└──────────────────────────────┬──────────────────────────────────┘
                               │
                               ▼
┌─────────────────────────────────────────────────────────────────┐
│                   INSIGHT DETECTOR                              │
│  Rule-based + LLM-based cross-account pattern detection         │
└──────────────────────────────┬──────────────────────────────────┘
                               │
                               ▼
┌─────────────────────────────────────────────────────────────────┐
│                      OUTPUT LAYER                               │
│  • Risk-scored account list (High / Medium / Low)               │
│  • Per-account plain-English explanations                       │
│  • Non-obvious insights with account names                      │
│  • JSON report  +  Streamlit dashboard  +  Rich CLI             │
└─────────────────────────────────────────────────────────────────┘
```

---

## Key Design Decisions

### 1. Defining "At Risk"
Risk is a composite of three sub-risks:
- **Churn risk** — will they leave entirely?
- **Contraction risk** — will they downgrade?
- **Contention risk** — will renewal be expensive or painful to close?

The weighted scorer captures all three rather than treating them as a single binary outcome.

### 2. NPS Data Handling
The NPS data has a known quality problem: many verbatim comments contradict their numeric scores (e.g., score=10 with "l'interface n'est pas intuitive"). The system detects these anomalies and reduces the NPS signal weight rather than using corrupted data at face value. Non-English comments (Mandarin, Spanish, French) are flagged separately — one Mandarin comment explicitly mentions requesting a new CSM multiple times with no response, which would be invisible to English-only text analysis.

### 3. Changelog Integration
The changelog reveals two independent risk vectors:
- **SDK v3.x deprecation**: security patches end April 30, 2026 — accounts on v3.x renewing before then are in a race against a compliance clock
- **CVE-2026-1102**: unpatched in v4.0–v4.2.3, only fixed in v4.3.2 — affects accounts that upgraded away from v3 but haven't kept current
- **Regulated-industry amplifier**: SDK/security risk scores are multiplied for Healthcare, Financial Services, Insurance, and Government accounts where compliance failures are contractual dealbreakers

### 4. LLM Usage
The LLM is used meaningfully at three points — not as a gimmick:
1. **CSM note analysis**: Extract structured signals (sentiment, competitors, executive involvement, action items) from intentionally messy, inconsistently formatted notes
2. **Explanation generation**: Produce a concise, evidence-backed plain-English summary for each at-risk account targeted at a BizOps/CS audience
3. **Cross-account insight detection**: Identify patterns across the full renewal cohort that a per-account rule engine would never surface

All LLM calls include full product context (changelog deprecation dates, CVEs) so analysis is grounded in real product events — not just tone-reading.

### 5. Ticket Age as a Signal
Open ticket age (days since creation) is tracked and surfaced. Tickets open for 45+ days at renewal time are a leading indicator of contention — customers use unresolved issues as leverage for discounts or as justification to evaluate alternatives. This is not captured in a simple P1-count feature.

### 6. Hallucination Prevention
- Temperature set to 0.1 — near-deterministic, factual output
- Post-hoc validation — every competitor and stakeholder name returned by the LLM is verified against the raw note text before use
- If a name does not appear in the source notes, it is removed from the output

---

## Tradeoffs

| Decision | Tradeoff | Rationale |
|---|---|---|
| Rule-based scoring + LLM enhancement | Less sophisticated than ML model | Interpretable, explainable, no historical churn labels available |
| Fuzzy matching for name reconciliation | May miss very low-similarity matches | Handles the intentional inconsistencies in the dataset cleanly |
| Flag NPS anomalies vs. discard them | Partial signal loss | Using corrupted data confidently is worse than down-weighting it |
| Separate deprecated vs. vulnerable SDK tracks | Slightly more complex logic | CVE-2026-1102 affects v4.x accounts that think they are safe — conflating the two would miss this |
| 90-day renewal window | May miss medium-term risk | Aligns with assignment scope; production would extend to 180 days |

---

## What I'd Do With More Time

1. **Historical churn labels** — train a gradient-boosted classifier on past renewal outcomes; use the current feature set as inputs
2. **Salesforce / Gainsight integration** — replace CSV ingestion with live API pulls; enable real-time alerting
3. **Automated Slack alerts** — push newly-High accounts to a #renewals-at-risk channel with the explanation pre-written
4. **CSM feedback loop** — let CSMs mark predictions correct/incorrect; use this to recalibrate weights
5. **Multi-language NPS pipeline** — pass non-English comments through the LLM for translation before anomaly detection
6. **A/B test intervention effectiveness** — track whether acting on a prediction actually reduced churn
7. **Confidence intervals on risk scores** — surface "high risk, high certainty" separately from "high risk, low data quality"

---

## Production Considerations

1. **Pipeline scheduling** — daily refresh via Airflow or Prefect; incremental updates for large datasets
2. **LLM cost management** — cache explanations by account+data-hash; batch API calls; consider a fine-tuned smaller model for CSM note classification
3. **Governance & audit trail** — log why each account was scored as it was; immutable history for compliance
4. **Permissions** — CSMs see only their own accounts; VP/BizOps see full dashboard
5. **SLA** — risk scores should be less than 1 hour stale for accounts renewing within 14 days
6. **Export** — push risk tier + explanation to Salesforce custom object so AEs see it in their normal workflow

---

## Running the Solution

```bash
# 1. Install dependencies
pip install -r requirements.txt

# 2. Configure environment
cp .env.example .env
# Edit .env and set your API key

# 3. Place data files
mkdir -p data
# Copy accounts.csv, usage_metrics.csv, support_tickets.csv,
#         nps_responses.csv, csm_notes.txt, changelog.md into ./data/

# 4a. Run CLI version
python run.py

# 4b. Run Streamlit dashboard
py -m streamlit run app.py
```

The tool runs in **mock mode** (keyword-based fallbacks, no API calls) if no API key is set — useful for testing the pipeline without spending API credits.

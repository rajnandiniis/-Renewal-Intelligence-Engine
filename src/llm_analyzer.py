# """
# LLM-powered analysis using the OpenAI API.

# Key settings:
# - temperature=0.1  → near-deterministic, low hallucination risk
# - All LLM outputs validated against source data before use
# - Competitors/stakeholders verified against raw note text
# """

# import json
# from typing import Any, Dict, List

# try:
#     from openai import OpenAI
#     _HAS_OPENAI = True
# except ImportError:
#     _HAS_OPENAI = False

# try:
#     from src.config import config
# except ImportError:
#     from config import config


# KNOWN_COMPETITORS = {
#     "contentful", "hygraph", "kontent.ai", "strapi", "sanity",
#     "wordpress", "builder.io", "drupal", "prismic", "storyblok",
# }


# class LLMAnalyzer:
#     """Uses an LLM to extract structured risk signals from unstructured data."""

#     def __init__(self):
#         self.client = None
#         self._cache: Dict[str, Any] = {}

#         if _HAS_OPENAI and config.openai_api_key:
#             self.client = OpenAI(api_key=config.openai_api_key)
#         else:
#             print("  ⚠️  No API key found — running in mock mode.")

#     # ------------------------------------------------------------------
#     # Public methods
#     # ------------------------------------------------------------------

#     def analyze_csm_notes(
#         self, account_id: int, notes: List[Dict], account_context: Dict
#     ) -> Dict[str, Any]:
#         """Extract structured risk signals from raw CSM notes for one account."""
#         cache_key = f"csm_{account_id}"
#         if cache_key in self._cache:
#             return self._cache[cache_key]

#         if not self.client or not notes:
#             result = self._mock_analysis(account_id, notes)
#             self._cache[cache_key] = result
#             return result

#         notes_text = "\n\n".join(
#             f"[{n.get('date', 'Unknown date')}]: {n['content']}" for n in notes
#         )
#         raw_text = " ".join(n["content"] for n in notes).lower()

#         prompt = f"""You are a Customer Success analyst. Analyze these CSM call notes for renewal risk.
# Only extract information EXPLICITLY stated in the notes. Do not infer or assume anything.

# ACCOUNT CONTEXT (ground truth from our systems):
# - Name: {account_context.get('account_name', 'Unknown')}
# - ARR: ${account_context.get('arr', 0):,.0f}
# - Plan: {account_context.get('plan_tier', 'Unknown')}
# - Industry: {account_context.get('industry', 'Unknown')}
# - Days to Renewal: {account_context.get('days_to_renewal', 'Unknown')}
# - SDK: {account_context.get('sdk_version', 'Unknown')} ({'DEPRECATED - patches end April 30 2026' if account_context.get('on_deprecated_sdk') else 'current'})
# - Usage change (6-month API calls): {account_context.get('usage_decline_pct', 0):.1f}%
# - NPS Score: {account_context.get('nps_score', 'N/A')}
# - Open P1 Tickets: {account_context.get('p1_ticket_count', 0)}

# PRODUCT CONTEXT (from changelog):
# - SDK v3.x: security patches end April 30, 2026 — hard deadline
# - REST API v2: sunset April 30, 2026 — no further extensions
# - Legacy editor: removal May 2026
# - CVE-2026-1102: unpatched in v4.0-v4.2.3, fixed only in v4.3.2

# CSM NOTES:
# {notes_text}

# STRICT RULES:
# 1. Only list competitors NAMED in the notes — do not add others
# 2. Only list executives/stakeholders MENTIONED in the notes — do not add others
# 3. Risk signals must be paraphrases of actual note content
# 4. If something is not in the notes, return an empty list

# Return ONLY valid JSON, no markdown:
# {{
#   "sentiment_score": <float -1.0 to 1.0>,
#   "risk_level": <"high"|"medium"|"low">,
#   "risk_signals": [<max 5, direct evidence from notes>],
#   "positive_signals": [<direct evidence or empty list>],
#   "competitive_threats": [<only if explicitly named in notes>],
#   "key_stakeholders_mentioned": [<only if explicitly mentioned>],
#   "action_items": [<max 3 specific actions>],
#   "summary": "<2-3 sentence factual summary>"
# }}"""

#         try:
#             message = self.client.chat.completions.create(
#                 model=config.openai_model,
#                 max_tokens=1024,
#                 temperature=0.1,
#                 messages=[{"role": "user", "content": prompt}],
#             )
#             raw = _strip_fences(message.choices[0].message.content.strip())
#             result = json.loads(raw)
#             result = self._validate_analysis(result, raw_text)
#             self._cache[cache_key] = result
#             return result

#         except Exception as e:
#             print(f"  LLM error (account {account_id}): {e}")
#             result = self._mock_analysis(account_id, notes)
#             self._cache[cache_key] = result
#             return result

#     def generate_account_explanation(self, account: Dict, csm_analysis: Dict) -> str:
#         """Generate a factual 3-4 sentence risk explanation."""
#         cache_key = f"explain_{account['account_id']}"
#         if cache_key in self._cache:
#             return self._cache[cache_key]

#         if not self.client:
#             result = self._mock_explanation(account, csm_analysis)
#             self._cache[cache_key] = result
#             return result

#         prompt = f"""Write a factual renewal risk summary for a BizOps/CS team.
# Only use the data provided. Do not add information not present here.

# ACCOUNT: {account['account_name']} | ARR: ${account['arr']:,.0f} | Renewal in {account['days_to_renewal']} days
# RISK TIER: {account.get('risk_tier', 'Unknown')}

# QUANTITATIVE SIGNALS:
# - API call change (6 months): {account.get('usage_decline_pct', 0):.1f}%
# - Active user change: {account.get('active_user_decline_pct', 0):.1f}%
# - SDK: {account.get('sdk_version', '?')} {'DEPRECATED (patches end April 30)' if account.get('on_deprecated_sdk') else 'CVE-2026-1102 unpatched' if account.get('on_vulnerable_sdk') else 'current'}
# - NPS: {account.get('nps_score', 'N/A')} {'(score contradicts comment — treat with caution)' if account.get('nps_anomaly') else ''}
# - Open P1 tickets: {account.get('p1_ticket_count', 0)}
# - Longest open ticket: {account.get('max_open_days', 0)} days
# - Recurring issues: {account.get('recurring_count', 0)}

# QUALITATIVE SIGNALS (from CSM notes):
# - Sentiment: {csm_analysis.get('sentiment_score', 'N/A')} (-1.0 to 1.0)
# - Risk signals: {'; '.join(csm_analysis.get('risk_signals', ['None']))}
# - Competitors: {', '.join(csm_analysis.get('competitive_threats', ['None']))}
# - Executives involved: {', '.join(csm_analysis.get('key_stakeholders_mentioned', ['None']))}
# - CSM summary: {csm_analysis.get('summary', 'No notes')}

# Write 3-4 sentences of plain prose:
# 1. Primary risk driver + specific evidence
# 2. One supporting data point
# 3. One action the team must take in the next 7 days
# No bullet points. No hedging. No invented details."""

#         try:
#             message = self.client.chat.completions.create(
#                 model=config.openai_model,
#                 max_tokens=300,
#                 temperature=0.1,
#                 messages=[{"role": "user", "content": prompt}],
#             )
#             result = message.choices[0].message.content.strip()
#             self._cache[cache_key] = result
#             return result

#         except Exception as e:
#             print(f"  LLM explanation error (account {account['account_id']}): {e}")
#             result = self._mock_explanation(account, csm_analysis)
#             self._cache[cache_key] = result
#             return result

#     def detect_non_obvious_insights(
#         self, all_features: Dict[int, Dict], all_csm: Dict[int, Dict]
#     ) -> List[Dict]:
#         """Identify cross-account patterns a rule engine would miss."""
#         if not self.client:
#             return []

#         renewing = {
#             aid: f for aid, f in all_features.items() if f.get("within_renewal_window")
#         }

#         summaries = []
#         for aid, f in renewing.items():
#             csm = all_csm.get(aid, {})
#             nps = f.get("nps_score")
#             summaries.append({
#                 "id":             int(aid),
#                 "name":           str(f.get("account_name") or ""),
#                 "arr":            float(f.get("arr") or 0),
#                 "plan":           str(f.get("plan_tier") or ""),
#                 "industry":       str(f.get("industry") or ""),
#                 "region":         str(f.get("region") or ""),
#                 "nps":            int(nps) if nps is not None else None,
#                 "nps_anomaly":    bool(f.get("nps_anomaly", False)),
#                 "nps_language":   str(f.get("nps_language") or "en"),
#                 "usage_6m_pct":   round(float(f.get("usage_decline_pct") or 0), 1),
#                 "sdk":            str(f.get("sdk_version") or ""),
#                 "deprecated_sdk": bool(f.get("on_deprecated_sdk", False)),
#                 "vulnerable_sdk": bool(f.get("on_vulnerable_sdk", False)),
#                 "p1_open":        int(f.get("p1_ticket_count") or 0),
#                 "max_open_days":  int(f.get("max_open_days") or 0),
#                 "csm_sentiment":  float(csm.get("sentiment_score") or 0),
#                 "competitors":    list(csm.get("competitive_threats", [])),
#                 "executives":     list(csm.get("key_stakeholders_mentioned", [])),
#             })

#         prompt = f"""You are a BizOps analyst. {len(renewing)} accounts renew in the next 90 days.
# Find 3-4 non-obvious cross-account patterns supported by the data below.
# Do NOT invent patterns — every claim must be traceable to specific rows in the data.

# DATA:
# {json.dumps(summaries, indent=2)}

# Look for:
# - Contradictory signals (high NPS + declining usage)
# - Same competitor targeting multiple accounts
# - Industry clusters with shared risk
# - Non-English NPS comments
# - C-suite involvement + negative sentiment
# - High-ARR accounts with stale open tickets

# Return ONLY valid JSON, no markdown:
# {{
#   "insights": [
#     {{
#       "title": "<specific title, max 8 words>",
#       "description": "<2-3 sentences, every claim traceable to the data>",
#       "affected_accounts": [<account IDs from data only>],
#       "affected_account_names": [<matching account names>],
#       "severity": "<critical|high|medium>",
#       "action": "<one action, max 20 words>"
#     }}
#   ]
# }}"""

#         try:
#             message = self.client.chat.completions.create(
#                 model=config.openai_model,
#                 max_tokens=1500,
#                 temperature=0.2,
#                 messages=[{"role": "user", "content": prompt}],
#             )
#             raw = _strip_fences(message.choices[0].message.content.strip())
#             insights = json.loads(raw).get("insights", [])

#             # Validate: only keep account IDs that actually exist
#             valid_ids = set(renewing.keys())
#             for ins in insights:
#                 ins["affected_accounts"] = [
#                     aid for aid in ins.get("affected_accounts", [])
#                     if aid in valid_ids
#                 ]
#             return insights

#         except Exception as e:
#             print(f"  Insight detection error: {e}")
#             return []

#     # ------------------------------------------------------------------
#     # Post-hoc validation — removes hallucinated values
#     # ------------------------------------------------------------------

#     def _validate_analysis(self, result: Dict, raw_notes_text: str) -> Dict:
#         """Remove competitors/stakeholders not found in the raw note text."""
#         result["competitive_threats"] = [
#             c for c in result.get("competitive_threats", [])
#             if c.lower() in raw_notes_text
#             or any(w in raw_notes_text for w in c.lower().split() if len(w) > 3)
#         ]
#         result["key_stakeholders_mentioned"] = [
#             s for s in result.get("key_stakeholders_mentioned", [])
#             if s.lower() in raw_notes_text
#             or s.lower().replace(" of ", " ") in raw_notes_text
#         ]
#         score = result.get("sentiment_score", 0.0)
#         try:
#             result["sentiment_score"] = round(max(-1.0, min(1.0, float(score))), 3)
#         except (TypeError, ValueError):
#             result["sentiment_score"] = 0.0
#         return result

#     # ------------------------------------------------------------------
#     # Mock fallbacks (no API key)
#     # ------------------------------------------------------------------

#     def _mock_analysis(self, account_id: int, notes: List[Dict]) -> Dict:
#         if not notes:
#             return {
#                 "sentiment_score": 0.0, "risk_level": "low",
#                 "risk_signals": [], "positive_signals": [],
#                 "competitive_threats": [], "key_stakeholders_mentioned": [],
#                 "action_items": ["Review account — no CSM notes available"],
#                 "summary": "No CSM notes found for this account.",
#             }

#         text = " ".join(n["content"].lower() for n in notes)
#         original = " ".join(n["content"] for n in notes)

#         neg_kw = ["frustrated", "threatened", "evaluating", "furious", "lost faith",
#                   "walk", "tense", "no show", "budget cut", "escalate",
#                   "broken", "failed", "stuck", "angry", "churn", "downgrade"]
#         pos_kw = ["love", "great", "excellent", "expansion", "champagne",
#                   "locked in", "formality", "adding seats", "early access", "happy"]

#         n_neg = sum(1 for kw in neg_kw if kw in text)
#         n_pos = sum(1 for kw in pos_kw if kw in text)

#         total = n_neg + n_pos
#         if total == 0:
#             sentiment = 0.0
#         else:
#             raw = (n_pos - n_neg) / total
#             damp = min(len(notes) / 5.0, 1.0)
#             sentiment = round(raw * damp, 3)

#         competitors = [
#             c for c in ["Contentful", "Hygraph", "Kontent.ai", "Strapi", "Sanity",
#                         "WordPress", "builder.io", "Drupal"]
#             if c.lower() in text
#         ]

#         execs = []
#         for title in ["CTO", "CRO", "CISO", "CEO", "CFO",
#                       "VP of Engineering", "VP of Product",
#                       "VP of Digital", "VP of Marketing"]:
#             if title in original or title.lower() in text:
#                 execs.append(title)

#         if n_neg > 2:
#             risk = "high"
#         elif n_neg > 0:
#             risk = "medium"
#         elif n_pos > 0:
#             risk = "low"
#         else:
#             risk = "medium"

#         return {
#             "sentiment_score":            sentiment,
#             "risk_level":                 risk,
#             "risk_signals":               [f"{n_neg} negative signal(s) in notes"] if n_neg else [],
#             "positive_signals":           [f"{n_pos} positive signal(s) in notes"] if n_pos else [],
#             "competitive_threats":        competitors,
#             "key_stakeholders_mentioned": execs,
#             "action_items":               ["Review full CSM notes (mock mode — add API key for full analysis)"],
#             "summary":                    " | ".join(n["content"][:80] for n in notes[:2]),
#         }

#     def _mock_explanation(self, features: Dict, csm: Dict) -> str:
#         parts = []
#         usage = features.get("usage_decline_pct") or 0
#         if usage < -20:
#             parts.append(f"API calls dropped {abs(usage):.0f}% over 6 months")
#         if features.get("on_deprecated_sdk"):
#             parts.append(f"{features.get('sdk_version')} is deprecated (patches end April 30)")
#         if features.get("on_vulnerable_sdk") and not features.get("on_deprecated_sdk"):
#             parts.append(f"{features.get('sdk_version')} has unpatched CVE-2026-1102")
#         nps = features.get("nps_score")
#         if nps is not None and nps <= 6:
#             parts.append(f"NPS of {int(nps)} is in detractor range")
#         if (features.get("p1_ticket_count") or 0) > 0:
#             parts.append(f"{features['p1_ticket_count']} open P1 ticket(s)")
#         if csm.get("competitive_threats"):
#             parts.append(f"evaluating {', '.join(csm['competitive_threats'])}")

#         if parts:
#             return (
#                 f"Risk drivers: {'; '.join(parts)}. "
#                 "Schedule an executive sponsor call within 5 business days."
#             )
#         return "No significant risk signals detected. Standard renewal process applies."


# # ------------------------------------------------------------------
# # Utility
# # ------------------------------------------------------------------

# def _strip_fences(text: str) -> str:
#     """Remove ```json ... ``` markdown wrappers from LLM output."""
#     if text.startswith("```"):
#         lines = text.split("\n")
#         lines = lines[1:] if lines[0].startswith("```") else lines
#         lines = lines[:-1] if lines and lines[-1].strip() == "```" else lines
#         text = "\n".join(lines).strip()
#     return text

"""
LLM-powered analysis using the OpenAI API.

Key settings:
- temperature=0.1  → near-deterministic, low hallucination risk
- All LLM outputs validated against source data before use
- Competitors/stakeholders verified against raw note text
"""

import json
from typing import Any, Dict, List

try:
    from openai import OpenAI
    _HAS_OPENAI = True
except ImportError:
    _HAS_OPENAI = False

try:
    from src.config import config
except ImportError:
    from config import config


KNOWN_COMPETITORS = {
    "contentful", "hygraph", "kontent.ai", "strapi", "sanity",
    "wordpress", "builder.io", "drupal", "prismic", "storyblok",
}


class LLMAnalyzer:
    """Uses an LLM to extract structured risk signals from unstructured data."""

    def __init__(self):
        self.client = None
        self._cache: Dict[str, Any] = {}

        if _HAS_OPENAI and config.openai_api_key:
            self.client = OpenAI(api_key=config.openai_api_key)
        else:
            print("  ⚠️  No API key found — running in mock mode.")

    # ------------------------------------------------------------------
    # Public methods
    # ------------------------------------------------------------------

    def analyze_csm_notes(
        self, account_id: int, notes: List[Dict], account_context: Dict
    ) -> Dict[str, Any]:
        """Extract structured risk signals from raw CSM notes for one account."""
        cache_key = f"csm_{account_id}"
        if cache_key in self._cache:
            return self._cache[cache_key]

        if not self.client or not notes:
            result = self._mock_analysis(account_id, notes)
            self._cache[cache_key] = result
            return result

        notes_text = "\n\n".join(
            f"[{n.get('date', 'Unknown date')}]: {n['content']}" for n in notes
        )
        raw_text = " ".join(n["content"] for n in notes).lower()

        prompt = f"""You are a Customer Success analyst. Analyze these CSM call notes for renewal risk.
Only extract information EXPLICITLY stated in the notes. Do not infer or assume anything.

ACCOUNT CONTEXT (ground truth from our systems):
- Name: {account_context.get('account_name', 'Unknown')}
- ARR: ${account_context.get('arr', 0):,.0f}
- Plan: {account_context.get('plan_tier', 'Unknown')}
- Industry: {account_context.get('industry', 'Unknown')}
- Days to Renewal: {account_context.get('days_to_renewal', 'Unknown')}
- SDK: {account_context.get('sdk_version', 'Unknown')} ({'DEPRECATED - patches end April 30 2026' if account_context.get('on_deprecated_sdk') else 'current'})
- Usage change (6-month API calls): {account_context.get('usage_decline_pct', 0):.1f}%
- NPS Score: {account_context.get('nps_score', 'N/A')}
- Open P1 Tickets: {account_context.get('p1_ticket_count', 0)}

PRODUCT CONTEXT (from changelog):
- SDK v3.x: security patches end April 30, 2026 — hard deadline
- REST API v2: sunset April 30, 2026 — no further extensions
- Legacy editor: removal May 2026
- CVE-2026-1102: unpatched in v4.0-v4.2.3, fixed only in v4.3.2

SENTIMENT SCORING RULES — READ CAREFULLY:
sentiment_score must reflect RENEWAL RISK, not surface politeness. Apply these rules:

1. SILENT CHURN PATTERN (score -0.7 or lower): Customer likes the support team or
   people but is actively migrating away, building alternatives, or reducing reliance
   on the product. Key phrases: "moving content to", "homegrown solution", "custom
   middleware", "usage has cratered", "silent churn", "score reflects the people not
   the product", "slowly migrating". A positive NPS paired with declining usage and
   migration language is HIGH RISK, not positive.

2. DECEPTIVE POSITIVES — do NOT let these raise the score above 0.0 if churn
   signals are present:
   - Customer likes "the support team" but not the product
   - High NPS score mentioned in notes (use the account context NPS, not the note's
     framing of it — a CSM noting "NPS came back at 8" while also flagging churn is
     still a churn signal)
   - Polite tone overall but with buried risk language

3. EXPLICIT HIGH-RISK LANGUAGE (score -0.5 or lower): "lost faith", "explore
   options", "evaluating alternatives", "want to walk", "budget cut", "no show",
   "tense call", "threatened to leave", "CTO/CRO/CISO joined unexpectedly",
   competitor named in context of a POC or evaluation.

4. GENUINE POSITIVES (score 0.5 or higher): Expansion confirmed, multi-year renewal
   signed, budget approved, champion actively advocating, seats being added.

5. DEFAULT: Neutral or mixed signals with no churn language → score between -0.2
   and 0.2.

CSM NOTES:
{notes_text}

STRICT RULES:
1. Only list competitors NAMED in the notes — do not add others
2. Only list executives/stakeholders MENTIONED in the notes — do not add others
3. Risk signals must be paraphrases of actual note content
4. If something is not in the notes, return an empty list

Return ONLY valid JSON, no markdown:
{{
  "sentiment_score": <float -1.0 to 1.0>,
  "risk_level": <"high"|"medium"|"low">,
  "risk_signals": [<max 5, direct evidence from notes>],
  "positive_signals": [<direct evidence or empty list>],
  "competitive_threats": [<only if explicitly named in notes>],
  "key_stakeholders_mentioned": [<only if explicitly mentioned>],
  "action_items": [<max 3 specific actions>],
  "summary": "<2-3 sentence factual summary>"
}}"""

        try:
            message = self.client.chat.completions.create(
                model=config.openai_model,
                max_tokens=1024,
                temperature=0.1,
                messages=[{"role": "user", "content": prompt}],
            )
            raw = _strip_fences(message.choices[0].message.content.strip())
            result = json.loads(raw)
            result = self._validate_analysis(result, raw_text)
            self._cache[cache_key] = result
            return result

        except Exception as e:
            print(f"  LLM error (account {account_id}): {e}")
            result = self._mock_analysis(account_id, notes)
            self._cache[cache_key] = result
            return result

    def generate_account_explanation(self, account: Dict, csm_analysis: Dict) -> str:
        """Generate a factual 3-4 sentence risk explanation."""
        cache_key = f"explain_{account['account_id']}"
        if cache_key in self._cache:
            return self._cache[cache_key]

        if not self.client:
            result = self._mock_explanation(account, csm_analysis)
            self._cache[cache_key] = result
            return result

        prompt = f"""Write a factual renewal risk summary for a BizOps/CS team.
Only use the data provided. Do not add information not present here.

ACCOUNT: {account['account_name']} | ARR: ${account['arr']:,.0f} | Renewal in {account['days_to_renewal']} days
RISK TIER: {account.get('risk_tier', 'Unknown')}

QUANTITATIVE SIGNALS:
- API call change (6 months): {account.get('usage_decline_pct', 0):.1f}%
- Active user change: {account.get('active_user_decline_pct', 0):.1f}%
- SDK: {account.get('sdk_version', '?')} {'DEPRECATED (patches end April 30)' if account.get('on_deprecated_sdk') else 'CVE-2026-1102 unpatched' if account.get('on_vulnerable_sdk') else 'current'}
- NPS: {account.get('nps_score', 'N/A')} {'(score contradicts comment — treat with caution)' if account.get('nps_anomaly') else ''}
- Open P1 tickets: {account.get('p1_ticket_count', 0)}
- Longest open ticket: {account.get('max_open_days', 0)} days
- Recurring issues: {account.get('recurring_count', 0)}

QUALITATIVE SIGNALS (from CSM notes):
- Sentiment: {csm_analysis.get('sentiment_score', 'N/A')} (-1.0 to 1.0)
- Risk signals: {'; '.join(csm_analysis.get('risk_signals', ['None']))}
- Competitors: {', '.join(csm_analysis.get('competitive_threats', ['None']))}
- Executives involved: {', '.join(csm_analysis.get('key_stakeholders_mentioned', ['None']))}
- CSM summary: {csm_analysis.get('summary', 'No notes')}

Write 3-4 sentences of plain prose:
1. Primary risk driver + specific evidence
2. One supporting data point
3. One action the team must take in the next 7 days
No bullet points. No hedging. No invented details."""

        try:
            message = self.client.chat.completions.create(
                model=config.openai_model,
                max_tokens=300,
                temperature=0.1,
                messages=[{"role": "user", "content": prompt}],
            )
            result = message.choices[0].message.content.strip()
            self._cache[cache_key] = result
            return result

        except Exception as e:
            print(f"  LLM explanation error (account {account['account_id']}): {e}")
            result = self._mock_explanation(account, csm_analysis)
            self._cache[cache_key] = result
            return result

    def detect_non_obvious_insights(
        self, all_features: Dict[int, Dict], all_csm: Dict[int, Dict]
    ) -> List[Dict]:
        """Identify cross-account patterns a rule engine would miss."""
        if not self.client:
            return []

        renewing = {
            aid: f for aid, f in all_features.items() if f.get("within_renewal_window")
        }

        summaries = []
        for aid, f in renewing.items():
            csm = all_csm.get(aid, {})
            nps = f.get("nps_score")
            summaries.append({
                "id":             int(aid),
                "name":           str(f.get("account_name") or ""),
                "arr":            float(f.get("arr") or 0),
                "plan":           str(f.get("plan_tier") or ""),
                "industry":       str(f.get("industry") or ""),
                "region":         str(f.get("region") or ""),
                "nps":            int(nps) if nps is not None else None,
                "nps_anomaly":    bool(f.get("nps_anomaly", False)),
                "nps_language":   str(f.get("nps_language") or "en"),
                "usage_6m_pct":   round(float(f.get("usage_decline_pct") or 0), 1),
                "sdk":            str(f.get("sdk_version") or ""),
                "deprecated_sdk": bool(f.get("on_deprecated_sdk", False)),
                "vulnerable_sdk": bool(f.get("on_vulnerable_sdk", False)),
                "p1_open":        int(f.get("p1_ticket_count") or 0),
                "max_open_days":  int(f.get("max_open_days") or 0),
                "csm_sentiment":  float(csm.get("sentiment_score") or 0),
                "competitors":    list(csm.get("competitive_threats", [])),
                "executives":     list(csm.get("key_stakeholders_mentioned", [])),
            })

        prompt = f"""You are a BizOps analyst. {len(renewing)} accounts renew in the next 90 days.
Find 3-4 non-obvious cross-account patterns supported by the data below.
Do NOT invent patterns — every claim must be traceable to specific rows in the data.

DATA:
{json.dumps(summaries, indent=2)}

Look for:
- Contradictory signals (high NPS + declining usage)
- Same competitor targeting multiple accounts
- Industry clusters with shared risk
- Non-English NPS comments
- C-suite involvement + negative sentiment
- High-ARR accounts with stale open tickets

Return ONLY valid JSON, no markdown:
{{
  "insights": [
    {{
      "title": "<specific title, max 8 words>",
      "description": "<2-3 sentences, every claim traceable to the data>",
      "affected_accounts": [<account IDs from data only>],
      "affected_account_names": [<matching account names>],
      "severity": "<critical|high|medium>",
      "action": "<one action, max 20 words>"
    }}
  ]
}}"""

        try:
            message = self.client.chat.completions.create(
                model=config.openai_model,
                max_tokens=1500,
                temperature=0.2,
                messages=[{"role": "user", "content": prompt}],
            )
            raw = _strip_fences(message.choices[0].message.content.strip())
            insights = json.loads(raw).get("insights", [])

            # Validate: only keep account IDs that actually exist
            valid_ids = set(renewing.keys())
            for ins in insights:
                ins["affected_accounts"] = [
                    aid for aid in ins.get("affected_accounts", [])
                    if aid in valid_ids
                ]
            return insights

        except Exception as e:
            print(f"  Insight detection error: {e}")
            return []

    # ------------------------------------------------------------------
    # Post-hoc validation — removes hallucinated values
    # ------------------------------------------------------------------

    def _validate_analysis(self, result: Dict, raw_notes_text: str) -> Dict:
        """Remove competitors/stakeholders not found in the raw note text."""
        result["competitive_threats"] = [
            c for c in result.get("competitive_threats", [])
            if c.lower() in raw_notes_text
            or any(w in raw_notes_text for w in c.lower().split() if len(w) > 3)
        ]
        result["key_stakeholders_mentioned"] = [
            s for s in result.get("key_stakeholders_mentioned", [])
            if s.lower() in raw_notes_text
            or s.lower().replace(" of ", " ") in raw_notes_text
        ]
        score = result.get("sentiment_score", 0.0)
        try:
            result["sentiment_score"] = round(max(-1.0, min(1.0, float(score))), 3)
        except (TypeError, ValueError):
            result["sentiment_score"] = 0.0
        return result

    # ------------------------------------------------------------------
    # Mock fallbacks (no API key)
    # ------------------------------------------------------------------

    def _mock_analysis(self, account_id: int, notes: List[Dict]) -> Dict:
        if not notes:
            return {
                "sentiment_score": 0.0, "risk_level": "low",
                "risk_signals": [], "positive_signals": [],
                "competitive_threats": [], "key_stakeholders_mentioned": [],
                "action_items": ["Review account — no CSM notes available"],
                "summary": "No CSM notes found for this account.",
            }

        text = " ".join(n["content"].lower() for n in notes)
        original = " ".join(n["content"] for n in notes)

        neg_kw = ["frustrated", "threatened", "evaluating", "furious", "lost faith",
                  "walk", "tense", "no show", "budget cut", "escalate",
                  "broken", "failed", "stuck", "angry", "churn", "downgrade",
                  # Silent churn / migration signals
                  "cratered", "homegrown", "middleware", "migrating", "migration",
                  "moving content", "slowly moving", "explore options", "embarrassing",
                  "fence", "contraction", "shelfware", "barely use", "under review",
                  "missed qbr", "no response", "compliance", "dealbreaker"]
        pos_kw = ["love", "great", "excellent", "expansion", "champagne",
                  "locked in", "formality", "adding seats", "early access", "happy"]

        n_neg = sum(1 for kw in neg_kw if kw in text)
        n_pos = sum(1 for kw in pos_kw if kw in text)

        total = n_neg + n_pos
        if total == 0:
            sentiment = 0.0
        else:
            raw = (n_pos - n_neg) / total
            damp = min(len(notes) / 5.0, 1.0)
            sentiment = round(raw * damp, 3)

        competitors = [
            c for c in ["Contentful", "Hygraph", "Kontent.ai", "Strapi", "Sanity",
                        "WordPress", "builder.io", "Drupal"]
            if c.lower() in text
        ]

        execs = []
        for title in ["CTO", "CRO", "CISO", "CEO", "CFO",
                      "VP of Engineering", "VP of Product",
                      "VP of Digital", "VP of Marketing"]:
            if title in original or title.lower() in text:
                execs.append(title)

        if n_neg > 2:
            risk = "high"
        elif n_neg > 0:
            risk = "medium"
        elif n_pos > 0:
            risk = "low"
        else:
            risk = "medium"

        return {
            "sentiment_score":            sentiment,
            "risk_level":                 risk,
            "risk_signals":               [f"{n_neg} negative signal(s) in notes"] if n_neg else [],
            "positive_signals":           [f"{n_pos} positive signal(s) in notes"] if n_pos else [],
            "competitive_threats":        competitors,
            "key_stakeholders_mentioned": execs,
            "action_items":               ["Review full CSM notes (mock mode — add API key for full analysis)"],
            "summary":                    " | ".join(n["content"][:80] for n in notes[:2]),
        }

    def _mock_explanation(self, features: Dict, csm: Dict) -> str:
        parts = []
        usage = features.get("usage_decline_pct") or 0
        if usage < -20:
            parts.append(f"API calls dropped {abs(usage):.0f}% over 6 months")
        if features.get("on_deprecated_sdk"):
            parts.append(f"{features.get('sdk_version')} is deprecated (patches end April 30)")
        if features.get("on_vulnerable_sdk") and not features.get("on_deprecated_sdk"):
            parts.append(f"{features.get('sdk_version')} has unpatched CVE-2026-1102")
        nps = features.get("nps_score")
        if nps is not None and nps <= 6:
            parts.append(f"NPS of {int(nps)} is in detractor range")
        if (features.get("p1_ticket_count") or 0) > 0:
            parts.append(f"{features['p1_ticket_count']} open P1 ticket(s)")
        if csm.get("competitive_threats"):
            parts.append(f"evaluating {', '.join(csm['competitive_threats'])}")

        if parts:
            return (
                f"Risk drivers: {'; '.join(parts)}. "
                "Schedule an executive sponsor call within 5 business days."
            )
        return "No significant risk signals detected. Standard renewal process applies."


# ------------------------------------------------------------------
# Utility
# ------------------------------------------------------------------

def _strip_fences(text: str) -> str:
    """Remove ```json ... ``` markdown wrappers from LLM output."""
    if text.startswith("```"):
        lines = text.split("\n")
        lines = lines[1:] if lines[0].startswith("```") else lines
        lines = lines[:-1] if lines and lines[-1].strip() == "```" else lines
        text = "\n".join(lines).strip()
    return text
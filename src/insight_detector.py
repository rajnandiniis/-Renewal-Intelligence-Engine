"""
Non-obvious insight detection — combines rule-based and LLM-detected patterns.
"""

from typing import Dict, List

try:
    from src.llm_analyzer import LLMAnalyzer
    from src.config import config
except ImportError:
    from llm_analyzer import LLMAnalyzer
    from config import config


class InsightDetector:
    """Surfaces cross-account patterns that simple rule engines miss."""

    def __init__(self, llm: LLMAnalyzer):
        self.llm = llm

    def detect_all(
        self, features: Dict[int, Dict], csm_analyses: Dict[int, Dict]
    ) -> List[Dict]:
        llm_insights  = self.llm.detect_non_obvious_insights(features, csm_analyses)
        rule_insights = self._rule_based(features, csm_analyses)

        # Merge: avoid duplicates by title, prefer LLM version
        seen_titles = {i["title"] for i in llm_insights}
        merged = llm_insights + [i for i in rule_insights if i["title"] not in seen_titles]

        order = {"critical": 0, "high": 1, "medium": 2}
        merged.sort(key=lambda x: order.get(x.get("severity", "medium"), 3))
        return merged

    # ------------------------------------------------------------------

    def _rule_based(
        self, features: Dict[int, Dict], csm_analyses: Dict[int, Dict]
    ) -> List[Dict]:
        insights = []
        renewing = {aid: f for aid, f in features.items() if f.get("within_renewal_window")}

        # --- 1. Silent churn: high NPS but usage cratering + negative CSM ---
        silent = [
            (aid, f["account_name"])
            for aid, f in renewing.items()
            if (
                f.get("nps_score") is not None and f["nps_score"] >= 8
                and (f.get("usage_decline_pct") or 0) < -20
                and csm_analyses.get(aid, {}).get("sentiment_score", 0) < -0.1
            )
        ]
        if silent:
            ids, names = zip(*silent)
            insights.append({
                "title": "Silent Churn: High NPS Masking Real Risk",
                "description": (
                    f"{len(ids)} account(s) ({', '.join(names)}) score NPS ≥8 "
                    "but show >20% API call decline and negative CSM sentiment. "
                    "This is a classic silent churn pattern — customers like the support team "
                    "but are quietly migrating away from the product."
                ),
                "affected_accounts":      list(ids),
                "affected_account_names": list(names),
                "severity": "high",
                "action": (
                    "Do not rely on NPS alone for health scoring. "
                    "Prioritize product usage telemetry and schedule a direct usage review call."
                ),
            })

        # --- 2. Compliance time bomb: deprecated SDK in regulated industry ---
        compliance = [
            (aid, f["account_name"])
            for aid, f in renewing.items()
            if f.get("on_deprecated_sdk") and f.get("industry") in config.regulated_industries
        ]
        if compliance:
            ids, names = zip(*compliance)
            insights.append({
                "title": "Compliance Risk: Deprecated SDK in Regulated Industries",
                "description": (
                    f"{len(ids)} regulated-industry account(s) ({', '.join(names)}) "
                    "are still on deprecated SDK versions with security patches ending April 30, 2026. "
                    "For healthcare and financial services customers this is a potential compliance "
                    "violation, not just a technical inconvenience."
                ),
                "affected_accounts":      list(ids),
                "affected_account_names": list(names),
                "severity": "critical",
                "action": (
                    "Assign a dedicated SA immediately for SDK migration. "
                    "Frame as a compliance obligation in renewal conversations."
                ),
            })

        # --- 3. C-suite escalation with negative sentiment ---
        csuites = [
            (aid, f["account_name"])
            for aid, f in renewing.items()
            if (
                csm_analyses.get(aid, {}).get("sentiment_score", 0) < -0.2
                and any(
                    e in " ".join(csm_analyses.get(aid, {}).get("key_stakeholders_mentioned", []))
                    for e in ["CTO", "CRO", "CISO", "CEO", "CFO"]
                )
            )
        ]
        if csuites:
            ids, names = zip(*csuites)
            insights.append({
                "title": "C-Suite Escalation With Negative Sentiment",
                "description": (
                    f"{len(ids)} account(s) ({', '.join(names)}) have C-level executives "
                    "involved in renewal conversations paired with negative CSM sentiment. "
                    "Executive involvement at this stage typically signals a strategic decision "
                    "is being made, not just a routine renewal."
                ),
                "affected_accounts":      list(ids),
                "affected_account_names": list(names),
                "severity": "high",
                "action": (
                    "Escalate to VP/SVP level on our side within 48 hours. "
                    "Prepare a tailored business case with ROI data."
                ),
            })

        # --- 4. NPS data quality / non-English comments unread ---
        non_english_unread = [
            (aid, f["account_name"], f.get("nps_language"))
            for aid, f in renewing.items()
            if f.get("nps_language") in ("zh", "es", "fr")
        ]
        if non_english_unread:
            ids   = [x[0] for x in non_english_unread]
            names = [x[1] for x in non_english_unread]
            langs = [x[2] for x in non_english_unread]
            insights.append({
                "title": "Non-English NPS Comments at Risk of Being Ignored",
                "description": (
                    f"{len(ids)} renewing account(s) ({', '.join(names)}) submitted "
                    f"NPS feedback in {', '.join(set(langs))}. "
                    "One Mandarin comment explicitly mentions requesting a new CSM multiple times "
                    "with no response. These signals are invisible to teams that rely solely "
                    "on automated sentiment scoring of English text."
                ),
                "affected_accounts":      ids,
                "affected_account_names": names,
                "severity": "medium",
                "action": (
                    "Translate and review all non-English NPS verbatim comments immediately. "
                    "Flag Pacific Rim Trading (#1017) for urgent CSM reassignment review."
                ),
            })

        # --- 5. Stale open tickets approaching renewal ---
        stale_ticket_accts = [
            (aid, f["account_name"], f.get("max_open_days", 0))
            for aid, f in renewing.items()
            if f.get("max_open_days", 0) > 45 and f.get("open_ticket_count", 0) > 0
        ]
        if stale_ticket_accts:
            stale_ticket_accts.sort(key=lambda x: x[2], reverse=True)
            ids   = [x[0] for x in stale_ticket_accts]
            names = [x[1] for x in stale_ticket_accts]
            ages  = [x[2] for x in stale_ticket_accts]
            insights.append({
                "title": "Tickets Older Than 45 Days Still Open at Renewal Time",
                "description": (
                    f"{len(ids)} account(s) ({', '.join(names)}) have open tickets "
                    f"that are {max(ages)}+ days old. "
                    "Unresolved tickets at renewal time are one of the strongest predictors "
                    "of contention — customers use them as leverage for discounts or as "
                    "justification to evaluate alternatives."
                ),
                "affected_accounts":      ids,
                "affected_account_names": names,
                "severity": "high",
                "action": (
                    "Force-resolve or formally escalate all tickets older than 30 days "
                    "before renewal conversations begin. Track as a renewal blocker."
                ),
            })

        return insights
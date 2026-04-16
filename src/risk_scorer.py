"""
Risk scoring — computes a composite 0-1 risk score and assigns tiers.
"""

from typing import Dict, List

try:
    from src.config import config
except ImportError:
    from config import config


class RiskScorer:
    """Weighted composite risk scorer."""

    def __init__(self, weights: Dict[str, float] = None):
        self.weights = weights or config.weights

    # ------------------------------------------------------------------

    def compute_risk_score(self, features: Dict, csm: Dict) -> float:
        """Return composite risk score in [0, 1]."""
        if not features.get("within_renewal_window"):
            return 0.0

        components: Dict[str, float] = {}

        # 1. Usage decline (25%)
        decline = features.get("usage_decline_pct", 0.0) or 0.0
        if decline < -50:
            components["usage_decline"] = 1.0
        elif decline < -30:
            components["usage_decline"] = 0.80
        elif decline < -15:
            components["usage_decline"] = 0.55
        elif decline < 0:
            components["usage_decline"] = 0.25
        else:
            components["usage_decline"] = 0.0

        # 2. Ticket severity (20%)
        components["ticket_severity"] = features.get("ticket_severity_score", 0.0)

        # 3. SDK deprecation + security vulnerability (15% combined)
        dep_risk  = features.get("sdk_deprecation_risk", 0.0)
        sec_risk  = features.get("security_risk", 0.0)
        # Regulated-industry amplifier
        if features.get("industry") in config.regulated_industries:
            dep_risk = min(dep_risk * 1.25, 1.0)
            sec_risk = min(sec_risk * 1.25, 1.0)
        components["sdk_deprecation"] = min(dep_risk + sec_risk * 0.4, 1.0)

        # 4. NPS signal (10%)
        if features.get("nps_anomaly"):
            # Anomaly — score is unreliable; treat as mild risk not high
            components["nps_signal"] = 0.35
        else:
            components["nps_signal"] = features.get("nps_risk_signal", 0.0)

        # 5. CSM sentiment (20%)
        sentiment = csm.get("sentiment_score", 0.0) or 0.0
        if sentiment < -0.6:
            components["csm_sentiment"] = 1.0
        elif sentiment < -0.3:
            components["csm_sentiment"] = 0.75
        elif sentiment < 0:
            components["csm_sentiment"] = 0.45
        else:
            components["csm_sentiment"] = 0.0

        # 6. Days to renewal urgency (10%)
        components["days_to_renewal"] = features.get("renewal_urgency", 0.0)

        # Weighted sum
        score = sum(self.weights.get(k, 0) * v for k, v in components.items())

        # Situational bonuses (additive, capped at 1.0)
        if csm.get("competitive_threats"):
            score += 0.08   # Active competitive evaluation

        executive_roles = {"CTO", "CRO", "CISO", "CEO", "CFO"}
        stakeholders = set(csm.get("key_stakeholders_mentioned", []))
        if stakeholders & executive_roles and sentiment < 0:
            score += 0.06   # C-suite involvement with negative sentiment

        if features.get("nps_language") in ("zh", "es", "fr") and features.get("nps_anomaly"):
            score += 0.04   # Non-English NPS that flagged anomalous — extra uncertainty

        return round(min(score, 1.0), 4)

    def assign_tier(self, score: float) -> str:
        if score >= config.high_risk_threshold:
            return "High"
        if score >= config.medium_risk_threshold:
            return "Medium"
        return "Low"

    def score_all_accounts(
        self, features: Dict[int, Dict], csm_analyses: Dict[int, Dict]
    ) -> List[Dict]:
        """Score all renewing accounts and return sorted by descending risk."""
        scored = []
        for aid, f in features.items():
            if not f.get("within_renewal_window"):
                continue
            csm   = csm_analyses.get(aid, {})
            score = self.compute_risk_score(f, csm)
            tier  = self.assign_tier(score)

            f["risk_score"]  = score
            f["risk_tier"]   = tier
            f["csm_analysis"] = csm
            scored.append(f)

        scored.sort(key=lambda x: x["risk_score"], reverse=True)
        return scored

    def get_arr_at_risk(self, scored: List[Dict]) -> Dict[str, float]:
        result = {"High": 0.0, "Medium": 0.0, "Low": 0.0, "Total": 0.0}
        for a in scored:
            t = a.get("risk_tier", "Low")
            arr = a.get("arr", 0.0) or 0.0
            result[t]       += arr
            result["Total"] += arr
        return result

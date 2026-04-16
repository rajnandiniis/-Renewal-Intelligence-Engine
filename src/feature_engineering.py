"""
Feature engineering — computes risk signals for every account.
"""

import pandas as pd
import numpy as np
from typing import Any, Dict, List

try:
    from src.config import config
except ImportError:
    from config import config


class FeatureEngineering:
    """Computes all measurable risk features per account."""

    def __init__(self, reconciled_data: Dict):
        self.data = reconciled_data
        self.reference_date = pd.Timestamp(config.reference_date)
        self.features: Dict[int, Dict[str, Any]] = {}

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def compute_all_features(self) -> Dict[int, Dict[str, Any]]:
        for _, account in self.data["accounts"].iterrows():
            aid = int(account["account_id"])
            self.features[aid] = {
                "account_id":         aid,
                "account_name":       account["account_name"],
                "arr":                float(account["arr"]) if pd.notna(account["arr"]) else 0.0,
                "plan_tier":          account["plan_tier"],
                "industry":           account["industry"],
                "csm_name":           account["csm_name"],
                "region":             account["region"],
                "contract_end_date":  account["contract_end_date"],
            }
            self._renewal_features(aid, account)
            self._usage_features(aid)
            self._ticket_features(aid)
            self._nps_features(aid)
            self._sdk_features(aid)
            self._csm_base_features(aid)

        return self.features

    def get_renewing_accounts(self) -> List[Dict]:
        return [f for f in self.features.values() if f.get("within_renewal_window")]

    # ------------------------------------------------------------------
    # Feature groups
    # ------------------------------------------------------------------

    def _renewal_features(self, aid: int, account: pd.Series) -> None:
        end = account["contract_end_date"]
        days = (end - self.reference_date).days

        if days < 0:
            urgency = 1.0
        elif days < 30:
            urgency = 0.90
        elif days < 60:
            urgency = 0.70
        elif days < 90:
            urgency = 0.50
        else:
            urgency = 0.0

        self.features[aid].update({
            "days_to_renewal":       days,
            "within_renewal_window": 0 <= days <= config.renewal_window_days,
            "renewal_urgency":       urgency,
        })

    def _usage_features(self, aid: int) -> None:
        usage = (
            self.data["usage_metrics"][self.data["usage_metrics"]["account_id"] == aid]
            .sort_values("month")
        )

        defaults = {
            "usage_decline_pct":        0.0,
            "active_user_decline_pct":  0.0,
            "current_api_calls":        0,
            "sdk_version":              "unknown",
            "on_deprecated_sdk":        False,
            "on_vulnerable_sdk":        False,
            "usage_trend_score":        0.0,
        }

        if len(usage) < 2:
            self.features[aid].update(defaults)
            return

        first = usage.iloc[0]
        last  = usage.iloc[-1]

        def safe_pct(new, old):
            old_val = old if pd.notna(old) and old != 0 else np.nan
            if pd.isna(old_val) or pd.isna(new):
                return 0.0
            return float((new - old_val) / abs(old_val) * 100)

        api_decline  = safe_pct(last["api_calls"],    first["api_calls"])
        user_decline = safe_pct(last["active_users"], first["active_users"])

        sdk = str(last["sdk_version"])
        dep_info = self.data["deprecation_info"]

        self.features[aid].update({
            "usage_decline_pct":        api_decline,
            "active_user_decline_pct":  user_decline,
            "current_api_calls":        int(last["api_calls"]) if pd.notna(last["api_calls"]) else 0,
            "sdk_version":              sdk,
            "on_deprecated_sdk":        sdk in dep_info["deprecated_sdks"],
            "on_vulnerable_sdk":        sdk in dep_info["vulnerable_sdks"],
            # 0-1 score: 1 = severe decline
            "usage_trend_score":        min(max(-api_decline / 100, 0.0), 1.0),
        })

    def _ticket_features(self, aid: int) -> None:
        tkts = self.data["support_tickets"][self.data["support_tickets"]["account_id"] == aid]

        if len(tkts) == 0:
            self.features[aid].update({
                "ticket_count":         0,
                "p1_ticket_count":      0,
                "open_ticket_count":    0,
                "escalated_count":      0,
                "recurring_count":      0,
                "avg_resolution_hours": 0.0,
                "max_open_days":        0,
                "ticket_severity_score": 0.0,
            })
            return

        p1_open = tkts[(tkts["priority"] == "P1") & (tkts["status"].isin(["Open", "Escalated"]))]
        open_t  = tkts[tkts["status"] == "Open"].copy()
        open_t["days_open"] = (self.reference_date - open_t["created_date"]).dt.days.fillna(0)
        max_open_days = int(open_t["days_open"].max()) if len(open_t) else 0

        escalated = len(tkts[tkts["status"] == "Escalated"])
        recurring = tkts["description"].str.contains("Recurring|recurring", na=False).sum()

        resolved = tkts[tkts["resolution_time_hours"].notna()]
        avg_res = float(resolved["resolution_time_hours"].mean()) if len(resolved) else 0.0

        # Severity score 0-1
        severity = (
            min(len(p1_open)  * 0.18, 0.45) +
            min(len(open_t)   * 0.06, 0.25) +
            min(escalated     * 0.10, 0.20) +
            min(int(recurring)* 0.05, 0.15) +
            min(max_open_days / 200, 0.15)   # stale tickets signal slow resolution
        )

        self.features[aid].update({
            "ticket_count":          len(tkts),
            "p1_ticket_count":       len(p1_open),
            "open_ticket_count":     len(open_t),
            "escalated_count":       escalated,
            "recurring_count":       int(recurring),
            "avg_resolution_hours":  avg_res,
            "max_open_days":         max_open_days,
            "ticket_severity_score": min(severity, 1.0),
        })

    def _nps_features(self, aid: int) -> None:
        nps = self.data["nps_responses"][self.data["nps_responses"]["account_id"] == aid]

        if len(nps) == 0:
            self.features[aid].update({
                "nps_score":    None,
                "nps_comment":  "",
                "nps_language": "none",
                "nps_anomaly":  False,
                "nps_risk_signal": 0.0,
            })
            return

        row     = nps.iloc[0]
        score   = row["score"] if pd.notna(row["score"]) else None
        comment = str(row["verbatim_comment"])
        lang    = row["comment_language"]
        anomaly = self._detect_nps_anomaly(score, comment) if score is not None else False

        if score is None:
            nps_risk = 0.0
        elif score <= 6:
            nps_risk = 0.85
        elif score <= 8:
            nps_risk = 0.40
        else:
            nps_risk = 0.10

        # Halve the NPS weight when anomaly is detected (data quality issue)
        if anomaly:
            nps_risk *= 0.5

        self.features[aid].update({
            "nps_score":       score,
            "nps_comment":     comment,
            "nps_language":    lang,
            "nps_anomaly":     anomaly,
            "nps_risk_signal": nps_risk,
        })

    @staticmethod
    def _detect_nps_anomaly(score: float, comment: str) -> bool:
        """Flag when score and comment sentiment clearly contradict each other."""
        if not comment or comment == "nan":
            return False
        tl = comment.lower()
        pos = ["love", "great", "best", "excellent", "amazing", "recommend", "phenomenal", "fantastic"]
        neg = ["hate", "terrible", "worst", "frustrat", "downgrade", "waste", "slow",
               "inexistent", "pas intuitive", "falling off", "embarrass", "disappointed",
               "lost faith", "不好", "太低"]  # Chinese negatives
        p = sum(1 for w in pos if w in tl)
        n = sum(1 for w in neg if w in tl)

        if score >= 9 and n > p:
            return True
        if score <= 3 and p > n:
            return True
        return False

    def _sdk_features(self, aid: int) -> None:
        """Compute SDK risk — separate deprecated vs security-vulnerable."""
        f = self.features[aid]
        on_deprecated = f.get("on_deprecated_sdk", False)
        on_vulnerable = f.get("on_vulnerable_sdk", False)

        cutoff = pd.Timestamp(self.data["deprecation_info"]["sdk_cutoff_date"])
        days_to_cutoff = (cutoff - self.reference_date).days

        if on_deprecated:
            if days_to_cutoff <= 0:
                sdk_risk = 1.0
            elif days_to_cutoff <= 15:
                sdk_risk = 0.95
            elif days_to_cutoff <= 30:
                sdk_risk = 0.80
            else:
                sdk_risk = 0.60
        else:
            sdk_risk = 0.0

        # Security risk is additive but separate — CVE-2026-1102
        security_risk = 0.30 if on_vulnerable else 0.0

        self.features[aid].update({
            "sdk_deprecation_risk": sdk_risk,
            "security_risk":        security_risk,
        })

    def _csm_base_features(self, aid: int) -> None:
        """Seed CSM features — enriched later by LLMAnalyzer."""
        notes = self.data["csm_notes_by_account"].get(aid, [])
        self.features[aid].update({
            "has_csm_notes":       len(notes) > 0,
            "csm_notes":           notes,
            "csm_sentiment_score": 0.0,
            "csm_risk_signals":    [],
            "csm_action_items":    [],
            "competitive_threats": [],
            "key_stakeholders":    [],
        })
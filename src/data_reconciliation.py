"""
Data reconciliation — matches CSM notes and NPS entries to canonical account IDs.
"""

import re
from difflib import get_close_matches
from typing import Dict, List, Optional

try:
    from src.data_ingestion import DataIngestion
    from src.config import config
except ImportError:
    from data_ingestion import DataIngestion
    from config import config


# Manual corrections for known typos in CSM notes
_NAME_CORRECTIONS: Dict[str, str] = {
    "britepath solutions":  "brightpath solutions",
    "pinacle media":        "pinnacle media group",
    "meridan health":       "meridian health",
    "thunderbolt moters":   "thunderbolt motors",
    "harbourside dining":   "harbourside dining group",
}


class DataReconciliation:
    """Matches CSM notes and other unstructured data to account records."""

    def __init__(self, ingestion: DataIngestion):
        self.ingestion = ingestion
        self.account_lookup: Dict[int, str] = {}   # id → name
        self.name_to_id: Dict[str, int] = {}       # lower(name) → id
        self.reconciled_notes: List[Dict] = []

        self._build_lookups()

    # ------------------------------------------------------------------

    def _build_lookups(self) -> None:
        if self.ingestion.accounts is not None:
            for _, row in self.ingestion.accounts.iterrows():
                self.account_lookup[int(row["account_id"])] = row["account_name"]
                self.name_to_id[row["account_name"].lower().strip()] = int(row["account_id"])

    def reconcile_csm_notes(self) -> List[Dict]:
        """Match every CSM note to a canonical account_id."""
        reconciled = []

        for note in self.ingestion.csm_notes:
            result = note.copy()

            # 1. Already has a numeric account_id in the note
            if note.get("account_id") and note["account_id"] in self.account_lookup:
                result["match_strategy"] = "direct_id"
                result["confidence"] = 1.0
                reconciled.append(result)
                continue

            # 2. Has a parsed account_name → try matching
            if note.get("account_name"):
                matched_id = self._match_name(note["account_name"])
                if matched_id:
                    result["account_id"] = matched_id
                    result["match_strategy"] = "name_match"
                    result["confidence"] = (
                        1.0 if note["account_name"].lower().strip() in self.name_to_id
                        else 0.85
                    )
                    reconciled.append(result)
                    continue

            # 3. Scan the raw content for an account id or name
            content_id = self._extract_from_content(note["content"])
            if content_id:
                result["account_id"] = content_id
                result["match_strategy"] = "content_scan"
                result["confidence"] = 0.70
                reconciled.append(result)
                continue

            result["match_strategy"] = "unmatched"
            result["confidence"] = 0.0
            reconciled.append(result)

        self.reconciled_notes = reconciled
        matched = sum(1 for n in reconciled if n.get("account_id"))
        print(f"  CSM notes reconciled: {matched}/{len(reconciled)} matched")
        return reconciled

    # ------------------------------------------------------------------

    def _match_name(self, raw_name: str) -> Optional[int]:
        """Return account_id for best-matching name, or None."""
        name = raw_name.lower().strip()

        # Direct hit
        if name in self.name_to_id:
            return self.name_to_id[name]

        # Known typo correction
        corrected = _NAME_CORRECTIONS.get(name)
        if corrected and corrected in self.name_to_id:
            return self.name_to_id[corrected]

        # Fuzzy match (difflib)
        candidates = list(self.name_to_id.keys())
        close = get_close_matches(name, candidates, n=1, cutoff=0.72)
        if close:
            return self.name_to_id[close[0]]

        # First-word fallback (e.g. "Acme" → "Acme Corp")
        first = name.split()[0] if name else ""
        for acc_name, acc_id in self.name_to_id.items():
            if first and acc_name.startswith(first):
                return acc_id

        return None

    def _extract_from_content(self, content: str) -> Optional[int]:
        """Scan raw note text for numeric account IDs or company name mentions."""
        # Numeric ID references
        for pat in [r"acct\s*#?\s*(\d{4})", r"account\s*(\d{4})", r"#(\d{4})", r"\((\d{4})\)"]:
            m = re.search(pat, content, re.IGNORECASE)
            if m:
                pid = int(m.group(1))
                if pid in self.account_lookup:
                    return pid

        # Company name mentions anywhere in the text
        content_lower = content.lower()
        for acc_name, acc_id in self.name_to_id.items():
            # Use the first distinctive word (≥5 chars) to avoid false matches
            first_word = acc_name.split()[0]
            if len(first_word) >= 5 and first_word in content_lower:
                return acc_id

        return None

    # ------------------------------------------------------------------

    def get_reconciled_data(self) -> Dict:
        """Return a single dict of all data keyed by account, ready for feature engineering."""
        csm_by_account: Dict[int, List[Dict]] = {}
        for note in self.reconciled_notes:
            aid = note.get("account_id")
            if aid:
                csm_by_account.setdefault(int(aid), []).append(note)

        return {
            "accounts":           self.ingestion.accounts,
            "usage_metrics":      self.ingestion.usage_metrics,
            "support_tickets":    self.ingestion.support_tickets,
            "nps_responses":      self.ingestion.nps_responses,
            "csm_notes_by_account": csm_by_account,
            "deprecation_info":   self.ingestion.get_deprecation_info(),
        }
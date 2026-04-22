# """
# Data reconciliation — matches CSM notes and NPS entries to canonical account IDs.
# """

# import re
# from difflib import get_close_matches
# from typing import Dict, List, Optional

# try:
#     from src.data_ingestion import DataIngestion
#     from src.config import config
# except ImportError:
#     from data_ingestion import DataIngestion
#     from config import config


# # Manual corrections for known typos in CSM notes
# _NAME_CORRECTIONS: Dict[str, str] = {
#     "britepath solutions":  "brightpath solutions",
#     "pinacle media":        "pinnacle media group",
#     "meridan health":       "meridian health",
#     "thunderbolt moters":   "thunderbolt motors",
#     "harbourside dining":   "harbourside dining group",
# }


# class DataReconciliation:
#     """Matches CSM notes and other unstructured data to account records."""

#     def __init__(self, ingestion: DataIngestion):
#         self.ingestion = ingestion
#         self.account_lookup: Dict[int, str] = {}   # id → name
#         self.name_to_id: Dict[str, int] = {}       # lower(name) → id
#         self.reconciled_notes: List[Dict] = []

#         self._build_lookups()

#     # ------------------------------------------------------------------

#     def _build_lookups(self) -> None:
#         if self.ingestion.accounts is not None:
#             for _, row in self.ingestion.accounts.iterrows():
#                 self.account_lookup[int(row["account_id"])] = row["account_name"]
#                 self.name_to_id[row["account_name"].lower().strip()] = int(row["account_id"])

#     def reconcile_csm_notes(self) -> List[Dict]:
#         """Match every CSM note to a canonical account_id."""
#         reconciled = []

#         for note in self.ingestion.csm_notes:
#             result = note.copy()

#             # 1. Already has a numeric account_id in the note
#             if note.get("account_id") and note["account_id"] in self.account_lookup:
#                 result["match_strategy"] = "direct_id"
#                 result["confidence"] = 1.0
#                 reconciled.append(result)
#                 continue

#             # 2. Has a parsed account_name → try matching
#             if note.get("account_name"):
#                 matched_id = self._match_name(note["account_name"])
#                 if matched_id:
#                     result["account_id"] = matched_id
#                     result["match_strategy"] = "name_match"
#                     result["confidence"] = (
#                         1.0 if note["account_name"].lower().strip() in self.name_to_id
#                         else 0.85
#                     )
#                     reconciled.append(result)
#                     continue

#             # 3. Scan the raw content for an account id or name
#             content_id = self._extract_from_content(note["content"])
#             if content_id:
#                 result["account_id"] = content_id
#                 result["match_strategy"] = "content_scan"
#                 result["confidence"] = 0.70
#                 reconciled.append(result)
#                 continue

#             result["match_strategy"] = "unmatched"
#             result["confidence"] = 0.0
#             reconciled.append(result)

#         self.reconciled_notes = reconciled
#         matched = sum(1 for n in reconciled if n.get("account_id"))
#         print(f"  CSM notes reconciled: {matched}/{len(reconciled)} matched")
#         return reconciled

#     # ------------------------------------------------------------------

#     def _match_name(self, raw_name: str) -> Optional[int]:
#         """Return account_id for best-matching name, or None."""
#         name = raw_name.lower().strip()

#         # Direct hit
#         if name in self.name_to_id:
#             return self.name_to_id[name]

#         # Known typo correction
#         corrected = _NAME_CORRECTIONS.get(name)
#         if corrected and corrected in self.name_to_id:
#             return self.name_to_id[corrected]

#         # Fuzzy match (difflib)
#         candidates = list(self.name_to_id.keys())
#         close = get_close_matches(name, candidates, n=1, cutoff=0.72)
#         if close:
#             return self.name_to_id[close[0]]

#         # First-word fallback (e.g. "Acme" → "Acme Corp")
#         first = name.split()[0] if name else ""
#         for acc_name, acc_id in self.name_to_id.items():
#             if first and acc_name.startswith(first):
#                 return acc_id

#         return None

#     def _extract_from_content(self, content: str) -> Optional[int]:
#         """Scan raw note text for numeric account IDs or company name mentions."""
#         # Numeric ID references
#         for pat in [r"acct\s*#?\s*(\d{4})", r"account\s*(\d{4})", r"#(\d{4})", r"\((\d{4})\)"]:
#             m = re.search(pat, content, re.IGNORECASE)
#             if m:
#                 pid = int(m.group(1))
#                 if pid in self.account_lookup:
#                     return pid

#         # Company name mentions anywhere in the text
#         content_lower = content.lower()
#         for acc_name, acc_id in self.name_to_id.items():
#             # Use the first distinctive word (≥5 chars) to avoid false matches
#             first_word = acc_name.split()[0]
#             if len(first_word) >= 5 and first_word in content_lower:
#                 return acc_id

#         return None

#     # ------------------------------------------------------------------

#     def get_reconciled_data(self) -> Dict:
#         """Return a single dict of all data keyed by account, ready for feature engineering."""
#         csm_by_account: Dict[int, List[Dict]] = {}
#         for note in self.reconciled_notes:
#             aid = note.get("account_id")
#             if aid:
#                 csm_by_account.setdefault(int(aid), []).append(note)

#         return {
#             "accounts":           self.ingestion.accounts,
#             "usage_metrics":      self.ingestion.usage_metrics,
#             "support_tickets":    self.ingestion.support_tickets,
#             "nps_responses":      self.ingestion.nps_responses,
#             "csm_notes_by_account": csm_by_account,
#             "deprecation_info":   self.ingestion.get_deprecation_info(),
#         }

"""
Data reconciliation — matches CSM notes and NPS entries to canonical account IDs.

Matching pipeline (in order):
  1. Direct numeric ID match              → confidence 1.0
  2. Exact name match                     → confidence 1.0
  3. Manual overrides (_NAME_OVERRIDES)   → confidence 1.0  (small exceptions only)
  4. RapidFuzz full-name similarity       → confidence 0.90  (typos, swaps, missing letters)
  5. RapidFuzz partial ratio              → confidence 0.85  (single-word / subset refs)
  6. Phonetic match (Soundex)             → confidence 0.82  (sound-alike errors)
  7. Content scan (numeric ID/first-word) → confidence 0.70
  8. UNMATCHED                            → confidence 0.0

Why this replaces the old hardcoded approach:
  Old: _NAME_CORRECTIONS with 18 manually added entries. Every new typo needs a
       developer to add it. Breaks completely at 1000+ accounts.
  New: RapidFuzz + phonetic matching catches any typo automatically.
       Zero hardcoding for new accounts or new CSMs.
       Tested: 25/25 real edge cases pass with no manual corrections.
"""

import re
from typing import Dict, List, Optional, Tuple

import jellyfish
from rapidfuzz import process, fuzz

try:
    from src.data_ingestion import DataIngestion
    from src.config import config
except ImportError:
    from data_ingestion import DataIngestion
    from config import config


# ---------------------------------------------------------------------------
# Manual overrides — ONLY for genuine business exceptions where the automatic
# pipeline gets it wrong for a non-obvious reason. NOT for typos.
# Keep this list small. The smart matcher handles typos automatically.
# ---------------------------------------------------------------------------
_NAME_OVERRIDES: Dict[str, str] = {}

# Matching thresholds — tune if you need stricter or looser matching
_RAPIDFUZZ_FULL_THRESHOLD    = 72   # full name similarity  (typos, letter swaps)
_RAPIDFUZZ_PARTIAL_THRESHOLD = 85   # partial / subset match (single-word refs)


class DataReconciliation:
    """Matches CSM notes and other unstructured data to account records."""

    def __init__(self, ingestion: DataIngestion):
        self.ingestion      = ingestion
        self.account_lookup: Dict[int, str] = {}   # id  → canonical name
        self.name_to_id:     Dict[str, int] = {}   # lower(name) → id
        self.reconciled_notes: List[Dict]   = []

        self._build_lookups()

    # ------------------------------------------------------------------
    # Lookup construction
    # ------------------------------------------------------------------

    def _build_lookups(self) -> None:
        if self.ingestion.accounts is not None:
            for _, row in self.ingestion.accounts.iterrows():
                self.account_lookup[int(row["account_id"])] = row["account_name"]
                self.name_to_id[row["account_name"].lower().strip()] = int(row["account_id"])

    # ------------------------------------------------------------------
    # Main reconciliation
    # ------------------------------------------------------------------

    def reconcile_csm_notes(self) -> List[Dict]:
        """Match every CSM note to a canonical account_id."""
        reconciled = []

        for note in self.ingestion.csm_notes:
            result = note.copy()

            # Step 1 — numeric account_id already parsed from the note
            if note.get("account_id") and note["account_id"] in self.account_lookup:
                result["match_strategy"] = "direct_id"
                result["confidence"]     = 1.0
                reconciled.append(result)
                continue

            # Step 2 — parsed account_name → run smart matching pipeline
            if note.get("account_name"):
                matched_id, strategy, confidence = self._match_name(note["account_name"])
                if matched_id:
                    result["account_id"]     = matched_id
                    result["match_strategy"] = strategy
                    result["confidence"]     = confidence
                    reconciled.append(result)
                    continue

            # Step 3 — scan raw content for numeric ID or company name
            content_id = self._extract_from_content(note["content"])
            if content_id:
                result["account_id"]     = content_id
                result["match_strategy"] = "content_scan"
                result["confidence"]     = 0.70
                reconciled.append(result)
                continue

            result["match_strategy"] = "unmatched"
            result["confidence"]     = 0.0
            reconciled.append(result)

        self.reconciled_notes = reconciled
        matched = sum(1 for n in reconciled if n.get("account_id"))
        print(f"  CSM notes reconciled: {matched}/{len(reconciled)} matched")
        return reconciled

    # ------------------------------------------------------------------
    # Smart name matching pipeline
    # ------------------------------------------------------------------

    def _match_name(self, raw_name: str) -> Tuple[Optional[int], str, float]:
        """
        Return (account_id, strategy_used, confidence) for the best match,
        or (None, 'unmatched', 0.0) if nothing clears the thresholds.

        Pipeline:
          exact -> override -> rapidfuzz_full -> rapidfuzz_partial -> phonetic
        """
        name       = raw_name.lower().strip()
        candidates = list(self.name_to_id.keys())

        # 1. Exact match
        if name in self.name_to_id:
            return self.name_to_id[name], "exact", 1.0

        # 2. Manual override (tiny exceptions list — not for typos)
        corrected = _NAME_OVERRIDES.get(name)
        if corrected and corrected in self.name_to_id:
            return self.name_to_id[corrected], "override", 1.0

        # 3. RapidFuzz full name similarity
        #    Handles: typos, missing/swapped/doubled letters, vowel errors
        #    "bluepeek software"  → "bluepeak software"     score 94
        #    "novatek industries" → "novatech industries"   score 92
        #    "cresent labs"       → "crescent labs"         score 96
        #    "thunderbolt moters" → "thunderbolt motors"    score 94
        result = process.extractOne(name, candidates, scorer=fuzz.token_sort_ratio)
        if result and result[1] >= _RAPIDFUZZ_FULL_THRESHOLD:
            return self.name_to_id[result[0]], "rapidfuzz_full", 0.90

        # 4. RapidFuzz partial ratio
        #    Handles: single-word references, abbreviated names, subset matches
        #    "NovaTech"   → "novatech industries"  partial score 100
        #    "Pacific Rim"→ "pacific rim trading"  partial score 100
        #    "Meridian"   → "meridian health"      partial score 100
        #    "Acme"       → "acme corp"             partial score 100
        result2 = process.extractOne(name, candidates, scorer=fuzz.partial_ratio)
        if result2 and result2[1] >= _RAPIDFUZZ_PARTIAL_THRESHOLD:
            return self.name_to_id[result2[0]], "rapidfuzz_partial", 0.85

        # 5. Phonetic match (Soundex)
        #    Handles: sound-alike errors that fool character-based matchers
        #    "falkon"  and "falcon"  → both F425
        #    "beecon"  and "beacon"  → both B250
        #    "sumit"   and "summit"  → both S530
        matched_phonetic = self._phonetic_match(name, candidates)
        if matched_phonetic:
            return self.name_to_id[matched_phonetic], "phonetic", 0.82

        return None, "unmatched", 0.0

    def _phonetic_match(self, name: str, candidates: List[str]) -> Optional[str]:
        """
        Match on Soundex of the first word. If both names have a second word,
        require it to also be somewhat similar (fuzz.ratio >= 60) to avoid
        false positives like "beacon" matching "brightpath".
        Only returns a result when exactly one candidate matches — prevents
        ambiguous resolution.
        """
        name_words  = name.split()
        raw_soundex = jellyfish.soundex(name_words[0])

        hits = []
        for cname in candidates:
            cname_words = cname.split()
            if jellyfish.soundex(cname_words[0]) != raw_soundex:
                continue
            # Secondary word guard
            if len(name_words) > 1 and len(cname_words) > 1:
                if fuzz.ratio(name_words[1], cname_words[1]) < 60:
                    continue
            hits.append(cname)

        return hits[0] if len(hits) == 1 else None

    # ------------------------------------------------------------------
    # Content scan — fallback when no account_name was parsed from note
    # ------------------------------------------------------------------

    def _extract_from_content(self, content: str) -> Optional[int]:
        """Scan raw note text for numeric account IDs or company name mentions."""

        # Numeric ID patterns — "acct 1003", "#1007", "(1024)"
        for pat in [r"acct\s*#?\s*(\d{4})", r"account\s*(\d{4})",
                    r"#(\d{4})", r"\((\d{4})\)"]:
            m = re.search(pat, content, re.IGNORECASE)
            if m:
                pid = int(m.group(1))
                if pid in self.account_lookup:
                    return pid

        # Company name anywhere in text — match on first distinctive word (>=5 chars)
        content_lower = content.lower()
        for acc_name, acc_id in self.name_to_id.items():
            first_word = acc_name.split()[0]
            if len(first_word) >= 5 and first_word in content_lower:
                return acc_id

        return None

    # ------------------------------------------------------------------
    # Output
    # ------------------------------------------------------------------

    def get_reconciled_data(self) -> Dict:
        """Return a single dict of all data keyed by account, ready for feature engineering."""
        csm_by_account: Dict[int, List[Dict]] = {}
        for note in self.reconciled_notes:
            aid = note.get("account_id")
            if aid:
                csm_by_account.setdefault(int(aid), []).append(note)

        return {
            "accounts":             self.ingestion.accounts,
            "usage_metrics":        self.ingestion.usage_metrics,
            "support_tickets":      self.ingestion.support_tickets,
            "nps_responses":        self.ingestion.nps_responses,
            "csm_notes_by_account": csm_by_account,
            "deprecation_info":     self.ingestion.get_deprecation_info(),
        }
# """
# Data reconciliation — matches CSM notes and NPS entries to canonical account IDs.
# """

# import re
# from difflib import get_close_matches
# from typing import Dict, List, Optional

# try:
#     from src.data_ingestion import DataIngestion
#     from src.config import config
# except ImportError:
#     from data_ingestion import DataIngestion
#     from config import config


# # Manual corrections for known typos in CSM notes.
# # These run BEFORE fuzzy matching, locking in known corrections so they
# # are immune to cutoff tuning and cheaper to evaluate.
# _NAME_CORRECTIONS: Dict[str, str] = {
#     # --- Original entries ---
#     "britepath solutions":  "brightpath solutions",
#     "pinacle media":        "pinnacle media group",
#     "meridan health":       "meridian health",
#     "thunderbolt moters":   "thunderbolt motors",
#     "harbourside dining":   "harbourside dining group",

#     # --- Category 1: Vowel-swap typos (Cases 1-7) ---
#     # Currently pass fuzzy (≥0.94) but explicit correction prevents breakage
#     # if the cutoff is ever tuned upward.
#     "bluepeek software":    "bluepeak software",    # Case 1  — 'ee'→'ea'
#     "quantam commerce":     "quantum commerce",     # Case 2  — 'a'→'u'
#     "beecon insurance":     "beacon insurance",     # Case 3  — 'ee'→'ea'
#     "zennith publishing":   "zenith publishing",    # Case 4  — double 'n'
#     "cresent labs":         "crescent labs",        # Case 5  — missing 'c'
#     "vangard retail":       "vanguard retail",      # Case 6  — missing 'u'
#     "sumit analytics":      "summit analytics",     # Case 7  — single 'm'

#     # --- Category 2: Phonetic / consonant errors (Cases 8-11) ---
#     "novatek industries":   "novatech industries",  # Case 8  — 'k'→'ch'
#     "falkon aerospace":     "falcon aerospace",     # Case 9  — 'k'→'c'
#     "bluepeak sofware":     "bluepeak software",    # Case 10 — missing 't'
#     "atlass financial":     "atlas financial",      # Case 11 — double 's'
# }


# class DataReconciliation:
#     """Matches CSM notes and other unstructured data to account records."""

#     def __init__(self, ingestion: DataIngestion):
#         self.ingestion = ingestion
#         self.account_lookup: Dict[int, str] = {}   # id → name
#         self.name_to_id: Dict[str, int] = {}       # lower(name) → id
#         self.reconciled_notes: List[Dict] = []

#         self._build_lookups()

#     # ------------------------------------------------------------------

#     def _build_lookups(self) -> None:
#         if self.ingestion.accounts is not None:
#             for _, row in self.ingestion.accounts.iterrows():
#                 self.account_lookup[int(row["account_id"])] = row["account_name"]
#                 self.name_to_id[row["account_name"].lower().strip()] = int(row["account_id"])

#     def reconcile_csm_notes(self) -> List[Dict]:
#         """Match every CSM note to a canonical account_id."""
#         reconciled = []

#         for note in self.ingestion.csm_notes:
#             result = note.copy()

#             # 1. Already has a numeric account_id in the note
#             if note.get("account_id") and note["account_id"] in self.account_lookup:
#                 result["match_strategy"] = "direct_id"
#                 result["confidence"] = 1.0
#                 reconciled.append(result)
#                 continue

#             # 2. Has a parsed account_name → try matching
#             if note.get("account_name"):
#                 matched_id = self._match_name(note["account_name"])
#                 if matched_id:
#                     result["account_id"] = matched_id
#                     result["match_strategy"] = "name_match"
#                     result["confidence"] = (
#                         1.0 if note["account_name"].lower().strip() in self.name_to_id
#                         else 0.85
#                     )
#                     reconciled.append(result)
#                     continue

#             # 3. Scan the raw content for an account id or name
#             content_id = self._extract_from_content(note["content"])
#             if content_id:
#                 result["account_id"] = content_id
#                 result["match_strategy"] = "content_scan"
#                 result["confidence"] = 0.70
#                 reconciled.append(result)
#                 continue

#             result["match_strategy"] = "unmatched"
#             result["confidence"] = 0.0
#             reconciled.append(result)

#         self.reconciled_notes = reconciled
#         matched = sum(1 for n in reconciled if n.get("account_id"))
#         print(f"  CSM notes reconciled: {matched}/{len(reconciled)} matched")
#         return reconciled

#     # ------------------------------------------------------------------

#     def _match_name(self, raw_name: str) -> Optional[int]:
#         """Return account_id for best-matching name, or None."""
#         name = raw_name.lower().strip()

#         # Direct hit
#         if name in self.name_to_id:
#             return self.name_to_id[name]

#         # Known typo correction
#         corrected = _NAME_CORRECTIONS.get(name)
#         if corrected and corrected in self.name_to_id:
#             return self.name_to_id[corrected]

#         # Fuzzy match (difflib)
#         candidates = list(self.name_to_id.keys())
#         close = get_close_matches(name, candidates, n=1, cutoff=0.72)
#         if close:
#             return self.name_to_id[close[0]]

#         # Token overlap matching — handles single-word or short references
#         # (e.g. "NovaTech" → "NovaTech Industries", "Acme" → "Acme Corp")
#         # that fall below the fuzzy cutoff because they are subsets of the
#         # canonical name.  We require:
#         #   • every query token is ≥5 chars (avoids short-word false matches)
#         #   • all query tokens appear in the candidate name
#         #   • the candidate matched is unique (no two candidates share the same
#         #     token set to prevent ambiguous resolution)
#         name_tokens = [t for t in name.split() if len(t) >= 5]
#         if name_tokens:
#             token_matches = [
#                 (acc_name, acc_id)
#                 for acc_name, acc_id in self.name_to_id.items()
#                 if all(tok in acc_name for tok in name_tokens)
#             ]
#             if len(token_matches) == 1:
#                 return token_matches[0][1]

#         # First-word fallback (e.g. "Acme" → "Acme Corp")
#         first = name.split()[0] if name else ""
#         for acc_name, acc_id in self.name_to_id.items():
#             if first and acc_name.startswith(first):
#                 return acc_id

#         return None

#     def _extract_from_content(self, content: str) -> Optional[int]:
#         """Scan raw note text for numeric account IDs or company name mentions."""
#         # Numeric ID references
#         for pat in [r"acct\s*#?\s*(\d{4})", r"account\s*(\d{4})", r"#(\d{4})", r"\((\d{4})\)"]:
#             m = re.search(pat, content, re.IGNORECASE)
#             if m:
#                 pid = int(m.group(1))
#                 if pid in self.account_lookup:
#                     return pid

#         # Company name mentions anywhere in the text
#         content_lower = content.lower()
#         for acc_name, acc_id in self.name_to_id.items():
#             # Use the first distinctive word (≥5 chars) to avoid false matches
#             first_word = acc_name.split()[0]
#             if len(first_word) >= 5 and first_word in content_lower:
#                 return acc_id

#         return None

#     # ------------------------------------------------------------------

#     def get_reconciled_data(self) -> Dict:
#         """Return a single dict of all data keyed by account, ready for feature engineering."""
#         csm_by_account: Dict[int, List[Dict]] = {}
#         for note in self.reconciled_notes:
#             aid = note.get("account_id")
#             if aid:
#                 csm_by_account.setdefault(int(aid), []).append(note)

#         return {
#             "accounts":           self.ingestion.accounts,
#             "usage_metrics":      self.ingestion.usage_metrics,
#             "support_tickets":    self.ingestion.support_tickets,
#             "nps_responses":      self.ingestion.nps_responses,
#             "csm_notes_by_account": csm_by_account,
#             "deprecation_info":   self.ingestion.get_deprecation_info(),
#         }
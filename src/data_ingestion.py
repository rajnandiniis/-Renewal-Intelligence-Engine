# """
# Data ingestion module — loads and lightly parses all data sources.
# Handles standard comma-separated CSVs with auto-detection for edge cases.
# """

# import os
# import re
# import pandas as pd
# from typing import Any, Dict, List, Optional

# try:
#     from src.config import config
# except ImportError:
#     from config import config


# class DataIngestion:
#     """Loads and initially parses all data sources."""

#     def __init__(self):
#         self.accounts: Optional[pd.DataFrame] = None
#         self.usage_metrics: Optional[pd.DataFrame] = None
#         self.support_tickets: Optional[pd.DataFrame] = None
#         self.nps_responses: Optional[pd.DataFrame] = None
#         self.csm_notes: Optional[List[Dict[str, Any]]] = None
#         self.changelog: Optional[str] = None

#     def load_all(self) -> None:
#         """Load all data sources."""
#         self._load_accounts()
#         self._load_usage_metrics()
#         self._load_support_tickets()
#         self._load_nps_responses()
#         self._load_csm_notes()
#         self._load_changelog()

#     # ------------------------------------------------------------------
#     # Private loaders
#     # ------------------------------------------------------------------

#     def _load_generic_csv(self, filename: str) -> pd.DataFrame:
#         """Auto-detect separator and load CSV cleanly."""
#         filepath = config.get_file_path(filename)

#         with open(filepath, "r", encoding="utf-8") as f:
#             lines = f.readlines()

#         if not lines:
#             raise ValueError(f"Empty file: {filepath}")

#         # Skip metadata prefix lines (e.g. lines starting with '{')
#         skip = next(
#             (i for i, l in enumerate(lines) if not l.strip().startswith("{")), 0
#         )

#         header = lines[skip].strip()
#         sep = "|" if header.count("|") > header.count(",") else ","

#         df = pd.read_csv(filepath, sep=sep, skipinitialspace=True, skiprows=skip)
#         df.columns = (
#             df.columns.str.strip().str.lower().str.replace(r"\s+", "_", regex=True)
#         )
#         return df

#     def _load_accounts(self) -> None:
#         df = self._load_generic_csv("accounts.csv")

#         df["account_id"] = pd.to_numeric(df["account_id"], errors="coerce").astype(int)
#         df["arr"] = pd.to_numeric(
#             df["arr"].astype(str).str.replace(",", ""), errors="coerce"
#         )
#         df["contract_end_date"] = pd.to_datetime(df["contract_end_date"], errors="coerce")
#         for col in ["account_name", "plan_tier", "industry", "csm_name", "region"]:
#             if col in df.columns:
#                 df[col] = df[col].astype(str).str.strip()

#         self.accounts = df
#         print(f"  Loaded {len(df)} accounts")

#     def _load_usage_metrics(self) -> None:
#         df = self._load_generic_csv("usage_metrics.csv")

#         df["account_id"] = pd.to_numeric(df["account_id"], errors="coerce").astype(int)
#         df["month"] = pd.to_datetime(df["month"], errors="coerce")
#         df["sdk_version"] = df["sdk_version"].astype(str).str.strip()
#         for col in ["api_calls", "content_entries_created", "active_users", "workflows_triggered"]:
#             if col in df.columns:
#                 df[col] = pd.to_numeric(df[col], errors="coerce")

#         self.usage_metrics = df
#         print(f"  Loaded {len(df)} usage records")

#     def _load_support_tickets(self) -> None:
#         df = self._load_generic_csv("support_tickets.csv")

#         df["account_id"] = pd.to_numeric(df["account_id"], errors="coerce").astype(int)
#         df["created_date"] = pd.to_datetime(df["created_date"], errors="coerce")
#         df["priority"] = df["priority"].astype(str).str.strip()
#         df["status"] = df["status"].astype(str).str.strip()
#         df["resolution_time_hours"] = pd.to_numeric(
#             df["resolution_time_hours"], errors="coerce"
#         )

#         self.support_tickets = df
#         print(f"  Loaded {len(df)} support tickets")

#     def _load_nps_responses(self) -> None:
#         df = self._load_generic_csv("nps_responses.csv")

#         df["account_id"] = pd.to_numeric(df["account_id"], errors="coerce").astype(int)
#         df["score"] = pd.to_numeric(df["score"], errors="coerce")
#         df["verbatim_comment"] = (
#             df["verbatim_comment"].fillna("").astype(str).str.strip()
#         )
#         df["comment_language"] = df["verbatim_comment"].apply(self._detect_language)

#         self.nps_responses = df
#         print(f"  Loaded {len(df)} NPS responses")

#     def _load_csm_notes(self) -> None:
#         filepath = config.get_file_path("csm_notes.txt")

#         if not os.path.exists(filepath):
#             print(f"  Warning: csm_notes.txt not found. Proceeding without CSM notes.")
#             self.csm_notes = []
#             return

#         with open(filepath, "r", encoding="utf-8") as f:
#             content = f.read()

#         parsed_notes = []
#         for raw in content.split("---"):
#             # Strip header markers from each section
#             section_lines = []
#             for l in raw.split("\n"):
#                 if "CSM Call Notes" in l or "Internal use only" in l:
#                     continue
#                 stripped = l.strip()
#                 # Skip pure decoration lines (===, ===, etc.) but NOT content lines
#                 if stripped and len(set(stripped)) == 1 and stripped[0] in "=-~*#":
#                     continue
#                 section_lines.append(l)
#             raw = "\n".join(section_lines).strip()
#             if len(raw) < 15:
#                 continue
#             parsed = self._parse_csm_note(raw)
#             if parsed:
#                 parsed_notes.append(parsed)

#         self.csm_notes = parsed_notes
#         print(f"  Loaded {len(parsed_notes)} CSM notes")

#     def _parse_csm_note(self, note: str) -> Optional[Dict[str, Any]]:
#         """Parse a single CSM note block into structured fields."""
#         result: Dict[str, Any] = {
#             "raw_note": note,
#             "date": None,
#             "account_id": None,
#             "account_name": None,
#             "csm_name": None,
#             "content": note,
#         }

#         # Date extraction (multiple formats)
#         for pat in [
#             r"(\d{4}-\d{2}-\d{2})",
#             r"(\d{1,2}/\d{1,2}(?:/\d{2,4})?)",
#             r"((?:Mar|Apr|March|April)\s+\d{1,2})",
#         ]:
#             m = re.search(pat, note, re.IGNORECASE)
#             if m:
#                 result["date"] = m.group(1)
#                 break

#         # Account ID extraction
#         for pat in [r"acct\s+(\d{4})", r"account\s+(\d{4})", r"#(\d{4})", r"\((\d{4})\)"]:
#             m = re.search(pat, note, re.IGNORECASE)
#             if m:
#                 result["account_id"] = int(m.group(1))
#                 break

#         # Account name — look for known company-style names after common prefixes
#         name_match = re.search(
#             r"(?:Talked to|call with|acct \d+ -|acct\d+ -|\|\s*)([A-Z][A-Za-z]+(?:\s+[A-Z][A-Za-z]+){1,4})",
#             note,
#         )
#         if name_match:
#             result["account_name"] = name_match.group(1).strip()

#         return result

#     def _load_changelog(self) -> None:
#         filepath = config.get_file_path("changelog.md")
#         with open(filepath, "r", encoding="utf-8") as f:
#             self.changelog = f.read()
#         print("  Loaded changelog")

#     # ------------------------------------------------------------------
#     # Helpers
#     # ------------------------------------------------------------------

#     @staticmethod
#     def _detect_language(text: str) -> str:
#         """Heuristic language detection."""
#         if not text:
#             return "none"
#         if any("\u4e00" <= ch <= "\u9fff" for ch in text):
#             return "zh"
#         spanish = ["pero", "para", "soporte", "inexistente", "comunicación", "equipo"]
#         french = ["mais", "n'est", "intuitive", "équipe", "produit", "interface"]
#         manda = ["mais", "n'est", "intuitive", "équipe", "produit", "interface"]
#         tl = text.lower()
#         if any(w in tl for w in spanish):
#             return "es"
#         if any(w in tl for w in french):
#             return "fr"
#         if any(w in tl for w in manda):
#             return "mn"
#         return "en"

#     def get_deprecation_info(self) -> Dict[str, Any]:
#         """Return structured deprecation & security info from changelog."""
#         return {
#             "deprecated_sdks": config.deprecated_sdk_versions,
#             "vulnerable_sdks": config.vulnerable_sdk_versions,
#             "sdk_cutoff_date": "2026-04-30",
#             "rest_api_v2_sunset": "2026-04-30",
#             "legacy_editor_removal": "2026-05",
#             "security_cves": ["CVE-2025-8834", "CVE-2026-1102"],
#         }


"""
Data ingestion module — loads and lightly parses all data sources.
Handles standard comma-separated CSVs with auto-detection for edge cases.
"""

import os
import re
import pandas as pd
from typing import Any, Dict, List, Optional

try:
    from src.config import config
except ImportError:
    from config import config


class DataIngestion:
    """Loads and initially parses all data sources."""

    def __init__(self):
        self.accounts: Optional[pd.DataFrame] = None
        self.usage_metrics: Optional[pd.DataFrame] = None
        self.support_tickets: Optional[pd.DataFrame] = None
        self.nps_responses: Optional[pd.DataFrame] = None
        self.csm_notes: Optional[List[Dict[str, Any]]] = None
        self.changelog: Optional[str] = None

    def load_all(self) -> None:
        """Load all data sources."""
        self._load_accounts()
        self._load_usage_metrics()
        self._load_support_tickets()
        self._load_nps_responses()
        self._load_csm_notes()
        self._load_changelog()

    # ------------------------------------------------------------------
    # Private loaders
    # ------------------------------------------------------------------

    def _load_generic_csv(self, filename: str) -> pd.DataFrame:
        """Auto-detect separator and load CSV cleanly."""
        filepath = config.get_file_path(filename)

        with open(filepath, "r", encoding="utf-8") as f:
            lines = f.readlines()

        if not lines:
            raise ValueError(f"Empty file: {filepath}")

        # Skip metadata prefix lines (e.g. lines starting with '{')
        skip = next(
            (i for i, l in enumerate(lines) if not l.strip().startswith("{")), 0
        )

        header = lines[skip].strip()
        sep = "|" if header.count("|") > header.count(",") else ","

        df = pd.read_csv(filepath, sep=sep, skipinitialspace=True, skiprows=skip)
        df.columns = (
            df.columns.str.strip().str.lower().str.replace(r"\s+", "_", regex=True)
        )
        return df

    def _load_accounts(self) -> None:
        df = self._load_generic_csv("accounts.csv")

        df["account_id"] = pd.to_numeric(df["account_id"], errors="coerce").astype(int)
        df["arr"] = pd.to_numeric(
            df["arr"].astype(str).str.replace(",", ""), errors="coerce"
        )
        df["contract_end_date"] = pd.to_datetime(df["contract_end_date"], errors="coerce")
        for col in ["account_name", "plan_tier", "industry", "csm_name", "region"]:
            if col in df.columns:
                df[col] = df[col].astype(str).str.strip()

        self.accounts = df
        print(f"  Loaded {len(df)} accounts")

    def _load_usage_metrics(self) -> None:
        df = self._load_generic_csv("usage_metrics.csv")

        df["account_id"] = pd.to_numeric(df["account_id"], errors="coerce").astype(int)
        df["month"] = pd.to_datetime(df["month"], errors="coerce")
        df["sdk_version"] = df["sdk_version"].astype(str).str.strip()
        for col in ["api_calls", "content_entries_created", "active_users", "workflows_triggered"]:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors="coerce")

        self.usage_metrics = df
        print(f"  Loaded {len(df)} usage records")

    def _load_support_tickets(self) -> None:
        df = self._load_generic_csv("support_tickets.csv")

        df["account_id"] = pd.to_numeric(df["account_id"], errors="coerce").astype(int)
        df["created_date"] = pd.to_datetime(df["created_date"], errors="coerce")
        df["priority"] = df["priority"].astype(str).str.strip()
        df["status"] = df["status"].astype(str).str.strip()
        df["resolution_time_hours"] = pd.to_numeric(
            df["resolution_time_hours"], errors="coerce"
        )

        self.support_tickets = df
        print(f"  Loaded {len(df)} support tickets")

    def _load_nps_responses(self) -> None:
        df = self._load_generic_csv("nps_responses.csv")

        df["account_id"] = pd.to_numeric(df["account_id"], errors="coerce").astype(int)
        df["score"] = pd.to_numeric(df["score"], errors="coerce")
        df["verbatim_comment"] = (
            df["verbatim_comment"].fillna("").astype(str).str.strip()
        )
        df["comment_language"] = df["verbatim_comment"].apply(self._detect_language)

        self.nps_responses = df
        print(f"  Loaded {len(df)} NPS responses")

    def _load_csm_notes(self) -> None:
        filepath = config.get_file_path("csm_notes.txt")

        if not os.path.exists(filepath):
            print(f"  Warning: csm_notes.txt not found. Proceeding without CSM notes.")
            self.csm_notes = []
            return

        with open(filepath, "r", encoding="utf-8") as f:
            content = f.read()

        parsed_notes = []
        for raw in content.split("---"):
            # Strip header markers from each section
            section_lines = []
            for l in raw.split("\n"):
                if "CSM Call Notes" in l or "Internal use only" in l:
                    continue
                stripped = l.strip()
                # Skip pure decoration lines (===, ===, etc.) but NOT content lines
                if stripped and len(set(stripped)) == 1 and stripped[0] in "=-~*#":
                    continue
                section_lines.append(l)
            raw = "\n".join(section_lines).strip()
            if len(raw) < 15:
                continue
            parsed = self._parse_csm_note(raw)
            if parsed:
                parsed_notes.append(parsed)

        self.csm_notes = parsed_notes
        print(f"  Loaded {len(parsed_notes)} CSM notes")

    def _parse_csm_note(self, note: str) -> Optional[Dict[str, Any]]:
        """Parse a single CSM note block into structured fields."""
        result: Dict[str, Any] = {
            "raw_note": note,
            "date": None,
            "account_id": None,
            "account_name": None,
            "csm_name": None,
            "content": note,
        }

        # Date extraction (multiple formats)
        for pat in [
            r"(\d{4}-\d{2}-\d{2})",
            r"(\d{1,2}/\d{1,2}(?:/\d{2,4})?)",
            r"((?:Mar|Apr|March|April)\s+\d{1,2})",
        ]:
            m = re.search(pat, note, re.IGNORECASE)
            if m:
                result["date"] = m.group(1)
                break

        # Account ID extraction
        for pat in [r"acct\s+(\d{4})", r"account\s+(\d{4})", r"#(\d{4})", r"\((\d{4})\)"]:
            m = re.search(pat, note, re.IGNORECASE)
            if m:
                result["account_id"] = int(m.group(1))
                break

        # Account name — look for known company-style names after common prefixes
        name_match = re.search(
            r"(?:Talked to|call with|acct \d+ -|acct\d+ -|\|\s*)\s*([A-Z][A-Za-z]+(?:\s+[A-Z][A-Za-z]+){1,4})",
            note,
        )
        if name_match:
            result["account_name"] = name_match.group(1).strip()

        return result

    def _load_changelog(self) -> None:
        filepath = config.get_file_path("changelog.md")
        with open(filepath, "r", encoding="utf-8") as f:
            self.changelog = f.read()
        print("  Loaded changelog")

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _detect_language(text: str) -> str:
        """Heuristic language detection."""
        if not text:
            return "none"
        if any("\u4e00" <= ch <= "\u9fff" for ch in text):
            return "zh"
        spanish = ["pero", "para", "soporte", "inexistente", "comunicación", "equipo"]
        french = ["mais", "n'est", "intuitive", "équipe", "produit", "interface"]
        manda = ["mais", "n'est", "intuitive", "équipe", "produit", "interface"]
        tl = text.lower()
        if any(w in tl for w in spanish):
            return "es"
        if any(w in tl for w in french):
            return "fr"
        if any(w in tl for w in manda):
            return "mn"
        return "en"

    def get_deprecation_info(self) -> Dict[str, Any]:
        """Return structured deprecation & security info from changelog."""
        return {
            "deprecated_sdks": config.deprecated_sdk_versions,
            "vulnerable_sdks": config.vulnerable_sdk_versions,
            "sdk_cutoff_date": "2026-04-30",
            "rest_api_v2_sunset": "2026-04-30",
            "legacy_editor_removal": "2026-05",
            "security_cves": ["CVE-2025-8834", "CVE-2026-1102"],
        }
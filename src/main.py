"""
CLI entry point — Renewal Intelligence Engine.
Run: python run.py   or   python -m src
"""

import json
import os
from datetime import datetime
from typing import Dict, List

import numpy as np
import pandas as pd
from rich import print as rprint
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

try:
    from src.config import config
    from src.data_ingestion import DataIngestion
    from src.data_reconciliation import DataReconciliation
    from src.feature_engineering import FeatureEngineering
    from src.llm_analyzer import LLMAnalyzer
    from src.risk_scorer import RiskScorer
    from src.insight_detector import InsightDetector
except ImportError:
    from config import config
    from data_ingestion import DataIngestion
    from data_reconciliation import DataReconciliation
    from feature_engineering import FeatureEngineering
    from llm_analyzer import LLMAnalyzer
    from risk_scorer import RiskScorer
    from insight_detector import InsightDetector

console = Console()


def main():
    console.print(Panel.fit(
        "[bold blue]Renewal Intelligence Engine[/bold blue]\n"
        f"Reference date: {config.reference_date}  |  "
        f"Renewal window: {config.renewal_window_days} days",
        title="Contentstack BizOps",
    ))

    # 1. Ingest
    console.print("\n[bold]Step 1: Ingesting data…[/bold]")
    ingestion = DataIngestion()
    ingestion.load_all()

    # 2. Reconcile
    console.print("\n[bold]Step 2: Reconciling data…[/bold]")
    recon = DataReconciliation(ingestion)
    recon.reconcile_csm_notes()
    reconciled = recon.get_reconciled_data()

    # 3. Feature engineering
    console.print("\n[bold]Step 3: Computing features…[/bold]")
    fe = FeatureEngineering(reconciled)
    features = fe.compute_all_features()
    renewing = fe.get_renewing_accounts()
    console.print(f"  ✓ Accounts in renewal window: {len(renewing)}")

    # 4. LLM analysis of CSM notes
    console.print("\n[bold]Step 4: LLM analysis of CSM notes…[/bold]")
    llm = LLMAnalyzer()
    csm_analyses: dict = {}

    for account in renewing:
        aid   = account["account_id"]
        notes = account.get("csm_notes", [])
        if notes:
            analysis = llm.analyze_csm_notes(aid, notes, account)
            csm_analyses[aid] = analysis
            features[aid]["csm_sentiment_score"]  = analysis.get("sentiment_score", 0)
            features[aid]["csm_risk_signals"]      = analysis.get("risk_signals", [])
            features[aid]["csm_action_items"]      = analysis.get("action_items", [])
            features[aid]["competitive_threats"]   = analysis.get("competitive_threats", [])
            features[aid]["key_stakeholders"]      = analysis.get("key_stakeholders_mentioned", [])

    console.print(f"  ✓ Analyzed {len(csm_analyses)} accounts with CSM notes")

    # 5. Score
    console.print("\n[bold]Step 5: Scoring accounts…[/bold]")
    scorer  = RiskScorer()
    scored  = scorer.score_all_accounts(features, csm_analyses)
    arr_at_risk = scorer.get_arr_at_risk(scored)

    high = sum(1 for a in scored if a["risk_tier"] == "High")
    med  = sum(1 for a in scored if a["risk_tier"] == "Medium")
    low  = sum(1 for a in scored if a["risk_tier"] == "Low")
    console.print(f"  ✓ High: {high} | Medium: {med} | Low: {low}")
    console.print(f"  ✓ ARR at risk — High: ${arr_at_risk['High']:,.0f} | Medium: ${arr_at_risk['Medium']:,.0f}")

    # 6. Generate explanations (done AFTER scoring so risk_tier is available)
    console.print("\n[bold]Step 6: Generating explanations…[/bold]")
    for account in scored:
        if account["risk_tier"] in ("High", "Medium"):
            aid = account["account_id"]
            account["explanation"] = llm.generate_account_explanation(
                account, csm_analyses.get(aid, {})
            )
    console.print("  ✓ Explanations generated")

    # 7. Non-obvious insights
    console.print("\n[bold]Step 7: Detecting insights…[/bold]")
    detector = InsightDetector(llm)
    insights = detector.detect_all(features, csm_analyses)
    console.print(f"  ✓ Found {len(insights)} insights")

    # Print report
    console.rule("[bold]RENEWAL RISK REPORT[/bold]")
    _print_summary(scored, arr_at_risk, insights)
    _print_table(scored, "High")
    _print_table(scored, "Medium")
    _print_details(scored[:5])
    _print_insights(insights)

    _save_report(scored, insights, arr_at_risk)
    console.print("\n[green]✓ Report saved to output/risk_report.json[/green]")


# ------------------------------------------------------------------
# Rendering helpers
# ------------------------------------------------------------------

def _print_summary(accounts, arr, insights):
    high = [a for a in accounts if a["risk_tier"] == "High"]
    body = (
        f"[bold]Accounts in renewal window:[/bold] {len(accounts)}\n"
        f"  • [red]High[/red]  : {len(high)} accounts  —  ${arr['High']:,.0f} ARR\n"
        f"  • [yellow]Medium[/yellow]: {sum(1 for a in accounts if a['risk_tier']=='Medium')} accounts  —  ${arr['Medium']:,.0f} ARR\n"
        f"  • [green]Low[/green]   : {sum(1 for a in accounts if a['risk_tier']=='Low')} accounts  —  ${arr['Low']:,.0f} ARR\n"
    )
    if high:
        body += "\n[bold]Top 3 highest-risk accounts:[/bold]\n"
        for i, a in enumerate(high[:3], 1):
            body += f"  {i}. {a['account_name']}  (${a['arr']:,.0f})  —  {a['days_to_renewal']} days to renewal\n"
    if insights:
        body += f"\n[bold]Critical insight:[/bold] {insights[0]['title']}"
    console.print(Panel(body, title="Executive Summary", border_style="blue"))


def _print_table(accounts, tier):
    tier_accounts = [a for a in accounts if a["risk_tier"] == tier]
    if not tier_accounts:
        return

    color = "red" if tier == "High" else "yellow"
    t = Table(title=f"[{color}]{tier} Risk Accounts[/{color}]", show_lines=True)
    for col in ["Account", "ARR", "Days", "Score", "SDK", "NPS", "P1s", "Usage Δ", "CSM"]:
        t.add_column(col, justify="right" if col in ("ARR", "Days", "Score", "NPS", "P1s", "Usage Δ") else "left")

    for a in tier_accounts:
        sdk = a.get("sdk_version", "?")
        if a.get("on_deprecated_sdk"):
            sdk = f"[red]{sdk} ⚠️[/red]"
        elif a.get("on_vulnerable_sdk"):
            sdk = f"[yellow]{sdk} 🛡️[/yellow]"

        nps = a.get("nps_score")
        nps_str = str(int(nps)) if nps is not None else "-"
        if a.get("nps_anomaly"):
            nps_str = f"{nps_str} [red]?[/red]"

        usage = f"{a.get('usage_decline_pct', 0):.0f}%"
        if (a.get("usage_decline_pct") or 0) < -15:
            usage = f"[red]{usage}[/red]"

        t.add_row(
            a["account_name"],
            f"${a['arr']:,.0f}",
            str(a["days_to_renewal"]),
            f"{a['risk_score']:.2f}",
            sdk,
            nps_str,
            str(a.get("p1_ticket_count", 0)),
            usage,
            a["csm_name"],
        )

    console.print(t)


def _print_details(accounts):
    console.print("\n[bold]DETAILED ANALYSIS — Top 5 Highest Risk[/bold]\n")
    for a in accounts:
        csm = a.get("csm_analysis", {})
        lines = [
            f"[bold cyan]{a['account_name']}[/bold cyan]  (${a['arr']:,.0f} ARR)",
            f"Score: [red]{a['risk_score']:.2f}[/red]  |  Renewal in {a['days_to_renewal']} days\n",
            "[bold]Risk signals:[/bold]",
            f"  • Usage Δ: {a.get('usage_decline_pct', 0):.1f}%",
            f"  • SDK: {a.get('sdk_version')} {'(DEPRECATED)' if a.get('on_deprecated_sdk') else '(CVE unpatched)' if a.get('on_vulnerable_sdk') else ''}",
            f"  • NPS: {int(a['nps_score']) if a.get('nps_score') is not None else 'N/A'} {'⚠️ ANOMALY' if a.get('nps_anomaly') else ''}",
            f"  • Open P1 tickets: {a.get('p1_ticket_count', 0)}",
            f"  • Longest open ticket: {a.get('max_open_days', 0)} days",
        ]
        if csm.get("competitive_threats"):
            lines.append(f"  • Competitors: {', '.join(csm['competitive_threats'])}")
        if csm.get("key_stakeholders_mentioned"):
            lines.append(f"  • Executives: {', '.join(csm['key_stakeholders_mentioned'])}")
        if a.get("explanation"):
            lines += ["", "[bold green]Recommended action:[/bold green]", a["explanation"]]

        color = "red" if a["risk_tier"] == "High" else "yellow"
        console.print(Panel("\n".join(lines), border_style=color))


def _print_insights(insights):
    console.print("\n[bold]NON-OBVIOUS INSIGHTS[/bold]\n")
    colors = {"critical": "red", "high": "yellow", "medium": "cyan"}

    for ins in insights:
        c = colors.get(ins.get("severity", "medium"), "white")
        names = ins.get("affected_account_names") or ins.get("affected_accounts", [])
        body = (
            f"[{c}]{ins['title']}[/{c}]\n\n"
            f"{ins['description']}\n\n"
            f"[bold]Affected:[/bold] {', '.join(str(n) for n in names)}\n"
            f"[bold]Action:[/bold] {ins.get('action', 'N/A')}"
        )
        console.print(Panel(body, border_style=c))


# ------------------------------------------------------------------
# JSON report
# ------------------------------------------------------------------

class _SafeEncoder(json.JSONEncoder):
    def default(self, obj):
        if isinstance(obj, (np.integer,)):    return int(obj)
        if isinstance(obj, (np.floating,)):   return float(obj)
        if isinstance(obj, (np.ndarray,)):    return obj.tolist()
        if isinstance(obj, pd.Timestamp):     return obj.strftime("%Y-%m-%d")
        try:
            if pd.isna(obj): return None
        except Exception:
            pass
        return super().default(obj)


def _save_report(accounts, insights, arr):
    os.makedirs(config.output_dir, exist_ok=True)

    clean = []
    for a in accounts:
        nps = a.get("nps_score")
        clean.append({
            "account_id":         a["account_id"],
            "account_name":       a["account_name"],
            "arr":                float(a["arr"]) if a.get("arr") else 0,
            "plan_tier":          a["plan_tier"],
            "industry":           a["industry"],
            "region":             a["region"],
            "csm_name":           a["csm_name"],
            "contract_end_date":  str(a["contract_end_date"]),
            "days_to_renewal":    int(a["days_to_renewal"]),
            "risk_score":         float(a["risk_score"]),
            "risk_tier":          a["risk_tier"],
            "sdk_version":        a.get("sdk_version"),
            "on_deprecated_sdk":  bool(a.get("on_deprecated_sdk")),
            "on_vulnerable_sdk":  bool(a.get("on_vulnerable_sdk")),
            "nps_score":          int(nps) if nps is not None else None,
            "nps_anomaly":        bool(a.get("nps_anomaly")),
            "nps_language":       a.get("nps_language"),
            "usage_decline_pct":  float(a.get("usage_decline_pct") or 0),
            "p1_ticket_count":    int(a.get("p1_ticket_count") or 0),
            "open_ticket_count":  int(a.get("open_ticket_count") or 0),
            "max_open_days":      int(a.get("max_open_days") or 0),
            "recurring_count":    int(a.get("recurring_count") or 0),
            "competitive_threats": a.get("competitive_threats", []),
            "key_stakeholders":   a.get("key_stakeholders", []),
            "explanation":        a.get("explanation", ""),
            "csm_risk_signals":   a.get("csm_risk_signals", []),
            "csm_action_items":   a.get("csm_action_items", []),
        })

    report = {
        "generated_at":     datetime.now().isoformat(),
        "reference_date":   config.reference_date,
        "renewal_window":   config.renewal_window_days,
        "summary": {
            "total":  len(accounts),
            "high":   sum(1 for a in accounts if a["risk_tier"] == "High"),
            "medium": sum(1 for a in accounts if a["risk_tier"] == "Medium"),
            "low":    sum(1 for a in accounts if a["risk_tier"] == "Low"),
            "arr_at_risk": arr,
        },
        "accounts": clean,
        "insights": insights,
    }

    path = os.path.join(config.output_dir, "risk_report.json")
    with open(path, "w") as f:
        json.dump(report, f, indent=2, cls=_SafeEncoder)


if __name__ == "__main__":
    main()
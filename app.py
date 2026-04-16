"""
Streamlit application — Renewal Intelligence Engine.
Run: streamlit run app.py
"""

import os
import sys
import pandas as pd
import streamlit as st
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from src.config import config
from src.data_ingestion import DataIngestion
from src.data_reconciliation import DataReconciliation
from src.feature_engineering import FeatureEngineering
from src.llm_analyzer import LLMAnalyzer
from src.risk_scorer import RiskScorer
from src.insight_detector import InsightDetector


st.set_page_config(
    page_title="Renewal Intelligence Engine",
    page_icon="🔍",
    layout="wide",
    initial_sidebar_state="expanded",
)


@st.cache_data(show_spinner=False)
def load_and_process_data():
    """Full pipeline — result is cached for the session."""
    ingestion = DataIngestion()
    ingestion.load_all()

    recon = DataReconciliation(ingestion)
    recon.reconcile_csm_notes()
    reconciled = recon.get_reconciled_data()

    fe = FeatureEngineering(reconciled)
    features = fe.compute_all_features()
    renewing = fe.get_renewing_accounts()

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

    scorer  = RiskScorer()
    scored  = scorer.score_all_accounts(features, csm_analyses)
    arr_at_risk = scorer.get_arr_at_risk(scored)

    for account in scored:
        if account["risk_tier"] in ("High", "Medium"):
            aid         = account["account_id"]
            explanation = llm.generate_account_explanation(account, csm_analyses.get(aid, {}))
            account["explanation"] = explanation

    detector = InsightDetector(llm)
    insights = detector.detect_all(features, csm_analyses)

    return scored, insights, arr_at_risk


# ------------------------------------------------------------------
# Main
# ------------------------------------------------------------------

def main():
    st.title("🔍 Renewal Intelligence Engine")
    st.caption(
        f"Contentstack BizOps  |  Reference date: {config.reference_date}  "
        f"|  Renewal window: {config.renewal_window_days} days"
    )

    with st.spinner("Running analysis pipeline…"):
        try:
            accounts, insights, arr_at_risk = load_and_process_data()
        except Exception as e:
            st.error(f"Pipeline error: {e}")
            st.stop()

    # ---- Sidebar filters ----
    st.sidebar.header("Filters")
    risk_filter = st.sidebar.multiselect(
        "Risk Tier", ["High", "Medium", "Low"], default=["High", "Medium"]
    )
    csm_filter = st.sidebar.multiselect(
        "CSM", sorted({a["csm_name"] for a in accounts}), default=[]
    )
    region_filter = st.sidebar.multiselect(
        "Region", sorted({a["region"] for a in accounts}), default=[]
    )
    industry_filter = st.sidebar.multiselect(
        "Industry", sorted({a["industry"] for a in accounts}), default=[]
    )
    max_arr = int(max((a["arr"] for a in accounts), default=2_000_000))
    arr_range = st.sidebar.slider(
        "ARR Range ($)", 0, max_arr, (0, max_arr), step=10_000, format="$%d"
    )

    filtered = [
        a for a in accounts
        if (not risk_filter     or a["risk_tier"] in risk_filter)
        and (not csm_filter     or a["csm_name"] in csm_filter)
        and (not region_filter  or a["region"] in region_filter)
        and (not industry_filter or a["industry"] in industry_filter)
        and arr_range[0] <= a["arr"] <= arr_range[1]
    ]

    tab1, tab2, tab3, tab4 = st.tabs(["📊 Dashboard", "📋 Account List", "🔎 Account Details", "💡 Insights"])

    with tab1:
        _dashboard(accounts, arr_at_risk, insights)
    with tab2:
        _account_list(filtered)
    with tab3:
        _account_details(accounts)
    with tab4:
        _insights_tab(insights)


# ------------------------------------------------------------------
# Tab renderers
# ------------------------------------------------------------------

def _dashboard(accounts, arr_at_risk, insights):
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Accounts in Window", len(accounts))
    c2.metric("🔴 High Risk",   sum(1 for a in accounts if a["risk_tier"] == "High"),
              f"${arr_at_risk['High']:,.0f} ARR")
    c3.metric("🟡 Medium Risk", sum(1 for a in accounts if a["risk_tier"] == "Medium"),
              f"${arr_at_risk['Medium']:,.0f} ARR")
    c4.metric("🟢 Low Risk",    sum(1 for a in accounts if a["risk_tier"] == "Low"),
              f"${arr_at_risk['Low']:,.0f} ARR")

    st.divider()
    st.subheader("🔴 Top High-Risk Accounts")

    high = [a for a in accounts if a["risk_tier"] == "High"][:6]
    if not high:
        st.info("No high-risk accounts in the current window.")
    else:
        for acc in high:
            _account_card(acc)

    if insights:
        st.divider()
        st.subheader("💡 Critical Insight")
        ins = insights[0]
        st.error(
            f"**{ins['title']}**\n\n"
            f"{ins['description']}\n\n"
            f"**Recommended action:** {ins.get('action', '')}"
        )


def _account_card(acc):
    label = (
        f"{acc['account_name']} — ${acc['arr']:,.0f} ARR | "
        f"Score: {acc['risk_score']:.2f} | Renewal in {acc['days_to_renewal']}d"
    )
    with st.expander(label):
        col1, col2 = st.columns(2)
        with col1:
            st.markdown("**Key metrics**")
            st.write(f"- SDK: `{acc.get('sdk_version', 'N/A')}`"
                     + (" ⚠️ *deprecated*" if acc.get("on_deprecated_sdk") else "")
                     + (" 🛡️ *CVE unpatched*" if acc.get("on_vulnerable_sdk") and not acc.get("on_deprecated_sdk") else ""))
            nps = acc.get("nps_score")
            nps_str = str(int(nps)) if nps is not None else "N/A"
            anomaly = " ❓ *anomaly*" if acc.get("nps_anomaly") else ""
            st.write(f"- NPS: {nps_str}{anomaly}")
            st.write(f"- Usage Δ 6m: {acc.get('usage_decline_pct', 0):.1f}%")
            st.write(f"- Open P1 tickets: {acc.get('p1_ticket_count', 0)}")
            st.write(f"- Longest open ticket: {acc.get('max_open_days', 0)} days")
        with col2:
            if acc.get("competitive_threats"):
                st.write(f"⚔️ **Competitors:** {', '.join(acc['competitive_threats'])}")
            if acc.get("key_stakeholders"):
                st.write(f"👔 **Executives:** {', '.join(acc['key_stakeholders'])}")
            explanation = acc.get("explanation", "")
            if explanation:
                st.info(explanation)


def _account_list(accounts):
    if not accounts:
        st.info("No accounts match the selected filters.")
        return

    rows = []
    for a in accounts:
        nps = a.get("nps_score")
        rows.append({
            "Account":        a["account_name"],
            "ARR":            f"${a['arr']:,.0f}",
            "Days":           a["days_to_renewal"],
            "Score":          round(a["risk_score"], 2),
            "Tier":           a["risk_tier"],
            "SDK":            a.get("sdk_version", "?"),
            "Deprecated":     "⚠️" if a.get("on_deprecated_sdk") else ("🛡️" if a.get("on_vulnerable_sdk") else ""),
            "NPS":            int(nps) if nps is not None else "-",
            "NPS⚠":          "❓" if a.get("nps_anomaly") else "",
            "P1 Open":        a.get("p1_ticket_count", 0),
            "Usage Δ":        f"{a.get('usage_decline_pct', 0):.0f}%",
            "CSM":            a["csm_name"],
            "Region":         a["region"],
            "Industry":       a["industry"],
        })

    st.dataframe(pd.DataFrame(rows), use_container_width=True, height=600)


def _account_details(accounts):
    selected_name = st.selectbox("Select account", [a["account_name"] for a in accounts])
    if not selected_name:
        return

    acc = next(a for a in accounts if a["account_name"] == selected_name)
    tier_icon = {"High": "🔴", "Medium": "🟡", "Low": "🟢"}.get(acc["risk_tier"], "")

    col1, col2 = st.columns([1, 1])

    with col1:
        st.header(acc["account_name"])
        st.markdown(f"**Risk:** {tier_icon} {acc['risk_tier']} (score: {acc['risk_score']:.2f})")
        st.markdown(f"**ARR:** ${acc['arr']:,.0f}")
        st.markdown(f"**Plan:** {acc['plan_tier']}")
        st.markdown(f"**Industry:** {acc['industry']}")
        st.markdown(f"**Region:** {acc['region']}")
        st.markdown(f"**CSM:** {acc['csm_name']}")
        end = acc["contract_end_date"]
        st.markdown(f"**Renewal:** {end.strftime('%Y-%m-%d')} ({acc['days_to_renewal']} days)")

    with col2:
        st.subheader("Risk Signals")
        signals = _collect_signals(acc)
        if signals:
            for emoji, title, desc in signals:
                st.warning(f"**{emoji} {title}**\n\n{desc}")
        else:
            st.success("No significant risk signals detected.")

    if acc.get("explanation"):
        st.divider()
        st.subheader("AI-Generated Summary")
        st.info(acc["explanation"])

    if acc.get("csm_notes"):
        st.divider()
        st.subheader("CSM Notes")
        for note in acc["csm_notes"]:
            with st.expander(f"Note — {note.get('date', 'Unknown date')}"):
                st.text(note["content"])

    if acc.get("csm_risk_signals"):
        st.subheader("LLM-Extracted Risk Signals")
        for sig in acc["csm_risk_signals"]:
            st.write(f"• {sig}")

    if acc.get("csm_action_items"):
        st.subheader("Recommended Actions")
        for action in acc["csm_action_items"]:
            st.write(f"▶ {action}")


def _collect_signals(acc):
    signals = []
    if acc.get("on_deprecated_sdk"):
        signals.append(("⚠️", "SDK Deprecated",
                         f"{acc['sdk_version']} — security patches end April 30, 2026"))
    elif acc.get("on_vulnerable_sdk"):
        signals.append(("🛡️", "Unpatched CVE",
                         f"{acc['sdk_version']} has unpatched CVE-2026-1102 (fix: upgrade to v4.3.2)"))
    if (acc.get("usage_decline_pct") or 0) < -15:
        signals.append(("📉", "Usage Decline",
                         f"{acc['usage_decline_pct']:.1f}% API call change over 6 months"))
    nps = acc.get("nps_score")
    if nps is not None and nps <= 6:
        signals.append(("😟", f"Low NPS ({int(nps)})", "Score in detractor range"))
    if acc.get("nps_anomaly"):
        signals.append(("❓", "NPS Anomaly",
                         "Score contradicts verbatim comment sentiment — treat NPS with caution"))
    if acc.get("nps_language") in ("zh", "es", "fr"):
        signals.append(("🌐", "Non-English NPS",
                         f"Comment in {acc['nps_language']} — verify translation for full signal"))
    if (acc.get("p1_ticket_count") or 0) > 0:
        signals.append(("🎫", "Open P1 Tickets",
                         f"{acc['p1_ticket_count']} unresolved critical ticket(s)"))
    if (acc.get("max_open_days") or 0) > 45:
        signals.append(("🕐", "Stale Tickets",
                         f"Oldest open ticket is {acc['max_open_days']} days old"))
    if acc.get("competitive_threats"):
        signals.append(("⚔️", "Competitive Evaluation",
                         f"Evaluating: {', '.join(acc['competitive_threats'])}"))
    if acc.get("key_stakeholders"):
        signals.append(("👔", "Executive Involvement",
                         f"Roles mentioned: {', '.join(acc['key_stakeholders'])}"))
    return signals


def _insights_tab(insights):
    st.header("💡 Non-Obvious Insights")
    st.caption("Patterns that simple rule-based alerts would miss")

    if not insights:
        st.info("No cross-account insights detected.")
        return

    sev_emoji = {"critical": "🚨", "high": "⚠️", "medium": "📌"}

    for ins in insights:
        emoji = sev_emoji.get(ins.get("severity", "medium"), "📌")
        with st.container():
            st.subheader(f"{emoji} {ins['title']}")
            col1, col2 = st.columns([2, 1])
            with col1:
                st.write(ins["description"])
                st.markdown(f"**Recommended action:** {ins.get('action', 'N/A')}")
            with col2:
                st.markdown("**Affected accounts:**")
                # Prefer human-readable names
                names = ins.get("affected_account_names") or ins.get("affected_accounts", [])
                for name in names:
                    st.write(f"• {name}")
                st.markdown(f"**Severity:** `{ins.get('severity', 'medium').upper()}`")
        st.divider()


if __name__ == "__main__":
    main()
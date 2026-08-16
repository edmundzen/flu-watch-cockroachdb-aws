import os
import streamlit as st
import psycopg2
import pandas as pd

st.set_page_config(page_title="Anomaly Review", layout="wide", page_icon="🚨")

st.markdown("""
<style>
.tier-badge { padding: .3rem .9rem; border-radius: 999px; font-size: .85rem; font-weight: 600; white-space: nowrap; display: inline-block; }
.badge-NORMAL { background: #d7f0d7; color: #1a7f37; }
.badge-WATCH  { background: #fbe3b4; color: #8a5b00; }
.badge-ALERT  { background: #f6d2d2; color: #c62828; }
.expl-box { background: rgba(128,128,128,.10); border-left: 4px solid #4c9ff0;
            padding: .8rem 1rem; border-radius: 4px; margin: .6rem 0; }
.expl-label { color: #1a73e8; font-weight: 600; font-size: .85rem; }
</style>
""", unsafe_allow_html=True)

hdr, rf = st.columns([6, 1])
hdr.title("📈 Anomaly review")
if rf.button("🔄 Refresh", help="Re-query the database"):
    st.rerun()

CONN_STR = os.environ.get("COCKROACH_CONN")
if not CONN_STR:
    st.error("COCKROACH_CONN not set. In PowerShell: $env:COCKROACH_CONN='postgresql://...'")
    st.stop()

@st.cache_resource
def get_conn():
    return psycopg2.connect(CONN_STR)

conn = get_conn()
st.success("Connected to CockroachDB ✅")

officer = st.text_input("Your name (recorded with each decision)", "Nandani Chauhan")
officer = officer.strip() or "Nandani Chauhan"

def decide(decision, rowid):
    with conn.cursor() as cur:
        cur.execute(
            "UPDATE anomaly_results SET decision=%s, reviewed_by=%s, reviewed_at=NOW() WHERE rowid=%s",
            (decision, officer, rowid))
    conn.commit()

# ---------- Anomaly cards (pending review) ----------
st.subheader("Pending review")
pending = pd.read_sql("""
    SELECT rowid, region, season_year, epi_week, current_cases,
           historical_avg_cases, explanation, alert_level, created_at
    FROM anomaly_results
    WHERE decision IS NULL
    ORDER BY created_at DESC
    LIMIT 20
""", conn)

if pending.empty:
    st.info("Nothing to review — run insert_test.py or wait for Nitish's Lambda.")
else:
    st.caption(f"Showing {len(pending)} latest pending rows")
    for _, r in pending.iterrows():
        tier = r['alert_level']
        with st.container(border=True):
            left, right = st.columns([4, 1])
            left.markdown(
                f"**{r['region']}**  \n"
                f"{int(r['season_year'])}, week {int(r['epi_week'])} · "
                f"{r['current_cases']:.0f} cases vs {r['historical_avg_cases']:.1f} average")
            right.markdown(
                f'<div style="text-align:right"><span class="tier-badge badge-{tier}">'
                f"{tier.title()}</span></div>", unsafe_allow_html=True)

            expl = r['explanation'] or "Explanation pending — Lambda hasn't processed this row yet."
            st.markdown(
                f'<div class="expl-box"><div class="expl-label">Bedrock explanation</div>'
                f"{expl}</div>", unsafe_allow_html=True)

            b1, b2 = st.columns(2)
            if b1.button("✓ Approve", key=f"a_{r['rowid']}"):
                decide("APPROVED", r['rowid'])
                st.rerun()
            if b2.button("✕ Reject", key=f"r_{r['rowid']}"):
                decide("REJECTED", r['rowid'])
                st.rerun()

# ---------- Active alerts (approved Watch/Alert rows) ----------
st.subheader("🚨 Active alerts")
active = pd.read_sql("""
    SELECT region, season_year, epi_week, current_cases, historical_avg_cases,
           alert_level, reviewed_by, reviewed_at
    FROM anomaly_results
    WHERE decision = 'APPROVED' AND alert_level IN ('WATCH', 'ALERT')
    ORDER BY reviewed_at DESC
""", conn)

if active.empty:
    st.caption("No active alerts — approved Watch/Alert rows appear here.")
else:
    for _, r in active.iterrows():
        tier = r['alert_level']
        st.markdown(
            f'<span class="tier-badge badge-{tier}">{tier.title()}</span> '
            f"<b>{r['region']}</b> — {int(r['season_year'])}, week {int(r['epi_week'])} · "
            f"{r['current_cases']:.0f} cases vs {r['historical_avg_cases']:.1f} avg · "
            f"approved by {r['reviewed_by']}", unsafe_allow_html=True)

# ---------- Decision log (audit trail) ----------
st.subheader("Decision log")
log = pd.read_sql("""
    SELECT region, season_year, epi_week, alert_level, decision, reviewed_by, reviewed_at
    FROM anomaly_results
    WHERE decision IS NOT NULL
    ORDER BY reviewed_at DESC
""", conn)
st.dataframe(log, use_container_width=True)
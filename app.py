"""
Streamlit Web App - Pension Clearing House File Analyzer
אפליקציית ניתוח קובץ מסלקה פנסיונית
"""

import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from pension_analyzer import parse_pension_xml, generate_insights, funds_to_dataframe

# --- Page Config ---
st.set_page_config(
    page_title="מנתח מסלקה פנסיונית",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded",
)

# RTL support
st.markdown("""
<style>
    .stApp { direction: rtl; }
    .stMarkdown, .stText, .stMetric, h1, h2, h3, p, div { direction: rtl; text-align: right; }
    [data-testid="stMetricValue"] { direction: ltr; }
    .stDataFrame { direction: ltr; }
    .recommendation-card {
        background: #f0f2f6; border-radius: 10px; padding: 15px; margin: 10px 0;
        border-right: 5px solid #ff6b6b;
    }
    .recommendation-card.medium { border-right-color: #ffa726; }
    .recommendation-card.low { border-right-color: #66bb6a; }
    .insight-box {
        background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
        color: white; border-radius: 10px; padding: 20px; margin: 10px 0;
    }
</style>
""", unsafe_allow_html=True)

st.title("📊 מנתח קובץ מסלקה פנסיונית")
st.markdown("העלה קובץ XML מהמסלקה הפנסיונית וקבל תמונת מצב מלאה ותובנות")

# --- File Upload ---
uploaded_file = st.file_uploader(
    "העלה קובץ מסלקה פנסיונית (XML)",
    type=["xml"],
    help="קובץ XML שהתקבל מהמסלקה הפנסיונית"
)

# --- Demo Mode ---
use_demo = st.sidebar.checkbox("🧪 הפעל מצב דמו עם נתוני דוגמה", value=not uploaded_file)

DEMO_XML = """<?xml version="1.0" encoding="UTF-8"?>
<MASLAKA-REPORT>
  <SHM-LAKOACH>ישראל ישראלי</SHM-LAKOACH>
  <MISPAR-ZIHUY>123456789</MISPAR-ZIHUY>
  <TAARICH-HAFAKAT-DOCH>2025-01-15</TAARICH-HAFAKAT-DOCH>

  <MUTZAR>
    <SHM-KUPA>מבטחים החדשה - פנסיה מקיפה</SHM-KUPA>
    <MIS-KUPA>510</MIS-KUPA>
    <SUG-KUPA>פנסיה</SUG-KUPA>
    <SHM-YATZRAN>מבטחים</SHM-YATZRAN>
    <STATUS>פעיל</STATUS>
    <YITRA>485000</YITRA>
    <HAFKADA-MAAVID>1850</HAFKADA-MAAVID>
    <HAFKADA-OVED>1200</HAFKADA-OVED>
    <HAFKADA-PITZUIM>950</HAFKADA-PITZUIM>
    <DMEY-NIHUL-HAFKADA>2.5</DMEY-NIHUL-HAFKADA>
    <DMEY-NIHUL-TZAVUR>0.35</DMEY-NIHUL-TZAVUR>
    <TASUA>8.2</TASUA>
    <MASLUL>מסלול כללי</MASLUL>
    <KISUY-BITUCHI>750000</KISUY-BITUCHI>
    <AVUR-BITUACH>180</AVUR-BITUACH>
    <TAARICH-HAFKADA-ACHRONA>2025-01-01</TAARICH-HAFKADA-ACHRONA>
    <TAARICH-PTICHA>2015-03-10</TAARICH-PTICHA>
  </MUTZAR>

  <MUTZAR>
    <SHM-KUPA>הראל השתלמות</SHM-KUPA>
    <MIS-KUPA>1120</MIS-KUPA>
    <SUG-KUPA>השתלמות</SUG-KUPA>
    <SHM-YATZRAN>הראל</SHM-YATZRAN>
    <STATUS>פעיל</STATUS>
    <YITRA>120000</YITRA>
    <HAFKADA-MAAVID>1125</HAFKADA-MAAVID>
    <HAFKADA-OVED>375</HAFKADA-OVED>
    <HAFKADA-PITZUIM>0</HAFKADA-PITZUIM>
    <DMEY-NIHUL-HAFKADA>1.5</DMEY-NIHUL-HAFKADA>
    <DMEY-NIHUL-TZAVUR>0.7</DMEY-NIHUL-TZAVUR>
    <TASUA>12.5</TASUA>
    <MASLUL>מסלול מנייתי</MASLUL>
    <KISUY-BITUCHI>0</KISUY-BITUCHI>
    <AVUR-BITUACH>0</AVUR-BITUACH>
    <TAARICH-HAFKADA-ACHRONA>2025-01-01</TAARICH-HAFKADA-ACHRONA>
    <TAARICH-PTICHA>2018-06-15</TAARICH-PTICHA>
  </MUTZAR>

  <MUTZAR>
    <SHM-KUPA>כלל גמל</SHM-KUPA>
    <MIS-KUPA>2250</MIS-KUPA>
    <SUG-KUPA>גמל</SUG-KUPA>
    <SHM-YATZRAN>כלל ביטוח</SHM-YATZRAN>
    <STATUS>פעיל</STATUS>
    <YITRA>67000</YITRA>
    <HAFKADA-MAAVID>500</HAFKADA-MAAVID>
    <HAFKADA-OVED>500</HAFKADA-OVED>
    <HAFKADA-PITZUIM>0</HAFKADA-PITZUIM>
    <DMEY-NIHUL-HAFKADA>4.5</DMEY-NIHUL-HAFKADA>
    <DMEY-NIHUL-TZAVUR>1.2</DMEY-NIHUL-TZAVUR>
    <TASUA>5.1</TASUA>
    <MASLUL>מסלול כללי</MASLUL>
    <KISUY-BITUCHI>0</KISUY-BITUCHI>
    <AVUR-BITUACH>0</AVUR-BITUACH>
    <TAARICH-HAFKADA-ACHRONA>2024-08-01</TAARICH-HAFKADA-ACHRONA>
    <TAARICH-PTICHA>2012-09-20</TAARICH-PTICHA>
  </MUTZAR>

  <MUTZAR>
    <SHM-KUPA>מגדל פנסיה ישנה</SHM-KUPA>
    <MIS-KUPA>3300</MIS-KUPA>
    <SUG-KUPA>פנסיה</SUG-KUPA>
    <SHM-YATZRAN>מגדל</SHM-YATZRAN>
    <STATUS>לא פעיל</STATUS>
    <YITRA>32000</YITRA>
    <HAFKADA-MAAVID>0</HAFKADA-MAAVID>
    <HAFKADA-OVED>0</HAFKADA-OVED>
    <HAFKADA-PITZUIM>0</HAFKADA-PITZUIM>
    <DMEY-NIHUL-HAFKADA>0</DMEY-NIHUL-HAFKADA>
    <DMEY-NIHUL-TZAVUR>1.1</DMEY-NIHUL-TZAVUR>
    <TASUA>3.8</TASUA>
    <MASLUL>מסלול אג"ח</MASLUL>
    <KISUY-BITUCHI>0</KISUY-BITUCHI>
    <AVUR-BITUACH>0</AVUR-BITUACH>
    <TAARICH-HAFKADA-ACHRONA>2014-12-01</TAARICH-HAFKADA-ACHRONA>
    <TAARICH-PTICHA>2008-01-15</TAARICH-PTICHA>
  </MUTZAR>

  <MUTZAR>
    <SHM-KUPA>הפניקס ביטוח מנהלים</SHM-KUPA>
    <MIS-KUPA>4401</MIS-KUPA>
    <SUG-KUPA>ביטוח</SUG-KUPA>
    <SHM-YATZRAN>הפניקס</SHM-YATZRAN>
    <STATUS>פעיל</STATUS>
    <YITRA>210000</YITRA>
    <HAFKADA-MAAVID>1400</HAFKADA-MAAVID>
    <HAFKADA-OVED>700</HAFKADA-OVED>
    <HAFKADA-PITZUIM>600</HAFKADA-PITZUIM>
    <DMEY-NIHUL-HAFKADA>5.2</DMEY-NIHUL-HAFKADA>
    <DMEY-NIHUL-TZAVUR>0.85</DMEY-NIHUL-TZAVUR>
    <TASUA>-1.2</TASUA>
    <MASLUL>מסלול הלכה</MASLUL>
    <KISUY-BITUCHI>500000</KISUY-BITUCHI>
    <AVUR-BITUACH>250</AVUR-BITUACH>
    <TAARICH-HAFKADA-ACHRONA>2025-01-01</TAARICH-HAFKADA-ACHRONA>
    <TAARICH-PTICHA>2010-07-01</TAARICH-PTICHA>
  </MUTZAR>
</MASLAKA-REPORT>
"""


def render_report(insights: dict):
    """Render the full analysis dashboard."""

    # --- Header Info ---
    if insights.get("owner_name"):
        st.markdown(f"### 👤 {insights['owner_name']}")
    col_info1, col_info2 = st.columns(2)
    if insights.get("owner_id"):
        col_info1.markdown(f"**ת.ז.:** {insights['owner_id']}")
    if insights.get("report_date"):
        col_info2.markdown(f"**תאריך דוח:** {insights['report_date']}")

    st.divider()

    # --- KPI Cards ---
    st.subheader("תמונת מצב כללית")
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("סה\"כ חיסכון", f"₪{insights['total_balance']:,.0f}")
    c2.metric("קופות פעילות", insights["active_funds_count"])
    c3.metric("קופות לא פעילות", insights["inactive_funds_count"])
    c4.metric("עלות ביטוח חודשית", f"₪{insights['total_insurance_cost']:,.0f}")

    st.divider()

    # --- Charts ---
    st.subheader("התפלגות חסכונות")
    col_chart1, col_chart2 = st.columns(2)

    # Pie by type
    type_data = {k: v["total_balance"] for k, v in insights["type_summary"].items()}
    if type_data:
        fig_pie = px.pie(
            names=list(type_data.keys()),
            values=list(type_data.values()),
            title="התפלגות לפי סוג מוצר",
            hole=0.4,
        )
        fig_pie.update_traces(textinfo="label+percent+value", texttemplate="%{label}<br>₪%{value:,.0f}<br>%{percent}")
        col_chart1.plotly_chart(fig_pie, use_container_width=True)

    # Bar by company
    company_data = insights.get("by_company", {})
    if company_data:
        fig_bar = px.bar(
            x=list(company_data.keys()),
            y=[v["balance"] for v in company_data.values()],
            title="יתרה לפי חברה מנהלת",
            labels={"x": "חברה", "y": "יתרה (₪)"},
            text=[f"₪{v['balance']:,.0f}" for v in company_data.values()],
        )
        fig_bar.update_traces(textposition="outside")
        col_chart2.plotly_chart(fig_bar, use_container_width=True)

    # Returns & Fees chart
    funds = insights["funds"]
    active = [f for f in funds if "פעיל" in (f.status or "פעיל") or not f.status]
    if active:
        st.subheader("תשואות ודמי ניהול")
        col_r1, col_r2 = st.columns(2)

        fig_return = go.Figure()
        fig_return.add_trace(go.Bar(
            x=[f.fund_name for f in active],
            y=[f.annual_return for f in active],
            marker_color=["#ef5350" if f.annual_return < 0 else "#66bb6a" for f in active],
            text=[f"{f.annual_return}%" for f in active],
            textposition="outside",
        ))
        fig_return.update_layout(title="תשואה שנתית (%)", yaxis_title="%")
        col_r1.plotly_chart(fig_return, use_container_width=True)

        fig_fees = go.Figure()
        fig_fees.add_trace(go.Bar(
            name="מהפקדות",
            x=[f.fund_name for f in active],
            y=[f.management_fee_deposits for f in active],
        ))
        fig_fees.add_trace(go.Bar(
            name="מצבירה",
            x=[f.fund_name for f in active],
            y=[f.management_fee_balance for f in active],
        ))
        fig_fees.update_layout(title="דמי ניהול (%)", barmode="group", yaxis_title="%")
        col_r2.plotly_chart(fig_fees, use_container_width=True)

    st.divider()

    # --- Recommendations ---
    recommendations = insights.get("recommendations", [])
    if recommendations:
        st.subheader("💡 תובנות והמלצות")
        for rec in recommendations:
            priority_class = "medium" if rec["priority"] == "בינונית" else ("low" if rec["priority"] == "נמוכה" else "")
            priority_emoji = "🔴" if rec["priority"] == "גבוהה" else ("🟡" if rec["priority"] == "בינונית" else "🟢")
            st.markdown(f"""
<div class="recommendation-card {priority_class}">
    <strong>{priority_emoji} {rec['title']}</strong> &nbsp; <small>(עדיפות: {rec['priority']})</small><br>
    {rec['detail']}
</div>
""", unsafe_allow_html=True)

    st.divider()

    # --- Detailed Table ---
    st.subheader("טבלת פירוט מוצרים")
    df = funds_to_dataframe(funds)
    st.dataframe(
        df.style.format({
            "יתרה (₪)": "₪{:,.0f}",
            "הפקדת מעביד (₪)": "₪{:,.0f}",
            "הפקדת עובד (₪)": "₪{:,.0f}",
            "פיצויים (₪)": "₪{:,.0f}",
            "סה\"כ הפקדה (₪)": "₪{:,.0f}",
            "דמי ניהול הפקדה (%)": "{:.2f}%",
            "דמי ניהול צבירה (%)": "{:.2f}%",
            "תשואה שנתית (%)": "{:.1f}%",
            "כיסוי ביטוחי (₪)": "₪{:,.0f}",
            "עלות ביטוח חודשית (₪)": "₪{:,.0f}",
        }),
        use_container_width=True,
        height=400,
    )

    # --- Export ---
    csv = df.to_csv(index=False).encode("utf-8-sig")
    st.download_button("📥 ייצוא לקובץ CSV", csv, "pension_report.csv", "text/csv")


# --- Main Flow ---
xml_content = None

if uploaded_file:
    xml_content = uploaded_file.read().decode("utf-8")
elif use_demo:
    xml_content = DEMO_XML
    st.info("מוצגים נתוני דוגמה. העלה קובץ XML אמיתי לניתוח נתונים שלך.")

if xml_content:
    try:
        report = parse_pension_xml(xml_content)
        if not report.funds:
            st.error("לא נמצאו מוצרים פנסיוניים בקובץ. ודא שהקובץ בפורמט מסלקה תקין.")
        else:
            insights = generate_insights(report)
            render_report(insights)
    except Exception as e:
        st.error(f"שגיאה בפענוח הקובץ: {e}")
        st.info("ודא שהקובץ הוא XML תקין בפורמט מסלקה פנסיונית.")

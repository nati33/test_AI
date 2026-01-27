"""
Pension Clearing House File Analyzer (מנתח קובץ מסלקה פנסיונית)

Parses Israeli pension clearing house XML files (Maslaka format)
and generates insights, summaries, and visualizations.
"""

import xml.etree.ElementTree as ET
import pandas as pd
import io
import re
from dataclasses import dataclass, field
from typing import Optional


# --- Data Models ---

@dataclass
class Fund:
    """Represents a single pension/savings fund product."""
    fund_name: str = ""
    fund_number: str = ""
    fund_type: str = ""  # פנסיה, גמל, השתלמות, ביטוח
    managing_company: str = ""
    status: str = ""  # פעיל / לא פעיל
    balance: float = 0.0
    employer_contribution: float = 0.0
    employee_contribution: float = 0.0
    severance_contribution: float = 0.0
    total_contribution: float = 0.0
    management_fee_deposits: float = 0.0  # דמי ניהול מהפקדות (%)
    management_fee_balance: float = 0.0   # דמי ניהול מצבירה (%)
    annual_return: float = 0.0            # תשואה שנתית (%)
    investment_track: str = ""            # מסלול השקעה
    insurance_coverage: float = 0.0       # כיסוי ביטוחי
    insurance_monthly_cost: float = 0.0   # עלות ביטוח חודשית
    last_deposit_date: str = ""
    opening_date: str = ""


@dataclass
class PensionReport:
    """Full parsed pension report from clearing house file."""
    owner_name: str = ""
    owner_id: str = ""
    report_date: str = ""
    funds: list = field(default_factory=list)


# --- XML Parsing ---

def _get_text(element, tag, default=""):
    """Safely get text from an XML child element."""
    if element is None:
        return default
    child = element.find(tag)
    if child is not None and child.text:
        return child.text.strip()
    # Try case-insensitive and namespace-agnostic search
    for c in element:
        local_name = c.tag.split("}")[-1] if "}" in c.tag else c.tag
        if local_name.lower() == tag.lower():
            return (c.text or "").strip()
    return default


def _get_float(element, tag, default=0.0):
    """Safely get float from an XML child element."""
    text = _get_text(element, tag, "")
    if not text:
        return default
    try:
        return float(re.sub(r"[^\d.\-]", "", text))
    except (ValueError, TypeError):
        return default


def _classify_fund_type(raw_type: str, fund_name: str) -> str:
    """Classify fund type into standard Hebrew categories."""
    combined = f"{raw_type} {fund_name}".lower()
    if any(k in combined for k in ["פנסיה", "פנסי", "pension", "pensia"]):
        return "פנסיה"
    if any(k in combined for k in ["השתלמות", "hishtalmut"]):
        return "קרן השתלמות"
    if any(k in combined for k in ["גמל", "gemel"]):
        return "קופת גמל"
    if any(k in combined for k in ["ביטוח", "bituach", "insurance"]):
        return "ביטוח מנהלים"
    return raw_type or "לא ידוע"


# Tag name mappings for common Maslaka XML variants
_TAG_ALIASES = {
    "fund_name": ["SHM-KUPA", "SHEM-KUPA", "ShmKupa", "ShemKupa", "FundName", "שם-קופה", "שם_קופה", "ProductName"],
    "fund_number": ["MIS-KUPA", "MISPAR-KUPA", "MisKupa", "FundNumber", "מספר-קופה", "ProductNumber"],
    "fund_type": ["SUG-KUPA", "SugKupa", "FundType", "סוג-קופה", "ProductType"],
    "managing_company": ["SHM-YATZRAN", "SHEM-YATZRAN", "ShmYatzran", "CompanyName", "שם-יצרן", "ManagingCompany"],
    "status": ["STATUS", "Status", "סטטוס", "ProductStatus"],
    "balance": ["YITRA", "Yitra", "Balance", "יתרה", "TotalSavings", "TOTAL-SAVING", "SCHUM-TZAVUR"],
    "employer_contribution": ["HAFKADA-MAAVID", "HafkadaMaavid", "EmployerDeposit", "הפקדת-מעביד"],
    "employee_contribution": ["HAFKADA-OVED", "HafkadaOved", "EmployeeDeposit", "הפקדת-עובד"],
    "severance_contribution": ["HAFKADA-PITZUIM", "HafkadaPitzuim", "SeveranceDeposit", "הפקדת-פיצויים"],
    "total_contribution": ["TOTAL-HAFKADA", "TotalHafkada", "TotalDeposit", "סה\"כ-הפקדה"],
    "management_fee_deposits": ["DMEY-NIHUL-HAFKADA", "DmeyNihulHafkada", "MgmtFeeDeposit", "דמי-ניהול-הפקדה"],
    "management_fee_balance": ["DMEY-NIHUL-TZAVUR", "DmeyNihulTzavur", "MgmtFeeBalance", "דמי-ניהול-צבירה"],
    "annual_return": ["TASUA", "Tasua", "AnnualReturn", "תשואה"],
    "investment_track": ["MASLUL", "Maslul", "InvestmentTrack", "מסלול-השקעה"],
    "insurance_coverage": ["KISUY-BITUCHI", "KisuyBituchi", "InsuranceCoverage", "כיסוי-ביטוחי"],
    "insurance_monthly_cost": ["AVUR-BITUACH", "AvurBituach", "InsuranceCost", "עלות-ביטוח"],
    "last_deposit_date": ["TAARICH-HAFKADA-ACHRONA", "LastDepositDate", "תאריך-הפקדה-אחרונה"],
    "opening_date": ["TAARICH-PTICHA", "OpeningDate", "תאריך-פתיחה"],
}

_OWNER_NAME_TAGS = ["SHM-LAKOACH", "SHEM-LAKOACH", "ShmLakoach", "OwnerName", "שם-לקוח", "ClientName"]
_OWNER_ID_TAGS = ["MISPAR-ZIHUY", "MisparZihuy", "OwnerID", "מספר-זיהוי", "IdNumber", "TZ"]
_REPORT_DATE_TAGS = ["TAARICH-HAFAKAT-DOCH", "ReportDate", "תאריך-הפקת-דוח"]
_PRODUCT_TAGS = ["MUTZAR", "Mutzar", "Product", "מוצר", "KUPA", "Kupa", "Fund", "RECORD", "Record"]


def _find_any(element, tag_list):
    """Find first matching child element from a list of possible tag names."""
    for tag in tag_list:
        found = element.find(tag)
        if found is not None:
            return found
        # Namespace-agnostic
        for child in element:
            local = child.tag.split("}")[-1] if "}" in child.tag else child.tag
            if local == tag:
                return child
    return None


def _get_any_text(element, tag_list, default=""):
    for tag in tag_list:
        val = _get_text(element, tag, "")
        if val:
            return val
    return default


def _get_any_float(element, tag_list, default=0.0):
    for tag in tag_list:
        val = _get_float(element, tag, 0.0)
        if val != 0.0:
            return val
    return default


def _find_product_elements(root):
    """Recursively find all product/fund elements in the XML tree."""
    results = []
    for tag in _PRODUCT_TAGS:
        results.extend(root.iter(tag))
        # Also namespace-agnostic
        for elem in root.iter():
            local = elem.tag.split("}")[-1] if "}" in elem.tag else elem.tag
            if local == tag and elem not in results:
                results.append(elem)
    if not results:
        # Fallback: look for elements that have balance-like children
        for elem in root.iter():
            for bal_tag in _TAG_ALIASES["balance"]:
                if elem.find(bal_tag) is not None:
                    if elem not in results:
                        results.append(elem)
                    break
    return results


def parse_pension_xml(xml_content: str) -> PensionReport:
    """Parse a Maslaka pension XML file and return structured data."""
    root = ET.fromstring(xml_content)
    report = PensionReport()

    # Extract owner info from anywhere in the tree
    for elem in root.iter():
        if not report.owner_name:
            report.owner_name = _get_any_text(elem, _OWNER_NAME_TAGS)
        if not report.owner_id:
            report.owner_id = _get_any_text(elem, _OWNER_ID_TAGS)
        if not report.report_date:
            report.report_date = _get_any_text(elem, _REPORT_DATE_TAGS)
        if report.owner_name and report.owner_id and report.report_date:
            break

    # Parse products
    products = _find_product_elements(root)
    for prod_elem in products:
        fund = Fund()
        fund.fund_name = _get_any_text(prod_elem, _TAG_ALIASES["fund_name"])
        fund.fund_number = _get_any_text(prod_elem, _TAG_ALIASES["fund_number"])
        raw_type = _get_any_text(prod_elem, _TAG_ALIASES["fund_type"])
        fund.fund_type = _classify_fund_type(raw_type, fund.fund_name)
        fund.managing_company = _get_any_text(prod_elem, _TAG_ALIASES["managing_company"])
        fund.status = _get_any_text(prod_elem, _TAG_ALIASES["status"]) or "פעיל"
        fund.balance = _get_any_float(prod_elem, _TAG_ALIASES["balance"])
        fund.employer_contribution = _get_any_float(prod_elem, _TAG_ALIASES["employer_contribution"])
        fund.employee_contribution = _get_any_float(prod_elem, _TAG_ALIASES["employee_contribution"])
        fund.severance_contribution = _get_any_float(prod_elem, _TAG_ALIASES["severance_contribution"])
        fund.total_contribution = _get_any_float(prod_elem, _TAG_ALIASES["total_contribution"])
        if fund.total_contribution == 0:
            fund.total_contribution = fund.employer_contribution + fund.employee_contribution + fund.severance_contribution
        fund.management_fee_deposits = _get_any_float(prod_elem, _TAG_ALIASES["management_fee_deposits"])
        fund.management_fee_balance = _get_any_float(prod_elem, _TAG_ALIASES["management_fee_balance"])
        fund.annual_return = _get_any_float(prod_elem, _TAG_ALIASES["annual_return"])
        fund.investment_track = _get_any_text(prod_elem, _TAG_ALIASES["investment_track"])
        fund.insurance_coverage = _get_any_float(prod_elem, _TAG_ALIASES["insurance_coverage"])
        fund.insurance_monthly_cost = _get_any_float(prod_elem, _TAG_ALIASES["insurance_monthly_cost"])
        fund.last_deposit_date = _get_any_text(prod_elem, _TAG_ALIASES["last_deposit_date"])
        fund.opening_date = _get_any_text(prod_elem, _TAG_ALIASES["opening_date"])

        if fund.fund_name or fund.balance > 0:
            report.funds.append(fund)

    return report


# --- Analysis Engine ---

def generate_insights(report: PensionReport) -> dict:
    """Generate insights and summary from parsed pension report."""
    funds = report.funds
    if not funds:
        return {"error": "לא נמצאו מוצרים פנסיוניים בקובץ"}

    active_funds = [f for f in funds if "פעיל" in f.status or not f.status or f.status == "פעיל"]
    inactive_funds = [f for f in funds if f not in active_funds]

    total_balance = sum(f.balance for f in funds)
    active_balance = sum(f.balance for f in active_funds)

    # Group by type
    by_type = {}
    for f in funds:
        by_type.setdefault(f.fund_type, []).append(f)

    type_summary = {}
    for ftype, flist in by_type.items():
        type_summary[ftype] = {
            "count": len(flist),
            "total_balance": sum(f.balance for f in flist),
            "funds": flist,
        }

    # Management fees analysis
    high_fee_funds = []
    for f in active_funds:
        issues = []
        if f.management_fee_deposits > 4.0:
            issues.append(f"דמי ניהול מהפקדות גבוהים: {f.management_fee_deposits}%")
        if f.management_fee_balance > 1.0:
            issues.append(f"דמי ניהול מצבירה גבוהים: {f.management_fee_balance}%")
        if issues:
            high_fee_funds.append({"fund": f, "issues": issues})

    # Returns analysis
    low_return_funds = [f for f in active_funds if f.annual_return < 0]
    top_return_funds = sorted(active_funds, key=lambda f: f.annual_return, reverse=True)[:3]

    # Insurance analysis
    insured_funds = [f for f in active_funds if f.insurance_coverage > 0]
    total_insurance_cost = sum(f.insurance_monthly_cost for f in active_funds)

    # Duplicate coverage check
    coverage_types = {}
    for f in insured_funds:
        coverage_types.setdefault(f.fund_type, []).append(f)
    duplicate_coverage = {k: v for k, v in coverage_types.items() if len(v) > 1}

    # Inactive funds with balance
    inactive_with_balance = [f for f in inactive_funds if f.balance > 0]

    # Recommendations
    recommendations = []
    if inactive_with_balance:
        total_inactive = sum(f.balance for f in inactive_with_balance)
        recommendations.append({
            "title": "איחוד קופות לא פעילות",
            "detail": f"נמצאו {len(inactive_with_balance)} קופות לא פעילות עם יתרה כוללת של ₪{total_inactive:,.0f}. מומלץ לבחון איחוד.",
            "priority": "גבוהה",
        })
    if high_fee_funds:
        recommendations.append({
            "title": "הפחתת דמי ניהול",
            "detail": f"נמצאו {len(high_fee_funds)} קופות עם דמי ניהול גבוהים מהממוצע בשוק. מומלץ לנהל מו\"מ להפחתה.",
            "priority": "גבוהה",
        })
    if duplicate_coverage:
        recommendations.append({
            "title": "בדיקת כפילות ביטוחית",
            "detail": f"נמצאו כיסויים ביטוחיים כפולים ב-{len(duplicate_coverage)} קטגוריות. מומלץ לבדוק ולמנוע תשלום כפול.",
            "priority": "בינונית",
        })
    if low_return_funds:
        recommendations.append({
            "title": "בחינת מסלולי השקעה",
            "detail": f"{len(low_return_funds)} קופות מציגות תשואה שלילית. מומלץ לבחון את מסלול ההשקעה.",
            "priority": "בינונית",
        })

    # Companies
    by_company = {}
    for f in funds:
        if f.managing_company:
            by_company.setdefault(f.managing_company, []).append(f)

    return {
        "owner_name": report.owner_name,
        "owner_id": report.owner_id,
        "report_date": report.report_date,
        "total_funds": len(funds),
        "active_funds_count": len(active_funds),
        "inactive_funds_count": len(inactive_funds),
        "total_balance": total_balance,
        "active_balance": active_balance,
        "type_summary": type_summary,
        "by_company": {k: {"count": len(v), "balance": sum(f.balance for f in v)} for k, v in by_company.items()},
        "high_fee_funds": high_fee_funds,
        "low_return_funds": low_return_funds,
        "top_return_funds": top_return_funds,
        "insured_funds": insured_funds,
        "total_insurance_cost": total_insurance_cost,
        "duplicate_coverage": duplicate_coverage,
        "inactive_with_balance": inactive_with_balance,
        "recommendations": recommendations,
        "funds": funds,
    }


def funds_to_dataframe(funds: list) -> pd.DataFrame:
    """Convert list of Fund objects to a pandas DataFrame."""
    rows = []
    for f in funds:
        rows.append({
            "שם קופה": f.fund_name,
            "מספר קופה": f.fund_number,
            "סוג": f.fund_type,
            "חברה מנהלת": f.managing_company,
            "סטטוס": f.status,
            "יתרה (₪)": f.balance,
            "הפקדת מעביד (₪)": f.employer_contribution,
            "הפקדת עובד (₪)": f.employee_contribution,
            "פיצויים (₪)": f.severance_contribution,
            "סה\"כ הפקדה (₪)": f.total_contribution,
            "דמי ניהול הפקדה (%)": f.management_fee_deposits,
            "דמי ניהול צבירה (%)": f.management_fee_balance,
            "תשואה שנתית (%)": f.annual_return,
            "מסלול השקעה": f.investment_track,
            "כיסוי ביטוחי (₪)": f.insurance_coverage,
            "עלות ביטוח חודשית (₪)": f.insurance_monthly_cost,
        })
    return pd.DataFrame(rows)

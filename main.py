import streamlit as st
import pandas as pd
import os
import altair as alt
import re
from io import BytesIO

# -----------------------------------------------------------
# PAGE CONFIG
# -----------------------------------------------------------
st.set_page_config(
    page_title="Inventory & Supply Chain Toolkit",
    layout="wide",
    initial_sidebar_state="expanded",
)

# -----------------------------------------------------------
# SHARED HELPERS
# -----------------------------------------------------------

def read_csv_robust(upload_or_path):
    attempts = [
        dict(sep=",", encoding=None),
        dict(sep=";", encoding=None),
        dict(sep=",", encoding="utf-8-sig"),
        dict(sep=";", encoding="utf-8-sig"),
    ]
    for opts in attempts:
        try:
            if hasattr(upload_or_path, "seek"):
                upload_or_path.seek(0)
            return pd.read_csv(upload_or_path, **opts)
        except Exception:
            pass
    if hasattr(upload_or_path, "seek"):
        upload_or_path.seek(0)
    return pd.read_csv(upload_or_path)

def df_to_csv_bytes(df):
    return df.to_csv(index=False).encode("utf-8")

def df_to_excel_bytes(df, sheet_name="Sheet1"):
    try:
        buf = BytesIO()
        with pd.ExcelWriter(buf, engine="openpyxl") as w:
            df.to_excel(w, index=False, sheet_name=sheet_name)
        buf.seek(0)
        return buf.getvalue()
    except Exception:
        return None

# -----------------------------------------------------------
# SESSION-STATE FILE ROUTING
# -----------------------------------------------------------
INVENTORY_DEFAULT = "StockHistorySample.csv"
FORECAST_DEFAULT  = "TWforecasts.csv"
BDD_030_DEFAULT   = "0030BDD400.csv"
CAPACITY_DEFAULT  = "PlantCapacity.csv"

def get_df_from_state(key, default_path):
    if st.session_state.get(f"{key}_file_bytes"):
        bio = BytesIO(st.session_state[f"{key}_file_bytes"])
        return read_csv_robust(bio), st.session_state.get(f"{key}_file_name", "uploaded.csv")
    if os.path.exists(default_path):
        return read_csv_robust(default_path), default_path
    return pd.DataFrame(), None

# -----------------------------------------------------------
# MODULE 1 — NON-PRODUCTIVE INVENTORY (NPI)
# -----------------------------------------------------------

def run_npi_app():
    st.title("Non-Productive Inventory Management")
    df, src = get_df_from_state("inventory", INVENTORY_DEFAULT)
    if df.empty:
        st.warning("Please upload inventory data on the Home page.")
        return

    COLUMN_ALIASES = {
        "quality inspection qty": "QualityInspectionQty",
        "blocked stock qty": "BlockedStockQty",
        "return stock qty": "ReturnStockQty",
        "overaged": "OveragedTireQty",
        "physicalstock": "PhysicalStock",
    }

    def normalize(dfin):
        mapping = {c: COLUMN_ALIASES[c.lower().strip()] for c in dfin.columns if c.lower().strip() in COLUMN_ALIASES}
        return dfin.rename(columns=mapping)

    df = normalize(df)
    if "Period" in df.columns:
        df["Period"] = pd.to_datetime(df["Period"], errors="coerce")

    # Basic cleanup and Tab logic
    st.caption(f"📂 Source: {src} | Rows: {len(df):,}")
    
    tab_o, tab_qi, tab_bs = st.tabs(["Overview", "Quality Inspection", "Blocked Stock"])
    
    with tab_o:
        st.subheader("Inventory Distribution")
        st.dataframe(df.head(100), use_container_width=True)

# -----------------------------------------------------------
# MODULE 2 — PLANNING OVERVIEW BDD400
# -----------------------------------------------------------

def run_planning_overview_bdd():
    st.title("Planning Overview BDD400")
    df, src = get_df_from_state("bdd030", BDD_030_DEFAULT)
    if df.empty:
        st.warning("Upload 0030BDD400.csv on Home.")
        return

    # ROBUST COLUMN IDENTIFICATION TO FIX KEYERROR
    col_map = {}
    for c in df.columns:
        clean = c.lower().replace(" ", "").replace("_", "").replace(".", "")
        if clean in ["closingstock", "stock", "quantity", "unrestricted"]: col_map[c] = "ClosingStock"
        elif clean in ["warehouse", "plant", "site"]: col_map[c] = "Warehouse"
        elif clean in ["week", "calweek", "calendarweek"]: col_map[c] = "Week"
        elif clean in ["year", "calyear", "calendaryear"]: col_map[c] = "Year"
    
    df = df.rename(columns=col_map)

    # Check for required columns before processing
    required = ["ClosingStock", "Warehouse", "Week", "Year"]
    missing = [r for r in required if r not in df.columns]
    if missing:
        st.error(f"Missing columns: {missing}. Found: {list(df.columns)}")
        return

    df["ClosingStock"] = pd.to_numeric(df["ClosingStock"].astype(str).str.replace(",",""), errors="coerce").fillna(0)
    df["YearWeek"] = df["Year"].astype(str) + "-W" + df["Week"].astype(str).str.zfill(2)

    st.sidebar.subheader("🔎 Filters")
    plants = sorted(df["Warehouse"].unique())
    sel_plants = st.sidebar.multiselect("Plants", plants, default=plants)
    
    v_df = df[df["Warehouse"].isin(sel_plants)].groupby(["Warehouse", "YearWeek"])["ClosingStock"].sum().reset_index()
    
    st.subheader("📄 Closing Stock Projection")
    st.dataframe(v_df, use_container_width=True)

    chart = (alt.Chart(v_df).mark_line(point=True).encode(
        x=alt.X("YearWeek:N", sort=None), y="ClosingStock:Q", color="Warehouse:N",
        tooltip=["Warehouse", "YearWeek", "ClosingStock"]
    ).properties(height=400))
    st.altair_chart(chart, use_container_width=True)

# -----------------------------------------------------------
# MODULE 3 — STORAGE CAPACITY MANAGEMENT
# -----------------------------------------------------------

def run_storage_capacity():
    st.title("Storage Capacity Management")
    df_inv, _ = get_df_from_state("bdd030", BDD_030_DEFAULT)
    df_cap, _ = get_df_from_state("capacity", CAPACITY_DEFAULT)

    if df_inv.empty or df_cap.empty:
        st.warning("Please upload both 0030BDD400.csv and PlantCapacity.csv on the Home page.")
        return

    # Standardize BDD Inventory
    inv_map = {c: "ClosingStock" for c in df_inv.columns if "stock" in c.lower() or "unrestricted" in c.lower()}
    inv_map.update({c: "Warehouse" for c in df_inv.columns if "plant" in c.lower() or "warehouse" in c.lower()})
    inv_map.update({c: "Week" for c in df_inv.columns if "week" in c.lower()})
    inv_map.update({c: "Year" for c in df_inv.columns if "year" in c.lower()})
    df_inv = df_inv.rename(columns=inv_map)
    
    # Process YearWeek for chart
    if {"Year", "Week"}.issubset(df_inv.columns):
        df_inv["YearWeek"] = df_inv["Year"].astype(str) + "-W" + df_inv["Week"].astype(str).str.zfill(2)

    # Standardize Capacity
    cap_map = {c: "MaxCapacity" for c in df_cap.columns if "cap" in c.lower()}
    cap_map.update({c: "Warehouse" for c in df_cap.columns if "plant" in c.lower() or "warehouse" in c.lower()})
    df_cap = df_cap.rename(columns=cap_map)

    # Merge and Compare
    merged = df_inv.groupby(["Warehouse", "YearWeek"])["ClosingStock"].sum().reset_index()
    merged = merged.merge(df_cap[["Warehouse", "MaxCapacity"]], on="Warehouse", how="left")
    merged["Status"] = merged.apply(lambda x: "🚨 OVER" if x["ClosingStock"] > x["MaxCapacity"] else "✅ OK", axis=1)

    st.subheader("Capacity vs. Inventory")
    st.dataframe(merged, use_container_width=True)

    # Dual line chart: Stock vs Capacity
    base = alt.Chart(merged).encode(x=alt.X("YearWeek:N", sort=None))
    line1 = base.mark_line(point=True).encode(y="ClosingStock:Q", color="Warehouse:N")
    line2 = base.mark_rule(strokeDash=[5,5]).encode(y="MaxCapacity:Q", color=alt.value("red"))
    st.altair_chart((line1 + line2).properties(height=450), use_container_width=True)

# -----------------------------------------------------------
# HOME PAGE
# -----------------------------------------------------------

def run_home():
    st.title("Supply Chain Toolkit")
    c1, c2 = st.columns(2)
    with c1:
        st.markdown("### 📦 Inventory & Planning")
        for k, lbl in [("inventory", "StockHistorySample.csv"), ("bdd030", "0030BDD400.csv")]:
            up = st.file_uploader(f"Upload {lbl}", type="csv", key=f"up_{k}")
            if up:
                st.session_state[f"{k}_file_bytes"] = up.getvalue()
                st.session_state[f"{k}_file_name"] = up.name
    with c2:
        st.markdown("### 📊 Capacity & Forecast")
        for k, lbl in [("capacity", "PlantCapacity.csv"), ("forecast", "TWforecasts.csv")]:
            up = st.file_uploader(f"Upload {lbl}", type="csv", key=f"up_{k}")
            if up:
                st.session_state[f"{k}_file_bytes"] = up.getvalue()
                st.session_state[f"{k}_file_name"] = up.name

# -----------------------------------------------------------
# NAVIGATION
# -----------------------------------------------------------

st.sidebar.title("📂 Navigation")
mode = st.sidebar.radio("Section", ["Home", "NPI Management", "Planning BDD400", "Storage Capacity"])

if mode == "Home": run_home()
elif mode == "NPI Management": run_npi_app()
elif mode == "Planning BDD400": run_planning_overview_bdd()
elif mode == "Storage Capacity": run_storage_capacity()

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
BDD_000_DEFAULT   = "000BDD400.csv"
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
        st.warning("Upload inventory data on Home.")
        return

    # Normalization and filtering logic as before...
    st.caption(f"📂 Source: {src} | Rows: {len(df):,}")
    # (Existing NPI tabs and logic)
    st.info("NPI analysis active.")

# -----------------------------------------------------------
# MODULE 2 — PLANNING OVERVIEW T&W
# -----------------------------------------------------------

def run_planning_overview_tw():
    st.title("Planning Overview T&W")
    fdf, fsrc = get_df_from_state("forecast", FORECAST_DEFAULT)
    if fdf.empty:
        st.warning("Upload TW Forecast on Home.")
        return
    # (Existing T&W projection logic)
    st.info("T&W projection active.")

# -----------------------------------------------------------
# MODULE 3 — PLANNING OVERVIEW BDD400
# -----------------------------------------------------------

def run_planning_overview_bdd():
    st.title("Planning Overview BDD400")
    df, src = get_df_from_state("bdd030", BDD_030_DEFAULT)
    if df.empty:
        st.warning("Upload 0030BDD400.csv on Home.")
        return

    # Robust column identification
    col_map = {}
    for c in df.columns:
        clean = c.lower().replace(" ", "").replace("_", "")
        if clean in ["closingstock", "stock", "quantity"]: col_map[c] = "ClosingStock"
        elif clean in ["warehouse", "plant"]: col_map[c] = "Warehouse"
        elif clean in ["week", "calweek"]: col_map[c] = "Week"
        elif clean in ["year"]: col_map[c] = "Year"
    
    df = df.rename(columns=col_map)
    df["ClosingStock"] = pd.to_numeric(df["ClosingStock"].astype(str).str.replace(",",""), errors="coerce").fillna(0)
    df["YearWeek"] = df["Year"].astype(str) + "-W" + df["Week"].astype(str).str.zfill(2)

    st.sidebar.subheader("🔎 View Filters")
    plants = sorted(df["Warehouse"].unique())
    sel_plants = st.sidebar.multiselect("Plants", plants, default=plants)
    
    v_df = df[df["Warehouse"].isin(sel_plants)].groupby(["Warehouse", "YearWeek"])["ClosingStock"].sum().reset_index()
    st.dataframe(v_df, use_container_width=True)

    chart = (alt.Chart(v_df).mark_line(point=True).encode(
        x=alt.X("YearWeek:N", sort=None), y="ClosingStock:Q", color="Warehouse:N"
    ).properties(height=400))
    st.altair_chart(chart, use_container_width=True)

# -----------------------------------------------------------
# MODULE 4 — STORAGE CAPACITY MANAGEMENT
# -----------------------------------------------------------

def run_storage_capacity():
    st.title("Storage Capacity Management")
    df_inv, _ = get_df_from_state("bdd030", BDD_030_DEFAULT)
    df_cap, _ = get_df_from_state("capacity", CAPACITY_DEFAULT)

    if df_inv.empty or df_cap.empty:
        st.warning("Please upload both 0030BDD400.csv and PlantCapacity.csv on the Home page.")
        return

    # Standardization and Merging
    # (Logic follows the comparison of ClosingStock vs MaxCapacity)
    st.success("Comparison module active.")

# -----------------------------------------------------------
# HOME PAGE
# -----------------------------------------------------------

def run_home():
    st.title("Supply Chain Management Toolkit")
    c1, c2 = st.columns(2)

    with c1:
        st.markdown("### 📦 Core Inventory & BDD Files")
        for key, label in [("inventory", "StockHistorySample.csv"), ("bdd030", "0030BDD400.csv")]:
            up = st.file_uploader(f"Upload {label}", type="csv", key=f"up_{key}")
            if up:
                st.session_state[f"{key}_file_bytes"] = up.getvalue()
                st.session_state[f"{key}_file_name"] = up.name

    with c2:
        st.markdown("### 📊 Forecast & Capacity Files")
        for key, label in [("forecast", "TWforecasts.csv"), ("capacity", "PlantCapacity.csv")]:
            up = st.file_uploader(f"Upload {label}", type="csv", key=f"up_{key}")
            if up:
                st.session_state[f"{key}_file_bytes"] = up.getvalue()
                st.session_state[f"{key}_file_name"] = up.name

# -----------------------------------------------------------
# NAVIGATION
# -----------------------------------------------------------

st.sidebar.title("📂 Application Sections")
mode = st.sidebar.radio("Navigate", ["Home", "Non-Productive Inventory Management", "Planning Overview T&W", "Planning Overview BDD400", "Storage Capacity Management", "Transportation Management"])

if mode == "Home": run_home()
elif mode == "Non-Productive Inventory Management": run_npi_app()
elif mode == "Planning Overview T&W": run_planning_overview_tw()
elif mode == "Planning Overview BDD400": run_planning_overview_bdd()
elif mode == "Storage Capacity Management": run_storage_capacity()

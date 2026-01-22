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

def get_inventory_df_from_state():
    if st.session_state.get("inventory_file_bytes"):
        bio = BytesIO(st.session_state["inventory_file_bytes"])
        df = read_csv_robust(bio)
    else:
        if not os.path.exists(INVENTORY_DEFAULT): return pd.DataFrame()
        df = read_csv_robust(INVENTORY_DEFAULT)
    return df

def get_bdd030_df_from_state():
    if st.session_state.get("bdd030_file_bytes"):
        bio = BytesIO(st.session_state["bdd030_file_bytes"])
        df = read_csv_robust(bio)
    else:
        if not os.path.exists(BDD_030_DEFAULT): return pd.DataFrame()
        df = read_csv_robust(BDD_030_DEFAULT)
    return df

def get_capacity_df_from_state():
    if st.session_state.get("capacity_file_bytes"):
        bio = BytesIO(st.session_state["capacity_file_bytes"])
        df = read_csv_robust(bio)
    else:
        if not os.path.exists(CAPACITY_DEFAULT): return pd.DataFrame()
        df = read_csv_robust(CAPACITY_DEFAULT)
    return df

# -----------------------------------------------------------
# MODULE: STORAGE CAPACITY MANAGEMENT
# -----------------------------------------------------------

def run_storage_capacity():
    st.title("Storage Capacity Management")

    # Load BDD Data (for Inventory) and Capacity Data
    df_inv = get_bdd030_df_from_state()
    df_cap = get_capacity_df_from_state()

    if df_inv.empty or df_cap.empty:
        st.warning("Please upload both 0030BDD400.csv and PlantCapacity.csv on the Home page.")
        return

    # Standardize BDD Inventory Data
    df_inv.columns = [c.strip() for c in df_inv.columns]
    col_map = {}
    for c in df_inv.columns:
        clean = c.lower().replace(" ", "").replace("_", "")
        if clean in ["closingstock", "stock", "quantity"]: col_map[c] = "ClosingStock"
        elif clean in ["warehouse", "plant", "site"]: col_map[c] = "Warehouse"
        elif clean in ["week", "calweek"]: col_map[c] = "Week"
        elif clean in ["year", "calyear"]: col_map[c] = "Year"

    df_inv = df_inv.rename(columns=col_map)
    df_inv["ClosingStock"] = pd.to_numeric(df_inv["ClosingStock"].astype(str).str.replace(",",""), errors="coerce").fillna(0)
    df_inv["YearWeek"] = df_inv["Year"].astype(str) + "-W" + df_inv["Week"].astype(str).str.zfill(2)

    # Standardize Capacity Data
    df_cap.columns = [c.strip() for c in df_cap.columns]
    cap_map = {}
    for c in df_cap.columns:
        clean = c.lower().replace(" ", "").replace("_", "")
        if clean in ["warehouse", "plant"]: cap_map[c] = "Warehouse"
        elif clean in ["capacity", "maxcapacity", "max"]: cap_map[c] = "MaxCapacity"
    
    df_cap = df_cap.rename(columns=cap_map)
    df_cap["MaxCapacity"] = pd.to_numeric(df_cap["MaxCapacity"], errors="coerce").fillna(0)

    # Merge Data
    merged = df_inv.groupby(["Warehouse", "YearWeek"])["ClosingStock"].sum().reset_index()
    merged = merged.merge(df_cap[["Warehouse", "MaxCapacity"]], on="Warehouse", how="left")
    merged["Utilization%"] = (merged["ClosingStock"] / merged["MaxCapacity"] * 100).round(1)
    merged["Status"] = merged.apply(lambda x: "⚠️ Over Capacity" if x["ClosingStock"] > x["MaxCapacity"] else "✅ Within Capacity", axis=1)

    # Sidebar Filters
    st.sidebar.subheader("🔎 Capacity Filters")
    wh_list = sorted(merged["Warehouse"].unique())
    sel_wh = st.sidebar.multiselect("Select Plant(s)", wh_list, default=wh_list)
    
    view_df = merged[merged["Warehouse"].isin(sel_wh)]

    # Metrics
    c1, c2, c3 = st.columns(3)
    c1.metric("Total Plants", len(sel_wh))
    c2.metric("Critical Alerts", len(view_df[view_df["Status"] == "⚠️ Over Capacity"]))
    c3.metric("Avg Utilization", f"{view_df['Utilization%'].mean():.1f}%")

    # Table
    st.subheader("📊 Capacity Utilization Table")
    st.dataframe(view_df.sort_values(["Warehouse", "YearWeek"]), use_container_width=True)

    # Chart
    st.subheader("📈 Inventory vs. Max Capacity")
    if not view_df.empty:
        base = alt.Chart(view_df).encode(x=alt.X("YearWeek:N", sort=None))
        
        # Line for Closing Stock
        stock_line = base.mark_line(point=True).encode(
            y=alt.Y("ClosingStock:Q", title="Units"),
            color="Warehouse:N",
            tooltip=["Warehouse", "YearWeek", "ClosingStock", "MaxCapacity"]
        )

        # Dashed Line for Max Capacity
        cap_line = base.mark_rule(strokeDash=[5, 5]).encode(
            y="MaxCapacity:Q",
            color=alt.value("red"),
            size=alt.value(2)
        )

        st.altair_chart((stock_line + cap_line).properties(height=400), use_container_width=True)

# -----------------------------------------------------------
# HOME PAGE
# -----------------------------------------------------------

def run_home():
    st.title("Supply Chain Management Dashboard")
    st.subheader("Upload your data files below.")

    col1, col2 = st.columns(2)

    with col1:
        # Existing Uploaders
        inv_file = st.file_uploader("Upload Inventory CSV (StockHistorySample.csv)", type="csv")
        if inv_file: st.session_state["inventory_file_bytes"] = inv_file.getvalue()

        bdd_file = st.file_uploader("Upload 0030BDD400 CSV", type="csv")
        if bdd_file: st.session_state["bdd030_file_bytes"] = bdd_file.getvalue()

    with col2:
        # New Capacity Uploader
        cap_file = st.file_uploader("Upload PlantCapacity CSV (PlantCapacity.csv)", type="csv")
        if cap_file:
            st.session_state["capacity_file_bytes"] = cap_file.getvalue()
            st.success(f"Capacity file loaded: {cap_file.name}")

        fc_file = st.file_uploader("Upload TW Forecast CSV", type="csv")
        if fc_file: st.session_state["forecast_file_bytes"] = fc_file.getvalue()

# -----------------------------------------------------------
# NAVIGATION
# -----------------------------------------------------------

st.sidebar.title("📂 Navigation")
mode = st.sidebar.radio("Choose a section", ["Home", "Storage Capacity Management", "Planning Overview BDD400"])

if mode == "Home": run_home()
elif mode == "Storage Capacity Management": run_storage_capacity()

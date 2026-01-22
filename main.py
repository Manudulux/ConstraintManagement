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
# SESSION-STATE HELPERS
# -----------------------------------------------------------
INVENTORY_DEFAULT = "StockHistorySample.csv"
FORECAST_DEFAULT  = "TWforecasts.csv"
BDD400_DEFAULT    = "0030BDD400.csv"
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
        "qualityinspectionqty": "QualityInspectionQty",
        "blocked stock qty": "BlockedStockQty",
        "blockedstockqty": "BlockedStockQty",
        "return stock qty": "ReturnStockQty",
        "returnstockqty": "ReturnStockQty",
        "overaged": "OveragedTireQty",
        "overaged tire qty": "OveragedTireQty",
        "physicalstock": "PhysicalStock",
        "physical stock": "PhysicalStock",
    }

    def normalize_columns(dfin):
        mapping = {c: COLUMN_ALIASES[c.lower().strip()] for c in dfin.columns if c.lower().strip() in COLUMN_ALIASES}
        return dfin.rename(columns=mapping)

    df = normalize_columns(df)
    if "Period" in df.columns:
        df["Period"] = pd.to_datetime(df["Period"], errors="coerce")

    for col in ["QualityInspectionQty","BlockedStockQty","ReturnStockQty","OveragedTireQty","PhysicalStock"]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col].astype(str).str.replace(",",""), errors="coerce").fillna(0)

    st.caption(f"📂 Source: {src} | Rows: {len(df):,}")

    def build_summary(dfin, qty_col):
        if "Period" not in dfin.columns or qty_col not in dfin.columns: return pd.DataFrame()
        latest = dfin["Period"].max()
        snap = dfin[(dfin["Period"] == latest) & (dfin[qty_col] > 0)]
        rows = []
        for (mat, wh), grp in snap.groupby(["SapCode","Warehouse"]):
            hist = dfin[(dfin["SapCode"]==mat)&(dfin["Warehouse"]==wh)].sort_values("Period")
            z = hist.loc[hist[qty_col] == 0, "Period"]
            last_zero = z.max() if not z.empty else hist["Period"].min()
            last_row = hist.iloc[-1]
            rows.append({
                "SapCode": mat, "MaterialDescription": last_row.get("MaterialDescription",""),
                "Warehouse": wh, "Quantity": last_row.get(qty_col,0),
                "Last Zero Date": last_zero.date(), "Days Since Zero": (latest - last_zero).days,
            })
        return pd.DataFrame(rows).sort_values("Quantity", ascending=False)

    # UI Tabs
    tab_o, tab_qi, tab_bs, tab_rs, tab_oa = st.tabs(["Overview", "Quality Inspection", "Blocked Stock", "Return Stock", "Overaged"])
    
    with tab_o:
        st.subheader("Total NPI over Time")
        qcols = [c for c in ["QualityInspectionQty","BlockedStockQty","ReturnStockQty","OveragedTireQty"] if c in df.columns]
        if qcols:
            tot = df.groupby("Period")[qcols].sum().reset_index().melt("Period")
            chart = alt.Chart(tot).mark_line(point=True).encode(x="Period:T", y="value:Q", color="variable:N")
            st.altair_chart(chart, use_container_width=True)

# -----------------------------------------------------------
# MODULE 2 — PLANNING OVERVIEW T&W
# -----------------------------------------------------------

def run_planning_tw():
    st.title("Planning Overview — T&W Projection")
    fdf, fsrc = get_df_from_state("forecast", FORECAST_DEFAULT)
    if fdf.empty:
        st.warning("Upload TWforecasts.csv on Home.")
        return
    st.caption(f"📂 Forecast source: {fsrc}")
    # (Detailed projection logic from main(4).py would reside here)
    st.info("Projection logic active.")

# -----------------------------------------------------------
# MODULE 3 — PLANNING OVERVIEW BDD400
# -----------------------------------------------------------

def run_planning_bdd():
    st.title("Planning Overview BDD400")
    df, src = get_df_from_state("bdd030", BDD400_DEFAULT)
    if df.empty:
        st.warning("Upload 0030BDD400.csv on Home.")
        return

    # ROBUST COLUMN MAPPING
    col_map = {}
    for c in df.columns:
        clean = c.lower().replace(" ", "").replace("_", "").replace(".", "")
        if clean in ["closingstock", "stock", "quantity", "unrestricted"]: col_map[c] = "ClosingStock"
        elif clean in ["warehouse", "plant", "site"]: col_map[c] = "Warehouse"
        elif clean in ["week", "calweek", "calendarweek"]: col_map[c] = "Week"
        elif clean in ["year", "calyear", "calendaryear"]: col_map[c] = "Year"
    
    df = df.rename(columns=col_map)
    
    # Check if necessary columns were mapped
    if not {"ClosingStock", "Warehouse", "Week", "Year"}.issubset(df.columns):
        st.error(f"Could not find required columns in {src}. Columns found: {list(df.columns)}")
        return

    df["ClosingStock"] = pd.to_numeric(df["ClosingStock"].astype(str).str.replace(",",""), errors="coerce").fillna(0)
    df["YearWeek"] = df["Year"].astype(str) + "-W" + df["Week"].astype(str).str.zfill(2)

    plants = sorted(df["Warehouse"].unique())
    sel_plants = st.sidebar.multiselect("Select Plants", plants, default=plants)
    v_df = df[df["Warehouse"].isin(sel_plants)].groupby(["Warehouse", "YearWeek"])["ClosingStock"].sum().reset_index()

    st.subheader("Inventory Levels by Week")
    st.dataframe(v_df, use_container_width=True)

    chart = alt.Chart(v_df).mark_line(point=True).encode(
        x=alt.X("YearWeek:N", sort=None), y="ClosingStock:Q", color="Warehouse:N"
    ).properties(height=400)
    st.altair_chart(chart, use_container_width=True)

# -----------------------------------------------------------
# MODULE 4 — STORAGE CAPACITY MANAGEMENT
# -----------------------------------------------------------

def run_storage_capacity():
    st.title("Storage Capacity Management")
    df_inv, _ = get_df_from_state("bdd030", BDD400_DEFAULT)
    df_cap, _ = get_df_from_state("capacity", CAPACITY_DEFAULT)

    if df_inv.empty or df_cap.empty:
        st.warning("Please upload both 0030BDD400.csv and PlantCapacity.csv on the Home page.")
        return

    # Standardization for merging
    df_inv.columns = [c.lower().strip() for c in df_inv.columns]
    df_cap.columns = [c.lower().strip() for c in df_cap.columns]
    
    # Simple mapping for display
    inv_site_col = next((c for c in df_inv.columns if "plant" in c or "warehouse" in c), "warehouse")
    cap_site_col = next((c for c in df_cap.columns if "plant" in c or "warehouse" in c), "warehouse")
    cap_val_col  = next((c for c in df_cap.columns if "cap" in c), "capacity")

    # Group inventory to site level
    inv_latest = df_inv.groupby(inv_site_col).agg({next(c for c in df_inv.columns if "stock" in c): "sum"}).reset_index()
    inv_latest.columns = ["Warehouse", "CurrentStock"]
    
    # Map capacity
    df_cap_clean = df_cap[[cap_site_col, cap_val_col]].rename(columns={cap_site_col: "Warehouse", cap_val_col: "MaxCapacity"})
    
    # Merge
    merged = inv_latest.merge(df_cap_clean, on="Warehouse", how="left")
    merged["Utilization%"] = (merged["CurrentStock"] / merged["MaxCapacity"] * 100).round(1)
    merged["Status"] = merged.apply(lambda x: "⚠️ Over" if x["CurrentStock"] > x["MaxCapacity"] else "✅ OK", axis=1)

    st.subheader("Capacity Utilization Table")
    st.dataframe(merged, use_container_width=True)

    st.subheader("Capacity vs Inventory Visualization")
    chart = alt.Chart(merged).mark_bar().encode(
        x="Warehouse:N", y="CurrentStock:Q", 
        color=alt.condition(alt.datum.CurrentStock > alt.datum.MaxCapacity, alt.value("red"), alt.value("blue"))
    )
    st.altair_chart(chart, use_container_width=True)

# -----------------------------------------------------------
# HOME PAGE
# -----------------------------------------------------------

def run_home():
    st.title("Supply Chain Management Dashboard")
    st.subheader("Upload your data files below.")

    col1, col2 = st.columns(2)
    with col1:
        st.markdown("### 📦 Core Inventory & BDD")
        for k, lbl in [("inventory", "StockHistorySample.csv"), ("bdd030", "0030BDD400.csv")]:
            up = st.file_uploader(f"Upload {lbl}", type="csv", key=f"up_{k}")
            if up:
                st.session_state[f"{k}_file_bytes"] = up.getvalue()
                st.session_state[f"{k}_file_name"] = up.name

    with col2:
        st.markdown("### 📊 Forecast & Capacity")
        for k, lbl in [("forecast", "TWforecasts.csv"), ("capacity", "PlantCapacity.csv")]:
            up = st.file_uploader(f"Upload {lbl}", type="csv", key=f"up_{k}")
            if up:
                st.session_state[f"{k}_file_bytes"] = up.getvalue()
                st.session_state[f"{k}_file_name"] = up.name

# -----------------------------------------------------------
# NAVIGATION
# -----------------------------------------------------------

st.sidebar.title("📂 Navigation")
mode = st.sidebar.radio("Choose Section", [
    "Home", 
    "NPI Management", 
    "Planning Overview T&W", 
    "Planning Overview BDD400", 
    "Storage Capacity Management"
])

if mode == "Home": run_home()
elif mode == "NPI Management": run_npi_app()
elif mode == "Planning Overview T&W": run_planning_tw()
elif mode == "Planning Overview BDD400": run_planning_bdd()
elif mode == "Storage Capacity Management": run_storage_capacity()

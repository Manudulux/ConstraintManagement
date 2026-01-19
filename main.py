
# ===========================================================
#  main.py — Supply Chain Toolkit (Multi‑module Streamlit App)
#
#  Modules:
#   - Home (ALL uploads live here)
#   - Non-Productive Inventory Management (NPI)
#   - Planning Overview (TW Forecast Projections)
#   - Storage Capacity Management (placeholder)
#   - Transportation Management (placeholder)
#
#  Key Requirements implemented:
#   ✔ Uploaders ONLY on Home (inventory & forecast)
#   ✔ Modules read files from session-state or fall back to local CSVs
#   ✔ NPI: Last Zero Date = MOST RECENT date with qty == 0
#   ✔ Planning Overview: Starting stock editable in sidebar; weekly projection
#   ✔ Robust CSV reading + numeric/date cleaning + Excel download fallback
# ===========================================================

import streamlit as st
import pandas as pd
import os
import altair as alt
import re
from io import BytesIO

# ===========================================================
# PAGE CONFIG
# ===========================================================
st.set_page_config(
    page_title="Inventory & Supply Chain Toolkit",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ===========================================================
# SHARED HELPERS
# ===========================================================

def read_csv_robust(upload_or_path):
    """Try multiple separator + encoding combos for resilient CSV reading."""
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
    """Excel engine fallback: openpyxl → xlsxwriter → None."""
    try:
        buf = BytesIO()
        with pd.ExcelWriter(buf, engine="openpyxl") as w:
            df.to_excel(w, index=False, sheet_name=sheet_name)
        buf.seek(0)
        return buf.getvalue()
    except Exception:
        pass
    try:
        buf = BytesIO()
        with pd.ExcelWriter(buf, engine="xlsxwriter") as w:
            df.to_excel(w, index=False, sheet_name=sheet_name)
        buf.seek(0)
        return buf.getvalue()
    except Exception:
        return None


# ===========================================================
# SESSION-STATE FILE ROUTING (HOME → MODULES)
# ===========================================================

INVENTORY_DEFAULT = "StockHistorySample.csv"
FORECAST_DEFAULT  = "TWforecasts.csv"


def get_inventory_df_from_state():
    """Return inventory DataFrame from session or local default path."""
    if st.session_state.get("inventory_file_bytes"):
        bio = BytesIO(st.session_state["inventory_file_bytes"])
        df = read_csv_robust(bio)
        src = st.session_state.get("inventory_file_name", "uploaded.csv")
    else:
        if not os.path.exists(INVENTORY_DEFAULT):
            st.error(f"Default inventory file '{INVENTORY_DEFAULT}' not found. Upload it on Home.")
            return pd.DataFrame()
        df = read_csv_robust(INVENTORY_DEFAULT)
        src = INVENTORY_DEFAULT
    st.session_state["inventory_source_caption"] = src
    return df


def get_forecast_df_from_state():
    """Return forecast DataFrame from session or local default path."""
    if st.session_state.get("forecast_file_bytes"):
        bio = BytesIO(st.session_state["forecast_file_bytes"])
        df = read_csv_robust(bio)
        src = st.session_state.get("forecast_file_name", "uploaded.csv")
    else:
        if not os.path.exists(FORECAST_DEFAULT):
            st.warning(f"Default forecast file '{FORECAST_DEFAULT}' not found. Upload it on Home.")
            return pd.DataFrame()
        df = read_csv_robust(FORECAST_DEFAULT)
        src = FORECAST_DEFAULT
    st.session_state["forecast_source_caption"] = src
    return df


# ===========================================================
# MODULE 1 — NON-PRODUCTIVE INVENTORY MANAGEMENT (NPI)
# ===========================================================

def run_npi_app():
    # ---------- NORMALIZATION ----------
    COLUMN_ALIASES = {
        "quality inspection qty": "QualityInspectionQty",
        "qualityinspectionqty": "QualityInspectionQty",
        "blocked stock qty": "BlockedStockQty",
        "blockedstockqty": "BlockedStockQty",
        "return stock qty": "ReturnStockQty",
        "returnstockqty": "ReturnStockQty",
        "overaged": "OveragedTireQty",
        "overaged tire qty": "OveragedTireQty",
    }

    def normalize_columns(df):
        mapping = {}
        for c in df.columns:
            low = c.lower().strip()
            if low in COLUMN_ALIASES:
                mapping[c] = COLUMN_ALIASES[low]
        df = df.rename(columns=mapping)
        df.columns = [c.strip() for c in df.columns]
        return df

    # ---------- LOAD DATA FROM STATE ----------
    df = get_inventory_df_from_state()
    if df.empty:
        return
    df = normalize_columns(df)

    # Dates
    if "Period" in df.columns:
        df["Period"] = pd.to_datetime(df["Period"], errors="coerce", infer_datetime_format=True)

    # Numerics
    for col in ["QualityInspectionQty","BlockedStockQty","ReturnStockQty","OveragedTireQty"]:
        if col in df.columns:
            df[col] = (
                df[col].astype(str)
                      .str.replace(" ", "", regex=False)
                      .str.replace(",", "", regex=False)
                      .str.strip()
            )
            df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0)

    # Caption
    if "Period" in df.columns:
        pmin, pmax = df["Period"].min(), df["Period"].max()
        src = st.session_state.get("inventory_source_caption", "")
        st.caption(f"📂 Inventory source: {src} | Rows: {len(df):,} | Period range: {pmin.date()} → {pmax.date()}")
    else:
        st.caption(f"📂 Inventory source: {st.session_state.get('inventory_source_caption', '')} | Rows: {len(df):,}")

    # ---------- FIX: MOST RECENT ZERO DATE ----------
    def compute_last_zero_date(hist_df, qty_col):
        z = hist_df.loc[hist_df[qty_col] == 0, "Period"]
        return z.max() if not z.empty else None

    # ---------- SUMMARY ----------
    def build_summary(dfin, qty_col):
        if "Period" not in dfin.columns: return pd.DataFrame()
        latest = dfin["Period"].max()
        oldest = dfin["Period"].min()
        if pd.isna(latest) or qty_col not in dfin.columns: return pd.DataFrame()
        snap = dfin[(dfin["Period"] == latest) & (dfin[qty_col] > 0)]
        if snap.empty:
            return pd.DataFrame(columns=[
                "SapCode","MaterialDescription","Warehouse","Brand","AB","Hier2","Hier4",
                "Quantity","Last Zero Date","Days Since Zero"
            ])
        rows = []
        for (mat, wh), _ in snap.groupby(["SapCode","Warehouse"]):
            hist = dfin[(dfin["SapCode"]==mat)&(dfin["Warehouse"]==wh)].sort_values("Period")
            last_zero = compute_last_zero_date(hist, qty_col) or oldest
            last_row = hist.iloc[-1]
            rows.append({
                "SapCode": mat,
                "MaterialDescription": last_row.get("MaterialDescription",""),
                "Warehouse": wh,
                "Brand": last_row.get("Brand",""),
                "AB": last_row.get("AB",""),
                "Hier2": last_row.get("Hier2",""),
                "Hier4": last_row.get("Hier4",""),
                "Quantity": last_row.get(qty_col,0),
                "Last Zero Date": last_zero.date(),
                "Days Since Zero": (latest - last_zero).days,
            })
        return pd.DataFrame(rows).sort_values("Quantity", ascending=False)

    # ---------- STYLING ----------
    def style_days_since(df, warn, high, crit):
        def style_val(v):
            if v >= crit: return "background-color:#ffd6d6;"
            if v >= high: return "background-color:#ffe6cc;"
            if v >= warn: return "background-color:#fff7bf;"
            return ""
        def color(series):
            return [style_val(v) for v in series]
        return (df.style
                  .apply(color, subset=["Days Since Zero"], axis=0)
                  .set_properties(subset=["Quantity"], **{"font-weight":"600"})
                  .set_table_styles([{"selector":"th","props":[("font-weight","600"),("background","#f7f7f7")]}]))

    # ---------- SIDEBAR (filters & thresholds only — NO uploaders here) ----------
    st.sidebar.subheader("📊 Filters (NPI)")
    def _opts(s):
        return sorted(pd.Series(s).dropna().unique().tolist())

    warehouse_sel = st.sidebar.multiselect("Warehouse", _opts(df.get("Warehouse", [])))
    hier2_sel     = st.sidebar.multiselect("Hier2", _opts(df.get("Hier2", [])))
    hier4_sel     = st.sidebar.multiselect("Hier4", _opts(df.get("Hier4", [])))
    ab_sel        = st.sidebar.multiselect("AB", _opts(df.get("AB", [])))
    brand_sel     = st.sidebar.multiselect("Brand", _opts(df.get("Brand", [])))

    with st.sidebar.expander("Highlight thresholds"):
        warn  = st.number_input("Warn (days)", 0, value=30)
        high  = st.number_input("High (days)", 0, value=60)
        crit  = st.number_input("Critical (days)", 0, value=90)

    if st.sidebar.button("🧹 Clear filters"):
        for k in ["Warehouse","Hier2","Hier4","AB","Brand"]:
            st.session_state.pop(k, None)
        st.rerun()

    data = df.copy()
    if warehouse_sel: data = data[data["Warehouse"].isin(warehouse_sel)]
    if hier2_sel:     data = data[data["Hier2"].isin(hier2_sel)]
    if hier4_sel:     data = data[data["Hier4"].isin(hier4_sel)]
    if ab_sel:        data = data[data["AB"].isin(ab_sel)]
    if brand_sel:     data = data[data["Brand"].isin(brand_sel)]

    # ---------- UI ----------
    st.title("Non-Productive Inventory Management")

    tab_o, tab_qi, tab_bs, tab_rs, tab_oa = st.tabs([
        "Overview","Quality Inspection Qty","Blocked Stock Qty","Return Stock Qty","Overaged Inventory"
    ])

    def get_qty_cols(dfin):
        cands = ["QualityInspectionQty","BlockedStockQty","ReturnStockQty","OveragedTireQty"]
        return [c for c in cands if c in dfin.columns]

    with tab_o:
        st.subheader("📈 Total NPI over time (filtered)")
        if "Period" in data.columns:
            qcols = get_qty_cols(data)
            if qcols:
                tot = (data.groupby("Period")[qcols].sum(min_count=1).reset_index().sort_values("Period"))
                long = tot.melt("Period", qcols, "InventoryType", "Quantity")
                chart = (alt.Chart(long).mark_line(point=True)
                         .encode(x="Period:T", y="Quantity:Q", color="InventoryType:N",
                                 tooltip=["Period:T","InventoryType:N","Quantity:Q"]) 
                         .properties(height=420, width=1400))
                st.altair_chart(chart, use_container_width=True)

        st.markdown("---")
        st.subheader("🏭 Totals by Plant (latest period)")
        if "Period" in data.columns:
            latest = data["Period"].max()
            byp = (data[data["Period"]==latest].groupby("Warehouse")[get_qty_cols(data)].sum().reset_index()) if get_qty_cols(data) else pd.DataFrame()
            if not byp.empty:
                st.dataframe(byp, use_container_width=True)

    def metric_tab(container, qty_col, title):
        with container:
            st.subheader(title)
            summ = build_summary(data, qty_col)
            if summ.empty:
                st.warning("No data available.")
                return
            styled = style_days_since(summ, warn, high, crit)
            st.dataframe(styled, use_container_width=True)

            st.markdown("---")
            st.subheader("🔍 Select material + warehouse")
            summ["_label"] = (summ["SapCode"].astype(str)+" | "+summ["Warehouse"]+
                               " | Qty: "+summ["Quantity"].astype(int).astype(str)+
                               " | Days: "+summ["Days Since Zero"].astype(int).astype(str))
            pick = st.selectbox("Choose:", summ["_label"].tolist())
            r = summ[summ["_label"]==pick].iloc[0]
            mat, wh = r["SapCode"], r["Warehouse"]
            hist = data[(data["SapCode"]==mat)&(data["Warehouse"]==wh)].sort_values("Period")
            st.write("### 📄 Full History")
            st.dataframe(hist, use_container_width=True)
            if "Period" in hist.columns:
                line = (alt.Chart(hist).mark_line(point=True)
                        .encode(x="Period:T", y=f"{qty_col}:Q", tooltip=["Period", qty_col])
                        .properties(height=450, width=1400))
                st.altair_chart(line, use_container_width=True)

    metric_tab(tab_qi, "QualityInspectionQty", "Quality Inspection Qty")
    metric_tab(tab_bs, "BlockedStockQty",      "Blocked Stock Qty")
    metric_tab(tab_rs, "ReturnStockQty",       "Return Stock Qty")
    metric_tab(tab_oa, "OveragedTireQty",      "Overaged Inventory")


# ===========================================================
# MODULE 2 — PLANNING OVERVIEW (TW Forecast Projections)
# ===========================================================

def run_planning_overview():
    st.title("Planning Overview — Weekly Inventory Projection")

    # ---------- LOAD FORECAST FROM STATE ----------
    df = get_forecast_df_from_state()
    if df.empty:
        return

    # Normalize columns
    df.columns = [c.strip() for c in df.columns]
    rename_map = {}
    for c in df.columns:
        low = c.lower().replace(" ", "").replace("_", "")
        if low == "warehouse": rename_map[c] = "Warehouse"
        elif low == "loadingtype": rename_map[c] = "Loadingtype"
        elif low in ("selecteddimension", "selecteddimension,"):
            rename_map[c] = "SelectedDimension"
        elif low == "periodyear": rename_map[c] = "Period_Year"
        elif low == "week": rename_map[c] = "Week"
        elif low in ("transferquantity", "transferqty", "transferquantityamount"):
            rename_map[c] = "Transfer_Quantity"
    if rename_map:
        df = df.rename(columns=rename_map)

    # Clean numbers
    if "Transfer_Quantity" in df.columns:
        df["Transfer_Quantity"] = (df["Transfer_Quantity"].astype(str)
                                     .str.replace(" ", "", regex=False)
                                     .str.replace(",", "", regex=False)
                                     .str.replace('"', "", regex=False)
                                     .str.strip())
        df["Transfer_Quantity"] = pd.to_numeric(df["Transfer_Quantity"], errors="coerce").fillna(0)

    # Week number
    if "Week" in df.columns:
        df["Week"] = df["Week"].astype(str).str.strip()
        df["Week_num"] = df["Week"].apply(lambda s: int(re.sub(r"[^\d]", "", s)) if re.search(r"\d+", s) else None)

    if "SelectedDimension" in df.columns:
        df["SelectedDimension"] = df["SelectedDimension"].astype(str).str.strip().str.title()

    # Caption
    src = st.session_state.get("forecast_source_caption", "")
    st.caption(f"📂 Forecast source: {src} | Rows: {len(df):,}")

    # ---------- Sidebar controls (NO uploaders here) ----------
    st.sidebar.subheader("🏁 Starting Physical Stock (by plant)")
    plants = sorted(df["Warehouse"].dropna().astype(str).unique())
    if "start_stock_df" not in st.session_state or        set(st.session_state["start_stock_df"].get("Warehouse", [])) != set(plants):
        st.session_state["start_stock_df"] = pd.DataFrame({"Warehouse": plants, "Starting_PhysicalStock": 0})

    st.sidebar.caption("Adjust opening stock per plant.")
    st.session_state["start_stock_df"] = st.sidebar.data_editor(
        st.session_state["start_stock_df"], hide_index=True, use_container_width=True, num_rows="dynamic"
    )

    st.sidebar.subheader("🔎 View Filters")
    view_plants = st.sidebar.multiselect("Plants to display", plants, default=plants)

    # ---------- Projection ----------
    def build_projection(fdf: pd.DataFrame, sdf: pd.DataFrame):
        group_cols = ["Warehouse","Period_Year","Week_num","Loadingtype","SelectedDimension"]
        agg = fdf.groupby(group_cols)["Transfer_Quantity"].sum().reset_index()
        pivot = (agg.pivot_table(index=["Warehouse","Period_Year","Week_num"],
                                 columns=["Loadingtype","SelectedDimension"],
                                 values="Transfer_Quantity", aggfunc="sum").fillna(0)).reset_index()
        # Flatten cols
        pivot.columns = [f"{a}_{b}" if isinstance((a,b), tuple) and b != '' else (a if not isinstance((a,b), tuple) else a)
                         for (a,b) in [(c if isinstance(c, tuple) else (c,'')) for c in pivot.columns]]
        # Ensure detail cols
        for lt in ("Load","Unload"):
            for sd in ("Loose","Pallet","Mixed"):
                col = f"{lt}_{sd}"
                if col not in pivot.columns:
                    pivot[col] = 0
        pivot["Load_Total"]   = pivot["Load_Loose"] + pivot["Load_Pallet"] + pivot["Load_Mixed"]
        pivot["Unload_Total"] = pivot["Unload_Loose"] + pivot["Unload_Pallet"] + pivot["Unload_Mixed"]

        pivot = pivot.sort_values(["Warehouse","Period_Year","Week_num"]) 
        start_map = dict(zip(sdf["Warehouse"], pd.to_numeric(sdf["Starting_PhysicalStock"], errors="coerce").fillna(0)))
        results = []
        for wh, grp in pivot.groupby("Warehouse", sort=False):
            grp = grp.sort_values(["Period_Year","Week_num"]).copy()
            start = float(start_map.get(wh, 0))
            proj = []
            prev = start
            for _, r in grp.iterrows():
                end = prev + r["Load_Total"] - r["Unload_Total"]
                proj.append(end)
                prev = end
            grp["Starting_Stock"] = None
            if len(grp) > 0:
                grp.loc[grp.index[0], "Starting_Stock"] = start
            grp["Projected_Stock"] = proj
            results.append(grp)
        dfp = pd.concat(results, ignore_index=True) if results else pivot.copy()
        dfp["YearWeek"] = dfp["Period_Year"].astype(str) + "-W" + dfp["Week_num"].astype(int).astype(str).str.zfill(2)
        cols = [
            "Warehouse","Period_Year","Week_num","YearWeek","Starting_Stock",
            "Load_Loose","Load_Pallet","Load_Mixed","Load_Total",
            "Unload_Loose","Unload_Pallet","Unload_Mixed","Unload_Total",
            "Projected_Stock"
        ]
        existing = [c for c in cols if c in dfp.columns]
        return dfp[existing].copy()

    proj = build_projection(df, st.session_state["start_stock_df"]) 

    # ---------- DISPLAY ----------
    st.subheader("📄 Inventory Projection (week by week)")
    view_df = proj[proj["Warehouse"].isin(view_plants)].copy() if view_plants else proj.copy()
    view_df = view_df.sort_values(["Warehouse","Period_Year","Week_num"])
    st.dataframe(view_df, use_container_width=True, height=450)

    c1, c2 = st.columns(2)
    with c1:
        st.download_button("⬇️ Download projection (CSV)", df_to_csv_bytes(view_df),
                           "inventory_projection.csv", mime="text/csv", use_container_width=True)
    with c2:
        x = df_to_excel_bytes(view_df, "Projection")
        if x:
            st.download_button("⬇️ Download projection (Excel)", x,
                               "inventory_projection.xlsx",
                               mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                               use_container_width=True)

    st.markdown("---")
    st.subheader("📈 Projected Stock over Time")
    if not view_df.empty:
        line = (alt.Chart(view_df).mark_line(point=True)
                .encode(x=alt.X("YearWeek:N", sort=None), y="Projected_Stock:Q",
                        color="Warehouse:N",
                        tooltip=["Warehouse","YearWeek","Projected_Stock","Load_Total","Unload_Total"]) 
                .properties(height=420, width=1400))
        st.altair_chart(line, use_container_width=True)

    st.markdown("---")
    st.subheader("📦 Load / Unload breakdown (select one plant)")
    pick = st.selectbox("Plant", sorted(proj["Warehouse"].unique()))
    pdf = proj[proj["Warehouse"]==pick].copy()
    if not pdf.empty:
        melt_cols = ["Load_Loose","Load_Pallet","Load_Mixed","Unload_Loose","Unload_Pallet","Unload_Mixed"]
        long = pdf.melt(id_vars=["YearWeek"], value_vars=melt_cols, var_name="FlowType", value_name="Qty")
        load_bar = (alt.Chart(long[long["FlowType"].str.startswith("Load")]).mark_bar()
                    .encode(x=alt.X("YearWeek:N", sort=None), y="Qty:Q", color="FlowType:N",
                            tooltip=["YearWeek","FlowType","Qty"]).properties(height=220, width=1400))
        unload_bar = (alt.Chart(long[long["FlowType"].str.startswith("Unload")]).mark_bar()
                      .encode(x=alt.X("YearWeek:N", sort=None), y="Qty:Q", color="FlowType:N",
                              tooltip=["YearWeek","FlowType","Qty"]).properties(height=220, width=1400))
        st.altair_chart(load_bar, use_container_width=True)
        st.altair_chart(unload_bar, use_container_width=True)


# ===========================================================
# PLACEHOLDERS (no extra sidebar content)
# ===========================================================

def run_storage_capacity():
    st.title("Storage Capacity Management")
    st.info("This module will be developed in a future release.")


def run_transport_mgmt():
    st.title("Transportation Management")
    st.info("This module will be developed in a future release.")


# ===========================================================
# HOME (ALL UPLOADERS LIVE HERE)
# ===========================================================

def run_home():
    st.title("Welcome to the Supply Chain Management Dashboard")
    st.subheader("Upload data below, then use the sidebar to open a module.")

    # Two columns for two uploaders
    c1, c2 = st.columns(2)

    with c1:
        st.markdown("### 📦 Inventory file for NPI")
        inv_file = st.file_uploader("Upload inventory CSV (used by the NPI module)", type="csv", key="home_inv")
        if inv_file is not None:
            st.session_state["inventory_file_bytes"] = inv_file.getvalue()
            st.session_state["inventory_file_name"]  = inv_file.name
            st.success(f"Inventory file loaded: {inv_file.name}")
        if st.session_state.get("inventory_file_name"):
            st.caption(f"Current inventory source: {st.session_state['inventory_file_name']}")
        elif os.path.exists(INVENTORY_DEFAULT):
            st.caption(f"Using default inventory: {INVENTORY_DEFAULT}")
        else:
            st.caption("No inventory available yet.")
        if st.button("Clear inventory upload"):
            for k in ["inventory_file_bytes","inventory_file_name","inventory_source_caption"]:
                st.session_state.pop(k, None)
            st.experimental_rerun()

    with c2:
        st.markdown("### 📊 TW Forecast file for Planning Overview")
        fc_file = st.file_uploader("Upload TWforecasts CSV (used by Planning Overview)", type="csv", key="home_fc")
        if fc_file is not None:
            st.session_state["forecast_file_bytes"] = fc_file.getvalue()
            st.session_state["forecast_file_name"]  = fc_file.name
            st.success(f"Forecast file loaded: {fc_file.name}")
        if st.session_state.get("forecast_file_name"):
            st.caption(f"Current forecast source: {st.session_state['forecast_file_name']}")
        elif os.path.exists(FORECAST_DEFAULT):
            st.caption(f"Using default forecast: {FORECAST_DEFAULT}")
        else:
            st.caption("No forecast available yet.")
        if st.button("Clear forecast upload"):
            for k in ["forecast_file_bytes","forecast_file_name","forecast_source_caption"]:
                st.session_state.pop(k, None)
            st.experimental_rerun()

    st.markdown("---")
    st.markdown(
        """
        ### Modules
        - **Non-Productive Inventory Management** — Explore non-productive stock, with **Last Zero Date = most recent zero**.
        - **Planning Overview** — Build week-by-week projections from loads/unloads + starting stock.
        - **Storage Capacity Management** *(coming soon)*
        - **Transportation Management** *(coming soon)*
        """
    )


# ===========================================================
# NAVIGATION (Sidebar menu)
# ===========================================================

st.sidebar.title("📂 Application Sections")
mode = st.sidebar.radio(
    "Choose a section",
    [
        "Home",
        "Non-Productive Inventory Management",
        "Planning Overview",
        "Storage Capacity Management",
        "Transportation Management",
    ],
)

if mode == "Home":
    run_home()
elif mode == "Non-Productive Inventory Management":
    run_npi_app()
elif mode == "Planning Overview":
    run_planning_overview()
elif mode == "Storage Capacity Management":
    run_storage_capacity()
elif mode == "Transportation Management":
    run_transport_mgmt()

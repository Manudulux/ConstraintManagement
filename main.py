
import streamlit as st
import pandas as pd
import os
import altair as alt
from io import BytesIO
import re

# ===========================================================
# PAGE CONFIG
# ===========================================================
st.set_page_config(
    page_title="Inventory & Supply Chain Toolkit",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ===========================================================
# SHARED HELPERS (robust CSV loading, normalization, downloads)
# ===========================================================
def read_csv_robust(upload_or_path):
    """Try common separator/encoding combos."""
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
            continue
    if hasattr(upload_or_path, "seek"):
        upload_or_path.seek(0)
    return pd.read_csv(upload_or_path)

def df_to_csv_bytes(df: pd.DataFrame) -> bytes:
    return df.to_csv(index=False).encode("utf-8")

def df_to_excel_bytes(df: pd.DataFrame, sheet_name: str = "Sheet1"):
    """Excel engine fallback: openpyxl → xlsxwriter → None."""
    try:
        buf = BytesIO()
        with pd.ExcelWriter(buf, engine="openpyxl") as writer:
            df.to_excel(writer, index=False, sheet_name=sheet_name)
        buf.seek(0)
        return buf.getvalue()
    except Exception:
        pass
    try:
        buf = BytesIO()
        with pd.ExcelWriter(buf, engine="xlsxwriter") as writer:
            df.to_excel(writer, index=False, sheet_name=sheet_name)
        buf.seek(0)
        return buf.getvalue()
    except Exception:
        return None

# ===========================================================
# ========== EXISTING NON‑PRODUCTIVE INVENTORY APP ==========
# (unchanged except being wrapped in a function)
# ===========================================================
def run_npi_app():

    # ------------- Column aliases for NPI -------------
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
            key = c.strip().lower()
            if key in COLUMN_ALIASES:
                mapping[c] = COLUMN_ALIASES[key]
        if mapping:
            df = df.rename(columns=mapping)
        # also strip whitespace from all column names
        df.columns = [c.strip() for c in df.columns]
        return df

    def load_data(upload):
        if upload is None:
            path = "StockHistorySample.csv"
            if not os.path.exists(path):
                st.error("Default file StockHistorySample.csv not found. Please upload a CSV.")
                st.stop()
            df = read_csv_robust(path)
            src = path
        else:
            upload.seek(0)
            df = read_csv_robust(upload)
            src = upload.name

        df = normalize_columns(df)

        if "Period" in df.columns:
            df["Period"] = pd.to_datetime(df["Period"], errors="coerce", infer_datetime_format=True)

        for col in ["QualityInspectionQty","BlockedStockQty","ReturnStockQty","OveragedTireQty"]:
            if col in df.columns:
                df[col] = (
                    df[col].astype(str)
                         .str.replace("\u00A0","",regex=False)
                         .str.replace(",","",regex=False)
                         .str.strip()
                )
                df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0)

        if "Period" in df.columns:
            pmin, pmax = df["Period"].min(), df["Period"].max()
            st.caption(f"📂 Source: {src} | Rows: {len(df):,} | Period range: {pmin.date()} → {pmax.date()}")
        else:
            st.caption(f"📂 Source: {src} | Rows: {len(df):,}")

        return df

    def compute_last_zero_date(hist_df, qty_col):
        z = hist_df.loc[hist_df[qty_col] == 0, "Period"]
        return z.max() if not z.empty else None

    def build_summary(df, qty_col):
        if "Period" not in df.columns: return pd.DataFrame()
        latest_period = df["Period"].max()
        oldest_period = df["Period"].min()
        if pd.isna(latest_period) or qty_col not in df.columns: return pd.DataFrame()

        snap = df[(df["Period"] == latest_period) & (df[qty_col] > 0)]
        if snap.empty:
            return pd.DataFrame(columns=[
                "SapCode","MaterialDescription","Warehouse","Brand","AB","Hier2","Hier4",
                "Quantity","Last Zero Date","Days Since Zero"
            ])

        rows = []
        for (mat, wh), _ in snap.groupby(["SapCode","Warehouse"]):
            hist = df[(df["SapCode"]==mat)&(df["Warehouse"]==wh)].sort_values("Period")
            last_zero = compute_last_zero_date(hist, qty_col) or oldest_period
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
                "Days Since Zero": (latest_period - last_zero).days
            })
        return pd.DataFrame(rows).sort_values("Quantity", ascending=False)

    def style_days_since(df, warn, high, critical):
        def style_val(v):
            if v >= critical: return "background-color:#ffd6d6;"
            if v >= high:     return "background-color:#ffe6cc;"
            if v >= warn:     return "background-color:#fff7bf;"
            return ""
        def color(series): return [style_val(v) for v in series]
        return (df.style
                  .apply(color, subset=["Days Since Zero"], axis=0)
                  .set_properties(subset=["Quantity"], **{"font-weight":"600"})
                  .set_table_styles([{"selector":"th","props":[("font-weight","600"),("background","#f7f7f7")]}]))

    # Sidebar: upload + filters + thresholds
    st.sidebar.subheader("📥 Upload Data")
    uploaded_file = st.sidebar.file_uploader("Upload CSV (optional)", type="csv")

    file_key = uploaded_file.name if uploaded_file else "StockHistorySample.csv"
    if "npi_active_file" not in st.session_state:
        st.session_state.npi_active_file = file_key
    elif file_key != st.session_state.npi_active_file:
        for k in ["Warehouse","Hier2","Hier4","AB","Brand"]:
            st.session_state.pop(k, None)
        st.session_state.npi_active_file = file_key
        st.toast("Filters reset – new file loaded.")

    df = load_data(uploaded_file)

    def _opts(s): return sorted(pd.Series(s).dropna().unique().tolist())

    st.sidebar.subheader("📊 Filters")
    warehouse_sel = st.sidebar.multiselect("Warehouse", _opts(df.get("Warehouse",[])))
    hier2_sel     = st.sidebar.multiselect("Hier2", _opts(df.get("Hier2",[])))
    hier4_sel     = st.sidebar.multiselect("Hier4", _opts(df.get("Hier4",[])))
    ab_sel        = st.sidebar.multiselect("AB", _opts(df.get("AB",[])))
    brand_sel     = st.sidebar.multiselect("Brand", _opts(df.get("Brand",[])))

    with st.sidebar.expander("Highlight settings"):
        warn  = st.number_input("Warn (days)", 0, value=30)
        high  = st.number_input("High (days)", 0, value=60)
        crit  = st.number_input("Critical (days)", 0, value=90)

    if st.sidebar.button("🧹 Reset filters"):
        for k in ["Warehouse","Hier2","Hier4","AB","Brand"]:
            st.session_state.pop(k, None)
        st.rerun()

    data = df.copy()
    if warehouse_sel: data = data[data["Warehouse"].isin(warehouse_sel)]
    if hier2_sel:     data = data[data["Hier2"].isin(hier2_sel)]
    if hier4_sel:     data = data[data["Hier4"].isin(hier4_sel)]
    if ab_sel:        data = data[data["AB"].isin(ab_sel)]
    if brand_sel:     data = data[data["Brand"].isin(brand_sel)]

    st.title("Non-Productive Inventory Management")

    # Tabs
    tab_overview, tab_qi, tab_bs, tab_rs, tab_oa = st.tabs([
        "Overview","Quality Inspection Qty","Blocked Stock Qty","Return Stock Qty","Overaged Inventory"
    ])

    # Overview
    def get_qty_cols(df_in):
        cands = ["QualityInspectionQty","BlockedStockQty","ReturnStockQty","OveragedTireQty"]
        return [c for c in cands if c in df_in.columns]

    with tab_overview:
        st.subheader("📈 Total non-productive inventory over time (filtered)")
        if "Period" in data.columns:
            qcols = get_qty_cols(data)
            if qcols:
                tot = (data.groupby("Period")[qcols].sum(min_count=1).reset_index().sort_values("Period"))
                long = tot.melt("Period", qcols, "InventoryType","Quantity")
                chart = (alt.Chart(long).mark_line(point=True)
                         .encode(x="Period:T", y="Quantity:Q", color="InventoryType:N",
                                 tooltip=["Period:T","InventoryType:N","Quantity:Q"])
                         .properties(height=420, width=1400))
                st.altair_chart(chart, use_container_width=True)

                c1,c2 = st.columns(2)
                with c1:
                    st.download_button("⬇️ Download totals-over-time (CSV)", df_to_csv_bytes(tot),
                                       "totals_over_time.csv", mime="text/csv")
                with c2:
                    x = df_to_excel_bytes(tot,"Totals")
                    if x:
                        st.download_button("⬇️ Download totals-over-time (Excel)", x,
                                           "totals_over_time.xlsx",
                                           mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")

        st.markdown("---")
        st.subheader("🏭 Totals by Plant (latest period)")
        if "Period" in data.columns:
            latest = data["Period"].max()
            slice_df = data[data["Period"]==latest]
            qcols = get_qty_cols(data)
            if qcols:
                byp = (slice_df.groupby("Warehouse")[qcols].sum(min_count=1).reset_index())
                long = byp.melt("Warehouse", qcols, "InventoryType","Quantity")
                bar = (alt.Chart(long).mark_bar()
                       .encode(x="Warehouse:N", y="Quantity:Q", color="InventoryType:N",
                               tooltip=["Warehouse:N","InventoryType:N","Quantity:Q"])
                       .properties(height=420, width=1400))
                st.altair_chart(bar, use_container_width=True)
                st.dataframe(byp, use_container_width=True)

                c3,c4 = st.columns(2)
                with c3:
                    st.download_button("⬇️ Download totals-by-plant (CSV)", df_to_csv_bytes(byp),
                                       "totals_by_plant.csv", mime="text/csv")
                with c4:
                    x = df_to_excel_bytes(byp,"ByPlant")
                    if x:
                        st.download_button("⬇️ Download totals-by-plant (Excel)", x,
                                           "totals_by_plant.xlsx",
                                           mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")

    # Metric tab renderer
    def metric_tab(container, qty_col, title):
        with container:
            st.subheader(title)
            summ = build_summary(data, qty_col)
            if summ.empty:
                st.warning("No data available.")
                return

            styled = style_days_since(summ, warn, high, crit)
            st.dataframe(styled, use_container_width=True)

            c1,c2 = st.columns(2)
            with c1:
                st.download_button("⬇️ Download summary (CSV)", df_to_csv_bytes(summ),
                                   f"{qty_col}_summary.csv", mime="text/csv")
            with c2:
                x = df_to_excel_bytes(summ, qty_col+"_Summary")
                if x:
                    st.download_button("⬇️ Download summary (Excel)", x,
                                       f"{qty_col}_summary.xlsx",
                                       mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")

            st.markdown("---")
            st.subheader("🔍 Select a material + warehouse")

            summ["_label"] = (summ["SapCode"].astype(str) + " | " + summ["Warehouse"]
                              + " | Qty: " + summ["Quantity"].astype(int).astype(str)
                              + " | Days: " + summ["Days Since Zero"].astype(int).astype(str))
            pick = st.selectbox("Choose:", summ["_label"].tolist())
            row = summ[summ["_label"]==pick].iloc[0]
            mat, wh = row["SapCode"], row["Warehouse"]

            hist = data[(data["SapCode"]==mat)&(data["Warehouse"]==wh)].sort_values("Period")
            st.write("### 📄 Full History")
            st.dataframe(hist, use_container_width=True)

            c3,c4 = st.columns(2)
            with c3:
                st.download_button("⬇️ Download history (CSV)", df_to_csv_bytes(hist),
                                   f"{qty_col}_{mat}_{wh}_history.csv", mime="text/csv")
            with c4:
                x = df_to_excel_bytes(hist, qty_col+"_History")
                if x:
                    st.download_button("⬇️ Download history (Excel)", x,
                                       f"{qty_col}_{mat}_{wh}_history.xlsx",
                                       mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")

            st.write("### 📊 Quantity Over Time")
            if "Period" in hist.columns and qty_col in hist.columns:
                line = (alt.Chart(hist).mark_line(point=True)
                        .encode(x="Period:T", y=f"{qty_col}:Q", tooltip=["Period", qty_col])
                        .properties(height=450, width=1400))
                st.altair_chart(line, use_container_width=True)

    metric_tab(tab_qi, "QualityInspectionQty", "Quality Inspection Qty")
    metric_tab(tab_bs, "BlockedStockQty",      "Blocked Stock Qty")
    metric_tab(tab_rs, "ReturnStockQty",       "Return Stock Qty")
    metric_tab(tab_oa, "OveragedTireQty",      "Overaged Inventory")


# ===========================================================
# ========== NEW: PLANNING OVERVIEW MODULE ==================
# ===========================================================
def run_planning_overview():
    st.title("Planning Overview")

    # ---------------- Sidebar: data upload (TWforecasts.csv) ----------------
    st.sidebar.subheader("📥 Forecast Data")
    uploaded = st.sidebar.file_uploader("Upload TWforecasts.csv (optional)", type="csv")

    # Default read from script directory if not uploaded
    def load_tw(upload):
        if upload is None:
            path = "TWforecasts.csv"
            if not os.path.exists(path):
                st.warning("TWforecasts.csv not found in script folder. Please upload it in the sidebar.")
                return pd.DataFrame()
            df = read_csv_robust(path)
            src = path
        else:
            upload.seek(0)
            df = read_csv_robust(upload)
            src = upload.name

        # Normalize columns: strip whitespace and fix common variants
        df.columns = [c.strip() for c in df.columns]

        # Standardize expected names where possible
        rename_map = {}
        for c in df.columns:
            c_low = c.lower().replace(" ", "").replace("_", "")
            if c_low == "warehouse":           rename_map[c] = "Warehouse"
            elif c_low == "loadingtype":       rename_map[c] = "Loadingtype"
            elif c_low in ("selecteddimension", "selecteddimension,"):  # guard
                rename_map[c] = "SelectedDimension"
            elif c_low in ("periodyear", "periodyear"):  rename_map[c] = "Period_Year"
            elif c_low == "week":              rename_map[c] = "Week"
            elif c_low in ("transferquantity","transfer_qty","transferquantityamount"):
                rename_map[c] = "Transfer_Quantity"
        if rename_map:
            df = df.rename(columns=rename_map)

        # Clean numeric Transfer_Quantity (remove quotes/commas/nbspaces)
        if "Transfer_Quantity" in df.columns:
            df["Transfer_Quantity"] = (df["Transfer_Quantity"].astype(str)
                                       .str.replace("\u00A0","", regex=False)
                                       .str.replace(",","", regex=False)
                                       .str.replace('"',"", regex=False)
                                       .str.strip())
            df["Transfer_Quantity"] = pd.to_numeric(df["Transfer_Quantity"], errors="coerce").fillna(0)

        # Cleanup values: week as integer (W03 -> 3)
        if "Week" in df.columns:
            df["Week"] = df["Week"].astype(str).str.strip()
            df["Week_num"] = df["Week"].apply(lambda s: int(re.sub(r"[^\d]", "", s)) if re.search(r"\d+", s) else None)

        # Also standardize SelectedDimension values
        if "SelectedDimension" in df.columns:
            df["SelectedDimension"] = df["SelectedDimension"].astype(str).str.strip().str.title()

        # Drop rows missing core fields
        needed = ["Warehouse","Loadingtype","Period_Year","Week_num","Transfer_Quantity"]
        if not all(k in df.columns for k in needed):
            st.error("Missing needed columns after normalization. Expected at least: "
                     "'Warehouse','Loadingtype','Period_Year','Week','Transfer_Quantity'.")
            return pd.DataFrame()

        st.caption(f"📂 Forecast source: {src} | Rows: {len(df):,} | Warehouses: "
                   f"{', '.join(sorted(df['Warehouse'].dropna().astype(str).unique())[:8])}"
                   f"{'…' if df['Warehouse'].nunique() > 8 else ''}")
        return df

    tw_df = load_tw(uploaded)
    if tw_df.empty:
        return

    # ---------------- Sidebar: Starting Physical Stock per plant ----------------
    st.sidebar.subheader("🏁 Starting Physical Stock (by plant)")
    plants = sorted(tw_df["Warehouse"].dropna().astype(str).unique())
    # Build editable table once, keep it in session
    if "starting_stock_df" not in st.session_state or \
       set(st.session_state.get("starting_stock_df", pd.DataFrame()).get("Warehouse", [])) != set(plants):
        st.session_state.starting_stock_df = pd.DataFrame({"Warehouse": plants, "Starting_PhysicalStock": 0})

    st.sidebar.caption("Edit the starting stock per plant (used at the first week of the projection).")
    st.session_state.starting_stock_df = st.sidebar.data_editor(
        st.session_state.starting_stock_df, hide_index=True, use_container_width=True, num_rows="dynamic", key="startstock_editor"
    )

    # ---------------- Optional plant filter (for viewing) ----------------
    st.sidebar.subheader("🔎 View Filters")
    view_plants = st.sidebar.multiselect("Plants to display", plants, default=plants)

    # ---------------- Build the projection ----------------
    def build_projection(df: pd.DataFrame, start_df: pd.DataFrame):
        # Aggregate by Warehouse, Year, Week, Loadingtype, SelectedDimension
        # (SelectedDimension may be 'Loose','Pallet','Mixed', or absent for some plants)
        group_cols = ["Warehouse","Period_Year","Week_num","Loadingtype","SelectedDimension"]
        agg = (df.groupby(group_cols)["Transfer_Quantity"].sum().reset_index())

        # Create Load/Unload detail columns
        # Pivot to columns: (Loadingtype, SelectedDimension)
        pivot = (agg.pivot_table(index=["Warehouse","Period_Year","Week_num"],
                                 columns=["Loadingtype","SelectedDimension"],
                                 values="Transfer_Quantity", aggfunc="sum")
                   .fillna(0))
        # Flatten multiindex columns
        pivot.columns = [f"{lt}_{sd}" for lt, sd in pivot.columns]
        pivot = pivot.reset_index()

        # Ensure all expected detail columns exist
        detail_cols = []
        for lt in ("Load","Unload"):
            for sd in ("Loose","Pallet","Mixed"):
                col = f"{lt}_{sd}"
                if col not in pivot.columns:
                    pivot[col] = 0
                detail_cols.append(col)

        # Totals per Load/Unload
        pivot["Load_Total"]   = pivot["Load_Loose"] + pivot["Load_Pallet"] + pivot["Load_Mixed"]
        pivot["Unload_Total"] = pivot["Unload_Loose"] + pivot["Unload_Pallet"] + pivot["Unload_Mixed"]

        # Merge Starting Stock mapping
        start_map = dict(zip(start_df["Warehouse"], pd.to_numeric(start_df["Starting_PhysicalStock"], errors="coerce").fillna(0)))
        pivot = pivot.sort_values(["Warehouse","Period_Year","Week_num"])

        # Projection per plant (cumulative)
        results = []
        for wh, grp in pivot.groupby("Warehouse", sort=False):
            grp = grp.sort_values(["Period_Year","Week_num"]).copy()
            # Baseline (starting stock before first listed week)
            start_stock = float(start_map.get(wh, 0))

            # We compute Projected_Stock as rolling:
            # Projected_Stock_t = (Projected_Stock_{t-1}) + Load_Total_t - Unload_Total_t
            projected = []
            prev = start_stock
            for _, r in grp.iterrows():
                end = prev + r["Load_Total"] - r["Unload_Total"]
                projected.append(end)
                prev = end
            grp["Starting_Stock"]  = None
            if len(grp) > 0:
                grp.loc[grp.index[0], "Starting_Stock"] = start_stock
            grp["Projected_Stock"] = projected
            results.append(grp)

        proj = pd.concat(results, ignore_index=True) if results else pivot.copy()
        # Human-friendly Year-Week label for sorting/plotting
        proj["YearWeek"] = proj["Period_Year"].astype(str) + "-W" + proj["Week_num"].astype(int).astype(str).str.zfill(2)

        # Reorder columns for readability
        cols = ["Warehouse","Period_Year","Week_num","YearWeek","Starting_Stock",
                "Load_Loose","Load_Pallet","Load_Mixed","Load_Total",
                "Unload_Loose","Unload_Pallet","Unload_Mixed","Unload_Total",
                "Projected_Stock"]
        existing = [c for c in cols if c in proj.columns]
        details = proj[existing].copy()
        return details

    projection_df = build_projection(tw_df, st.session_state.starting_stock_df)

    # ---------------- DISPLAY ----------------
    st.subheader("📄 Inventory Projection (week by week)")
    if view_plants:
        view_df = projection_df[projection_df["Warehouse"].isin(view_plants)].copy()
    else:
        view_df = projection_df.copy()

    # Order for display: by plant, then year-week
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

    # ---------------- Charts ----------------
    st.markdown("---")
    st.subheader("📈 Projected Stock over time")

    if not view_df.empty:
        stock_line = (alt.Chart(view_df)
            .mark_line(point=True)
            .encode(
                x=alt.X("YearWeek:N", sort=None, title="Year-Week"),
                y=alt.Y("Projected_Stock:Q", title="Projected Stock"),
                color=alt.Color("Warehouse:N", title="Plant"),
                tooltip=["Warehouse","YearWeek","Projected_Stock",
                         "Load_Total","Unload_Total"]
            ).properties(height=420, width=1400))
        st.altair_chart(stock_line, use_container_width=True)

    st.markdown("---")
    st.subheader("📦 Weekly Load vs Unload breakdown (select one plant)")

    plant_pick = st.selectbox("Plant", sorted(projection_df["Warehouse"].unique().tolist()))
    plant_df = projection_df[projection_df["Warehouse"]==plant_pick].copy()
    if not plant_df.empty:
        # Melt for stacked bars
        melt_cols = ["Load_Loose","Load_Pallet","Load_Mixed","Unload_Loose","Unload_Pallet","Unload_Mixed"]
        bar_long = plant_df.melt(id_vars=["YearWeek"], value_vars=melt_cols,
                                 var_name="FlowType", value_name="Qty")
        # Keep two charts aligned
        load_long   = bar_long[bar_long["FlowType"].str.startswith("Load_")].copy()
        unload_long = bar_long[bar_long["FlowType"].str.startswith("Unload_")].copy()

        load_bar = (alt.Chart(load_long).mark_bar().encode(
            x=alt.X("YearWeek:N", sort=None, title="Year-Week"),
            y=alt.Y("Qty:Q", title="Load (Qty)"),
            color=alt.Color("FlowType:N", title="Load Type"),
            tooltip=["YearWeek","FlowType","Qty"]
        ).properties(height=220, width=1400))

        unload_bar = (alt.Chart(unload_long).mark_bar().encode(
            x=alt.X("YearWeek:N", sort=None, title="Year-Week"),
            y=alt.Y("Qty:Q", title="Unload (Qty)"),
            color=alt.Color("FlowType:N", title="Unload Type"),
            tooltip=["YearWeek","FlowType","Qty"]
        ).properties(height=220, width=1400))

        st.altair_chart(load_bar, use_container_width=True)
        st.altair_chart(unload_bar, use_container_width=True)

    # Helper tip
    st.info("Tip: Adjust **Starting Physical Stock** in the sidebar to see the projection update immediately.")

# ===========================================================
# ========== LAYOUT / NAVIGATION ============================
# ===========================================================
st.sidebar.title("📂 Application Sections")
app_mode = st.sidebar.radio(
    "Choose a section",
    [
        "Home",
        "Non-Productive Inventory Management",
        "Planning Overview",
        "Storage Capacity Management",
        "Transportation Management",
    ],
)

# ---------------- Home ----------------
if app_mode == "Home":
    st.title("Welcome to the Supply Chain Management Dashboard")
    st.subheader("Please choose a module from the sidebar.")
    st.markdown("""
    ## Available Modules
    - **Non-Productive Inventory Management**  
      Analyze non-productive stock, visualize trends, compute days since zero, and deep-dive into material history.

    - **Planning Overview**  
      Upload weekly load/unload forecasts and build a **week-by-week inventory projection** by plant.

    - **Storage Capacity Management** *(coming soon)*

    - **Transportation Management** *(coming soon)*
    """)

# ---------------- NPI ----------------
elif app_mode == "Non-Productive Inventory Management":
    run_npi_app()

# ---------------- Planning Overview ----------------
elif app_mode == "Planning Overview":
    run_planning_overview()

# ---------------- Placeholders ----------------
elif app_mode == "Storage Capacity Management":
    st.title("Storage Capacity Management")
    st.info("This module will be developed in a future release.")

elif app_mode == "Transportation Management":
    st.title("Transportation Management")
    st.info("This module will be developed in a future release.")

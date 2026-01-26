import streamlit as st
import pandas as pd
import os
import altair as alt
import re
from io import BytesIO

# ------------------------------------------------------------
# PAGE CONFIG
# ------------------------------------------------------------
st.set_page_config(
    page_title="Inventory & Supply Chain Toolkit",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ------------------------------------------------------------
# SHARED HELPERS
# ------------------------------------------------------------
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
        pass
    try:
        buf = BytesIO()
        with pd.ExcelWriter(buf, engine="xlsxwriter") as w:
            df.to_excel(w, index=False, sheet_name=sheet_name)
        buf.seek(0)
        return buf.getvalue()
    except Exception:
        return None

# >>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>
# NEW: Standard PlantKey rule (first 4 alphanumerics, uppercased)
# >>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>

def derive_plant_key(series: pd.Series) -> pd.Series:
    def _norm(x):
        if pd.isna(x):
            return None
        s = re.sub(r"[^A-Za-z0-9]", "", str(x)).upper()
        return s[:4] if len(s) >= 4 else None
    return series.apply(_norm)

# ------------------------------------------------------------
# SESSION-STATE FILE ROUTING (HOME → MODULES)
# ------------------------------------------------------------
INVENTORY_DEFAULT = "StockHistorySample.csv"
FORECAST_DEFAULT = "TWforecasts.csv"
BDD000_DEFAULT = "000BDD400.csv"  # Transfer/receipt flows per week (assumption)
BDD0030_DEFAULT = "0030BDD400.csv"  # Closing stock per week (assumption)
PLANTCAP_DEFAULT = "PlantCapacity.csv"

# Generic getter with default fallback and user feedback

def _get_df_from_state(bytes_key: str, name_key: str, default_filename: str, warn_if_missing: bool = True):
    if st.session_state.get(bytes_key):
        bio = BytesIO(st.session_state[bytes_key])
        df = read_csv_robust(bio)
        src = st.session_state.get(name_key, "uploaded.csv")
        st.session_state[f"{bytes_key}_caption"] = src
        return df
    else:
        if os.path.exists(default_filename):
            df = read_csv_robust(default_filename)
            st.session_state[f"{bytes_key}_caption"] = default_filename
            return df
        else:
            if warn_if_missing:
                st.warning(f"Default file '{default_filename}' not found. Upload it on Home.")
            return pd.DataFrame()


def get_inventory_df_from_state():
    return _get_df_from_state("inventory_file_bytes", "inventory_file_name", INVENTORY_DEFAULT, warn_if_missing=False)


def get_forecast_df_from_state():
    return _get_df_from_state("forecast_file_bytes", "forecast_file_name", FORECAST_DEFAULT, warn_if_missing=False)


def get_bdd000_df_from_state():
    return _get_df_from_state("bdd000_file_bytes", "bdd000_file_name", BDD000_DEFAULT, warn_if_missing=False)


def get_bdd0030_df_from_state():
    return _get_df_from_state("bdd0030_file_bytes", "bdd0030_file_name", BDD0030_DEFAULT, warn_if_missing=False)


def get_plant_capacity_df_from_state():
    return _get_df_from_state("plantcap_file_bytes", "plantcap_file_name", PLANTCAP_DEFAULT, warn_if_missing=False)

# ------------------------------------------------------------
# MODULE 1 — NON-PRODUCTIVE INVENTORY MANAGEMENT (NPI)
# ------------------------------------------------------------

def run_npi_app():
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

    def normalize_columns(df):
        mapping = {}
        for c in df.columns:
            low = c.lower().strip()
            if low in COLUMN_ALIASES:
                mapping[c] = COLUMN_ALIASES[low]
        df = df.rename(columns=mapping)
        df.columns = [c.strip() for c in df.columns]
        return df

    df = get_inventory_df_from_state()
    if df.empty:
        st.info("Please upload an Inventory file on Home.")
        return
    df = normalize_columns(df)
    if "Period" in df.columns:
        df["Period"] = pd.to_datetime(df["Period"], errors="coerce", infer_datetime_format=True)

    for col in ["QualityInspectionQty", "BlockedStockQty", "ReturnStockQty", "OveragedTireQty", "PhysicalStock"]:
        if col in df.columns:
            df[col] = (
                df[col]
                .astype(str)
                .str.replace(" ", "", regex=False)
                .str.replace(",", "", regex=False)
                .str.strip()
            )
            df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0)

    if "Period" in df.columns:
        pmin, pmax = df["Period"].min(), df["Period"].max()
        src = st.session_state.get(
            "inventory_file_bytes_caption", st.session_state.get("inventory_source_caption", "")
        )
        st.caption(
            f"📂 Inventory source: {st.session_state.get('inventory_file_bytes_caption', '')} \\\nRows: {len(df):,} \\\nPeriod range: {pmin.date()} → {pmax.date()}"
        )
    else:
        st.caption(
            f"📂 Inventory source: {st.session_state.get('inventory_file_bytes_caption','')} \\\nRows: {len(df):,}"
        )

    def compute_last_zero_date(hist_df, qty_col):
        z = hist_df.loc[hist_df[qty_col] == 0, "Period"]
        return z.max() if not z.empty else None

    def build_summary(dfin, qty_col):
        if "Period" not in dfin.columns:
            return pd.DataFrame()
        latest = dfin["Period"].max()
        oldest = dfin["Period"].min()
        if pd.isna(latest) or qty_col not in dfin.columns:
            return pd.DataFrame()
        snap = dfin[(dfin["Period"] == latest) & (dfin[qty_col] > 0)]
        if snap.empty:
            return pd.DataFrame(
                columns=[
                    "SapCode",
                    "MaterialDescription",
                    "Warehouse",
                    "Brand",
                    "AB",
                    "Hier2",
                    "Hier4",
                    "Quantity",
                    "Last Zero Date",
                    "Days Since Zero",
                ]
            )
        rows = []
        for (mat, wh), _ in snap.groupby(["SapCode", "Warehouse"]):
            hist = dfin[(dfin["SapCode"] == mat) & (dfin["Warehouse"] == wh)].sort_values("Period")
            last_zero = compute_last_zero_date(hist, qty_col) or oldest
            last_row = hist.iloc[-1]
            rows.append(
                {
                    "SapCode": mat,
                    "MaterialDescription": last_row.get("MaterialDescription", ""),
                    "Warehouse": wh,
                    "Brand": last_row.get("Brand", ""),
                    "AB": last_row.get("AB", ""),
                    "Hier2": last_row.get("Hier2", ""),
                    "Hier4": last_row.get("Hier4", ""),
                    "Quantity": last_row.get(qty_col, 0),
                    "Last Zero Date": last_zero.date(),
                    "Days Since Zero": (latest - last_zero).days,
                }
            )
        return pd.DataFrame(rows).sort_values("Quantity", ascending=False)

    def style_days_since(df, warn, high, crit):
        def style_val(v):
            if v >= crit:
                return "background-color:#ffd6d6;"
            if v >= high:
                return "background-color:#ffe6cc;"
            if v >= warn:
                return "background-color:#fff7bf;"
            return ""

        def color(series):
            return [style_val(v) for v in series]

        return (
            df.style.apply(color, subset=["Days Since Zero"], axis=0)
            .set_properties(subset=["Quantity"], **{"font-weight": "600"})
            .set_table_styles(
                [{"selector": "th", "props": [("font-weight", "600"), ("background", "#f7f7f7")] }]
            )
        )

    st.sidebar.subheader("📊 Filters (NPI)")

    def _opts(s):
        return sorted(pd.Series(s).dropna().unique().tolist())

    warehouse_sel = st.sidebar.multiselect("Warehouse", _opts(df.get("Warehouse", [])))
    hier2_sel = st.sidebar.multiselect("Hier2", _opts(df.get("Hier2", [])))
    hier4_sel = st.sidebar.multiselect("Hier4", _opts(df.get("Hier4", [])))
    ab_sel = st.sidebar.multiselect("AB", _opts(df.get("AB", [])))
    brand_sel = st.sidebar.multiselect("Brand", _opts(df.get("Brand", [])))

    with st.sidebar.expander("Highlight thresholds"):
        warn = st.number_input("Warn (days)", 0, value=30)
        high = st.number_input("High (days)", 0, value=60)
        crit = st.number_input("Critical (days)", 0, value=90)

    if st.sidebar.button("🧹 Clear filters"):
        for k in ["Warehouse", "Hier2", "Hier4", "AB", "Brand"]:
            st.session_state.pop(k, None)
        st.rerun()

    data = df.copy()
    if warehouse_sel:
        data = data[data["Warehouse"].isin(warehouse_sel)]
    if hier2_sel:
        data = data[data["Hier2"].isin(hier2_sel)]
    if hier4_sel:
        data = data[data["Hier4"].isin(hier4_sel)]
    if ab_sel:
        data = data[data["AB"].isin(ab_sel)]
    if brand_sel:
        data = data[data["Brand"].isin(brand_sel)]

    st.title("Non-Productive Inventory Management")
    tab_o, tab_qi, tab_bs, tab_rs, tab_oa = st.tabs(
        [
            "Overview",
            "Quality Inspection Qty",
            "Blocked Stock Qty",
            "Return Stock Qty",
            "Overaged Inventory",
        ]
    )

    def get_qty_cols(dfin):
        cands = ["QualityInspectionQty", "BlockedStockQty", "ReturnStockQty", "OveragedTireQty"]
        return [c for c in cands if c in dfin.columns]

    with tab_o:
        st.subheader("📈 Total NPI over time (filtered)")
        if "Period" in data.columns:
            qcols = get_qty_cols(data)
            if qcols:
                tot = (
                    data.groupby("Period")[qcols].sum(min_count=1).reset_index().sort_values("Period")
                )
                long = tot.melt("Period", qcols, "InventoryType", "Quantity")
                chart = (
                    alt.Chart(long)
                    .mark_line(point=True)
                    .encode(
                        x="Period:T",
                        y="Quantity:Q",
                        color="InventoryType:N",
                        tooltip=["Period:T", "InventoryType:N", "Quantity:Q"],
                    )
                    .properties(height=420, width=1400)
                )
                st.altair_chart(chart, use_container_width=True)

        st.markdown("---")
        st.subheader("🏭 Totals by Plant (latest period)")
        if "Period" in data.columns:
            latest = data["Period"].max()
            qcols = get_qty_cols(data)
            byp = (
                data[data["Period"] == latest].groupby("Warehouse")[qcols].sum().reset_index()
            ) if qcols else pd.DataFrame()
            if "PhysicalStock" in data.columns:
                ps = (
                    data[data["Period"] == latest]
                    .groupby("Warehouse")["PhysicalStock"].sum()
                    .reset_index()
                )
                byp = byp.merge(ps, on="Warehouse", how="left") if not byp.empty else ps
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
            st.subheader("🔎 Select material + warehouse")
            summ["_label"] = (
                summ["SapCode"].astype(str)
                + " · "
                + summ["Warehouse"]
                + " · Qty: "
                + summ["Quantity"].astype(int).astype(str)
                + " · Days: "
                + summ["Days Since Zero"].astype(int).astype(str)
            )
            pick = st.selectbox("Choose:", summ["_label"].tolist())
            r = summ[summ["_label"] == pick].iloc[0]
            mat, wh = r["SapCode"], r["Warehouse"]

            hist = data[(data["SapCode"] == mat) & (data["Warehouse"] == wh)].sort_values("Period")
            st.write("### 📄 Full History")
            st.dataframe(hist, use_container_width=True)
            if "Period" in hist.columns:
                line = (
                    alt.Chart(hist)
                    .mark_line(point=True)
                    .encode(x="Period:T", y=f"{qty_col}:Q", tooltip=["Period", qty_col])
                    .properties(height=450, width=1400)
                )
                st.altair_chart(line, use_container_width=True)

    metric_tab(tab_qi, "QualityInspectionQty", "Quality Inspection Qty")
    metric_tab(tab_bs, "BlockedStockQty", "Blocked Stock Qty")
    metric_tab(tab_rs, "ReturnStockQty", "Return Stock Qty")
    metric_tab(tab_oa, "OveragedTireQty", "Overaged Inventory")

# ------------------------------------------------------------
# MODULE 2 — PLANNING OVERVIEW (T&W Forecast Projections)
# ------------------------------------------------------------

def run_planning_overview_tw():
    st.title("Planning Overview T&W — Weekly Inventory Projection")

    # ---- LOAD FORECAST ----
    fdf = get_forecast_df_from_state()
    if fdf.empty:
        st.info("Please upload TWforecasts.csv on Home.")
        return

    # Normalize forecast columns
    fdf.columns = [c.strip() for c in fdf.columns]
    rename_map = {}
    for c in fdf.columns:
        low = c.lower().replace(" ", "").replace("_", "")
        if low == "warehouse":
            rename_map[c] = "Warehouse"
        elif low in ("plant",):
            rename_map[c] = "Warehouse"
        elif low == "loadingtype":
            rename_map[c] = "Loadingtype"
        elif low in ("selecteddimension", "selecteddimension,"):
            rename_map[c] = "SelectedDimension"
        elif low == "periodyear":
            rename_map[c] = "Period_Year"
        elif low == "week":
            rename_map[c] = "Week"
        elif low in ("transferquantity", "transferqty", "transferquantityamount"):
            rename_map[c] = "Transfer_Quantity"
    if rename_map:
        fdf = fdf.rename(columns=rename_map)

    if "Transfer_Quantity" in fdf.columns:
        fdf["Transfer_Quantity"] = (
            fdf["Transfer_Quantity"]
            .astype(str)
            .str.replace(" ", "", regex=False)
            .str.replace(",", "", regex=False)
            .str.replace('"', "", regex=False)
            .str.strip()
        )
        fdf["Transfer_Quantity"] = pd.to_numeric(
            fdf["Transfer_Quantity"], errors="coerce"
        ).fillna(0)

    if "Week" in fdf.columns:
        fdf["Week"] = fdf["Week"].astype(str).str.strip()
        fdf["Week_num"] = fdf["Week"].apply(
            lambda s: int(re.sub(r"[^\d]", "", s)) if re.search(r"\d+", s) else None
        )

    if "SelectedDimension" in fdf.columns:
        fdf["SelectedDimension"] = (
            fdf["SelectedDimension"].astype(str).str.strip().str.title()
        )

    src = st.session_state.get("forecast_file_bytes_caption", "")
    st.caption(f"📂 Forecast source: {src} \\\nRows: {len(fdf):,}")

    # ---- LOAD INVENTORY (to get PhysicalStock baselines) ----
    idf = get_inventory_df_from_state()
    inv_note = st.session_state.get("inventory_file_bytes_caption", "")

    # Normalize inventory
    if not idf.empty:
        idf.columns = [c.strip() for c in idf.columns]
        if "Period" in idf.columns:
            idf["Period"] = pd.to_datetime(idf["Period"], errors="coerce", infer_datetime_format=True)
        if "PhysicalStock" in idf.columns:
            idf["PhysicalStock"] = (
                idf["PhysicalStock"].astype(str)
                .str.replace(" ", "", regex=False)
                .str.replace(",", "", regex=False)
                .str.strip()
            )
            idf["PhysicalStock"] = pd.to_numeric(
                idf["PhysicalStock"], errors="coerce"
            ).fillna(0)

    # Build weekly physical stock by plant (ISO year/week)
    inv_weekly = pd.DataFrame()
    if not idf.empty and {"Warehouse", "Period", "PhysicalStock"}.issubset(idf.columns):
        iso = idf["Period"].dt.isocalendar()
        idf["ISO_Year"], idf["ISO_Week"] = iso.year, iso.week
        inv_weekly = (
            idf.groupby(["Warehouse", "ISO_Year", "ISO_Week"], dropna=True)["PhysicalStock"]
            .sum()
            .reset_index()
        )
        inv_weekly["YearWeekIdx"] = inv_weekly["ISO_Year"] * 100 + inv_weekly["ISO_Week"]
        # Standardize plant matching (PlantKey = first 4 alphanumerics)
        inv_weekly["PlantKey"] = derive_plant_key(inv_weekly["Warehouse"].astype(str))

    # ---- Sidebar controls ----
    st.sidebar.subheader("🏁 Starting Physical Stock (fallback per plant)")
    plants = (
        sorted(fdf["Warehouse"].dropna().astype(str).unique())
        if "Warehouse" in fdf.columns
        else []
    )
    if "start_stock_df" not in st.session_state or set(st.session_state["start_stock_df"].get("Warehouse", [])) != set(plants):
        st.session_state["start_stock_df"] = pd.DataFrame(
            {"Warehouse": plants, "Starting_PhysicalStock": 0}
        )
    st.sidebar.caption(
        "Used only if no inventory baseline is found for a plant prior to the first forecast week."
    )
    st.session_state["start_stock_df"] = st.sidebar.data_editor(
        st.session_state["start_stock_df"],
        hide_index=True,
        use_container_width=True,
        num_rows="dynamic",
    )

    st.sidebar.subheader("🔎 View Filters")
    view_plants = st.sidebar.multiselect("Plants to display", plants, default=plants)

    # ---- Build Projection with baseline rule ----
    def build_projection(fdf: pd.DataFrame, inv_weekly: pd.DataFrame, start_df: pd.DataFrame):
        group_cols = [
            "Warehouse",
            "Period_Year",
            "Week_num",
            "Loadingtype",
            "SelectedDimension",
        ]
        agg = fdf.groupby(group_cols)["Transfer_Quantity"].sum().reset_index()
        pivot = (
            agg.pivot_table(
                index=["Warehouse", "Period_Year", "Week_num"],
                columns=["Loadingtype", "SelectedDimension"],
                values="Transfer_Quantity",
                aggfunc="sum",
            )
            .fillna(0)
            .reset_index()
        )
        # Flatten
        pivot.columns = [
            f"{a}_{b}" if isinstance((a, b), tuple) and b != "" else (a if not isinstance((a, b), tuple) else a)
            for (a, b) in [(c if isinstance(c, tuple) else (c, "")) for c in pivot.columns]
        ]

        for lt in ("Load", "Unload"):
            for sd in ("Loose", "Pallet", "Mixed"):
                col = f"{lt}_{sd}"
                if col not in pivot.columns:
                    pivot[col] = 0

        pivot["Load_Total"] = pivot["Load_Loose"] + pivot["Load_Pallet"] + pivot["Load_Mixed"]
        pivot["Unload_Total"] = pivot["Unload_Loose"] + pivot["Unload_Pallet"] + pivot["Unload_Mixed"]
        pivot = pivot.sort_values(["Warehouse", "Period_Year", "Week_num"])
        pivot["YearWeekIdx"] = pivot["Period_Year"] * 100 + pivot["Week_num"].astype(int)

        # Build start stock lookup by standardized PlantKey (fallback to raw Warehouse)
        start_tmp = start_df.copy()
        start_tmp["PlantKey"] = derive_plant_key(start_tmp["Warehouse"].astype(str))
        start_tmp["__k"] = start_tmp["PlantKey"].fillna(start_tmp["Warehouse"].astype(str))
        start_map = dict(
            zip(
                start_tmp["__k"],
                pd.to_numeric(start_tmp["Starting_PhysicalStock"], errors="coerce").fillna(0),
            )
        )
        results = []
        for wh, grp in pivot.groupby("Warehouse", sort=False):
            grp = grp.sort_values(["Period_Year", "Week_num"]).copy()
            first_idx = int(grp.iloc[0]["YearWeekIdx"]) if len(grp) > 0 else None
            baseline = None

            # Standardize plant matching (PlantKey = first 4 alphanumerics)
            wh_key = derive_plant_key(pd.Series([wh])).iloc[0]
            lookup_key = wh_key if wh_key else str(wh)

            if not inv_weekly.empty:
                if wh_key and "PlantKey" in inv_weekly.columns:
                    sub = inv_weekly[inv_weekly["PlantKey"] == wh_key].copy()
                else:
                    sub = inv_weekly[inv_weekly["Warehouse"] == wh].copy()
                exact = sub[sub["YearWeekIdx"] == first_idx]
                if not exact.empty:
                    baseline = float(exact["PhysicalStock"].iloc[0])
                else:
                    prior = sub[sub["YearWeekIdx"] <= first_idx].sort_values("YearWeekIdx")
                    if not prior.empty:
                        baseline = float(prior.iloc[-1]["PhysicalStock"])  # most recent available

            if baseline is None:
                baseline = float(start_map.get(lookup_key, 0))

            proj_vals = []
            prev = baseline
            for _, r in grp.iterrows():
                end = prev - float(r["Load_Total"]) + float(r["Unload_Total"])
                proj_vals.append(end)
                prev = end

            grp["Starting_Stock"] = None
            if len(grp) > 0:
                grp.loc[grp.index[0], "Starting_Stock"] = baseline
            grp["Projected_Stock"] = proj_vals
            results.append(grp)

        dfp = pd.concat(results, ignore_index=True) if results else pivot.copy()
        dfp["YearWeek"] = (
            dfp["Period_Year"].astype(str)
            + "-W"
            + dfp["Week_num"].astype(int).astype(str).str.zfill(2)
        )
        cols = [
            "Warehouse",
            "Period_Year",
            "Week_num",
            "YearWeek",
            "Starting_Stock",
            "Load_Loose",
            "Load_Pallet",
            "Load_Mixed",
            "Load_Total",
            "Unload_Loose",
            "Unload_Pallet",
            "Unload_Mixed",
            "Unload_Total",
            "Projected_Stock",
        ]
        existing = [c for c in cols if c in dfp.columns]
        return dfp[existing].copy()

    proj = build_projection(fdf, inv_weekly, st.session_state["start_stock_df"])

    # ---- DISPLAY ----
    if inv_weekly.empty:
        st.info(
            "No PhysicalStock found in the inventory file — projections start from the manual starting stock per plant."
        )
    else:
        st.caption(f"Inventory baseline source: {inv_note}")

    st.subheader("📄 Inventory Projection (week by week)")
    view_df = proj[proj["Warehouse"].isin(view_plants)].copy() if view_plants else proj.copy()
    view_df = view_df.sort_values(["Warehouse", "Period_Year", "Week_num"]) if not view_df.empty else view_df
    st.dataframe(view_df, use_container_width=True, height=450)

    c1, c2 = st.columns(2)
    with c1:
        st.download_button(
            "⬇️ Download projection (CSV)",
            df_to_csv_bytes(view_df),
            "inventory_projection_tw.csv",
            mime="text/csv",
            use_container_width=True,
        )
    with c2:
        x = df_to_excel_bytes(view_df, "Projection")
        if x:
            st.download_button(
                "⬇️ Download projection (Excel)",
                x,
                "inventory_projection_tw.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                use_container_width=True,
            )

    st.markdown("---")
    st.subheader("📈 Projected Stock over Time")
    if not view_df.empty:
        line = (
            alt.Chart(view_df)
            .mark_line(point=True)
            .encode(
                x=alt.X("YearWeek:N", sort=None),
                y="Projected_Stock:Q",
                color="Warehouse:N",
                tooltip=[
                    "Warehouse",
                    "YearWeek",
                    "Projected_Stock",
                    "Load_Total",
                    "Unload_Total",
                ],
            )
            .properties(height=420, width=1400)
        )
        st.altair_chart(line, use_container_width=True)

    st.markdown("---")
    st.subheader("📦 Load / Unload breakdown (select one plant)")
    if not proj.empty:
        pick = st.selectbox("Plant", sorted(proj["Warehouse"].unique()))
        pdf = proj[proj["Warehouse"] == pick].copy()
        if not pdf.empty:
            melt_cols = [
                "Load_Loose",
                "Load_Pallet",
                "Load_Mixed",
                "Unload_Loose",
                "Unload_Pallet",
                "Unload_Mixed",
            ]
            exist_melt_cols = [c for c in melt_cols if c in pdf.columns]
            if exist_melt_cols:
                long = pdf.melt(
                    id_vars=["YearWeek"],
                    value_vars=exist_melt_cols,
                    var_name="FlowType",
                    value_name="Qty",
                )
                load_bar = (
                    alt.Chart(long[long["FlowType"].str.startswith("Load")]).mark_bar()
                    .encode(
                        x=alt.X("YearWeek:N", sort=None),
                        y="Qty:Q",
                        color="FlowType:N",
                        tooltip=["YearWeek", "FlowType", "Qty"],
                    )
                    .properties(height=220, width=1400)
                )
                unload_bar = (
                    alt.Chart(long[long["FlowType"].str.startswith("Unload")]).mark_bar()
                    .encode(
                        x=alt.X("YearWeek:N", sort=None),
                        y="Qty:Q",
                        color="FlowType:N",
                        tooltip=["YearWeek", "FlowType", "Qty"],
                    )
                    .properties(height=220, width=1400)
                )
                st.altair_chart(load_bar, use_container_width=True)
                st.altair_chart(unload_bar, use_container_width=True)

# ------------------------------------------------------------
# MODULE 3 — PLANNING OVERVIEW BDD400 (Closing Stock time series)
# ------------------------------------------------------------

def _normalize_bdd0030(df: pd.DataFrame) -> pd.DataFrame:
    # Normalize common columns for 0030 BDD400: Warehouse/Plant, Period_Year, Week, ClosingStock
    df = df.copy()
    colmap = {}
    for c in df.columns:
        low = c.lower().strip().replace(" ", "").replace("_", "")
        if low in ("warehouse", "plant", "wh", "site"):
            colmap[c] = "Warehouse"
        elif low in ("periodyear", "year", "fiscalyear"):
            colmap[c] = "Period_Year"
        elif low in ("week", "wk", "periodweek"):
            colmap[c] = "Week"
        elif low in (
            "closingstock",
            "closingstockqty",
            "closinginventory",
            "closing",
            "stockclosing",
        ):
            colmap[c] = "ClosingStock"
    if colmap:
        df = df.rename(columns=colmap)

    # Clean numerics
    if "ClosingStock" in df.columns:
        df["ClosingStock"] = (
            df["ClosingStock"].astype(str).str.replace(" ", "", regex=False).str.replace(",", "", regex=False).str.strip()
        )
        df["ClosingStock"] = pd.to_numeric(df["ClosingStock"], errors="coerce").fillna(0)

    if "Week" in df.columns:
        df["Week"] = df["Week"].astype(str).str.strip()
        # extract week number if string like 'W07'
        df["Week_num"] = df["Week"].apply(lambda s: int(re.sub(r"[^\d]", "", s)) if re.search(r"\d+", s) else None)

    # Build YearWeek label
    if {"Period_Year", "Week_num"}.issubset(df.columns):
        df["YearWeek"] = df["Period_Year"].astype(str) + "-W" + df["Week_num"].astype(int).astype(str).str.zfill(2)

    return df


def run_planning_overview_bdd400():
    st.title("Planning Overview BDD400 — Closing Stock by Plant")

    b3 = get_bdd0030_df_from_state()
    if b3.empty:
        st.info("Please upload 0030BDD400.csv on Home.")
        return
    b3 = _normalize_bdd0030(b3)

    # Aggregate if duplicates exist per Warehouse/Year/Week
    if {"Warehouse", "Period_Year", "Week_num", "ClosingStock"}.issubset(b3.columns):
        agg = (
            b3.groupby(["Warehouse", "Period_Year", "Week_num"], dropna=True)["ClosingStock"].sum().reset_index()
        )
        agg["YearWeek"] = (
            agg["Period_Year"].astype(str)
            + "-W"
            + agg["Week_num"].astype(int).astype(str).str.zfill(2)
        )
    else:
        st.error(
            "0030BDD400 is missing required columns (Warehouse/Plant, Period_Year, Week, ClosingStock). Please check headers."
        )
        return

    plants = sorted(agg["Warehouse"].dropna().unique().tolist())
    st.sidebar.subheader("🔎 View Filters — BDD400")
    view_plants = st.sidebar.multiselect("Plants to display", plants, default=plants)

    view_df = agg[agg["Warehouse"].isin(view_plants)].copy() if view_plants else agg.copy()
    view_df = view_df.sort_values(["Warehouse", "Period_Year", "Week_num"])

    st.subheader("📄 Closing Stock (week by week)")
    st.dataframe(view_df, use_container_width=True, height=450)

    c1, c2 = st.columns(2)
    with c1:
        st.download_button(
            "⬇️ Download closing stock (CSV)",
            df_to_csv_bytes(view_df),
            "closingstock_bdd400.csv",
            mime="text/csv",
            use_container_width=True,
        )
    with c2:
        x = df_to_excel_bytes(view_df, "ClosingStock")
        if x:
            st.download_button(
                "⬇️ Download closing stock (Excel)",
                x,
                "closingstock_bdd400.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                use_container_width=True,
            )

    st.markdown("---")
    st.subheader("📈 Closing Stock over Time")
    if not view_df.empty:
        line = (
            alt.Chart(view_df)
            .mark_line(point=True)
            .encode(
                x=alt.X("YearWeek:N", sort=None),
                y="ClosingStock:Q",
                color="Warehouse:N",
                tooltip=["Warehouse", "YearWeek", "ClosingStock"],
            )
            .properties(height=420, width=1400)
        )
        st.altair_chart(line, use_container_width=True)

# ------------------------------------------------------------
# MODULE 4 — STORAGE CAPACITY MANAGEMENT
# ------------------------------------------------------------

def _normalize_capacity(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    colmap = {}
    for c in df.columns:
        low = c.lower().strip().replace(" ", "").replace("_", "")
        if low in ("warehouse", "plant", "wh", "site"):
            colmap[c] = "Warehouse"
        elif low in ("maxcapacity", "capacity", "maxcap", "plantcapacity", "storagecapacity"):
            colmap[c] = "MaxCapacity"
    if colmap:
        df = df.rename(columns=colmap)

    if "MaxCapacity" in df.columns:
        df["MaxCapacity"] = (
            df["MaxCapacity"].astype(str).str.replace(" ", "", regex=False).str.replace(",", "", regex=False).str.strip()
        )
        df["MaxCapacity"] = pd.to_numeric(df["MaxCapacity"], errors="coerce").fillna(0)
    return df


def run_storage_capacity():
    st.title("Storage Capacity Management")

    b3 = get_bdd0030_df_from_state()
    cap = get_plant_capacity_df_from_state()

    if b3.empty:
        st.info("Please upload 0030BDD400.csv on Home.")
        return

    if cap.empty:
        st.info("Please upload PlantCapacity.csv on Home.")
        return

    b3 = _normalize_bdd0030(b3)
    cap = _normalize_capacity(cap)

    # Aggregate closing stock per plant/week
    if {"Warehouse", "Period_Year", "Week_num", "ClosingStock"}.issubset(b3.columns):
        invw = (
            b3.groupby(["Warehouse", "Period_Year", "Week_num"], dropna=True)["ClosingStock"]
            .sum()
            .reset_index()
        )
        invw["YearWeek"] = (
            invw["Period_Year"].astype(str)
            + "-W"
            + invw["Week_num"].astype(int).astype(str).str.zfill(2)
        )
    else:
        st.error(
            "0030BDD400 is missing required columns (Warehouse/Plant, Period_Year, Week, ClosingStock). Please check headers."
        )
        return

    # >>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>
    # ENFORCE STANDARD MATCHING RULE: PlantKey = first 4 alphanumerics
    # >>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>
    if "Warehouse" not in cap.columns:
        st.error("PlantCapacity.csv must contain a plant/warehouse column.")
        return

    invw["PlantKey"] = derive_plant_key(invw["Warehouse"].astype(str))
    cap["PlantKey"] = derive_plant_key(cap["Warehouse"].astype(str))

    # Merge by PlantKey (not by raw Warehouse text)
    if {"PlantKey", "MaxCapacity"}.issubset(set(cap.columns)):
        merged = invw.merge(
            cap[["PlantKey", "MaxCapacity"]].drop_duplicates("PlantKey"),
            on="PlantKey",
            how="left",
        )
    else:
        st.error(
            "PlantCapacity.csv must contain columns Plant/ Warehouse (to derive PlantKey) and MaxCapacity."
        )
        return

    merged["Capacity_Gap"] = merged["ClosingStock"] - merged["MaxCapacity"]
    merged["Status"] = merged["Capacity_Gap"].apply(
        lambda x: "Above" if x > 0 else ("At" if x == 0 else "Below")
    )

    # Sidebar filters
    plants = sorted(merged["Warehouse"].dropna().unique().tolist())
    st.sidebar.subheader("🔎 View Filters — Capacity")
    sel_plants = st.sidebar.multiselect("Plants to display", plants, default=plants)
    view = (
        merged[merged["Warehouse"].isin(sel_plants)].copy()
        if sel_plants
        else merged.copy()
    )

    # Default tab is the first one -> put Summary first
    tab_summary, tab_detail = st.tabs(["Over / Under Summary", "Detail"])

    with tab_summary:
        if view.empty:
            st.info("No data available for the current filter selection.")
        else:
            # Utilization (% of capacity) for thresholds
            v2 = view.copy()
            v2["UtilizationPct"] = (v2["ClosingStock"] / v2["MaxCapacity"]) * 100
            v2.loc[v2["MaxCapacity"] <= 0, "UtilizationPct"] = pd.NA
            v2["YearWeekIdx"] = v2["Period_Year"] * 100 + v2["Week_num"].astype(int)
            v2["Capacity_Gap"] = v2["ClosingStock"] - v2["MaxCapacity"]

            # Sort weeks chronologically
            week_order = (
                v2[["YearWeek", "YearWeekIdx"]]
                .drop_duplicates()
                .sort_values("YearWeekIdx")["YearWeek"]
                .tolist()
            )

            st.caption(
                "Color rules (Utilization = ClosingStock / MaxCapacity): "
                "🟩 < 95% | 🟨 95%–105% | 🟥 > 105%"
            )

            # Plant x Week table (values = Capacity_Gap; colors = UtilizationPct)
            util_pivot = (
                v2.pivot_table(
                    index="Warehouse",
                    columns="YearWeek",
                    values="UtilizationPct",
                    aggfunc="mean",
                )
                .reindex(columns=week_order)
            )
            gap_pivot = (
                v2.pivot_table(
                    index="Warehouse",
                    columns="YearWeek",
                    values="Capacity_Gap",
                    aggfunc="sum",
                )
                .reindex(columns=week_order)
            )

            def _util_style(val):
                if pd.isna(val):
                    return ""
                if val < 95:
                    return "background-color:#d9f2d9; color:#1b5e20;"
                if val <= 105:
                    return "background-color:#fff2cc; color:#7a5b00;"
                return "background-color:#f8d7da; color:#7f1d1d;"

            style_matrix = util_pivot.applymap(_util_style)
            styled_gap = (
                gap_pivot.style
                .format("{:+,.0f}")
                .apply(lambda _x: style_matrix, axis=None)
                .set_table_styles(
                    [{"selector": "th", "props": [("font-weight", "600"), ("background", "#f7f7f7")]}]
                )
            )

            st.subheader("🗓️ Utilization by Plant & Week")
            st.dataframe(styled_gap, use_container_width=True, height=520)

            # Show underlying data expanded by default
            with st.expander("Show data", expanded=True):
                st.dataframe(gap_pivot, use_container_width=True, height=420)

            st.markdown("---")

            # Summary by Week (all selected plants) — weighted by capacity
            week_sum = (
                v2.groupby(["YearWeek", "YearWeekIdx"], dropna=True)
                .agg(TotalClosingStock=("ClosingStock", "sum"), TotalCapacity=("MaxCapacity", "sum"))
                .reset_index()
                .sort_values("YearWeekIdx")
            )
            week_sum["UtilizationPct"] = (week_sum["TotalClosingStock"] / week_sum["TotalCapacity"]) * 100
            week_sum.loc[week_sum["TotalCapacity"] <= 0, "UtilizationPct"] = pd.NA

            week_disp = week_sum[["YearWeek", "TotalClosingStock", "TotalCapacity", "UtilizationPct"]].copy()

            def _row_style(row):
                v = row["UtilizationPct"]
                return [
                    "" if c != "UtilizationPct" else _util_style(v)
                    for c in row.index
                ]

            styled_week = (
                week_disp.style
                .format({"TotalClosingStock": "{:,.0f}", "TotalCapacity": "{:,.0f}", "UtilizationPct": "{:.0f}%"})
                .apply(_row_style, axis=1)
                .set_table_styles(
                    [{"selector": "th", "props": [("font-weight", "600"), ("background", "#f7f7f7")]}]
                )
            )

            st.subheader("📊 Utilization by Week (All Selected Plants)")
            st.dataframe(styled_week, use_container_width=True, height=420)

    with tab_detail:
        st.subheader("📄 Capacity Check by Plant & Week")
        st.dataframe(
            view.sort_values(["Warehouse", "Period_Year", "Week_num"]),
            use_container_width=True,
            height=450,
        )

        c1, c2 = st.columns(2)
        with c1:
            st.download_button(
                "⬇️ Download capacity check (CSV)",
                df_to_csv_bytes(view),
                "capacity_check.csv",
                mime="text/csv",
                use_container_width=True,
            )
        with c2:
            x = df_to_excel_bytes(view, "CapacityCheck")
            if x:
                st.download_button(
                    "⬇️ Download capacity check (Excel)",
                    x,
                    "capacity_check.xlsx",
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    use_container_width=True,
                )

        st.markdown("---")
        st.subheader("📈 Closing Stock vs Capacity (select one plant)")

        if not view.empty:
            pick = st.selectbox("Plant", sorted(view["Warehouse"].unique()))
            v = (
                view[view["Warehouse"] == pick]
                .sort_values(["Period_Year", "Week_num"])
                .copy()
            )

            if not v.empty:
                # Two-series line chart: ClosingStock and MaxCapacity
                v_long = pd.concat(
                    [
                        v.assign(Metric="ClosingStock", Value=v["ClosingStock"])[
                            ["YearWeek", "Metric", "Value"]
                        ],
                        v.assign(Metric="MaxCapacity", Value=v["MaxCapacity"])[
                            ["YearWeek", "Metric", "Value"]
                        ],
                    ]
                )
                line = (
                    alt.Chart(v_long)
                    .mark_line(point=True)
                    .encode(
                        x=alt.X("YearWeek:N", sort=None),
                        y="Value:Q",
                        color="Metric:N",
                        tooltip=["YearWeek", "Metric", "Value"],
                    )
                    .properties(height=420, width=1400)
                )
                st.altair_chart(line, use_container_width=True)

                st.markdown("---")
                st.subheader("🟥 Capacity Over/Under (bars)")
                bars = (
                    alt.Chart(v)
                    .mark_bar()
                    .encode(
                        x=alt.X("YearWeek:N", sort=None),
                        y="Capacity_Gap:Q",
                        color=alt.condition(
                            alt.datum.Capacity_Gap > 0,
                            alt.value("#d62728"),
                            alt.value("#2ca02c"),
                        ),
                        tooltip=[
                            "YearWeek",
                            "ClosingStock",
                            "MaxCapacity",
                            "Capacity_Gap",
                            "Status",
                        ],
                    )
                    .properties(height=260, width=1400)
                )
                st.altair_chart(bars, use_container_width=True)


# ------------------------------------------------------------
# HOME (ALL UPLOADERS LIVE HERE)
# ------------------------------------------------------------

def run_home():
    st.title("Welcome to the Supply Chain Management Dashboard")
    st.subheader("Upload data below, then use the sidebar to open a module.")

    c1, c2 = st.columns(2)
    with c1:
        st.markdown("### 📦 Inventory file for NPI")
        inv_file = st.file_uploader(
            "Upload inventory CSV (used by the NPI & Planning Overview baselines)",
            type="csv",
            key="home_inv",
        )
        if inv_file is not None:
            st.session_state["inventory_file_bytes"] = inv_file.getvalue()
            st.session_state["inventory_file_name"] = inv_file.name
            st.success(f"Inventory file loaded: {inv_file.name}")

        if st.session_state.get("inventory_file_name"):
            st.caption(f"Current inventory source: {st.session_state['inventory_file_name']}")
        elif os.path.exists(INVENTORY_DEFAULT):
            st.caption(f"Using default inventory: {INVENTORY_DEFAULT}")
        else:
            st.caption("No inventory available yet.")

        if st.button("Clear inventory upload"):
            for k in [
                "inventory_file_bytes",
                "inventory_file_name",
                "inventory_source_caption",
                "inventory_file_bytes_caption",
            ]:
                st.session_state.pop(k, None)
            st.experimental_rerun()

        st.markdown("### 🧑‍🏭 Plant Capacity file")
        cap_file = st.file_uploader(
            "Upload PlantCapacity.csv (used by Storage Capacity Management)",
            type="csv",
            key="home_cap",
        )
        if cap_file is not None:
            st.session_state["plantcap_file_bytes"] = cap_file.getvalue()
            st.session_state["plantcap_file_name"] = cap_file.name
            st.success(f"Plant capacity file loaded: {cap_file.name}")

        if st.session_state.get("plantcap_file_name"):
            st.caption(f"Current capacity source: {st.session_state['plantcap_file_name']}")
        elif os.path.exists(PLANTCAP_DEFAULT):
            st.caption(f"Using default capacity: {PLANTCAP_DEFAULT}")
        else:
            st.caption("No plant capacity available yet.")

        if st.button("Clear capacity upload"):
            for k in ["plantcap_file_bytes", "plantcap_file_name"]:
                st.session_state.pop(k, None)
            st.experimental_rerun()

    with c2:
        st.markdown("### 📈 T&W Forecast file for Planning Overview T&W")
        fc_file = st.file_uploader(
            "Upload TWforecasts.csv (used by Planning Overview T&W)",
            type="csv",
            key="home_fc",
        )
        if fc_file is not None:
            st.session_state["forecast_file_bytes"] = fc_file.getvalue()
            st.session_state["forecast_file_name"] = fc_file.name
            st.success(f"Forecast file loaded: {fc_file.name}")

        if st.session_state.get("forecast_file_name"):
            st.caption(f"Current forecast source: {st.session_state['forecast_file_name']}")
        elif os.path.exists(FORECAST_DEFAULT):
            st.caption(f"Using default forecast: {FORECAST_DEFAULT}")
        else:
            st.caption("No forecast available yet.")

        if st.button("Clear forecast upload"):
            for k in [
                "forecast_file_bytes",
                "forecast_file_name",
                "forecast_source_caption",
                "forecast_file_bytes_caption",
            ]:
                st.session_state.pop(k, None)
            st.experimental_rerun()

        st.markdown("### 🧾 BDD400 input files")
        bdd000_file = st.file_uploader("Upload 000BDD400.csv (optional)", type="csv", key="home_bdd000")
        if bdd000_file is not None:
            st.session_state["bdd000_file_bytes"] = bdd000_file.getvalue()
            st.session_state["bdd000_file_name"] = bdd000_file.name
            st.success(f"BDD000 file loaded: {bdd000_file.name}")

        if st.session_state.get("bdd000_file_name"):
            st.caption(f"Current BDD000 source: {st.session_state['bdd000_file_name']}")
        elif os.path.exists(BDD000_DEFAULT):
            st.caption(f"Using default BDD000: {BDD000_DEFAULT}")

        bdd0030_file = st.file_uploader("Upload 0030BDD400.csv", type="csv", key="home_bdd0030")
        if bdd0030_file is not None:
            st.session_state["bdd0030_file_bytes"] = bdd0030_file.getvalue()
            st.session_state["bdd0030_file_name"] = bdd0030_file.name
            st.success(f"BDD0030 file loaded: {bdd0030_file.name}")

        if st.session_state.get("bdd0030_file_name"):
            st.caption(f"Current BDD0030 source: {st.session_state['bdd0030_file_name']}")
        elif os.path.exists(BDD0030_DEFAULT):
            st.caption(f"Using default BDD0030: {BDD0030_DEFAULT}")

        c_clear1, c_clear2 = st.columns(2)
        with c_clear1:
            if st.button("Clear BDD000 upload"):
                for k in ["bdd000_file_bytes", "bdd000_file_name"]:
                    st.session_state.pop(k, None)
                st.experimental_rerun()
        with c_clear2:
            if st.button("Clear BDD0030 upload"):
                for k in ["bdd0030_file_bytes", "bdd0030_file_name"]:
                    st.session_state.pop(k, None)
                st.experimental_rerun()

    st.markdown("---")
    st.markdown(
        """
        ### Modules
        - **Non-Productive Inventory Management** — Explore non-productive stock, with **Last Zero Date = most recent zero**.
        - **Planning Overview T&W** — Week-by-week projections driven by T&W flows. If a week has no PhysicalStock, the baseline uses the **most recent available** PhysicalStock from the inventory file.
        - **Planning Overview BDD400** — Visualize weekly **ClosingStock** by plant from *0030BDD400.csv*.
        - **Storage Capacity Management** — Compare weekly **ClosingStock vs MaxCapacity** by plant, highlight over/under capacity.
        - **Mitigation proposal** *(coming soon)*
        """
    )

# ------------------------------------------------------------

# ------------------------------------------------------------
# MODULE 5 — MITIGATION PROPOSAL
# ------------------------------------------------------------
def run_mitigation_proposal():
    st.header("💡 Mitigation Proposal")
    st.info("Select a Plant and Period(s) to view SAP codes ranked by Confirmed PR to distribute.")

    # Load data
    try:
        df = read_csv_robust("0030BDD400.csv")
    except Exception as e:
        st.error(f"Error loading 0030BDD400.csv: {e}")
        return

    # 1. Plant Selection
    if 'PlantID' not in df.columns:
        st.error("Column 'PlantID' not found in the CSV.")
        return
    
    plant_list = sorted(df['PlantID'].unique().astype(str))
    selected_plant = st.selectbox("Select Plant ID", plant_list)

    # Filter data for the selected plant
    df_plant = df[df['PlantID'] == selected_plant]

    # 2. Period Selection
    if 'InternalTimeStamp' not in df.columns:
        st.error("Column 'InternalTimeStamp' not found in the CSV.")
        return
        
    # Get sorted list of periods available for this plant
    period_list = sorted(df_plant['InternalTimeStamp'].unique().astype(str))
    selected_periods = st.multiselect("Select Period(s)", period_list)

    if not selected_periods:
        st.warning("Please select at least one period.")
        return

    # Identify the "first period" in the user's selection
    sorted_selected = [p for p in period_list if p in selected_periods]
    first_period = sorted_selected[0]

    # 3. Extract Daysofcoverage and ClosingStock from the first selected period
    df_first = df_plant[df_plant['InternalTimeStamp'] == first_period][['SapCode', 'Daysofcoverage', 'ClosingStock']]
    df_first = df_first.drop_duplicates(subset=['SapCode'])

    # 4. Aggregation for the selected periods
    df_selected = df_plant[df_plant['InternalTimeStamp'].isin(selected_periods)]
    
    # Group by SapCode and MaterialDescription, summing the PR to distribute
    agg_df = df_selected.groupby(['SapCode', 'MaterialDescription'], as_index=False).agg({
        'ConfirmedPRtodistribute': 'sum'
    })

    # 5. Merge calculations with contextual data (DOC and Stock)
    result_df = pd.merge(agg_df, df_first, on='SapCode', how='left')

    # 6. Sorting descending by ConfirmedPRtodistribute
    result_df = result_df.sort_values(by='ConfirmedPRtodistribute', ascending=False)

    # 7. Display Results
    st.subheader(f"Mitigation Ranking for {selected_plant}")
    st.markdown(f"**Reference Period:** {first_period} (used for Days of Coverage and Closing Stock)")
    
    display_cols = ['SapCode', 'MaterialDescription', 'ConfirmedPRtodistribute', 'Daysofcoverage', 'ClosingStock']
    st.dataframe(result_df[display_cols], use_container_width=True)

    # Download button
    csv_bytes = result_df[display_cols].to_csv(index=False).encode('utf-8')
    st.download_button(
        label="⬇️ Download mitigation proposal (CSV)",
        data=csv_bytes,
        file_name=f"mitigation_proposal_{selected_plant}.csv",
        mime='text/csv',
    )

# NAVIGATION
# ------------------------------------------------------------

st.sidebar.title("📂 Application Sections")
mode = st.sidebar.radio(
    "Choose a section",
    [
        "Home",
        "Non-Productive Inventory Management",
        "Planning Overview T&W",
        "Planning Overview BDD400",
        "Storage Capacity Management",
        "Mitigation proposal",
    ],
)
if mode == "Home":
    run_home()
elif mode == "Non-Productive Inventory Management":
    run_npi_app()
elif mode == "Planning Overview T&W":
    run_planning_overview_tw()
elif mode == "Planning Overview BDD400":
    run_planning_overview_bdd400()
elif mode == "Storage Capacity Management":
    run_storage_capacity()
elif mode == "Mitigation proposal":
 run_mitigation_proposal()

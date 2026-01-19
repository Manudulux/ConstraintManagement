
import streamlit as st
import pandas as pd
import os
import altair as alt
from io import BytesIO

# ===========================================================
# PAGE CONFIG — large central area
# ===========================================================
st.set_page_config(
    page_title="Identifying non-productive inventory",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ===========================================================
# DROP-IN PATCH: Robust CSV reader + column normalization
# ===========================================================
def read_csv_robust(upload_or_path):
    """
    Tries several common delimiter/encoding combos so uploads
    with ';' or UTF-8 BOM don't silently fail.
    """
    attempts = [
        dict(sep=",", encoding=None),
        dict(sep=";", encoding=None),
        dict(sep=",", encoding="utf-8-sig"),
        dict(sep=";", encoding="utf-8-sig"),
    ]
    for opts in attempts:
        try:
            if hasattr(upload_or_path, "seek"):
                upload_or_path.seek(0)  # ensure fresh read for UploadedFile
            return pd.read_csv(upload_or_path, **opts)
        except Exception:
            continue
    # Last resort: let pandas guess
    if hasattr(upload_or_path, "seek"):
        upload_or_path.seek(0)
    return pd.read_csv(upload_or_path)

# Aliases to auto-fix header differences from various sources
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

def normalize_columns(df: pd.DataFrame) -> pd.DataFrame:
    ren = {}
    for c in df.columns:
        key = c.strip().lower()
        if key in COLUMN_ALIASES:
            ren[c] = COLUMN_ALIASES[key]
    if ren:
        df = df.rename(columns=ren)
    return df

# ===========================================================
# LOAD DATA with Fix #1 and Fix #2 (robust parsing)
# ===========================================================
def load_data(upload):
    """
    - If upload is None, loads default "StockHistorySample.csv".
    - Rewinds uploaded file before reading (Fix #1).
    - Robust CSV parsing (Drop-in).
    - Robust date & numeric cleaning (Fix #2).
    - Shows a data-source banner (file name, rows, period range).
    """
    if upload is None:
        path = "StockHistorySample.csv"
        if not os.path.exists(path):
            st.error("Default file StockHistorySample.csv not found. Please upload a CSV.")
            st.stop()
        df = read_csv_robust(path)
        src = f"Default file: {path}"
    else:
        upload.seek(0)  # critical for re-uploads
        df = read_csv_robust(upload)
        src = f"Uploaded file: {upload.name}"

    # Normalize headers if needed
    df = normalize_columns(df)

    # Date parsing (tolerant)
    if "Period" in df.columns:
        df["Period"] = pd.to_datetime(
            df["Period"], errors="coerce", infer_datetime_format=True, utc=False
        )

    # Numeric cleaning (tolerant to commas & NBSP)
    for col in ["QualityInspectionQty", "BlockedStockQty", "ReturnStockQty", "OveragedTireQty"]:
        if col in df.columns:
            df[col] = (
                df[col]
                .astype(str)
                .str.replace("\u00A0", "", regex=False)  # non-breaking space
                .str.replace(",", "", regex=False)       # thousand separators
                .str.strip()
            )
            df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0)

    # Source + time window banner
    if "Period" in df.columns:
        pmin = pd.to_datetime(df["Period"], errors="coerce").min()
        pmax = pd.to_datetime(df["Period"], errors="coerce").max()
        st.caption(
            f"✅ Data source → {src} | Rows: {len(df):,} | Period range: "
            f"{(pmin.date() if pd.notna(pmin) else 'n/a')} → {(pmax.date() if pd.notna(pmax) else 'n/a')}"
        )
    else:
        st.caption(f"✅ Data source → {src} | Rows: {len(df):,}")

    return df

# ===========================================================
# DOWNLOAD HELPERS
# ===========================================================
def df_to_csv_bytes(df: pd.DataFrame) -> bytes:
    return df.to_csv(index=False).encode("utf-8")

def df_to_excel_bytes(df: pd.DataFrame, sheet_name: str = "Sheet1") -> bytes:
    buf = BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as writer:
        df.to_excel(writer, index=False, sheet_name=sheet_name)
    buf.seek(0)
    return buf.getvalue()

# ===========================================================
# HELPERS
# ===========================================================
def compute_first_nonzero_date(hist_df: pd.DataFrame, qty_col: str):
    """
    Returns earliest Period with qty_col > 0 (your 'since we have inventory').
    If never > 0, returns None and caller handles fallback.
    """
    pos = hist_df.loc[hist_df[qty_col] > 0, "Period"]
    return pos.min() if not pos.empty else None

def build_summary(df: pd.DataFrame, qty_column: str) -> pd.DataFrame:
    """
    Latest-period snapshot by (SapCode, Warehouse) for the selected metric.
    - Shows only materials with qty > 0 in the latest period.
    - 'Last Zero Date' = first date where metric became > 0 (earliest non-zero).
    - If never > 0, falls back to dataset oldest period.
    """
    if "Period" not in df.columns:
        return pd.DataFrame(columns=[
            "SapCode", "MaterialDescription", "Warehouse", "Brand",
            "AB", "Hier2", "Hier4", "Quantity", "Last Zero Date", "Days Since Zero"
        ])

    latest_period = df["Period"].max()
    oldest_period = df["Period"].min()

    if pd.isna(latest_period) or pd.isna(oldest_period) or qty_column not in df.columns:
        return pd.DataFrame(columns=[
            "SapCode", "MaterialDescription", "Warehouse", "Brand",
            "AB", "Hier2", "Hier4", "Quantity", "Last Zero Date", "Days Since Zero"
        ])

    latest = df[df["Period"] == latest_period]
    latest = latest[latest[qty_column] > 0]  # only items with stock in this metric now
    if latest.empty:
        return pd.DataFrame(columns=[
            "SapCode", "MaterialDescription", "Warehouse", "Brand",
            "AB", "Hier2", "Hier4", "Quantity", "Last Zero Date", "Days Since Zero"
        ])

    results = []
    for (mat, wh), _ in latest.groupby(["SapCode", "Warehouse"]):
        hist = (
            df[(df["SapCode"] == mat) & (df["Warehouse"] == wh)]
            .sort_values("Period")
        )

        since_date = compute_first_nonzero_date(hist, qty_column)
        if since_date is None:
            since_date = oldest_period  # fallback if never > 0

        latest_row = hist.iloc[-1]
        qty_now = latest_row.get(qty_column, 0)

        results.append({
            "SapCode": mat,
            "MaterialDescription": latest_row.get("MaterialDescription", ""),
            "Warehouse": wh,
            "Brand": latest_row.get("Brand", ""),
            "AB": latest_row.get("AB", ""),
            "Hier2": latest_row.get("Hier2", ""),
            "Hier4": latest_row.get("Hier4", ""),
            "Quantity": qty_now,
            "Last Zero Date": since_date.date(),
            "Days Since Zero": (latest_period - since_date).days,
        })

    res = pd.DataFrame(results)
    return res.sort_values("Quantity", ascending=False) if not res.empty else res

def get_available_qty_cols(df: pd.DataFrame):
    """Return only the inventory type columns that exist in df."""
    candidates = ["QualityInspectionQty", "BlockedStockQty", "ReturnStockQty", "OveragedTireQty"]
    return [c for c in candidates if c in df.columns]

# === Styling: highlight high 'Days Since Zero' ================================
def style_days_since(df: pd.DataFrame, warn: int, high: int, critical: int) -> pd.io.formats.style.Styler:
    """
    Color-code the 'Days Since Zero' column with thresholds:
      - >= critical: light red
      - >= high:    light orange
      - >= warn:    light yellow
    """
    df = df.copy()
    col = "Days Since Zero"
    styles = pd.DataFrame("", index=df.index, columns=df.columns)

    def color_for(v):
        if pd.isna(v): return ""
        if v >= critical: return "background-color: #ffd6d6;"  # light red
        if v >= high:     return "background-color: #ffe6cc;"  # light orange
        if v >= warn:     return "background-color: #fff7bf;"  # light yellow
        return ""

    styles[col] = [color_for(v) for v in df[col]]
    # Slight emphasis for the Quantity column as well (optional)
    styles["Quantity"] = ["font-weight: 600;" for _ in df.index]
    styled = df.style.set_table_styles(
        [{"selector":"th","props":[("font-weight","600"),("background","#f7f7f7")]}]
    ).set_properties(**{"white-space": "nowrap"}).set_td_classes(styles)
    return styled

# ===========================================================
# UI — Title & File Upload (with auto-clear filters on file change)
# ===========================================================
st.title("Identifying non-productive inventory")

uploaded_file = st.file_uploader("Upload CSV (optional)", type="csv")

# Auto-clear filters when file changes
file_key = uploaded_file.name if uploaded_file is not None else "StockHistorySample.csv"
if "active_file_key" not in st.session_state:
    st.session_state.active_file_key = file_key
elif file_key != st.session_state.active_file_key:
    for k in ["Warehouse", "Hier2", "Hier4", "AB", "Brand"]:
        st.session_state.pop(k, None)
    st.session_state.active_file_key = file_key
    st.toast(f"Filters cleared for new file: {file_key}")

df = load_data(uploaded_file)

# ===========================================================
# SIDEBAR FILTERS + manual reset button + thresholds
# ===========================================================
st.sidebar.header("Filters")

def _opts(series):
    return sorted(pd.Series(series).dropna().unique().tolist())

warehouse_sel = st.sidebar.multiselect("Warehouse", _opts(df.get("Warehouse", [])))
hier2_sel     = st.sidebar.multiselect("Hier2", _opts(df.get("Hier2", [])))
hier4_sel     = st.sidebar.multiselect("Hier4", _opts(df.get("Hier4", [])))
ab_sel        = st.sidebar.multiselect("AB", _opts(df.get("AB", [])))
brand_sel     = st.sidebar.multiselect("Brand", _opts(df.get("Brand", [])))

with st.sidebar.expander("Highlight thresholds", expanded=False):
    warn_threshold     = st.number_input("Warn (days)",     min_value=0, value=30, step=5)
    high_threshold     = st.number_input("High (days)",     min_value=0, value=60, step=5)
    critical_threshold = st.number_input("Critical (days)", min_value=0, value=90, step=5)
    st.caption("Rows with higher 'Days Since Zero' get stronger coloring.")

with st.sidebar:
    if st.button("🧹 Clear all filters"):
        for k in ["Warehouse", "Hier2", "Hier4", "AB", "Brand"]:
            st.session_state.pop(k, None)
        st.rerun()

# Apply filters
filtered = df.copy()
if warehouse_sel:
    filtered = filtered[filtered["Warehouse"].isin(warehouse_sel)]
if hier2_sel:
    filtered = filtered[filtered["Hier2"].isin(hier2_sel)]
if hier4_sel:
    filtered = filtered[filtered["Hier4"].isin(hier4_sel)]
if ab_sel:
    filtered = filtered[filtered["AB"].isin(ab_sel)]
if brand_sel:
    filtered = filtered[filtered["Brand"].isin(brand_sel)]

# ===========================================================
# TABS
#   First: "Overview"
#   Then the four metric-specific tabs
# ===========================================================
overview_tab, qi_tab, bs_tab, rs_tab, oa_tab = st.tabs([
    "Overview",
    "Quality Inspection Qty",
    "Blocked Stock Qty",
    "Return Stock Qty",
    "Overaged Inventory",
])

qty_cols = ["QualityInspectionQty", "BlockedStockQty", "ReturnStockQty", "OveragedTireQty"]

# ===========================================================
# OVERVIEW TAB
#   1) Totals over time (line chart) + downloads
#   2) Totals by plant (Warehouse) for the latest period (stacked bar + table) + downloads
# ===========================================================
with overview_tab:
    st.subheader("📈 Total non-productive inventory over time")

    if "Period" not in filtered.columns:
        st.warning("No 'Period' column found in the dataset.")
    else:
        available_cols = get_available_qty_cols(filtered)
        if not available_cols:
            st.warning("No inventory quantity columns found to chart.")
        else:
            # Totals over time
            totals_over_time = (
                filtered
                .groupby("Period")[available_cols]
                .sum(min_count=1)
                .reset_index()
                .sort_values("Period")
            )

            # Melt for multi-line Altair chart
            long_time = totals_over_time.melt(
                id_vars="Period", value_vars=available_cols,
                var_name="InventoryType", value_name="Quantity"
            )

            line = (
                alt.Chart(long_time)
                .mark_line(point=True)
                .encode(
                    x=alt.X("Period:T", title="Period"),
                    y=alt.Y("Quantity:Q", title="Quantity"),
                    color=alt.Color("InventoryType:N", title="Inventory Type"),
                    tooltip=["Period:T", "InventoryType:N", "Quantity:Q"]
                )
                .properties(height=420, width=1400)
            )
            st.altair_chart(line, use_container_width=True)

            # Downloads: totals over time
            c1, c2 = st.columns(2)
            with c1:
                st.download_button(
                    "⬇️ Download totals-over-time (CSV)",
                    data=df_to_csv_bytes(totals_over_time),
                    file_name="totals_over_time.csv",
                    mime="text/csv",
                    use_container_width=True,
                )
            with c2:
                st.download_button(
                    "⬇️ Download totals-over-time (Excel)",
                    data=df_to_excel_bytes(totals_over_time, "TotalsOverTime"),
                    file_name="totals_over_time.xlsx",
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    use_container_width=True,
                )

            st.markdown("---")
            st.subheader("🏭 Totals by plant (latest period)")

            latest_period = filtered["Period"].max()
            if pd.isna(latest_period):
                st.warning("Could not detect a valid latest period.")
            else:
                latest_slice = filtered[filtered["Period"] == latest_period].copy()

                if "Warehouse" not in latest_slice.columns:
                    latest_slice["Warehouse"] = "Unknown"

                by_plant = (
                    latest_slice
                    .groupby("Warehouse")[available_cols]
                    .sum(min_count=1)
                    .reset_index()
                )

                # Show as stacked bar (Warehouse on X, stacked by InventoryType)
                long_plant = by_plant.melt(
                    id_vars="Warehouse", value_vars=available_cols,
                    var_name="InventoryType", value_name="Quantity"
                )

                bar = (
                    alt.Chart(long_plant)
                    .mark_bar()
                    .encode(
                        x=alt.X("Warehouse:N", title="Plant"),
                        y=alt.Y("Quantity:Q", title="Quantity"),
                        color=alt.Color("InventoryType:N", title="Inventory Type"),
                        tooltip=["Warehouse:N", "InventoryType:N", "Quantity:Q"]
                    )
                    .properties(height=420, width=1400)
                )
                st.altair_chart(bar, use_container_width=True)

                st.write(f"**Latest period:** {latest_period.date()}")

                # Show table + downloads
                st.dataframe(by_plant, use_container_width=True, height=380)

                c3, c4 = st.columns(2)
                with c3:
                    st.download_button(
                        "⬇️ Download totals-by-plant (CSV)",
                        data=df_to_csv_bytes(by_plant),
                        file_name="totals_by_plant_latest_period.csv",
                        mime="text/csv",
                        use_container_width=True,
                    )
                with c4:
                    st.download_button(
                        "⬇️ Download totals-by-plant (Excel)",
                        data=df_to_excel_bytes(by_plant, "TotalsByPlant_Latest"),
                        file_name="totals_by_plant_latest_period.xlsx",
                        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                        use_container_width=True,
                    )

# ===========================================================
# METRIC TABS — Shared renderer
#   - Highlight high 'Days Since Zero'
#   - Download buttons for highlighted summary & selected history
# ===========================================================
def render_metric_tab(container, df_filt, qty_col, title, key_suffix):
    with container:
        st.subheader(f"📌 {title} — Latest Period Overview")

        summary_df = build_summary(df_filt, qty_col)
        if summary_df.empty:
            st.warning("No data available for the selected filters / metric.")
            return

        # === Highlighted summary (Styler) ===
        # Legend
        st.caption(
            f"Color legend — {warn_threshold}+ days: light yellow, "
            f"{high_threshold}+ days: light orange, "
            f"{critical_threshold}+ days: light red."
        )
        styled = style_days_since(summary_df, warn_threshold, high_threshold, critical_threshold)
        st.dataframe(styled, use_container_width=True, height=500)

        # Download highlighted summary
        col_a, col_b = st.columns(2)
        with col_a:
            st.download_button(
                "⬇️ Download summary (CSV)",
                data=df_to_csv_bytes(summary_df),
                file_name=f"{qty_col.lower()}_summary.csv",
                mime="text/csv",
                use_container_width=True,
                key=f"dl_csv_summary_{key_suffix}",
            )
        with col_b:
            st.download_button(
                "⬇️ Download summary (Excel)",
                data=df_to_excel_bytes(summary_df, f"{qty_col}_Summary"),
                file_name=f"{qty_col.lower()}_summary.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                use_container_width=True,
                key=f"dl_xlsx_summary_{key_suffix}",
            )

        st.markdown("---")
        st.subheader("🔎 Select a material to view full history")

        # Selection widget
        summary_df["_option"] = (
            summary_df["SapCode"].astype(str)
            + " | " + summary_df["Warehouse"].astype(str)
            + " | Qty: " + summary_df["Quantity"].astype(int).astype(str)
            + " | Days: " + summary_df["Days Since Zero"].astype(int).astype(str)
        )
        pick = st.selectbox(
            "Material / Warehouse",
            options=summary_df["_option"].tolist(),
            index=0,
            key=f"select_{key_suffix}",
        )
        sel_row = summary_df.loc[summary_df["_option"] == pick].iloc[0]
        mat = sel_row["SapCode"]
        wh  = sel_row["Warehouse"]

        history = (
            df_filt[(df_filt["SapCode"] == mat) &
                    (df_filt["Warehouse"] == wh)]
            .sort_values("Period")
        )

        st.write("### 📄 Full History Table")
        st.dataframe(history, use_container_width=True, height=450)

        # Download history
        col_c, col_d = st.columns(2)
        with col_c:
            st.download_button(
                "⬇️ Download history (CSV)",
                data=df_to_csv_bytes(history),
                file_name=f"{qty_col.lower()}_{mat}_{wh}_history.csv",
                mime="text/csv",
                use_container_width=True,
                key=f"dl_csv_hist_{key_suffix}",
            )
        with col_d:
            st.download_button(
                "⬇️ Download history (Excel)",
                data=df_to_excel_bytes(history, f"{qty_col}_History"),
                file_name=f"{qty_col.lower()}_{mat}_{wh}_history.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                use_container_width=True,
                key=f"dl_xlsx_hist_{key_suffix}",
            )

        st.write("### 📊 Quantity Over Time")
        if qty_col in history.columns and "Period" in history.columns:
            chart = (
                alt.Chart(history)
                .mark_line(point=True)
                .encode(
                    x=alt.X("Period:T", title="Period"),
                    y=alt.Y(f"{qty_col}:Q", title="Quantity"),
                    tooltip=["Period", qty_col],
                )
                .properties(height=450, width=1400)
            )
            st.altair_chart(chart, use_container_width=True)
        else:
            st.info(f"Column '{qty_col}' or 'Period' not found in history for this selection.")

# Render each metric tab
render_metric_tab(qi_tab, filtered, "QualityInspectionQty", "Quality Inspection Qty", "qi")
render_metric_tab(bs_tab, filtered, "BlockedStockQty", "Blocked Stock Qty", "bs")
render_metric_tab(rs_tab, filtered, "ReturnStockQty", "Return Stock Qty", "rs")
render_metric_tab(oa_tab, filtered, "OveragedTireQty", "Overaged Inventory", "oa")

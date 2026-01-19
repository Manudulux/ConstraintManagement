
import streamlit as st
import pandas as pd
import os
import altair as alt

# ===========================================================
# PAGE CONFIG — large central area
# ===========================================================
st.set_page_config(
    page_title="Inventory Quality Dashboard",
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
                upload_or_path.seek(0)  # <-- Fix #1 (part): ensure fresh read
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
        upload.seek(0)  # <-- Fix #1: critical for re-uploads
        df = read_csv_robust(upload)
        src = f"Uploaded file: {upload.name}"

    # Normalize headers if needed
    df = normalize_columns(df)

    # Date parsing (Fix #2 - tolerant)
    if "Period" in df.columns:
        df["Period"] = pd.to_datetime(
            df["Period"], errors="coerce", infer_datetime_format=True, utc=False
        )

    # Numeric cleaning (Fix #2 - tolerant to commas & NBSP)
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

# ===========================================================
# UI — Title & File Upload (with auto-clear filters on file change)
# ===========================================================
st.title("📦 Inventory Quality / Blocked / Return / Overaged Analyzer")

uploaded_file = st.file_uploader("Upload CSV (optional)", type="csv")

# Auto-clear filters when file changes (Drop-in patch behavior)
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
# SIDEBAR FILTERS + manual reset button
# ===========================================================
st.sidebar.header("Filters")

# Build options (drop NA so the UI stays clean)
def _opts(series):
    return sorted(pd.Series(series).dropna().unique().tolist())

warehouse_sel = st.sidebar.multiselect("Warehouse", _opts(df.get("Warehouse", [])))
hier2_sel     = st.sidebar.multiselect("Hier2", _opts(df.get("Hier2", [])))
hier4_sel     = st.sidebar.multiselect("Hier4", _opts(df.get("Hier4", [])))
ab_sel        = st.sidebar.multiselect("AB", _opts(df.get("AB", [])))
brand_sel     = st.sidebar.multiselect("Brand", _opts(df.get("Brand", [])))

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
# TABS (4 metrics)
# ===========================================================
tabs = st.tabs([
    "Quality Inspection Qty",
    "Blocked Stock Qty",
    "Return Stock Qty",
    "Overaged Inventory",
])

qty_cols = [
    "QualityInspectionQty",
    "BlockedStockQty",
    "ReturnStockQty",
    "OveragedTireQty",
]

# ===========================================================
# RENDER TABS
# ===========================================================
for tab, qty_col in zip(tabs, qty_cols):
    with tab:
        st.subheader(f"📌 {qty_col} — Latest Period Overview")

        summary_df = build_summary(filtered, qty_col)
        if summary_df.empty:
            st.warning("No data available for the selected filters / metric.")
            continue

        # Clickable table via data_editor selection column
        display_df = summary_df.copy()
        display_df["Select"] = False

        picked = st.data_editor(
            display_df,
            use_container_width=True,
            hide_index=True,
            height=700,
            column_config={
                "Select": st.column_config.CheckboxColumn(required=False)
            },
        )

        chosen = picked[picked["Select"] == True]
        if len(chosen) == 1:
            st.markdown("---")
            st.subheader("🔍 Full History for Selected Material")

            mat = chosen.iloc[0]["SapCode"]
            wh = chosen.iloc[0]["Warehouse"]

            history = (
                filtered[(filtered["SapCode"] == mat) &
                         (filtered["Warehouse"] == wh)]
                .sort_values("Period")
            )

            st.write("### 📄 Full History Table")
            st.dataframe(history, use_container_width=True, height=600)

            st.write("### 📊 Quantity Over Time")
            if qty_col in history.columns:
                chart = (
                    alt.Chart(history)
                    .mark_line(point=True)
                    .encode(
                        x=alt.X("Period:T", title="Period"),
                        y=alt.Y(f"{qty_col}:Q", title="Quantity"),
                        tooltip=["Period", qty_col],
                    )
                    .properties(height=500, width=1400)
                )
                st.altair_chart(chart, use_container_width=True)
            else:
                st.info(f"Column '{qty_col}' not found in history for this selection.")

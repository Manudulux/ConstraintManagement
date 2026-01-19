
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
                upload_or_path.seek(0)
            return pd.read_csv(upload_or_path, **opts)
        except Exception:
            continue

    if hasattr(upload_or_path, "seek"):
        upload_or_path.seek(0)
    return pd.read_csv(upload_or_path)

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
    return df


# ===========================================================
# LOAD DATA
# ===========================================================
def load_data(upload):
    if upload is None:
        path = "StockHistorySample.csv"
        if not os.path.exists(path):
            st.error("Default file StockHistorySample.csv not found.")
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
        minp = df["Period"].min()
        maxp = df["Period"].max()
        st.caption(f"📂 Source: {src} | Rows: {len(df):,} | Period range: {minp.date()} → {maxp.date()}")

    return df


# ===========================================================
# CSV / EXCEL DOWNLOAD HELPERS
# ===========================================================
def df_to_csv_bytes(df):
    return df.to_csv(index=False).encode("utf-8")

def df_to_excel_bytes(df, sheet_name="Sheet1"):
    # Try openpyxl
    try:
        buf = BytesIO()
        with pd.ExcelWriter(buf, engine="openpyxl") as w:
            df.to_excel(w, index=False, sheet_name=sheet_name)
        buf.seek(0)
        return buf.getvalue()
    except Exception:
        pass

    # fallback: xlsxwriter
    try:
        buf = BytesIO()
        with pd.ExcelWriter(buf, engine="xlsxwriter") as w:
            df.to_excel(w, index=False, sheet_name=sheet_name)
        buf.seek(0)
        return buf.getvalue()
    except Exception:
        return None


# ===========================================================
# LOGIC FIX — "MOST RECENT ZERO DATE"
# ===========================================================
def compute_last_zero_date(hist_df, qty_col):
    """
    Returns the MOST RECENT period where qty == 0.
    If never zero, return None and fallback to oldest period in caller.
    """
    z = hist_df.loc[hist_df[qty_col] == 0, "Period"]
    return z.max() if not z.empty else None


# ===========================================================
# BUILD SUMMARY TABLE
# ===========================================================
def build_summary(df, qty_col):
    if "Period" not in df.columns:
        return pd.DataFrame()

    latest_period = df["Period"].max()
    oldest_period = df["Period"].min()

    if pd.isna(latest_period):
        return pd.DataFrame()

    if qty_col not in df.columns:
        return pd.DataFrame()

    latest = df[df["Period"] == latest_period]
    latest = latest[latest[qty_col] > 0]

    if latest.empty:
        return pd.DataFrame(columns=[
            "SapCode","MaterialDescription","Warehouse","Brand","AB","Hier2","Hier4",
            "Quantity","Last Zero Date","Days Since Zero"
        ])

    rows = []
    for (mat, wh), _ in latest.groupby(["SapCode","Warehouse"]):
        hist = df[(df["SapCode"]==mat)&(df["Warehouse"]==wh)].sort_values("Period")

        last_zero = compute_last_zero_date(hist, qty_col)
        if last_zero is None:
            last_zero = oldest_period

        latest_row = hist.iloc[-1]

        rows.append({
            "SapCode": mat,
            "MaterialDescription": latest_row.get("MaterialDescription",""),
            "Warehouse": wh,
            "Brand": latest_row.get("Brand",""),
            "AB": latest_row.get("AB",""),
            "Hier2": latest_row.get("Hier2",""),
            "Hier4": latest_row.get("Hier4",""),
            "Quantity": latest_row.get(qty_col,0),
            "Last Zero Date": last_zero.date(),
            "Days Since Zero": (latest_period - last_zero).days
        })

    out = pd.DataFrame(rows)
    return out.sort_values("Quantity", ascending=False)


# ===========================================================
# HIGHLIGHTER
# ===========================================================
def style_days_since(df, warn, high, critical):
    def fmt(v):
        if pd.isna(v): return ""
        if v >= critical: return "background-color:#ffd6d6;"
        if v >= high:     return "background-color:#ffe6cc;"
        if v >= warn:     return "background-color:#fff7bf;"
        return ""

    def color_col(series):
        return [fmt(v) for v in series]

    return (
        df.style
        .apply(color_col, subset=["Days Since Zero"], axis=0)
        .set_properties(subset=["Quantity"], **{"font-weight":"600"})
        .set_table_styles([{"selector":"th","props":[("font-weight","600"),("background","#f7f7f7")]}])
    )


# ===========================================================
# SIDEBAR — FILE UPLOAD + FILTERS
# ===========================================================
st.sidebar.header("Data & Filters")

uploaded_file = st.sidebar.file_uploader("Upload CSV (optional)", type="csv")

file_key = uploaded_file.name if uploaded_file else "StockHistorySample.csv"
if "active_file_key" not in st.session_state:
    st.session_state.active_file_key = file_key
elif file_key != st.session_state.active_file_key:
    for k in ["Warehouse","Hier2","Hier4","AB","Brand"]:
        st.session_state.pop(k, None)
    st.session_state.active_file_key = file_key
    st.toast("Filters reset (new file loaded).")

df = load_data(uploaded_file)

def _opts(s):
    return sorted(pd.Series(s).dropna().unique().tolist())

warehouse_sel = st.sidebar.multiselect("Warehouse", _opts(df.get("Warehouse",[])))
hier2_sel     = st.sidebar.multiselect("Hier2", _opts(df.get("Hier2",[])))
hier4_sel     = st.sidebar.multiselect("Hier4", _opts(df.get("Hier4",[])))
ab_sel        = st.sidebar.multiselect("AB", _opts(df.get("AB",[])))
brand_sel     = st.sidebar.multiselect("Brand", _opts(df.get("Brand",[])))

with st.sidebar.expander("Highlight thresholds"):
    warn_threshold     = st.number_input("Warn (days)",     0, value=30)
    high_threshold     = st.number_input("High (days)",     0, value=60)
    critical_threshold = st.number_input("Critical (days)", 0, value=90)

if st.sidebar.button("🧹 Clear all filters"):
    for k in ["Warehouse","Hier2","Hier4","AB","Brand"]:
        st.session_state.pop(k, None)
    st.rerun()


# ===========================================================
# APPLY FILTERS
# ===========================================================
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
# MAIN TITLE
# ===========================================================
st.title("Identifying non-productive inventory")

# ===========================================================
# TABS
# ===========================================================
overview_tab, qi_tab, bs_tab, rs_tab, oa_tab = st.tabs([
    "Overview",
    "Quality Inspection Qty",
    "Blocked Stock Qty",
    "Return Stock Qty",
    "Overaged Inventory",
])


# ===========================================================
# OVERVIEW TAB
# ===========================================================
def get_available_qty_cols(df):
    cols = ["QualityInspectionQty","BlockedStockQty","ReturnStockQty","OveragedTireQty"]
    return [c for c in cols if c in df.columns]


with overview_tab:
    st.subheader("📈 Total non-productive inventory over time (filtered)")

    if "Period" in filtered.columns:
        qty_cols = get_available_qty_cols(filtered)
        if qty_cols:
            totals_over_time = (
                filtered
                .groupby("Period")[qty_cols]
                .sum(min_count=1)
                .reset_index()
                .sort_values("Period")
            )

            long = totals_over_time.melt("Period", qty_cols, "InventoryType","Quantity")

            chart = (
                alt.Chart(long)
                .mark_line(point=True)
                .encode(
                    x="Period:T",
                    y="Quantity:Q",
                    color="InventoryType:N",
                    tooltip=["Period:T","InventoryType:N","Quantity:Q"]
                )
                .properties(height=420, width=1400)
            )
            st.altair_chart(chart, use_container_width=True)

            c1, c2 = st.columns(2)
            with c1:
                st.download_button(
                    "⬇️ Download totals-over-time (CSV)",
                    data=df_to_csv_bytes(totals_over_time),
                    file_name="totals_over_time.csv",
                    mime="text/csv"
                )
            with c2:
                xlsx = df_to_excel_bytes(totals_over_time, "TotalsOverTime")
                if xlsx:
                    st.download_button(
                        "⬇️ Download totals-over-time (Excel)",
                        data=xlsx,
                        file_name="totals_over_time.xlsx",
                        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
                    )

        st.markdown("---")
        st.subheader("🏭 Totals by plant (latest period)")

        latest_period = filtered["Period"].max()
        if pd.notna(latest_period):
            latest_slice = filtered[filtered["Period"] == latest_period].copy()

            if "Warehouse" not in latest_slice.columns:
                latest_slice["Warehouse"]="Unknown"

            qty_cols = get_available_qty_cols(filtered)
            if qty_cols:
                by_plant = (
                    latest_slice
                    .groupby("Warehouse")[qty_cols]
                    .sum(min_count=1)
                    .reset_index()
                )

                longp = by_plant.melt("Warehouse", qty_cols, "InventoryType","Quantity")

                bar = (
                    alt.Chart(longp)
                    .mark_bar()
                    .encode(
                        x="Warehouse:N",
                        y="Quantity:Q",
                        color="InventoryType:N",
                        tooltip=["Warehouse:N","InventoryType:N","Quantity:Q"]
                    )
                    .properties(height=420, width=1400)
                )
                st.altair_chart(bar, use_container_width=True)

                st.write(f"**Latest period:** {latest_period.date()}")
                st.dataframe(by_plant, use_container_width=True)

                c3, c4 = st.columns(2)
                with c3:
                    st.download_button(
                        "⬇️ Download totals-by-plant (CSV)",
                        data=df_to_csv_bytes(by_plant),
                        file_name="totals_by_plant_latest_period.csv",
                        mime="text/csv"
                    )
                with c4:
                    xlsx = df_to_excel_bytes(by_plant, "TotalsByPlant")
                    if xlsx:
                        st.download_button(
                            "⬇️ Download totals-by-plant (Excel)",
                            data=xlsx,
                            file_name="totals_by_plant_latest_period.xlsx",
                            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
                        )


# ===========================================================
# METRIC TAB RENDERER
# ===========================================================
def render_tab(container, df_filt, qty_col, title):
    with container:
        st.subheader(f"{title} — Latest Period Overview")

        summ = build_summary(df_filt, qty_col)
        if summ.empty:
            st.warning("No data available.")
            return

        st.caption(
            f"Highlighting: {warn_threshold}+ days (yellow), "
            f"{high_threshold}+ (orange), {critical_threshold}+ (red)."
        )

        styled = style_days_since(summ, warn_threshold, high_threshold, critical_threshold)
        st.dataframe(styled, use_container_width=True, height=500)

        c1,c2 = st.columns(2)
        with c1:
            st.download_button(
                "⬇️ Download summary (CSV)",
                data=df_to_csv_bytes(summ),
                file_name=f"{qty_col}_summary.csv",
                mime="text/csv"
            )
        with c2:
            xlsx = df_to_excel_bytes(summ, f"{qty_col}_Summary")
            if xlsx:
                st.download_button(
                    "⬇️ Download summary (Excel)",
                    data=xlsx,
                    file_name=f"{qty_col}_summary.xlsx",
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
                )

        st.markdown("---")
        st.subheader("🔍 Select a material")

        summ["_label"] = (
            summ["SapCode"].astype(str)
            +" | "+ summ["Warehouse"]
            +" | Qty "+ summ["Quantity"].astype(int).astype(str)
            +" | Days "+ summ["Days Since Zero"].astype(int).astype(str)
        )

        sel = st.selectbox("Material / Warehouse", summ["_label"].tolist())
        row = summ[summ["_label"]==sel].iloc[0]
        mat = row["SapCode"]
        wh  = row["Warehouse"]

        hist = df_filt[(df_filt["SapCode"]==mat)&(df_filt["Warehouse"]==wh)].sort_values("Period")

        st.write("### 📄 Full History")
        st.dataframe(hist, use_container_width=True, height=450)

        c3,c4 = st.columns(2)
        with c3:
            st.download_button(
                "⬇️ Download history (CSV)",
                data=df_to_csv_bytes(hist),
                file_name=f"{qty_col}_{mat}_{wh}_history.csv",
                mime="text/csv"
            )
        with c4:
            xlsx = df_to_excel_bytes(hist, f"{qty_col}_History")
            if xlsx:
                st.download_button(
                    "⬇️ Download history (Excel)",
                    data=xlsx,
                    file_name=f"{qty_col}_{mat}_{wh}_history.xlsx",
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
                )

        st.write("### 📊 Quantity Over Time")
        if "Period" in hist.columns and qty_col in hist.columns:
            chart = (
                alt.Chart(hist)
                .mark_line(point=True)
                .encode(
                    x="Period:T",
                    y=f"{qty_col}:Q",
                    tooltip=["Period",qty_col]
                )
                .properties(height=450, width=1400)
            )
            st.altair_chart(chart, use_container_width=True)


# ===========================================================
# RENDER EACH METRIC TAB
# ===========================================================
render_tab(qi_tab, filtered, "QualityInspectionQty", "Quality Inspection Qty")
render_tab(bs_tab, filtered, "BlockedStockQty", "Blocked Stock Qty")
render_tab(rs_tab, filtered, "ReturnStockQty", "Return Stock Qty")
render_tab(oa_tab, filtered, "OveragedTireQty", "Overaged Inventory")

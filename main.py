
import streamlit as st
import pandas as pd
import os
import altair as alt

# -----------------------------------------------------------
# PAGE CONFIG: MAXIMIZE CENTRAL SECTION
# -----------------------------------------------------------
st.set_page_config(
    page_title="Inventory Quality Dashboard",
    layout="wide",
    initial_sidebar_state="expanded",
)

# -----------------------------------------------------------
# LOAD DATA WITH NUMERIC CLEANING
# -----------------------------------------------------------
def load_data(upload):
    if upload is None:
        default_path = "StockHistorySample.csv"
        if os.path.exists(default_path):
            df = pd.read_csv(default_path)
        else:
            st.error("Default file StockHistorySample.csv not found. Upload a file.")
            st.stop()
    else:
        df = pd.read_csv(upload)

    # Ensure datetime
    df["Period"] = pd.to_datetime(df["Period"], errors="coerce")

    # Columns we might plot/filter on and need numeric
    qty_cols = [
        "QualityInspectionQty",
        "BlockedStockQty",
        "ReturnStockQty",
        "OveragedTireQty",
    ]
    for col in qty_cols:
        if col in df.columns:
            df[col] = (
                df[col]
                .astype(str)
                .str.replace(",", "", regex=False)
                .str.strip()
            )
            df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0)

    return df


# -----------------------------------------------------------
# HELPERS
# -----------------------------------------------------------
def compute_first_nonzero_date(hist_df: pd.DataFrame, qty_col: str):
    """Return earliest Period with qty_col > 0, or None if never >0."""
    pos = hist_df.loc[hist_df[qty_col] > 0, "Period"]
    return pos.min() if not pos.empty else None


# -----------------------------------------------------------
# SUMMARY BUILDER (latest period only)
# -----------------------------------------------------------
def build_summary(df: pd.DataFrame, qty_column: str) -> pd.DataFrame:
    # Identify time bounds
    latest_period = df["Period"].max()
    oldest_period = df["Period"].min()

    # If no dates, return empty structure
    if pd.isna(latest_period) or pd.isna(oldest_period):
        return pd.DataFrame(columns=[
            "SapCode", "MaterialDescription", "Warehouse", "Brand",
            "AB", "Hier2", "Hier4", "Quantity", "Last Zero Date", "Days Since Zero"
        ])

    # Look only at the latest period’s snapshot
    latest = df[df["Period"] == latest_period]

    # Keep only pairs with quantity > 0 in this metric at the latest period
    if qty_column not in latest.columns:
        # Metric column missing in data -> no rows
        return pd.DataFrame(columns=[
            "SapCode", "MaterialDescription", "Warehouse", "Brand",
            "AB", "Hier2", "Hier4", "Quantity", "Last Zero Date", "Days Since Zero"
        ])
    latest = latest[latest[qty_column] > 0]

    if latest.empty:
        return pd.DataFrame(columns=[
            "SapCode", "MaterialDescription", "Warehouse", "Brand",
            "AB", "Hier2", "Hier4", "Quantity", "Last Zero Date", "Days Since Zero"
        ])

    results = []
    # Material + Warehouse granularity (as requested)
    for (mat, wh), _ in latest.groupby(["SapCode", "Warehouse"]):
        # Full history for this pair
        hist = (
            df[(df["SapCode"] == mat) & (df["Warehouse"] == wh)]
            .sort_values("Period")
        )

        # Earliest date when qty became > 0 for THIS metric
        since_date = compute_first_nonzero_date(hist, qty_column)
        if since_date is None:
            # never positive -> fallback to oldest period
            since_date = oldest_period

        latest_row = hist.iloc[-1]
        quantity_latest = latest_row[qty_column] if qty_column in latest_row else 0

        results.append({
            "SapCode": mat,
            "MaterialDescription": latest_row.get("MaterialDescription", ""),
            "Warehouse": wh,
            "Brand": latest_row.get("Brand", ""),
            "AB": latest_row.get("AB", ""),
            "Hier2": latest_row.get("Hier2", ""),
            "Hier4": latest_row.get("Hier4", ""),
            "Quantity": quantity_latest,
            # Column label keeps the original wording you used
            "Last Zero Date": since_date.date(),
            "Days Since Zero": (latest_period - since_date).days,
        })

    df_result = pd.DataFrame(results)
    # Sort by decreasing quantity (as requested)
    return df_result.sort_values("Quantity", ascending=False) if not df_result.empty else df_result


# -----------------------------------------------------------
# APP TITLE
# -----------------------------------------------------------
st.title("📦 Inventory Quality / Blocked / Return / Overaged Analyzer")

uploaded_file = st.file_uploader("Upload CSV (optional)", type="csv")
df = load_data(uploaded_file)

# -----------------------------------------------------------
# SIDEBAR FILTERS
# -----------------------------------------------------------
st.sidebar.header("Filters")

filters = {
    "Warehouse": st.sidebar.multiselect("Warehouse", sorted(df["Warehouse"].dropna().unique())),
    "Hier2": st.sidebar.multiselect("Hier2", sorted(df["Hier2"].dropna().unique())),
    "Hier4": st.sidebar.multiselect("Hier4", sorted(df["Hier4"].dropna().unique())),
    "AB": st.sidebar.multiselect("AB", sorted(df["AB"].dropna().unique())),
    "Brand": st.sidebar.multiselect("Brand", sorted(df["Brand"].dropna().unique())),
}

filtered = df.copy()
for col, selected in filters.items():
    if selected:
        filtered = filtered[filtered[col].isin(selected)]

# -----------------------------------------------------------
# TABS (4 TOTAL)
# -----------------------------------------------------------
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

# -----------------------------------------------------------
# DISPLAY LOGIC PER TAB
# -----------------------------------------------------------
for tab, qty_col in zip(tabs, qty_cols):
    with tab:
        st.subheader(f"📌 {qty_col} — Latest Period Overview")

        summary_df = build_summary(filtered, qty_col)

        if summary_df.empty:
            st.warning("No data available for the selected filters.")
            continue

        # Add selection checkbox to enable 'click' behaviour
        df_display = summary_df.copy()
        df_display["Select"] = False

        selected = st.data_editor(
            df_display,
            use_container_width=True,
            hide_index=True,
            height=700,
            column_config={
                "Select": st.column_config.CheckboxColumn(required=False)
            },
        )

        selected_rows = selected[selected["Select"] == True]

        if len(selected_rows) == 1:
            st.markdown("---")
            st.subheader("🔍 Full History for Selected Material")

            mat = selected_rows.iloc[0]["SapCode"]
            wh = selected_rows.iloc[0]["Warehouse"]

            history = (
                filtered[(filtered["SapCode"] == mat) &
                         (filtered["Warehouse"] == wh)]
                .sort_values("Period")
            )

            st.write("### 📄 Full History Table")
            st.dataframe(history, use_container_width=True, height=600)

            st.write("### 📊 Quantity Over Time")

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

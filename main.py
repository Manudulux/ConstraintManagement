
import streamlit as st
import pandas as pd
import os
import altair as alt

# -----------------------------------------------------------
# PAGE CONFIG
# -----------------------------------------------------------
st.set_page_config(
    page_title="Inventory Quality Dashboard",
    layout="wide",
    initial_sidebar_state="expanded",
)

# -----------------------------------------------------------
# LOAD DATA WITH CLEANING
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

    df["Period"] = pd.to_datetime(df["Period"], errors="coerce")

    # Columns to numeric
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
# LAST ZERO DATE HELPER
# -----------------------------------------------------------
def compute_last_zero(df, col):
    df = df.sort_values("Period")
    zeros = df[df[col] == 0]["Period"]
    return zeros.max() if not zeros.empty else None


# -----------------------------------------------------------
# SUMMARY BUILDER (Latest Period Only)
# -----------------------------------------------------------
def build_summary(df, qty_column):
    latest_period = df["Period"].max()
    oldest_period = df["Period"].min()

    if latest_period is None:
        return pd.DataFrame(columns=[
            "SapCode", "MaterialDescription", "Warehouse", "Brand",
            "AB", "Hier2", "Hier4", "Quantity", "Last Zero Date", "Days Since Zero"
        ])

    latest = df[df["Period"] == latest_period]

    # Only > 0 values
    latest = latest[latest[qty_column] > 0]

    if latest.empty:
        return pd.DataFrame(columns=[
            "SapCode", "MaterialDescription", "Warehouse", "Brand",
            "AB", "Hier2", "Hier4", "Quantity", "Last Zero Date", "Days Since Zero"
        ])

    results = []

    for (mat, wh), _ in latest.groupby(["SapCode", "Warehouse"]):
        hist = (
            df[(df["SapCode"] == mat) &
               (df["Warehouse"] == wh)]
            .sort_values("Period")
        )

        last_zero = compute_last_zero(hist, qty_column)

        if last_zero is None:
            last_zero_date = oldest_period
            days_since_zero = (latest_period - oldest_period).days
        else:
            last_zero_date = last_zero
            days_since_zero = (latest_period - last_zero).days

        latest_row = hist.iloc[-1]

        results.append({
            "SapCode": mat,
            "MaterialDescription": latest_row["MaterialDescription"],
            "Warehouse": wh,
            "Brand": latest_row["Brand"],
            "AB": latest_row["AB"],
            "Hier2": latest_row["Hier2"],
            "Hier4": latest_row["Hier4"],
            "Quantity": latest_row[qty_column],
            "Last Zero Date": last_zero_date.date(),
            "Days Since Zero": days_since_zero
        })

    df_result = pd.DataFrame(results)

    if df_result.empty:
        return df_result

    return df_result.sort_values("Quantity", ascending=False)


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
    "Warehouse": st.sidebar.multiselect("Warehouse", sorted(df["Warehouse"].unique())),
    "Hier2": st.sidebar.multiselect("Hier2", sorted(df["Hier2"].unique())),
    "Hier4": st.sidebar.multiselect("Hier4", sorted(df["Hier4"].unique())),
    "AB": st.sidebar.multiselect("AB", sorted(df["AB"].unique())),
    "Brand": st.sidebar.multiselect("Brand", sorted(df["Brand"].unique())),
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

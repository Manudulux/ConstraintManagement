
import streamlit as st
import pandas as pd
import os
import altair as alt

# -----------------------------------------------------------
# CONFIGURATION — MAKE CENTRAL SECTION MUCH LARGER
# -----------------------------------------------------------
st.set_page_config(
    page_title="Inventory Quality Dashboard",
    layout="wide",                # << VERY LARGE CENTER SECTION
    initial_sidebar_state="expanded"
)

# -----------------------------------------------------------
# LOAD DATA
# -----------------------------------------------------------
def load_data(upload):
    if upload is None:
        default_path = "StockHistorySample.csv"
        if os.path.exists(default_path):
            df = pd.read_csv(default_path)
        else:
            st.error("Default file not found. Please upload a CSV.")
            st.stop()
    else:
        df = pd.read_csv(upload)

    df["Period"] = pd.to_datetime(df["Period"])

    # Ensure numeric quality fields (fixes your crash)
    qty_cols = ["QualityInspectionQty", "BlockedStockQty", "ReturnStockQty"]

    for col in qty_cols:
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
# BUILD SUMMARY — ONLY LATEST PERIOD
# -----------------------------------------------------------
def build_summary(df, qty_column):
    latest_period = df["Period"].max()
    latest = df[df["Period"] == latest_period]

    # Only materials with quantity > 0
    latest = latest[latest[qty_column] > 0]

    results = []
    for (mat, wh), group in latest.groupby(["SapCode", "Warehouse"]):
        hist = df[(df["SapCode"] == mat) & (df["Warehouse"] == wh)].sort_values("Period")
        last_zero = compute_last_zero(hist, qty_column)

        results.append({
            "SapCode": mat,
            "MaterialDescription": hist.iloc[-1]["MaterialDescription"],
            "Warehouse": wh,
            "Brand": hist.iloc[-1]["Brand"],
            "AB": hist.iloc[-1]["AB"],
            "Hier2": hist.iloc[-1]["Hier2"],
            "Hier4": hist.iloc[-1]["Hier4"],
            "Quantity": hist.iloc[-1][qty_column],
            "Last Zero Date": last_zero.date() if last_zero else None,
            "Days Since Zero": (hist.iloc[-1]["Period"] - last_zero).days if last_zero else None
        })

    df_result = pd.DataFrame(results)
    return df_result.sort_values("Quantity", ascending=False)


# -----------------------------------------------------------
# TITLE
# -----------------------------------------------------------
st.title("📦 Inventory Quality / Blocked / Return Stock Analyzer")

uploaded = st.file_uploader("Upload CSV (optional)", type="csv")
df = load_data(uploaded)

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
# TABS
# -----------------------------------------------------------
tabs = st.tabs(["Quality Inspection", "Blocked Stock", "Return Stock"])
qty_cols = ["QualityInspectionQty", "BlockedStockQty", "ReturnStockQty"]

# -----------------------------------------------------------
# LOOP THROUGH TABS
# -----------------------------------------------------------
for tab, qty_col in zip(tabs, qty_cols):
    with tab:
        st.subheader(f"📌 {qty_col} — Latest Period Overview")

        summary = build_summary(filtered, qty_col)

        # Create a selection column
        summary_display = summary.copy()
        summary_display["Select"] = False

        selected = st.data_editor(
            summary_display,
            use_container_width=True,   # << FULL WIDTH TABLE
            hide_index=True,
            height=650,                 # << TALLER CENTRAL SECTION
            column_config={
                "Select": st.column_config.CheckboxColumn(required=False)
            }
        )

        selected_rows = selected[selected["Select"] == True]

        if len(selected_rows) == 1:
            st.markdown("---")
            st.subheader("🔍 Full History for Selected Material")

            mat = selected_rows.iloc[0]["SapCode"]
            wh = selected_rows.iloc[0]["Warehouse"]

            hist = (
                filtered[(filtered["SapCode"] == mat) &
                         (filtered["Warehouse"] == wh)]
                .sort_values("Period")
            )

            st.write("### 📄 Full History Table")
            st.dataframe(hist, use_container_width=True, height=500)

            st.write("### 📊 Quantity Over Time")

            chart = (
                alt.Chart(hist)
                .mark_line(point=True)
                .encode(
                    x=alt.X("Period:T", title="Period"),
                    y=alt.Y(f"{qty_col}:Q", title="Quantity"),
                    tooltip=["Period", qty_col]
                )
                .properties(height=500, width=1200)   # << MUCH LARGER CHART
            )

            st.altair_chart(chart, use_container_width=True)

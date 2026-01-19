
import streamlit as st
import pandas as pd
import os
import altair as alt

# -----------------------------------
# Load Data
# -----------------------------------
def load_data(upload):
    if upload is None:
        default_path = "StockHistorySample.csv"
        if os.path.exists(default_path):
            df = pd.read_csv(default_path)
        else:
            st.error("Default file not found. Upload a CSV.")
            st.stop()
    else:
        df = pd.read_csv(upload)

    df["Period"] = pd.to_datetime(df["Period"])
    return df


# -----------------------------------
# Compute last zero date
# -----------------------------------
def compute_last_zero(df, col):
    df = df.sort_values("Period")
    zeros = df[df[col] == 0]["Period"]
    return zeros.max() if not zeros.empty else None


# -----------------------------------
# Build latest-period summary
# -----------------------------------
def build_summary(df, qty_column):
    latest_period = df["Period"].max()
    latest = df[df["Period"] == latest_period]

    # Only materials with non-zero quantity
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


# -----------------------------------
# UI
# -----------------------------------
st.title("📦 Inventory Quality / Blocked / Return Stock Analyzer")

uploaded_file = st.file_uploader("Upload CSV (optional)", type="csv")
df = load_data(uploaded_file)

# -----------------------------------
# Sidebar filters
# -----------------------------------
st.sidebar.header("Filters")

filters = {
    "Warehouse": st.sidebar.multiselect("Warehouse", sorted(df["Warehouse"].unique())),
    "Hier2": st.sidebar.multiselect("Hier2", sorted(df["Hier2"].unique())),
    "Hier4": st.sidebar.multiselect("Hier4", sorted(df["Hier4"].unique())),
    "AB": st.sidebar.multiselect("AB", sorted(df["AB"].unique())),
    "Brand": st.sidebar.multiselect("Brand", sorted(df["Brand"].unique())),
}

filtered = df.copy()
for col, sel in filters.items():
    if sel:
        filtered = filtered[filtered[col].isin(sel)]

# -----------------------------------
# Tabs
# -----------------------------------
tabs = st.tabs(["Quality Inspection", "Blocked Stock", "Return Stock"])
qty_columns = ["QualityInspectionQty", "BlockedStockQty", "ReturnStockQty"]

# -----------------------------------
# Display each tab
# -----------------------------------
for tab, qty_col in zip(tabs, qty_columns):
    with tab:
        st.subheader(f"{qty_col} – Latest Period Overview")

        summary_df = build_summary(filtered, qty_col)

        # Add selection column
        summary_df_display = summary_df.copy()
        summary_df_display["Select"] = False

        selected = st.data_editor(
            summary_df_display,
            use_container_width=True,
            hide_index=True,
            height=600,
            column_config={
                "Select": st.column_config.CheckboxColumn(required=False)
            }
        )

        # Get selected rows
        selected_rows = selected[selected["Select"] == True]

        if len(selected_rows) == 1:
            st.markdown("### 📈 Full History for Selected Material")

            mat = selected_rows.iloc[0]["SapCode"]
            wh = selected_rows.iloc[0]["Warehouse"]

            history = filtered[(filtered["SapCode"] == mat) &
                               (filtered["Warehouse"] == wh)].sort_values("Period")

            st.write("#### Complete History (Table)")
            st.dataframe(history, use_container_width=True)

            st.write("#### Quantity Over Time")
            chart = (
                alt.Chart(history)
                .mark_line(point=True)
                .encode(
                    x="Period:T",
                    y=qty_col + ":Q",
                    tooltip=["Period", qty_col]
                )
                .properties(height=400)
            )
            st.altair_chart(chart, use_container_width=True)

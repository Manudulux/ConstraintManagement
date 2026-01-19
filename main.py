
import streamlit as st
import pandas as pd
import os

# ---------------------------
# Load file function
# ---------------------------
def load_data(upload):
    if upload is None:
        # Default automatic loading
        default_path = "StockHistorySample.csv.csv"
        if os.path.exists(default_path):
            df = pd.read_csv(default_path)
        else:
            st.error("Default file not found. Please upload a file.")
            st.stop()
    else:
        df = pd.read_csv(upload)

    # Parse dates
    df["Period"] = pd.to_datetime(df["Period"])

    return df


# ---------------------------
# Compute “last zero date”
# ---------------------------
def compute_last_zero(df, qty_column):
    df = df.sort_values("Period")
    zero_dates = df[df[qty_column] == 0]["Period"]

    if len(zero_dates) == 0:
        return None
    return zero_dates.max()


# ---------------------------
# Streamlit App
# ---------------------------
st.title("📦 Inventory Quality / Blocked / Return Stock Analyzer")

uploaded_file = st.file_uploader("Upload CSV (optional)", type="csv")
df = load_data(uploaded_file)


# ---------------------------
# Sidebar Filters
# ---------------------------
st.sidebar.header("Filters")

warehouse_sel = st.sidebar.multiselect("Warehouse", sorted(df["Warehouse"].unique()))
hier2_sel = st.sidebar.multiselect("Hier2", sorted(df["Hier2"].unique()))
hier4_sel = st.sidebar.multiselect("Hier4", sorted(df["Hier4"].unique()))
ab_sel = st.sidebar.multiselect("AB", sorted(df["AB"].unique()))
brand_sel = st.sidebar.multiselect("Brand", sorted(df["Brand"].unique()))

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


# ---------------------------
# Compute metrics for each Material
# ---------------------------
materials = []

for material, group in filtered.groupby("SapCode"):
    group = group.sort_values("Period")
    latest = group.iloc[-1]

    result = {
        "SapCode": material,
        "MaterialDescription": latest["MaterialDescription"],
        "Latest Period": latest["Period"].date(),
        "Warehouse": latest["Warehouse"],
        "Brand": latest["Brand"],
        "AB": latest["AB"],
        "Hier2": latest["Hier2"],
        "Hier4": latest["Hier4"],

        # Quantities today
        "QualityInspectionQty": latest["QualityInspectionQty"],
        "BlockedStockQty": latest["BlockedStockQty"],
        "ReturnStockQty": latest["ReturnStockQty"],
    }

    # Compute “last zero” dates
    for col in ["QualityInspectionQty", "BlockedStockQty", "ReturnStockQty"]:
        last_zero = compute_last_zero(group, col)
        result[f"{col} – Last Zero Date"] = last_zero.date() if last_zero else None

        if last_zero:
            result[f"{col} – Days Since Zero"] = (latest["Period"] - last_zero).days
        else:
            result[f"{col} – Days Since Zero"] = None

    materials.append(result)

result_df = pd.DataFrame(materials)


# ---------------------------
# Display
# ---------------------------
st.subheader("Filtered Material Overview")
st.dataframe(result_df)

# Allow download
csv_download = result_df.to_csv(index=False).encode("utf-8")
st.download_button("Download Results as CSV", csv_download, "inventory_analysis.csv")

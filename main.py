
import streamlit as st
import pandas as pd
import os
import altair as alt
from io import BytesIO


# ===========================================================
# PAGE CONFIG
# ===========================================================
st.set_page_config(
    page_title="Inventory & Supply Chain Toolkit",
    layout="wide",
    initial_sidebar_state="expanded",
)


# ===========================================================
# TOP‑LEVEL NAVIGATION MENU — NEW
# ===========================================================
st.sidebar.title("📂 Application Sections")

app_mode = st.sidebar.radio(
    "Choose a section:",
    [
        "Home",
        "Non-Productive Inventory Management",
        "Planning Overview",
        "Storage Capacity Management",
        "Transportation Management",
    ]
)


# ===========================================================
# ==========  FULL NPI APPLICATION MOVED INTO FUNCTION  ======
# ===========================================================
def run_npi_app():

    # -------------------------------------------------------
    # ----------  ROBUST CSV LOADER + NORMALIZATION  --------
    # -------------------------------------------------------
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

    # -------------------------------------------------------
    # ----------            LOAD DATA                  -------
    # -------------------------------------------------------
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
            st.caption(f"📂 Source: {src} | Rows: {len(df)} | Periods: {minp.date()} → {maxp.date()}")

        return df

    # -------------------------------------------------------
    # ----------       DOWNLOAD HELPERS                -------
    # -------------------------------------------------------
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

    # -------------------------------------------------------
    # ---------- FIX: MOST RECENT ZERO DATE ---------
    # -------------------------------------------------------
    def compute_last_zero_date(hist_df, qty_col):
        z = hist_df.loc[hist_df[qty_col] == 0, "Period"]
        return z.max() if not z.empty else None

    # -------------------------------------------------------
    # ---------- Build Summary Table ------------------
    # -------------------------------------------------------
    def build_summary(df, qty_col):
        if "Period" not in df.columns: return pd.DataFrame()
        latest = df["Period"].max()
        first  = df["Period"].min()
        if qty_col not in df.columns: return pd.DataFrame()

        snap = df[df["Period"] == latest]
        snap = snap[snap[qty_col] > 0]
        if snap.empty: return pd.DataFrame()

        rows=[]
        for (mat,wh), _ in snap.groupby(["SapCode","Warehouse"]):
            hist = df[(df["SapCode"]==mat)&(df["Warehouse"]==wh)].sort_values("Period")

            last_zero = compute_last_zero_date(hist, qty_col)
            if last_zero is None:
                last_zero = first

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
                "Days Since Zero": (latest - last_zero).days,
            })

        out = pd.DataFrame(rows)
        return out.sort_values("Quantity", ascending=False)

    # -------------------------------------------------------
    # ---------- Highlighting Styling ------------------
    # -------------------------------------------------------
    def style_days_since(df, warn, high, critical):
        def style_val(v):
            if v >= critical: return "background-color:#ffd6d6;"
            if v >= high:     return "background-color:#ffe6cc;"
            if v >= warn:     return "background-color:#fff7bf;"
            return ""

        def color(series):
            return [style_val(v) for v in series]

        return (
            df.style
            .apply(color, subset=["Days Since Zero"], axis=0)
            .set_properties(subset=["Quantity"], **{"font-weight":"600"})
            .set_table_styles([{"selector":"th","props":[("font-weight","600"),("background","#f7f7f7")]}])
        )

    # -------------------------------------------------------
    # ---------- Sidebar Controls ----------------------
    # -------------------------------------------------------
    st.sidebar.subheader("📥 Upload Data")
    uploaded_file = st.sidebar.file_uploader("Upload CSV", type="csv")

    # reset filters if file changes
    file_key = uploaded_file.name if uploaded_file else "DEFAULT_FILE"
    if "active_file" not in st.session_state:
        st.session_state.active_file = file_key
    elif st.session_state.active_file != file_key:
        for k in ["Warehouse","Hier2","Hier4","AB","Brand"]:
            st.session_state.pop(k, None)
        st.session_state.active_file = file_key
        st.toast("Filters reset – new file loaded.")

    df = load_data(uploaded_file)

    def _opts(s):
        return sorted(pd.Series(s).dropna().unique().tolist())

    st.sidebar.subheader("📊 Filters")
    sel_wh  = st.sidebar.multiselect("Warehouse", _opts(df.get("Warehouse",[])))
    sel_h2  = st.sidebar.multiselect("Hier2",     _opts(df.get("Hier2",[])))
    sel_h4  = st.sidebar.multiselect("Hier4",     _opts(df.get("Hier4",[])))
    sel_ab  = st.sidebar.multiselect("AB",        _opts(df.get("AB",[])))
    sel_brd = st.sidebar.multiselect("Brand",     _opts(df.get("Brand",[])))

    with st.sidebar.expander("Highlight settings:"):
        warn  = st.number_input("Warn (days)", 0, value=30)
        high  = st.number_input("High (days)", 0, value=60)
        crit  = st.number_input("Critical (days)", 0, value=90)

    if st.sidebar.button("🧹 Reset filters"):
        for k in ["Warehouse","Hier2","Hier4","AB","Brand"]:
            st.session_state.pop(k, None)
        st.rerun()

    # -------------------------------------------------------
    # ---------- Filtering ------------------------------
    # -------------------------------------------------------
    data = df.copy()
    if sel_wh:  data = data[data["Warehouse"].isin(sel_wh)]
    if sel_h2:  data = data[data["Hier2"].isin(sel_h2)]
    if sel_h4:  data = data[data["Hier4"].isin(sel_h4)]
    if sel_ab:  data = data[data["AB"].isin(sel_ab)]
    if sel_brd: data = data[data["Brand"].isin(sel_brd)]

    # -------------------------------------------------------
    # ---------- Main Title -----------------------------
    # -------------------------------------------------------
    st.title("Non-Productive Inventory Management")

    # -------------------------------------------------------
    # ---------- Tabs ----------------------------------
    # -------------------------------------------------------
    tab1, tab2, tab3, tab4, tab5 = st.tabs([
        "Overview",
        "Quality Inspection Qty",
        "Blocked Stock Qty",
        "Return Stock Qty",
        "Overaged Inventory",
    ])

    # -------------------------------------------------------
    # ---------- Overview Tab ----------------------------
    # -------------------------------------------------------
    def get_qty_cols(df):
        cols = ["QualityInspectionQty","BlockedStockQty","ReturnStockQty","OveragedTireQty"]
        return [c for c in cols if c in df.columns]

    with tab1:
        st.subheader("📈 Total non-productive inventory over time (filtered)")
        if "Period" in data.columns:
            qty_cols = get_qty_cols(data)
            if qty_cols:
                tot = (
                    data.groupby("Period")[qty_cols]
                    .sum(min_count=1)
                    .reset_index()
                    .sort_values("Period")
                )
                long = tot.melt("Period", qty_cols, "InventoryType","Quantity")
                chart = (
                    alt.Chart(long)
                    .mark_line(point=True)
                    .encode(
                        x="Period:T",
                        y="Quantity:Q",
                        color="InventoryType:N",
                        tooltip=["Period:T","InventoryType:N","Quantity:Q"]
                    ).properties(height=420, width=1400)
                )
                st.altair_chart(chart, use_container_width=True)

                c1,c2 = st.columns(2)
                with c1:
                    st.download_button(
                        "⬇️ Download totals-over-time (CSV)",
                        df_to_csv_bytes(tot),
                        "totals_over_time.csv"
                    )
                with c2:
                    x = df_to_excel_bytes(tot,"Totals")
                    if x:
                        st.download_button(
                            "⬇️ Download totals-over-time (Excel)",
                            x,
                            "totals_over_time.xlsx"
                        )

        st.markdown("---")
        st.subheader("🏭 Totals by Plant (latest period)")
        if "Period" in data.columns:
            latest = data["Period"].max()
            slice = data[data["Period"]==latest]

            qty_cols = get_qty_cols(data)
            if qty_cols:
                byp = (
                    slice.groupby("Warehouse")[qty_cols]
                    .sum(min_count=1)
                    .reset_index()
                )
                long = byp.melt("Warehouse", qty_cols, "InventoryType","Quantity")
                bar = (
                    alt.Chart(long)
                    .mark_bar()
                    .encode(
                        x="Warehouse:N",
                        y="Quantity:Q",
                        color="InventoryType:N",
                        tooltip=["Warehouse:N","InventoryType:N","Quantity:Q"]
                    ).properties(height=420, width=1400)
                )
                st.altair_chart(bar, use_container_width=True)
                st.dataframe(byp,use_container_width=True)

                c3,c4 = st.columns(2)
                with c3:
                    st.download_button(
                        "⬇️ Download totals-by-plant (CSV)",
                        df_to_csv_bytes(byp),
                        "totals_by_plant.csv"
                    )
                with c4:
                    x = df_to_excel_bytes(byp,"ByPlant")
                    if x:
                        st.download_button(
                            "⬇️ Download totals-by-plant (Excel)",
                            x,
                            "totals_by_plant.xlsx"
                        )

    # -------------------------------------------------------
    # ---------- Render any metric tab --------------------
    # -------------------------------------------------------
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
                st.download_button(
                    f"⬇️ {qty_col} summary (CSV)",
                    df_to_csv_bytes(summ),
                    f"{qty_col}_summary.csv"
                )
            with c2:
                x = df_to_excel_bytes(summ,qty_col+"_Summary")
                if x:
                    st.download_button(
                        f"⬇️ {qty_col} summary (Excel)",
                        x,
                        f"{qty_col}_summary.xlsx"
                    )

            st.markdown("---")
            st.subheader("🔍 Select a material + warehouse")

            summ["_label"] = (
                summ["SapCode"].astype(str)
                +" | "+ summ["Warehouse"]
                +" | Qty: "+ summ["Quantity"].astype(int).astype(str)
                +" | Days: "+ summ["Days Since Zero"].astype(int).astype(str)
            )
            pick = st.selectbox("Choose:", summ["_label"].tolist())
            row = summ[summ["_label"]==pick].iloc[0]
            mat = row["SapCode"] ; wh = row["Warehouse"]

            hist = data[(data["SapCode"]==mat)&(data["Warehouse"]==wh)].sort_values("Period")
            st.write("### 📄 Full History")
            st.dataframe(hist,use_container_width=True)

            c3,c4 = st.columns(2)
            with c3:
                st.download_button(
                    "⬇️ History (CSV)",
                    df_to_csv_bytes(hist),
                    f"{qty_col}_{mat}_{wh}_history.csv"
                )
            with c4:
                x = df_to_excel_bytes(hist,qty_col+"_History")
                if x:
                    st.download_button(
                        "⬇️ History (Excel)",
                        x,
                        f"{qty_col}_{mat}_{wh}_history.xlsx"
                    )

            st.write("### 📊 Quantity Over Time")
            if "Period" in hist.columns and qty_col in hist.columns:
                line = (
                    alt.Chart(hist)
                    .mark_line(point=True)
                    .encode(
                        x="Period:T",
                        y=f"{qty_col}:Q",
                        tooltip=["Period",qty_col]
                    )
                    .properties(height=450,width=1400)
                )
                st.altair_chart(line,use_container_width=True)

    # Render metric tabs
    metric_tab(tab2, "QualityInspectionQty", "Quality Inspection Qty")
    metric_tab(tab3, "BlockedStockQty", "Blocked Stock Qty")
    metric_tab(tab4, "ReturnStockQty", "Return Stock Qty")
    metric_tab(tab5, "OveragedTireQty", "Overaged Inventory")


# ===========================================================
# =================== HOME PAGE =============================
# ===========================================================
if app_mode == "Home":

    st.title("Welcome to the Supply Chain Management Dashboard")
    st.subheader("Please choose a module from the sidebar.")

    st.markdown("""
    ## Available Modules
    - **Non-Productive Inventory Management**  
      Analyze stagnant and non-productive stock, visualize trends, compute days since zero, deep-dive into material-level history, and more.

    - **Planning Overview** *(coming soon)*  
      Future area for demand/supply planning insights.

    - **Storage Capacity Management** *(coming soon)*  
      Future capacity simulation & warehouse utilization dashboards.

    - **Transportation Management** *(coming soon)*  
      Planned module for shipment flows, carrier performance, and logistics efficiency.
    """)


# ===========================================================
# ========== NON-PRODUCTIVE INVENTORY MODULE ================
# ===========================================================
elif app_mode == "Non-Productive Inventory Management":
    run_npi_app()


# ===========================================================
# ========== EMPTY FUTURE MODULES ===========================
# ===========================================================
elif app_mode == "Planning Overview":
    st.title("Planning Overview")
    st.info("This module will be developed in a future release.")

elif app_mode == "Storage Capacity Management":
    st.title("Storage Capacity Management")
    st.info("This module will be developed in a future release.")

elif app_mode == "Transportation Management":
    st.title("Transportation Management")
    st.info("This module will be developed in a future release.")

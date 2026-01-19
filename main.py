
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

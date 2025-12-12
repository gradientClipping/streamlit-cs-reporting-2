import streamlit as st
import streamlit.components.v1 as components
import pandas as pd
import numpy as np
import re
import io
import altair as alt
from datetime import datetime

# ==========================
# 1. PAGE CONFIGURATION
# ==========================
st.set_page_config(
    page_title="Data Reconciliation",
    layout="wide",
    initial_sidebar_state="expanded"
)

# ==========================
# 2. PROFESSIONAL CSS STYLING (Neutral Gray Theme)
# ==========================
st.markdown("""
<style>
    /* Global Reset & Font */
    .stApp {
        background-color: #f4f6f9;
        font-family: 'Inter', -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
    }

    /* Headings */
    h1, h2, h3 {
        color: #1e293b;
        font-weight: 600;
        letter-spacing: -0.5px;
    }
    h1 { font-size: 24px; margin-bottom: 20px; }
    h3 { font-size: 16px; margin-top: 0; }

    /* Cards/Containers */
    .dashboard-card {
        background-color: white;
        border-radius: 8px;
        border: 1px solid #e6e9ee;
        padding: 20px;
        margin-bottom: 16px;
        box-shadow: 0 4px 10px rgba(18,24,39,0.03);
    }

    /* KPI Boxes for Session summary (used in components iframe also) */
    .kpi-grid {
        display: grid;
        grid-template-columns: repeat(4, 1fr);
        gap: 12px;
        margin-bottom: 12px;
    }
    .kpi {
        background: white;
        border-radius: 10px;
        padding: 14px;
        border: 1px solid #eef2f6;
        box-shadow: 0 1px 3px rgba(18,24,39,0.04);
    }
    .kpi .label { font-size:12px; color:#64748b; font-weight:600; }
    .kpi .value { font-size:20px; color:#1e293b; font-weight:700; margin-top:8px; }

    /* Buttons */
    div.stButton > button {
        width: 100%;
        background-color: #374151;
        color: white;
        border: none;
        padding: 10px 16px;
        border-radius: 6px;
        font-weight: 600;
        transition: background 0.15s;
    }
    div.stButton > button:hover {
        background-color: #1f2937;
    }

    /* Tables */
    div[data-testid="stDataFrame"] {
        border: 1px solid #e6e9ee;
        border-radius: 6px;
    }

    /* Small utility */
    .muted { color:#64748b; font-size:13px; }
</style>
""", unsafe_allow_html=True)

# ==========================
# 3. HELPER FUNCTIONS
# ==========================
def normalize_phone(x):
    if pd.isna(x) or str(x).strip() == "": return None
    x = re.sub(r"\D", "", str(x))
    if x.startswith("62"): x = "0" + x[2:]
    elif x.startswith("8"): x = "0" + x
    return x

def parse_datetime(series, dayfirst=False):
    return pd.to_datetime(series, errors='coerce', dayfirst=dayfirst)

# ==========================
# 4. MODULE A: CALL DURATION LOGIC
# ==========================
RATE_INBOUND = 1000
RATE_OUTBOUND = 12
INBOUND_FREE_QUOTA = 5000

def convert_duration_to_seconds(x):
    try:
        x = str(x).strip()
        if x in ["-", "", "nan", "NaN", "None"]: return 0.0
        if ":" in x:
            parts = x.split(":")
            if len(parts) == 3: return float(parts[0])*3600 + float(parts[1])*60 + float(parts[2])
            if len(parts) == 2: return float(parts[0])*60 + float(parts[1])
        return float(x)
    except:
        return 0.0

def load_smartcare_file(uploaded_file):
    try:
        return pd.read_excel(uploaded_file, skiprows=3)
    except:
        uploaded_file.seek(0)
        try:
            return pd.read_csv(uploaded_file, skiprows=3, sep=None, engine='python')
        except:
            uploaded_file.seek(0)
            tables = pd.read_html(uploaded_file, header=3)
            return tables[0]

def process_channel(info_df, sc_df, channel_type):
    # Prepare Infomedia
    df_info = info_df.copy()
    
    if channel_type == "Inbound":
        if "ZONE" in df_info.columns:
            df_info = df_info[df_info["ZONE"] == "JJ"].copy()
        col_phone = "A_NUMBER"
        col_time = "DATE_TIME" if "DATE_TIME" in df_info.columns else df_info.columns[0]
        col_dur = "CALL_DURATION"
    else: # Outbound
        col_phone = "bnum"
        col_time = "call_start_time"
        col_dur = "duration"
    
    if col_phone not in df_info.columns:
        st.error(f"Missing column '{col_phone}' in Infomedia {channel_type}.")
        return None
    
    df_info["phone"] = df_info[col_phone].apply(normalize_phone)
    df_info["last8"] = df_info["phone"].astype(str).str[-8:]
    df_info["INFO_DURATION_SEC"] = df_info[col_dur].apply(convert_duration_to_seconds) if col_dur in df_info.columns else 0.0
    df_info["clean_time"] = parse_datetime(df_info[col_time])
    df_info = df_info.reset_index(drop=True).reset_index().rename(columns={"index": "id_trx"})
    
    # Prepare Smartcare
    df_sc = sc_df.copy()
    cols_map = {
        "H": "Start IVR Duration", "L": "Agent Ring Duration", 
        "O": "Duration Talk", "P": "Duration Hold", "R": "Duration Survey"
    }
    
    for col_name in cols_map.values():
        if col_name in df_sc.columns:
            df_sc[col_name] = df_sc[col_name].apply(convert_duration_to_seconds)
        else:
            df_sc[col_name] = 0.0
    
    if channel_type == "Inbound":
        df_sc["SC_TOTAL_DURATION"] = (
            df_sc[cols_map["H"]] + df_sc[cols_map["L"]] + 
            df_sc[cols_map["O"]] + df_sc[cols_map["P"]] + df_sc[cols_map["R"]]
        )
    else: # Outbound
        df_sc["SC_TOTAL_DURATION"] = (
            df_sc[cols_map["L"]] + df_sc[cols_map["O"]] + 
            df_sc[cols_map["P"]] + df_sc[cols_map["R"]]
        )
    
    sc_phone_col = "Caller Id" if "Caller Id" in df_sc.columns else df_sc.columns[0]
    df_sc["phone"] = df_sc[sc_phone_col].apply(normalize_phone)
    df_sc["last8"] = df_sc["phone"].astype(str).str[-8:]
    if "Incoming Time" in df_sc.columns:
        df_sc["clean_time"] = parse_datetime(df_sc["Incoming Time"], dayfirst=True)
    else:
        dt_cols = [c for c in df_sc.columns if "time" in c.lower() or "date" in c.lower()]
        df_sc["clean_time"] = parse_datetime(df_sc[dt_cols[0]] , dayfirst=True) if dt_cols else pd.NaT
    
    # Match
    merged = pd.merge(
        df_info,
        df_sc[["last8", "phone", "clean_time", "SC_TOTAL_DURATION"]],
        on="last8", how="left", suffixes=("", "_sc")
    )
    merged["is_exact"] = merged.get("phone") == merged.get("phone_sc")
    merged["is_duration_valid"] = merged.get("SC_TOTAL_DURATION", 0.0) >= merged.get("INFO_DURATION_SEC", 0.0)
    merged["time_diff"] = (merged["clean_time"] - merged.get("clean_time_sc")).abs().fillna(pd.Timedelta(days=3650))
    
    sorted_df = merged.sort_values(
        by=["id_trx", "is_exact", "is_duration_valid", "time_diff"],
        ascending=[True, False, False, True]
    )
    final_result = sorted_df.drop_duplicates(subset=["id_trx"], keep="first")
    final_result.loc[final_result["SC_TOTAL_DURATION"].isna(), "SC_TOTAL_DURATION"] = 0.0
    
    return final_result

def display_duration_summary(df, channel_type):
    """
    Updated summary display (Option B layout).
    Shows both Smartcare Base and Infomedia Base, applies inbound quota,
    and uses separate rates for inbound/outbound.
    """
    # Calculate sums (seconds)
    total_sec_info = df["INFO_DURATION_SEC"].sum()
    total_sec_sc = df["SC_TOTAL_DURATION"].sum()
    
    # Branch logic by channel to produce display units and billing rules
    if channel_type == "Inbound":
        # Convert seconds -> minutes for display
        val_info = total_sec_info / 60.0      # Infomedia base (minutes)
        val_sc = total_sec_sc / 60.0          # Smartcare base (minutes)
        unit_label = "Minutes"
        # Apply inbound free quota (minutes)
        billable_sc = max(0.0, val_sc - INBOUND_FREE_QUOTA)
        rate = RATE_INBOUND
        quota_display = f"-{INBOUND_FREE_QUOTA:,.0f}"
    else:
        # Outbound: keep in seconds (no quota)
        val_info = total_sec_info            # Infomedia base (seconds)
        val_sc = total_sec_sc                # Smartcare base (seconds)
        unit_label = "Seconds"
        billable_sc = val_sc
        rate = RATE_OUTBOUND
        quota_display = "N/A"
    
    # Cost and variance
    amount_sc = billable_sc * rate
    variance = val_sc - val_info  # SC - Info (in displayed units)
    
    # --- Top summary card ---
    st.markdown(f"""
    <div class="dashboard-card">
        <h3 style="margin-bottom: 16px;">{channel_type} Cost Reconciliation</h3>
        <div style="display:grid; grid-template-columns: 1fr 1fr 1fr; gap:20px; margin-bottom: 20px;">
            <div>
                <div style="font-size:12px; color:#64748b; font-weight:600;">INFOMEDIA (SOURCE)</div>
                <div style="font-size:20px; font-weight:600; color:#1e293b;">{val_info:,.2f}</div>
                <div style="font-size:12px; color:#94a3b8;">Total {unit_label}</div>
            </div>
            <div>
                <div style="font-size:12px; color:#64748b; font-weight:600;">SMARTCARE (VALIDATED)</div>
                <div style="font-size:20px; font-weight:600; color:#374151;">{val_sc:,.2f}</div>
                <div style="font-size:12px; color:#94a3b8;">Total {unit_label}</div>
            </div>
             <div>
                <div style="font-size:12px; color:#64748b; font-weight:600;">VARIANCE</div>
                <div style="font-size:20px; font-weight:600; color:{'#e53e3e' if variance < 0 else '#16a34a'};">
                    {variance:+,.2f}
                </div>
                <div style="font-size:12px; color:#94a3b8;">{unit_label}</div>
            </div>
        </div>
    </div>
    """, unsafe_allow_html=True)
    
    # --- Detailed table (components.html to ensure rendering inside tabs/expanders) ---
    html_block = f"""
    <style>
      .card {{ background:#f8fafc; padding:16px; border-radius:6px; border:1px solid #e6e9ee; font-family: Inter, system-ui, -apple-system, 'Segoe UI', Roboto, 'Helvetica Neue', Arial; }}
      .comp-table {{ width:100%; border-collapse:collapse; font-size:14px; margin-top:10px; }}
      .comp-table th {{ text-align:left; color:#64748b; font-weight:600; padding:8px; border-bottom:1px solid #e6e9ee; }}
      .comp-table td {{ padding:8px; border-bottom:1px solid #f1f5f9; color:#334155; }}
      .metric-value {{ text-align:right; font-weight:600; }}
      .metric-strong {{ text-align:right; font-weight:700; color:#2d3748; }}
      .cost-value {{ text-align:right; font-weight:700; color:#374151; font-size:16px; }}
      .quota {{ text-align:right; color:#e53e3e; font-weight:600; }}
      .muted {{ color:#64748b; text-align:right; }}
      .label-left {{ text-align:left; }}
    </style>
    <div class="card">
      <table class="comp-table" role="table" aria-label="Reconciliation Summary">
          <thead>
            <tr>
              <th style="width:40%;">Metric</th>
              <th style="text-align:right;">Value</th>
              <th style="text-align:right;">Calculation</th>
            </tr>
          </thead>
          <tbody>
            <tr>
              <td class="label-left">Smartcare Base ({unit_label})</td>
              <td class="metric-value">{val_sc:,.2f}</td>
              <td class="muted">Validated</td>
            </tr>
            <tr>
              <td class="label-left">Infomedia Base ({unit_label})</td>
              <td class="metric-value">{val_info:,.2f}</td>
              <td class="muted">Source</td>
            </tr>
            <tr>
              <td class="label-left">Variance ({unit_label})</td>
              <td class="metric-value">{variance:+,.2f}</td>
              <td class="muted">SC - Info</td>
            </tr>
            <tr>
              <td class="label-left">Free Quota</td>
              <td class="quota">{quota_display}</td>
              <td class="muted">{'Inbound Only' if unit_label=='Minutes' else 'No Quota'}</td>
            </tr>
            <tr style="border-top:2px solid #e6e9ee;">
              <td class="label-left"><strong>Billable Duration ({unit_label})</strong></td>
              <td class="metric-strong">{billable_sc:,.2f}</td>
              <td class="muted">After deductions</td>
            </tr>
            <tr>
              <td class="label-left"><strong>Estimated Cost</strong></td>
              <td class="cost-value">IDR {amount_sc:,.0f}</td>
              <td class="muted">@ {rate:,} / unit</td>
            </tr>
          </tbody>
      </table>
    </div>
    """
    components.html(html_block, height=260)
    
    return df

# ==========================
# 5. MODULE B: SESSION ID LOGIC
# ==========================
SESSION_KEY_PATTERN = re.compile(r'(call\s*session\s*id|session\s*id)', re.IGNORECASE)
NUMBER_PATTERN = re.compile(r'(\d{5,})')  

def extract_session_id_row(row):
    values = row.values
    for i, cell in enumerate(values):
        if pd.isna(cell): continue
        text = str(cell)
        if SESSION_KEY_PATTERN.search(text):
            match = NUMBER_PATTERN.search(text)
            if match: return match.group(1)
            if i + 1 < len(values) and not pd.isna(values[i + 1]):
                next_text = str(values[i + 1])
                match_next = NUMBER_PATTERN.search(next_text)
                if match_next: return match_next.group(1)
            return None
    return None

def extract_date_from_filename(filename):
    match = re.search(r'(\d{6})', filename)
    if match:
        date_str = match.group(1)
        try:
            return datetime.strptime(date_str, "%y%m%d").date()
        except ValueError:
            return None
    return None

def process_session_data(log_file, smartcare_file):
    try:
        aws_filename = log_file.name
        target_date = extract_date_from_filename(aws_filename)
        
        if target_date:
            st.markdown(f'<div class="status-box status-info">Date detected: {target_date}</div>', unsafe_allow_html=True)
        else:
            st.markdown(f'<div class="status-box status-error">Date not found in filename: {aws_filename}</div>', unsafe_allow_html=True)
        
        # --- FIX: ROBUST LOG FILE READING ---
        try:
            # Try UTF-8 first
            raw_aws = pd.read_fwf(log_file, header=None, encoding='utf-8')
        except UnicodeDecodeError:
            # Fallback to Latin-1 if UTF-8 fails (Common for server logs)
            log_file.seek(0)
            raw_aws = pd.read_fwf(log_file, header=None, encoding='latin1')
        
        raw_aws.columns = [f"col{i+1}" for i in range(raw_aws.shape[1])]
        raw_aws["session_id"] = raw_aws.apply(extract_session_id_row, axis=1)
        aws_ids = raw_aws['session_id'].dropna().astype(str).str.strip()
        set_aws = set(aws_ids.unique())
        
        # --- FIX: ROBUST CSV READING FOR SMARTCARE ---
        try:
            raw_smartcare = pd.read_csv(smartcare_file, encoding='utf-8')
        except UnicodeDecodeError:
            smartcare_file.seek(0)
            raw_smartcare = pd.read_csv(smartcare_file, encoding='latin1')

        if 'Session ID' not in raw_smartcare.columns:
            st.markdown('<div class="status-box status-error">Missing "Session ID" column in CSV.</div>', unsafe_allow_html=True)
            return None, None, None, None
        
        # Filter by Date if possible
        if target_date and 'Date' in raw_smartcare.columns:
            # Clean date column before parsing
            raw_smartcare['Date'] = raw_smartcare['Date'].astype(str).str.strip()
            raw_smartcare['temp_date_obj'] = pd.to_datetime(raw_smartcare['Date'], format='%d-%b-%y', errors='coerce')
            raw_smartcare = raw_smartcare[raw_smartcare['temp_date_obj'].dt.date == target_date]
            
        smartcare_ids = raw_smartcare['Session ID'].dropna().astype(str).str.strip()
        set_smartcare = set(smartcare_ids.unique())
        
        # Reconciliation
        only_in_aws = set_aws - set_smartcare
        only_in_smartcare = set_smartcare - set_aws
        common_ids = set_aws & set_smartcare
        
        summary = {
            "aws_total": len(set_aws),
            "smartcare_total": len(set_smartcare),
            "only_aws": len(only_in_aws),
            "only_smartcare": len(only_in_smartcare),
            "intersection": len(common_ids),
            "duplicates_in_aws": (len(aws_ids) - len(set_aws)),  # count duplicates in raw aws extraction
            "missing_session_rows": raw_aws['session_id'].isna().sum()
        }
        
        df_only_aws = pd.DataFrame(sorted(list(only_in_aws)), columns=['Session ID'])
        df_only_smartcare = pd.DataFrame(sorted(list(only_in_smartcare)), columns=['Session ID'])
        df_common = pd.DataFrame(sorted(list(common_ids)), columns=['Session ID'])
        
        return summary, df_only_aws, df_only_smartcare, df_common
        
    except Exception as e:
        st.markdown(f'<div class="status-box status-error">Processing Error: {str(e)}</div>', unsafe_allow_html=True)
        return None, None, None, None

def to_excel_download(df, name='data'):
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
        df.to_excel(writer, index=False, sheet_name='Data')
    return output.getvalue()

# --- New: Session summary display (S2 - Enhanced Card UI, Neutral Gray) ---
def display_session_summary(summary, df_only_aws, df_only_smartcare, df_common):
    if not summary:
        st.info("No session summary to display.")
        return

    # Build HTML KPI cards (we render using components.html to make styling consistent)
    html = f"""
    <style>
      .wrap {{ font-family: Inter, system-ui, -apple-system, 'Segoe UI', Roboto, Arial; }}
      .card-grid {{ display:grid; grid-template-columns: repeat(4, 1fr); gap:12px; }}
      .card-item {{
        background: white;
        border-radius:10px;
        padding:14px;
        border:1px solid #eef2f6;
        box-shadow: 0 2px 6px rgba(18,24,39,0.04);
      }}
      .kpi-label {{ font-size:12px; color:#64748b; font-weight:600; }}
      .kpi-value {{ font-size:20px; color:#1e293b; font-weight:700; margin-top:8px; }}
      .kpi-muted {{ font-size:12px; color:#94a3b8; margin-top:6px; }}
      .controls {{ margin-top:12px; display:flex; gap:8px; }}
      .btn {{
        background:#374151; color:white; padding:8px 10px; border-radius:8px; text-decoration:none; font-weight:600;
      }}
    </style>
    <div class="wrap">
      <div class="dashboard-card" style="padding:18px;">
        <h3 style="margin-bottom:8px;">Session ID Summary</h3>
        <div class="card-grid">
          <div class="card-item"><div class="kpi-label">Total Sessions (AWS extracted)</div><div class="kpi-value">{summary['aws_total']:,}</div><div class="kpi-muted">Total unique IDs from AWS</div></div>
          <div class="card-item"><div class="kpi-label">Smartcare Sessions</div><div class="kpi-value">{summary['smartcare_total']:,}</div><div class="kpi-muted">Unique IDs from Smartcare</div></div>
          <div class="card-item"><div class="kpi-label">Duplicates in AWS</div><div class="kpi-value">{summary.get('duplicates_in_aws',0):,}</div><div class="kpi-muted">Duplicate rows detected</div></div>
          <div class="card-item"><div class="kpi-label">Missing Session Rows</div><div class="kpi-value">{summary.get('missing_session_rows',0):,}</div><div class="kpi-muted">Rows without extracted session id</div></div>
        </div>

        <div style="height:12px;"></div>

        <div style="display:flex; gap:12px;">
          <div style="flex:1;">
            <div style="background:#ffffff; border:1px solid #eef2f6; border-radius:8px; padding:12px;">
              <div style="font-size:13px; color:#64748b; font-weight:600;">Unmatched (Only AWS)</div>
              <div style="font-size:18px; color:#1e293b; font-weight:700; margin-top:8px;">{summary['only_aws']:,}</div>
              <div style="margin-top:8px;"><a class="btn" href="#" onclick="return false;">Download</a></div>
            </div>
          </div>

          <div style="flex:1;">
            <div style="background:#ffffff; border:1px solid #eef2f6; border-radius:8px; padding:12px;">
              <div style="font-size:13px; color:#64748b; font-weight:600;">Unmatched (Only Smartcare)</div>
              <div style="font-size:18px; color:#1e293b; font-weight:700; margin-top:8px;">{summary['only_smartcare']:,}</div>
              <div style="margin-top:8px;"><a class="btn" href="#" onclick="return false;">Download</a></div>
            </div>
          </div>

          <div style="flex:1;">
            <div style="background:#ffffff; border:1px solid #eef2f6; border-radius:8px; padding:12px;">
              <div style="font-size:13px; color:#64748b; font-weight:600;">Matched</div>
              <div style="font-size:18px; color:#1e293b; font-weight:700; margin-top:8px;">{summary['intersection']:,}</div>
              <div style="margin-top:8px;"><a class="btn" href="#" onclick="return false;">Download</a></div>
            </div>
          </div>
        </div>

        <div style="margin-top:12px;" class="kpi-muted">Tip: Use the detail tabs below to inspect the actual Session ID lists and download them.</div>
      </div>
    </div>
    """
    # Render the KPI area
    components.html(html, height=320)

    # Provide real download buttons under the KPI area (Streamlit native)
    c1, c2, c3 = st.columns(3)
    with c1:
        st.write("AWS Only")
        st.dataframe(df_only_aws.head(10), use_container_width=True)
        st.download_button("Download AWS Only (Excel)", to_excel_download(df_only_aws, 'aws_only'), "aws_only.xlsx")
    with c2:
        st.write("Smartcare Only")
        st.dataframe(df_only_smartcare.head(10), use_container_width=True)
        st.download_button("Download Smartcare Only (Excel)", to_excel_download(df_only_smartcare, 'sc_only'), "sc_only.xlsx")
    with c3:
        st.write("Matched")
        st.dataframe(df_common.head(10), use_container_width=True)
        st.download_button("Download Matched (Excel)", to_excel_download(df_common, 'matched'), "matched.xlsx")

# ==========================
# 6. MAIN UI
# ==========================

# Sidebar
with st.sidebar:
    st.markdown("### Configuration")
    app_mode = st.radio("Module", ["Call Duration", "Session ID"], label_visibility="collapsed")
    st.markdown("---")
    
    if app_mode == "Call Duration":
        st.markdown("**Infomedia (Source)**")
        info_file = st.file_uploader("Upload .xlsx", type=["xlsx"], key="info")
        
        sheet_in, sheet_out = None, None
        if info_file:
            try:
                xls = pd.ExcelFile(info_file)
                sheet_in = st.selectbox("Inbound Sheet", xls.sheet_names, index=0)
                sheet_out = st.selectbox("Outbound Sheet", xls.sheet_names, index=1 if len(xls.sheet_names)>1 else 0)
            except Exception as e:
                st.warning(f"Couldn't read Excel sheets: {e}")
        
        st.markdown("**Smartcare (Comparison)**")
        sc_in_file = st.file_uploader("Inbound Log", type=["xls", "csv", "xlsx"], key="sc_in")
        sc_out_file = st.file_uploader("Outbound Log", type=["xls", "csv", "xlsx"], key="sc_out")
        
        st.markdown("---")
        run_btn = st.button("Analyze Duration")
        
    else: # Session ID
        st.markdown("**AWS Log (Source)**")
        aws_file = st.file_uploader("Upload .log", type=["log", "txt"], key="aws")
        
        st.markdown("**Smartcare CSV (Comparison)**")
        sc_csv_file = st.file_uploader("Upload .csv", type=["csv"], key="sc_csv")
        
        st.markdown("---")
        st.caption("AWS filename format: YYMMDD")
        st.caption("Smartcare date format: DD-Mon-YY")
        run_btn = st.button("Analyze Sessions")

# Main Content
st.title("Data Reconciliation")

if app_mode == "Call Duration":
    if not run_btn:
        st.info("Upload files in the sidebar and click Analyze Duration.")
    elif info_file and sc_in_file and sc_out_file and sheet_in is not None and sheet_out is not None:
        try:
            with st.spinner("Processing..."):
                df_info_in = pd.read_excel(info_file, sheet_name=sheet_in)
                df_info_out = pd.read_excel(info_file, sheet_name=sheet_out)
                df_sc_in = load_smartcare_file(sc_in_file)
                df_sc_out = load_smartcare_file(sc_out_file)
                
                tab1, tab2 = st.tabs(["Inbound", "Outbound"])
                
                with tab1:
                    res_in = process_channel(df_info_in, df_sc_in, "Inbound")
                    if res_in is not None:
                        display_duration_summary(res_in, "Inbound")
                        with st.expander("Details"):
                            cols_shown = [c for c in ["id_trx", "phone", "clean_time", "clean_time_sc", "time_diff", "SC_TOTAL_DURATION", "INFO_DURATION_SEC"] if c in res_in.columns]
                            st.dataframe(res_in[cols_shown].head(50), use_container_width=True)
                        st.download_button("Download CSV", res_in.to_csv(index=False).encode('utf-8'), "inbound_report.csv", "text/csv")
                
                with tab2:
                    res_out = process_channel(df_info_out, df_sc_out, "Outbound")
                    if res_out is not None:
                        display_duration_summary(res_out, "Outbound")
                        with st.expander("Details"):
                            cols_shown = [c for c in ["id_trx", "phone", "clean_time", "clean_time_sc", "time_diff", "SC_TOTAL_DURATION", "INFO_DURATION_SEC"] if c in res_out.columns]
                            st.dataframe(res_out[cols_shown].head(50), use_container_width=True)
                        st.download_button("Download CSV", res_out.to_csv(index=False).encode('utf-8'), "outbound_report.csv", "text/csv")
                        
        except Exception as e:
            st.error(f"Error: {str(e)}")
    else:
        st.error("Missing required files or sheet selection.")

elif app_mode == "Session ID":
    if not run_btn:
        st.info("Upload files in the sidebar and click Analyze Sessions.")
    elif aws_file and sc_csv_file:
        summary, df_only_aws, df_only_smartcare, df_common = process_session_data(aws_file, sc_csv_file)
        
        if summary:
            # Use the new enhanced session UI
            display_session_summary(summary, df_only_aws, df_only_smartcare, df_common)
        else:
            st.error("Failed to process session files.")
    else:
        st.error("Missing required files.")

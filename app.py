import streamlit as st
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import seaborn as sns
from matplotlib.colors import ListedColormap
from io import BytesIO
import re
import unicodedata
import streamlit_authenticator as stauth
import yaml
from yaml.loader import SafeLoader
import os
import warnings

# --- Ẩn các cảnh báo hệ thống ---
warnings.filterwarnings("ignore", category=DeprecationWarning)
warnings.filterwarnings("ignore", category=UserWarning)

# Cấu hình hiển thị tiếng Việt cho Matplotlib
plt.rcParams['font.family'] = 'DejaVu Sans'

# =========================================================
# 1. CẤU HÌNH BẢO MẬT & PHÂN QUYỀN ĐĂNG NHẬP
# =========================================================
st.set_page_config(layout="wide", page_title="WHONET Antibiogram System", page_icon="🛡️")

@st.cache_data(ttl=3600)
def initialize_auth_config():
    default_config = {
        "credentials": {
            "usernames": {
                "bacsiclinical": {"email": "doctor@hospital.com", "name": "Bác sĩ Lâm sàng", "password": "bacsivien", "role": "doctor"},
                "duocvisinh": {"email": "admin@hospital.com", "name": "Dược lâm sàng / Vi sinh", "password": "bacsivien", "role": "admin"}
            }
        },
        "cookie": {"expiry_days": 30, "key": "antibiogram_secret_key_2026", "name": "antibiogram_cookie"}
    }

    config = None
    if os.path.exists('config.yaml'):
        try:
            with open('config.yaml', 'r', encoding='utf-8') as file:
                config = yaml.load(file, Loader=SafeLoader)
        except Exception: config = None

    if config is None or not isinstance(config, dict) or 'credentials' not in config:
        try:
            with open('config.yaml', 'w', encoding='utf-8') as f:
                yaml.dump(default_config, f, default_flow_style=False, allow_unicode=True)
            config = default_config
        except Exception as e:
            st.error(f"❌ Lỗi khởi tạo file bảo mật: {e}")
            st.stop()
        
    try:
        modified = False
        for username, user_info in config['credentials']['usernames'].items():
            pwd = user_info['password']
            if not pwd.startswith("$2b$"): 
                try: hashed_password = stauth.Hasher([pwd]).generate()[0]
                except AttributeError: hashed_password = stauth.Hasher([pwd]).hash(pwd)
                config['credentials']['usernames'][username]['password'] = hashed_password
                modified = True
                
        if modified:
            with open('config.yaml', 'w', encoding='utf-8') as file:
                yaml.dump(config, file, default_flow_style=False, allow_unicode=True)
        return config
    except Exception as e:
        st.error(f"❌ Lỗi mã hóa mật khẩu: {e}")
        st.stop()

auth_config = initialize_auth_config()

try:
    authenticator = stauth.Authenticate(
        auth_config['credentials'], auth_config['cookie']['name'],
        auth_config['cookie']['key'], auth_config['cookie']['expiry_days']
    )
except TypeError:
    authenticator = stauth.Authenticate(auth_config)

authenticator.login(location='main')

if st.session_state["authentication_status"] == False:
    st.error('Tài khoản hoặc mật khẩu không đúng!')
    st.stop()
elif st.session_state["authentication_status"] is None:
    st.warning('Vui lòng đăng nhập hệ thống để tiếp tục. (Tài khoản: duocvisinh / Mật khẩu: bacsivien)')
    st.stop()

username = st.session_state["username"]
name = st.session_state["name"]
user_role = auth_config['credentials']['usernames'][username]['role']

authenticator.logout('Đăng xuất khỏi hệ thống', 'sidebar')
st.sidebar.markdown(f"### 👋 Xin chào, \n**{name}**")
st.sidebar.markdown(f"Quyền hạn: `{user_role.upper()}`")
st.sidebar.markdown("---")

st.title("🛡️ Hệ thống Giám sát Dịch tễ & Kháng sinh đồ tích lũy WHONET")

# =========================================================
# 2. DANH MỤC QUY TẮC PHỤ TRỢ & TỪ ĐIỂN THÔNG MINH
# =========================================================
# TỪ ĐIỂN ÁNH XẠ: Giúp nối mã 3 chữ WHONET với Tên đầy đủ trong file rules của bạn
WHONET_ABX_MAP = {
    "amk": "amikacin", "gen": "gentamicin", "tob": "tobramycin", "net": "netilmicin",
    "caz": "ceftazidime", "cro": "ceftriaxone", "fep": "cefepime", "ctx": "cefotaxime", 
    "cxm": "cefuroxime", "czo": "cefazolin", "fox": "cefoxitin", 
    "ipm": "imipenem", "mem": "meropenem", "etp": "ertapenem", "dor": "doripenem",
    "cip": "ciprofloxacin", "lvx": "levofloxacin", "mxf": "moxifloxacin", "ofx": "ofloxacin",
    "tzp": "piperacillin", "sam": "ampicillin", "amc": "amoxicillin", 
    "oxa": "oxacillin", "pen": "penicillin", "amp": "ampicillin", "amx": "amoxicillin",
    "van": "vancomycin", "tec": "teicoplanin", "lzd": "linezolid", 
    "ery": "erythromycin", "cli": "clindamycin", "azi": "azithromycin",
    "sxt": "trimethoprim", "cot": "trimethoprim", "sul": "sulfamethoxazole",
    "col": "colistin", "tcy": "tetracycline", "tig": "tigecycline", 
    "chl": "chloramphenicol", "nit": "nitrofurantoin", "fos": "fosfomycin"
}

def remove_vietnamese_sign(text):
    if not isinstance(text, str): return ""
    text = unicodedata.normalize('NFD', text)
    return re.sub(r'[\u0300-\u036f]', '', text).replace('đ', 'd').replace('Đ', 'D').upper().strip()

def clean_sheet_name(name):
    return re.sub(r"[\\/\?\*\:\[\]]", "", str(name))[:31].strip()

@st.cache_data
def load_auxiliary_rules():
    spec_translation = {"bl": "Máu", "ur": "Nước tiểu", "sp": "Đờm", "as": "Mủ", "ab": "Dịch màng bụng"}
    ward_to_dept, intrinsic_rules, excluded_rules, organism_groups = {}, [], [], {}

    if os.path.exists("specimen_rules.xlsx"):
        try:
            spec_df = pd.read_excel("specimen_rules.xlsx")
            spec_translation = dict(zip(spec_df["SPEC_TYPE"].astype(str).str.strip().str.lower(), spec_df["Specimen_Name"].astype(str).str.strip()))
        except: pass

    if os.path.exists("ward_rules.xlsx"):
        try:
            ward_df = pd.read_excel("ward_rules.xlsx")
            ward_to_dept = dict(zip(ward_df["WARD"].astype(str).str.strip(), ward_df["Ward_Name"].astype(str).str.strip()))
        except: pass

    if os.path.exists("intrinsic_rules.xlsx"):
        try:
            ir_df = pd.read_excel("intrinsic_rules.xlsx")
            for _, r in ir_df.iterrows(): intrinsic_rules.append((str(r["Organism"]).strip().lower(), str(r["Antibiotic"]).strip().lower()))
        except: pass

    if os.path.exists("clsi_excluded.xlsx"):
        try:
            ex_df = pd.read_excel("clsi_excluded.xlsx")
            for _, r in ex_df.iterrows(): excluded_rules.append((str(r["Organism"]).strip().lower(), str(r["Antibiotic"]).strip().lower()))
        except: pass

    if os.path.exists("organism_group.xlsx"):
        try:
            group_file = pd.read_excel("organism_group.xlsx")
            organism_groups = dict(zip(group_file["Organism"].astype(str).str.strip(), group_file["Gram"].fillna("Không xác định")))
        except: pass

    return spec_translation, ward_to_dept, intrinsic_rules, excluded_rules, organism_groups

spec_translation, ward_to_dept, intrinsic_rules, excluded_rules, organism_groups = load_auxiliary_rules()

# =========================================================
# 3. TIẾP NHẬN & XỬ LÝ DỮ LIỆU THÔ WHONET
# =========================================================
@st.cache_data(show_spinner="⏳ Đang nạp dữ liệu WHONET vào bộ nhớ đệm...")
def load_raw_data(file_source):
    # Hàm này đảm bảo file Excel nặng cỡ nào cũng chỉ đọc 1 lần duy nhất
    df = pd.read_excel(file_source)
    df["WARD"] = df["WARD"].astype(str).str.strip()
    df["DEPARTMENT"] = df["DEPARTMENT"].astype(str).str.strip()
    df["SPEC_TYPE"] = df["SPEC_TYPE"].astype(str).str.strip().str.lower()
    df["PID"] = df["PID"].astype(str).str.strip()
    df["Organism"] = df["Organism"].astype(str).str.strip()
    
    # --- THÊM ĐOẠN NÀY ĐỂ CHUẨN HÓA GỘP TÊN VI KHUẨN ---
    organism_mapping = {
        "Staphylococcus aureus ss aureus": "Staphylococcus aureus",
        "Staphylococcus aureus subsp. aureus": "Staphylococcus aureus",
        "Klebsiella pneumoniae ss pneumoniae": "Klebsiella pneumoniae",
        # (Bạn có thể phẩy và thêm các vi khuẩn khác vào đây sau này nếu cần)
    }
    df["Organism"] = df["Organism"].replace(organism_mapping)
    # ----------------------------------------------------
    
    if "Full Name" in df.columns:
        df = df.drop(columns=["Full Name"])
    return df
# --- KHUNG TẢI FILE NẰM SÁT LỀ TRÁI ---
st.sidebar.markdown("### 📂 Tải dữ liệu WHONET")
uploaded_file = st.sidebar.file_uploader("Chọn file dữ liệu Excel/CSV", type=['xlsx', 'xls', 'csv'])
# ----------------------------------------

if uploaded_file:
    if user_role == "admin" and hasattr(uploaded_file, 'name'):
        try:
            with open("data_cache.xlsx", "wb") as f: f.write(uploaded_file.getbuffer())
        except: pass

    # Gọi hàm đã được cache
    raw = load_raw_data(uploaded_file)
    raw["WARD"] = raw["WARD"].astype(str).str.strip()
    raw["DEPARTMENT"] = raw["DEPARTMENT"].astype(str).str.strip()
    raw["SPEC_TYPE"] = raw["SPEC_TYPE"].astype(str).str.strip().str.lower()
    raw["PID"] = raw["PID"].astype(str).str.strip()
    raw["Organism"] = raw["Organism"].astype(str).str.strip()

    if "Full Name" in raw.columns: raw = raw.drop(columns=["Full Name"])
    if not ward_to_dept and not raw.empty:
        ward_to_dept = raw.groupby("WARD")["DEPARTMENT"].apply(lambda x: " / ".join(filter(None, x.unique()))).to_dict()

    if excluded_rules:
        for org, ab in excluded_rules:
            mask = (raw["Organism"].str.lower() == org) & (raw["Antibiotics"].astype(str).str.strip().str.lower() == ab)
            raw = raw.loc[~mask]

    # =========================================================
    # 4. BỘ LỌC ĐỘNG TRÊN GIAO DIỆN INTERFACE
    # =========================================================
    st.markdown("### ⚙️ Cấu hình thuật toán & Bộ lọc dữ liệu")
    isolate_option = st.radio("💡 Chọn phương pháp lọc chủng đầu tiên (First Isolate):", 
                              options=["Tách biệt theo Bệnh phẩm (PID + Vi khuẩn + Loại bệnh phẩm)", "Gom gộp toàn diện (Tiêu chuẩn CLSI M39: PID + Vi khuẩn)"])

    raw["SPEC_DATE"] = pd.to_datetime(raw["SPEC_DATE"], errors="coerce")
    min_date, max_date = raw["SPEC_DATE"].min(), raw["SPEC_DATE"].max()
    
    col1, col2 = st.columns(2)
    with col1: start_date = st.date_input("Từ ngày", value=min_date.date() if pd.notna(min_date) else None)
    with col2: end_date = st.date_input("Đến ngày", value=max_date.date() if pd.notna(max_date) else None)

    df_filtered = raw[(raw["SPEC_DATE"] >= pd.to_datetime(start_date)) & (raw["SPEC_DATE"] <= pd.to_datetime(end_date))].copy()
    df_filtered = df_filtered[df_filtered["Organism"].notna() & (df_filtered["Organism"] != "nan") & (~df_filtered["Organism"].str.contains("No Growth", case=False, na=False))]

    all_wards = sorted(df_filtered["WARD"].dropna().unique().tolist())
    all_specimens = sorted(df_filtered["SPEC_TYPE"].dropna().unique().tolist())

    st.markdown("#### 🔍 Chọn nhanh theo khối lâm sàng")
    col_btn1, col_btn2, col_btn3 = st.columns(3)
    with col_btn1: cb_icu = st.checkbox("🏥 Khối Hồi sức tích cực / Cấp cứu")
    with col_btn2: cb_ngoai = st.checkbox("✂️ Khối Ngoại khoa")
    with col_btn3: cb_noi = st.checkbox("💊 Khối Nội khoa")

    default_wards = []
    if cb_icu: default_wards += [w for w in all_wards if any(k in remove_vietnamese_sign(w) or k in remove_vietnamese_sign(ward_to_dept.get(w, "")) for k in ["ICU", "HOI SUC", "CAP CUU", "HSCC", "GAY ME"])]
    if cb_ngoai: default_wards += [w for w in all_wards if any(k in remove_vietnamese_sign(w) or k in remove_vietnamese_sign(ward_to_dept.get(w, "")) for k in ["NGOAI", "PHAU THUAT", "CHAN THUONG", "SAN"])]
    if cb_noi: default_wards += [w for w in all_wards if any(k in remove_vietnamese_sign(w) or k in remove_vietnamese_sign(ward_to_dept.get(w, "")) for k in ["NOI", "TIM MACH", "HO HAP", "TIEU HOA", "NHI"]) and not any(k in remove_vietnamese_sign(ward_to_dept.get(w, "")) for k in ["HOI SUC", "ICU", "GAY ME"])]
    
    if not cb_icu and not cb_ngoai and not cb_noi: default_wards = all_wards
    else: default_wards = list(set(default_wards))

    selected_wards = st.multiselect("Khoa phòng lọc:", options=all_wards, default=default_wards, format_func=lambda x: f"{x} — {ward_to_dept.get(x, 'Chưa rõ')}")

    col_sp1, col_sp2, col_sp3 = st.columns(3)
    with col_sp1: cb_mau = st.checkbox("🩸 Mẫu MÁU")
    with col_sp2: cb_tieu = st.checkbox("🚽 Mẫu NƯỚC TIỂU")
    with col_sp3: cb_hohap = st.checkbox("𫆀 Mẫu HÔ HẤP")

    default_specs = []
    if cb_mau: default_specs += [s for s in all_specimens if "MAU" in remove_vietnamese_sign(spec_translation.get(s.lower(), "")) or s.lower() == "bl"]
    if cb_tieu: default_specs += [s for s in all_specimens if "NUOC TIEU" in remove_vietnamese_sign(spec_translation.get(s.lower(), "")) or s.lower() == "ur"]
    if cb_hohap: default_specs += [s for s in all_specimens if any(k in remove_vietnamese_sign(spec_translation.get(s.lower(), "")) or k in s.lower() for k in ["DOM", "HO HAP", "PHE QUAN", "BAL", "SP"])]

    if not cb_mau and not cb_tieu and not cb_hohap: default_specs = all_specimens
    else: default_specs = list(set(default_specs))

    selected_specimens = st.multiselect("Bệnh phẩm lọc:", options=all_specimens, default=default_specs, format_func=lambda x: f"{x} — {spec_translation.get(x.lower(), x)}")

    if selected_wards: df_filtered = df_filtered[df_filtered["WARD"].isin(selected_wards)]
    if selected_specimens: df_filtered = df_filtered[df_filtered["SPEC_TYPE"].isin(selected_specimens)]

    if df_filtered.empty: st.warning("⚠️ Không tìm thấy kết quả nào phù hợp với bộ lọc."); st.stop()

    pivot = df_filtered.pivot_table(index=["PID", "SPEC_DATE", "WARD", "SPEC_TYPE", "Organism"], columns="Antibiotics", values="Interpretation", aggfunc="first").reset_index()
    pivot = pivot.sort_values("SPEC_DATE")
    
    subset_cols = ["PID", "Organism", "SPEC_TYPE"] if "Tách biệt theo Bệnh phẩm" in isolate_option else ["PID", "Organism"]
    pivot = pivot.drop_duplicates(subset=subset_cols, keep="first")

    # =========================================================
    # 5. THUẬT TOÁN ĐẾM VÀ TÍNH ANTIBIOGRAM
    # =========================================================
    st.markdown("---")
    counts = pivot.groupby("Organism").size().reset_index(name="n").sort_values(by="n", ascending=False).reset_index(drop=True)
    ignore_cols = {"PID", "SPEC_DATE", "WARD", "SPEC_TYPE", "Organism"}
    antibiotic_cols = [col for col in pivot.columns if col not in ignore_cols]

    def calculate_antibiogram(source_df, target_orgs, ab_list, rules_list):
        result_list = []
        filtered = source_df[source_df["Organism"].isin(target_orgs)]
        for org in sorted(filtered["Organism"].unique()):
            temp = filtered[filtered["Organism"] == org]
            row = {"Vi khuẩn": org, "Số lượng n": len(temp)}
            org_lower = org.lower()
            for ab in ab_list:
                ab_lower = str(ab).lower()
                # CƠ CHẾ DỊCH TÊN: Ánh xạ mã WHONET ra tên đầy đủ
                ab_full = WHONET_ABX_MAP.get(ab_lower[:3], ab_lower) 
                
                # Nâng cấp logic chuỗi: Match cả tên viết tắt lẫn tên đầy đủ
                is_ir = any(
                    (r_org in org_lower or org_lower in r_org) and 
                    (r_ab in ab_lower or ab_lower in r_ab or r_ab in ab_full or ab_full in r_ab) 
                    for r_org, r_ab in rules_list
                )
                
                if is_ir: row[ab] = "0%"
                else:
                    if ab in temp.columns:
                        valid = temp[temp[ab].isin(["S", "I", "R"])]
                        if len(valid) > 0: 
                            pct_s = int(round(((valid[ab] == 'S').sum() / len(valid)) * 100, 0))
                            row[ab] = f"{pct_s}% ({len(valid)})"
                        else: row[ab] = "-"
                    else: row[ab] = "-"
            result_list.append(row)
        return pd.DataFrame(result_list)

    antibiogram = calculate_antibiogram(pivot, counts["Organism"].tolist(), antibiotic_cols, intrinsic_rules)
    antibiogram["Gram"] = antibiogram["Vi khuẩn"].map(organism_groups).fillna("Không xác định")
    antibiogram = antibiogram.sort_values("Số lượng n", ascending=False).reset_index(drop=True)
    
    gram_negative_abg = antibiogram[antibiogram["Gram"] == "Gram âm"]
    gram_positive_abg = antibiogram[antibiogram["Gram"] == "Gram dương"]
    common_orgs_abg = antibiogram[antibiogram["Số lượng n"] >= 30]
    rare_orgs_abg = antibiogram[antibiogram["Số lượng n"] < 30]
    
    st.markdown("### 🏆 Dashboard Tổng Quan Báo Cáo")
    kpi1, kpi2, kpi3, kpi4 = st.columns(4)
    total_isolates = len(pivot)
    top_1_org = counts.iloc[0]["Organism"] if not counts.empty else "N/A"
    top_1_n = counts.iloc[0]["n"] if not counts.empty else 0
    gram_neg_count = int(gram_negative_abg["Số lượng n"].sum())
    gram_pos_count = int(gram_positive_abg["Số lượng n"].sum())
    
    kpi1.metric("Tổng Số Chủng Sau Lọc", f"{total_isolates} mẫu")
    kpi2.metric("Vi Khuẩn Top 1", top_1_org, f"{top_1_n} mẫu")
    kpi3.metric("Số Lượng Gram Âm", gram_neg_count, f"{int(round(gram_neg_count/total_isolates*100, 0))}%" if total_isolates > 0 else "0%")
    kpi4.metric("Số Lượng Gram Dương", gram_pos_count, f"{int(round(gram_pos_count/total_isolates*100, 0))}%" if total_isolates > 0 else "0%")

    # =========================================================
    # 6. GIAO DIỆN TABS TRÊN ỨNG DỤNG WEB
    # =========================================================
    main_tabs = st.tabs(["🦠 1. Mô hình bệnh & Xu hướng", "🗺️ 2. Bản đồ nhiệt (Heatmap)", "🚨 3. Giám sát Đa kháng (MDR)", "📋 4. Bảng số liệu chi tiết"])

    with main_tabs[0]:
        st.header("🦠 Cơ cấu phân lập Vi khuẩn")
        distribution_df = counts.copy()
        if len(distribution_df) > 6:
            plot_dist = pd.concat([distribution_df.iloc[:6], pd.DataFrame([{"Organism": "Vi khuẩn khác", "n": distribution_df.iloc[6:]["n"].sum()}])], ignore_index=True)
        else: plot_dist = distribution_df

        if not plot_dist.empty and plot_dist["n"].sum() > 0:
            fig_dist, ax_dist = plt.subplots(figsize=(10, 4))
            wedges, texts, autotexts = ax_dist.pie(plot_dist["n"], autopct='%1.0f%%', startangle=140, colors=sns.color_palette("Set3", len(plot_dist)), textprops=dict(color="black", weight="bold"))
            ax_dist.legend(wedges, plot_dist["Organism"], title="Vi khuẩn", loc="center left", bbox_to_anchor=(1, 0, 0.5, 1))
            plt.tight_layout()
            col_p1, col_p2 = st.columns([6, 4])
            with col_p1: st.pyplot(fig_dist)
            with col_p2: st.dataframe(distribution_df, use_container_width=True, hide_index=True)
            plt.close(fig_dist)

        st.markdown("---")
        st.header("📈 Xu hướng nhạy cảm qua các năm")
        pivot_trend = pivot.copy()
        pivot_trend["YEAR"] = pivot_trend["SPEC_DATE"].dt.year
        available_years = sorted(pivot_trend["YEAR"].unique())

        if len(available_years) >= 2:
            col_t1, col_t2 = st.columns(2)
            with col_t1: trend_org = st.selectbox("Chọn vi khuẩn:", options=sorted(pivot_trend["Organism"].unique()))
            with col_t2: trend_ab = st.selectbox("Chọn kháng sinh:", options=[c for c in antibiotic_cols if c in pivot_trend.columns])
            trend_data = []
            for yr in available_years:
                yr_df = pivot_trend[(pivot_trend["YEAR"] == yr) & (pivot_trend["Organism"] == trend_org)]
                if not yr_df.empty and trend_ab in yr_df.columns:
                    valid_test = yr_df[yr_df[trend_ab].isin(["S", "I", "R"])]
                    if len(valid_test) > 0: 
                        pct_val = int(round(((valid_test[trend_ab] == "S").sum() / len(valid_test)) * 100, 0))
                        trend_data.append({"Năm": str(yr), "% Nhạy cảm (%S)": pct_val, "Mẫu": len(valid_test)})
            trend_res_df = pd.DataFrame(trend_data)
            if not trend_res_df.empty:
                fig_trend, ax_trend = plt.subplots(figsize=(8, 3))
                sns.lineplot(data=trend_res_df, x="Năm", y="% Nhạy cảm (%S)", marker="o", color="#1E88E5", ax=ax_trend)
                for idx, r_t in trend_res_df.iterrows(): ax_trend.text(r_t["Năm"], r_t["% Nhạy cảm (%S)"] + 4, f"{r_t['% Nhạy cảm (%S)']}% (n={r_t['Mẫu']})", ha="center", fontsize=8, weight="bold")
                ax_trend.set_ylim(0, 120)
                st.pyplot(fig_trend)
                plt.close(fig_trend)

    with main_tabs[1]:
        st.header("🗺️ Bản đồ nhiệt nhạy cảm kháng sinh")
        def prepare_heatmap_matrix(df, ab_cols, ir_list):
            if df.empty: return pd.DataFrame(), pd.DataFrame()
            annot_raw = df.set_index("Vi khuẩn")[ab_cols].fillna("").astype(str)
            annot_display = annot_raw.copy()
            data_numeric = pd.DataFrame(np.nan, index=annot_raw.index, columns=annot_raw.columns)
            for org in annot_raw.index:
                org_lower = str(org).strip().lower()
                for ab in annot_raw.columns:
                    ab_lower = str(ab).strip().lower()
                    ab_full = WHONET_ABX_MAP.get(ab_lower[:3], ab_lower) # Áp dụng từ điển dịch tên
                    val_str = annot_raw.at[org, ab].strip()
                    is_intrinsic = any(
                        (r_org in org_lower or org_lower in r_org) and 
                        (r_ab in ab_lower or ab_lower in r_ab or r_ab in ab_full or ab_full in r_ab) 
                        for r_org, r_ab in ir_list
                    )
                    if is_intrinsic:
                        annot_display.at[org, ab] = "0%"
                        data_numeric.at[org, ab] = 0.0
                    elif val_str and val_str != "-":
                        try:
                            pct_val = float(val_str.split("%")[0])
                            annot_display.at[org, ab] = f"{int(pct_val)}%"
                            data_numeric.at[org, ab] = pct_val
                        except: annot_display.at[org, ab] = ""
                    else: annot_display.at[org, ab] = ""
            return data_numeric, annot_display

        def get_custom_cmap():
            colors = []
            for i in range(101):
                if i >= 90: colors.append("#4CAF50")
                elif i >= 70: colors.append("#FFEB3B")
                else: colors.append("#F44336")
            return ListedColormap(colors)

        common_org_list = common_orgs_abg["Vi khuẩn"].tolist() if not common_orgs_abg.empty else []
        g_neg_h = gram_negative_abg[gram_negative_abg["Vi khuẩn"].isin(common_org_list)] if not gram_negative_abg.empty else pd.DataFrame()
        g_pos_h = gram_positive_abg[gram_positive_abg["Vi khuẩn"].isin(common_org_list)] if not gram_positive_abg.empty else pd.DataFrame()

        for target_df, t_title in [(g_neg_h, "Gram Âm"), (g_pos_h, "Gram Dương")]:
            if not target_df.empty:
                h_data, h_annot = prepare_heatmap_matrix(target_df, antibiotic_cols, intrinsic_rules)
                active_cols = h_data.dropna(how='all', axis=1).columns.tolist()
                if active_cols:
                    fig, ax = plt.subplots(figsize=(max(12, len(active_cols) * 0.7), max(4, len(h_data) * 0.7)))
                    sns.heatmap(h_data[active_cols], annot=h_annot[active_cols], fmt="", cmap=get_custom_cmap(), vmin=0.0, vmax=100.0, linewidths=1.5, linecolor="#ffffff", ax=ax, annot_kws={"fontsize": 9, "weight": "bold"})
                    plt.xticks(rotation=45, ha='right')
                    plt.tight_layout()
                    st.subheader(f"📊 Heatmap {t_title} (n ≥ 30)")
                    st.pyplot(fig)
                    plt.close(fig)

    with main_tabs[2]:
        st.header("🚨 Hệ thống Cảnh báo Cách ly Dịch tễ")
        gram_neg_groups = {
            "Cephalosporins": ["CAZ", "CRO", "FEP", "CTX", "CXM"], 
            "Carbapenems": ["IPM", "MEM", "ETP", "DOR"], 
            "Fluoroquinolones": ["CIP", "LVX", "MXF"], 
            "Aminoglycosides": ["GEN", "AMK", "TOB"], 
            "Beta-lactam/Inhibitor": ["TZP", "SAM", "AMC"]
        }
        gram_pos_groups = {
            "Penicillins/Beta-lactamase": ["OXA", "FOX", "PEN", "AMP"], 
            "Fluoroquinolones": ["CIP", "LVX", "MXF"], 
            "Glycopeptides": ["VAN", "TEC"], 
            "Macrolides/Lincosamides": ["ERY", "CLI"], 
            "Folate Pathway": ["SXT"]
        }
        
        advanced_mdr_rows = []
        list_neg_orgs = set(gram_negative_abg["Vi khuẩn"].values) if not gram_negative_abg.empty else set()
        col_mapping = {c.upper().strip(): c for c in pivot.columns}

        for _, row in pivot.iterrows():
            org_name = str(row["Organism"])
            org_lower = org_name.lower()
            is_neg = org_name in list_neg_orgs
            target_groups = gram_neg_groups if is_neg else gram_pos_groups
            groups_tested, groups_resistant, total_drugs_tested, total_drugs_resistant = 0, 0, 0, 0
            
            for grp_name, drugs in target_groups.items():
                valid_drugs = []
                for drg in drugs:
                    drg_lower = drg.lower()
                    drg_full = WHONET_ABX_MAP.get(drg_lower[:3], drg_lower) # Áp dụng từ điển dịch tên
                    
                    is_intrinsic = any(
                        (r_org in org_lower or org_lower in r_org) and 
                        (r_ab in drg_lower or drg_lower in r_ab or r_ab in drg_full or drg_full in r_ab) 
                        for r_org, r_ab in intrinsic_rules
                    )
                    
                    if not is_intrinsic:
                        # Tìm cả mã 3 chữ (CAZ) HOẶC tên đầy đủ đã được dịch (CEFTAZIDIME)
                        real_col = col_mapping.get(drg.upper()) or col_mapping.get(drg_full.upper())
                        if real_col: valid_drugs.append(real_col)
                        
                tested_in_group = [drg for drg in valid_drugs if drg in row and row[drg] in ["S", "I", "R"]]
                if tested_in_group:
                    groups_tested += 1
                    total_drugs_tested += len(tested_in_group)
                    if any(row[drg] == "R" for drg in tested_in_group): groups_resistant += 1
                    total_drugs_resistant += sum(1 for drg in tested_in_group if row[drg] == "R")
            
            status, icon = "Thường", "🟢"
            if groups_tested >= 3:
                if total_drugs_tested > 0 and total_drugs_resistant == total_drugs_tested: status, icon = "🚨 PDR", "💀"
                elif (groups_tested - groups_resistant) <= 1 and groups_resistant >= 3: status, icon = "🟠 XDR", "💥"
                elif groups_resistant >= 3: status, icon = "🟡 MDR", "⚠️"
            
            phenotypes = []
            c_oxa = col_mapping.get("OXA", col_mapping.get("FOX"))
            c_van = col_mapping.get("VAN")
            c_carb = [col_mapping.get(x) for x in ["IPM", "MEM", "ETP"] if col_mapping.get(x)]
            
            if "staphylococcus aureus" in org_name.lower() and c_oxa and row.get(c_oxa) == "R": phenotypes.append("MRSA")
            if "enterococcus" in org_name.lower() and c_van and row.get(c_van) == "R": phenotypes.append("VRE")
            if is_neg and any(row.get(c) == "R" for c in c_carb if c): phenotypes.append("CRE")
            
            if phenotypes:
                if "Thường" in status:
                    status = "Cảnh báo"
                    icon = "🔴"
                status += f" [{', '.join(phenotypes)}]"

            if groups_resistant >= 1 or "Thường" not in status:
                advanced_mdr_rows.append({
                    "Mã BN": row["PID"], "Vi khuẩn": org_name, 
                    "Khoa phòng": f"{row['WARD']} — {ward_to_dept.get(row['WARD'], '')}", 
                    "Bệnh phẩm": spec_translation.get(row['SPEC_TYPE'].lower(), row['SPEC_TYPE']), 
                    "Ngày cấy": row["SPEC_DATE"].strftime('%Y-%m-%d') if pd.notna(row["SPEC_DATE"]) else "N/A", 
                    "Nhóm Kháng/Thử": f"{groups_resistant} / {groups_tested}", "Phân loại": f"{icon} {status}"
                })

        report_mdr_df = pd.DataFrame(advanced_mdr_rows)
        if not report_mdr_df.empty: st.dataframe(report_mdr_df, use_container_width=True, hide_index=True)
        else: st.success("🎉 Không phát hiện chủng siêu kháng thuốc nào.")

    with main_tabs[3]:
        st.header("📋 Chi tiết bảng Kháng sinh đồ tích lũy (CLSI M39)")
        def drop_redundant_cols(df): return df.drop(columns=[c for c in ["Organism", "Gram"] if c in df.columns]).fillna("-") if not df.empty else pd.DataFrame()
        s_tab1, s_tab2, s_tab3, s_tab4, s_tab5 = st.tabs(["📊 Toàn viện", "🔴 Gram Âm", "🔵 Gram Dương", "🟢 Thường gặp (n ≥ 30)", "🟡 Ít gặp (n < 30)"])
        with s_tab1: st.dataframe(drop_redundant_cols(antibiogram), use_container_width=True, hide_index=True)
        with s_tab2: st.dataframe(drop_redundant_cols(gram_negative_abg), use_container_width=True, hide_index=True)
        with s_tab3: st.dataframe(drop_redundant_cols(gram_positive_abg), use_container_width=True, hide_index=True)
        with s_tab4: st.dataframe(drop_redundant_cols(common_orgs_abg), use_container_width=True, hide_index=True)
        with s_tab5: st.dataframe(drop_redundant_cols(rare_orgs_abg), use_container_width=True, hide_index=True)

    # =========================================================
    # 7. KHỐI KẾT XUẤT EXCEL THẨM MỸ ĐỒ HỌA CAO CẤP
    # =========================================================
    st.markdown("---")
    st.header("📥 Xuất Bản Báo Cáo Nghiên Cứu")
    
    def generate_excel_report():
        output_buffer = BytesIO()
        
        sheets_to_write = [
            ("Antibiogram_ToanVien", antibiogram),
            ("Gram_Am", gram_negative_abg),
            ("Gram_Duong", gram_positive_abg),
            ("Thuong_Gap", common_orgs_abg),
            ("It_Gap", rare_orgs_abg),
            ("Ca_Cach_Ly_MDR", report_mdr_df)
        ]
        
        for w in selected_wards:
            ward_pivot = pivot[pivot["WARD"] == w]
            if not ward_pivot.empty:
                ward_abg = calculate_antibiogram(ward_pivot, counts["Organism"].tolist(), antibiotic_cols, intrinsic_rules)
                sheets_to_write.append((f"Khoa_{w}", ward_abg))
                
        with pd.ExcelWriter(output_buffer, engine='xlsxwriter') as writer:
            workbook = writer.book
            
            header_format = workbook.add_format({
                'bold': True, 'text_wrap': True, 'valign': 'vcenter', 'align': 'center',
                'fg_color': '#1F4E78', 'font_color': 'white', 'font_name': 'Segoe UI', 'font_size': 11, 'border': 1
            })
            cell_center = workbook.add_format({'align': 'center', 'valign': 'vcenter', 'font_name': 'Segoe UI', 'font_size': 10, 'border': 1})
            cell_left = workbook.add_format({'align': 'left', 'valign': 'vcenter', 'font_name': 'Segoe UI', 'font_size': 10, 'border': 1})
            
            green_format = workbook.add_format({'bg_color': '#C6EFCE', 'font_color': '#006100', 'align': 'center', 'valign': 'vcenter', 'font_name': 'Segoe UI', 'border': 1})
            yellow_format = workbook.add_format({'bg_color': '#FFEB9C', 'font_color': '#9C6500', 'align': 'center', 'valign': 'vcenter', 'font_name': 'Segoe UI', 'border': 1})
            red_format = workbook.add_format({'bg_color': '#FFC7CE', 'font_color': '#9C0006', 'align': 'center', 'valign': 'vcenter', 'font_name': 'Segoe UI', 'border': 1})

            for sheet_name, df_to_write in sheets_to_write:
                if df_to_write.empty: continue
                
                clean_name = clean_sheet_name(sheet_name)
                df_clean = df_to_write.copy()
                if "Gram" in df_clean.columns and clean_name != "Antibiogram_ToanVien":
                    df_clean = df_clean.drop(columns=["Gram"])
                df_clean = df_clean.fillna("-")
                
                df_clean.to_excel(writer, sheet_name=clean_name, index=False, startrow=0)
                worksheet = writer.sheets[clean_name]
                worksheet.hide_gridlines(0) 
                
                for col_num, column_title in enumerate(df_clean.columns):
                    worksheet.write(0, col_num, column_title, header_format)
                worksheet.set_row(0, 28)
                
                for col_num, column_title in enumerate(df_clean.columns):
                    max_len = max(df_clean[column_title].astype(str).map(len).max(), len(str(column_title))) + 4
                    if column_title in ["Vi khuẩn", "Khoa phòng", "Bệnh phẩm"]:
                        worksheet.set_column(col_num, col_num, max_len, cell_left)
                    else: worksheet.set_column(col_num, col_num, max_len, cell_center)
                
                for row_idx in range(1, len(df_clean) + 2): worksheet.set_row(row_idx, 20)
                
                if clean_name in ["Ca_Cach_Ly_MDR"]: worksheet.freeze_panes(1, 0)
                else: worksheet.freeze_panes(1, 2)
                
                if clean_name != "Ca_Cach_Ly_MDR":
                    for row_idx in range(len(df_clean)):
                        for col_idx, col_name in enumerate(df_clean.columns):
                            if col_name in ["Vi khuẩn", "Số lượng n", "Gram"]: continue
                            val = str(df_clean.iloc[row_idx][col_name])
                            if "%" in val:
                                try:
                                    pct = int(val.split("%")[0])
                                    if pct >= 90: worksheet.write(row_idx + 1, col_idx, val, green_format)
                                    elif pct >= 70: worksheet.write(row_idx + 1, col_idx, val, yellow_format)
                                    else: worksheet.write(row_idx + 1, col_idx, val, red_format)
                                except: pass
                                    
        return output_buffer.getvalue()

    st.download_button(
        label="📥 TẢI XUỐNG BÁO CÁO EXCEL CAO CẤP (Đã định dạng chuyên nghiệp)", 
        data=generate_excel_report(), 
        file_name="WHONET_Antibiogram_Professional_Report.xlsx", 
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )
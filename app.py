import streamlit as st
import requests
from bs4 import BeautifulSoup
import re
from PIL import Image, ImageDraw
import pandas as pd
import sqlite3
import datetime
import io
from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas

# =========================================================================================
# PAGE CONFIGURATION
# =========================================================================================
st.set_page_config(
    page_title="OmniMetrology AI | National Legal Metrology Enforcement Portal",
    layout="wide",
    page_icon="⚖️",
    initial_sidebar_state="expanded"
)

# =========================================================================================
# OFFLINE AI ASSISTANT — 100% free, no API key, no paid service of any kind.
# Rule-based keyword matching against a Legal Metrology knowledge base.
# =========================================================================================
LLM_ENABLED = False

# =========================================================================================
# RULE-BASED ASSISTANT (works with zero API keys, zero cost, zero setup)
# =========================================================================================
RULE_BASED_KB = [
    (["mrp", "maximum retail price"],
     "Under Rule 6 of the Legal Metrology (Packaged Commodities) Rules, 2011, every pre-packaged "
     "commodity must declare the Maximum Retail Price inclusive of all taxes, in the format "
     "'MRP Rs. ___ (inclusive of all taxes)'."),
    (["net quantity", "net qty", "net weight"],
     "Net quantity must be declared in standard units (grams/kilograms for solids, "
     "millilitres/litres for liquids) in a specific font size proportional to the package's "
     "principal display area, per Rule 6 and the Second Schedule."),
    (["unit sale price", "usp"],
     "The Unit Sale Price (price per standard unit, e.g., price per kg or per litre) must be "
     "declared so consumers can compare value across pack sizes, under Rule 6(1)(f)."),
    (["manufacturer", "packer", "marketed by", "mfd by"],
     "The name and complete address of the manufacturer, packer, or importer must be declared "
     "under Rule 6(1)(a)(i). This is where the PIN code declaration is checked in this portal."),
    (["country of origin", "made in"],
     "Country of origin must be declared for all imported pre-packaged commodities, and is now "
     "increasingly required as good practice for domestic goods too, per Rule 6(1)(a) read with "
     "Legal Metrology Rules & Consumer Protection e-commerce guidelines."),
    (["expiry", "best before", "mfg date", "manufacturing date"],
     "Month and year of manufacture/packing and, where applicable, the 'best before' or expiry "
     "date must be declared under Rule 6(1)(e)."),
    (["pin code", "pincode", "postal code"],
     "A valid 6-digit PIN code as part of the manufacturer/packer address is required so "
     "consumers and enforcement officers can identify the responsible entity's jurisdiction. "
     "This portal treats a missing or structurally invalid PIN as a standalone 'dual violation' "
     "in addition to any other missing fields."),
    (["shrinkflation", "quantity reduced", "less quantity same price"],
     "Shrinkflation — reducing net quantity while keeping price constant without clear disclosure "
     "— is scrutinised under fair trade practice provisions. This portal flags it whenever the "
     "audited net weight is lower than the previously declared net weight for the same product."),
    (["dual violation"],
     "A 'Dual Violation' in this portal means the routing engine could not find a valid, "
     "structurally correct PIN code in the product's declared information. That is flagged as a "
     "violation of the address-declaration requirement (Rule 6) *independently* of whichever "
     "other statutory fields (MRP, net quantity, etc.) are missing."),
    (["how does routing work", "officer routing", "how is the officer assigned"],
     "The enforcement routing engine works in layers: (1) an exact valid PIN code maps straight "
     "to the district officer, (2) a structurally valid but unmapped PIN falls back to the "
     "selected zonal command, (3) a missing/invalid PIN triggers a Dual Violation and the engine "
     "tries to match a city name in the text, (4) failing that, e-commerce listings route to the "
     "platform's registered nodal officer, and (5) as a last resort everything routes to the "
     "default zonal headquarters you picked in the sidebar."),
    (["compliance score", "how is score calculated"],
     "The compliance score is the percentage of statutory checks passed out of all checks run "
     "(MRP, unit sale price, net quantity, manufacturer details, country of origin, expiry/mfg "
     "date, and — when a routing result is available — valid PIN code declaration)."),
    (["what can you do", "help", "what is this portal", "who are you"],
     "I'm the offline OmniMetrology Assistant. I can explain Legal Metrology rules (MRP, net "
     "quantity, manufacturer address, PIN codes, expiry dates, country of origin), explain "
     "shrinkflation and dual violations, explain how officer routing works, and answer questions "
     "about your most recent audit if you've run one in another tab. I run fully offline with no "
     "external API or cost."),
    (["penalty", "fine", "punishment", "notice"],
     "This portal generates a demonstration Legal Metrology penalty notice PDF whenever an audit "
     "is non-compliant, listing the missing statutory fields and the routed enforcement officer. "
     "In a real deployment, actual penalty amounts and procedures would follow the Legal "
     "Metrology Act, 2009 and state-level enforcement rules."),
    (["e-commerce", "online seller", "amazon", "flipkart", "blinkit"],
     "For online listings, this portal scrapes the product page text and runs the same statutory "
     "checks as physical packaging. If no valid PIN code is found in the listing or seller "
     "address, it falls back to routing the alert to the platform's registered nodal grievance "
     "officer instead of a specific district."),
]

def text_to_speech_bytes(text, lang="en"):
    """Converts text to spoken audio using gTTS (free, no API key). Returns MP3 bytes or None."""
    try:
        from gtts import gTTS
        clean_text = re.sub(r"[*_#`]", "", text)[:600]  # strip markdown, cap length
        tts = gTTS(text=clean_text, lang=lang)
        buf = io.BytesIO()
        tts.write_to_fp(buf)
        buf.seek(0)
        return buf.read()
    except Exception:
        return None

def rule_based_answer(question):
    q = question.lower()
    best_match, best_score = None, 0
    for keywords, answer in RULE_BASED_KB:
        score = sum(1 for k in keywords if k in q)
        if score > best_score:
            best_score, best_match = score, answer
    if best_match:
        return best_match
    return (
        "I don't have a specific rule matched for that in offline mode. Try asking about MRP, "
        "net quantity, unit sale price, manufacturer address, country of origin, expiry dates, "
        "PIN code declaration, shrinkflation, dual violations, or how officer routing works. "
        "For open-ended questions, enable the LLM assistant by adding an ANTHROPIC_API_KEY to "
        "your Streamlit secrets."
    )

# =========================================================================================
# DATABASE LAYER (with safe migration for the new routing/pincode columns)
# =========================================================================================
DB_PATH = "metrology_audit.db"

def init_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS audit_logs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT,
                    source TEXT,
                    item_name TEXT,
                    vendor TEXT,
                    region TEXT,
                    score REAL,
                    status TEXT,
                    missing_count INTEGER
                )''')
    conn.commit()

    new_columns = {
        "pincode": "TEXT",
        "pincode_valid": "TEXT",
        "district": "TEXT",
        "officer_name": "TEXT",
        "officer_phone": "TEXT",
        "routing_method": "TEXT",
        "dual_violation": "TEXT",
    }
    c.execute("PRAGMA table_info(audit_logs)")
    existing_cols = {row[1] for row in c.fetchall()}
    for col, coltype in new_columns.items():
        if col not in existing_cols:
            try:
                c.execute(f"ALTER TABLE audit_logs ADD COLUMN {col} {coltype}")
            except sqlite3.OperationalError:
                pass
    conn.commit()
    conn.close()

init_db()

def log_audit_to_db(source, item_name, vendor, region, score, status, missing_count,
                     pincode="N/A", pincode_valid="N/A", district="N/A",
                     officer_name="N/A", officer_phone="N/A", routing_method="N/A",
                     dual_violation="No"):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    c.execute("""INSERT INTO audit_logs
                (timestamp, source, item_name, vendor, region, score, status, missing_count,
                 pincode, pincode_valid, district, officer_name, officer_phone, routing_method, dual_violation)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
              (ts, source, item_name, vendor, region, score, status, missing_count,
               pincode, pincode_valid, district, officer_name, officer_phone, routing_method, dual_violation))
    conn.commit()
    conn.close()

def get_db_logs():
    conn = sqlite3.connect(DB_PATH)
    df = pd.read_sql_query("SELECT * FROM audit_logs ORDER BY id DESC", conn)
    conn.close()
    return df

# =========================================================================================
# PREMIUM "GOVERNMENT + APPLE" LIGHT THEME
# =========================================================================================
st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&family=Poppins:wght@600;700;800&display=swap');

html, body, [class*="css"]  {
    font-family: 'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
}
.stApp {
    background: linear-gradient(180deg, #f7f9fc 0%, #eef1f7 100%);
    color: #0f172a;
}
.tricolor-strip {
    height: 6px; width: 100%;
    background: linear-gradient(90deg, #FF9933 0%, #FF9933 33%, #FFFFFF 33%, #FFFFFF 66%, #138808 66%, #138808 100%);
    border-radius: 4px; margin-bottom: 18px;
}
.sih-header {
    background: #ffffff; border: 1px solid #e2e8f0; border-left: 8px solid #1e3a8a;
    padding: 28px 32px; border-radius: 18px; margin-bottom: 26px;
    box-shadow: 0 10px 30px -12px rgba(15, 23, 42, 0.15);
}
.sih-title { font-family: 'Poppins', sans-serif; font-size: 2.1rem; font-weight: 800; color: #0f172a; margin: 0; letter-spacing: -0.5px; }
.sih-sub { font-size: 1rem; font-weight: 500; color: #334155; margin-top: 8px; }
.badge-row { margin-top: 14px; }
.gov-badge {
    display: inline-block; background: #eff6ff; color: #1e3a8a; border: 1px solid #bfdbfe;
    font-weight: 700; font-size: 0.78rem; padding: 5px 12px; border-radius: 999px; margin-right: 8px;
}
h1, h2, h3, h4 { font-family: 'Poppins', sans-serif; color: #0f172a !important; font-weight: 700 !important; }
p, li, span, label, div { color: #1e293b; }
.stMarkdown, .stText { color: #1e293b !important; }
.glass-card {
    background: #ffffff; border: 1px solid #e2e8f0; border-radius: 16px; padding: 20px 22px;
    box-shadow: 0 8px 24px -14px rgba(15,23,42,0.18); margin-bottom: 14px;
}
.routing-card {
    background: #f8fafc; border: 1px solid #cbd5e1; border-left: 6px solid #1e3a8a;
    border-radius: 14px; padding: 18px 20px; margin: 10px 0 16px 0;
}
.routing-card b { color: #0f172a; }
.dual-violation-banner {
    background: #fef2f2; border: 1px solid #fecaca; border-left: 6px solid #dc2626;
    border-radius: 14px; padding: 16px 20px; color: #991b1b; font-weight: 700; margin-bottom: 14px;
}
.clean-pin-banner {
    background: #f0fdf4; border: 1px solid #bbf7d0; border-left: 6px solid #16a34a;
    border-radius: 14px; padding: 16px 20px; color: #14532d; font-weight: 700; margin-bottom: 14px;
}
.chat-bubble-user {
    background: #eff6ff; border: 1px solid #bfdbfe; border-radius: 14px 14px 2px 14px;
    padding: 12px 16px; margin: 6px 0; color: #1e3a8a; font-weight: 600;
}
.chat-bubble-ai {
    background: #ffffff; border: 1px solid #e2e8f0; border-radius: 14px 14px 14px 2px;
    padding: 12px 16px; margin: 6px 0; color: #1e293b;
}
.mode-pill {
    display: inline-block; font-size: 0.75rem; font-weight: 700; padding: 4px 10px;
    border-radius: 999px; margin-bottom: 10px;
}
.mode-pill-llm { background: #ecfdf5; color: #065f46; border: 1px solid #a7f3d0; }
.mode-pill-rule { background: #fffbeb; color: #92400e; border: 1px solid #fde68a; }
div[data-testid="stMetric"] {
    background: #ffffff; border: 1px solid #e2e8f0; border-radius: 14px; padding: 14px 16px;
    box-shadow: 0 6px 18px -12px rgba(15,23,42,0.15);
}
div[data-testid="stMetricValue"] { font-size: 1.9rem !important; font-weight: 800 !important; color: #1e3a8a !important; }
div[data-testid="stMetricLabel"] { color: #475569 !important; font-weight: 600 !important; }
.stButton>button {
    background: linear-gradient(90deg, #1e3a8a 0%, #1d4ed8 100%) !important; color: #ffffff !important;
    font-weight: 700 !important; border-radius: 10px !important; border: none !important;
    padding: 12px 26px !important; transition: all 0.2s ease !important;
    box-shadow: 0 6px 18px -6px rgba(29, 78, 216, 0.5) !important;
}
.stButton>button:hover { transform: translateY(-1px) !important; box-shadow: 0 10px 22px -6px rgba(29, 78, 216, 0.65) !important; }
.stDownloadButton>button {
    background: linear-gradient(90deg, #b91c1c 0%, #dc2626 100%) !important; color: #ffffff !important;
    font-weight: 700 !important; border-radius: 10px !important; border: none !important;
}
.stTabs [data-baseweb="tab"] { font-weight: 700; color: #334155; }
.stTabs [aria-selected="true"] { color: #1e3a8a !important; border-bottom-color: #1e3a8a !important; }
section[data-testid="stSidebar"] { background: #0f172a; }
section[data-testid="stSidebar"] * { color: #f1f5f9 !important; }
section[data-testid="stSidebar"] input, section[data-testid="stSidebar"] select { color: #0f172a !important; }
[data-testid="stDataFrame"] { border-radius: 12px; overflow: hidden; }
</style>
""", unsafe_allow_html=True)

# =========================================================================================
# PIN-CODE → DISTRICT / OFFICER ROUTING ENGINE
# =========================================================================================
PIN_DISTRICT_MAP = {
    "636": {"district": "Salem",           "state": "Tamil Nadu",     "zone": "South Zone (Bengaluru)",  "officer_name": "Insp. R. Kumar",        "officer_phone": "+914272212345"},
    "600": {"district": "Chennai",         "state": "Tamil Nadu",     "zone": "South Zone (Bengaluru)",  "officer_name": "Insp. S. Priya",        "officer_phone": "+914428451234"},
    "560": {"district": "Bengaluru Urban", "state": "Karnataka",      "zone": "South Zone (Bengaluru)",  "officer_name": "Insp. M. Gowda",        "officer_phone": "+918022345678"},
    "682": {"district": "Ernakulam",       "state": "Kerala",         "zone": "South Zone (Bengaluru)",  "officer_name": "Insp. A. Nair",         "officer_phone": "+914842345566"},
    "500": {"district": "Hyderabad",       "state": "Telangana",      "zone": "South Zone (Bengaluru)",  "officer_name": "Insp. K. Reddy",        "officer_phone": "+914023456789"},
    "110": {"district": "New Delhi",       "state": "Delhi",          "zone": "North Zone (Delhi)",      "officer_name": "Insp. V. Sharma",       "officer_phone": "+911123456789"},
    "201": {"district": "Ghaziabad",       "state": "Uttar Pradesh",  "zone": "North Zone (Delhi)",      "officer_name": "Insp. N. Tyagi",        "officer_phone": "+911204567890"},
    "226": {"district": "Lucknow",         "state": "Uttar Pradesh",  "zone": "North Zone (Delhi)",      "officer_name": "Insp. P. Yadav",        "officer_phone": "+915222345678"},
    "160": {"district": "Chandigarh",      "state": "Chandigarh",     "zone": "North Zone (Delhi)",      "officer_name": "Insp. H. Singh",        "officer_phone": "+911722345678"},
    "302": {"district": "Jaipur",          "state": "Rajasthan",      "zone": "North Zone (Delhi)",      "officer_name": "Insp. D. Meena",        "officer_phone": "+911412345678"},
    "400": {"district": "Mumbai",          "state": "Maharashtra",    "zone": "West Zone (Mumbai)",      "officer_name": "Insp. R. Patil",        "officer_phone": "+912223456789"},
    "411": {"district": "Pune",            "state": "Maharashtra",    "zone": "West Zone (Mumbai)",      "officer_name": "Insp. S. Deshmukh",     "officer_phone": "+912023456789"},
    "380": {"district": "Ahmedabad",       "state": "Gujarat",        "zone": "West Zone (Mumbai)",      "officer_name": "Insp. J. Patel",        "officer_phone": "+917923456789"},
    "700": {"district": "Kolkata",         "state": "West Bengal",    "zone": "East Zone (Kolkata)",     "officer_name": "Insp. A. Banerjee",     "officer_phone": "+913323456789"},
    "751": {"district": "Bhubaneswar",     "state": "Odisha",         "zone": "East Zone (Kolkata)",     "officer_name": "Insp. B. Mohanty",      "officer_phone": "+916742345678"},
    "781": {"district": "Guwahati",        "state": "Assam",          "zone": "East Zone (Kolkata)",     "officer_name": "Insp. D. Bora",         "officer_phone": "+913612345678"},
    "800": {"district": "Patna",           "state": "Bihar",          "zone": "East Zone (Kolkata)",     "officer_name": "Insp. R. Jha",          "officer_phone": "+916122345678"},
    "452": {"district": "Indore",          "state": "Madhya Pradesh", "zone": "Central Zone",            "officer_name": "Insp. A. Chouhan",      "officer_phone": "+917312345678"},
    "462": {"district": "Bhopal",          "state": "Madhya Pradesh", "zone": "Central Zone",            "officer_name": "Insp. M. Verma",        "officer_phone": "+917552345678"},
    "492": {"district": "Raipur",          "state": "Chhattisgarh",   "zone": "Central Zone",            "officer_name": "Insp. S. Sahu",         "officer_phone": "+917712345678"},
}
CITY_FALLBACK_MAP = {
    "salem": "636", "chennai": "600", "bengaluru": "560", "bangalore": "560",
    "kochi": "682", "ernakulam": "682", "hyderabad": "500", "delhi": "110",
    "ghaziabad": "201", "lucknow": "226", "chandigarh": "160", "jaipur": "302",
    "mumbai": "400", "pune": "411", "ahmedabad": "380", "kolkata": "700",
    "bhubaneswar": "751", "guwahati": "781", "patna": "800", "indore": "452",
    "bhopal": "462", "raipur": "492",
}
PLATFORM_HQ_MAP = {
    "amazon":    {"officer_name": "Nodal Officer — Amazon India HQ",    "officer_phone": "+911800120000", "district": "Amazon India Registered HQ"},
    "flipkart":  {"officer_name": "Nodal Officer — Flipkart HQ",        "officer_phone": "+918049049049", "district": "Flipkart Registered HQ"},
    "blinkit":   {"officer_name": "Nodal Officer — Blinkit HQ",         "officer_phone": "+911204020000", "district": "Blinkit Registered HQ"},
    "instamart": {"officer_name": "Nodal Officer — Swiggy Instamart HQ","officer_phone": "+918067466100", "district": "Instamart Registered HQ"},
    "myntra":    {"officer_name": "Nodal Officer — Myntra HQ",          "officer_phone": "+918067128000", "district": "Myntra Registered HQ"},
    "meesho":    {"officer_name": "Nodal Officer — Meesho HQ",          "officer_phone": "+918069999000", "district": "Meesho Registered HQ"},
}
ZONE_HQ_MAP = {
    "North Zone (Delhi)":      {"officer_name": "North Zone Central Command",   "officer_phone": "+911123000000"},
    "West Zone (Mumbai)":      {"officer_name": "West Zone Central Command",    "officer_phone": "+912223000000"},
    "South Zone (Bengaluru)":  {"officer_name": "South Zone Central Command",   "officer_phone": "+918022000000"},
    "East Zone (Kolkata)":     {"officer_name": "East Zone Central Command",    "officer_phone": "+913323000000"},
    "Central Zone":            {"officer_name": "Central Zone Command",         "officer_phone": "+917552000000"},
}

def _is_valid_pincode(pin):
    if not re.fullmatch(r"\d{6}", pin):
        return False
    if pin[0] not in "12345678":
        return False
    if len(set(pin)) == 1:
        return False
    return True

def resolve_officer(text, source_type="physical", selected_zone="North Zone (Delhi)"):
    text_l = text.lower()
    candidates = re.findall(r"\b\d{6}\b", text)
    valid_pins = [p for p in candidates if _is_valid_pincode(p)]

    result = {
        "pincode_found": valid_pins[0] if valid_pins else (candidates[0] if candidates else "Not Found"),
        "pincode_valid": bool(valid_pins),
        "dual_violation": False,
        "routing_method": None,
        "district": None, "state": None, "zone": None,
        "officer_name": None, "officer_phone": None,
    }

    if valid_pins:
        prefix = valid_pins[0][:3]
        if prefix in PIN_DISTRICT_MAP:
            info = PIN_DISTRICT_MAP[prefix]
            result.update(info)
            result["routing_method"] = "PIN_CODE_EXACT_MATCH"
            return result
        else:
            result["routing_method"] = "PIN_FORMAT_VALID_UNMAPPED_PREFIX"
            result["district"] = "Unmapped Prefix — Zonal Review Required"
            result["zone"] = selected_zone
            result.update(ZONE_HQ_MAP.get(selected_zone, ZONE_HQ_MAP["North Zone (Delhi)"]))
            return result

    result["dual_violation"] = True

    for city, prefix in CITY_FALLBACK_MAP.items():
        if city in text_l:
            info = PIN_DISTRICT_MAP[prefix]
            result.update(info)
            result["routing_method"] = "CITY_NAME_TEXT_FALLBACK"
            return result

    if source_type in ("web", "ecommerce", "bulk"):
        for platform, info in PLATFORM_HQ_MAP.items():
            if platform in text_l:
                result.update(info)
                result["zone"] = "Platform HQ (Non-Regional)"
                result["routing_method"] = "PLATFORM_HQ_FALLBACK"
                return result

    result.update(ZONE_HQ_MAP.get(selected_zone, ZONE_HQ_MAP["North Zone (Delhi)"]))
    result["district"] = "Unresolved — Manual Review"
    result["zone"] = selected_zone
    result["routing_method"] = "DEFAULT_ZONAL_HQ_FALLBACK"
    return result

# =========================================================================================
# COMPUTER VISION / OCR ENGINE
# -----------------------------------------------------------------------------------------
# Uses pytesseract (a thin wrapper around the Tesseract binary) instead of EasyOCR/torch.
# EasyOCR + torch together need well over 1GB RAM just to load the model, which reliably
# OOM-kills the process on Streamlit Community Cloud's free tier — that's what was showing
# up in the browser as a generic "reconnect failed" error (the server crashed mid-request).
# Tesseract has no ML model download and a tiny memory footprint, so it's the right fit here.
# Requires a system package: see packages.txt (tesseract-ocr) alongside requirements.txt.
# =========================================================================================
def enhance_and_annotate_image(pil_img_or_file):
    """
    Pure-PIL + Tesseract pipeline. Deliberately avoids OpenCV/numpy entirely for this
    step: no cv2 import, no full-resolution numpy arrays, no CLAHE/denoise/sharpen
    passes each holding their own full-size copy in memory. Tesseract works perfectly
    well on a modestly-sized, lightly-contrast-enhanced PIL image, and this whole
    pipeline now peaks at roughly ONE small image in memory at a time instead of 6-7
    full-resolution copies, which is what was crashing the 1GB Streamlit Cloud instance.
    """
    import pytesseract
    import shutil
    import gc
    from PIL import ImageOps, ImageFilter

    tess_path = shutil.which("tesseract")
    if tess_path:
        pytesseract.pytesseract.tesseract_cmd = tess_path
    else:
        raise RuntimeError(
            "TESSERACT_NOT_FOUND: the 'tesseract' binary is not installed on this server. "
            "This means packages.txt was not picked up — check that packages.txt sits in the "
            "SAME root folder as app.py and requirements.txt (not in a subfolder), that it "
            "contains exactly the line 'tesseract-ocr', and then fully reboot the app (Manage "
            "app -> Reboot), not just rerun it."
        )

    MAX_DIM = 1000  # plenty for OCR on packaging text; keeps memory tiny regardless of upload size

    if hasattr(pil_img_or_file, "seek"):
        pil_img_or_file.seek(0)
    gc.collect()

    pil_img = Image.open(pil_img_or_file)
    try:
        pil_img.draft("RGB", (MAX_DIM, MAX_DIM))  # JPEG: decode small directly, skips the big spike
    except Exception:
        pass

    pil_img = pil_img.convert("RGB")
    pil_img.thumbnail((MAX_DIM, MAX_DIM), Image.LANCZOS)  # in-place, no extra full-size copy

    # Lightweight contrast + sharpen using PIL only (no OpenCV, no numpy arrays)
    gray = ImageOps.grayscale(pil_img)
    gray = ImageOps.autocontrast(gray, cutoff=1)
    gray = gray.filter(ImageFilter.SHARPEN)

    data = pytesseract.image_to_data(gray, output_type=pytesseract.Output.DICT)
    del gray
    gc.collect()

    draw_img = pil_img.copy()
    draw = ImageDraw.Draw(draw_img)
    full_text = []

    compliance_keywords = ["mrp", "rs", "₹", "net", "qty", "g", "kg", "ml", "mfd", "exp", "manufactured", "origin", "pin"]

    n_boxes = len(data["text"])
    for i in range(n_boxes):
        text = data["text"][i].strip()
        conf = int(data["conf"][i]) if str(data["conf"][i]).lstrip("-").isdigit() else -1
        if not text or conf < 30:
            continue
        full_text.append(text)
        x, y, w, h = data["left"][i], data["top"][i], data["width"][i], data["height"][i]
        color = "#16a34a" if any(k in text.lower() for k in compliance_keywords) else "#d97706"
        draw.rectangle([x, y, x + w, y + h], outline=color, width=3)

    return " ".join(full_text), draw_img

# =========================================================================================
# METROLOGY RULE ENGINE
# =========================================================================================
def audit_legal_metrology(text_data, historical_qty=None, current_qty=None, pincode_valid=None):
    text = text_data.lower()
    checks = {
        "mrp_declared": bool(re.search(r'(mrp|maximum retail price|inclusive of all taxes|₹|\brs\.?\b|\binr\b)', text)),
        "unit_sale_price": bool(re.search(r'(\busp\b|unit sale price|per g|per kg|per ml|per l|/g|/kg|/ml|/l|\bprice per\b)', text)),
        "net_quantity": bool(re.search(r'\b\d+(\.\d+)?\s*(g|kg|ml|l|ltr|grams|kilograms|litres|pcs|units|pack of \d+)\b', text)),
        "manufacturer_details": bool(re.search(r'(manufactured by|mfd by|packed by|marketed by|mfg|address|mktd by|imported by)', text)),
        "country_of_origin": bool(re.search(r'(country of origin|made in|origin|manufactured in|country:)', text)),
        "expiry_or_mfg_date": bool(re.search(r'(expiry|exp date|best before|use by|mfd|date of mfg|use within|\bexp\b)', text)),
    }
    if pincode_valid is not None:
        checks["valid_pincode_declared"] = bool(pincode_valid)

    passed_rules = sum(checks.values())
    compliance_score = round((passed_rules / len(checks)) * 100, 2)

    shrinkflation_detected = False
    if historical_qty and current_qty and current_qty < historical_qty:
        shrinkflation_detected = True

    return {
        "compliance_score": compliance_score,
        "is_compliant": compliance_score == 100 and not shrinkflation_detected,
        "checks": checks,
        "shrinkflation": shrinkflation_detected
    }

# =========================================================================================
# PDF PENALTY NOTICE GENERATOR
# =========================================================================================
def generate_pdf_notice(product_name, vendor, score, missing, routing=None):
    buffer = io.BytesIO()
    p = canvas.Canvas(buffer, pagesize=letter)
    p.setFont("Helvetica-Bold", 16)
    p.drawString(50, 750, "GOVERNMENT OF INDIA — LEGAL METROLOGY NOTICE")
    p.setFont("Helvetica", 10)
    p.drawString(50, 735, "Issued under Legal Metrology (Packaged Commodities) Rules, 2011")
    p.line(50, 725, 550, 725)

    p.drawString(50, 705, f"Target Entity / Vendor: {vendor}")
    p.drawString(50, 690, f"Product Description: {product_name[:55]}")
    p.drawString(50, 675, f"Audit Score: {score}%")
    p.drawString(50, 660, f"Timestamp: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

    y = 640
    if routing:
        p.setFont("Helvetica-Bold", 11)
        p.drawString(50, y, "Enforcement Routing")
        y -= 16
        p.setFont("Helvetica", 10)
        p.drawString(60, y, f"District/Region: {routing.get('district', 'N/A')}")
        y -= 15
        p.drawString(60, y, f"Assigned Officer: {routing.get('officer_name', 'N/A')} ({routing.get('officer_phone', 'N/A')})")
        y -= 15
        p.drawString(60, y, f"Routing Method: {routing.get('routing_method', 'N/A')}")
        y -= 25

    if routing and routing.get("dual_violation"):
        p.setFont("Helvetica-Bold", 11)
        p.drawString(50, y, "*** DUAL VIOLATION PENALTY FLAG ***")
        y -= 15
        p.setFont("Helvetica", 9)
        p.drawString(60, y, "Missing/Invalid PIN Code Declaration — Rule 6, Legal Metrology")
        y -= 13
        p.drawString(60, y, "(Packaged Commodities) Rules, 2011. Escalated via fallback routing.")
        y -= 25

    p.setFont("Helvetica-Bold", 12)
    p.drawString(50, y, "Statutory Non-Compliance Breakdown:")
    y -= 20
    p.setFont("Helvetica", 10)
    for m in missing:
        p.drawString(70, y, f"• Missing Requirement: {m.replace('_', ' ').title()}")
        y -= 18

    p.setFont("Helvetica-Oblique", 9)
    p.drawString(50, y - 25, "Automated Enforcement Notice generated by OmniMetrology AI — Prototype for demonstration.")
    p.showPage()
    p.save()
    buffer.seek(0)
    return buffer

def scrape_url(url):
    headers = {"User-Agent": "Mozilla/5.0"}
    try:
        res = requests.get(url, headers=headers, timeout=8)
        soup = BeautifulSoup(res.content, "html.parser")
        return {"status": True, "title": soup.title.string if soup.title else "E-Commerce Item", "text": soup.get_text(separator=" ")}
    except Exception as e:
        return {"status": False, "error": str(e)}

def render_routing_card(routing):
    if routing.get("dual_violation"):
        st.markdown(f"""
        <div class="dual-violation-banner">
            🚨 DUAL VIOLATION FLAGGED: Missing or invalid PIN code declaration on packaging/listing.
            This is a separate statutory violation under Legal Metrology Rule 6, in addition to any
            missing-field violations below. Routing has escalated via fallback: <b>{routing.get('routing_method')}</b>.
        </div>
        """, unsafe_allow_html=True)
    else:
        st.markdown(f"""
        <div class="clean-pin-banner">
            ✅ Valid PIN code detected ({routing.get('pincode_found')}) — routed by exact address match.
        </div>
        """, unsafe_allow_html=True)

    st.markdown(f"""
    <div class="routing-card">
        <b>📍 Enforcement Routing</b><br>
        District / Region: <b>{routing.get('district', 'N/A')}</b> &nbsp;|&nbsp;
        Zone: <b>{routing.get('zone', 'N/A')}</b><br>
        Assigned Officer: <b>{routing.get('officer_name', 'N/A')}</b> &nbsp;|&nbsp;
        Contact: <b>{routing.get('officer_phone', 'N/A')}</b><br>
        Routing Method: <b>{routing.get('routing_method', 'N/A')}</b>
    </div>
    """, unsafe_allow_html=True)

# =========================================================================================
# HEADER
# =========================================================================================
st.markdown('<div class="tricolor-strip"></div>', unsafe_allow_html=True)
st.markdown("""
<div class="sih-header">
    <div class="sih-title">⚖️ OmniMetrology AI — National Enforcement Portal</div>
    <div class="sih-sub">AI-Powered Legal Metrology Compliance, Shrinkflation Detection & District-Level Enforcement Routing</div>
    <div class="badge-row">
        <span class="gov-badge">Legal Metrology (Packaged Commodities) Rules, 2011</span>
        <span class="gov-badge">Smart India Hackathon</span>
        <span class="gov-badge">Prototype Build</span>
    </div>
</div>
""", unsafe_allow_html=True)

# =========================================================================================
# SIDEBAR
# =========================================================================================
st.sidebar.title("🚨 Officer Dispatch Control")
st.sidebar.caption("Used as the fallback zone when a PIN code cannot be resolved automatically.")
officer_region = st.sidebar.selectbox("Default Fallback Zone:", list(ZONE_HQ_MAP.keys()))
officer_phone = st.sidebar.text_input("Manual Override — Officer Mobile:", value="+919876543210")
vendor_email = st.sidebar.text_input("Vendor Legal Contact:", value="legal@vendor-corp.com")
st.sidebar.markdown("---")
st.sidebar.caption("📍 District-level routing is automatic: the AI reads the PIN code from the package or listing and dispatches the alert to the local officer — not the whole zone.")
st.sidebar.markdown("---")
st.sidebar.info("🤖 AI Assistant: Offline rule-based mode\n\nNo API key, no cost. Answers Legal Metrology questions and reads them aloud.")

tab_dash, tab_web, tab_ocr, tab_fraud, tab_bulk, tab_ai = st.tabs([
    "📈 Command Center",
    "🌐 E-Commerce Web Audit",
    "📸 Physical Vision OCR",
    "📊 Fraud & Shrinkflation",
    "📂 Bulk CSV Inventory",
    "🤖 AI Assistant"
])

# --- TAB 1: COMMAND CENTER ---
with tab_dash:
    st.markdown("### 🏛️ Real-Time National Enforcement Overview")
    logs_df = get_db_logs()

    if not logs_df.empty:
        m1, m2, m3, m4, m5 = st.columns(5)
        m1.metric("Total Audits", len(logs_df))
        m2.metric("Mean Compliance", f"{round(logs_df['score'].mean(), 1)}%")
        m3.metric("Non-Compliant", len(logs_df[logs_df["status"] == "NON-COMPLIANT"]))
        m4.metric("High-Risk (<50%)", len(logs_df[logs_df["score"] < 50]))
        dual_col = logs_df["dual_violation"] if "dual_violation" in logs_df.columns else pd.Series(dtype=str)
        m5.metric("Dual PIN Violations", int((dual_col == "Yes").sum()) if not dual_col.empty else 0)

        st.markdown("---")
        col_c1, col_c2 = st.columns(2)
        with col_c1:
            st.markdown("#### Regional Missing-Field Breakdown")
            st.bar_chart(logs_df.groupby("region")["missing_count"].sum())
        with col_c2:
            st.markdown("#### Compliance Score Trend")
            st.line_chart(logs_df["score"])

        if "district" in logs_df.columns and logs_df["district"].notna().any():
            st.markdown("#### District-Wise Case Load")
            dist_counts = logs_df[logs_df["district"].notna()]["district"].value_counts()
            st.bar_chart(dist_counts)

        st.markdown("#### Live Audit Logs")
        st.dataframe(logs_df, use_container_width=True)
    else:
        st.info("No audit logs yet. Run a scan in any tab to populate this dashboard.")

# --- TAB 2: WEB AUDIT ---
with tab_web:
    st.markdown("### Automated E-Commerce Listing Inspection")
    target_url = st.text_input("Enter E-Commerce Product URL (Amazon, Blinkit, Instamart):")
    vendor_name = st.text_input("Seller / Brand Name:", value="E-Commerce Seller Inc.")

    if st.button("Run Web Audit"):
        if target_url:
            with st.spinner("Fetching and analysing listing..."):
                scraped = scrape_url(target_url)
            if scraped["status"]:
                routing = resolve_officer(scraped["text"] + " " + target_url, source_type="web", selected_zone=officer_region)
                audit = audit_legal_metrology(scraped["text"], pincode_valid=routing["pincode_valid"])
                missing = [k for k, v in audit["checks"].items() if not v]
                status_str = "COMPLIANT" if audit["is_compliant"] else "NON-COMPLIANT"

                log_audit_to_db("Web Scraper", scraped["title"][:30], vendor_name, officer_region,
                                 audit["compliance_score"], status_str, len(missing),
                                 pincode=routing["pincode_found"], pincode_valid=str(routing["pincode_valid"]),
                                 district=routing["district"], officer_name=routing["officer_name"],
                                 officer_phone=routing["officer_phone"], routing_method=routing["routing_method"],
                                 dual_violation="Yes" if routing["dual_violation"] else "No")

                st.session_state["last_context"] = {
                    "source": "Web Audit", "product": scraped["title"], "vendor": vendor_name,
                    "score": audit["compliance_score"], "missing_fields": missing, "routing": routing
                }

                c1, c2 = st.columns([1, 2])
                with c1:
                    st.metric("Metrology Compliance", f"{audit['compliance_score']}%")
                with c2:
                    if audit["is_compliant"]:
                        st.success("✅ FULLY STATUTORY COMPLIANT")
                    else:
                        st.error("⚠️ STATUTORY NON-COMPLIANCE DETECTED")
                        st.toast(f"📱 SMS dispatched to {routing['officer_name']} ({routing['officer_phone']})", icon="📲")
                        st.toast(f"📧 Legal notice dispatched to {vendor_email}", icon="📩")

                render_routing_card(routing)

                if not audit["is_compliant"]:
                    for m in missing:
                        st.write(f"❌ Missing Field: **{m.replace('_', ' ').title()}**")
                    pdf = generate_pdf_notice(scraped["title"], vendor_name, audit["compliance_score"], missing, routing=routing)
                    st.download_button("📄 Download Official Legal Penalty Notice (PDF)", pdf, "Penalty_Notice.pdf", "application/pdf")
            else:
                st.error(f"Could not reach the target URL: {scraped.get('error', 'Unknown error')}")
        else:
            st.warning("Please enter a URL first.")

# --- TAB 3: VISION OCR ---
with tab_ocr:
    st.markdown("### Optical Character Scanning for Physical Packaging")
    st.caption("First scan after a fresh deploy will take ~30-60s while the OCR model loads. Every scan after that is fast.")
    file = st.file_uploader("Upload Packaging Image:", type=["png", "jpg", "jpeg"])
    pkg_vendor = st.text_input("Manufacturer Name:", value="Local Packager Corp")

    if file and st.button("Process Vision Pipeline"):
        # Guard against extremely large uploads (e.g. raw 20MP camera files) at the source,
        # before any processing touches them, to avoid a memory spike on decode.
        MAX_UPLOAD_MB = 8
        if file.size > MAX_UPLOAD_MB * 1024 * 1024:
            st.error(
                f"This image is {file.size / (1024*1024):.1f} MB, which is too large for this "
                f"server's memory budget (limit {MAX_UPLOAD_MB} MB). Please use your phone's "
                "camera app to take/export a compressed photo, or resize it before uploading."
            )
            st.stop()
        try:
            with st.spinner("Running OCR + compliance analysis..."):
                text, annotated_img = enhance_and_annotate_image(file)
        except Exception as e:
            st.error(f"OCR failed with this exact error: `{e}`")
            st.caption(
                "Common causes: (1) packages.txt missing/misplaced/misspelled — must be in the "
                "repo root as exactly `tesseract-ocr`, then the app needs a full 'Reboot' (not "
                "just a rerun). (2) The app is still mid-rebuild — wait ~1 min after pushing and "
                "try again. (3) A memory limit — check Manage app -> logs for 'OOM' or 'Killed'."
            )
            st.exception(e)
            st.stop()

        routing = resolve_officer(text, source_type="physical", selected_zone=officer_region)
        audit = audit_legal_metrology(text, pincode_valid=routing["pincode_valid"])
        missing = [k for k, v in audit["checks"].items() if not v]
        status_str = "COMPLIANT" if audit["is_compliant"] else "NON-COMPLIANT"

        log_audit_to_db("Vision OCR", file.name, pkg_vendor, officer_region,
                         audit["compliance_score"], status_str, len(missing),
                         pincode=routing["pincode_found"], pincode_valid=str(routing["pincode_valid"]),
                         district=routing["district"], officer_name=routing["officer_name"],
                         officer_phone=routing["officer_phone"], routing_method=routing["routing_method"],
                         dual_violation="Yes" if routing["dual_violation"] else "No")

        st.session_state["last_context"] = {
            "source": "Vision OCR", "product": file.name, "vendor": pkg_vendor,
            "score": audit["compliance_score"], "missing_fields": missing, "routing": routing,
            "ocr_text": text
        }

        c1, c2 = st.columns([1, 2])
        with c1:
            st.image(annotated_img, caption="Green = Verified Declaration | Amber = Standard Ambient Text", use_container_width=True)
        with c2:
            st.metric("Packaging Compliance Score", f"{audit['compliance_score']}%")
            for k, v in audit["checks"].items():
                st.write(f"{'✅' if v else '❌'} **{k.replace('_', ' ').title()}**")

        render_routing_card(routing)
        with st.expander("🔍 Raw OCR Text Extracted"):
            st.write(text if text.strip() else "_No text detected — try a clearer, well-lit photo._")

        if not audit["is_compliant"]:
            pdf = generate_pdf_notice(file.name, pkg_vendor, audit["compliance_score"], missing, routing=routing)
            st.download_button("📄 Download Official Legal Penalty Notice (PDF)", pdf, "Penalty_Notice.pdf", "application/pdf")

# --- TAB 4: SHRINKFLATION FRAUD ---
with tab_fraud:
    st.markdown("### Deceptive Packaging & Shrinkflation Anomaly Engine")
    col_a, col_b = st.columns(2)
    with col_a:
        prev_qty = st.number_input("Declared Historical Net Weight (grams):", value=500)
    with col_b:
        curr_qty = st.number_input("Audited Net Weight (grams):", value=410)

    sample_text = st.text_area(
        "Package Text String:",
        value="MRP Rs. 150. Net Qty 410g. Mfd by Brand Co. Country of Origin: India. PIN 636001."
    )

    if st.button("Execute Deceptive Packaging Scan"):
        routing = resolve_officer(sample_text, source_type="physical", selected_zone=officer_region)
        audit = audit_legal_metrology(sample_text, historical_qty=prev_qty, current_qty=curr_qty, pincode_valid=routing["pincode_valid"])

        if audit["shrinkflation"]:
            pct = round(((prev_qty - curr_qty) / prev_qty) * 100, 2)
            st.error(f"🚨 SHRINKFLATION FRAUD DETECTED: Quantity reduced by {pct}% without a corresponding price adjustment.")
        else:
            st.success("✅ No quantity-reduction anomalies detected.")

        st.session_state["last_context"] = {
            "source": "Shrinkflation Scan", "score": audit["compliance_score"],
            "shrinkflation": audit["shrinkflation"], "routing": routing
        }
        render_routing_card(routing)

# --- TAB 5: BULK CSV INVENTORY ---
with tab_bulk:
    st.markdown("### Batch Automated Inventory Scan")
    csv_file = st.file_uploader("Upload Enterprise Batch CSV (must include a 'url' column):", type=["csv"])
    if csv_file:
        df = pd.read_csv(csv_file)
        if "url" in df.columns and st.button("Run Batch Processing"):
            results = []
            progress = st.progress(0)
            for idx, row in df.iterrows():
                scraped = scrape_url(row["url"])
                if scraped["status"]:
                    routing = resolve_officer(scraped["text"] + " " + row["url"], source_type="bulk", selected_zone=officer_region)
                    audit = audit_legal_metrology(scraped["text"], pincode_valid=routing["pincode_valid"])
                    score = audit["compliance_score"]
                    status = "COMPLIANT" if audit["is_compliant"] else "NON-COMPLIANT"
                    district = routing["district"]
                    dual = "Yes" if routing["dual_violation"] else "No"
                else:
                    score, status, district, dual = 0.0, "FAILED", "N/A", "No"
                    routing = {"pincode_found": "N/A", "pincode_valid": "N/A", "officer_name": "N/A",
                               "officer_phone": "N/A", "routing_method": "N/A"}

                results.append({"URL": row["url"], "Score": score, "Status": status,
                                 "District": district, "Dual Violation": dual})
                log_audit_to_db("Bulk CSV", row["url"][:25], "Batch Vendor", officer_region, score, status, 0,
                                 pincode=routing.get("pincode_found", "N/A"), pincode_valid=str(routing.get("pincode_valid", "N/A")),
                                 district=district, officer_name=routing.get("officer_name", "N/A"),
                                 officer_phone=routing.get("officer_phone", "N/A"), routing_method=routing.get("routing_method", "N/A"),
                                 dual_violation=dual)
                progress.progress((idx + 1) / len(df))

            st.dataframe(pd.DataFrame(results), use_container_width=True)

# --- TAB 6: AI ASSISTANT (rule-based now, LLM-ready) ---
with tab_ai:
    st.markdown("### 🤖 Ask About Legal Metrology, This Product, or How the Portal Works")

    st.markdown('<span class="mode-pill mode-pill-rule">● OFFLINE MODE — free rule-based knowledge base, no API key</span>', unsafe_allow_html=True)

    ctx = st.session_state.get("last_context")
    if ctx:
        with st.expander("📎 Using context from your most recent audit", expanded=False):
            st.json(ctx)
    else:
        st.info("Run an audit in another tab first so the assistant can answer questions about *your* specific product — or just ask a general question below.")

    st.markdown("#### 🎙️ Voice Input (optional, no API key needed)")
    st.caption(
        "Record a question with your microphone. Transcription uses Google's free speech "
        "recognition service via the `SpeechRecognition` library — good for short, clear "
        "questions, no account required."
    )
    speak_replies = st.toggle("🔊 Speak answers out loud", value=True)

    audio_value = st.audio_input("Tap to record your question")
    transcribed_text = ""
    if audio_value is not None:
        try:
            import speech_recognition as sr
            recognizer = sr.Recognizer()
            with sr.AudioFile(audio_value) as source:
                audio_data = recognizer.record(source)
            transcribed_text = recognizer.recognize_google(audio_data)
            st.success(f"Heard: \"{transcribed_text}\"")
        except Exception as e:
            st.warning(f"Could not transcribe audio automatically ({e}). Please type your question below instead.")

    if "chat_history" not in st.session_state:
        st.session_state.chat_history = []

    for i, (role, msg) in enumerate(st.session_state.chat_history):
        css_class = "chat-bubble-user" if role == "user" else "chat-bubble-ai"
        label = "🧑 You" if role == "user" else "🤖 Assistant"
        st.markdown(f'<div class="{css_class}"><b>{label}:</b><br>{msg}</div>', unsafe_allow_html=True)
        is_last = (i == len(st.session_state.chat_history) - 1)
        if role == "assistant" and is_last and speak_replies:
            audio_bytes = text_to_speech_bytes(msg)
            if audio_bytes:
                st.audio(audio_bytes, format="audio/mp3", autoplay=True)

    user_question = st.text_input("Type your question:", value=transcribed_text, key="ai_question_input")
    col_ask, col_clear = st.columns([1, 1])
    with col_ask:
        ask_clicked = st.button("Ask", use_container_width=True)
    with col_clear:
        if st.button("Clear Chat", use_container_width=True):
            st.session_state.chat_history = []
            st.rerun()

    if ask_clicked and user_question.strip():
        st.session_state.chat_history.append(("user", user_question))
        answer = rule_based_answer(user_question)
        st.session_state.chat_history.append(("assistant", answer))
        st.rerun()

    st.markdown("---")
    st.markdown("##### 💡 Try asking:")
    sample_qs = [
        "What is a dual violation?",
        "How does officer routing work?",
        "What does the compliance score mean?",
        "What is shrinkflation and how is it detected?",
    ]
    cols = st.columns(len(sample_qs))
    for col, q in zip(cols, sample_qs):
        if col.button(q, use_container_width=True):
            st.session_state.chat_history.append(("user", q))
            answer = rule_based_answer(q)
            st.session_state.chat_history.append(("assistant", answer))
            st.rerun()

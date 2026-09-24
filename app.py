import streamlit as st
import requests
from bs4 import BeautifulSoup
import re
from PIL import Image, ImageDraw, ImageOps, ImageFilter
import pandas as pd
import sqlite3
import datetime
import io
import gc
import shutil
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
# Bilingual (English / Tamil) rule-based keyword matching against a Legal Metrology KB.
# =========================================================================================
LLM_ENABLED = False

RULE_BASED_KB = [
    (["mrp", "maximum retail price"],
     "Under Rule 6 of the Legal Metrology (Packaged Commodities) Rules, 2011, every pre-packaged "
     "commodity must declare the Maximum Retail Price inclusive of all taxes, in the format "
     "'MRP Rs. ___ (inclusive of all taxes)'.",
     "சட்டப்பூர்வ அளவீட்டு (பொதி பொருட்கள்) விதிகள், 2011-ன் விதி 6-ன் கீழ், ஒவ்வொரு பொதி "
     "பொருளிலும் அனைத்து வரிகளையும் உள்ளடக்கிய அதிகபட்ச சில்லறை விலை (MRP) தெளிவாக "
     "குறிப்பிடப்பட வேண்டும்."),
    (["net quantity", "net qty", "net weight"],
     "Net quantity must be declared in standard units (grams/kilograms for solids, "
     "millilitres/litres for liquids) in a specific font size proportional to the package's "
     "principal display area, per Rule 6 and the Second Schedule.",
     "விதி 6 மற்றும் இரண்டாம் அட்டவணையின்படி, நிகர அளவு (கிராம்/கிலோ அல்லது மில்லி/லிட்டர்) "
     "தெளிவான எழுத்துருவில் பொதியில் குறிப்பிடப்பட வேண்டும்."),
    (["unit sale price", "usp"],
     "The Unit Sale Price (price per standard unit, e.g., price per kg or per litre) must be "
     "declared so consumers can compare value across pack sizes, under Rule 6(1)(f).",
     "விதி 6(1)(f)-ன் கீழ், நுகர்வோர் ஒப்பிட்டுப் பார்க்க உதவும் வகையில் ஒரு அலகு விற்பனை "
     "விலை (ஒரு கிலோ/லிட்டருக்கான விலை) குறிப்பிடப்பட வேண்டும்."),
    (["manufacturer", "packer", "marketed by", "mfd by"],
     "The name and complete address of the manufacturer, packer, or importer must be declared "
     "under Rule 6(1)(a)(i). This is where the PIN code declaration is checked in this portal.",
     "விதி 6(1)(a)(i)-ன் கீழ், உற்பத்தியாளர்/பேக் செய்பவர்/இறக்குமதியாளரின் பெயர் மற்றும் "
     "முழு முகவரி (PIN குறியீடு உட்பட) குறிப்பிடப்பட வேண்டும்."),
    (["country of origin", "made in"],
     "Country of origin must be declared for all imported pre-packaged commodities, and is "
     "increasingly required for domestic goods too.",
     "இறக்குமதி செய்யப்பட்ட அனைத்து பொருட்களுக்கும் தோற்றுவாய் நாடு குறிப்பிடப்பட வேண்டும்."),
    (["expiry", "best before", "mfg date", "manufacturing date"],
     "Month and year of manufacture/packing and, where applicable, the 'best before' or expiry "
     "date must be declared under Rule 6(1)(e).",
     "விதி 6(1)(e)-ன் கீழ், உற்பத்தி/பேக்கிங் மாதம்-ஆண்டு மற்றும் காலாவதி தேதி "
     "குறிப்பிடப்பட வேண்டும்."),
    (["pin code", "pincode", "postal code"],
     "A valid 6-digit PIN code as part of the manufacturer/packer address is required so "
     "consumers and enforcement officers can identify the responsible entity's jurisdiction. "
     "This portal treats a missing or structurally invalid PIN as a standalone 'dual violation'.",
     "6 இலக்க செல்லுபடியாகும் PIN குறியீடு முகவரியில் இருக்க வேண்டும். இது இல்லாவிட்டால் "
     "இந்த போர்ட்டல் அதை தனி 'இரட்டை மீறல்' (Dual Violation) ஆக குறிக்கும்."),
    (["shrinkflation", "quantity reduced", "less quantity same price"],
     "Shrinkflation — reducing net quantity while keeping price constant without clear disclosure "
     "— is scrutinised under fair trade practice provisions.",
     "விலையை மாற்றாமல் அளவை குறைப்பது 'Shrinkflation' எனப்படும். இது நியாயமான வர்த்தக "
     "நடைமுறை விதிகளின் கீழ் ஆய்வு செய்யப்படும்."),
    (["dual violation"],
     "A 'Dual Violation' means the routing engine could not find a valid, structurally correct "
     "PIN code in the product's declared information — flagged independently of other missing "
     "statutory fields.",
     "'இரட்டை மீறல்' என்பது தயாரிப்பில் சரியான PIN குறியீடு இல்லாதது; இது மற்ற "
     "மீறல்களைத் தவிர தனியாக குறிக்கப்படும்."),
    (["how does routing work", "officer routing", "how is the officer assigned"],
     "The routing engine works in layers: (1) exact valid PIN → district officer, (2) valid but "
     "unmapped PIN → zonal command, (3) missing/invalid PIN → Dual Violation + city-name match, "
     "(4) e-commerce → platform nodal officer, (5) last resort → default zonal HQ.",
     "இணைப்பு பொறிமுறை: (1) சரியான PIN → மாவட்ட அதிகாரி, (2) அறியப்படாத PIN → மண்டல "
     "தலைமையகம், (3) PIN இல்லை → இரட்டை மீறல் + நகர பெயர் தேடல், (4) இ-காமர்ஸ் → தள "
     "அதிகாரி, (5) கடைசியாக → இயல்புநிலை மண்டல தலைமையகம்."),
    (["compliance score", "how is score calculated"],
     "The compliance score is the percentage of statutory checks passed out of all checks run.",
     "இணக்க மதிப்பெண் என்பது இயக்கப்பட்ட அனைத்து சட்ட சரிபார்ப்புகளில் தேர்ச்சி பெற்றவற்றின் "
     "சதவீதம் ஆகும்."),
    (["what can you do", "help", "what is this portal", "who are you"],
     "I'm the offline OmniMetrology Assistant. I can explain Legal Metrology rules, shrinkflation, "
     "dual violations, officer routing, and answer questions about your most recent audit. I run "
     "fully offline in English or Tamil, at zero cost.",
     "நான் ஆஃப்லைன் OmniMetrology உதவியாளர். சட்டப்பூர்வ அளவீட்டு விதிகள், Shrinkflation, "
     "இரட்டை மீறல்கள், அதிகாரி இணைப்பு பற்றி விளக்க முடியும். தமிழ் மற்றும் ஆங்கிலத்தில் "
     "இலவசமாக செயல்படுகிறேன்."),
    (["penalty", "fine", "punishment", "notice"],
     "This portal generates a demonstration Legal Metrology penalty notice PDF whenever an audit "
     "is non-compliant, listing missing statutory fields and the routed enforcement officer.",
     "தணிக்கை சட்டவிரோதமாக இருந்தால், இந்த போர்ட்டல் ஒரு மாதிரி அபராத அறிவிப்பு PDF-ஐ "
     "உருவாக்கும், விடுபட்ட விதிகள் மற்றும் ஒதுக்கப்பட்ட அதிகாரி விவரங்களுடன்."),
    (["e-commerce", "online seller", "amazon", "flipkart", "blinkit"],
     "For online listings, this portal scrapes the product page text and runs the same statutory "
     "checks as physical packaging, falling back to the platform's nodal officer if no PIN is found.",
     "இணைய விற்பனைக்கு, இந்த போர்ட்டல் பக்க உரையை பெற்று அதே சட்ட சரிபார்ப்புகளை "
     "இயக்கும்; PIN இல்லையெனில் தள அதிகாரிக்கு அனுப்பும்."),
    (["camera", "photo blurry", "ocr wrong", "not reading properly", "misread"],
     "If the camera/OCR misreads text: hold the package flat and well-lit, avoid glare, fill the "
     "frame with the label, and use the 'Auto-Enhance & Retry' pipeline — it now tries multiple "
     "orientations and scan modes automatically and picks the clearest result, with a confidence "
     "score shown on screen.",
     "கேமரா சரியாக படிக்கவில்லை என்றால்: பொதியை தட்டையாக, நல்ல வெளிச்சத்தில் வைத்து, "
     "பளபளப்பு இல்லாமல், லேபிளை முழு திரையிலும் நிரப்பி புகைப்படம் எடுக்கவும். இந்த "
     "போர்ட்டல் இப்போது தானாகவே பல கோணங்களை முயற்சித்து தெளிவான முடிவை தேர்ந்தெடுக்கும்."),
]

def rule_based_answer(question, lang="en"):
    q = question.lower()
    best_match, best_score, best_ta = None, 0, None
    for entry in RULE_BASED_KB:
        keywords, answer_en, answer_ta = entry[0], entry[1], entry[2]
        score = sum(1 for k in keywords if k in q)
        if score > best_score:
            best_score, best_match, best_ta = score, answer_en, answer_ta
    if best_match:
        return best_ta if lang == "ta" else best_match
    if lang == "ta":
        return ("இதற்கு குறிப்பிட்ட விதி கிடைக்கவில்லை. MRP, நிகர அளவு, உற்பத்தியாளர் "
                "முகவரி, PIN குறியீடு, Shrinkflation, இரட்டை மீறல் அல்லது அதிகாரி இணைப்பு "
                "பற்றி கேட்கவும்.")
    return (
        "I don't have a specific rule matched for that in offline mode. Try asking about MRP, "
        "net quantity, unit sale price, manufacturer address, country of origin, expiry dates, "
        "PIN code declaration, shrinkflation, dual violations, camera/OCR tips, or how officer "
        "routing works."
    )

def text_to_speech_bytes(text, lang="en"):
    """Converts text to spoken audio using gTTS (free, no API key). Returns MP3 bytes or None."""
    try:
        from gtts import gTTS
        clean_text = re.sub(r"[*_#`]", "", text)[:600]
        tts = gTTS(text=clean_text, lang=lang)
        buf = io.BytesIO()
        tts.write_to_fp(buf)
        buf.seek(0)
        return buf.read()
    except Exception:
        return None

# =========================================================================================
# DATABASE LAYER
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
        "pincode": "TEXT", "pincode_valid": "TEXT", "district": "TEXT",
        "officer_name": "TEXT", "officer_phone": "TEXT", "routing_method": "TEXT",
        "dual_violation": "TEXT", "ocr_confidence": "REAL",
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
                     dual_violation="No", ocr_confidence=None):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    c.execute("""INSERT INTO audit_logs
                (timestamp, source, item_name, vendor, region, score, status, missing_count,
                 pincode, pincode_valid, district, officer_name, officer_phone, routing_method,
                 dual_violation, ocr_confidence)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
              (ts, source, item_name, vendor, region, score, status, missing_count,
               pincode, pincode_valid, district, officer_name, officer_phone, routing_method,
               dual_violation, ocr_confidence))
    conn.commit()
    conn.close()

def get_db_logs():
    conn = sqlite3.connect(DB_PATH)
    df = pd.read_sql_query("SELECT * FROM audit_logs ORDER BY id DESC", conn)
    conn.close()
    return df

# =========================================================================================
# PREMIUM "GOVERNMENT + APPLE" LIGHT THEME (refined)
# =========================================================================================
st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&family=Poppins:wght@600;700;800&display=swap');

html, body, [class*="css"]  { font-family: 'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; }
.stApp { background: radial-gradient(circle at top left, #eef2ff 0%, #f7f9fc 35%, #eef1f7 100%); color: #0f172a; }
.tricolor-strip { height: 6px; width: 100%; background: linear-gradient(90deg, #FF9933 0%, #FF9933 33%, #FFFFFF 33%, #FFFFFF 66%, #138808 66%, #138808 100%); border-radius: 4px; margin-bottom: 18px; }
.sih-header { background: linear-gradient(135deg, #ffffff 0%, #f8fafc 100%); border: 1px solid #e2e8f0; border-left: 8px solid #1e3a8a; padding: 30px 34px; border-radius: 20px; margin-bottom: 26px; box-shadow: 0 14px 34px -14px rgba(15, 23, 42, 0.20); }
.sih-title { font-family: 'Poppins', sans-serif; font-size: 2.25rem; font-weight: 800; color: #0f172a; margin: 0; letter-spacing: -0.6px; }
.sih-sub { font-size: 1.02rem; font-weight: 500; color: #334155; margin-top: 8px; }
.badge-row { margin-top: 14px; }
.gov-badge { display: inline-block; background: #eff6ff; color: #1e3a8a; border: 1px solid #bfdbfe; font-weight: 700; font-size: 0.78rem; padding: 5px 12px; border-radius: 999px; margin-right: 8px; }
.gov-badge-new { background: #ecfdf5; color: #065f46; border: 1px solid #a7f3d0; }
h1, h2, h3, h4 { font-family: 'Poppins', sans-serif; color: #0f172a !important; font-weight: 700 !important; }
p, li, span, label, div { color: #1e293b; }
.stMarkdown, .stText { color: #1e293b !important; }
.glass-card { background: #ffffff; border: 1px solid #e2e8f0; border-radius: 16px; padding: 20px 22px; box-shadow: 0 8px 24px -14px rgba(15,23,42,0.18); margin-bottom: 14px; }
.routing-card { background: #f8fafc; border: 1px solid #cbd5e1; border-left: 6px solid #1e3a8a; border-radius: 14px; padding: 18px 20px; margin: 10px 0 16px 0; }
.routing-card b { color: #0f172a; }
.dual-violation-banner { background: #fef2f2; border: 1px solid #fecaca; border-left: 6px solid #dc2626; border-radius: 14px; padding: 16px 20px; color: #991b1b; font-weight: 700; margin-bottom: 14px; }
.clean-pin-banner { background: #f0fdf4; border: 1px solid #bbf7d0; border-left: 6px solid #16a34a; border-radius: 14px; padding: 16px 20px; color: #14532d; font-weight: 700; margin-bottom: 14px; }
.confidence-banner { background: #fffbeb; border: 1px solid #fde68a; border-left: 6px solid #d97706; border-radius: 14px; padding: 14px 18px; color: #92400e; font-weight: 600; margin-bottom: 14px; }
.chat-bubble-user { background: #eff6ff; border: 1px solid #bfdbfe; border-radius: 14px 14px 2px 14px; padding: 12px 16px; margin: 6px 0; color: #1e3a8a; font-weight: 600; }
.chat-bubble-ai { background: #ffffff; border: 1px solid #e2e8f0; border-radius: 14px 14px 14px 2px; padding: 12px 16px; margin: 6px 0; color: #1e293b; }
.mode-pill { display: inline-block; font-size: 0.75rem; font-weight: 700; padding: 4px 10px; border-radius: 999px; margin-bottom: 10px; margin-right: 6px; }
.mode-pill-llm { background: #ecfdf5; color: #065f46; border: 1px solid #a7f3d0; }
.mode-pill-rule { background: #fffbeb; color: #92400e; border: 1px solid #fde68a; }
.mode-pill-lang { background: #eff6ff; color: #1e3a8a; border: 1px solid #bfdbfe; }
div[data-testid="stMetric"] { background: #ffffff; border: 1px solid #e2e8f0; border-radius: 14px; padding: 14px 16px; box-shadow: 0 6px 18px -12px rgba(15,23,42,0.15); }
div[data-testid="stMetricValue"] { font-size: 1.9rem !important; font-weight: 800 !important; color: #1e3a8a !important; }
div[data-testid="stMetricLabel"] { color: #475569 !important; font-weight: 600 !important; }
.stButton>button { background: linear-gradient(90deg, #1e3a8a 0%, #1d4ed8 100%) !important; color: #ffffff !important; font-weight: 700 !important; border-radius: 10px !important; border: none !important; padding: 12px 26px !important; transition: all 0.2s ease !important; box-shadow: 0 6px 18px -6px rgba(29, 78, 216, 0.5) !important; }
.stButton>button:hover { transform: translateY(-1px) !important; box-shadow: 0 10px 22px -6px rgba(29, 78, 216, 0.65) !important; }
.stDownloadButton>button { background: linear-gradient(90deg, #b91c1c 0%, #dc2626 100%) !important; color: #ffffff !important; font-weight: 700 !important; border-radius: 10px !important; border: none !important; }
.stTabs [data-baseweb="tab"] { font-weight: 700; color: #334155; }
.stTabs [aria-selected="true"] { color: #1e3a8a !important; border-bottom-color: #1e3a8a !important; }
section[data-testid="stSidebar"] { background: linear-gradient(180deg, #0f172a 0%, #111827 100%); }
section[data-testid="stSidebar"] * { color: #f1f5f9 !important; }
section[data-testid="stSidebar"] input, section[data-testid="stSidebar"] select { color: #0f172a !important; }
[data-testid="stDataFrame"] { border-radius: 12px; overflow: hidden; }
</style>
""", unsafe_allow_html=True)

# =========================================================================================
# PIN-CODE → DISTRICT / OFFICER ROUTING ENGINE (unchanged logic, kept intact)
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
# COMPUTER VISION / OCR ENGINE — v2 (fixes "camera makes mistakes" complaint)
# -----------------------------------------------------------------------------------------
# What was wrong before: a single fixed OCR pass (one PSM mode, no rotation handling,
# no retry) meant a slightly tilted photo, a busy background, or a low-confidence read
# went straight into the compliance checker as-is. Camera photos are messier than
# scanned images, so this version:
#   1. Auto-upscales small/blurry camera frames before OCR (helps small label text).
#   2. Tries to auto-correct rotation using Tesseract's orientation detector.
#   3. Runs OCR with several page-segmentation modes (PSM 3/4/6/11) and keeps the
#      pass with the highest average word confidence, instead of a single fixed mode.
#   4. Optionally reads Tamil text too (lang='eng+tam') when Tamil mode is selected,
#      so bilingual packaging is read correctly.
#   5. Surfaces the OCR confidence score to the user, so a bad photo is visibly
#      flagged instead of silently producing wrong compliance results.
# Still pure PIL (no OpenCV/numpy) to keep memory low enough for free hosting tiers.
# =========================================================================================
def _get_tesseract_path():
    tess_path = shutil.which("tesseract")
    if not tess_path:
        raise RuntimeError(
            "TESSERACT_NOT_FOUND: the 'tesseract' binary is not installed on this server. "
            "Check that packages.txt sits in the SAME root folder as app.py and requirements.txt, "
            "contains 'tesseract-ocr' and 'tesseract-ocr-tam' (for Tamil), then fully reboot the app."
        )
    return tess_path

def _prep_base_image(pil_img_or_file, max_dim=1400):
    if hasattr(pil_img_or_file, "seek"):
        pil_img_or_file.seek(0)
    gc.collect()
    pil_img = Image.open(pil_img_or_file)
    try:
        pil_img.draft("RGB", (max_dim, max_dim))
    except Exception:
        pass
    pil_img = pil_img.convert("RGB")

    # Auto-upscale small camera captures so small label text is legible to Tesseract
    w, h = pil_img.size
    min_side = min(w, h)
    if min_side < 900:
        scale = 900 / max(min_side, 1)
        pil_img = pil_img.resize((int(w * scale), int(h * scale)), Image.LANCZOS)
    pil_img.thumbnail((max_dim, max_dim), Image.LANCZOS)
    return pil_img

def _auto_rotate(pil_img):
    """Best-effort rotation fix using Tesseract's orientation detector. Silently
    skips if the image doesn't have enough text for OSD to work (common on noisy
    camera shots) — a failed OSD must never break the whole scan."""
    import pytesseract
    try:
        osd = pytesseract.image_to_osd(pil_img)
        angle_match = re.search(r"Rotate:\s*(\d+)", osd)
        if angle_match:
            angle = int(angle_match.group(1))
            if angle in (90, 180, 270):
                return pil_img.rotate(-angle, expand=True)
    except Exception:
        pass
    return pil_img

def enhance_and_annotate_image(pil_img_or_file, lang="eng"):
    import pytesseract
    pytesseract.pytesseract.tesseract_cmd = _get_tesseract_path()

    pil_img = _prep_base_image(pil_img_or_file)
    pil_img = _auto_rotate(pil_img)

    gray = ImageOps.grayscale(pil_img)
    gray = ImageOps.autocontrast(gray, cutoff=1)
    gray = gray.filter(ImageFilter.SHARPEN)

    # Try several segmentation modes and keep whichever gives the highest-confidence read.
    # PSM 6 = uniform block, 4 = column of text, 11 = sparse text, 3 = fully automatic.
    candidate_psms = ["--psm 6", "--psm 4", "--psm 11", "--psm 3"]
    best_data, best_conf, best_cfg = None, -1.0, None
    for cfg in candidate_psms:
        try:
            data = pytesseract.image_to_data(gray, lang=lang, config=cfg, output_type=pytesseract.Output.DICT)
        except Exception:
            continue
        confs = [int(c) for c in data["conf"] if str(c).lstrip("-").isdigit() and int(c) >= 0]
        avg_conf = (sum(confs) / len(confs)) if confs else -1.0
        if avg_conf > best_conf:
            best_conf, best_data, best_cfg = avg_conf, data, cfg

    del gray
    gc.collect()

    if best_data is None:
        return "", pil_img.copy(), 0.0

    draw_img = pil_img.copy()
    draw = ImageDraw.Draw(draw_img)
    full_text = []
    compliance_keywords = ["mrp", "rs", "₹", "net", "qty", "g", "kg", "ml", "mfd", "exp",
                            "manufactured", "origin", "pin"]

    n_boxes = len(best_data["text"])
    for i in range(n_boxes):
        text = best_data["text"][i].strip()
        conf = int(best_data["conf"][i]) if str(best_data["conf"][i]).lstrip("-").isdigit() else -1
        if not text or conf < 30:
            continue
        full_text.append(text)
        x, y, w, h = best_data["left"][i], best_data["top"][i], best_data["width"][i], best_data["height"][i]
        color = "#16a34a" if any(k in text.lower() for k in compliance_keywords) else "#d97706"
        draw.rectangle([x, y, x + w, y + h], outline=color, width=3)

    return " ".join(full_text), draw_img, round(max(best_conf, 0.0), 1)

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
def generate_pdf_notice(product_name, vendor, score, missing, routing=None, ocr_confidence=None):
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
    y = 645
    if ocr_confidence is not None:
        p.drawString(50, y, f"OCR Confidence: {ocr_confidence}%")
        y -= 20
    else:
        y -= 5

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
            Routing has escalated via fallback: <b>{routing.get('routing_method')}</b>.
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

def render_confidence_banner(conf):
    if conf is None:
        return
    if conf < 55:
        st.markdown(f"""
        <div class="confidence-banner">
            ⚠️ OCR confidence is low ({conf}%). The photo may be blurry, tilted, or poorly lit —
            results below may contain misreads. Retake the photo flat, in good light, filling the
            frame with the label, or edit the extracted text manually before trusting the audit.
        </div>
        """, unsafe_allow_html=True)
    else:
        st.caption(f"🟢 OCR confidence: {conf}% (average word-level confidence across the best scan pass)")

# =========================================================================================
# HEADER
# =========================================================================================
st.markdown('<div class="tricolor-strip"></div>', unsafe_allow_html=True)
st.markdown("""
<div class="sih-header">
    <div class="sih-title">⚖️ OmniMetrology AI — National Enforcement Portal</div>
    <div class="sih-sub">AI-Powered Legal Metrology Compliance, Shrinkflation Detection, District-Level Enforcement Routing &amp; Bilingual Voice Assistant</div>
    <div class="badge-row">
        <span class="gov-badge">Legal Metrology (Packaged Commodities) Rules, 2011</span>
        <span class="gov-badge">Smart India Hackathon</span>
        <span class="gov-badge gov-badge-new">v2 — Multi-Pass OCR</span>
        <span class="gov-badge gov-badge-new">English + தமிழ்</span>
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
st.sidebar.subheader("🌐 Language / மொழி")
ui_lang_choice = st.sidebar.radio("Assistant & voice language:", ["English", "தமிழ் (Tamil)"], label_visibility="collapsed")
lang_code = "ta" if "Tamil" in ui_lang_choice else "en"
st.sidebar.caption("Controls the AI Assistant's replies, spoken audio, voice-input recognition, and OCR language pack.")
st.sidebar.markdown("---")
st.sidebar.caption("📍 District-level routing is automatic: the AI reads the PIN code from the package or listing and dispatches the alert to the local officer — not the whole zone.")
st.sidebar.markdown("---")
st.sidebar.info("🤖 AI Assistant: Offline rule-based mode\n\nNo API key, no cost. Bilingual (English/Tamil), reads answers aloud.")

tab_dash, tab_web, tab_ocr, tab_unified, tab_fraud, tab_bulk, tab_ai = st.tabs([
    "📈 Command Center",
    "🌐 E-Commerce Web Audit",
    "📸 Physical Vision OCR",
    "🔀 Unified Smart Scan",
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

        if "ocr_confidence" in logs_df.columns and logs_df["ocr_confidence"].notna().any():
            st.markdown("#### 📷 OCR Confidence Distribution (Vision Scans)")
            st.bar_chart(logs_df[logs_df["ocr_confidence"].notna()]["ocr_confidence"])

        st.markdown("#### Live Audit Logs")
        st.dataframe(logs_df, use_container_width=True)
        csv_bytes = logs_df.to_csv(index=False).encode("utf-8")
        st.download_button("⬇️ Export All Logs (CSV)", csv_bytes, "omnimetrology_audit_logs.csv", "text/csv")
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
    st.caption("First scan after a fresh deploy will take ~30-60s while the OCR engine warms up. Every scan after that is fast.")

    ocr_source = st.radio("Choose input method:", ["📁 Upload a photo", "📷 Use camera"], horizontal=True)
    file = None
    if ocr_source == "📁 Upload a photo":
        file = st.file_uploader("Upload Packaging Image:", type=["png", "jpg", "jpeg"])
    else:
        file = st.camera_input("Take a photo of the package label")

    pkg_vendor = st.text_input("Manufacturer Name:", value="Local Packager Corp")
    ocr_lang = "eng+tam" if lang_code == "ta" else "eng"

    if file and st.button("Process Vision Pipeline"):
        MAX_UPLOAD_MB = 8
        if hasattr(file, "size") and file.size > MAX_UPLOAD_MB * 1024 * 1024:
            st.error(
                f"This image is {file.size / (1024*1024):.1f} MB, which is too large for this "
                f"server's memory budget (limit {MAX_UPLOAD_MB} MB). Please use a compressed photo."
            )
            st.stop()
        try:
            with st.spinner("Running multi-pass OCR (auto-rotate + best-confidence scan) + compliance analysis..."):
                text, annotated_img, ocr_conf = enhance_and_annotate_image(file, lang=ocr_lang)
        except Exception as e:
            st.error(f"OCR failed with this exact error: `{e}`")
            st.caption(
                "Common causes: (1) packages.txt missing/misplaced/misspelled — must be in the "
                "repo root, containing 'tesseract-ocr' (and 'tesseract-ocr-tam' for Tamil), then "
                "the app needs a full 'Reboot'. (2) The app is still mid-rebuild. (3) Memory limit "
                "— check Manage app -> logs for 'OOM' or 'Killed'."
            )
            st.exception(e)
            st.stop()

        routing = resolve_officer(text, source_type="physical", selected_zone=officer_region)
        audit = audit_legal_metrology(text, pincode_valid=routing["pincode_valid"])
        missing = [k for k, v in audit["checks"].items() if not v]
        status_str = "COMPLIANT" if audit["is_compliant"] else "NON-COMPLIANT"
        fname = getattr(file, "name", "camera_capture.jpg")

        log_audit_to_db("Vision OCR", fname, pkg_vendor, officer_region,
                         audit["compliance_score"], status_str, len(missing),
                         pincode=routing["pincode_found"], pincode_valid=str(routing["pincode_valid"]),
                         district=routing["district"], officer_name=routing["officer_name"],
                         officer_phone=routing["officer_phone"], routing_method=routing["routing_method"],
                         dual_violation="Yes" if routing["dual_violation"] else "No", ocr_confidence=ocr_conf)

        st.session_state["last_context"] = {
            "source": "Vision OCR", "product": fname, "vendor": pkg_vendor,
            "score": audit["compliance_score"], "missing_fields": missing, "routing": routing,
            "ocr_text": text, "ocr_confidence": ocr_conf
        }

        render_confidence_banner(ocr_conf)

        c1, c2 = st.columns([1, 2])
        with c1:
            st.image(annotated_img, caption="Green = Verified Declaration | Amber = Standard Ambient Text", use_container_width=True)
        with c2:
            st.metric("Packaging Compliance Score", f"{audit['compliance_score']}%")
            for k, v in audit["checks"].items():
                st.write(f"{'✅' if v else '❌'} **{k.replace('_', ' ').title()}**")

        render_routing_card(routing)
        with st.expander("🔍 Raw OCR Text Extracted (editable — fix any misreads before re-auditing)"):
            corrected_text = st.text_area("Extracted text:", value=text if text.strip() else "", height=100,
                                           key="ocr_correction_box")
            if st.button("🔁 Re-run Compliance Check on Corrected Text"):
                audit2 = audit_legal_metrology(corrected_text, pincode_valid=routing["pincode_valid"])
                missing2 = [k for k, v in audit2["checks"].items() if not v]
                st.metric("Updated Compliance Score", f"{audit2['compliance_score']}%")
                for k, v in audit2["checks"].items():
                    st.write(f"{'✅' if v else '❌'} **{k.replace('_', ' ').title()}**")

        if not audit["is_compliant"]:
            pdf = generate_pdf_notice(fname, pkg_vendor, audit["compliance_score"], missing, routing=routing, ocr_confidence=ocr_conf)
            st.download_button("📄 Download Official Legal Penalty Notice (PDF)", pdf, "Penalty_Notice.pdf", "application/pdf")

# --- TAB 4: UNIFIED SMART SCAN (new "two-in-one" tool) ---
with tab_unified:
    st.markdown("### 🔀 Unified Smart Scan — One Tool, Any Input")
    st.caption("Feed it a product photo, an e-commerce URL, or pasted label text — it auto-detects the "
               "input type and runs the full compliance + routing pipeline in one step.")

    unified_mode = st.radio("What are you scanning?", ["📷 Photo / Camera", "🌐 URL", "📝 Paste Text"], horizontal=True)
    unified_vendor = st.text_input("Vendor / Brand Name:", value="Unified Scan Entity", key="unified_vendor")

    unified_text, unified_img, unified_conf, unified_source_label = None, None, None, None

    if unified_mode == "📷 Photo / Camera":
        u_file = st.camera_input("Capture label", key="unified_camera") or st.file_uploader(
            "...or upload a photo", type=["png", "jpg", "jpeg"], key="unified_upload")
        if u_file and st.button("Run Unified Scan", key="unified_run_photo"):
            ocr_lang = "eng+tam" if lang_code == "ta" else "eng"
            with st.spinner("Scanning image..."):
                unified_text, unified_img, unified_conf = enhance_and_annotate_image(u_file, lang=ocr_lang)
            unified_source_label = "Unified Scan — Photo"

    elif unified_mode == "🌐 URL":
        u_url = st.text_input("Product URL:", key="unified_url")
        if u_url and st.button("Run Unified Scan", key="unified_run_url"):
            with st.spinner("Fetching listing..."):
                scraped = scrape_url(u_url)
            if scraped["status"]:
                unified_text = scraped["text"]
                unified_source_label = "Unified Scan — URL"
            else:
                st.error(f"Could not reach URL: {scraped.get('error')}")

    else:
        u_text = st.text_area("Paste label / listing text:", key="unified_paste", height=100)
        if u_text.strip() and st.button("Run Unified Scan", key="unified_run_text"):
            unified_text = u_text
            unified_source_label = "Unified Scan — Manual Text"

    if unified_text is not None:
        routing = resolve_officer(unified_text, source_type="physical" if unified_mode == "📷 Photo / Camera" else "web",
                                   selected_zone=officer_region)
        audit = audit_legal_metrology(unified_text, pincode_valid=routing["pincode_valid"])
        missing = [k for k, v in audit["checks"].items() if not v]
        status_str = "COMPLIANT" if audit["is_compliant"] else "NON-COMPLIANT"

        log_audit_to_db(unified_source_label, "Unified Scan Item", unified_vendor, officer_region,
                         audit["compliance_score"], status_str, len(missing),
                         pincode=routing["pincode_found"], pincode_valid=str(routing["pincode_valid"]),
                         district=routing["district"], officer_name=routing["officer_name"],
                         officer_phone=routing["officer_phone"], routing_method=routing["routing_method"],
                         dual_violation="Yes" if routing["dual_violation"] else "No", ocr_confidence=unified_conf)

        st.session_state["last_context"] = {
            "source": unified_source_label, "vendor": unified_vendor,
            "score": audit["compliance_score"], "missing_fields": missing, "routing": routing
        }

        if unified_conf is not None:
            render_confidence_banner(unified_conf)

        c1, c2 = st.columns([1, 2]) if unified_img is not None else (None, st)
        if unified_img is not None:
            with c1:
                st.image(unified_img, use_container_width=True)
            target = c2
        else:
            target = c2
        with target:
            st.metric("Compliance Score", f"{audit['compliance_score']}%")
            for k, v in audit["checks"].items():
                st.write(f"{'✅' if v else '❌'} **{k.replace('_', ' ').title()}**")

        render_routing_card(routing)
        if not audit["is_compliant"]:
            pdf = generate_pdf_notice("Unified Scan Item", unified_vendor, audit["compliance_score"], missing,
                                       routing=routing, ocr_confidence=unified_conf)
            st.download_button("📄 Download Penalty Notice (PDF)", pdf, "Penalty_Notice.pdf", "application/pdf",
                                key="unified_pdf_dl")

# --- TAB 5: SHRINKFLATION FRAUD ---
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

# --- TAB 6: BULK CSV INVENTORY ---
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

            result_df = pd.DataFrame(results)
            st.dataframe(result_df, use_container_width=True)
            st.download_button("⬇️ Export Batch Results (CSV)", result_df.to_csv(index=False).encode("utf-8"),
                                "batch_scan_results.csv", "text/csv")

# --- TAB 7: AI ASSISTANT (bilingual, rule-based, LLM-ready) ---
with tab_ai:
    st.markdown("### 🤖 Ask About Legal Metrology, This Product, or How the Portal Works")

    st.markdown(
        f'<span class="mode-pill mode-pill-rule">● OFFLINE MODE — free rule-based knowledge base</span>'
        f'<span class="mode-pill mode-pill-lang">🌐 {"தமிழ்" if lang_code == "ta" else "English"}</span>',
        unsafe_allow_html=True
    )

    ctx = st.session_state.get("last_context")
    if ctx:
        with st.expander("📎 Using context from your most recent audit", expanded=False):
            st.json(ctx)
    else:
        st.info("Run an audit in another tab first so the assistant can answer questions about *your* specific product — or just ask a general question below.")

    st.markdown("#### 🎙️ Voice Input (optional, no API key needed)")
    st.caption(
        "Record a question with your microphone in English or Tamil (set language in the sidebar). "
        "Transcription uses Google's free speech recognition service via `SpeechRecognition` — "
        "good for short, clear questions, no account required."
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
            stt_lang = "ta-IN" if lang_code == "ta" else "en-IN"
            transcribed_text = recognizer.recognize_google(audio_data, language=stt_lang)
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
            audio_bytes = text_to_speech_bytes(msg, lang=lang_code)
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
        answer = rule_based_answer(user_question, lang=lang_code)
        st.session_state.chat_history.append(("assistant", answer))
        st.rerun()

    st.markdown("---")
    st.markdown("##### 💡 Try asking:")
    sample_qs_en = [
        "What is a dual violation?",
        "How does officer routing work?",
        "What does the compliance score mean?",
        "Why does the camera misread my photo?",
    ]
    sample_qs_ta = [
        "இரட்டை மீறல் என்றால் என்ன?",
        "அதிகாரி இணைப்பு எப்படி வேலை செய்கிறது?",
        "இணக்க மதிப்பெண் என்றால் என்ன?",
        "கேமரா ஏன் தவறாக படிக்கிறது?",
    ]
    sample_qs = sample_qs_ta if lang_code == "ta" else sample_qs_en
    cols = st.columns(len(sample_qs))
    for col, q in zip(cols, sample_qs):
        if col.button(q, use_container_width=True):
            st.session_state.chat_history.append(("user", q))
            answer = rule_based_answer(q, lang=lang_code)
            st.session_state.chat_history.append(("assistant", answer))
            st.rerun()

import streamlit as st
import pandas as pd
from datetime import datetime, timedelta
import PyPDF2
import re
import sqlite3
from fpdf import FPDF
import io

# --- CONFIGURAZIONE ---
st.set_page_config(page_title="Canile Soft - Gestionale", layout="wide")
SHEET_ID = "1pcFa454IT1tlykbcK-BeAU9hnIQ_D8V_UuZaKI_KtYM"

# --- FUNZIONI DATABASE & GOOGLE SHEETS ---
def load_data(sheet_name):
    url = f"https://docs.google.com/spreadsheets/d/{SHEET_ID}/gviz/tq?tqx=out:csv&sheet={sheet_name}"
    try:
        df = pd.read_csv(url)
        df.columns = [c.strip().lower() for c in df.columns]
        return df.dropna(how='all')
    except:
        return pd.DataFrame()

def init_db():
    conn = sqlite3.connect('canile.db')
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS storico 
                 (data TEXT, inizio TEXT, fine TEXT, cane TEXT, volontario TEXT, luogo TEXT)''')
    conn.commit()
    conn.close()

def salva_storico(programma, data_turno):
    conn = sqlite3.connect('canile.db')
    for att in programma:
        conn.execute("INSERT INTO storico VALUES (?, ?, ?, ?, ?, ?)",
                     (str(data_turno), att['Inizio'], att['Fine'], att['Cane'], att['Volontario'], att['Luogo']))
    conn.commit()
    conn.close()

def suggerisci_volontario(cane):
    try:
        conn = sqlite3.connect('canile.db')
        query = f"SELECT volontario, COUNT(*) as volte FROM storico WHERE cane = '{cane}' GROUP BY volontario ORDER BY volte DESC LIMIT 1"
        res = pd.read_sql_query(query, conn)
        conn.close()
        return res['volontario'].iloc[0] if not res.empty else None
    except:
        return None

# --- FUNZIONI PDF ---
def extract_pdf_data(uploaded_file):
    try:
        reader = PyPDF2.PdfReader(uploaded_file)
        text = ""
        for page in reader.pages:
            text += page.extract_text() + "\n"
        labels = ['CIBO', 'GUINZAGLIERIA', 'STRUMENTI', 'ATTIVITÀ', 'NOTE', 'TEMPO']
        extracted = {label: "N/D" for label in labels}
        for label in labels:
            pattern = rf"{label}[:\s]+(.*?)(?={'|'.join(labels)}|$)"
            match = re.search(pattern, text, re.DOTALL | re.IGNORECASE)
            if match:
                extracted[label] = match.group(1).strip().replace('\n', ' ')
        return extracted
    except:
        return None

def to_pdf_export(df, data_t):
    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("Arial", 'B', 14)
    pdf.cell(190, 10, f"Programma Canile - {data_t}", ln=True, align='C')
    pdf.set_font("Arial", size=9)
    for _, r in df.iterrows():
        linea = f"{r['Inizio']}-{r['Fine']} | {r['Cane']} | {r['Volontario']} | {r['Luogo']}"
        pdf.cell(190, 7, linea, border=1, ln=True)
    return pdf.output(dest='S').encode('latin-1')

# --- INIZIALIZZAZIONE ---
init_db()
if 'programma' not in st.session_state:
    st.session_state.programma = []

# --- CARICAMENTO DATI ---
df_cani_db = load_data("Cani")
df_volontari_db = load_data("Volontari")
df_luoghi_db = load_data("Luoghi")

st.title("🐾 Canile Soft Online - Smart Scheduler")

# --- 1. SIDEBAR CONFIGURAZIONE ---
with st.sidebar:
    st.header("⚙️ Turno e PDF")
    data_turno = st.date_input("Data del turno", datetime.today())
    ora_inizio = st.time_input("Inizio Turno", datetime.strptime("08:00", "%H:%M"))
    ora_fine = st.time_input("Fine Turno", datetime.strptime("12:00", "%H:%M"))
    pdf_files = st.file_uploader("Carica PDF Cani", accept_multiple_files=True, type="pdf")

database_pdf = {}
if pdf_files:
    for f in pdf_files:
        nome_cane = f.name.split('.')[0].strip().capitalize()
        dati = extract_pdf_data(f)
        if dati: database_pdf[nome_cane] = dati

# --- 2. CHECK-IN DISPONIBILITÀ ---
st.header("✅ Check-in Disponibilità")
c1, c2, c3 = st.columns(3)
with c1:
    cani_list = df_cani_db['nome'].tolist() if 'nome' in df_cani_db.columns else []
    cani_oggi = st.multiselect("Cani", cani_list, default=cani_list)
with c2:
    vol_list = df_volontari_db['nome'].tolist() if 'nome' in df_volontari_db.columns else []
    vol_oggi = st.multiselect("Volontari", vol_list, default=vol_list)
with c3:
    luoghi_list = df_luoghi_db['nome'].tolist() if 'nome' in df_luoghi_db.columns else []
    luoghi_oggi = st.multiselect("Campi", luoghi_list, default=luoghi_list)

# --- 3. ASSEGNAZIONE ATTIVITÀ ---
st.divider()
inizio_lav = datetime.combine(data_turno, ora_inizio) + timedelta(minutes=15)
fine_lav = datetime.combine(data_turno, ora_fine) - timedelta(minutes=30)

with st.container():
    st.subheader("🔗 Nuova Assegnazione")
    a1, a2, a3 = st.columns(3)
    c_sel = a1.selectbox("Seleziona Cane", cani_oggi)
    
    # Suggerimento storico
    v_sugg = suggerisci_volontario(c_sel)
    v_idx = vol_oggi.index(v_sugg) if v_sugg in vol_oggi else 0
    v_sel = a2.selectbox("Seleziona Volontario", vol_oggi, index=v_idx)
    if v_sugg: st.caption(f"✨ Suggerito: {v_sugg} (Coppia frequente)")
    
    l_sel = a3.selectbox("Seleziona Luogo", luoghi_oggi)

    # Gestione Tempo da PDF
    info_pdf = database_pdf.get(c_sel.capitalize(), {})
    tempo_val = 30
    try:
        tempo_val = int(re.search(r'\d+', info_pdf.get('TEMPO', '30')).group())
    except: pass

    t1, t2 = st.columns(2)
    ora_dal = t1.time_input("Ora Inizio", inizio_lav.time())
    ora_al_sugg = (datetime.combine(data_turno, ora_dal) + timedelta(minutes=tempo_val)).time()
    ora_al = t2.time_input("Ora Fine (da TEMPO PDF)", ora_al_sugg)

    if st.button("➕ Aggiungi Attività"):
        st.session_state.programma.append({
            "Inizio": ora_dal.strftime('%H:%M'), "Fine": ora_al.strftime('%H:%M'),
            "Cane": c_sel, "Volontario": v_sel, "Luogo": l_sel,
            "CIBO": info_pdf.get('CIBO', '-'), "NOTE": info_pdf.get('NOTE', '-'),
            "ATTIVITÀ": info_pdf.get('ATTIVITÀ', '-'), "STRUMENTI": info_pdf.get('STRUMENTI', '-'),
            "GUINZAGLIERIA": info_pdf.get('GUINZAGLIERIA', '-')
        })
        st.rerun()

# --- 4. RIEPILOGO E EXPORT ---
if st.session_state.programma:
    st.divider()
    df_prog = pd.DataFrame(st.session_state.programma).sort_values(by="Inizio")
    st.dataframe(df_prog, use_container_width=True)
    
    e1, e2, e3, e4 = st.columns(4)
    if e1.button("💾 Salva Storico"):
        salva_storico(st.session_state.programma, data_turno)
        st.success("Salvato!")
    
    # Export Excel
    exc_buffer = io.BytesIO()
    with pd.ExcelWriter(exc_buffer, engine='openpyxl') as w:
        df_prog.to_excel(w, index=False)
    e2.download_button("📊 Excel", exc_buffer.getvalue(), f"turno_{data_turno}.xlsx")
    
    # Export PDF
    pdf_bytes = to_pdf_export(df_prog, data_turno)
    e3.download_button("📄 PDF", pdf_bytes, f"turno_{data_turno}.pdf")
    
    if e4.button("🗑️ Svuota"):
        st.session_state.programma = []
        st.rerun()

st.info(f"📋 Briefing: {ora_inizio.strftime('%H:%M')} | 🥣 Pasti: {fine_lav.strftime('%H:%M')}")

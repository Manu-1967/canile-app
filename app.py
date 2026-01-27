import streamlit as st
import pandas as pd
from datetime import datetime, timedelta
import PyPDF2
import re

st.set_page_config(page_title="Canile Soft - PDF Intelligence", layout="wide")

SHEET_ID = "1pcFa454IT1tlykbcK-BeAU9hnIQ_D8V_UuZaKI_KtYM"

def load_data(sheet_name):
    url = f"https://docs.google.com/spreadsheets/d/{SHEET_ID}/gviz/tq?tqx=out:csv&sheet={sheet_name}"
    try:
        df = pd.read_csv(url)
        df.columns = [c.strip().lower() for c in df.columns]
        return df.dropna(how='all')
    except:
        return pd.DataFrame()

def extract_pdf_data(uploaded_file):
    """Estrae i dati cercando le etichette specifiche"""
    try:
        reader = PyPDF2.PdfReader(uploaded_file)
        text = ""
        for page in reader.pages:
            text += page.extract_text() + "\n"
        
        # Dizionario per i risultati
        labels = ['CIBO', 'GUINZAGLIERIA', 'STRUMENTI', 'ATTIVITÀ', 'NOTE', 'TEMPO']
        extracted = {label: "N/D" for label in labels}
        
        # Logica di estrazione basata su regex per catturare il testo dopo l'etichetta
        for label in labels:
            pattern = rf"{label}[:\s]+(.*?)(?={'|'.join(labels)}|$)"
            match = re.search(pattern, text, re.DOTALL | re.IGNORECASE)
            if match:
                extracted[label] = match.group(1).strip().replace('\n', ' ')
        
        return extracted
    except Exception as e:
        return None

# --- CARICAMENTO DATI ---
df_cani_db = load_data("Cani")
df_volontari_db = load_data("Volontari")
df_luoghi_db = load_data("Luoghi")

st.title("🐾 Canile Soft Online - Scheduler Intelligente")

# --- SIDEBAR: CONFIGURAZIONE E PDF ---
with st.sidebar:
    st.header("⚙️ Configurazione")
    data_turno = st.date_input("Data", datetime.today())
    ora_inizio = st.time_input("Inizio Turno", datetime.strptime("08:00", "%H:%M"))
    ora_fine = st.time_input("Fine Turno", datetime.strptime("12:00", "%H:%M"))
    
    st.divider()
    st.header("📄 Caricamento Schede")
    files = st.file_uploader("Carica PDF Cani", accept_multiple_files=True, type="pdf")

# Analisi dei PDF caricati
database_pdf = {}
if files:
    for f in files:
        # Il nome del cane deve corrispondere al nome del file (senza .pdf)
        nome_cane = f.name.split('.')[0].strip().capitalize()
        dati = extract_pdf_data(f)
        if dati:
            database_pdf[nome_cane] = dati
    st.sidebar.success(f"✅ {len(database_pdf)} schede caricate")

# --- INTERFACCIA PRINCIPALE ---
col_c, col_v, col_l = st.columns(3)
with col_c:
    cani_list = df_cani_db['nome'].tolist() if 'nome' in df_cani_db.columns else []
    cani_oggi = st.multiselect("Cani presenti", cani_list, default=cani_list)
with col_v:
    vol_list = df_volontari_db['nome'].tolist() if 'nome' in df_volontari_db.columns else []
    vol_oggi = st.multiselect("Volontari presenti", vol_list, default=vol_list)
with col_l:
    luoghi_list = df_luoghi_db['nome'].tolist() if 'nome' in df_luoghi_db.columns else []
    luoghi_oggi = st.multiselect("Campi agibili", luoghi_list, default=luoghi_list)

# --- PROGRAMMAZIONE ---
st.divider()
if 'programma' not in st.session_state:
    st.session_state.programma = []

# Calcolo orari limiti
inizio_lav = datetime.combine(data_turno, ora_inizio) + timedelta(minutes=15)
fine_lav = datetime.combine(data_turno, ora_fine) - timedelta(minutes=30)

st.subheader("🔗 Aggiungi Attività")
with st.container():
    c1, c2, c3, c4 = st.columns([1, 1, 1, 1])
    v_sel = c1.selectbox("Volontario", vol_oggi)
    c_sel = c2.selectbox("Cane", cani_oggi)
    l_sel = c3.selectbox("Luogo", luoghi_oggi)
    
    # Recupero tempo dal PDF per pre-compilazione
    durata_minuti = 30 # Default
    info_pdf = database_pdf.get(c_sel.capitalize(), {})
    tempo_str = info_pdf.get('TEMPO', '30')
    try:
        durata_minuti = int(re.search(r'\d+', tempo_str).group())
    except:
        durata_minuti = 30

    ora_dal = c4.time_input("Inizio", inizio_lav.time())
    # Calcolo automatico fine basato su TEMPO del PDF
    ora_al_sugg = (datetime.combine(data_turno, ora_dal) + timedelta(minutes=durata_minuti)).time()
    ora_al = c4.time_input("Fine (Auto-calc)", ora_al_sugg)

    if st.button("➕ Aggiungi al Programma"):
        # (Qui resta il tuo codice di controllo collisioni precedente...)
        st.session_state.programma.append({
            "Inizio": ora_dal.strftime('%H:%M'),
            "Fine": ora_al.strftime('%H:%M'),
            "Cane": c_sel,
            "Volontario": v_sel,
            "Luogo": l_sel,
            "CIBO": info_pdf.get('CIBO', '-'),
            "GUINZAGLIERIA": info_pdf.get('GUINZAGLIERIA', '-'),
            "STRUMENTI": info_pdf.get('STRUMENTI', '-'),
            "ATTIVITÀ": info_pdf.get('ATTIVITÀ', '-'),
            "NOTE": info_pdf.get('NOTE', '-')
        })
        st.rerun()

# --- TABELLA FINALE ---
if st.session_state.programma:
    st.write("### 📝 Programma Giornaliero")
    df_prog = pd.DataFrame(st.session_state.programma).sort_values(by="Inizio")
    st.dataframe(df_prog, use_container_width=True)
    
    if st.button("🗑️ Svuota Tutto"):
        st.session_state.programma = []
        st.rerun()

st.info(f"📋 Briefing: {ora_inizio.strftime('%H:%M')} | 🥣 Pasti: {fine_lav.strftime('%H:%M')}")

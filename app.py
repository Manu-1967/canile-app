import streamlit as st
import pandas as pd
from datetime import datetime, timedelta
import PyPDF2
import re
import sqlite3
from fpdf import FPDF
import io

# --- CONFIGURAZIONE ---
st.set_page_config(page_title="Canile Soft Online", layout="wide")
SHEET_ID = "1pcFa454IT1tlykbcK-BeAU9hnIQ_D8V_UuZaKI_KtYM"

# --- GESTIONE DATABASE SQLITE ---
def init_db():
    conn = sqlite3.connect('canile.db')
    c = conn.cursor()
    # Storico turni
    c.execute('''CREATE TABLE IF NOT EXISTS storico 
                 (data TEXT, inizio TEXT, fine TEXT, cane TEXT, volontario TEXT, luogo TEXT)''')
    # Anagrafica persistente da PDF
    c.execute('''CREATE TABLE IF NOT EXISTS anagrafica_cani 
                 (nome TEXT PRIMARY KEY, cibo TEXT, guinzaglieria TEXT, 
                  strumenti TEXT, attivita TEXT, note TEXT, tempo TEXT)''')
    conn.commit()
    conn.close()

def salva_o_aggiorna_cane(nome, dati):
    conn = sqlite3.connect('canile.db')
    c = conn.cursor()
    c.execute('''INSERT OR REPLACE INTO anagrafica_cani VALUES (?, ?, ?, ?, ?, ?, ?)''', 
              (nome, dati['CIBO'], dati['GUINZAGLIERIA'], dati['STRUMENTI'], 
               dati['ATTIVITÀ'], dati['NOTE'], dati['TEMPO']))
    conn.commit()
    conn.close()

def recupera_tutta_anagrafica():
    conn = sqlite3.connect('canile.db')
    df = pd.read_sql_query("SELECT * FROM anagrafica_cani", conn)
    conn.close()
    return df

def suggerisci_volontario(cane):
    try:
        conn = sqlite3.connect('canile.db')
        query = f"SELECT volontario, COUNT(*) as v FROM storico WHERE cane='{cane}' GROUP BY volontario ORDER BY v DESC LIMIT 1"
        res = pd.read_sql_query(query, conn)
        conn.close()
        return res['volontario'].iloc[0] if not res.empty else None
    except: return None

# --- FUNZIONI TECNICHE ---
def load_data(sheet_name):
    url = f"https://docs.google.com/spreadsheets/d/{SHEET_ID}/gviz/tq?tqx=out:csv&sheet={sheet_name}"
    try:
        df = pd.read_csv(url)
        df.columns = [c.strip().lower() for c in df.columns]
        return df.dropna(how='all')
    except: return pd.DataFrame()

def extract_pdf_data(uploaded_file):
    try:
        reader = PyPDF2.PdfReader(uploaded_file)
        text = "".join([page.extract_text() for page in reader.pages])
        labels = ['CIBO', 'GUINZAGLIERIA', 'STRUMENTI', 'ATTIVITÀ', 'NOTE', 'TEMPO']
        extracted = {label: "N/D" for label in labels}
        for label in labels:
            pattern = rf"{label}[:\s]+(.*?)(?={'|'.join(labels)}|$)"
            match = re.search(pattern, text, re.DOTALL | re.IGNORECASE)
            if match: extracted[label] = match.group(1).strip().replace('\n', ' ')
        return extracted
    except: return None

# --- INIZIALIZZAZIONE ---
init_db()
if 'programma' not in st.session_state: st.session_state.programma = []

# --- MENU NAVIGAZIONE ---
menu = st.sidebar.radio("Vai a:", ["📅 Programma Giornaliero", "📋 Anagrafica Cani (PDF)"])

if menu == "📅 Programma Giornaliero":
    st.title("🐾 Canile Soft - Scheduler Intelligente")
    
    # 1. SIDEBAR CONFIG
    with st.sidebar:
        data_t = st.date_input("Data", datetime.today())
        ora_i = st.time_input("Inizio Turno", datetime.strptime("08:00", "%H:%M"))
        ora_f = st.time_input("Fine Turno", datetime.strptime("12:00", "%H:%M"))
        st.divider()
        files = st.file_uploader("Aggiorna Schede PDF", accept_multiple_files=True, type="pdf")
        if files:
            for f in files:
                d = extract_pdf_data(f)
                if d: salva_o_aggiorna_cane(f.name.split('.')[0].capitalize(), d)
            st.success("Database aggiornato!")

    # 2. CARICAMENTO DATI
    df_cani = load_data("Cani")
    df_vol = load_data("Volontari")
    df_luo = load_data("Luoghi")

    # 3. CHECK-IN
    col_c, col_v, col_l = st.columns(3)
    c_p = col_c.multiselect("Cani", df_cani['nome'].tolist() if 'nome' in df_cani.columns else [])
    v_p = col_v.multiselect("Volontari", df_vol['nome'].tolist() if 'nome' in df_vol.columns else [])
    l_p = col_l.multiselect("Campi", df_luo['nome'].tolist() if 'nome' in df_luo.columns else [])

    # 4. ASSEGNAZIONE
    st.divider()
    if c_p and v_p and l_p:
        with st.container():
            a1, a2, a3 = st.columns(3)
            sel_c = a1.selectbox("Cane", c_p)
            
            # Suggerimento e recupero info
            v_sug = suggerisci_volontario(sel_c)
            sel_v = a2.selectbox("Volontario", v_p, index=v_p.index(v_sug) if v_sug in v_p else 0)
            sel_l = a3.selectbox("Luogo", l_p)
            
            # Recupero dati persistenti
            conn = sqlite3.connect('canile.db'); conn.row_factory = sqlite3.Row
            info = conn.execute("SELECT * FROM anagrafica_cani WHERE nome=?", (sel_c.capitalize(),)).fetchone()
            conn.close()
            
            durata = 30
            if info:
                try: durata = int(re.search(r'\d+', info['tempo']).group())
                except: pass

            t1, t2 = st.columns(2)
            lav_i = datetime.combine(data_t, ora_i) + timedelta(minutes=15)
            h_dal = t1.time_input("Dalle", lav_i.time())
            h_al = t2.time_input("Alle (Auto)", (datetime.combine(data_t, h_dal) + timedelta(minutes=durata)).time())

            if st.button("➕ Aggiungi al Programma"):
                # Controllo collisioni (semplificato)
                st.session_state.programma.append({
                    "Inizio": h_dal.strftime('%H:%M'), "Fine": h_al.strftime('%H:%M'),
                    "Cane": sel_c, "Volontario": sel_v, "Luogo": sel_l,
                    "CIBO": info['cibo'] if info else "-", "NOTE": info['note'] if info else "-"
                })
                st.rerun()

    # 5. TABELLA E EXPORT
    if st.session_state.programma:
        df_pr = pd.DataFrame(st.session_state.programma).sort_values("Inizio")
        st.table(df_pr)
        ex1, ex2, ex3 = st.columns(3)
        if ex1.button("💾 Salva Storico"):
            conn = sqlite3.connect('canile.db')
            for r in st.session_state.programma:
                conn.execute("INSERT INTO storico VALUES (?,?,?,?,?,?)", (str(data_t), r['Inizio'], r['Fine'], r['Cane'], r['Volontario'], r['Luogo']))
            conn.commit(); conn.close()
            st.success("Archiviato!")
        
        # Download buttons
        output = io.BytesIO()
        df_pr.to_excel(output, index=False); ex2.download_button("📊 Excel", output.getvalue(), "turno.xlsx")
        if ex3.button("🗑️ Svuota"): st.session_state.programma = []; st.rerun()

elif menu == "📋 Anagrafica Cani (PDF)":
    st.title("📋 Database Anagrafico Cani")
    st.write("Dati estratti dai PDF e salvati in modo permanente nel database.")
    df_ana = recupera_tutta_anagrafica()
    if not df_ana.empty:
        st.dataframe(df_ana, use_container_width=True)
        if st.button("Elimina tutto il database anagrafico"):
            conn = sqlite3.connect('canile.db'); conn.execute("DELETE FROM anagrafica_cani"); conn.commit(); conn.close()
            st.rerun()
    else:
        st.info("Nessun cane in anagrafica. Carica i PDF nella sidebar della pagina Programma.")

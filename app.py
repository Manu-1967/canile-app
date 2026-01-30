import streamlit as st
import pandas as pd
from datetime import datetime, timedelta
import PyPDF2
import re
import sqlite3
import io
import matplotlib.pyplot as plt

# --- CONFIGURAZIONE ---
st.set_page_config(page_title="Programma Canile Pro", layout="wide")

def init_db():
    """Crea il file locale canile.db se non esiste. Serve per l'anagrafica PDF."""
    conn = sqlite3.connect('canile.db')
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS storico 
                 (data TEXT, inizio TEXT, cane TEXT, volontario TEXT, luogo TEXT)''')
    # Struttura pulita senza colonna "livello"
    c.execute('''CREATE TABLE IF NOT EXISTS anagrafica_cani 
                 (nome TEXT PRIMARY KEY, cibo TEXT, guinzaglieria TEXT, strumenti TEXT, 
                  attivita TEXT, note TEXT, tempo TEXT)''')
    conn.commit()
    conn.close()

def parse_dog_pdf(uploaded_file):
    """Legge il PDF e cerca i titoli in MAIUSCOLO."""
    reader = PyPDF2.PdfReader(uploaded_file)
    full_text = ""
    for page in reader.pages:
        full_text += page.extract_text() + "\n"

    headers = ["CIBO", "GUINZAGLIERIA", "STRUMENTI", "ATTIVITÀ", "NOTE", "TEMPO"]
    nome_cane = uploaded_file.name.replace(".pdf", "").replace(".PDF", "").strip()
    dati_estratti = {"nome": nome_cane}

    for i, header in enumerate(headers):
        if i < len(headers) - 1:
            next_header = headers[i+1]
            pattern = f"{header}(.*?){next_header}"
        else:
            pattern = f"{header}(.*)$"
        match = re.search(pattern, full_text, re.DOTALL)
        if match:
            testo = match.group(1).strip()
            dati_estratti[header.lower().replace("à", "a")] = testo
        else:
            dati_estratti[header.lower().replace("à", "a")] = ""
    return dati_estratti

def salva_anagrafica_db(dati):
    conn = sqlite3.connect('canile.db')
    c = conn.cursor()
    c.execute('''INSERT OR REPLACE INTO anagrafica_cani 
                 (nome, cibo, guinzaglieria, strumenti, attivita, note, tempo) 
                 VALUES (?, ?, ?, ?, ?, ?, ?)''', 
              (dati['nome'], dati.get('cibo', ''), dati.get('guinzaglieria', ''), 
               dati.get('strumenti', ''), dati.get('attivita', ''), 
               dati.get('note', ''), dati.get('tempo', '')))
    conn.commit()
    conn.close()

def load_gsheets(sheet_name):
    """Carica la lista cani e volontari dal tuo Google Sheet."""
    url = f"https://docs.google.com/spreadsheets/d/1pcFa454IT1tlykbcK-BeAU9hnIQ_D8V_UuZaKI_KtYM/gviz/tq?tqx=out:csv&sheet={sheet_name}"
    try:
        df = pd.read_csv(url)
        df.columns = [c.strip().lower() for c in df.columns]
        return df.dropna(how='all')
    except:
        return pd.DataFrame()

def esporta_immagine(df):
    fig, ax = plt.subplots(figsize=(12, len(df)*0.6 + 1))
    ax.axis('off')
    tabla = ax.table(cellText=df.values, colLabels=df.columns, cellLoc='center', loc='center')
    tabla.auto_set_font_size(False)
    tabla.set_fontsize(10)
    tabla.scale(1.2, 1.2)
    buf = io.BytesIO()
    plt.savefig(buf, format='png', bbox_inches='tight', dpi=150)
    return buf.getvalue()

# Inizializzazione DB
init_db()
if 'programma' not in st.session_state: st.session_state.programma = []

# --- INTERFACCIA ---
st.title("🐾 Gestione Programma Canile")

with st.sidebar:
    st.header("⚙️ Impostazioni")
    data_t = st.date_input("Giorno", datetime.today())
    st.divider()
    st.header("📂 Carica PDF")
    pdf_files = st.file_uploader("Trascina qui i PDF dei cani", accept_multiple_files=True, type="pdf")
    if pdf_files and st.button("Leggi PDF e aggiorna"):
        for pdf in pdf_files:
            dati = parse_dog_pdf(pdf)
            salva_anagrafica_db(dati)
        st.success("Dati estratti salvati correttamente!")

# Caricamento dati dai tuoi Fogli Google
df_c = load_gsheets("Cani")
df_v = load_gsheets("Volontari")
df_l = load_gsheets("Luoghi")

tab_prog, tab_ana = st.tabs(["📅 Programma del Giorno", "📋 Schede Cani (da PDF)"])

with tab_prog:
    c_p = st.multiselect("🐕 Seleziona Cani", df_c['nome'].tolist() if not df_c.empty else [])
    v_p = st.multiselect("👤 Volontari in turno", df_v['nome'].tolist() if not df_v.empty else [])
    
    # Se un cane è selezionato, mostriamo un piccolo avviso se ci sono note nel DB
    if c_p:
        conn = sqlite3.connect('canile.db')
        note_df = pd.read_sql_query(f"SELECT nome, note, guinzaglieria FROM anagrafica_cani WHERE nome IN ({','.join(['?']*len(c_p))})", conn, params=c_p)
        conn.close()
        if not note_df.empty:
            with st.expander("⚠️ Note rapide cani selezionati"):
                for _, row in note_df.iterrows():
                    st.write(f"**{row['nome']}**: {row['note']} (Usa: {row['guinzaglieria']})")

    if st.button("🗑️ Svuota Programma"):
        st.session_state.programma = []
        st.rerun()

    # Qui puoi aggiungere i turni...
    # (Inserire logica di aggiunta o generazione automatica)

with tab_ana:
    st.header("📋 Informazioni estratte dai PDF")
    conn = sqlite3.connect('canile.db')
    df_db = pd.read_sql_query("SELECT * FROM anagrafica_cani", conn)
    conn.close()
    if not df_db.empty:
        st.dataframe(df_db, use_container_width=True, hide_index=True)
    else:
        st.info("L'anagrafica è vuota. Carica i PDF nella barra laterale.")

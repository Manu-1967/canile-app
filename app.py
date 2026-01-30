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
    conn = sqlite3.connect('canile.db')
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS storico 
                 (data TEXT, inizio TEXT, cane TEXT, volontario TEXT, luogo TEXT)''')
    c.execute('''CREATE TABLE IF NOT EXISTS anagrafica_cani 
                 (nome TEXT PRIMARY KEY, cibo TEXT, guinzaglieria TEXT, strumenti TEXT, 
                  attivita TEXT, note TEXT, tempo TEXT)''')
    conn.commit()
    conn.close()

def parse_dog_pdf(uploaded_file):
    reader = PyPDF2.PdfReader(uploaded_file)
    full_text = ""
    for page in reader.pages:
        full_text += page.extract_text() + "\n"
    headers = ["CIBO", "GUINZAGLIERIA", "STRUMENTI", "ATTIVITÀ", "NOTE", "TEMPO"]
    nome_cane = uploaded_file.name.replace(".pdf", "").replace(".PDF", "").strip()
    dati_estratti = {"nome": nome_cane}
    for i, header in enumerate(headers):
        pattern = f"{header}(.*?){headers[i+1]}" if i < len(headers)-1 else f"{header}(.*)$"
        match = re.search(pattern, full_text, re.DOTALL)
        dati_estratti[header.lower().replace("à", "a")] = match.group(1).strip() if match else ""
    return dati_estratti

def salva_anagrafica_db(dati):
    conn = sqlite3.connect('canile.db')
    c = conn.cursor()
    c.execute('''INSERT OR REPLACE INTO anagrafica_cani VALUES (?,?,?,?,?,?,?)''', 
              (dati['nome'], dati.get('cibo',''), dati.get('guinzaglieria',''), 
               dati.get('strumenti',''), dati.get('attivita',''), dati.get('note',''), dati.get('tempo','')))
    conn.commit()
    conn.close()

def get_info_cane(nome_cane):
    conn = sqlite3.connect('canile.db')
    df = pd.read_sql_query("SELECT * FROM anagrafica_cani WHERE nome=?", conn, params=(nome_cane,))
    conn.close()
    return df.iloc[0].to_dict() if not df.empty else {}

def load_gsheets(sheet_name):
    url = f"https://docs.google.com/spreadsheets/d/1pcFa454IT1tlykbcK-BeAU9hnIQ_D8V_UuZaKI_KtYM/gviz/tq?tqx=out:csv&sheet={sheet_name}"
    try:
        df = pd.read_csv(url)
        df.columns = [c.strip().lower() for c in df.columns]
        return df.dropna(how='all')
    except: return pd.DataFrame()

def esporta_immagine(df):
    # Regoliamo la larghezza in base al numero di colonne per non tagliare il testo
    fig, ax = plt.subplots(figsize=(22, len(df)*0.9 + 2)) 
    ax.axis('off')
    # Creazione tabella con allineamento a sinistra per le note lunghe
    tabla = ax.table(cellText=df.values, colLabels=df.columns, cellLoc='left', loc='center')
    tabla.auto_set_font_size(False)
    tabla.set_fontsize(9)
    tabla.scale(1.0, 2.2) # Aumentata l'altezza delle celle per i testi lunghi
    buf = io.BytesIO()
    plt.savefig(buf, format='png', bbox_inches='tight', dpi=150)
    return buf.getvalue()

# Inizializzazione
init_db()
if 'programma' not in st.session_state: st.session_state.programma = []

st.title("🐾 Programma Canile con Modifica Rapida")

with st.sidebar:
    st.header("📂 Caricamento PDF")
    pdf_files = st.file_uploader("Trascina qui i file", accept_multiple_files=True, type="pdf")
    if pdf_files and st.button("🔄 Aggiorna Database"):
        for pdf in pdf_files:
            salva_anagrafica_db(parse_dog_pdf(pdf))
        st.success("Dati PDF salvati!")
    data_t = st.date_input("Data Turno", datetime.today())

df_c = load_gsheets("Cani")
df_v = load_gsheets("Volontari")
df_l = load_gsheets("Luoghi")

tab_prog, tab_ana = st.tabs(["📅 Gestione Turni", "📋 Database Cani"])

with tab_prog:
    # --- AREA INSERIMENTO ---
    with st.expander("➕ Aggiungi Nuovo Turno", expanded=True):
        c1, c2, c3 = st.columns(3)
        c_sel = c1.selectbox("Cane", ["-"] + (df_c['nome'].tolist() if not df_c.empty else []))
        v_sel = c2.multiselect("Volontari", df_v['nome'].tolist() if not df_v.empty else [])
        l_sel = c3.selectbox("Luogo", ["-"] + (df_l['nome'].tolist() if not df_l.empty else []))
        
        c4, c5 = st.columns(2)
        o_sel = c4.time_input("Ora Inizio", datetime.strptime("08:00", "%H:%M"))
        
        if st.button("Inserisci Turno"):
            if c_sel != "-":
                info = get_info_cane(c_sel)
                st.session_state.programma.append({
                    "Ora": o_sel.strftime('%H:%M'),
                    "Cane": c_sel,
                    "Volontari": ", ".join(v_sel),
                    "Luogo": l_sel,
                    "Cibo": info.get('cibo', '-'),
                    "Guinzaglio": info.get('guinzaglieria', '-'),
                    "Strumenti": info.get('strumenti', '-'),
                    "Attività": info.get('attivita', '-'),
                    "Note": info.get('note', '-'),
                    "Tempo": info.get('tempo', '-')
                })
                st.rerun()

    # --- TABELLA EDITABILE ---
    if st.session_state.programma:
        st.subheader("📝 Modifica e Personalizza")
        st.info("💡 Puoi cliccare su qualsiasi cella (Note, Cibo, ecc.) per modificare il testo manualmente.")
        
        df_edit = pd.DataFrame(st.session_state.programma).sort_values("Ora")
        
        # st.data_editor permette la modifica manuale dei dati estratti
        edited_df = st.data_editor(df_edit, use_container_width=True, hide_index=True)
        
        # Sincronizza le modifiche fatte a mano
        st.session_state.programma = edited_df.to_dict('records')
        
        st.divider()
        col_del, col_down = st.columns([1, 1])
        
        if col_del.button("🗑️ Svuota Tutto"):
            st.session_state.programma = []
            st.rerun()
            
        # Generazione immagine con i dati (eventualmente modificati)
        img_data = esporta_immagine(edited_df)
        col_down.download_button("📸 Scarica per WhatsApp", data=img_data, file_name=f"programma_{data_t}.png", mime="image/png")

with tab_ana:
    conn = sqlite3.connect('canile.db')
    st.dataframe(pd.read_sql_query("SELECT * FROM anagrafica_cani", conn), use_container_width=True, hide_index=True)
    conn.close()

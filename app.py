import streamlit as st
import pandas as pd
from datetime import datetime, timedelta
import PyPDF2
import re
import sqlite3
import io

# --- CONFIGURAZIONE E STILE ---
st.set_page_config(page_title="Canile Soft - Smart PDF", layout="wide")
st.markdown("""
    <style>
    .reportview-container { background: #f0f2f6; }
    .stTable { background-color: white; border-radius: 10px; }
    </style>
    """, unsafe_allow_html=True)

SHEET_ID = "1pcFa454IT1tlykbcK-BeAU9hnIQ_D8V_UuZaKI_KtYM"

# --- LOGICA ESTRAZIONE PDF AVANZATA ---
def extract_pdf_data(uploaded_file):
    try:
        reader = PyPDF2.PdfReader(uploaded_file)
        text = ""
        for page in reader.pages:
            text += page.extract_text() + "\n"
        
        # Le tue voci in MAIUSCOLO
        labels = ['CIBO', 'GUINZAGLIERIA', 'STRUMENTI', 'ATTIVITÀ', 'NOTE', 'TEMPO']
        extracted = {label: "N/D" for label in labels}
        
        # Regex: Cerca il Titolo e prende tutto fino al prossimo Titolo o fine file
        # (?i) rende la ricerca case-insensitive se necessario, ma qui cerchiamo i tuoi titoli fissi
        for i, label in enumerate(labels):
            # Crea una lista delle altre etichette per fermare la cattura
            altre_labels = "|".join([l for l in labels if l != label])
            pattern = rf"{label}[:\s\n]+(.*?)(?=\n(?:{altre_labels})[:\s]|$)"
            
            # re.DOTALL permette al punto (.) di includere anche i caratteri "nuova riga" (\n)
            match = re.search(pattern, text, re.DOTALL | re.IGNORECASE)
            if match:
                extracted[label] = match.group(1).strip()
        
        return extracted
    except Exception as e:
        st.error(f"Errore nella lettura del PDF: {e}")
        return None

# --- DATABASE LOGIC ---
def init_db():
    conn = sqlite3.connect('canile.db')
    c = conn.cursor()
    c.execute('CREATE TABLE IF NOT EXISTS storico (data TEXT, inizio TEXT, fine TEXT, cane TEXT, volontario TEXT, luogo TEXT)')
    c.execute('CREATE TABLE IF NOT EXISTS anagrafica_cani (nome TEXT PRIMARY KEY, cibo TEXT, guinzaglieria TEXT, strumenti TEXT, attivita TEXT, note TEXT, tempo TEXT)')
    conn.commit()
    conn.close()

def load_data(sheet_name):
    url = f"https://docs.google.com/spreadsheets/d/{SHEET_ID}/gviz/tq?tqx=out:csv&sheet={sheet_name}"
    try:
        df = pd.read_csv(url)
        df.columns = [c.strip().lower() for c in df.columns]
        return df.dropna(how='all')
    except: return pd.DataFrame()

init_db()

# --- INTERFACCIA ---
menu = st.sidebar.radio("Navigazione", ["📅 Gestione Turno", "📋 Database Cani"])

if menu == "📅 Gestione Turno":
    st.title("🐾 Canile Soft - Programmazione")

    # Sidebar: Orari e Caricamento PDF
    with st.sidebar:
        data_t = st.date_input("Data", datetime.today())
        ora_i = st.time_input("Inizio", datetime.strptime("08:00", "%H:%M"))
        ora_f = st.time_input("Fine", datetime.strptime("12:00", "%H:%M"))
        st.divider()
        files = st.file_uploader("Carica PDF Cani (Aggiorna Database)", accept_multiple_files=True, type="pdf")
        if files:
            for f in files:
                d = extract_pdf_data(f)
                if d:
                    nome_cane = f.name.split('.')[0].strip().capitalize()
                    conn = sqlite3.connect('canile.db')
                    conn.execute("""INSERT OR REPLACE INTO anagrafica_cani 
                                    VALUES (?,?,?,?,?,?,?)""", 
                                 (nome_cane, d['CIBO'], d['GUINZAGLIERIA'], d['STRUMENTI'], d['ATTIVITÀ'], d['NOTE'], d['TEMPO']))
                    conn.commit(); conn.close()
            st.success("Dati PDF acquisiti correttamente.")

    # Caricamento dati da Google
    df_c = load_data("Cani"); df_v = load_data("Volontari"); df_l = load_data("Luoghi")

    # Check-in
    st.subheader("✅ 1. Check-in Disponibilità")
    c1, c2, c3 = st.columns(3)
    c_p = c1.multiselect("Cani pronti", df_c['nome'].tolist() if 'nome' in df_c.columns else [], default=df_c['nome'].tolist())
    v_p = c2.multiselect("Volontari presenti", df_v['nome'].tolist() if 'nome' in df_v.columns else [], default=df_v['nome'].tolist())
    l_p = c3.multiselect("Campi agibili", df_l['nome'].tolist() if 'nome' in df_l.columns else [], default=df_l['nome'].tolist())

    # Pianificazione
    st.divider()
    if c_p and v_p and l_p:
        st.subheader("🔗 2. Nuova Attività")
        col1, col2, col3 = st.columns(3)
        sel_c = col1.selectbox("Cane", c_p)
        
        # Recupero dati da Database
        conn = sqlite3.connect('canile.db'); conn.row_factory = sqlite3.Row
        info = conn.execute("SELECT * FROM anagrafica_cani WHERE nome=?", (sel_c.capitalize(),)).fetchone()
        conn.close()

        # Suggerimento Volontario
        conn = sqlite3.connect('canile.db')
        v_sug = pd.read_sql_query(f"SELECT volontario FROM storico WHERE cane='{sel_c}' GROUP BY volontario ORDER BY COUNT(*) DESC LIMIT 1", conn)
        v_nome = v_sug['volontario'].iloc[0] if not v_sug.empty else None
        conn.close()
        
        sel_v = col2.selectbox("Volontario", v_p, index=v_p.index(v_nome) if v_nome in v_p else 0)
        sel_l = col3.selectbox("Luogo", l_p)

        # Orari
        t_start = datetime.combine(data_t, ora_i) + timedelta(minutes=15)
        h_dal = col1.time_input("Inizio", t_start.time())
        
        durata_min = 30
        if info:
            try: durata_min = int(re.search(r'\d+', info['tempo']).group())
            except: pass
        
        h_al = col2.time_input("Fine (Auto)", (datetime.combine(data_t, h_dal) + timedelta(minutes=durata_min)).time())

        if info:
            st.info(f"💡 **Info {sel_c}:** {info['note'][:150]}...")

        if st.button("➕ Aggiungi al Programma", use_container_width=True):
            if 'programma' not in st.session_state: st.session_state.programma = []
            st.session_state.programma.append({
                "Orario": f"{h_dal.strftime('%H:%M')} - {h_al.strftime('%H:%M')}",
                "Inizio": h_dal.strftime('%H:%M'),
                "Cane": sel_c,
                "Volontario": sel_v,
                "Luogo": sel_l,
                "Cibo": info['cibo'] if info else "-",
                "Attività": info['attivita'] if info else "-",
                "Guinzaglieria": info['guinzaglieria'] if info else "-",
                "Note": info['note'] if info else "-"
            })
            st.rerun()

    # Visualizzazione
    if 'programma' in st.session_state and st.session_state.programma:
        st.divider()
        st.subheader("📝 3. Riepilogo Turno")
        df_prog = pd.DataFrame(st.session_state.programma).sort_values("Inizio")
        st.dataframe(df_prog, use_container_width=True)

        # Export e Salva
        b1, b2, b3 = st.columns(3)
        if b1.button("💾 Salva Storico"):
            conn = sqlite3.connect('canile.db')
            for r in st.session_state.programma:
                conn.execute("INSERT INTO storico VALUES (?,?,?,?,?,?)", (str(data_t), r['Inizio'], "-", r['Cane'], r['Volontario'], r['Luogo']))
            conn.commit(); conn.close(); st.success("Salvataggio completato!")
        
        output = io.BytesIO()
        df_prog.to_excel(output, index=False)
        b2.download_button("📊 Scarica Excel", output.getvalue(), "programma.xlsx")
        if b3.button("🗑️ Svuota"): st.session_state.programma = []; st.rerun()

elif menu == "📋 Database Cani":
    st.title("📋 Database Persistente")
    df_ana = pd.read_sql_query("SELECT * FROM anagrafica_cani", sqlite3.connect('canile.db'))
    st.dataframe(df_ana, use_container_width=True)

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

# CSS Personalizzato per tabelle e bottoni
st.markdown("""
    <style>
    .stTable {font-size: 14px;}
    .css-12w0qpk {padding: 2rem;}
    div[data-testid="stMetricValue"] {font-size: 24px; color: #4CAF50;}
    </style>
    """, unsafe_allow_html=True)

SHEET_ID = "1pcFa454IT1tlykbcK-BeAU9hnIQ_D8V_UuZaKI_KtYM"

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

# --- HELPER FUNCTIONS ---
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

init_db()

# --- NAVIGAZIONE ---
menu = st.sidebar.radio("Navigazione", ["📅 Gestione Turno", "📋 Database Cani (PDF)"])

if menu == "📅 Gestione Turno":
    st.title("🐾 Canile Soft - Dashboard Operativa")
    
    # --- SIDEBAR E PDF ---
    with st.sidebar:
        st.header("⚙️ Parametri Turno")
        data_t = st.date_input("Giorno", datetime.today())
        ora_i = st.time_input("Inizio", datetime.strptime("08:00", "%H:%M"))
        ora_f = st.time_input("Fine", datetime.strptime("12:00", "%H:%M"))
        st.divider()
        files = st.file_uploader("Carica/Aggiorna Schede PDF", accept_multiple_files=True, type="pdf")
        if files:
            for f in files:
                d = extract_pdf_data(f)
                if d:
                    conn = sqlite3.connect('canile.db')
                    conn.execute("INSERT OR REPLACE INTO anagrafica_cani VALUES (?,?,?,?,?,?,?)", 
                                (f.name.split('.')[0].capitalize(), d['CIBO'], d['GUINZAGLIERIA'], d['STRUMENTI'], d['ATTIVITÀ'], d['NOTE'], d['TEMPO']))
                    conn.commit(); conn.close()
            st.success("Database PDF Aggiornato")

    # --- CARICAMENTO DATI ---
    df_c = load_data("Cani")
    df_v = load_data("Volontari")
    df_l = load_data("Luoghi")

    # --- 1. CHECK-IN MIGLIORATO ---
    st.subheader("✅ 1. Check-in Disponibilità")
    
    with st.expander("Apri pannello presenze", expanded=True):
        col1, col2, col3 = st.columns(3)
        with col1:
            st.write("**🐕 Cani Pronti**")
            c_p = st.multiselect("Seleziona chi esce oggi", df_c['nome'].tolist() if 'nome' in df_c.columns else [], default=df_c['nome'].tolist())
        with col2:
            st.write("**👤 Volontari**")
            v_p = st.multiselect("Chi è presente?", df_v['nome'].tolist() if 'nome' in df_v.columns else [], default=df_v['nome'].tolist())
        with col3:
            st.write("**📍 Campi**")
            l_p = st.multiselect("Campi utilizzabili", df_l['nome'].tolist() if 'nome' in df_l.columns else [], default=df_l['nome'].tolist())

    # Metriche veloci
    m1, m2, m3 = st.columns(3)
    m1.metric("Cani", len(c_p))
    m2.metric("Volontari", len(v_p))
    m3.metric("Campi", len(l_p))

    # --- 2. ASSEGNAZIONE ATTIVITÀ ---
    st.divider()
    st.subheader("🔗 2. Pianificazione Attività")
    
    if c_p and v_p and l_p:
        with st.container():
            # Griglia di selezione pulita
            row1 = st.columns([2, 2, 2])
            sel_c = row1[0].selectbox("Cane", c_p)
            
            # Suggerimento automatico
            conn = sqlite3.connect('canile.db')
            v_sug = pd.read_sql_query(f"SELECT volontario FROM storico WHERE cane='{sel_c}' GROUP BY volontario ORDER BY COUNT(*) DESC LIMIT 1", conn)
            v_sug_nome = v_sug['volontario'].iloc[0] if not v_sug.empty else None
            conn.close()
            
            sel_v = row1[1].selectbox("Volontario", v_p, index=v_p.index(v_sug_nome) if v_sug_nome in v_p else 0)
            sel_l = row1[2].selectbox("Luogo", l_p)
            
            if v_sug_nome: st.caption(f"💡 Suggerimento: {sel_c} lavora spesso con {v_sug_nome}")

            # Dettagli da PDF (Recupero automatico)
            conn = sqlite3.connect('canile.db'); conn.row_factory = sqlite3.Row
            info = conn.execute("SELECT * FROM anagrafica_cani WHERE nome=?", (sel_c.capitalize(),)).fetchone()
            conn.close()

            row2 = st.columns([1, 1, 4])
            lav_i = datetime.combine(data_t, ora_i) + timedelta(minutes=15)
            h_dal = row2[0].time_input("Inizio", lav_i.time())
            
            durata = 30
            if info:
                try: durata = int(re.search(r'\d+', info['tempo']).group())
                except: pass
            
            h_al = row2[1].time_input("Fine", (datetime.combine(data_t, h_dal) + timedelta(minutes=durata)).time())
            
            # Anteprima dati cane
            if info:
                row2[2].info(f"📋 **Note PDF:** {info['note']} | **Cibo:** {info['cibo']}")
            else:
                row2[2].warning("⚠️ Nessun PDF trovato per questo cane.")

            if st.button("🚀 Conferma e Aggiungi al Programma", use_container_width=True):
                if 'programma' not in st.session_state: st.session_state.programma = []
                st.session_state.programma.append({
                    "Orario": f"{h_dal.strftime('%H:%M')} - {h_al.strftime('%H:%M')}",
                    "Inizio": h_dal.strftime('%H:%M'),
                    "Cane": sel_c,
                    "Volontario": sel_v,
                    "Luogo": sel_l,
                    "Cibo": info['cibo'] if info else "-",
                    "Attività": info['attivita'] if info else "-",
                    "Guinzaglieria": info['guinzaglieria'] if info else "-"
                })
                st.rerun()

    # --- 3. TABELLA PROGRAMMA MIGLIORATA ---
    if 'programma' in st.session_state and st.session_state.programma:
        st.divider()
        st.subheader("📝 3. Programma del Giorno")
        
        df_pr = pd.DataFrame(st.session_state.programma).sort_values("Inizio")
        
        # Stilizzazione Tabella con Pandas Styler
        def highlight_rows(s):
            return ['background-color: #f0f2f6' if i % 2 == 0 else '' for i in range(len(s))]
        
        st.dataframe(df_pr.style.apply(highlight_rows, axis=0), use_container_width=True)

        # Azioni Finali
        c_ex1, c_ex2, c_ex3 = st.columns(3)
        if c_ex1.button("💾 Salva in Storico", use_container_width=True):
            conn = sqlite3.connect('canile.db')
            for r in st.session_state.programma:
                conn.execute("INSERT INTO storico VALUES (?,?,?,?,?,?)", (str(data_t), r['Inizio'], "-", r['Cane'], r['Volontario'], r['Luogo']))
            conn.commit(); conn.close(); st.success("Salvato!")

        # Export Excel
        output = io.BytesIO()
        df_pr.to_excel(output, index=False)
        c_ex2.download_button("📊 Scarica Excel", output.getvalue(), f"turno_{data_t}.xlsx", use_container_width=True)

        if c_ex3.button("🗑️ Svuota Tutto", use_container_width=True):
            st.session_state.programma = []; st.rerun()

    st.write("---")
    st.caption(f"🏁 Briefing: {ora_i.strftime('%H:%M')} | 🥣 Pasti: {(datetime.combine(data_t, ora_f) - timedelta(minutes=30)).strftime('%H:%M')}")

elif menu == "📋 Database Cani (PDF)":
    st.title("📋 Anagrafica Permanente Cani")
    conn = sqlite3.connect('canile.db')
    df_ana = pd.read_sql_query("SELECT * FROM anagrafica_cani", conn)
    conn.close()
    
    if not df_ana.empty:
        st.write("Dati estratti e memorizzati dai PDF caricati.")
        st.table(df_ana)
    else:
        st.info("L'anagrafica è vuota. Carica i PDF nella sidebar della gestione turno.")

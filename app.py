import streamlit as st
import pandas as pd
from datetime import datetime, timedelta
import PyPDF2
import re
import sqlite3
import io

# --- CONFIGURAZIONE ---
st.set_page_config(page_title="Canile Soft - Gestione Pro", layout="wide")

# Mappa Colori per Gerarchia
COLOR_MAP = {"ROSSO": 3, "GIALLO": 2, "VERDE": 1, "N/D": 0}

# --- FUNZIONI CORE ---
def extract_pdf_data(uploaded_file):
    try:
        reader = PyPDF2.PdfReader(uploaded_file)
        text = "".join([page.extract_text() + "\n" for page in reader.pages])
        labels = ['CIBO', 'GUINZAGLIERIA', 'STRUMENTI', 'ATTIVITÀ', 'NOTE', 'TEMPO', 'LIVELLO']
        extracted = {label: "N/D" for label in labels}
        for label in labels:
            altre = "|".join([l for l in labels if l != label])
            pattern = rf"{label}[:\s\n]+(.*?)(?=\n(?:{altre})[:\s]|$)"
            match = re.search(pattern, text, re.DOTALL | re.IGNORECASE)
            if match: extracted[label] = match.group(1).strip()
        return extracted
    except: return None

def init_db():
    conn = sqlite3.connect('canile.db')
    c = conn.cursor()
    c.execute('CREATE TABLE IF NOT EXISTS storico (data TEXT, inizio TEXT, cane TEXT, volontario TEXT, luogo TEXT)')
    c.execute('''CREATE TABLE IF NOT EXISTS anagrafica_cani 
                 (nome TEXT PRIMARY KEY, cibo TEXT, guinzaglieria TEXT, strumenti TEXT, attivita TEXT, note TEXT, tempo TEXT, livello TEXT)''')
    conn.commit(); conn.close()

def load_gsheets(sheet_name):
    url = f"https://docs.google.com/spreadsheets/d/1pcFa454IT1tlykbcK-BeAU9hnIQ_D8V_UuZaKI_KtYM/gviz/tq?tqx=out:csv&sheet={sheet_name}"
    try:
        df = pd.read_csv(url); df.columns = [c.strip().lower() for c in df.columns]
        return df.dropna(how='all')
    except: return pd.DataFrame()

init_db()

# --- SIDEBAR ---
with st.sidebar:
    st.header("⚙️ Parametri Turno")
    data_t = st.date_input("Data", datetime.today())
    ora_i = st.time_input("Inizio", datetime.strptime("08:00", "%H:%M"))
    ora_f = st.time_input("Fine", datetime.strptime("12:00", "%H:%M"))
    st.divider()
    files = st.file_uploader("Carica PDF Cani", accept_multiple_files=True, type="pdf")
    if files:
        conn = sqlite3.connect('canile.db')
        for f in files:
            d = extract_pdf_data(f)
            if d:
                nome = f.name.split('.')[0].strip().capitalize()
                conn.execute("INSERT OR REPLACE INTO anagrafica_cani VALUES (?,?,?,?,?,?,?,?)", 
                             (nome, d['CIBO'], d['GUINZAGLIERIA'], d['STRUMENTI'], d['ATTIVITÀ'], d['NOTE'], d['TEMPO'], d['LIVELLO']))
        conn.commit(); conn.close(); st.success("Anagrafica PDF Aggiornata")

# --- CARICAMENTO DATI ---
df_c = load_gsheets("Cani")
df_v = load_gsheets("Volontari") # Assumiamo colonne 'nome' e 'livello'
df_l = load_gsheets("Luoghi")

# --- INTERFACCIA PRINCIPALE ---
menu = st.tabs(["📅 Programma Turno", "📋 Anagrafica Cani"])

with menu[0]:
    st.subheader("✅ 1. Check-in Disponibilità")
    c1, c2, c3 = st.columns(3)
    c_p = c1.multiselect("Cani", df_c['nome'].tolist() if not df_c.empty else [])
    v_p = c2.multiselect("Volontari", df_v['nome'].tolist() if not df_v.empty else [])
    l_p = c3.multiselect("Campi", [l for l in df_l['nome'].tolist() if l != "Duca Park"] if not df_l.empty else [])

    if 'programma' not in st.session_state: st.session_state.programma = []

    # --- INSERIMENTO MANUALE ---
    st.divider()
    with st.expander("✍️ Inserimento Manuale (Prioritario)"):
        m1, m2, m3, m4 = st.columns(4)
        m_cane = m1.selectbox("Cane", c_p if c_p else ["-"])
        m_vol = m2.selectbox("Volontario Principale", v_p if v_p else ["-"])
        m_luo = m3.selectbox("Luogo", df_l['nome'].tolist() if not df_l.empty else ["-"])
        m_dur = m4.number_input("Durata (min)", 10, 120, 30)
        if st.button("➕ Aggiungi riga manuale"):
            st.session_state.programma.append({"Cane": m_cane, "Volontario": m_vol, "Luogo": m_luo, "Durata": m_dur, "Manuale": True})
            st.rerun()

    # --- MOTORE AUTOMATICO ---
    if st.button("🤖 GENERA / COMPLETA (Rispetta Colori e Storico)", use_container_width=True):
        final_prog = []
        conn = sqlite3.connect('canile.db'); conn.row_factory = sqlite3.Row
        
        # 1. Briefing
        start_dt = datetime.combine(data_t, ora_i)
        final_prog.append({"Orario": f"{start_dt.strftime('%H:%M')} - {(start_dt+timedelta(minutes=15)).strftime('%H:%M')}", 
                           "Cane": "TUTTI", "Volontario": "TUTTI", "Luogo": "Ufficio", "Attività": "Briefing", "Inizio_Sort": start_dt.strftime('%H:%M')})
        
        # 2. Preparazione code
        cani_da_fare = [c for c in c_p if c not in [r['Cane'] for r in st.session_state.programma]]
        vols_pool = v_p.copy()
        
        curr_t = start_dt + timedelta(minutes=15)
        limit_t = datetime.combine(data_t, ora_f) - timedelta(minutes=30)
        
        while (cani_da_fare or vols_pool) and curr_t < limit_t:
            campi_disponibili = l_p.copy()
            while cani_da_fare and campi_disponibili and vols_pool:
                cane_nome = cani_da_fare.pop(0)
                info = conn.execute("SELECT * FROM anagrafica_cani WHERE nome=?", (cane_nome.capitalize(),)).fetchone()
                cane_lvl = COLOR_MAP.get(str(info['livello']).upper(), 0) if info else 0
                
                # Trova il miglior volontario: 1. Colore >= Cane, 2. Più storico
                best_v = None
                max_storico = -1
                
                for v_nome in vols_pool:
                    v_info = df_v[df_v['nome'] == v_nome].iloc[0]
                    v_lvl = COLOR_MAP.get(str(v_info['livello']).upper(), 0) if 'livello' in v_info else 0
                    
                    if v_lvl >= cane_lvl:
                        storic_count = conn.execute("SELECT COUNT(*) FROM storico WHERE cane=? AND volontario=?", (cane_nome, v_nome)).fetchone()[0]
                        if storic_count > max_storico:
                            max_storico = storic_count
                            best_v = v_nome
                
                if not best_v: best_v = vols_pool[0] # Fallback se nessuno ha il colore (allerta sicurezza)
                
                vols_pool.remove(best_v)
                v_label = best_v
                
                # Supporto: se avanzano volontari, accoppiali
                while len(vols_pool) > len(cani_da_fare) and vols_pool:
                    sup = vols_pool.pop(0)
                    v_label += f" + {sup} (Sup.)"
                
                durata = int(re.search(r'\d+', info['tempo']).group()) if info and info['tempo'] != "N/D" else 30
                
                final_prog.append({
                    "Orario": f"{curr_t.strftime('%H:%M')} - {(curr_t+timedelta(minutes=durata)).strftime('%H:%M')}",
                    "Cane": cane_nome, "Volontario": v_label, "Luogo": campi_disponibili.pop(0),
                    "Cibo": info['cibo'] if info else "-", "Note": info['note'] if info else "-",
                    "Attività": info['attivita'] if info else "Uscita", "Inizio_Sort": curr_t.strftime('%H:%M')
                })
            
            curr_t += timedelta(minutes=45) # Slot successivo
            vols_pool = v_p.copy() # Reset per nuovo slot

        # Pasti
        pasti_t = datetime.combine(data_t, ora_f) - timedelta(minutes=30)
        final_prog.append({"Orario": f"{pasti_t.strftime('%H:%M')} - {ora_f.strftime('%H:%M')}", "Cane": "TUTTI", "Volontario": "TUTTI", "Luogo": "Box", "Attività": "Pasti", "Inizio_Sort": pasti_t.strftime('%H:%M')})
        st.session_state.programma = final_prog
        conn.close(); st.rerun()

    # --- VISUALIZZAZIONE EDITOR ---
    if st.session_state.programma:
        df_edit = pd.DataFrame(st.session_state.programma).sort_values("Inizio_Sort")
        st.data_editor(df_edit.drop(columns=['Inizio_Sort'], errors='ignore'), use_container_width=True, hide_index=True)

with menu[1]:
    st.subheader("📋 Database persistente dai PDF")
    conn = sqlite3.connect('canile.db')
    try:
        df_db = pd.read_sql_query("SELECT * FROM anagrafica_cani", conn)
        st.dataframe(df_db, use_container_width=True)
    except: st.info("Database vuoto.")
    conn.close()

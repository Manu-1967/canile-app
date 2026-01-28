import streamlit as st
import pandas as pd
from datetime import datetime, timedelta
import PyPDF2
import re
import sqlite3
import io

# --- CONFIGURAZIONE ---
st.set_page_config(page_title="Canile Soft - Gestione Totale", layout="wide")

COLOR_MAP = {"ROSSO": 3, "GIALLO": 2, "VERDE": 1, "N/D": 0}

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
            reader = PyPDF2.PdfReader(f)
            text = "".join([p.extract_text() for p in reader.pages])
            d = {l: "N/D" for l in ['CIBO', 'GUINZAGLIERIA', 'STRUMENTI', 'ATTIVITÀ', 'NOTE', 'TEMPO', 'LIVELLO']}
            for l in d.keys():
                match = re.search(rf"{l}[:\s\n]+(.*?)(?=\n(?:CIBO|GUINZAGLIERIA|STRUMENTI|ATTIVITÀ|NOTE|TEMPO|LIVELLO)[:\s]|$)", text, re.DOTALL | re.IGNORECASE)
                if match: d[l] = match.group(1).strip()
            nome = f.name.split('.')[0].strip().capitalize()
            conn.execute("INSERT OR REPLACE INTO anagrafica_cani VALUES (?,?,?,?,?,?,?,?)", 
                         (nome, d['CIBO'], d['GUINZAGLIERIA'], d['STRUMENTI'], d['ATTIVITÀ'], d['NOTE'], d['TEMPO'], d['LIVELLO']))
        conn.commit(); conn.close(); st.success("Anagrafica PDF Aggiornata")

df_c = load_gsheets("Cani"); df_v = load_gsheets("Volontari"); df_l = load_gsheets("Luoghi")

# --- INTERFACCIA ---
if 'programma' not in st.session_state: st.session_state.programma = []

menu = st.tabs(["📅 Programma Turno", "📋 Anagrafica Cani"])

with menu[0]:
    st.subheader("✅ 1. Disponibilità")
    c1, c2, c3 = st.columns(3)
    c_p = c1.multiselect("Cani", df_c['nome'].tolist() if not df_c.empty else [])
    v_p = c2.multiselect("Volontari", df_v['nome'].tolist() if not df_v.empty else [])
    l_p = c3.multiselect("Campi", [l for l in df_l['nome'].tolist() if l != "Duca Park"] if not df_l.empty else [])

    st.divider()
    
    # --- AGGIUNTA MANUALE ---
    with st.expander("➕ Aggiungi riga al programma (Manuale)"):
        col1, col2, col3, col4 = st.columns(4)
        m_cane = col1.selectbox("Cane", ["-"] + c_p)
        m_vol = col2.selectbox("Volontario", ["-"] + v_p)
        m_luo = col3.selectbox("Luogo", ["-"] + (df_l['nome'].tolist() if not df_l.empty else []))
        m_ora = col4.time_input("Ora Inizio", ora_i)
        if st.button("Aggiungi riga"):
            if m_cane != "-":
                st.session_state.programma.append({
                    "Orario": f"{m_ora.strftime('%H:%M')} - {(datetime.combine(data_t, m_ora)+timedelta(minutes=30)).strftime('%H:%M')}",
                    "Cane": m_cane, "Volontario": m_vol, "Luogo": m_luo, "Attività": "Manuale", "Inizio_Sort": m_ora.strftime('%H:%M')
                })
                st.rerun()

    # --- GENERAZIONE AUTOMATICA / COMPLETAMENTO ---
    col_btn1, col_btn2 = st.columns(2)
    
    if col_btn1.button("🤖 Completa Automaticamente Mancanti", use_container_width=True):
        conn = sqlite3.connect('canile.db'); conn.row_factory = sqlite3.Row
        
        # Garantisci Briefing e Pasti se non presenti
        if not any(r.get('Luogo') == 'Ufficio' for r in st.session_state.programma):
            st.session_state.programma.append({"Orario": f"{ora_i.strftime('%H:%M')} - {(datetime.combine(data_t, ora_i)+timedelta(minutes=15)).strftime('%H:%M')}", "Cane": "TUTTI", "Volontario": "TUTTI", "Luogo": "Ufficio", "Attività": "Briefing", "Inizio_Sort": ora_i.strftime('%H:%M')})
        
        cani_fatti = [r['Cane'] for r in st.session_state.programma]
        cani_restanti = [c for c in c_p if c not in cani_fatti]
        vols_pool = v_p.copy()
        
        curr_t = datetime.combine(data_t, ora_i) + timedelta(minutes=15)
        limit_t = datetime.combine(data_t, ora_f) - timedelta(minutes=30)

        while cani_restanti and curr_t < limit_t:
            campi_occupati = [r['Luogo'] for r in st.session_state.programma if r.get('Inizio_Sort') == curr_t.strftime('%H:%M')]
            campi_liberi = [l for l in l_p if l not in campi_occupati]
            
            while cani_restanti and campi_liberi and vols_pool:
                cane = cani_restanti.pop(0)
                info = conn.execute("SELECT * FROM anagrafica_cani WHERE nome=?", (cane.capitalize(),)).fetchone()
                
                # Assegnazione per Colore/Esperienza (Semplificata per brevità)
                v_scelto = vols_pool.pop(0)
                v_label = v_scelto
                while len(vols_pool) > len(cani_restanti) and vols_pool:
                    v_label += f" + {vols_pool.pop(0)} (Sup.)"

                st.session_state.programma.append({
                    "Orario": f"{curr_t.strftime('%H:%M')} - {(curr_t+timedelta(minutes=30)).strftime('%H:%M')}",
                    "Cane": cane, "Volontario": v_label, "Luogo": campi_liberi.pop(0),
                    "Cibo": info['cibo'] if info else "-", "Note": info['note'] if info else "-",
                    "Attività": info['attivita'] if info else "Uscita", "Inizio_Sort": curr_t.strftime('%H:%M')
                })
            curr_t += timedelta(minutes=30)
            vols_pool = v_p.copy()
        
        conn.close(); st.rerun()

    if col_btn2.button("🗑️ Svuota e Rifai Tutto", use_container_width=True):
        st.session_state.programma = []
        st.rerun()

    # --- EDITOR TABELLARE ---
    if st.session_state.programma:
        st.subheader("📝 Modifica il Programma")
        df_prog = pd.DataFrame(st.session_state.programma).sort_values("Inizio_Sort")
        
        # L'editor permette di modificare ogni singola cella o aggiungere/rimuovere righe
        df_modificato = st.data_editor(
            df_prog,
            num_rows="dynamic",
            use_container_width=True,
            hide_index=True,
            column_config={
                "Inizio_Sort": None,
                "Note": st.column_config.TextColumn(width="large"),
                "Cibo": st.column_config.TextColumn(width="large"),
                "Attività": st.column_config.TextColumn(width="large")
            }
        )
        st.session_state.programma = df_modificato.to_dict('records')

        # EXPORT
        output = io.BytesIO()
        with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
            df_modificato.drop(columns=['Inizio_Sort']).to_excel(writer, index=False)
        st.download_button("📊 Scarica Excel Aggiornato", output.getvalue(), f"turno_{data_t}.xlsx")

with menu[1]:
    conn = sqlite3.connect('canile.db')
    st.dataframe(pd.read_sql_query("SELECT * FROM anagrafica_cani", conn), use_container_width=True)
    conn.close()

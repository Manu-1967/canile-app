import streamlit as st
import pandas as pd
from datetime import datetime, timedelta
import PyPDF2
import re
import sqlite3
import io

# --- CONFIGURAZIONE ---
st.set_page_config(page_title="Canile Soft - Mobile", layout="wide")

# Mappa conflitti (Da memoria utente)
CONFLITTI = {
    "Lago Park": "Central Park", "Central Park": "Lago Park",
    "Peter Park": "Duca Park", "Duca Park": "Peter Park"
}

def init_db():
    conn = sqlite3.connect('canile.db') #
    c = conn.cursor()
    c.execute('CREATE TABLE IF NOT EXISTS storico (data TEXT, inizio TEXT, cane TEXT, volontario TEXT, luogo TEXT)')
    c.execute('''CREATE TABLE IF NOT EXISTS anagrafica_cani 
                 (nome TEXT PRIMARY KEY, cibo TEXT, guinzaglieria TEXT, strumenti TEXT, attivita TEXT, note TEXT, tempo TEXT, livello TEXT)''')
    conn.commit(); conn.close()

def load_gsheets(sheet_name):
    url = f"https://docs.google.com/spreadsheets/d/1pcFa454IT1tlykbcK-BeAU9hnIQ_D8V_UuZaKI_KtYM/gviz/tq?tqx=out:csv&sheet={sheet_name}"
    try:
        df = pd.read_csv(url)
        df.columns = [c.strip().lower() for c in df.columns]
        return df.dropna(how='all')
    except: return pd.DataFrame()

init_db()

# --- SESSION STATE ---
if 'programma' not in st.session_state: st.session_state.programma = []
if 'affinita' not in st.session_state: st.session_state.affinita = {}
if 'luoghi_pref' not in st.session_state: st.session_state.luoghi_pref = {}

# --- SIDEBAR ---
with st.sidebar:
    st.header("⚙️ Configurazione")
    data_t = st.date_input("Data Turno", datetime.today())
    ora_i = st.time_input("Inizio", datetime.strptime("08:00", "%H:%M"))
    ora_f = st.time_input("Fine", datetime.strptime("12:00", "%H:%M"))
    files = st.file_uploader("📂 PDF Schede Cani", accept_multiple_files=True, type="pdf")
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
        conn.commit(); conn.close(); st.success("Database aggiornato!")

df_c = load_gsheets("Cani"); df_v = load_gsheets("Volontari"); df_l = load_gsheets("Luoghi")

st.title("📱 Canile Soft")

# Selezione Risorse
c1, c2, c3 = st.columns(3)
c_p = c1.multiselect("Cani Presenti", df_c['nome'].tolist() if not df_c.empty else [])
v_p = c2.multiselect("Volontari Presenti", df_v['nome'].tolist() if not df_v.empty else [])
# Duca Park escluso di default dal completamento automatico
l_p_auto = [l for l in df_l['nome'].tolist() if l != "Duca Park"] if not df_l.empty else []
l_all = df_l['nome'].tolist() if not df_l.empty else []

tab_prog, tab_ana, tab_set = st.tabs(["📅 Programma", "🐕 Anagrafica", "⚙️ Impostazioni"])

# --- TAB SETTINGS ---
with tab_set:
    st.subheader("🔗 Link Rapidi (Affinità e Luoghi)")
    col_s1, col_s2 = st.columns(2)
    with col_s1:
        c_aff = st.selectbox("Cane", ["-"] + c_p, key="sel_c_aff")
        v_aff = st.multiselect("Volontari Preferiti", v_p, key="sel_v_aff")
        if st.button("Salva Affinità"):
            st.session_state.affinita[c_aff] = v_aff
    with col_s2:
        c_loc = st.selectbox("Cane", ["-"] + c_p, key="sel_c_loc")
        l_pref = st.multiselect("Campi Preferiti", l_all, key="sel_l_pref")
        if st.button("Salva Preferenza Campo"):
            st.session_state.luoghi_pref[c_loc] = l_pref

# --- TAB PROGRAMMA ---
with tab_prog:
    with st.expander("✍️ Inserimento Manuale"):
        mc1, mc2, mc3, mc4 = st.columns(4)
        m_cane = mc1.selectbox("Cane", ["-"] + c_p)
        m_vol = mc2.selectbox("Volontario", ["-"] + v_p)
        m_luo = mc3.selectbox("Luogo", ["-"] + l_all)
        m_ora = mc4.time_input("Inizio", ora_i)
        if st.button("➕ Aggiungi riga"):
            st.session_state.programma.append({
                "Orario": f"{m_ora.strftime('%H:%M')} - {(datetime.combine(data_t, m_ora)+timedelta(minutes=30)).strftime('%H:%M')}",
                "Cane": m_cane, "Volontario": m_vol, "Luogo": m_luo, "Attività": "Uscita", 
                "Inizio_Sort": m_ora.strftime('%H:%M'), "Tipo": "Manuale"
            })

    btn_auto, btn_clear = st.columns(2)
    
    if btn_auto.button("🤖 Genera Programma Intelligente", use_container_width=True):
        conn = sqlite3.connect('canile.db'); conn.row_factory = sqlite3.Row
        start_dt = datetime.combine(data_t, ora_i)
        end_dt = datetime.combine(data_t, ora_f)
        pasti_dt = end_dt - timedelta(minutes=30) # Pasti fine turno
        
        # Svuota auto precedenti ma tieni manuali
        st.session_state.programma = [r for r in st.session_state.programma if r['Tipo'] == "Manuale"]
        
        # 1. Briefing
        st.session_state.programma.append({
            "Orario": f"{start_dt.strftime('%H:%M')} - {(start_dt+timedelta(minutes=15)).strftime('%H:%M')}",
            "Cane": "TUTTI", "Volontario": "TUTTI", "Luogo": "Ufficio", "Attività": "Briefing",
            "Inizio_Sort": start_dt.strftime('%H:%M'), "Tipo": "Auto"
        })

        cani_fatti = [r['Cane'] for r in st.session_state.programma if r['Cane'] != "TUTTI"]
        cani_da_fare = [c for c in c_p if c not in cani_fatti]
        curr_t = start_dt + timedelta(minutes=15)

        while cani_da_fare and curr_t < pasti_dt:
            v_disponibili = v_p.copy()
            l_disponibili = l_p_auto.copy()
            ora_str = curr_t.strftime('%H:%M')
            
            # Rimuovi chi è già impegnato in attività manuali in questo orario
            impegnati_man = [r for r in st.session_state.programma if r['Inizio_Sort'] == ora_str]
            for r in impegnati_man:
                if r['Volontario'] in v_disponibili: v_disponibili.remove(r['Volontario'])
                if r['Luogo'] in l_disponibili: l_disponibili.remove(r['Luogo'])

            # Applica conflitti spaziali
            for r in impegnati_man:
                if r['Luogo'] in CONFLITTI:
                    vietato = CONFLITTI[r['Luogo']]
                    if vietato in l_disponibili: l_disponibili.remove(vietato)

            # Ordina cani per preferenza campo
            cani_da_fare.sort(key=lambda c: 1 if c in st.session_state.luoghi_pref and any(lp in l_disponibili for lp in st.session_state.luoghi_pref[c]) else 0, reverse=True)

            # Assegnazione slot
            while cani_da_fare and v_disponibili and l_disponibili:
                cane = cani_da_fare.pop(0)
                
                # Scelta Luogo
                campo = None
                if cane in st.session_state.luoghi_pref:
                    for pref in st.session_state.luoghi_pref[cane]:
                        if pref in l_disponibili: campo = pref; break
                if not campo: campo = l_disponibili[0]
                
                l_disponibili.remove(campo)
                if campo in CONFLITTI and CONFLITTI[campo] in l_disponibili:
                    l_disponibili.remove(CONFLITTI[campo])

                # Scelta Volontario (Logica: Affinità -> Storico)
                v_scelto = None
                if cane in st.session_state.affinita:
                    for pref_v in st.session_state.affinita[cane]:
                        if pref_v in v_disponibili: v_scelto = pref_v; break
                
                if not v_scelto:
                    v_scores = []
                    for v in v_disponibili:
                        count = conn.execute("SELECT COUNT(*) FROM storico WHERE cane=? AND volontario=?", (cane, v)).fetchone()[0]
                        v_scores.append((v, count))
                    v_scores.sort(key=lambda x: x[1], reverse=True)
                    v_scelto = v_scores[0][0]

                v_disponibili.remove(v_scelto)
                
                info = conn.execute("SELECT * FROM anagrafica_cani WHERE nome=?", (cane.capitalize(),)).fetchone()
                st.session_state.programma.append({
                    "Orario": f"{ora_str} - {(curr_t+timedelta(minutes=30)).strftime('%H:%M')}",
                    "Cane": cane, "Volontario": v_scelto, "Luogo": campo,
                    "Cibo": info['cibo'] if info else "-", "Note": info['note'] if info else "-",
                    "Attività": info['attivita'] if info else "Uscita",
                    "Inizio_Sort": ora_str, "Tipo": "Auto"
                })

            curr_t += timedelta(minutes=30)

        # 3. Pasti
        st.session_state.programma.append({
            "Orario": f"{pasti_dt.strftime('%H:%M')} - {end_dt.strftime('%H:%M')}",
            "Cane": "TUTTI", "Volontario": "TUTTI", "Luogo": "Box", "Attività": "Pasti",
            "Inizio_Sort": pasti_dt.strftime('%H:%M'), "Tipo": "Auto"
        })
        conn.close(); st.rerun()

    if btn_clear.button("🗑️ Svuota Tutto", use_container_width=True):
        st.session_state.programma = []; st.rerun()

    # Visualizzazione Tabella
    if st.session_state.programma:
        df_view = pd.DataFrame(st.session_state.programma).sort_values("Inizio_Sort")
        df_edited = st.data_editor(df_view, use_container_width=True, hide_index=True, height=600)
        st.session_state.programma = df_edited.to_dict('records')

# --- TAB ANAGRAFICA ---
with tab_ana:
    conn = sqlite3.connect('canile.db')
    df_db = pd.read_sql_query("SELECT * FROM anagrafica_cani", conn)
    conn.close()
    st.dataframe(df_db, use_container_width=True)

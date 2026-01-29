import streamlit as st
import pandas as pd
from datetime import datetime, timedelta
import PyPDF2
import re
import sqlite3
import io

# --- CONFIGURAZIONE ---
st.set_page_config(page_title="Canile Soft v3.1 - Safety Edition", layout="centered")

def init_db():
    conn = sqlite3.connect('canile.db')
    c = conn.cursor()
    c.execute('CREATE TABLE IF NOT EXISTS storico (data TEXT, inizio TEXT, cane TEXT, volontario TEXT, luogo TEXT)')
    c.execute('''CREATE TABLE IF NOT EXISTS anagrafica_cani 
                 (nome TEXT PRIMARY KEY, cibo TEXT, guinzaglieria TEXT, strumenti TEXT, 
                  attivita TEXT, note TEXT, tempo TEXT, livello TEXT)''')
    conn.commit()
    conn.close()

def load_gsheets(sheet_name):
    url = f"https://docs.google.com/spreadsheets/d/1pcFa454IT1tlykbcK-BeAU9hnIQ_D8V_UuZaKI_KtYM/gviz/tq?tqx=out:csv&sheet={sheet_name}"
    try:
        df = pd.read_csv(url)
        df.columns = [c.strip().lower() for c in df.columns]
        
        if sheet_name == "Luoghi":
            if 'automatico' not in df.columns: df['automatico'] = 'sì'
            if 'adiacenza' not in df.columns: df['adiacenza'] = ""
            
        return df.dropna(how='all')
    except:
        return pd.DataFrame()

def parse_pdf_content(text):
    campi = ['CIBO', 'GUINZAGLIERIA', 'STRUMENTI', 'ATTIVITÀ', 'NOTE', 'TEMPO', 'LIVELLO']
    dati_estratti = {c: "N/D" for c in campi}
    for campo in campi:
        pattern = rf"{campo}[:\s\n]+(.*?)(?=\n(?:{'|'.join(campi)})[:\s]|$)"
        match = re.search(pattern, text, re.DOTALL | re.IGNORECASE)
        if match:
            dati_estratti[campo] = match.group(1).strip()
    return dati_estratti

# --- FUNZIONE DI SICUREZZA ADIACENZE ---
def is_safe_placement(cane_nome, luogo_nome, occupazioni_attuali, df_cani, df_luoghi):
    """Verifica se il cane può stare nel luogo senza conflitti con i vicini."""
    # 1. Recupera reattività del cane dal DataFrame Google Sheets
    info_cane = df_cani[df_cani['nome'].str.lower() == cane_nome.lower()]
    reattivita = 0
    if not info_cane.empty:
        reattivita = pd.to_numeric(info_cane.iloc[0].get('reattività', 0), errors='coerce')
    
    # Se il cane non è reattivo (>5), è sempre sicuro
    if reattivita <= 5:
        return True

    # 2. Se è reattivo, cerchiamo i luoghi adiacenti
    info_luogo = df_luoghi[df_luoghi['nome'].str.lower() == luogo_nome.lower()]
    if info_luogo.empty:
        return True
    
    adiacenti_str = str(info_luogo.iloc[0].get('adiacenza', ""))
    if not adiacenti_str or adiacenti_str.lower() == "nan":
        return True 

    lista_adiacenti = [l.strip().lower() for l in adiacenti_str.split(',')]

    # 3. Controlla se nei luoghi adiacenti c'è già un cane (qualsiasi cane)
    for occ in occupazioni_attuali:
        if str(occ['Luogo']).lower() in lista_adiacenti:
            return False 
            
    return True

init_db()

# --- SIDEBAR ---
with st.sidebar:
    st.header("⚙️ Setup")
    data_t = st.date_input("Data", datetime.today())
    ora_i = st.time_input("Inizio", datetime.strptime("08:00", "%H:%M"))
    ora_f = st.time_input("Fine", datetime.strptime("12:00", "%H:%M"))
    
    st.divider()
    pdf_files = st.file_uploader("📂 Carica/Aggiorna PDF Cani", accept_multiple_files=True, type="pdf")
    if pdf_files:
        conn = sqlite3.connect('canile.db')
        for f in pdf_files:
            reader = PyPDF2.PdfReader(f)
            text = " ".join([page.extract_text() for page in reader.pages])
            info = parse_pdf_content(text)
            nome_cane = f.name.split('.')[0].strip().capitalize()
            conn.execute("INSERT OR REPLACE INTO anagrafica_cani VALUES (?,?,?,?,?,?,?,?)", 
                         (nome_cane, info['CIBO'], info['GUINZAGLIERIA'], info['STRUMENTI'], 
                          info['ATTIVITÀ'], info['NOTE'], info['TEMPO'], info['LIVELLO']))
        conn.commit(); conn.close()
        st.success("Anagrafica aggiornata!")

df_c = load_gsheets("Cani"); df_v = load_gsheets("Volontari"); df_l = load_gsheets("Luoghi")
if 'programma' not in st.session_state: st.session_state.programma = []

st.title("📱 Canile Soft v3.1")

# --- SELEZIONE RISORSE ---
c_p = st.multiselect("🐕 Cani in turno", df_c['nome'].tolist() if not df_c.empty else [])
v_p = st.multiselect("👤 Volontari presenti", df_v['nome'].tolist() if not df_v.empty else [])
l_p = st.multiselect("📍 Luoghi disponibili (Aperti oggi)", df_l['nome'].tolist() if not df_l.empty else [])

tab_prog, tab_ana = st.tabs(["📅 Programma", "📋 Anagrafica"])

with tab_prog:
    # 1. INSERIMENTO MANUALE
    with st.expander("✍️ Inserimento Libero (Manuale)"):
        col1, col2 = st.columns(2)
        m_cane = col1.selectbox("Cane", ["-"] + c_p)
        m_luo = col2.selectbox("Luogo", ["-"] + l_p)
        m_vols = st.multiselect("Volontari assegnati", v_p)
        m_ora = st.time_input("Ora Inizio", ora_i)
        
        if st.button("➕ Aggiungi Manualmente"):
            if m_cane != "-":
                ora_str = m_ora.strftime('%H:%M')
                conflitti = []
                for turno in st.session_state.programma:
                    if turno["Orario"] == ora_str:
                        vols_occupati = [v.strip() for v in turno["Volontario"].split(",")]
                        for v_scelto in m_vols:
                            if v_scelto in vols_occupati:
                                conflitti.append(v_scelto)
                
                if conflitti:
                    st.error(f"Attenzione! I seguenti volontari sono già occupati alle {ora_str}: {', '.join(conflitti)}")
                else:
                    st.session_state.programma.append({
                        "Orario": ora_str, "Cane": m_cane, 
                        "Volontario": ", ".join(m_vols) if m_vols else "Da assegnare", 
                        "Luogo": m_luo, "Attività": "Manuale", "Inizio_Sort": ora_str
                    })
                    st.success(f"Turno delle {ora_str} aggiunto!")
                    st.rerun()

    # 2. GENERAZIONE AUTOMATICA CON LOGICA DI SICUREZZA
    c_btn1, c_btn2 = st.columns(2)
    
    if c_btn1.button("🤖 Genera/Completa Automatico", use_container_width=True):
        conn = sqlite3.connect('canile.db'); conn.row_factory = sqlite3.Row
        start_dt = datetime.combine(data_t, ora_i)
        end_dt = datetime.combine(data_t, ora_f)
        pasti_dt = end_dt - timedelta(minutes=30) 
        
        manuali_esistenti = [r for r in st.session_state.programma if r.get("Attività") == "Manuale"]
        st.session_state.programma = []
        
        st.session_state.programma.append({
            "Orario": start_dt.strftime('%H:%M'), "Cane": "TUTTI", "Volontario": "TUTTI", 
            "Luogo": "Ufficio", "Attività": "Briefing", "Inizio_Sort": start_dt.strftime('%H:%M')
        })

        cani_gia_occupati = [m["Cane"] for m in manuali_esistenti]
        cani_da_fare = [c for c in c_p if c not in cani_gia_occupati]
        curr_t = start_dt + timedelta(minutes=15)
        
        luoghi_auto_ok = []
        if not df_l.empty and 'automatico' in df_l.columns:
             filtro = (df_l['nome'].isin(l_p)) & (df_l['automatico'].astype(str).str.lower().str.strip() == 'sì')
             luoghi_auto_ok = df_l[filtro]['nome'].tolist()
        else:
             luoghi_auto_ok = l_p.copy()

        # --- ALGORITMO DI ASSEGNAZIONE ---
        while cani_da_fare and curr_t < pasti_dt and luoghi_auto_ok:
            ora_attuale_str = curr_t.strftime('%H:%M')
            
            vols_impegnati_ora = []
            occupazioni_ora = []
            for m in manuali_esistenti:
                if m["Orario"] == ora_attuale_str:
                    vols_impegnati_ora.extend([v.strip() for v in str(m["Volontario"]).split(",")])
                    occupazioni_ora.append({"Cane": m["Cane"], "Luogo": m["Luogo"]})

            vols_liberi = [v for v in v_p if v not in vols_impegnati_ora]
            campi_disponibili = [l for l in luoghi_auto_ok if l not in [o["Luogo"] for o in occupazioni_ora]]
            
            batch_inseriti = []
            
            # Tentativo di inserimento per ogni cane rimasto
            for i in range(len(cani_da_fare)):
                if not vols_liberi or not campi_disponibili:
                    break
                
                cane = cani_da_fare[i]
                campo_scelto = None
                
                # Cerca il primo campo sicuro per questo cane
                for campo in campi_disponibili:
                    if is_safe_placement(cane, campo, occupazioni_ora, df_c, df_l):
                        campo_scelto = campo
                        break
                
                if campo_scelto:
                    cani_da_fare.pop(i)
                    campi_disponibili.remove(campo_scelto)
                    
                    # Punteggio volontario
                    vols_punteggio = []
                    for v in vols_liberi:
                        cnt = conn.execute("SELECT COUNT(*) FROM storico WHERE cane=? AND volontario=?", (cane, v)).fetchone()[0]
                        vols_punteggio.append((v, cnt))
                    vols_punteggio.sort(key=lambda x: x[1], reverse=True)
                    
                    lead = vols_punteggio[0][0]
                    vols_liberi.remove(lead)
                    
                    info = conn.execute("SELECT note FROM anagrafica_cani WHERE nome=?", (cane.capitalize(),)).fetchone()
                    
                    assegnazione = {
                        "Orario": ora_attuale_str, "Cane": cane, "Volontario": lead, 
                        "Luogo": campo_scelto, "Note": info['note'] if info else "-", 
                        "Inizio_Sort": ora_attuale_str, "Attività": "Automatico",
                        "sups": [] # Temporaneo per i supporti
                    }
                    batch_inseriti.append(assegnazione)
                    occupazioni_ora.append({"Cane": cane, "Luogo": campo_scelto})
                    break # Forza ricalcolo indice dopo pop

            # Distribuzione volontari extra come supporti
            if vols_liberi and batch_inseriti:
                idx = 0
                while vols_liberi:
                    batch_inseriti[idx % len(batch_inseriti)]["sups"].append(vols_liberi.pop(0))
                    idx += 1
            
            # Finalizzazione stringa volontari e aggiunta a session_state
            for b in batch_inseriti:
                if b["sups"]:
                    b["Volontario"] += f" + {', '.join(b['sups'])}"
                del b["sups"]
                st.session_state.programma.append(b)
            
            curr_t += timedelta(minutes=45)

        st.session_state.programma.extend(manuali_esistenti)
        st.session_state.programma.append({
            "Orario": pasti_dt.strftime('%H:%M'), "Cane": "TUTTI", "Volontario": "TUTTI", 
            "Luogo": "Box", "Attività": "Pasti", "Inizio_Sort": pasti_dt.strftime('%H:%M')
        })
        conn.close(); st.rerun()

    if c_btn2.button("🗑️ Svuota", use_container_width=True):
        st.session_state.programma = []; st.rerun()

    if st.session_state.programma:
        df_view = pd.DataFrame(st.session_state.programma).sort_values("Inizio_Sort")
        df_edited = st.data_editor(df_view, use_container_width=True, hide_index=True, num_rows="dynamic")
        st.session_state.programma = df_edited.to_dict('records')

with tab_ana:
    conn = sqlite3.connect('canile.db')
    df_db = pd.read_sql_query("SELECT * FROM anagrafica_cani", conn)
    if not df_db.empty:
        c_del = st.selectbox("Seleziona cane da eliminare", ["-"] + df_db['nome'].tolist())
        if st.button("❌ Elimina Record"):
            if c_del != "-":
                conn.execute("DELETE FROM anagrafica_cani WHERE nome=?", (c_del,))
                conn.commit(); st.rerun()
        st.divider()
        st.dataframe(df_db, use_container_width=True, hide_index=True)
    conn.close()

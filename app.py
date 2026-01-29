import streamlit as st
import pandas as pd
from datetime import datetime, timedelta
import PyPDF2
import re
import sqlite3
import io

# --- CONFIGURAZIONE ---
st.set_page_config(page_title="Canile Soft v3", layout="centered")

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
    # Link al tuo Google Sheet (assicurati che sia pubblico o accessibile)
    url = f"https://docs.google.com/spreadsheets/d/1pcFa454IT1tlykbcK-BeAU9hnIQ_D8V_UuZaKI_KtYM/gviz/tq?tqx=out:csv&sheet={sheet_name}"
    try:
        df = pd.read_csv(url)
        df.columns = [c.strip().lower() for c in df.columns]
        
        # ### MODIFICA: Gestione sicurezza colonna 'automatico' per i Luoghi
        if sheet_name == "Luoghi" and 'automatico' not in df.columns:
            # Se la colonna non esiste nel foglio, assumiamo 'sì' per tutto per non rompere il codice
            df['automatico'] = 'sì'
            
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

st.title("📱 Canile Soft")

# --- SELEZIONE RISORSE ---
c_p = st.multiselect("🐕 Cani in turno", df_c['nome'].tolist() if not df_c.empty else [])
v_p = st.multiselect("👤 Volontari presenti", df_v['nome'].tolist() if not df_v.empty else [])
l_p = st.multiselect("📍 Luoghi disponibili (Aperti oggi)", df_l['nome'].tolist() if not df_l.empty else [])

tab_prog, tab_ana = st.tabs(["📅 Programma", "📋 Anagrafica"])

with tab_prog:
    # 1. INSERIMENTO MANUALE (Flessibile al 100% - Qui vede TUTTI i luoghi selezionati)
    with st.expander("✍️ Inserimento Libero (Manuale)"):
        col1, col2 = st.columns(2)
        m_cane = col1.selectbox("Cane", ["-"] + c_p)
        m_luo = col2.selectbox("Luogo", ["-"] + l_p) # Qui mostriamo tutto quello che hai selezionato sopra
        m_vols = st.multiselect("Volontari assegnati", v_p)
        m_ora = st.time_input("Ora Inizio", ora_i)
        
        if st.button("➕ Aggiungi Manualmente"):
            if m_cane != "-":
                st.session_state.programma.append({
                    "Orario": m_ora.strftime('%H:%M'),
                    "Cane": m_cane, 
                    "Volontario": ", ".join(m_vols) if m_vols else "Da assegnare", 
                    "Luogo": m_luo, 
                    "Attività": "Manuale", 
                    "Inizio_Sort": m_ora.strftime('%H:%M')
                })
                st.rerun()

   # 2. GENERAZIONE AUTOMATICA (Con protezione inserimenti manuali)
    c_btn1, c_btn2 = st.columns(2)
    
    if c_btn1.button("🤖 Genera/Completa Automatico", use_container_width=True):
        conn = sqlite3.connect('canile.db'); conn.row_factory = sqlite3.Row
        start_dt = datetime.combine(data_t, ora_i)
        end_dt = datetime.combine(data_t, ora_f)
        pasti_dt = end_dt - timedelta(minutes=30) 
        
        # 1. SALVIAMO I MANUALI ESISTENTI
        # Filtriamo la lista attuale tenendo solo ciò che è stato inserito manualmente
        manuali_esistenti = [
            r per r in st.session_state.programma 
            if r.get("Attività") == "Manuale"
        ]
        
        # 2. Reset (Cancelliamo i vecchi automatici, ma teniamo i manuali in memoria)
        st.session_state.programma = []
        
        # Aggiungiamo il Briefing iniziale
        st.session_state.programma.append({
            "Orario": start_dt.strftime('%H:%M'), "Cane": "TUTTI", "Volontario": "TUTTI", 
            "Luogo": "Ufficio", "Attività": "Briefing", "Inizio_Sort": start_dt.strftime('%H:%M')
        })

        # 3. FILTRO CANI DA FARE
        # Prendiamo tutti i cani selezionati (c_p)
        # Ma togliamo quelli che sono già nei "manuali_esistenti" per non duplicarli
        cani_gia_assegnati = [m["Cane"] for m in manuali_esistenti]
        cani_da_fare = [c for c in c_p if c not in cani_gia_assegnati]
        
        curr_t = start_dt + timedelta(minutes=15)
        
        # Logica Luoghi Automatici
        luoghi_auto_ok = []
        if not df_l.empty and 'automatico' in df_l.columns:
             filtro = (df_l['nome'].isin(l_p)) & (df_l['automatico'].astype(str).str.lower().str.strip() == 'sì')
             luoghi_auto_ok = df_l[filtro]['nome'].tolist()
        else:
             luoghi_auto_ok = l_p.copy()
             
        if not luoghi_auto_ok:
            st.error("Attenzione: Nessun luogo selezionato è abilitato per l'uso 'Automatico'.")

        # ALGORITMO DI ASSEGNAZIONE
        while cani_da_fare and curr_t < pasti_dt and luoghi_auto_ok:
            vols_liberi = v_p.copy()
            campi_disponibili = luoghi_auto_ok.copy() 
            
            n_cani = min(len(cani_da_fare), len(campi_disponibili))
            if n_cani > 0:
                batch = []
                for _ in range(n_cani):
                    cane = cani_da_fare.pop(0)
                    campo = campi_disponibili.pop(0)
                    
                    vols_punteggio = []
                    for v in vols_liberi:
                        cnt = conn.execute("SELECT COUNT(*) FROM storico WHERE cane=? AND volontario=?", (cane, v)).fetchone()[0]
                        vols_punteggio.append((v, cnt))
                    vols_punteggio.sort(key=lambda x: x[1], reverse=True)
                    
                    lead = vols_punteggio[0][0]
                    vols_liberi.remove(lead)
                    batch.append({"cane": cane, "campo": campo, "lead": lead, "sups": []})

                # Supporti
                if vols_liberi and batch: # check batch exists
                    idx = 0
                    while vols_liberi:
                        batch[idx % len(batch)]["sups"].append(vols_liberi.pop(0))
                        idx += 1
                
                for b in batch:
                    v_str = b["lead"] + (f" + {', '.join(b['sups'])}" if b["sups"] else "")
                    info = conn.execute("SELECT note FROM anagrafica_cani WHERE nome=?", (b["cane"].capitalize(),)).fetchone()
                    st.session_state.programma.append({
                        "Orario": curr_t.strftime('%H:%M'), "Cane": b["cane"], "Volontario": v_str, 
                        "Luogo": b["campo"], "Note": info['note'] if info else "-", 
                        "Inizio_Sort": curr_t.strftime('%H:%M')
                    })
            curr_t += timedelta(minutes=45)

        # 4. REINSERIAMO I MANUALI E I PASTI
        st.session_state.programma.extend(manuali_esistenti)
        
        st.session_state.programma.append({
            "Orario": pasti_dt.strftime('%H:%M'), "Cane": "TUTTI", "Volontario": "TUTTI", 
            "Luogo": "Box", "Attività": "Pasti", "Inizio_Sort": pasti_dt.strftime('%H:%M')
        })
        conn.close(); st.rerun()

    if c_btn2.button("🗑️ Svuota Tutto", use_container_width=True):
        st.session_state.programma = []; st.rerun()
    # EDITOR FINALE
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

import streamlit as st
import pandas as pd
from datetime import datetime, timedelta
import PyPDF2
import re
import sqlite3

# --- CONFIGURAZIONE ---
st.set_page_config(page_title="Canile Soft v3", layout="wide")

def init_db():
    # Il database deve chiamarsi 'canile.db'
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
        return df.dropna(how='all')
    except:
        return pd.DataFrame()

def parse_pdf_content(text):
    """
    Estrae i dati dividendo per titoli previsti. 
    Formatta come: **TITOLO**: testo completo (inclusi spazi e invii).
    """
    campi = ['CIBO', 'GUINZAGLIERIA', 'STRUMENTI', 'ATTIVITÀ', 'NOTE', 'TEMPO', 'LIVELLO']
    dati_estratti = {c: "N/D" for c in campi}
    
    # Pulizia preliminare minima per non perdere spazi significativi
    text_clean = text.replace('\xa0', ' ')
    
    for campo in campi:
        # Regex: Cerca il titolo (case insensitive), cattura tutto fino al prossimo titolo o fine doc
        # Il flag re.DOTALL permette al punto (.) di includere i ritorni a capo
        pattern = rf"(?i){campo}[:\s\n]+(.*?)(?=\n(?:{'|'.join(campi)})[:\s]|$)"
        match = re.search(pattern, text_clean, re.DOTALL)
        
        if match:
            contenuto = match.group(1).strip()
            # Salviamo con il formato richiesto: **TITOLO**: Testo
            dati_estratti[campo] = f"**{campo.upper()}**: {contenuto}"
            
    return dati_estratti

init_db()

# --- SIDEBAR ---
with st.sidebar:
    st.header("⚙️ Setup")
    data_t = st.date_input("Data", datetime.today())
    ora_i = st.time_input("Inizio Shift", datetime.strptime("08:00", "%H:%M"))
    ora_f = st.time_input("Fine Shift", datetime.strptime("12:00", "%H:%M"))
    
    st.divider()
    pdf_files = st.file_uploader("📂 Carica PDF Cani (Aggiorna Anagrafica)", accept_multiple_files=True, type="pdf")
    
    if pdf_files:
        conn = sqlite3.connect('canile.db')
        for f in pdf_files:
            reader = PyPDF2.PdfReader(f)
            # Uniamo il testo di tutte le pagine
            text = ""
            for page in reader.pages:
                text += page.extract_text() + "\n"
            
            info = parse_pdf_content(text)
            nome_cane = f.name.split('.')[0].strip().capitalize()
            
            conn.execute("""
                INSERT OR REPLACE INTO anagrafica_cani 
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (nome_cane, info['CIBO'], info['GUINZAGLIERIA'], info['STRUMENTI'], 
                  info['ATTIVITÀ'], info['NOTE'], info['TEMPO'], info['LIVELLO']))
        conn.commit()
        conn.close()
        st.success(f"Aggiornati {len(pdf_files)} cani!")

df_c = load_gsheets("Cani")
df_v = load_gsheets("Volontari")
df_l = load_gsheets("Luoghi")

if 'programma' not in st.session_state: 
    st.session_state.programma = []

st.title("📱 Canile Soft v3")

# --- SELEZIONE RISORSE ---
col_a, col_b, col_c = st.columns(3)
with col_a:
    c_p = st.multiselect("🐕 Cani in turno", df_c['nome'].tolist() if not df_c.empty else [])
with col_b:
    v_p = st.multiselect("👤 Volontari presenti", df_v['nome'].tolist() if not df_v.empty else [])
with col_c:
    l_p = st.multiselect("📍 Luoghi disponibili", df_l['nome'].tolist() if not df_l.empty else [])

tabs = st.tabs(["📅 Programma Giornaliero", "📋 Database Anagrafica"])

with tabs[0]:
    # 1. INSERIMENTO MANUALE
    with st.expander("✍️ Assegnazione Manuale (Cane - Volontario - Luogo)"):
        c1, c2, c3 = st.columns(3)
        m_cane = c1.selectbox("Cane", ["-"] + c_p)
        m_luo = c2.selectbox("Luogo", ["-"] + l_p)
        m_vols = c3.multiselect("Volontari", v_p)
        m_ora = st.time_input("Ora Inizio Attività", ora_i)
        
        if st.button("➕ Aggiungi al Programma"):
            if m_cane != "-":
                st.session_state.programma.append({
                    "Orario": m_ora.strftime('%H:%M'),
                    "Cane": m_cane, 
                    "Volontario": ", ".join(m_vols) if m_vols else "Da assegnare", 
                    "Luogo": m_luo, 
                    "Nota": "Inserimento manuale",
                    "Inizio_Sort": m_ora.strftime('%H:%M')
                })
                st.rerun()

    # 2. GENERAZIONE AUTOMATICA
    btn_gen, btn_del = st.columns(2)
    
    if btn_gen.button("🤖 Genera Programma Automatico", use_container_width=True):
        conn = sqlite3.connect('canile.db')
        conn.row_factory = sqlite3.Row
        
        start_dt = datetime.combine(data_t, ora_i)
        end_dt = datetime.combine(data_t, ora_f)
        # Il pasto è sempre negli ultimi 30 minuti del turno
        pasti_dt = end_dt - timedelta(minutes=30) 
        
        st.session_state.programma = []
        # Briefing iniziale
        st.session_state.programma.append({
            "Orario": start_dt.strftime('%H:%M'), "Cane": "TUTTI", "Volontario": "TUTTI", 
            "Luogo": "Ufficio", "Nota": "Briefing iniziale", "Inizio_Sort": start_dt.strftime('%H:%M')
        })

        cani_da_fare = cani_da_fare = [c for c in c_p]
        curr_t = start_dt + timedelta(minutes=15)
        
        # Filtro parchi esclusi come richiesto
        parchi_esclusi = ['lago', 'centrale', 'duca', 'peter']
        luoghi_validi = [l for l in l_p if l.lower() not in parchi_esclusi]
        
        while cani_da_fare and curr_t < pasti_dt:
            vols_liberi = v_p.copy()
            campi_disponibili = luoghi_validi.copy()
            
            n_cani = min(len(cani_da_fare), len(campi_disponibili))
            if n_cani > 0:
                batch = []
                for _ in range(n_cani):
                    if not cani_da_fare or not vols_liberi: break
                    cane = cani_da_fare.pop(0)
                    campo = campi_disponibili.pop(0)
                    
                    # Logica storica semplice: chi ha lavorato meno con questo cane?
                    vols_punteggio = []
                    for v in vols_liberi:
                        cnt = conn.execute("SELECT COUNT(*) FROM storico WHERE cane=? AND volontario=?", (cane, v)).fetchone()[0]
                        vols_punteggio.append((v, cnt))
                    vols_punteggio.sort(key=lambda x: x[1])
                    
                    lead = vols_punteggio[0][0]
                    vols_liberi.remove(lead)
                    batch.append({"cane": cane, "campo": campo, "lead": lead, "sups": []})

                # Assegnazione volontari restanti come supporto
                idx = 0
                while vols_liberi and batch:
                    batch[idx % len(batch)]["sups"].append(vols_liberi.pop(0))
                    idx += 1
                
                for b in batch:
                    v_str = b["lead"] + (f" + {', '.join(b['sups'])}" if b["sups"] else "")
                    # Recupero note anagrafica
                    info = conn.execute("SELECT note FROM anagrafica_cani WHERE nome=?", (b["cane"].capitalize(),)).fetchone()
                    st.session_state.programma.append({
                        "Orario": curr_t.strftime('%H:%M'), "Cane": b["cane"], "Volontario": v_str, 
                        "Luogo": b["campo"], "Nota": info['note'] if info else "-", 
                        "Inizio_Sort": curr_t.strftime('%H:%M')
                    })
            curr_t += timedelta(minutes=45)

        # Pasti finale
        st.session_state.programma.append({
            "Orario": pasti_dt.strftime('%H:%M'), "Cane": "TUTTI", "Volontario": "TUTTI", 
            "Luogo": "Box / Zona Pasti", "Nota": "Somministrazione pasti e pulizia finale", "Inizio_Sort": pasti_dt.strftime('%H:%M')
        })
        conn.close()
        st.rerun()

    if btn_del.button("🗑️ Svuota Programma", use_container_width=True):
        st.session_state.programma = []
        st.rerun()

    # Visualizzazione e modifica tabella
    if st.session_state.programma:
        df_view = pd.DataFrame(st.session_state.programma).sort_values("Inizio_Sort")
        df_edited = st.data_editor(
            df_view, 
            use_container_width=True, 
            hide_index=True, 
            num_rows="dynamic",
            column_order=["Orario", "Cane", "Volontario", "Luogo", "Nota"]
        )
        st.session_state.programma = df_edited.to_dict('records')

with tabs[1]:
    conn = sqlite3.connect('canile.db')
    df_db = pd.read_sql_query("SELECT * FROM anagrafica_cani", conn)
    if not df_db.empty:
        col1, col2 = st.columns([3, 1])
        c_del = col1.selectbox("Seleziona cane da eliminare dal database", ["-"] + df_db['nome'].tolist())
        if col2.button("❌ Elimina", use_container_width=True):
            if c_del != "-":
                conn.execute("DELETE FROM anagrafica_cani WHERE nome=?", (c_del,))
                conn.commit()
                st.rerun()
        st.divider()
        st.write("### Schede Tecniche Estratte")
        st.table(df_db) # Utilizzo table per visualizzare meglio il testo lungo
    else:
        st.info("Nessun dato in anagrafica. Carica i PDF nella sidebar.")
    conn.close()

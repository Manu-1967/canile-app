import streamlit as st
import pandas as pd
from datetime import datetime, timedelta
import PyPDF2
import re
import sqlite3
import io

# --- CONFIGURAZIONE E STILI ---
st.set_page_config(page_title="Canile Soft v2", layout="centered")

def init_db():
    conn = sqlite3.connect('canile.db')
    c = conn.cursor()
    # Tabella storico per punteggio lead
    c.execute('CREATE TABLE IF NOT EXISTS storico (data TEXT, inizio TEXT, cane TEXT, volontario TEXT, luogo TEXT)')
    # Tabella anagrafica cani con le colonne richieste
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
    """Estrae i dati basandosi sulle intestazioni in MAIUSCOLO."""
    campi = ['CIBO', 'GUINZAGLIERIA', 'STRUMENTI', 'ATTIVITÀ', 'NOTE', 'TEMPO', 'LIVELLO']
    dati_estratti = {c: "N/D" for c in campi}
    
    for i, campo in enumerate(campi):
        # Cerca il campo e cattura tutto fino al prossimo campo in maiuscolo o fine documento
        pattern = rf"{campo}[:\s\n]+(.*?)(?=\n(?:{'|'.join(campi)})[:\s]|$)"
        match = re.search(pattern, text, re.DOTALL | re.IGNORECASE)
        if match:
            dati_estratti[campo] = match.group(1).strip()
    return dati_estratti

init_db()

# --- SIDEBAR: SETUP E CARICAMENTO PDF ---
with st.sidebar:
    st.header("⚙️ Configurazione")
    data_t = st.date_input("Data Turno", datetime.today())
    ora_i = st.time_input("Inizio Turno", datetime.strptime("08:00", "%H:%M"))
    ora_f = st.time_input("Fine Turno", datetime.strptime("12:00", "%H:%M"))
    
    st.divider()
    st.subheader("📂 Aggiorna Anagrafica Cani")
    pdf_files = st.file_uploader("Carica PDF Cani (Nuovi o Aggiornamenti)", accept_multiple_files=True, type="pdf")
    
    if pdf_files:
        conn = sqlite3.connect('canile.db')
        for f in pdf_files:
            reader = PyPDF2.PdfReader(f)
            text = " ".join([page.extract_text() for page in reader.pages])
            info = parse_pdf_content(text)
            nome_cane = f.name.split('.')[0].strip().capitalize()
            
            conn.execute('''INSERT OR REPLACE INTO anagrafica_cani 
                            VALUES (?, ?, ?, ?, ?, ?, ?, ?)''', 
                         (nome_cane, info['CIBO'], info['GUINZAGLIERIA'], info['STRUMENTI'], 
                          info['ATTIVITÀ'], info['NOTE'], info['TEMPO'], info['LIVELLO']))
        conn.commit()
        conn.close()
        st.success(f"Aggiornati {len(pdf_files)} cani!")

# Caricamento dati da GSheets
df_c = load_gsheets("Cani")
df_v = load_gsheets("Volontari")
df_l = load_gsheets("Luoghi")

if 'programma' not in st.session_state:
    st.session_state.programma = []

st.title("📱 Canile Soft")

# --- SELEZIONE RISORSE ---
c_p = st.multiselect("🐕 Cani in turno", df_c['nome'].tolist() if not df_c.empty else [])
v_p = st.multiselect("👤 Volontari presenti", df_v['nome'].tolist() if not df_v.empty else [])
l_p = st.multiselect("📍 Luoghi disponibili", df_l['nome'].tolist() if not df_l.empty else [])

tab_prog, tab_ana = st.tabs(["📅 Programma", "📋 Gestione Anagrafica"])

with tab_prog:
    # Inserimento Manuale
    with st.expander("✍️ Assegnazione Manuale"):
        col1, col2 = st.columns(2)
        m_cane = col1.selectbox("Cane", ["-"] + c_p)
        m_luo = col2.selectbox("Luogo", ["-"] + l_p)
        m_vol = st.multiselect("Volontari", v_p)
        m_ora = st.time_input("Ora Inizio", ora_i)
        
        if st.button("➕ Aggiungi al Programma"):
            if m_cane != "-" and m_vol:
                st.session_state.programma.append({
                    "Orario": m_ora.strftime('%H:%M'),
                    "Cane": m_cane, 
                    "Volontario": ", ".join(m_vol), 
                    "Luogo": m_luo, 
                    "Attività": "Manuale", 
                    "Inizio_Sort": m_ora.strftime('%H:%M')
                })
                st.rerun()

    # Generazione Automatica
    c_btn1, c_btn2 = st.columns(2)
    
    if c_btn1.button("🤖 Genera Automatico", use_container_width=True):
        conn = sqlite3.connect('canile.db')
        conn.row_factory = sqlite3.Row
        
        start_dt = datetime.combine(data_t, ora_i)
        end_dt = datetime.combine(data_t, ora_f)
        pasti_dt = end_dt - timedelta(minutes=30) # Pasti ultimi 30 min
        
        # Reset e Briefing
        st.session_state.programma = []
        st.session_state.programma.append({
            "Orario": start_dt.strftime('%H:%M'), "Cane": "TUTTI", "Volontario": "TUTTI", 
            "Luogo": "Ufficio", "Attività": "Briefing", "Inizio_Sort": start_dt.strftime('%H:%M')
        })

        cani_da_fare = c_p.copy()
        curr_t = start_dt + timedelta(minutes=15)
        
        while cani_da_fare and curr_t < pasti_dt:
            vols_liberi = v_p.copy()
            campi_liberi = l_p.copy()
            
            n_cani = min(len(cani_da_fare), len(campi_liberi))
            if n_cani > 0:
                batch = []
                for _ in range(n_cani):
                    cane = cani_da_fare.pop(0)
                    campo = campi_liberi.pop(0)
                    
                    # Punteggio basato su storico
                    vols_punteggio = []
                    for v in vols_liberi:
                        cnt = conn.execute("SELECT COUNT(*) FROM storico WHERE cane=? AND volontario=?", (cane, v)).fetchone()[0]
                        vols_punteggio.append((v, cnt))
                    vols_punteggio.sort(key=lambda x: x[1], reverse=True)
                    
                    lead = vols_punteggio[0][0]
                    vols_liberi.remove(lead)
                    batch.append({"cane": cane, "campo": campo, "lead": lead, "sups": []})

                # Distribuzione rimenenti
                idx = 0
                while vols_liberi:
                    batch[idx % len(batch)]["sups"].append(vols_liberi.pop(0))
                    idx += 1
                
                for b in batch:
                    v_completo = b["lead"] + (f" + {', '.join(b['sups'])}" if b["sups"] else "")
                    info = conn.execute("SELECT note FROM anagrafica_cani WHERE nome=?", (b["cane"].capitalize(),)).fetchone()
                    st.session_state.programma.append({
                        "Orario": curr_t.strftime('%H:%M'), "Cane": b["cane"], "Volontario": v_completo, 
                        "Luogo": b["campo"], "Note": info['note'] if info else "-", 
                        "Inizio_Sort": curr_t.strftime('%H:%M')
                    })
            curr_t += timedelta(minutes=45) # Sessioni da 45 min

        # Pasti finale
        st.session_state.programma.append({
            "Orario": pasti_dt.strftime('%H:%M'), "Cane": "TUTTI", "Volontario": "TUTTI", 
            "Luogo": "Box", "Attività": "Pasti", "Inizio_Sort": pasti_dt.strftime('%H:%M')
        })
        conn.close()
        st.rerun()

    if c_btn2.button("🗑️ Svuota Programma", use_container_width=True):
        st.session_state.programma = []
        st.rerun()

    # Visualizzazione e Download
    if st.session_state.programma:
        df_view = pd.DataFrame(st.session_state.programma).sort_values("Inizio_Sort")
        edited_df = st.data_editor(df_view, use_container_width=True, hide_index=True)
        st.session_state.programma = edited_df.to_dict('records')
        
        # Export Excel
        output = io.BytesIO()
        with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
            edited_df.to_excel(writer, index=False, sheet_name='Turno')
            workbook = writer.book
            worksheet = writer.sheets['Turno']
            wrap = workbook.add_format({'text_wrap': True, 'align': 'left', 'valign': 'top'})
            worksheet.set_column('A:E', 20, wrap)
        
        st.download_button("💾 Scarica Excel", output.getvalue(), "turno.xlsx", "application/vnd.ms-excel", use_container_width=True)

with tab_ana:
    st.subheader("📋 Database Cani (da PDF)")
    conn = sqlite3.connect('canile.db')
    df_db = pd.read_sql_query("SELECT * FROM anagrafica_cani", conn)
    
    if not df_db.empty:
        # Funzione per rimuovere un cane
        cane_da_eliminare = st.selectbox("Seleziona cane da rimuovere", ["-"] + df_db['nome'].tolist())
        if st.button("❌ Elimina Cane Selezionato"):
            if cane_da_eliminare != "-":
                conn.execute("DELETE FROM anagrafica_cani WHERE nome=?", (cane_da_eliminare,))
                conn.commit()
                st.success(f"{cane_da_eliminare} rimosso dal database.")
                st.rerun()
        
        st.divider()
        st.dataframe(df_db, use_container_width=True, hide_index=True)
    else:
        st.info("Nessun cane in anagrafica. Carica dei PDF dalla sidebar.")
    conn.close()

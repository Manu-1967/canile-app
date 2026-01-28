import streamlit as st
import pandas as pd
from datetime import datetime, timedelta
import PyPDF2
import re
import sqlite3
import io

# --- CONFIGURAZIONE ---
st.set_page_config(page_title="Canile Soft - Gestione Integrale", layout="wide")

# --- LOGICA ESTRAZIONE PDF ---
def extract_pdf_data(uploaded_file):
    try:
        reader = PyPDF2.PdfReader(uploaded_file)
        text = "".join([page.extract_text() + "\n" for page in reader.pages])
        # Cerchiamo anche il "Livello" o "Colore" nel testo
        labels = ['CIBO', 'GUINZAGLIERIA', 'STRUMENTI', 'ATTIVITÀ', 'NOTE', 'TEMPO', 'LIVELLO']
        extracted = {label: "N/D" for label in labels}
        for label in labels:
            altre = "|".join([l for l in labels if l != label])
            pattern = rf"{label}[:\s\n]+(.*?)(?=\n(?:{altre})[:\s]|$)"
            match = re.search(pattern, text, re.DOTALL | re.IGNORECASE)
            if match: extracted[label] = match.group(1).strip()
        return extracted
    except: return None

# --- DATABASE ---
def init_db():
    conn = sqlite3.connect('canile.db')
    c = conn.cursor()
    c.execute('CREATE TABLE IF NOT EXISTS storico (data TEXT, inizio TEXT, cane TEXT, volontario TEXT, luogo TEXT)')
    c.execute('''CREATE TABLE IF NOT EXISTS anagrafica_cani 
                 (nome TEXT PRIMARY KEY, cibo TEXT, guinzaglieria TEXT, strumenti TEXT, attivita TEXT, note TEXT, tempo TEXT, livello TEXT)''')
    conn.commit(); conn.close()

init_db()

def load_gsheets(sheet_name):
    url = f"https://docs.google.com/spreadsheets/d/1pcFa454IT1tlykbcK-BeAU9hnIQ_D8V_UuZaKI_KtYM/gviz/tq?tqx=out:csv&sheet={sheet_name}"
    try:
        df = pd.read_csv(url)
        df.columns = [c.strip().lower() for c in df.columns]
        return df.dropna(how='all')
    except: return pd.DataFrame()

# --- INTERFACCIA ---
st.title("🐾 Gestione Turno con Supporto e Gerarchia")

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
        conn.commit(); conn.close(); st.success("Database PDF Aggiornato")

df_c = load_gsheets("Cani"); df_v = load_gsheets("Volontari"); df_l = load_gsheets("Luoghi")

# --- CHECK-IN ---
st.subheader("✅ Disponibilità Operativa")
c1, c2, c3 = st.columns(3)
c_p = c1.multiselect("Cani", df_c['nome'].tolist() if not df_c.empty else [])
v_p = c2.multiselect("Volontari", df_v['nome'].tolist() if not df_v.empty else [])
l_p = c3.multiselect("Campi (Duca Park escluso da auto)", [l for l in df_l['nome'].tolist() if l != "Duca Park"] if not df_l.empty else [])

if 'programma' not in st.session_state: st.session_state.programma = []

# --- LOGICA DI ASSEGNAZIONE ---
if st.button("🤖 Genera Programma (Tutti i volontari al lavoro)", use_container_width=True):
    if not (c_p and v_p):
        st.error("Seleziona cani e volontari!")
    else:
        final_prog = []
        start_dt = datetime.combine(data_t, ora_i)
        end_dt = datetime.combine(data_t, ora_f)
        
        # 1. Briefing
        final_prog.append({"Orario": f"{start_dt.strftime('%H:%M')} - {(start_dt+timedelta(minutes=15)).strftime('%H:%M')}", 
                           "Cane": "TUTTI", "Volontario": "TUTTI", "Luogo": "Ufficio", "Attività": "Briefing", "Inizio_Sort": start_dt.strftime('%H:%M')})
        
        curr_t = start_dt + timedelta(minutes=15)
        limit_t = end_dt - timedelta(minutes=30)
        
        # Copia delle liste per gestione code
        cani_queue = c_p.copy()
        vols_pool = v_p.copy()
        
        # Database per info cani e livelli
        conn = sqlite3.connect('canile.db'); conn.row_factory = sqlite3.Row
        
        while cani_queue and curr_t < limit_t:
            vols_attivi = []
            # In questo slot, proviamo a far uscire quanti più cani possibile in base ai campi
            campi_disponibili = l_p.copy()
            
            while cani_queue and campi_disponibili and vols_pool:
                cane = cani_queue.pop(0)
                info = conn.execute("SELECT * FROM anagrafica_cani WHERE nome=?", (cane.capitalize(),)).fetchone()
                
                # Scegliamo il volontario principale (più esperto per quel cane se possibile)
                # In questa versione semplificata prendiamo il primo, ma assegniamo SUPPORTI
                v_main = vols_pool.pop(0)
                v_string = v_main
                
                # Se abbiamo volontari extra, assegniamoli come SUPPORTO
                while len(vols_pool) > len(cani_queue) and vols_pool:
                    v_supporto = vols_pool.pop(0)
                    v_string += f" + {v_supporto} (Sup.)"
                
                durata = 30
                if info and info['tempo'] != "N/D":
                    try: durata = int(re.search(r'\d+', info['tempo']).group())
                    except: pass
                
                final_prog.append({
                    "Orario": f"{curr_t.strftime('%H:%M')} - {(curr_t+timedelta(minutes=durata)).strftime('%H:%M')}",
                    "Cane": cane, "Volontario": v_string, "Luogo": campi_disponibili.pop(0),
                    "Cibo": info['cibo'] if info else "-", "Note": info['note'] if info else "-",
                    "Attività": info['attivita'] if info else "Uscita", "Inizio_Sort": curr_t.strftime('%H:%M')
                })
            
            curr_t += timedelta(minutes=30)
            vols_pool = v_p.copy() # Reset pool per il prossimo slot se necessario
            
        # 2. Pasti
        pasti_t = end_dt - timedelta(minutes=30)
        final_prog.append({"Orario": f"{pasti_t.strftime('%H:%M')} - {end_dt.strftime('%H:%M')}", 
                           "Cane": "TUTTI", "Volontario": "TUTTI", "Luogo": "Box", "Attività": "Pasti", "Inizio_Sort": pasti_t.strftime('%H:%M')})
        
        st.session_state.programma = final_prog
        conn.close()
        st.rerun()

# --- VISUALIZZAZIONE E EXCEL ---
if st.session_state.programma:
    st.divider()
    df_prog = pd.DataFrame(st.session_state.programma).sort_values("Inizio_Sort")
    df_view = df_prog.drop(columns=['Inizio_Sort'])
    
    st.data_editor(df_view, use_container_width=True, hide_index=True, 
                   column_config={"Note": st.column_config.TextColumn(width="large"), 
                                  "Cibo": st.column_config.TextColumn(width="large")})
    
    # Download Excel Formattato
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
        df_view.to_excel(writer, index=False, sheet_name='Turno')
        workbook, worksheet = writer.book, writer.sheets['Turno']
        fmt = workbook.add_format({'text_wrap': True, 'valign': 'top', 'border': 1, 'font_size': 9})
        for i, col in enumerate(df_view.columns):
            worksheet.set_column(i, i, 22 if len(col)>5 else 12, fmt)
    
    st.download_button("📊 Scarica Excel Leggibile", output.getvalue(), f"turno_{data_t}.xlsx")
    if st.button("🗑️ Reset"): st.session_state.programma = []; st.rerun()

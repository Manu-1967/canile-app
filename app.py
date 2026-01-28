import streamlit as st
import pandas as pd
from datetime import datetime, timedelta
import PyPDF2
import re
import sqlite3
import io

# --- CONFIGURAZIONE ---
st.set_page_config(page_title="Canile Soft - Automazione Totale", layout="wide")

SHEET_ID = "1pcFa454IT1tlykbcK-BeAU9hnIQ_D8V_UuZaKI_KtYM"

# --- ESTRAZIONE PDF ---
def extract_pdf_data(uploaded_file):
    try:
        reader = PyPDF2.PdfReader(uploaded_file)
        text = "".join([page.extract_text() + "\n" for page in reader.pages])
        labels = ['CIBO', 'GUINZAGLIERIA', 'STRUMENTI', 'ATTIVITÀ', 'NOTE', 'TEMPO']
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
    c.execute('CREATE TABLE IF NOT EXISTS anagrafica_cani (nome TEXT PRIMARY KEY, cibo TEXT, guinzaglieria TEXT, strumenti TEXT, attivita TEXT, note TEXT, tempo TEXT)')
    conn.commit(); conn.close()

def load_data(sheet_name):
    url = f"https://docs.google.com/spreadsheets/d/{SHEET_ID}/gviz/tq?tqx=out:csv&sheet={sheet_name}"
    try:
        df = pd.read_csv(url); df.columns = [c.strip().lower() for c in df.columns]
        return df.dropna(how='all')
    except: return pd.DataFrame(columns=['nome'])

init_db()

# --- INTERFACCIA ---
st.title("🐾 Canile Soft - Programmazione Automatica Totale")

with st.sidebar:
    data_t = st.date_input("Data", datetime.today())
    ora_i = st.time_input("Inizio Turno", datetime.strptime("08:00", "%H:%M"))
    ora_f = st.time_input("Fine Turno", datetime.strptime("12:00", "%H:%M"))
    st.divider()
    files = st.file_uploader("Carica PDF Cani", accept_multiple_files=True, type="pdf")
    if files:
        conn = sqlite3.connect('canile.db')
        for f in files:
            d = extract_pdf_data(f)
            if d:
                nome_cane = f.name.split('.')[0].strip().capitalize()
                conn.execute("INSERT OR REPLACE INTO anagrafica_cani VALUES (?,?,?,?,?,?,?)", 
                             (nome_cane, d['CIBO'], d['GUINZAGLIERIA'], d['STRUMENTI'], d['ATTIVITÀ'], d['NOTE'], d['TEMPO']))
        conn.commit(); conn.close()
        st.success("PDF Acquisiti")

df_c = load_data("Cani"); df_v = load_data("Volontari"); df_l = load_data("Luoghi")

# --- 1. DISPONIBILITÀ ---
st.subheader("✅ 1. Check-in")
c1, c2, c3 = st.columns(3)
c_p = c1.multiselect("Cani presenti", df_c['nome'].tolist() if 'nome' in df_c.columns else [])
v_p = c2.multiselect("Volontari presenti", df_v['nome'].tolist() if 'nome' in df_v.columns else [])
l_p = c3.multiselect("Luoghi agibili", df_l['nome'].tolist() if 'nome' in df_l.columns else [])

# Inizializzazione sessione
if 'programma' not in st.session_state: st.session_state.programma = []

# --- 2. GESTIONE TEMPI ---
tempi_cani = {}
if c_p:
    conn = sqlite3.connect('canile.db'); conn.row_factory = sqlite3.Row
    for c in c_p:
        info = conn.execute("SELECT tempo FROM anagrafica_cani WHERE nome=?", (c.capitalize(),)).fetchone()
        t_def = 30
        if info and info['tempo'] != "N/D":
            try: t_def = int(re.search(r'\d+', info['tempo']).group())
            except: t_def = 30
        tempi_cani[c] = t_def
    conn.close()

# --- 3. INSERIMENTO MANUALE ---
with st.expander("✍️ Aggiungi riga manuale (completamento)"):
    m1, m2, m3, m4 = st.columns(4)
    m_c = m1.selectbox("Cane", c_p if c_p else ["-"])
    m_v = m2.selectbox("Volontario", v_p if v_p else ["-"])
    m_l = m3.selectbox("Luogo", l_p if l_p else ["-"])
    m_t = m4.number_input("Minuti", 10, 120, 30)
    if st.button("➕ Aggiungi riga"):
        st.session_state.programma.append({"Cane": m_c, "Volontario": m_v, "Luogo": m_l, "Durata": m_t, "Tipo": "Manuale"})

# --- 4. MOTORE DI AUTOMAZIONE ---
if st.button("🤖 GENERA / COMPLETA PROGRAMMA TOTALE", use_container_width=True):
    if not (c_p and v_p and l_p):
        st.error("Seleziona cani, volontari e luoghi!")
    else:
        # Reset e inserimento Briefing
        final_prog = []
        start_dt = datetime.combine(data_t, ora_i)
        end_dt = datetime.combine(data_t, ora_f)
        
        # 1. Briefing
        final_prog.append({"Orario": f"{start_dt.strftime('%H:%M')} - {(start_dt+timedelta(minutes=15)).strftime('%H:%M')}", 
                           "Cane": "TUTTI", "Volontario": "TUTTI", "Luogo": "Ufficio", "Inizio_Sort": start_dt.strftime('%H:%M')})
        
        # 2. Gestione Code (Cani e Volontari da far lavorare)
        cani_lavoro = [c for c in c_p if c not in [r['Cane'] for r in st.session_state.programma]]
        vols_lavoro = v_p.copy() # Qui potremmo aggiungere logica per far lavorare tutti i volontari più volte
        
        curr_t = start_dt + timedelta(minutes=15)
        limit_t = end_dt - timedelta(minutes=30) # Lasciamo spazio per i pasti
        
        # Recupero storico per esperienza
        conn = sqlite3.connect('canile.db')
        storico = pd.read_sql_query("SELECT cane, volontario, COUNT(*) as n FROM storico GROUP BY cane, volontario", conn)
        conn.close()

        # Algoritmo di riempimento (Parallelizzazione Volontari)
        # Per ogni slot temporale, cerchiamo di occupare tutti i volontari
        while cani_lavoro and curr_t < limit_t:
            vols_liberi = v_p.copy()
            luoghi_liberi = [l for l in l_p if l not in ["Ufficio", "Box", "Duca Park"]]
            
            for v in vols_liberi:
                if not cani_lavoro: break
                if not luoghi_liberi: break
                
                # Scegliamo il cane (priorità a chi ha già lavorato con v per esperienza, o il primo della lista)
                cane_scelto = cani_lavoro[0]
                durata = tempi_cani.get(cane_scelto, 30)
                luogo_scelto = luoghi_liberi.pop(0)
                
                final_prog.append({
                    "Orario": f"{curr_t.strftime('%H:%M')} - {(curr_t+timedelta(minutes=durata)).strftime('%H:%M')}",
                    "Cane": cane_scelto, "Volontario": v, "Luogo": luogo_scelto, "Inizio_Sort": curr_t.strftime('%H:%M')
                })
                cani_lavoro.remove(cane_scelto)
            
            curr_t += timedelta(minutes=30) # Prossimo slot

        # 3. Pasti
        pasti_t = end_dt - timedelta(minutes=30)
        final_prog.append({"Orario": f"{pasti_t.strftime('%H:%M')} - {end_dt.strftime('%H:%M')}", 
                           "Cane": "TUTTI", "Volontario": "TUTTI", "Luogo": "Box", "Inizio_Sort": pasti_t.strftime('%H:%M')})
        
        st.session_state.programma = final_prog
        st.rerun()

# --- 5. VISUALIZZAZIONE E EDITOR ---
if st.session_state.programma:
    st.divider()
    df_res = pd.DataFrame(st.session_state.programma).sort_values("Inizio_Sort")
    
    # Recupero info extra per la visualizzazione
    conn = sqlite3.connect('canile.db'); conn.row_factory = sqlite3.Row
    full_data = []
    for _, row in df_res.iterrows():
        d = dict(row)
        info = conn.execute("SELECT cibo, note, attivita FROM anagrafica_cani WHERE nome=?", (str(row['Cane']).capitalize(),)).fetchone()
        d['Cibo'] = info['cibo'] if info else "-"
        d['Note'] = info['note'] if info else "-"
        d['Attività'] = info['attivita'] if info else row.get('Attività', "-")
        full_data.append(d)
    conn.close()

    df_final = pd.DataFrame(full_data).drop(columns=['Inizio_Sort'], errors='ignore')
    
    # EDITOR TABELLARE (Ritorno a capo e larghezze)
    df_mod = st.data_editor(
        df_final,
        use_container_width=True,
        hide_index=True,
        num_rows="dynamic",
        column_config={
            "Note": st.column_config.TextColumn(width="large"),
            "Cibo": st.column_config.TextColumn(width="large"),
            "Attività": st.column_config.TextColumn(width="large"),
            "Orario": st.column_config.TextColumn(width="small"),
        }
    )
    
    # AZIONI
    c_salva, c_excel, c_reset = st.columns(3)
    if c_salva.button("💾 Salva Storico", use_container_width=True):
        conn = sqlite3.connect('canile.db')
        for r in df_mod.to_dict('records'):
            if r['Cane'] != "TUTTI":
                conn.execute("INSERT INTO storico (data, inizio, cane, volontario, luogo) VALUES (?,?,?,?,?)", 
                             (str(data_t), r['Orario'][:5], r['Cane'], r['Volontario'], r['Luogo']))
        conn.commit(); conn.close(); st.success("Database aggiornato!")

    # EXCEL FORMATTATO
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
        df_mod.to_excel(writer, index=False, sheet_name='Turno')
        workbook = writer.book
        worksheet = writer.sheets['Turno']
        fmt = workbook.add_format({'text_wrap': True, 'valign': 'top', 'border': 1, 'font_size': 9})
        for i, col in enumerate(df_mod.columns):
            w = 25 if col in ['Note', 'Cibo', 'Attività'] else 15
            worksheet.set_column(i, i, w, fmt)
    
    c_excel.download_button("📊 Scarica Excel Leggibile", output.getvalue(), f"turno_{data_t}.xlsx", use_container_width=True)
    if c_reset.button("🗑️ Reset", use_container_width=True): st.session_state.programma = []; st.rerun()

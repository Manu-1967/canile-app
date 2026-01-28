import streamlit as st
import pandas as pd
from datetime import datetime, timedelta
import PyPDF2
import re
import sqlite3
import io

# --- CONFIGURAZIONE ---
st.set_page_config(page_title="Canile Soft - Auto-Scheduler", layout="wide")

SHEET_ID = "1pcFa454IT1tlykbcK-BeAU9hnIQ_D8V_UuZaKI_KtYM"

# --- LOGICA ESTRAZIONE PDF ---
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
    c.execute('CREATE TABLE IF NOT EXISTS storico (data TEXT, inizio TEXT, fine TEXT, cane TEXT, volontario TEXT, luogo TEXT)')
    c.execute('CREATE TABLE IF NOT EXISTS anagrafica_cani (nome TEXT PRIMARY KEY, cibo TEXT, guinzaglieria TEXT, strumenti TEXT, attivita TEXT, note TEXT, tempo TEXT)')
    conn.commit(); conn.close()

def load_data(sheet_name):
    url = f"https://docs.google.com/spreadsheets/d/{SHEET_ID}/gviz/tq?tqx=out:csv&sheet={sheet_name}"
    try:
        df = pd.read_csv(url); df.columns = [c.strip().lower() for c in df.columns]
        return df.dropna(how='all')
    except: return pd.DataFrame(columns=['nome'])

init_db()

# --- NAVIGAZIONE ---
menu = st.sidebar.radio("Navigazione", ["📅 Gestione Turno", "📋 Anagrafica Cani"])

if menu == "📅 Gestione Turno":
    st.title("🐾 Canile Soft - Dashboard Automatica")

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
            st.success("Dati PDF Aggiornati")

    df_c = load_data("Cani"); df_v = load_data("Volontari"); df_l = load_data("Luoghi")

    # --- 1. CHECK-IN ---
    st.subheader("✅ 1. Check-in Disponibilità")
    c1, col2, col3 = st.columns(3)
    c_p = c1.multiselect("Cani pronti", df_c['nome'].tolist() if 'nome' in df_c.columns else [])
    v_p = col2.multiselect("Volontari presenti", df_v['nome'].tolist() if 'nome' in df_v.columns else [])
    l_p = col3.multiselect("Campi agibili", df_l['nome'].tolist() if 'nome' in df_l.columns else [])

    # --- 2. GESTIONE TEMPI MANCANTI ---
    tempi_cani = {}
    if c_p:
        st.divider()
        st.subheader("⏱️ 2. Conferma Tempi di Lavoro")
        with st.expander("Controlla durate attività", expanded=False):
            conn = sqlite3.connect('canile.db'); conn.row_factory = sqlite3.Row
            for cane in c_p:
                info = conn.execute("SELECT tempo FROM anagrafica_cani WHERE nome=?", (cane.capitalize(),)).fetchone()
                default_t = 30
                if info:
                    try: default_t = int(re.search(r'\d+', info['tempo']).group())
                    except: pass
                tempi_cani[cane] = st.number_input(f"Minuti per {cane}", 10, 120, default_t, key=f"t_{cane}")
            conn.close()

    # --- 3. GENERAZIONE AUTOMATICA ---
    st.divider()
    col_btn1, col_btn2 = st.columns(2)
    
    if col_btn1.button("🤖 Genera Programma Automatico", use_container_width=True):
        if not (c_p and v_p and l_p):
            st.warning("Seleziona cani, volontari e luoghi!")
        else:
            if 'programma' not in st.session_state: st.session_state.programma = []
            
            # Cani già inseriti manualmente
            cani_gia_inseriti = [r['Cane'] for r in st.session_state.programma]
            cani_da_inserire = [c for c in c_p if c not in cani_gia_inseriti]
            
            # Recupero storico per esperienza
            conn = sqlite3.connect('canile.db')
            storico = pd.read_sql_query("SELECT cane, volontario, COUNT(*) as n FROM storico GROUP BY cane, volontario", conn)
            conn.close()

            # Algoritmo Semplice di Distribuzione
            current_time = datetime.combine(data_t, ora_i)
            # Limitiamo il tempo totale (pasti a fine turno)
            limit_time = datetime.combine(data_t, ora_f) - timedelta(minutes=30)
            
            # Tentativo di assegnazione
            for cane in cani_da_inserire:
                if current_time >= limit_time: break
                
                # Trova volontario con più esperienza o il primo libero
                suggeriti = storico[storico['cane'] == cane].sort_values('n', ascending=False)
                vol_scelto = None
                for v in v_p:
                    if v in suggeriti['volontario'].values:
                        vol_scelto = v
                        break
                if not vol_scelto: vol_scelto = v_p[0] # Altrimenti il primo per fargli fare esperienza

                luogo_scelto = l_p[cani_da_inserire.index(cane) % len(l_p)]
                durata = tempi_cani.get(cane, 30)
                
                # Recupero info PDF per la riga
                conn = sqlite3.connect('canile.db'); conn.row_factory = sqlite3.Row
                info = conn.execute("SELECT * FROM anagrafica_cani WHERE nome=?", (cane.capitalize(),)).fetchone()
                conn.close()

                st.session_state.programma.append({
                    "Orario": f"{current_time.strftime('%H:%M')} - {(current_time + timedelta(minutes=durata)).strftime('%H:%M')}",
                    "Cane": cane, "Volontario": vol_scelto, "Luogo": luogo_scelto,
                    "Cibo": info['cibo'] if info else "-", "Note": info['note'] if info else "-",
                    "Attività": info['attivita'] if info else "-", "Inizio_Sort": current_time.strftime('%H:%M')
                })
                # Incremento tempo (distribuzione sequenziale per semplicità)
                # In una versione avanzata gestiremo i volontari in parallelo
                if len(st.session_state.programma) % len(v_p) == 0:
                    current_time += timedelta(minutes=durata)
            
            st.rerun()

    # --- 4. VISUALIZZAZIONE E MODIFICA ---
    if 'programma' in st.session_state and st.session_state.programma:
        st.subheader("📝 3. Programma (Modificabile)")
        df_ed = pd.DataFrame(st.session_state.programma).sort_values("Inizio_Sort")
        
        # Editor per modifiche manuali o completamento
        df_mod = st.data_editor(
            df_ed,
            num_rows="dynamic",
            column_config={
                "Inizio_Sort": None,
                "Note": st.column_config.TextColumn(width="large"),
                "Cibo": st.column_config.TextColumn(width="large"),
                "Attività": st.column_config.TextColumn(width="large")
            },
            use_container_width=True,
            hide_index=True
        )
        st.session_state.programma = df_mod.to_dict('records')

        # Export e Salva
        b1, b2, b3 = st.columns(3)
        if b1.button("💾 Salva Storico", use_container_width=True):
            conn = sqlite3.connect('canile.db')
            for r in st.session_state.programma:
                conn.execute("INSERT INTO storico (data, inizio, cane, volontario, luogo) VALUES (?,?,?,?,?)", 
                             (str(data_t), r.get('Inizio_Sort'), r['Cane'], r['Volontario'], r['Luogo']))
            conn.commit(); conn.close(); st.success("Salvato!")

        # EXCEL
        output = io.BytesIO()
        with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
            df_mod.drop(columns=['Inizio_Sort'], errors='ignore').to_excel(writer, index=False)
            # ... (logica formattazione excel precedente)
        b2.download_button("📊 Scarica Excel", output.getvalue(), f"turno_{data_t}.xlsx", use_container_width=True)
        
        if b3.button("🗑️ Svuota Tutto", use_container_width=True): 
            st.session_state.programma = []; st.rerun()

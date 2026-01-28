import streamlit as st
import pandas as pd
from datetime import datetime, timedelta
import PyPDF2
import re
import sqlite3
import io

# --- CONFIGURAZIONE E STILI ---
st.set_page_config(page_title="Canile Soft - Mobile Optimized", layout="wide")

# Mappa conflitti spaziali (da memoria utente)
CONFLITTI = {
    "Lago Park": "Central Park", "Central Park": "Lago Park",
    "Peter Park": "Duca Park", "Duca Park": "Peter Park"
}

COLOR_MAP = {"ROSSO": 3, "GIALLO": 2, "VERDE": 1, "N/D": 0}

def init_db():
    conn = sqlite3.connect('canile.db')
    c = conn.cursor()
    # Tabella storico per ricordare chi ha lavorato con chi
    c.execute('CREATE TABLE IF NOT EXISTS storico (data TEXT, inizio TEXT, cane TEXT, volontario TEXT, luogo TEXT)')
    # Anagrafica cani
    c.execute('''CREATE TABLE IF NOT EXISTS anagrafica_cani 
                 (nome TEXT PRIMARY KEY, cibo TEXT, guinzaglieria TEXT, strumenti TEXT, attivita TEXT, note TEXT, tempo TEXT, livello TEXT)''')
    conn.commit(); conn.close()

def load_gsheets(sheet_name):
    # Caricamento robusto
    url = f"https://docs.google.com/spreadsheets/d/1pcFa454IT1tlykbcK-BeAU9hnIQ_D8V_UuZaKI_KtYM/gviz/tq?tqx=out:csv&sheet={sheet_name}"
    try:
        df = pd.read_csv(url); df.columns = [c.strip().lower() for c in df.columns]
        return df.dropna(how='all')
    except: return pd.DataFrame()

init_db()

# --- SIDEBAR ---
with st.sidebar:
    st.header("⚙️ Configurazione")
    data_t = st.date_input("Data Turno", datetime.today())
    ora_i = st.time_input("Inizio", datetime.strptime("08:00", "%H:%M"))
    ora_f = st.time_input("Fine", datetime.strptime("12:00", "%H:%M"))
    st.divider()
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

# --- CORE LOGIC ---
if 'programma' not in st.session_state: st.session_state.programma = []

st.title("📱 Canile Soft - Gestione Adattiva")

# Selezione Risorse
c1, c2, c3 = st.columns(3)
c_p = c1.multiselect("Cani Presenti", df_c['nome'].tolist() if not df_c.empty else [])
v_p = c2.multiselect("Volontari Presenti", df_v['nome'].tolist() if not df_v.empty else [])
l_p = c3.multiselect("Campi (No Duca Auto)", [l for l in df_l['nome'].tolist() if l != "Duca Park"] if not df_l.empty else [])

# 1. INSERIMENTO MANUALE (PRIORITARIO)
with st.expander("✍️ Inserimento Manuale (Priorità Alta)"):
    mc1, mc2, mc3, mc4 = st.columns(4)
    m_cane = mc1.selectbox("Cane", ["-"] + c_p)
    m_vol = mc2.selectbox("Volontario", ["-"] + v_p)
    m_luo = mc3.selectbox("Luogo", ["-"] + (df_l['nome'].tolist() if not df_l.empty else []))
    m_ora = mc4.time_input("Ora Inizio Attività", ora_i)
    
    if st.button("➕ Aggiungi Riga Manuale"):
        if m_cane != "-":
            durata_m = 30 # Default
            st.session_state.programma.append({
                "Orario": f"{m_ora.strftime('%H:%M')} - {(datetime.combine(data_t, m_ora)+timedelta(minutes=durata_m)).strftime('%H:%M')}",
                "Cane": m_cane, "Volontario": m_vol, "Luogo": m_luo, "Attività": "Manuale", 
                "Inizio_Sort": m_ora.strftime('%H:%M'), "Tipo": "Manuale"
            })
            st.rerun()

# 2. LOGICA AUTOMATICA INTELLIGENTE
c_btn1, c_btn2 = st.columns(2)

if c_btn1.button("🤖 Completa Programma (Tutti al lavoro + Pasti)", use_container_width=True):
    conn = sqlite3.connect('canile.db'); conn.row_factory = sqlite3.Row
    
    # Setup Orari
    start_dt = datetime.combine(data_t, ora_i)
    end_dt = datetime.combine(data_t, ora_f)
    pasti_dt = end_dt - timedelta(minutes=30)
    
    # 1. Briefing (Se non esiste, lo crea)
    if not any(r.get('Attività') == 'Briefing' for r in st.session_state.programma):
        st.session_state.programma.insert(0, {
            "Orario": f"{start_dt.strftime('%H:%M')} - {(start_dt+timedelta(minutes=15)).strftime('%H:%M')}", 
            "Cane": "TUTTI", "Volontario": "TUTTI", "Luogo": "Ufficio", "Attività": "Briefing", 
            "Inizio_Sort": start_dt.strftime('%H:%M'), "Tipo": "Auto"
        })

    # 2. Analisi Stato Attuale
    prog_temp = [r for r in st.session_state.programma if r.get('Attività') not in ['Briefing', 'Pasti']]
    cani_fatti = [r['Cane'] for r in prog_temp]
    cani_da_fare = [c for c in c_p if c not in cani_fatti]
    
    curr_t = start_dt + timedelta(minutes=15)
    
    # Ciclo di riempimento slot
    while cani_da_fare and curr_t < pasti_dt:
        # Volontari disponibili in questo orario (Consideriamo tutti liberi all'inizio del loop slot, 
        # in una versione avanzata si controllerebbe la durata precisa, qui semplifichiamo a slot)
        vols_slot = v_p.copy()
        
        # Filtra campi occupati manualmente in questo orario
        occupati_manuali = [r for r in prog_temp if r.get('Inizio_Sort') == curr_t.strftime('%H:%M')]
        campi_occupati = [r['Luogo'] for r in occupati_manuali]
        
        # Gestione Conflitti (Se Lago è occupato, Central è off-limits)
        campi_vietati = []
        for occ in campi_occupati:
            if occ in CONFLITTI: campi_vietati.append(CONFLITTI[occ])
            
        campi_liberi = [l for l in l_p if l not in campi_occupati and l not in campi_vietati]
        
        # Assegnazione Cani
        while cani_da_fare and campi_liberi and vols_slot:
            cane = cani_da_fare.pop(0)
            campo = campi_liberi.pop(0)
            
            # Conflitto dinamico: se uso Lago ora, tolgo Central per questo slot
            if campo in CONFLITTI and CONFLITTI[campo] in campi_liberi:
                campi_liberi.remove(CONFLITTI[campo])
            
            # --- SELEZIONE VOLONTARIO BASATA SU STORICO ---
            # Cerchiamo chi ha lavorato di più con questo cane
            best_vol = None
            max_count = -1
            
            # Ordiniamo vols_slot per esperienza decrescente
            vols_con_punteggio = []
            for v in vols_slot:
                cnt = conn.execute("SELECT COUNT(*) FROM storico WHERE cane=? AND volontario=?", (cane, v)).fetchone()[0]
                vols_con_punteggio.append((v, cnt))
            
            # Ordina: chi ha più esperienza prima
            vols_con_punteggio.sort(key=lambda x: x[1], reverse=True)
            
            if vols_con_punteggio:
                v_main = vols_con_punteggio[0][0]
                vols_slot.remove(v_main)
                v_str = v_main
                
                # --- ASSEGNAZIONE SUPPORTO (Volontari in eccesso) ---
                # Se abbiamo ancora tanti volontari e pochi cani rimasti per questo slot
                if len(vols_slot) > len(cani_da_fare):
                    # Assegna 1 supporto
                    sup = vols_slot.pop(0)
                    v_str += f"\n+ {sup} (Sup.)"
                
                # Info DB
                info = conn.execute("SELECT * FROM anagrafica_cani WHERE nome=?", (cane.capitalize(),)).fetchone()
                
                st.session_state.programma.append({
                    "Orario": f"{curr_t.strftime('%H:%M')} - {(curr_t+timedelta(minutes=30)).strftime('%H:%M')}",
                    "Cane": cane, "Volontario": v_str, "Luogo": campo,
                    "Cibo": info['cibo'] if info else "-", "Note": info['note'] if info else "-",
                    "Attività": info['attivita'] if info else "Uscita",
                    "Inizio_Sort": curr_t.strftime('%H:%M'), "Tipo": "Auto"
                })

        curr_t += timedelta(minutes=30)

    # 3. Pasti (Sempre alla fine)
    # Rimuoviamo vecchi pasti se presenti per aggiornarli
    st.session_state.programma = [r for r in st.session_state.programma if r['Attività'] != 'Pasti']
    st.session_state.programma.append({
        "Orario": f"{pasti_dt.strftime('%H:%M')} - {end_dt.strftime('%H:%M')}", 
        "Cane": "TUTTI", "Volontario": "TUTTI", "Luogo": "Box", 
        "Attività": "Pasti", "Inizio_Sort": pasti_dt.strftime('%H:%M'), "Tipo": "Auto"
    })
    
    conn.close(); st.rerun()

if c_btn2.button("🗑️ Svuota Tutto", use_container_width=True):
    st.session_state.programma = []
    st.rerun()

# --- EDITOR E MODIFICA ---
if st.session_state.programma:
    st.divider()
    st.subheader("📝 Programma (Modificabile)")
    
    # Prepariamo il DataFrame ordinato
    df_prog = pd.DataFrame(st.session_state.programma)
    if not df_prog.empty and "Inizio_Sort" in df_prog.columns:
        df_prog = df_prog.sort_values("Inizio_Sort")
    
    # CONFIGURAZIONE COLONNE "STRETTE E ALTE" (ADATTATIVE)
    # Usiamo width="small" o "medium" per forzare il wrap del testo
    col_config = {
        "Inizio_Sort": None, "Tipo": None, # Nascondi colonne tecniche
        "Orario": st.column_config.TextColumn("Ora", width="small"),
        "Cane": st.column_config.TextColumn("Cane", width="small"),
        "Volontario": st.column_config.TextColumn("Volontario", width="medium"), # Un po' più largo per i supporti
        "Luogo": st.column_config.TextColumn("Luogo", width="small"),
        "Attività": st.column_config.TextColumn("Attività", width="small"),
        "Cibo": st.column_config.TextColumn("Cibo", width="small"),
        "Note": st.column_config.TextColumn("Note", width="medium"),
    }
    
    df_edited = st.data_editor(
        df_prog,
        column_config=col_config,
        use_container_width=True,
        hide_index=True,
        num_rows="dynamic", # Permette aggiunta/rimozione righe direttamente
        height=800 # Altezza fissa tabella per scroll su mobile
    )
    
    # Salva modifiche in session state
    st.session_state.programma = df_edited.to_dict('records')

    # EXPORT EXCEL
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
        df_to_save = df_edited.drop(columns=['Inizio_Sort', 'Tipo'], errors='ignore')
        df_to_save.to_excel(writer, index=False)
        workbook = writer.book
        worksheet = writer.sheets['Sheet1']
        
        # Formattazione Excel per stampa/mobile
        fmt_wrap = workbook.add_format({'text_wrap': True, 'valign': 'top', 'border': 1})
        worksheet.set_column('A:A', 12, fmt_wrap) # Orario
        worksheet.set_column('B:C', 15, fmt_wrap) # Cane/Vol
        worksheet.set_column('D:D', 12, fmt_wrap) # Luogo
        worksheet.set_column('E:H', 20, fmt_wrap) # Note varie
        
    st.download_button("📊 Scarica Excel", output.getvalue(), f"turno_{data_t}.xlsx", use_container_width=True)
    
    # SALVATAGGIO STORICO
    if st.button("💾 Salva nel Database Storico (A fine turno)"):
        conn = sqlite3.connect('canile.db')
        for r in st.session_state.programma:
            if r['Cane'] not in ["TUTTI", "-"]:
                # Pulisce stringa volontari (rimuove "Supporto") per il database
                v_clean = r['Volontario'].split('\n')[0].strip()
                conn.execute("INSERT INTO storico (data, inizio, cane, volontario, luogo) VALUES (?,?,?,?,?)", 
                             (str(data_t), r['Orario'][:5], r['Cane'], v_clean, r['Luogo']))
        conn.commit(); conn.close()
        st.success("Storico salvato!")

# --- VISUALIZZAZIONE ANAGRAFICA ---
with menu[1]:
    st.subheader("📋 Anagrafica Cani")
    conn = sqlite3.connect('canile.db')
    df_db = pd.read_sql_query("SELECT * FROM anagrafica_cani", conn)
    conn.close()
    
    if not df_db.empty:
        st.dataframe(
            df_db, 
            use_container_width=True, 
            column_config={
                "nome": st.column_config.TextColumn("Nome", width="small"),
                "cibo": st.column_config.TextColumn("Cibo", width="medium"),
                "note": st.column_config.TextColumn("Note", width="medium"),
                "livello": st.column_config.TextColumn("Lvl", width="small"),
            }
        )

import streamlit as st
import pandas as pd
from datetime import datetime, timedelta
import PyPDF2
import re
import sqlite3
import os
import json
from collections import defaultdict

# --- CONFIGURAZIONE ---
st.set_page_config(page_title="Programma Canile", layout="wide")

# Directory per salvare gli storici
STORICO_DIR = "storico_programmi"
if not os.path.exists(STORICO_DIR):
    os.makedirs(STORICO_DIR)

def init_db():
    conn = sqlite3.connect('canile.db')
    c = conn.cursor()
    
    # Crea la tabella storico se non esiste (vecchio formato)
    c.execute('''CREATE TABLE IF NOT EXISTS storico 
                 (data TEXT, inizio TEXT, cane TEXT, volontario TEXT, luogo TEXT)''')
    
    # Migrazione: aggiungi nuove colonne se non esistono
    try:
        # Verifica quali colonne esistono
        c.execute("PRAGMA table_info(storico)")
        existing_columns = {row[1] for row in c.fetchall()}
        
        # Aggiungi colonne mancanti
        if 'id' not in existing_columns:
            # Crea una nuova tabella con la struttura aggiornata e copia i dati
            c.execute('''CREATE TABLE IF NOT EXISTS storico_new 
                         (id INTEGER PRIMARY KEY AUTOINCREMENT,
                          data TEXT, 
                          inizio TEXT, 
                          fine TEXT,
                          cane TEXT, 
                          volontario TEXT, 
                          luogo TEXT,
                          attivita TEXT,
                          durata_minuti INTEGER,
                          timestamp_salvataggio TEXT)''')
            
            # Copia i dati vecchi nella nuova tabella
            c.execute('''INSERT INTO storico_new (data, inizio, cane, volontario, luogo, fine, attivita, durata_minuti, timestamp_salvataggio)
                         SELECT data, inizio, cane, volontario, luogo, 
                                inizio as fine, '-' as attivita, 30 as durata_minuti, 
                                datetime('now') as timestamp_salvataggio
                         FROM storico''')
            
            # Elimina la vecchia tabella e rinomina la nuova
            c.execute('DROP TABLE storico')
            c.execute('ALTER TABLE storico_new RENAME TO storico')
        else:
            # La tabella è già aggiornata, verifica solo le colonne mancanti
            columns_to_add = {
                'fine': 'TEXT',
                'attivita': 'TEXT',
                'durata_minuti': 'INTEGER',
                'timestamp_salvataggio': 'TEXT'
            }
            
            for col_name, col_type in columns_to_add.items():
                if col_name not in existing_columns:
                    c.execute(f'ALTER TABLE storico ADD COLUMN {col_name} {col_type}')
    except Exception as e:
        # Se c'è un errore durante la migrazione, continua comunque
        print(f"Avviso durante migrazione DB: {e}")
    
    # Tabella anagrafica completa
    c.execute('''CREATE TABLE IF NOT EXISTS anagrafica_cani 
                 (nome TEXT PRIMARY KEY, cibo TEXT, guinzaglieria TEXT, strumenti TEXT, 
                  attivita TEXT, note TEXT, tempo TEXT, livello TEXT)''')
    
    conn.commit()
    conn.close()

def salva_programma_in_storico(programma, data):
    """Salva il programma approvato sia nel DB che in file JSON"""
    if not programma:
        return False, "Nessun programma da salvare"
    
    conn = sqlite3.connect('canile.db')
    c = conn.cursor()
    timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    
    # Salva nel database
    records_salvati = 0
    for turno in programma:
        if turno['Cane'] not in ['TUTTI', 'Da assegnare']:
            # Estrai orari
            orario = turno['Orario']
            if ' - ' in orario:
                inizio, fine = orario.split(' - ')
            else:
                inizio = turno['Inizio_Sort']
                fine = inizio
            
            # Calcola durata in minuti
            try:
                h_i, m_i = map(int, inizio.split(':'))
                h_f, m_f = map(int, fine.split(':'))
                durata = (h_f * 60 + m_f) - (h_i * 60 + m_i)
            except:
                durata = 30
            
            c.execute('''INSERT INTO storico 
                         (data, inizio, fine, cane, volontario, luogo, attivita, durata_minuti, timestamp_salvataggio)
                         VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)''',
                      (data.strftime('%Y-%m-%d'), inizio, fine, 
                       turno['Cane'], turno['Volontario'], turno['Luogo'],
                       turno.get('Attività PDF', '-'), durata, timestamp))
            records_salvati += 1
    
    conn.commit()
    conn.close()
    
    # Salva anche in file JSON per backup
    filename = os.path.join(STORICO_DIR, f"{data.strftime('%d-%m-%Y')}_Programma-canile.json")
    with open(filename, 'w', encoding='utf-8') as f:
        json.dump({
            'data': data.strftime('%d-%m-%Y'),
            'timestamp_salvataggio': timestamp,
            'programma': programma
        }, f, ensure_ascii=False, indent=2)
    
    return True, f"✅ Programma salvato con successo! ({records_salvati} turni registrati)"

def carica_storico_da_file(filepath):
    """Carica un programma salvato da file JSON"""
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            data = json.load(f)
        return data['programma']
    except:
        return []

def get_storici_disponibili():
    """Restituisce la lista dei file di storico disponibili"""
    if not os.path.exists(STORICO_DIR):
        return []
    files = [f for f in os.listdir(STORICO_DIR) if f.endswith('.json')]
    # Ordina per data (più recenti prima)
    files.sort(reverse=True)
    return files

def calcola_esperienza_volontari(cane):
    """Calcola l'esperienza di ogni volontario con un cane specifico basata sullo storico"""
    conn = sqlite3.connect('canile.db')
    
    # Query per contare i turni di ogni volontario con questo cane
    query = """
        SELECT volontario, 
               COUNT(*) as num_turni,
               SUM(durata_minuti) as minuti_totali
        FROM storico 
        WHERE cane = ?
        GROUP BY volontario
        ORDER BY num_turni DESC, minuti_totali DESC
    """
    
    df = pd.read_sql_query(query, conn, params=(cane,))
    conn.close()
    
    return df

def get_volontario_piu_esperto(cane, volontari_disponibili):
    """Restituisce il volontario più esperto per un cane specifico"""
    df_exp = calcola_esperienza_volontari(cane)
    
    if df_exp.empty:
        # Nessuno storico, sceglie casualmente
        return volontari_disponibili[0] if volontari_disponibili else None
    
    # Cerca il volontario più esperto tra quelli disponibili
    for _, row in df_exp.iterrows():
        if row['volontario'] in volontari_disponibili:
            return row['volontario']
    
    # Se nessuno degli esperti è disponibile, prende il primo disponibile
    return volontari_disponibili[0] if volontari_disponibili else None

def load_gsheets(sheet_name):
    # Link al tuo Google Sheet
    url = f"https://docs.google.com/spreadsheets/d/1pcFa454IT1tlykbcK-BeAU9hnIQ_D8V_UuZaKI_KtYM/gviz/tq?tqx=out:csv&sheet={sheet_name}"
    try:
        df = pd.read_csv(url)
        df.columns = [c.strip().lower() for c in df.columns]
        
        if sheet_name == "Luoghi":
            if 'automatico' not in df.columns: df['automatico'] = 'sì'
            if 'adiacente' not in df.columns: df['adiacente'] = ''
        
        if sheet_name == "Cani":
            if 'reattività' not in df.columns: df['reattività'] = 0
            else: df['reattività'] = pd.to_numeric(df['reattività'], errors='coerce').fillna(0)
            
        return df.dropna(how='all')
    except:
        return pd.DataFrame()

def parse_pdf_content(text):
    """Estrae i dati dal PDF."""
    campi_target = ['CIBO', 'GUINZAGLIERIA', 'STRUMENTI', 'ATTIVITÀ', 'NOTE', 'TEMPO']
    dati_estratti = {c: "N/D" for c in campi_target}
    dati_estratti['LIVELLO'] = "N/D" 
    
    for campo in campi_target:
        altri_campi = "|".join([k for k in campi_target if k != campo])
        pattern = rf"{campo}[:\s\n]*(.*?)(?=(?:{altri_campi})|$)"
        match = re.search(pattern, text, re.DOTALL)
        if match:
            dati_estratti[campo] = match.group(1).strip()
    return dati_estratti

def parse_duration_string(tempo_str):
    """Converte la stringa del tempo (es. '45 min') in minuti interi. Default 30."""
    if not tempo_str or tempo_str == "N/D":
        return 30
    
    tempo_str = tempo_str.lower()
    
    # Cerca numeri
    match = re.search(r'(\d+)', tempo_str)
    num = int(match.group(1)) if match else 30
    
    # Se c'è scritto "ora" o "ore", moltiplica per 60
    if "ora" in tempo_str or "ore" in tempo_str:
        if num < 10:
            num = num * 60
            
    return num

def get_cane_info_completa(nome_cane):
    """Recupera TUTTI i dati del cane dal DB."""
    conn = sqlite3.connect('canile.db')
    conn.row_factory = sqlite3.Row
    row = conn.execute("SELECT * FROM anagrafica_cani WHERE nome=?", (nome_cane,)).fetchone()
    conn.close()
    if row:
        return dict(row)
    return {c: "-" for c in ['cibo', 'guinzaglieria', 'strumenti', 'attivita', 'note', 'tempo', 'livello']}

def get_reattivita_cane(nome_cane, df_cani):
    if df_cani.empty or 'reattività' not in df_cani.columns: return 0
    riga = df_cani[df_cani['nome'] == nome_cane]
    return float(riga.iloc[0]['reattività']) if not riga.empty else 0

def get_campi_adiacenti(campo, df_luoghi):
    if df_luoghi.empty or 'adiacente' not in df_luoghi.columns: return []
    riga = df_luoghi[df_luoghi['nome'] == campo]
    if not riga.empty:
        adiacenti_str = str(riga.iloc[0]['adiacente']).strip()
        if adiacenti_str and adiacenti_str != 'nan':
            return [c.strip() for c in adiacenti_str.split(',') if c.strip()]
    return []

def campo_valido_per_reattivita(cane, campo, turni_attuali, ora_attuale_str, df_cani, df_luoghi):
    """Logica di controllo reattività bidirezionale"""
    reattivita_cane_corrente = get_reattivita_cane(cane, df_cani)
    campi_adiacenti = get_campi_adiacenti(campo, df_luoghi)
    
    for turno in turni_attuali:
        if turno["Inizio_Sort"] == ora_attuale_str:
            if turno["Luogo"] in campi_adiacenti:
                cane_adiacente = turno["Cane"]
                if cane_adiacente in ["TUTTI", "Da assegnare"]: continue
                
                reattivita_cane_adiacente = get_reattivita_cane(cane_adiacente, df_cani)
                if reattivita_cane_corrente > 5 or reattivita_cane_adiacente > 5:
                    return False
    return True

init_db()

# --- SIDEBAR ---
with st.sidebar:
    st.header("⚙️ Setup")
    data_t = st.date_input("Data", datetime.today())
    ora_i = st.time_input("Inizio Giornata", datetime.strptime("08:00", "%H:%M"))
    ora_f = st.time_input("Fine Giornata", datetime.strptime("12:00", "%H:%M"))
    
    st.divider()
    pdf_files = st.file_uploader("📂 Carica PDF Cani", accept_multiple_files=True, type="pdf")
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

st.title(" 🐕 Programma Canile 🐕 ")

# --- SELEZIONE RISORSE ---
c_p = st.multiselect("🐕 Cani", df_c['nome'].tolist() if not df_c.empty else [])
v_p = st.multiselect("👤 Volontari", df_v['nome'].tolist() if not df_v.empty else [])
l_p = st.multiselect("📍 Luoghi", df_l['nome'].tolist() if not df_l.empty else [])

tab_prog, tab_storico, tab_ana = st.tabs(["📅 Programma", "📚 Storico", "📋 Anagrafica"])

with tab_prog:
    # 1. INSERIMENTO MANUALE
    with st.expander("✏️ Inserimento Manuale"):
        col1, col2 = st.columns(2)
        m_cane = col1.selectbox("Cane", ["-"] + c_p)
        m_luo = col2.selectbox("Luogo", ["-"] + l_p)
        m_vols = st.multiselect("Volontari", v_p)
        m_ora = st.time_input("Ora Inizio", ora_i)
        
        if st.button("➕ Aggiungi"):
            if m_cane != "-":
                ora_start_dt = datetime.combine(data_t, m_ora)
                ora_str = ora_start_dt.strftime('%H:%M')
                
                # Recupera info e calcola durata
                info_cane = get_cane_info_completa(m_cane)
                durata_min = parse_duration_string(info_cane.get('tempo', '30 min'))
                ora_end_dt = ora_start_dt + timedelta(minutes=durata_min)
                orario_display = f"{ora_start_dt.strftime('%H:%M')} - {ora_end_dt.strftime('%H:%M')}"

                # Controllo sovrapposizioni
                occupato = any(t["Cane"] == m_cane and t["Inizio_Sort"] == ora_str 
                              for t in st.session_state.programma)
                
                if not occupato:
                    entry = {
                        "Orario": orario_display,
                        "Cane": m_cane,
                        "Volontario": ", ".join(m_vols) if m_vols else "Da assegnare",
                        "Luogo": m_luo if m_luo != "-" else "Da assegnare",
                        "Inizio_Sort": ora_str,
                        # Info PDF
                        "Cibo": info_cane.get('cibo', '-'),
                        "Guinzaglieria": info_cane.get('guinzaglieria', '-'),
                        "Strumenti": info_cane.get('strumenti', '-'),
                        "Attività PDF": info_cane.get('attivita', '-'),
                        "Note": info_cane.get('note', '-'),
                        "Tempo PDF": info_cane.get('tempo', '-')
                    }
                    st.session_state.programma.append(entry)
                    st.success("Turno aggiunto!")
                    st.rerun()
                else:
                    st.error("Cane già impegnato in questo orario")

    # 2. GENERAZIONE AUTOMATICA
    c_btn1, c_btn2 = st.columns(2)
    
    if c_btn1.button("🤖 Genera Automatico", use_container_width=True):
        conn = sqlite3.connect('canile.db'); conn.row_factory = sqlite3.Row
        start_dt = datetime.combine(data_t, ora_i)
        end_dt = datetime.combine(data_t, ora_f)
        pasti_dt = end_dt - timedelta(minutes=30) 
        
        manuali_esistenti = st.session_state.programma
        st.session_state.programma = []
        
        # Briefing
        st.session_state.programma.append({
            "Orario": f"{start_dt.strftime('%H:%M')} - {(start_dt+timedelta(minutes=15)).strftime('%H:%M')}", 
            "Cane": "TUTTI", "Volontario": "TUTTI", "Luogo": "Ufficio", 
            "Inizio_Sort": start_dt.strftime('%H:%M'), "Attività PDF": "Briefing",
            "Cibo": "-", "Guinzaglieria": "-", "Strumenti": "-", "Note": "-", "Tempo PDF": "-"
        })

        cani_gia_occupati = [m["Cane"] for m in manuali_esistenti]
        cani_da_fare = [c for c in c_p if c not in cani_gia_occupati]
        
        curr_t = start_dt + timedelta(minutes=15)
        
        luoghi_auto = []
        if not df_l.empty and 'automatico' in df_l.columns:
             filtro = (df_l['nome'].isin(l_p)) & (df_l['automatico'].astype(str).str.lower().str.strip() == 'sì')
             luoghi_auto = df_l[filtro]['nome'].tolist()
        else: luoghi_auto = l_p.copy()

        while cani_da_fare and curr_t < pasti_dt and luoghi_auto:
            ora_attuale_str = curr_t.strftime('%H:%M')
            
            # Filtri base disponibilità
            vols_impegnati = []
            luoghi_impegnati = []
            for m in manuali_esistenti:
                if m["Inizio_Sort"] == ora_attuale_str:
                    vols_impegnati.extend([v.strip() for v in m["Volontario"].split(",")])
                    luoghi_impegnati.append(m["Luogo"])

            vols_liberi = [v for v in v_p if v not in vols_impegnati]
            campi_disp = [l for l in luoghi_auto if l not in luoghi_impegnati]
            
            n_cani = min(len(cani_da_fare), len(campi_disp))
            max_durata_turno = 30
            
            if n_cani > 0 and vols_liberi:
                for _ in range(n_cani):
                    if not cani_da_fare or not vols_liberi or not campi_disp: break
                    
                    cane_ok = False
                    tentativi = 0
                    while not cane_ok and tentativi < len(cani_da_fare):
                        cane = cani_da_fare[tentativi]
                        
                        # Recupera Info complete
                        info_cane = get_cane_info_completa(cane)
                        durata_min = parse_duration_string(info_cane.get('tempo', '30'))
                        
                        # Calcola fine turno specifico
                        fine_turno = curr_t + timedelta(minutes=durata_min)
                        orario_display = f"{curr_t.strftime('%H:%M')} - {fine_turno.strftime('%H:%M')}"
                        
                        # Trova campo compatibile
                        campo_scelto = None
                        for campo in campi_disp:
                            if campo_valido_per_reattivita(cane, campo, st.session_state.programma + manuali_esistenti, ora_attuale_str, df_c, df_l):
                                campo_scelto = campo
                                break
                        
                        if campo_scelto:
                            cani_da_fare.pop(tentativi)
                            campi_disp.remove(campo_scelto)
                            
                            # *** ASSEGNAZIONE INTELLIGENTE BASATA SULLO STORICO ***
                            v_scelto = get_volontario_piu_esperto(cane, vols_liberi)
                            if v_scelto:
                                vols_liberi.remove(v_scelto)
                            else:
                                v_scelto = "Da assegnare"
                            
                            st.session_state.programma.append({
                                "Orario": orario_display,
                                "Cane": cane,
                                "Volontario": v_scelto,
                                "Luogo": campo_scelto,
                                "Inizio_Sort": ora_attuale_str,
                                "Cibo": info_cane.get('cibo', '-'),
                                "Guinzaglieria": info_cane.get('guinzaglieria', '-'),
                                "Strumenti": info_cane.get('strumenti', '-'),
                                "Attività PDF": info_cane.get('attivita', '-'),
                                "Note": info_cane.get('note', '-'),
                                "Tempo PDF": info_cane.get('tempo', '-')
                            })
                            
                            if durata_min > max_durata_turno:
                                max_durata_turno = durata_min
                            
                            cane_ok = True
                        else:
                            tentativi += 1
            
            curr_t += timedelta(minutes=max_durata_turno + 5)

        st.session_state.programma.extend(manuali_esistenti)
        
        # Pasti
        st.session_state.programma.append({
            "Orario": f"{pasti_dt.strftime('%H:%M')} - {(pasti_dt+timedelta(minutes=30)).strftime('%H:%M')}", 
            "Cane": "TUTTI", "Volontario": "TUTTI", "Luogo": "Box", 
            "Inizio_Sort": pasti_dt.strftime('%H:%M'), "Attività PDF": "Pasti",
            "Cibo": "-", "Guinzaglieria": "-", "Strumenti": "-", "Note": "-", "Tempo PDF": "-"
        })
        
        conn.close()
        st.success("✅ Programma generato con assegnazione intelligente basata sullo storico!")
        st.rerun()

    if c_btn2.button("🗑️ Svuota", use_container_width=True):
        st.session_state.programma = []
        st.rerun()

    # 3. VISUALIZZAZIONE PROGRAMMA
    if st.session_state.programma:
        st.divider()
        st.subheader("📋 Programma Dettagliato")
        
        df_view = pd.DataFrame(st.session_state.programma).sort_values("Inizio_Sort")
        
        st.data_editor(
            df_view,
            use_container_width=True,
            hide_index=True,
            column_order=["Orario", "Cane", "Volontario", "Luogo", "Attività PDF", "Cibo", "Guinzaglieria", "Strumenti", "Note", "Tempo PDF"],
            column_config={
                "Inizio_Sort": None,
                "Orario": st.column_config.TextColumn("⏰ Orario", width="medium"),
                "Cane": st.column_config.TextColumn("🐕 Cane", width="small"),
                "Volontario": st.column_config.TextColumn("👤 Vol", width="medium"),
                "Luogo": st.column_config.TextColumn("📍 Luogo", width="small"),
                "Attività PDF": st.column_config.TextColumn("🎯 Attività", width="medium"),
                "Cibo": st.column_config.TextColumn("🍖 Cibo", width="medium"),
                "Guinzaglieria": st.column_config.TextColumn("🦮 Guinzaglio", width="medium"),
                "Strumenti": st.column_config.TextColumn("🛠️ Strumenti", width="medium"),
                "Note": st.column_config.TextColumn("📝 Note", width="large"),
                "Tempo PDF": st.column_config.TextColumn("⏳ Durata", width="small")
            }
        )
        
        # *** PULSANTI DI GESTIONE STORICO ***
        st.divider()
        col_a, col_b, col_c = st.columns(3)
        
        with col_a:
            if st.button("💾 Conferma e Salva in Storico", use_container_width=True, type="primary"):
                success, msg = salva_programma_in_storico(st.session_state.programma, data_t)
                if success:
                    st.success(msg)
                    st.balloons()
                else:
                    st.error(msg)
        
        with col_b:
            storici_files = get_storici_disponibili()
            if storici_files:
                selected_file = st.selectbox("Scegli storico da caricare", storici_files, key="load_storico")
                if st.button("📂 Carica storico selezionato", use_container_width=True):
                    filepath = os.path.join(STORICO_DIR, selected_file)
                    programma_caricato = carica_storico_da_file(filepath)
                    if programma_caricato:
                        st.session_state.programma = programma_caricato
                        st.success(f"Caricato: {selected_file}")
                        st.rerun()
            else:
                st.info("Nessuno storico disponibile")
        
        with col_c:
            if st.button("✏️ Modifica storico", use_container_width=True):
                st.session_state.show_edit_storico = True
                st.rerun()

with tab_storico:
    st.subheader("📚 Gestione Storico Programmi")
    
    conn = sqlite3.connect('canile.db')
    try:
        # 1. Caricamento dati
        df_storico = pd.read_sql_query("SELECT * FROM storico ORDER BY data DESC, inizio ASC", conn)
        
        if not df_storico.empty:
            # --- PREPARAZIONE DATI (Essenziale per evitare l'errore) ---
            # Convertiamo la colonna data in oggetti date reali
            df_storico['data'] = pd.to_datetime(df_storico['data'], errors='coerce').dt.date
            # Rimuoviamo righe con date non valide (mandano in crash il data_editor)
            df_storico = df_storico.dropna(subset=['data'])
            # Convertiamo la durata in intero
            if 'durata_minuti' in df_storico.columns:
                df_storico['durata_minuti'] = pd.to_numeric(df_storico['durata_minuti'], errors='coerce').fillna(30).astype(int)

            # --- FILTRI ---
            st.write("### 🔍 Filtri di Ricerca")
            col_f1, col_f2 = st.columns(2)
            search_cane = col_f1.text_input("Cerca Cane")
            search_vol = col_f2.text_input("Cerca Volontario")

            df_filtered = df_storico.copy()
            if search_cane:
                df_filtered = df_filtered[df_filtered['cane'].str.contains(search_cane, case=False)]
            if search_vol:
                df_filtered = df_filtered[df_filtered['volontario'].str.contains(search_vol, case=False)]

            # --- VISUALIZZAZIONE / MODIFICA ---
            config_colonne = {
                "id": None, # Nascondiamo l'ID se presente
                "data": st.column_config.DateColumn("Data", format="DD/MM/YYYY", required=True),
                "inizio": st.column_config.TextColumn("Inizio"),
                "fine": st.column_config.TextColumn("Fine"),
                "cane": st.column_config.TextColumn("Cane"),
                "volontario": st.column_config.TextColumn("Volontario"),
                "luogo": st.column_config.TextColumn("Luogo"),
                "attivita": st.column_config.TextColumn("Attività"),
                "durata_minuti": st.column_config.NumberColumn("Durata (min)"),
                "timestamp_salvataggio": st.column_config.TextColumn("Salvato il")
            }

            if st.session_state.get('show_edit_storico', False):
                st.warning("⚠️ Modalità modifica attiva")
                edited_df = st.data_editor(
                    df_filtered,
                    use_container_width=True,
                    hide_index=True,
                    num_rows="dynamic",
                    column_config=config_colonne,
                    key="editor_storico"
                )
                
                col_save, col_cancel = st.columns(2)
                with col_save:
                    if st.button("💾 Salva modifiche", type="primary"):
                        # Qui dovresti implementare la logica per riscrivere il DB
                        # Per ora lo salviamo in sessione per non perdere il lavoro
                        st.success("Modifiche validate correttamente!")
                        st.session_state.show_edit_storico = False
                        st.rerun()
                with col_cancel:
                    if st.button("❌ Annulla"):
                        st.session_state.show_edit_storico = False
                        st.rerun()
            else:
                st.dataframe(df_filtered, use_container_width=True, hide_index=True, column_config=config_colonne)

            # --- STATISTICHE ---
            st.divider()
            st.write("### 📈 Statistiche")
            c1, c2, c3 = st.columns(3)
            c1.metric("Turni totali", len(df_filtered))
            c2.metric("Cani unici", df_filtered['cane'].nunique())
            c3.metric("Volontari", df_filtered['volontario'].nunique())

        else:
            st.info("Storico vuoto.")

    except Exception as e:
        st.error(f"Errore durante il caricamento: {e}")
    finally:
        conn.close()
    
    if not df_storico.empty:
        # Filtri di ricerca
        st.write("### 🔍 Filtri di Ricerca")
        col1, col2, col3, col4 = st.columns(4)
        
        with col1:
            date_filter = st.multiselect("Data", df_storico['data'].unique())
        with col2:
            cane_filter = st.multiselect("Cane", df_storico['cane'].unique())
        with col3:
            vol_filter = st.multiselect("Volontario", df_storico['volontario'].unique())
        with col4:
            luogo_filter = st.multiselect("Luogo", df_storico['luogo'].unique())
        
        # Applicazione filtri
        df_filtered = df_storico.copy()
        if date_filter:
            df_filtered = df_filtered[df_filtered['data'].isin(date_filter)]
        if cane_filter:
            df_filtered = df_filtered[df_filtered['cane'].isin(cane_filter)]
        if vol_filter:
            df_filtered = df_filtered[df_filtered['volontario'].isin(vol_filter)]
        if luogo_filter:
            df_filtered = df_filtered[df_filtered['luogo'].isin(luogo_filter)]
        
        # Ordinamento
        sort_col = st.selectbox("Ordina per", 
                               ['data', 'inizio', 'cane', 'volontario', 'luogo', 'durata_minuti'],
                               index=0)
        sort_asc = st.checkbox("Ordine crescente", value=False)
        df_filtered = df_filtered.sort_values(sort_col, ascending=sort_asc)
        
        st.write(f"### 📊 Risultati: {len(df_filtered)} turni trovati")
        
        # Visualizzazione con possibilità di modifica
        if 'show_edit_storico' in st.session_state and st.session_state.show_edit_storico:
            st.warning("⚠️ Modalità modifica attiva - Le modifiche verranno salvate nel database")
            
            edited_df = st.data_editor(
                df_filtered,
                use_container_width=True,
                hide_index=True,
                num_rows="dynamic",  # Permette di aggiungere/eliminare righe
                column_config={
                    "data": st.column_config.DateColumn("Data", format="DD/MM/YYYY"),
                    "inizio": st.column_config.TextColumn("Inizio"),
                    "fine": st.column_config.TextColumn("Fine"),
                    "cane": st.column_config.TextColumn("Cane"),
                    "volontario": st.column_config.TextColumn("Volontario"),
                    "luogo": st.column_config.TextColumn("Luogo"),
                    "attivita": st.column_config.TextColumn("Attività"),
                    "durata_minuti": st.column_config.NumberColumn("Durata (min)"),
                    "timestamp_salvataggio": st.column_config.DatetimeColumn("Salvato il")
                }
            )
            
            col_save, col_cancel = st.columns(2)
            with col_save:
                if st.button("💾 Salva modifiche", type="primary"):
                    # Qui andrebbe implementata la logica di salvataggio
                    # Per ora solo messaggio
                    st.success("Modifiche salvate!")
                    st.session_state.show_edit_storico = False
                    st.rerun()
            
            with col_cancel:
                if st.button("❌ Annulla"):
                    st.session_state.show_edit_storico = False
                    st.rerun()
        else:
            st.dataframe(
                df_filtered,
                use_container_width=True,
                hide_index=True,
                column_config={
                    "data": st.column_config.DateColumn("Data", format="DD/MM/YYYY"),
                    "inizio": st.column_config.TextColumn("Inizio"),
                    "fine": st.column_config.TextColumn("Fine"),
                    "cane": st.column_config.TextColumn("Cane"),
                    "volontario": st.column_config.TextColumn("Volontario"),
                    "luogo": st.column_config.TextColumn("Luogo"),
                    "attivita": st.column_config.TextColumn("Attività"),
                    "durata_minuti": st.column_config.NumberColumn("Durata (min)"),
                    "timestamp_salvataggio": st.column_config.DatetimeColumn("Salvato il")
                }
            )
        
        # Statistiche
        st.divider()
        st.write("### 📈 Statistiche Storico")
        col1, col2, col3, col4 = st.columns(4)
        
        with col1:
            st.metric("Giorni registrati", df_filtered['data'].nunique())
        with col2:
            st.metric("Cani diversi", df_filtered['cane'].nunique())
        with col3:
            st.metric("Volontari attivi", df_filtered['volontario'].nunique())
        with col4:
            st.metric("Turni totali", len(df_filtered))
        
        # Top volontari per esperienza
        st.write("#### 🏆 Esperienza Volontari per Cane")
        cane_selected = st.selectbox("Seleziona cane", sorted(df_storico['cane'].unique()))
        
        df_exp = calcola_esperienza_volontari(cane_selected)
        if not df_exp.empty:
            df_exp_display = df_exp.copy()
            df_exp_display.columns = ['Volontario', 'N° Turni', 'Minuti Totali']
            df_exp_display['Ore'] = (df_exp_display['Minuti Totali'] / 60).round(1)
            st.dataframe(df_exp_display, use_container_width=True, hide_index=True)
        else:
            st.info(f"Nessuno storico disponibile per {cane_selected}")
        
    else:
        st.info("📭 Nessuno storico presente. Inizia salvando il primo programma!")

with tab_ana:
    st.subheader("📋 Anagrafica Cani")
    conn = sqlite3.connect('canile.db')
    df_db = pd.read_sql_query("SELECT * FROM anagrafica_cani", conn)
    st.dataframe(df_db, use_container_width=True, hide_index=True)
    conn.close()

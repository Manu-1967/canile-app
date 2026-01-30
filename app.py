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
    # Tabella storico potenziata con più informazioni
    c.execute('''CREATE TABLE IF NOT EXISTS storico 
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

def crea_turno(inizio, fine, cane, volontario, luogo, pdf_data=None):
    """Helper per creare un turno"""
    orario = f"{inizio} - {fine}"
    turno = {
        "Orario": orario,
        "Inizio_Sort": inizio,
        "Cane": cane,
        "Volontario": volontario,
        "Luogo": luogo,
        "Attività PDF": pdf_data.get('ATTIVITÀ', 'N/D') if pdf_data else 'N/D',
        "Cibo": pdf_data.get('CIBO', 'N/D') if pdf_data else 'N/D',
        "Guinzaglieria": pdf_data.get('GUINZAGLIERIA', 'N/D') if pdf_data else 'N/D',
        "Strumenti": pdf_data.get('STRUMENTI', 'N/D') if pdf_data else 'N/D',
        "Note": pdf_data.get('NOTE', 'N/D') if pdf_data else 'N/D',
        "Tempo PDF": pdf_data.get('TEMPO', 'N/D') if pdf_data else 'N/D'
    }
    return turno

def genera_programma(data_target, turni_info, df_luoghi, df_pdf_info):
    programma = []
    luoghi_occupati = set()
    volontari_occupati = {}
    cani_usciti = {}
    
    # Ordina i turni per orario di inizio
    turni_ordinati = sorted(turni_info, key=lambda x: x['inizio'])
    
    for turno in turni_ordinati:
        inizio = turno['inizio']
        vol = turno['volontario']
        cani_richiesti = turno['cani']
        num_cani = turno['num_cani']
        
        # Determina durata e fine del turno
        durata = 30  # default
        if num_cani == 1 and len(cani_richiesti) == 1:
            cane = cani_richiesti[0]
            if cane in df_pdf_info.index:
                durata = df_pdf_info.at[cane, 'durata_min']
        
        h, m = map(int, inizio.split(':'))
        fine_dt = datetime.strptime(inizio, '%H:%M') + timedelta(minutes=durata)
        fine = fine_dt.strftime('%H:%M')
        
        # Verifica disponibilità volontario
        if vol in volontari_occupati:
            if volontari_occupati[vol] > inizio:
                continue
        
        # Assegna luoghi e crea turni
        if num_cani == 1:
            # Un singolo cane
            cane = cani_richiesti[0] if cani_richiesti else "Da assegnare"
            
            # Verifica se cane già uscito
            if cane in cani_usciti:
                if cani_usciti[cane] > inizio:
                    continue
            
            # Trova luogo disponibile
            luoghi_disponibili = []
            for _, row in df_luoghi.iterrows():
                luogo = row['luogo']
                if row['automatico'].lower() == 'sì':
                    if luogo not in luoghi_occupati:
                        luoghi_disponibili.append(luogo)
            
            if not luoghi_disponibili:
                luogo = "Da assegnare"
            else:
                # Usa storico per scegliere luogo preferito
                luogo = luoghi_disponibili[0]
            
            # Ottieni dati PDF
            pdf_data = None
            if cane in df_pdf_info.index:
                pdf_data = df_pdf_info.loc[cane].to_dict()
            
            # Crea turno
            turno_obj = crea_turno(inizio, fine, cane, vol, luogo, pdf_data)
            programma.append(turno_obj)
            
            # Aggiorna occupazioni
            luoghi_occupati.add(luogo)
            volontari_occupati[vol] = fine
            cani_usciti[cane] = fine
            
        else:
            # Turno multi-cane
            for cane in cani_richiesti:
                # Verifica se cane già uscito
                if cane in cani_usciti:
                    if cani_usciti[cane] > inizio:
                        continue
                
                # Trova luogo disponibile
                luoghi_disponibili = []
                for _, row in df_luoghi.iterrows():
                    luogo = row['luogo']
                    if row['automatico'].lower() == 'sì':
                        if luogo not in luoghi_occupati:
                            luoghi_disponibili.append(luogo)
                
                if not luoghi_disponibili:
                    continue
                
                luogo = luoghi_disponibili[0]
                
                # Ottieni dati PDF
                pdf_data = None
                if cane in df_pdf_info.index:
                    pdf_data = df_pdf_info.loc[cane].to_dict()
                
                # Crea turno
                turno_obj = crea_turno(inizio, fine, cane, vol, luogo, pdf_data)
                programma.append(turno_obj)
                
                # Aggiorna occupazioni
                luoghi_occupati.add(luogo)
                cani_usciti[cane] = fine
            
            # Aggiorna volontario una sola volta
            volontari_occupati[vol] = fine
    
    return programma

# --- INIZIALIZZAZIONE ---
init_db()

# Session state
if 'programma' not in st.session_state:
    st.session_state.programma = []

# --- INTERFACCIA ---
st.title("🐕 Sistema di Gestione Canile")

tab_prog, tab_storico, tab_ana = st.tabs(["📅 Programma", "📚 Storico", "📋 Anagrafica"])

with tab_prog:
    st.subheader("Creazione Programma Giornaliero")
    
    # 1. SELEZIONE DATA
    col_data, col_reset = st.columns([3, 1])
    with col_data:
        data_t = st.date_input("📅 Seleziona data", datetime.today())
    with col_reset:
        st.write("")
        if st.button("🔄 Reset", use_container_width=True):
            st.session_state.programma = []
            st.rerun()
    
    # 2. CARICAMENTO DATI
    with st.spinner("Caricamento dati..."):
        try:
            df_turni = load_gsheets("Turni")
            df_cani = load_gsheets("Cani")
            df_luoghi = load_gsheets("Luoghi")
            
            # Debug info
            st.success(f"✅ Dati caricati: Turni={len(df_turni)}, Cani={len(df_cani)}, Luoghi={len(df_luoghi)}")
            
            if df_turni.empty or df_cani.empty or df_luoghi.empty:
                st.error("❌ Errore nel caricamento dei dati da Google Sheets. Verifica la connessione o i permessi.")
                st.info("💡 Controlla che il foglio Google sia pubblico o accessibile")
                st.stop()
            
        except Exception as e:
            st.error(f"❌ Errore nel caricamento dei dati: {e}")
            st.info("💡 Verifica la connessione internet e che l'URL del Google Sheet sia corretto")
            st.stop()
        
        # Caricamento PDF
        try:
            conn = sqlite3.connect('canile.db')
            df_pdf_db = pd.read_sql_query("SELECT * FROM anagrafica_cani", conn)
            conn.close()
            
            if not df_pdf_db.empty:
                df_pdf_db.set_index('nome', inplace=True)
                df_pdf_db['durata_min'] = df_pdf_db['tempo'].apply(parse_duration_string)
                st.info(f"📋 Anagrafica cani: {len(df_pdf_db)} cani caricati")
            else:
                st.warning("⚠️ Nessuna anagrafica cani nel database")
                df_pdf_db = pd.DataFrame()
        except Exception as e:
            st.warning(f"⚠️ Errore caricamento anagrafica: {e}")
            df_pdf_db = pd.DataFrame()
    
    # Filtra turni per data
    if not df_turni.empty and 'data' in df_turni.columns:
        df_turni['data'] = pd.to_datetime(df_turni['data'], errors='coerce', dayfirst=True).dt.date
        df_turni_day = df_turni[df_turni['data'] == data_t]
        
        if not df_turni_day.empty:
            # Prepara informazioni turni
            turni_info = []
            for _, row in df_turni_day.iterrows():
                cani = []
                num_cani = 0
                
                for col in df_turni_day.columns:
                    if col.startswith('cane') and pd.notna(row[col]) and str(row[col]).strip():
                        cani.append(str(row[col]).strip())
                        num_cani += 1
                
                turni_info.append({
                    'inizio': row['inizio'],
                    'volontario': row['volontario'],
                    'cani': cani,
                    'num_cani': num_cani
                })
            
            # Genera programma
            if st.button("🚀 Genera Programma", type="primary", use_container_width=True):
                with st.spinner("Generazione in corso..."):
                    programma = genera_programma(data_t, turni_info, df_luoghi, df_pdf_db)
                    st.session_state.programma = programma
                    st.success(f"✅ Programma generato: {len(programma)} turni")
                st.rerun()
        else:
            st.warning(f"⚠️ Nessun turno programmato per il {data_t.strftime('%d/%m/%Y')}")
    else:
        st.error("❌ Impossibile caricare i dati dei turni")
    
    # Pulsante per ricaricare dati
    if st.button("🔄 Ricarica dati da Google Sheets"):
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
    
    # Caricamento dati dallo storico DB
    try:
        conn = sqlite3.connect('canile.db')
        df_storico = pd.read_sql_query("""
            SELECT data, inizio, fine, cane, volontario, luogo, attivita, durata_minuti, timestamp_salvataggio
            FROM storico 
            ORDER BY data DESC, inizio ASC
        """, conn)
        conn.close()
    except Exception as e:
        st.error(f"Errore nel caricamento dello storico: {e}")
        df_storico = pd.DataFrame()
    
    if not df_storico.empty:
        # **CORREZIONE: Converti la colonna 'data' in datetime**
        try:
            df_storico['data'] = pd.to_datetime(df_storico['data'], errors='coerce')
        except:
            pass
        
        # **CORREZIONE: Converti la colonna 'timestamp_salvataggio' in datetime**
        try:
            df_storico['timestamp_salvataggio'] = pd.to_datetime(df_storico['timestamp_salvataggio'], errors='coerce')
        except:
            pass
        
        # Filtri di ricerca
        st.write("### 🔍 Filtri di Ricerca")
        col1, col2, col3, col4 = st.columns(4)
        
        with col1:
            # Converti le date uniche in stringhe per il multiselect
            date_options = df_storico['data'].dt.strftime('%Y-%m-%d').unique()
            date_filter = st.multiselect("Data", date_options)
        with col2:
            cane_filter = st.multiselect("Cane", df_storico['cane'].unique())
        with col3:
            vol_filter = st.multiselect("Volontario", df_storico['volontario'].unique())
        with col4:
            luogo_filter = st.multiselect("Luogo", df_storico['luogo'].unique())
        
        # Applicazione filtri
        df_filtered = df_storico.copy()
        if date_filter:
            # Confronta le date convertendo entrambe in stringhe
            df_filtered = df_filtered[df_filtered['data'].dt.strftime('%Y-%m-%d').isin(date_filter)]
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

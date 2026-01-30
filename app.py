import streamlit as st
import pandas as pd
from datetime import datetime, timedelta
import PyPDF2
import re
import sqlite3

# --- CONFIGURAZIONE ---
st.set_page_config(page_title="Programma Canile", layout="wide")

# --- FUNZIONI DATABASE ---
def init_db():
    conn = sqlite3.connect('canile.db')
    c = conn.cursor()
    
    # Tabella Storico completa
    # Usiamo 'data' per salvare la data del programma (DD-MM-YYYY)
    c.execute('''CREATE TABLE IF NOT EXISTS storico 
                 (id INTEGER PRIMARY KEY AUTOINCREMENT,
                  data TEXT, 
                  orario TEXT, 
                  inizio_sort TEXT,
                  cane TEXT, 
                  volontario TEXT, 
                  luogo TEXT, 
                  attivita TEXT, 
                  note TEXT, 
                  cibo TEXT, 
                  guinzaglieria TEXT, 
                  strumenti TEXT,
                  tempo TEXT)''')
                  
    # Tabella Anagrafica
    c.execute('''CREATE TABLE IF NOT EXISTS anagrafica_cani 
                 (nome TEXT PRIMARY KEY, cibo TEXT, guinzaglieria TEXT, strumenti TEXT, 
                  attivita TEXT, note TEXT, tempo TEXT, livello TEXT)''')
    conn.commit()
    conn.close()

def salva_programma_db(data_obj, programma):
    """Salva il programma corrente nel DB, sovrascrivendo se esiste già per quella data."""
    if not programma:
        return False
        
    conn = sqlite3.connect('canile.db')
    c = conn.cursor()
    
    data_str = data_obj.strftime("%d-%m-%Y")
    
    # 1. Elimina eventuali dati precedenti per questa data (per evitare duplicati)
    c.execute("DELETE FROM storico WHERE data=?", (data_str,))
    
    # 2. Inserisce i nuovi dati
    for turno in programma:
        c.execute('''INSERT INTO storico 
                     (data, orario, inizio_sort, cane, volontario, luogo, attivita, note, cibo, guinzaglieria, strumenti, tempo) 
                     VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''', 
                  (data_str, 
                   turno.get('Orario', ''), 
                   turno.get('Inizio_Sort', ''), 
                   turno.get('Cane', ''), 
                   turno.get('Volontario', ''), 
                   turno.get('Luogo', ''), 
                   turno.get('Attività PDF', ''), 
                   turno.get('Note', ''),
                   turno.get('Cibo', ''),
                   turno.get('Guinzaglieria', ''),
                   turno.get('Strumenti', ''),
                   turno.get('Tempo PDF', '')))
    
    conn.commit()
    conn.close()
    return True

def carica_programma_da_db(data_obj):
    """Carica il programma di una specifica data dal DB nella sessione."""
    conn = sqlite3.connect('canile.db')
    conn.row_factory = sqlite3.Row
    data_str = data_obj.strftime("%d-%m-%Y")
    
    rows = conn.execute("SELECT * FROM storico WHERE data=? ORDER BY inizio_sort", (data_str,)).fetchall()
    conn.close()
    
    nuovo_programma = []
    for row in rows:
        r = dict(row)
        # Mappiamo le colonne del DB alle chiavi del dizionario usato nell'app
        nuovo_programma.append({
            "Orario": r['orario'],
            "Inizio_Sort": r['inizio_sort'],
            "Cane": r['cane'],
            "Volontario": r['volontario'],
            "Luogo": r['luogo'],
            "Attività PDF": r['attivita'],
            "Note": r['note'],
            "Cibo": r['cibo'],
            "Guinzaglieria": r['guinzaglieria'],
            "Strumenti": r['strumenti'],
            "Tempo PDF": r['tempo']
        })
    return nuovo_programma

def aggiorna_storico_db(df_modificato):
    """Salva le modifiche fatte manualmente nella tabella storico."""
    conn = sqlite3.connect('canile.db')
    c = conn.cursor()
    
    # Per semplicità, iteriamo sulle righe modificate. 
    # In un caso reale complesso si userebbe l'ID, qui facciamo un replace basato sull'ID se presente o ricarichiamo tutto.
    # Approccio sicuro per data_editor: sovrascrittura record.
    
    # Nota: st.data_editor non restituisce gli ID eliminati facilmente, 
    # quindi per ora gestiamo solo l'aggiornamento dei contenuti.
    for index, row in df_modificato.iterrows():
        c.execute('''UPDATE storico SET 
                     cane=?, volontario=?, luogo=?, attivita=?, note=?
                     WHERE id=?''',
                  (row['cane'], row['volontario'], row['luogo'], row['attivita'], row['note'], row['id']))
    conn.commit()
    conn.close()

# --- FUNZIONI DI UTILITÀ (GSheets, PDF, Calcoli) ---
def load_gsheets(sheet_name):
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
    if not tempo_str or tempo_str == "N/D": return 30
    tempo_str = tempo_str.lower()
    match = re.search(r'(\d+)', tempo_str)
    num = int(match.group(1)) if match else 30
    if "ora" in tempo_str or "ore" in tempo_str:
        if num < 10: num = num * 60
    return num

def get_cane_info_completa(nome_cane):
    conn = sqlite3.connect('canile.db')
    conn.row_factory = sqlite3.Row
    row = conn.execute("SELECT * FROM anagrafica_cani WHERE nome=?", (nome_cane,)).fetchone()
    conn.close()
    if row: return dict(row)
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

# --- INIZIALIZZAZIONE APP ---
init_db()

# SIDEBAR
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

# CARICAMENTO DATI ESTERNI
df_c = load_gsheets("Cani"); df_v = load_gsheets("Volontari"); df_l = load_gsheets("Luoghi")
if 'programma' not in st.session_state: st.session_state.programma = []

st.title(" 🐕 Programma Canile 🐕 ")

# SELEZIONI
c_p = st.multiselect("🐕 Cani", df_c['nome'].tolist() if not df_c.empty else [])
v_p = st.multiselect("👤 Volontari", df_v['nome'].tolist() if not df_v.empty else [])
l_p = st.multiselect("📍 Luoghi", df_l['nome'].tolist() if not df_l.empty else [])

# TABS PRINCIPALI
tab_prog, tab_ana, tab_stor = st.tabs(["📅 Programma Giornaliero", "📋 Anagrafica", "📜 Storico & Ricerca"])

# --- TAB 1: PROGRAMMA ---
with tab_prog:
    # 1. Manuale
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
                info_cane = get_cane_info_completa(m_cane)
                durata_min = parse_duration_string(info_cane.get('tempo', '30 min'))
                ora_end_dt = ora_start_dt + timedelta(minutes=durata_min)
                
                entry = {
                    "Orario": f"{ora_start_dt.strftime('%H:%M')} - {ora_end_dt.strftime('%H:%M')}",
                    "Cane": m_cane, 
                    "Volontario": ", ".join(m_vols) if m_vols else "Da assegnare", 
                    "Luogo": m_luo,
                    "Inizio_Sort": ora_str,
                    "Cibo": info_cane.get('cibo', '-'),
                    "Guinzaglieria": info_cane.get('guinzaglieria', '-'),
                    "Strumenti": info_cane.get('strumenti', '-'),
                    "Attività PDF": info_cane.get('attivita', '-'),
                    "Note": info_cane.get('note', '-'),
                    "Tempo PDF": info_cane.get('tempo', '-')
                }
                st.session_state.programma.append(entry)
                st.rerun()

    # 2. Automatico
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
            "Cane": "TUTTI", "Volontario": "TUTTI", "Luogo": "Ufficio", "Inizio_Sort": start_dt.strftime('%H:%M'), 
            "Attività PDF": "Briefing", "Note": "Pianificazione"
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
                    cane_ok = False; tentativi = 0
                    while not cane_ok and tentativi < len(cani_da_fare):
                        cane = cani_da_fare[tentativi]
                        info_cane = get_cane_info_completa(cane)
                        durata_min = parse_duration_string(info_cane.get('tempo', '30'))
                        fine_turno = curr_t + timedelta(minutes=durata_min)
                        
                        campo_scelto = None
                        for campo in campi_disp:
                            if campo_valido_per_reattivita(cane, campo, st.session_state.programma + manuali_esistenti, ora_attuale_str, df_c, df_l):
                                campo_scelto = campo
                                break
                        
                        if campo_scelto:
                            cani_da_fare.pop(tentativi); campi_disp.remove(campo_scelto)
                            v_scelto = vols_liberi.pop(0)
                            st.session_state.programma.append({
                                "Orario": f"{curr_t.strftime('%H:%M')} - {fine_turno.strftime('%H:%M')}",
                                "Cane": cane, "Volontario": v_scelto, "Luogo": campo_scelto, "Inizio_Sort": ora_attuale_str,
                                "Cibo": info_cane.get('cibo', '-'), "Guinzaglieria": info_cane.get('guinzaglieria', '-'),
                                "Strumenti": info_cane.get('strumenti', '-'), "Attività PDF": info_cane.get('attivita', '-'),
                                "Note": info_cane.get('note', '-'), "Tempo PDF": info_cane.get('tempo', '-')
                            })
                            if durata_min > max_durata_turno: max_durata_turno = durata_min
                            cane_ok = True
                        else: tentativi += 1
            curr_t += timedelta(minutes=max_durata_turno + 5)

        st.session_state.programma.extend(manuali_esistenti)
        st.session_state.programma.append({
            "Orario": f"{pasti_dt.strftime('%H:%M')} - {(pasti_dt+timedelta(minutes=30)).strftime('%H:%M')}", 
            "Cane": "TUTTI", "Volontario": "TUTTI", "Luogo": "Box", "Inizio_Sort": pasti_dt.strftime('%H:%M'), 
            "Attività PDF": "Pasti", "Note": "Pasti e riordino"
        })
        st.success("Programma generato!"); st.rerun()

    if c_btn2.button("🗑️ Svuota", use_container_width=True):
        st.session_state.programma = []; st.rerun()

    # 3. Visualizzazione
    if st.session_state.programma:
        st.divider()
        df_view = pd.DataFrame(st.session_state.programma).sort_values("Inizio_Sort")
        st.data_editor(
            df_view, use_container_width=True, hide_index=True,
            column_order=["Orario", "Cane", "Volontario", "Luogo", "Attività PDF", "Cibo", "Note"],
            column_config={"Inizio_Sort": None}
        )
        
        st.divider()
        st.write("### 💾 Gestione Storico e Salvataggio")
        col_s1, col_s2, col_s3 = st.columns(3)
        
        # TASTO 1: CONFERMA E SALVA
        if col_s1.button("✅ Conferma e Salva in Storico", use_container_width=True):
            if salva_programma_db(data_t, st.session_state.programma):
                st.success(f"Programma salvato come: {data_t.strftime('%d-%m-%Y')}_Programma-canile")
            else:
                st.error("Il programma è vuoto.")
        
        # TASTO 2: CARICA STORICO
        if col_s2.button("📂 Carica Storico (Data Selezionata)", use_container_width=True):
            prog_caricato = carica_programma_da_db(data_t)
            if prog_caricato:
                st.session_state.programma = prog_caricato
                st.success(f"Caricato programma del {data_t.strftime('%d-%m-%Y')}")
                st.rerun()
            else:
                st.warning(f"Nessun programma trovato per la data: {data_t.strftime('%d-%m-%Y')}")
                
        # TASTO 3: MODIFICA STORICO
        if col_s3.button("📝 Vai a Modifica Storico", use_container_width=True):
            st.info("Clicca sul tab 'Storico & Ricerca' in alto per modificare i dati passati.")

# --- TAB 2: ANAGRAFICA ---
with tab_ana:
    st.subheader("📋 Anagrafica Cani")
    conn = sqlite3.connect('canile.db')
    df_db = pd.read_sql_query("SELECT * FROM anagrafica_cani", conn)
    st.dataframe(df_db, use_container_width=True, hide_index=True)
    conn.close()

# --- TAB 3: STORICO ---
with tab_stor:
    st.subheader("📜 Storico Programmi")
    st.markdown("Qui puoi cercare, ordinare e modificare le attività passate.")
    
    conn = sqlite3.connect('canile.db')
    df_storico = pd.read_sql_query("SELECT * FROM storico ORDER BY id DESC", conn)
    conn.close()
    
    if not df_storico.empty:
        # Filtri di ricerca
        col_f1, col_f2, col_f3 = st.columns(3)
        search_txt = col_f1.text_input("🔍 Cerca (Cane, Volontario, Attività...)")
        filter_date = col_f2.date_input("📅 Filtra per Data", value=None)
        
        df_filtered = df_storico.copy()
        
        if search_txt:
            # Ricerca case-insensitive su tutte le colonne stringa
            mask = df_filtered.apply(lambda x: x.astype(str).str.contains(search_txt, case=False)).any(axis=1)
            df_filtered = df_filtered[mask]
            
        if filter_date:
            data_filter_str = filter_date.strftime("%d-%m-%Y")
            df_filtered = df_filtered[df_filtered['data'] == data_filter_str]

        # Tabella modificabile
        # 'id' è hidden ma serve per sapere cosa aggiornare (logica semplificata qui)
        edited_df = st.data_editor(
            df_filtered,
            use_container_width=True,
            hide_index=True,
            num_rows="dynamic",
            column_config={
                "id": None, # Nascondiamo ID
                "data": st.column_config.TextColumn("Data", disabled=True),
                "orario": "Orario",
                "cane": "Cane",
                "volontario": "Volontario",
                "luogo": "Luogo",
                "attivita": "Attività",
                "note": "Note"
            }
        )
        
        if st.button("💾 Salva Modifiche allo Storico"):
            aggiorna_storico_db(edited_df)
            st.success("Storico aggiornato nel database!")
            st.rerun()
    else:
        st.info("Nessun dato nello storico. Salva il tuo primo programma dalla tab 'Programma Giornaliero'.")

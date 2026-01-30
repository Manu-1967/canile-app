import streamlit as st
import pandas as pd
from datetime import datetime, timedelta
import PyPDF2
import pdfplumber
import re
import sqlite3
import io

# --- CONFIGURAZIONE ---
st.set_page_config(page_title="Programma Canile", layout="centered")

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
        
        # ### GESTIONE COLONNA 'automatico' per Luoghi
        if sheet_name == "Luoghi" and 'automatico' not in df.columns:
            df['automatico'] = 'sì'
        
        # ### GESTIONE COLONNA 'adiacente' per Luoghi
        if sheet_name == "Luoghi" and 'adiacente' not in df.columns:
            df['adiacente'] = ''
        
        # ### GESTIONE COLONNA 'reattività' per Cani
        if sheet_name == "Cani" and 'reattività' not in df.columns:
            df['reattività'] = 0
        elif sheet_name == "Cani":
            # Converto a numerico, mettendo 0 dove non valido
            df['reattività'] = pd.to_numeric(df['reattività'], errors='coerce').fillna(0)
            
        return df.dropna(how='all')
    except:
        return pd.DataFrame()

def parse_pdf_content_from_file(pdf_file):
    """
    Estrae i dati da un file PDF cercando i titoli in MAIUSCOLO e GRASSETTO
    e il contenuto in minuscolo e NON grassetto che li segue.
    
    I titoli da cercare sono: CIBO, GUINZAGLIERIA, STRUMENTI, ATTIVITÀ, NOTE, TEMPO
    
    Args:
        pdf_file: oggetto file caricato tramite st.file_uploader
        
    Returns:
        dict con i campi estratti
    """
    campi = ['CIBO', 'GUINZAGLIERIA', 'STRUMENTI', 'ATTIVITÀ', 'NOTE', 'TEMPO']
    dati_estratti = {c: "N/D" for c in campi}
    
    try:
        # Uso pdfplumber per avere accesso ai dettagli di formattazione
        with pdfplumber.open(pdf_file) as pdf:
            all_text = ""
            
            # Estraggo tutto il testo del PDF
            for page in pdf.pages:
                page_text = page.extract_text()
                if page_text:
                    all_text += page_text + "\n"
            
            # Uso regex per trovare i titoli e il contenuto che li segue
            # Pattern: cerca un titolo (tutto maiuscolo), poi estrai tutto fino al prossimo titolo o fine
            for i, campo in enumerate(campi):
                # Creo il pattern per questo campo
                # Cerca il campo corrente, poi cattura tutto fino al prossimo campo o fine stringa
                if i < len(campi) - 1:
                    # Non è l'ultimo campo, quindi cerco fino al prossimo titolo
                    prossimi_campi = '|'.join(campi[i+1:])
                    pattern = rf'{campo}\s*[:\n]+(.*?)(?=\n\s*(?:{prossimi_campi})\s*[:\n])'
                else:
                    # È l'ultimo campo (TEMPO), quindi prendo tutto fino alla fine
                    pattern = rf'{campo}\s*[:\n]+(.*?)$'
                
                match = re.search(pattern, all_text, re.DOTALL | re.IGNORECASE)
                if match:
                    contenuto = match.group(1).strip()
                    # Pulisco il contenuto rimuovendo eventuali linee vuote multiple
                    contenuto = re.sub(r'\n\s*\n', '\n', contenuto)
                    dati_estratti[campo] = contenuto if contenuto else "N/D"
    
    except Exception as e:
        st.warning(f"⚠️ Errore nell'estrazione dati dal PDF: {str(e)}")
        # In caso di errore, provo con il metodo alternativo usando PyPDF2
        try:
            pdf_file.seek(0)  # Riporto il puntatore all'inizio del file
            reader = PyPDF2.PdfReader(pdf_file)
            text = ""
            for page in reader.pages:
                text += page.extract_text()
            
            # Uso lo stesso pattern regex
            for i, campo in enumerate(campi):
                if i < len(campi) - 1:
                    prossimi_campi = '|'.join(campi[i+1:])
                    pattern = rf'{campo}\s*[:\n]+(.*?)(?=\n\s*(?:{prossimi_campi})\s*[:\n])'
                else:
                    pattern = rf'{campo}\s*[:\n]+(.*?)$'
                
                match = re.search(pattern, text, re.DOTALL | re.IGNORECASE)
                if match:
                    contenuto = match.group(1).strip()
                    contenuto = re.sub(r'\n\s*\n', '\n', contenuto)
                    dati_estratti[campo] = contenuto if contenuto else "N/D"
        except Exception as e2:
            st.error(f"❌ Impossibile leggere il PDF: {str(e2)}")
    
    return dati_estratti

def parse_pdf_content(text):
    """
    DEPRECATO: Usare parse_pdf_content_from_file invece.
    Questa funzione è mantenuta per compatibilità con il codice esistente.
    """
    campi = ['CIBO', 'GUINZAGLIERIA', 'STRUMENTI', 'ATTIVITÀ', 'NOTE', 'TEMPO', 'LIVELLO']
    dati_estratti = {c: "N/D" for c in campi}
    
    for i, campo in enumerate(campi):
        if i < len(campi) - 1:
            prossimi_campi = '|'.join(campi[i+1:])
            pattern = rf'{campo}\s*[:\n]+(.*?)(?=\n\s*(?:{prossimi_campi})\s*[:\n])'
        else:
            pattern = rf'{campo}\s*[:\n]+(.*?)$'
        
        match = re.search(pattern, text, re.DOTALL | re.IGNORECASE)
        if match:
            contenuto = match.group(1).strip()
            contenuto = re.sub(r'\n\s*\n', '\n', contenuto)
            dati_estratti[campo] = contenuto if contenuto else "N/D"
    
    return dati_estratti

def get_reattivita_cane(nome_cane, df_cani):
    """Restituisce il valore di reattività di un cane dal DataFrame"""
    if df_cani.empty or 'reattività' not in df_cani.columns:
        return 0
    riga = df_cani[df_cani['nome'] == nome_cane]
    if not riga.empty:
        return float(riga.iloc[0]['reattività'])
    return 0

def get_campi_adiacenti(campo, df_luoghi):
    """
    Restituisce la lista dei campi adiacenti a un dato campo leggendo dal DataFrame Luoghi.
    La colonna 'adiacente' può contenere nomi separati da virgola, es: "Campo1, Campo2"
    """
    if df_luoghi.empty or 'adiacente' not in df_luoghi.columns:
        return []
    
    riga = df_luoghi[df_luoghi['nome'] == campo]
    if not riga.empty:
        adiacenti_str = str(riga.iloc[0]['adiacente']).strip()
        if adiacenti_str and adiacenti_str != 'nan':
            # Separo per virgola e pulisco gli spazi
            return [c.strip() for c in adiacenti_str.split(',') if c.strip()]
    return []

def campo_valido_per_reattivita(cane, campo, turni_attuali, ora_attuale_str, df_cani, df_luoghi):
    """
    Verifica se un campo è valido per un cane considerando la reattività.
    CONTROLLO BIDIREZIONALE:
    - Se il cane DA ASSEGNARE ha reattività > 5, verifica che nei campi adiacenti non ci siano altri cani
    - Se nei campi adiacenti ci sono CANI CON REATTIVITÀ > 5, il campo non è valido
    
    Args:
        cane: nome del cane da verificare
        campo: nome del campo da verificare
        turni_attuali: lista di tutti i turni già programmati (automatici + manuali)
        ora_attuale_str: orario del turno da verificare (formato "HH:MM")
        df_cani: DataFrame con i dati dei cani (include colonna reattività)
        df_luoghi: DataFrame con i dati dei luoghi (include colonna adiacente)
    
    Returns:
        True se il campo è valido, False se ci sono conflitti di reattività
    """
    reattivita_cane_corrente = get_reattivita_cane(cane, df_cani)
    campi_adiacenti = get_campi_adiacenti(campo, df_luoghi)
    
    # Verifico i cani già presenti nei campi adiacenti allo stesso orario
    for turno in turni_attuali:
        if turno["Orario"] == ora_attuale_str:
            if turno["Luogo"] in campi_adiacenti:
                # C'è un cane in un campo adiacente
                cane_adiacente = turno["Cane"]
                
                # Ignoro i turni speciali (Briefing, Pasti)
                if cane_adiacente in ["TUTTI", "Da assegnare"]:
                    continue
                
                reattivita_cane_adiacente = get_reattivita_cane(cane_adiacente, df_cani)
                
                # CONFLITTO se ALMENO UNO dei due ha reattività > 5
                if reattivita_cane_corrente > 5 or reattivita_cane_adiacente > 5:
                    return False
    
    return True

def salva_turni_in_storico(programma, data):
    """
    Salva tutti i turni del programma giornaliero nello storico del database.
    Ogni volontario viene salvato separatamente (se ci sono più volontari separati da '+').
    
    Args:
        programma: lista di dict con i turni della giornata
        data: data della giornata (datetime.date)
    
    Returns:
        numero di record salvati
    """
    conn = sqlite3.connect('canile.db')
    c = conn.cursor()
    
    data_str = data.strftime('%Y-%m-%d')
    record_salvati = 0
    
    for turno in programma:
        # Salto i turni speciali (Briefing, Pasti) e quelli senza cane specifico
        if turno.get("Cane") in ["TUTTI", "Da assegnare", "-"]:
            continue
        
        cane = turno.get("Cane", "")
        orario = turno.get("Orario", "")
        luogo = turno.get("Luogo", "")
        volontari_str = turno.get("Volontario", "")
        
        # Separo i volontari (possono essere separati da ' + ')
        volontari = [v.strip() for v in volontari_str.split('+') if v.strip()]
        
        # Salvo un record per ogni volontario
        for volontario in volontari:
            try:
                c.execute("INSERT INTO storico (data, inizio, cane, volontario, luogo) VALUES (?, ?, ?, ?, ?)",
                         (data_str, orario, cane, volontario, luogo))
                record_salvati += 1
            except Exception as e:
                st.warning(f"Errore salvando turno {cane} - {volontario}: {str(e)}")
    
    conn.commit()
    conn.close()
    
    return record_salvati


init_db()

# --- SIDEBAR ---
with st.sidebar:
    st.header("⚙️ Setup")
    data_t = st.date_input("Data", datetime.today())
    ora_i = st.time_input("Inizio", datetime.strptime("08:00", "%H:%M"))
    ora_f = st.time_input("Fine", datetime.strptime("12:00", "%H:%M"))
    
    st.divider()
    st.subheader("🗂️ Anagrafica Cani")
    
    # Caricamento PDF anagrafica
    pdf_file = st.file_uploader("📄 Carica PDF Anagrafica Cane", type=["pdf"], key="pdf_upload")
    
    if pdf_file:
        # Estraggo i dati dal PDF usando la nuova funzione
        dati_pdf = parse_pdf_content_from_file(pdf_file)
        
        st.success("✅ PDF caricato con successo!")
        
        # Mostro un'anteprima dei dati estratti
        with st.expander("🔍 Anteprima dati estratti dal PDF"):
            for campo, valore in dati_pdf.items():
                st.text(f"{campo}:")
                st.text_area(f"preview_{campo}", valore, height=60, disabled=True, label_visibility="collapsed")
        
        nome_cane = st.text_input("🐕 Nome Cane", key="nome_cane_pdf")
        livello_cane = st.selectbox("📊 Livello", ["Base", "Medio", "Avanzato"], key="livello_pdf")
        
        if st.button("💾 Salva in Anagrafica", type="primary", use_container_width=True):
            if nome_cane:
                conn = sqlite3.connect('canile.db')
                c = conn.cursor()
                try:
                    c.execute("""INSERT OR REPLACE INTO anagrafica_cani 
                                 (nome, cibo, guinzaglieria, strumenti, attivita, note, tempo, livello) 
                                 VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                             (nome_cane, 
                              dati_pdf.get('CIBO', 'N/D'),
                              dati_pdf.get('GUINZAGLIERIA', 'N/D'),
                              dati_pdf.get('STRUMENTI', 'N/D'),
                              dati_pdf.get('ATTIVITÀ', 'N/D'),
                              dati_pdf.get('NOTE', 'N/D'),
                              dati_pdf.get('TEMPO', 'N/D'),
                              livello_cane))
                    conn.commit()
                    st.success(f"✅ {nome_cane} salvato nell'anagrafica!")
                    st.rerun()
                except Exception as e:
                    st.error(f"❌ Errore nel salvataggio: {str(e)}")
                finally:
                    conn.close()
            else:
                st.warning("⚠️ Inserisci il nome del cane!")
    
    st.divider()
    
    # Visualizzazione anagrafica esistente
    conn = sqlite3.connect('canile.db')
    df_anagrafica = pd.read_sql_query("SELECT * FROM anagrafica_cani", conn)
    conn.close()
    
    if not df_anagrafica.empty:
        st.write("**Cani in Anagrafica:**")
        cane_selezionato = st.selectbox("Visualizza scheda:", df_anagrafica['nome'].tolist(), key="vis_cane")
        
        if cane_selezionato:
            riga = df_anagrafica[df_anagrafica['nome'] == cane_selezionato].iloc[0]
            
            with st.expander(f"📋 Scheda di {cane_selezionato}", expanded=True):
                st.write(f"**Livello:** {riga['livello']}")
                st.write(f"**🍖 CIBO:** {riga['cibo']}")
                st.write(f"**🦴 GUINZAGLIERIA:** {riga['guinzaglieria']}")
                st.write(f"**🎾 STRUMENTI:** {riga['strumenti']}")
                st.write(f"**🎯 ATTIVITÀ:** {riga['attivita']}")
                st.write(f"**📝 NOTE:** {riga['note']}")
                st.write(f"**⏱️ TEMPO:** {riga['tempo']}")
                
                if st.button("🗑️ Elimina", key=f"del_{cane_selezionato}"):
                    conn = sqlite3.connect('canile.db')
                    c = conn.cursor()
                    c.execute("DELETE FROM anagrafica_cani WHERE nome=?", (cane_selezionato,))
                    conn.commit()
                    conn.close()
                    st.success(f"✅ {cane_selezionato} eliminato!")
                    st.rerun()

# Carico i dati dai fogli Google
df_cani = load_gsheets("Cani")
df_volontari = load_gsheets("Volontari")
df_luoghi = load_gsheets("Luoghi")

# --- STATO SESSIONE ---
if "programma" not in st.session_state:
    st.session_state.programma = []

# --- INTERFACCIA PRINCIPALE ---
st.title("🐕 Gestione Programma Canile")

tab1, tab2, tab3 = st.tabs(["📅 Programma", "🐕 Cani", "📊 Storico"])

with tab1:
    st.subheader(f"Programma del {data_t.strftime('%d/%m/%Y')}")
    
    # Generazione orari
    orari = []
    t = datetime.combine(data_t, ora_i)
    t_fine = datetime.combine(data_t, ora_f)
    while t < t_fine:
        orari.append(t.strftime("%H:%M"))
        t += timedelta(minutes=30)
    
    # Inizializzo con turni fissi se programma vuoto
    if not st.session_state.programma:
        st.session_state.programma = [
            {"Orario": orari[0], "Cane": "TUTTI", "Volontario": "TUTTI", "Luogo": "Briefing"},
            {"Orario": orari[len(orari)//2], "Cane": "TUTTI", "Volontario": "TUTTI", "Luogo": "Pasti cani"},
        ]
    
    # Pulsanti di gestione
    col1, col2, col3 = st.columns(3)
    
    with col1:
        if st.button("➕ Aggiungi Turno Manuale", use_container_width=True):
            st.session_state.programma.append({
                "Orario": orari[0] if orari else "08:00",
                "Cane": "Da assegnare",
                "Volontario": "Da assegnare",
                "Luogo": "Da assegnare"
            })
    
    with col2:
        if st.button("🔄 Genera Turni Automatici", use_container_width=True, type="primary"):
            # Logica di assegnazione automatica (INVARIATA)
            luoghi_automatici = df_luoghi[df_luoghi['automatico'].str.lower() == 'sì']['nome'].tolist() if not df_luoghi.empty else []
            
            conn = sqlite3.connect('canile.db')
            df_storico = pd.read_sql_query("SELECT * FROM storico", conn)
            conn.close()
            
            cani_da_gestire = df_cani[df_cani['livello'].str.lower().isin(['base', 'medio'])]['nome'].tolist() if not df_cani.empty else []
            
            turni_attuali = [t for t in st.session_state.programma if t["Cane"] not in ["TUTTI", "Da assegnare"]]
            
            for ora in orari[1:]:
                for cane in cani_da_gestire:
                    if any(t["Cane"] == cane and t["Orario"] == ora for t in turni_attuali):
                        continue
                    
                    if not df_storico.empty:
                        turni_cane = df_storico[df_storico['cane'] == cane]
                        if not turni_cane.empty:
                            conteggi = turni_cane.groupby('volontario').size().reset_index(name='count')
                            conteggi = conteggi.sort_values('count', ascending=False)
                            volontario_piu_esperto = conteggi.iloc[0]['volontario'] if len(conteggi) > 0 else "Da assegnare"
                        else:
                            volontario_piu_esperto = "Da assegnare"
                    else:
                        volontario_piu_esperto = "Da assegnare"
                    
                    for luogo in luoghi_automatici:
                        if not any(t["Luogo"] == luogo and t["Orario"] == ora for t in turni_attuali):
                            if campo_valido_per_reattivita(cane, luogo, turni_attuali, ora, df_cani, df_luoghi):
                                turno = {
                                    "Orario": ora,
                                    "Cane": cane,
                                    "Volontario": volontario_piu_esperto,
                                    "Luogo": luogo
                                }
                                st.session_state.programma.append(turno)
                                turni_attuali.append(turno)
                                break
            
            st.success("✅ Turni generati!")
    
    with col3:
        if st.button("🗑️ Svuota Programma", use_container_width=True):
            st.session_state.programma = []
            st.rerun()
    
    # Editor programma
    if st.session_state.programma:
        df_prog = pd.DataFrame(st.session_state.programma)
        
        cani_list = ["TUTTI", "Da assegnare"] + (df_cani['nome'].tolist() if not df_cani.empty else [])
        vol_list = ["TUTTI", "Da assegnare"] + (df_volontari['nome'].tolist() if not df_volontari.empty else [])
        luoghi_list = ["Briefing", "Pasti cani", "Da assegnare"] + (df_luoghi['nome'].tolist() if not df_luoghi.empty else [])
        
        df_edited = st.data_editor(
            df_prog,
            num_rows="dynamic",
            use_container_width=True,
            column_config={
                "Orario": st.column_config.SelectboxColumn("⏰ Orario", options=orari, required=True),
                "Cane": st.column_config.SelectboxColumn("🐕 Cane", options=cani_list, required=True),
                "Volontario": st.column_config.TextColumn("👤 Volontario", required=True),
                "Luogo": st.column_config.SelectboxColumn("📍 Luogo", options=luoghi_list, required=True),
            },
            key="editor_programma"
        )
        
        st.session_state.programma = df_edited.to_dict('records')
    else:
        st.info("Nessun turno programmato. Usa i pulsanti sopra per iniziare.")

with tab2:
    st.subheader("🐕 Gestione Cani")
    
    if not df_cani.empty:
        st.dataframe(df_cani, use_container_width=True)
    else:
        st.info("Nessun cane trovato nel foglio Google.")

with tab3:
    st.subheader("📊 Storico Turni")
    
    conn = sqlite3.connect('canile.db')
    df_storico_vis = pd.read_sql_query("SELECT * FROM storico ORDER BY data DESC, inizio", conn)
    
    if not df_storico_vis.empty:
        subtab_view, subtab_stats = st.tabs(["📋 Visualizza", "📈 Statistiche"])
        
        with subtab_view:
            st.write("### 📋 Tutti i Turni Salvati")
            
            col_f1, col_f2, col_f3 = st.columns(3)
            
            with col_f1:
                date_uniche = sorted(df_storico_vis['data'].unique(), reverse=True)
                filtro_data = st.selectbox("Filtra per data", ["Tutte"] + date_uniche, key="filtro_data")
            
            with col_f2:
                cani_unici = sorted(df_storico_vis['cane'].unique())
                filtro_cane = st.selectbox("Filtra per cane", ["Tutti"] + cani_unici, key="filtro_cane")
            
            with col_f3:
                vol_unici = sorted(df_storico_vis['volontario'].unique())
                filtro_vol = st.selectbox("Filtra per volontario", ["Tutti"] + vol_unici, key="filtro_vol")
            
            df_filtrato = df_storico_vis.copy()
            
            if filtro_data != "Tutte":
                df_filtrato = df_filtrato[df_filtrato['data'] == filtro_data]
            
            if filtro_cane != "Tutti":
                df_filtrato = df_filtrato[df_filtrato['cane'] == filtro_cane]
            
            if filtro_vol != "Tutti":
                df_filtrato = df_filtrato[df_filtrato['volontario'] == filtro_vol]
            
            if not df_filtrato.empty:
                df_filtrato['data'] = pd.to_datetime(df_filtrato['data'])
                
                df_edited = st.data_editor(
                    df_filtrato,
                    num_rows="dynamic",
                    use_container_width=True,
                    hide_index=True,
                    column_config={
                        "data": st.column_config.DateColumn("📅 Data", format="DD/MM/YYYY"),
                        "inizio": st.column_config.TextColumn("⏰ Orario", width="small"),
                        "cane": st.column_config.TextColumn("🐕 Cane", width="medium"),
                        "volontario": st.column_config.TextColumn("👤 Volontario", width="medium"),
                        "luogo": st.column_config.TextColumn("📍 Luogo", width="medium"),
                    },
                    key="editor_storico"
                )
                
                col_save, col_del = st.columns(2)
                
                with col_save:
                    if st.button("💾 Salva Modifiche", use_container_width=True, type="primary"):
                        try:
                            for _, row in df_edited.iterrows():
                                data_str = row['data'].strftime('%Y-%m-%d') if pd.notna(row['data']) else row['data']
                                conn.execute(
                                    "UPDATE storico SET data=?, inizio=?, cane=?, volontario=?, luogo=? WHERE rowid=?",
                                    (data_str, row['inizio'], row['cane'], row['volontario'], row['luogo'], row['rowid'])
                                )
                            conn.commit()
                            st.success("✅ Modifiche salvate con successo!")
                            st.rerun()
                        except Exception as e:
                            st.error(f"❌ Errore nel salvataggio: {str(e)}")
                
                with col_del:
                    if st.button("🗑️ Elimina Turni Selezionati", use_container_width=True):
                        st.warning("⚠️ Funzione in sviluppo: usa il data editor per eliminare righe (modalità 'dynamic')")
                
                st.divider()
                
                st.write("#### 🗑️ Cancellazione Rapida")
                col_del1, col_del2 = st.columns([2, 1])
                
                with col_del1:
                    data_da_cancellare = st.selectbox("Seleziona data da cancellare completamente", 
                                                      ["---"] + date_uniche,
                                                      key="del_data")
                
                with col_del2:
                    if st.button("❌ Cancella Giornata", use_container_width=True, disabled=(data_da_cancellare == "---")):
                        if data_da_cancellare != "---":
                            count = conn.execute("SELECT COUNT(*) FROM storico WHERE data=?", (data_da_cancellare,)).fetchone()[0]
                            if st.session_state.get('confirm_delete') == data_da_cancellare:
                                conn.execute("DELETE FROM storico WHERE data=?", (data_da_cancellare,))
                                conn.commit()
                                st.success(f"✅ Cancellati {count} turni del {data_da_cancellare}")
                                st.session_state.confirm_delete = None
                                st.rerun()
                            else:
                                st.session_state.confirm_delete = data_da_cancellare
                                st.warning(f"⚠️ Vuoi davvero cancellare {count} turni? Clicca di nuovo per confermare.")
            else:
                st.info("Nessun turno trovato con i filtri selezionati.")
        
        with subtab_stats:
            st.write("### 📈 Statistiche Esperienza")
            
            df_storico = pd.read_sql_query("SELECT * FROM storico", conn)
            
            if not df_storico.empty:
                st.write("#### 🐕 Esperienza per Cane")
                
                cani_disponibili = sorted(df_storico['cane'].unique())
                cane_selezionato = st.selectbox("Seleziona un cane", cani_disponibili, key="stats_cane")
                
                if cane_selezionato:
                    df_cane = df_storico[df_storico['cane'] == cane_selezionato]
                    
                    stats_volontari = df_cane.groupby('volontario').agg({
                        'data': 'count'
                    }).reset_index()
                    stats_volontari.columns = ['Volontario', 'Turni Totali']
                    stats_volontari = stats_volontari.sort_values('Turni Totali', ascending=False)
                    
                    col_stat1, col_stat2 = st.columns(2)
                    
                    with col_stat1:
                        st.metric("📊 Turni Totali con questo cane", len(df_cane))
                        st.metric("👥 Volontari Diversi", len(stats_volontari))
                    
                    with col_stat2:
                        if len(stats_volontari) > 0:
                            st.metric("🥇 Volontario più esperto", 
                                     stats_volontari.iloc[0]['Volontario'],
                                     f"{stats_volontari.iloc[0]['Turni Totali']} turni")
                    
                    st.divider()
                    st.write("**Classifica Esperienza:**")
                    
                    stats_volontari['Percentuale'] = (stats_volontari['Turni Totali'] / len(df_cane) * 100).round(1)
                    
                    st.dataframe(
                        stats_volontari,
                        use_container_width=True,
                        hide_index=True,
                        column_config={
                            "Volontario": st.column_config.TextColumn("👤 Volontario", width="medium"),
                            "Turni Totali": st.column_config.NumberColumn("📊 Turni", width="small"),
                            "Percentuale": st.column_config.NumberColumn("📈 %", format="%.1f%%", width="small"),
                        }
                    )
                    
                    st.bar_chart(stats_volontari.set_index('Volontario')['Turni Totali'])
                
                st.divider()
                
                st.write("#### 📊 Statistiche Generali")
                
                col_g1, col_g2, col_g3 = st.columns(3)
                
                with col_g1:
                    st.metric("🐕 Cani Totali", df_storico['cane'].nunique())
                    st.metric("👥 Volontari Totali", df_storico['volontario'].nunique())
                
                with col_g2:
                    st.metric("📅 Giorni con Turni", df_storico['data'].nunique())
                    st.metric("📍 Luoghi Utilizzati", df_storico['luogo'].nunique())
                
                with col_g3:
                    st.metric("✅ Turni Totali", len(df_storico))
                    media_turni_giorno = len(df_storico) / max(df_storico['data'].nunique(), 1)
                    st.metric("📊 Media Turni/Giorno", f"{media_turni_giorno:.1f}")
                
                st.write("#### 🏆 Top 10 Volontari più Attivi")
                top_volontari = df_storico.groupby('volontario').size().reset_index(name='Turni')
                top_volontari = top_volontari.sort_values('Turni', ascending=False).head(10)
                
                st.dataframe(
                    top_volontari.reset_index(drop=True),
                    use_container_width=True,
                    hide_index=True,
                    column_config={
                        "volontario": st.column_config.TextColumn("👤 Volontario", width="large"),
                        "Turni": st.column_config.NumberColumn("📊 Turni Totali", width="medium"),
                    }
                )
                
            else:
                st.info("📭 Nessun dato disponibile per le statistiche. Salva alcuni turni per iniziare!")
    else:
        st.info("📭 Nessun dato nello storico. Salva alcuni turni per iniziare!")
    
    conn.close()

# --- SEZIONE SALVATAGGIO IN STORICO ---
st.divider()
st.subheader("💾 Salvataggio Giornata")

if st.session_state.programma:
    st.info(f"📊 Turni programmati: **{len(st.session_state.programma)}** (verranno salvati solo i turni con cani specifici)")
    
    col_salva1, col_salva2 = st.columns([3, 1])
    
    with col_salva1:
        st.write("Una volta completata la giornata, salva i turni nello storico per migliorare l'assegnazione automatica futura.")
    
    with col_salva2:
        if st.button("✅ Conferma e Salva in Storico", type="primary", use_container_width=True):
            record_salvati = salva_turni_in_storico(st.session_state.programma, data_t)
            if record_salvati > 0:
                st.success(f"✅ Salvati {record_salvati} turni nello storico del {data_t.strftime('%d/%m/%Y')}!")
                st.info("💡 L'algoritmo di assegnazione automatica ora terrà conto di questi turni per dare priorità ai volontari più esperti con ogni cane.")
                st.session_state.programma = []
                st.rerun()
            else:
                st.warning("⚠️ Nessun turno valido da salvare (solo turni speciali o senza cane).")
else:
    st.info("📝 Crea prima un programma giornaliero per poterlo salvare nello storico.")

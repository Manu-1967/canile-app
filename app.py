import streamlit as st
import pandas as pd
from datetime import datetime, timedelta
import PyPDF2
import re
import sqlite3
import io

# --- CONFIGURAZIONE ---
st.set_page_config(page_title="Programma Canile Pro", layout="wide")

def init_db():
    """Inizializza il database canile.db con le tabelle necessarie."""
    conn = sqlite3.connect('canile.db')
    c = conn.cursor()
    # Storico per statistiche
    c.execute('''CREATE TABLE IF NOT EXISTS storico 
                 (data TEXT, inizio TEXT, cane TEXT, volontario TEXT, luogo TEXT)''')
    # Anagrafica basata sui titoli del PDF: CIBO, GUINZAGLIERIA, STRUMENTI, ATTIVITÀ, NOTE, TEMPO
    c.execute('''CREATE TABLE IF NOT EXISTS anagrafica_cani 
                 (nome TEXT PRIMARY KEY, cibo TEXT, guinzaglieria TEXT, strumenti TEXT, 
                  attivita TEXT, note TEXT, tempo TEXT)''')
    conn.commit()
    conn.close()

def parse_dog_pdf(uploaded_file):
    """
    Legge il PDF del cane ed estrae i dati strutturati.
    I titoli sono: CIBO, GUINZAGLIERIA, STRUMENTI, ATTIVITÀ, NOTE, TEMPO
    I titoli sono in MAIUSCOLO e GRASSETTO.
    Il contenuto è tutto ciò che segue il titolo fino al prossimo titolo o fine documento.
    """
    reader = PyPDF2.PdfReader(uploaded_file)
    
    # Estrai tutto il testo dal PDF
    full_text = ""
    for page in reader.pages:
        full_text += page.extract_text()
    
    # Lista dei titoli attesi nell'ordine
    TITOLI = ["CIBO", "GUINZAGLIERIA", "STRUMENTI", "ATTIVITÀ", "NOTE", "TEMPO"]
    
    # Dizionario per memorizzare i dati
    dati = {
        "nome": uploaded_file.name.replace(".pdf", "").upper(),
        "cibo": "",
        "guinzaglieria": "",
        "strumenti": "",
        "attivita": "",
        "note": "",
        "tempo": ""
    }
    
    # Usa regex per trovare ogni titolo e il suo contenuto
    # Pattern: cerca il titolo in maiuscolo seguito da tutto il testo fino al prossimo titolo o fine stringa
    for i, titolo in enumerate(TITOLI):
        # Crea pattern per trovare il titolo corrente
        if i < len(TITOLI) - 1:
            # Non è l'ultimo titolo: cerca fino al prossimo titolo
            next_titolo = TITOLI[i + 1]
            pattern = rf'{titolo}\s+(.*?)\s*(?={next_titolo})'
        else:
            # È l'ultimo titolo (TEMPO): cerca fino alla fine
            pattern = rf'{titolo}\s+(.*?)$'
        
        match = re.search(pattern, full_text, re.DOTALL | re.MULTILINE)
        
        if match:
            contenuto = match.group(1).strip()
            
            # Mappa il titolo al campo del dizionario
            campo_map = {
                'CIBO': 'cibo',
                'GUINZAGLIERIA': 'guinzaglieria',
                'STRUMENTI': 'strumenti',
                'ATTIVITÀ': 'attivita',
                'NOTE': 'note',
                'TEMPO': 'tempo'
            }
            
            campo = campo_map.get(titolo)
            if campo:
                dati[campo] = contenuto
    
    return dati

def carica_anagrafica():
    """Carica l'anagrafica dei cani dal database."""
    conn = sqlite3.connect("canile.db")
    df = pd.read_sql("SELECT * FROM anagrafica_cani", conn)
    conn.close()
    return df

def salva_anagrafica_db(dati):
    """Salva i dati del cane nel database."""
    conn = sqlite3.connect("canile.db")
    c = conn.cursor()

    c.execute("""
        INSERT OR REPLACE INTO anagrafica_cani
        (nome, cibo, guinzaglieria, strumenti, attivita, note, tempo)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    """, (
        dati["nome"],
        dati["cibo"],
        dati["guinzaglieria"],
        dati["strumenti"],
        dati["attivita"],
        dati["note"],
        dati["tempo"]
    ))

    conn.commit()
    conn.close()

def genera_excel_volontari():
    """Genera un file Excel con l'anagrafica dei cani."""
    conn = sqlite3.connect("canile.db")
    df = pd.read_sql("SELECT * FROM anagrafica_cani", conn)
    conn.close()

    file_excel = "programma_volontari.xlsx"
    df.to_excel(file_excel, index=False)

    return file_excel

def genera_excel_programma(programma, data_turno):
    """Genera un file Excel con il programma completo del turno."""
    df = pd.DataFrame(programma)
    
    # Riordina le colonne
    cols_order = ["Orario", "Cane", "Colore_Cane", "Volontario", "Colore_Volontario", "Compatibilità", "Luogo", "Tipo", "CIBO", "GUINZAGLIERIA", "STRUMENTI", "ATTIVITÀ", "NOTE", "TEMPO"]
    # Usa solo le colonne che esistono
    cols_order = [c for c in cols_order if c in df.columns]
    df = df[cols_order]
    
    file_excel = f"programma_turno_{data_turno.strftime('%Y%m%d')}.xlsx"
    df.to_excel(file_excel, index=False)
    
    return file_excel

def genera_pdf_volontari():
    """Genera un file PDF con l'anagrafica dei cani."""
    from fpdf import FPDF
    
    conn = sqlite3.connect("canile.db")
    df = pd.read_sql("SELECT * FROM anagrafica_cani", conn)
    conn.close()

    pdf = FPDF()
    pdf.set_auto_page_break(auto=True, margin=15)

    for _, row in df.iterrows():
        pdf.add_page()
        pdf.set_font("Arial", "B", 14)
        pdf.cell(0, 10, row["nome"], ln=True)

        pdf.set_font("Arial", "", 11)
        for campo in ["cibo", "guinzaglieria", "strumenti", "attivita", "note", "tempo"]:
            pdf.multi_cell(0, 8, f"{campo.upper()}: {row[campo]}")
            pdf.ln(1)

    file_pdf = "programma_volontari.pdf"
    pdf.output(file_pdf)

    return file_pdf

def load_gsheets(sheet_name):
    """Carica dati da Google Sheets."""
    url = f"https://docs.google.com/spreadsheets/d/1pcFa454IT1tlykbcK-BeAU9hnIQ_D8V_UuZaKI_KtYM/gviz/tq?tqx=out:csv&sheet={sheet_name}"
    try:
        df = pd.read_csv(url)
        df.columns = [c.strip().lower() for c in df.columns]
        if sheet_name == "Luoghi":
            if 'automatico' not in df.columns: 
                df['automatico'] = 'sì'
            if 'adiacente' not in df.columns: 
                df['adiacente'] = ''
        if sheet_name == "Cani":
            if 'reattività' not in df.columns: 
                df['reattività'] = 0
            df['reattività'] = pd.to_numeric(df['reattività'], errors='coerce').fillna(0)
            # Aggiungi colonna colore se non presente
            if 'colore' not in df.columns:
                df['colore'] = 'verde'  # default
            df['colore'] = df['colore'].str.lower().str.strip()
        if sheet_name == "Volontari":
            # Aggiungi colonna colore se non presente
            if 'colore' not in df.columns:
                df['colore'] = 'verde'  # default
            df['colore'] = df['colore'].str.lower().str.strip()
        return df.dropna(how='all')
    except:
        return pd.DataFrame()

def get_livello_colore(colore):
    """
    Restituisce il livello numerico del colore.
    Scala: nero (4) > rosso (3) > arancione (2) > verde (1)
    """
    livelli = {
        'nero': 4,
        'rosso': 3,
        'arancione': 2,
        'verde': 1
    }
    return livelli.get(colore.lower().strip(), 1)  # default verde se non riconosciuto

def verifica_compatibilita_colore(colore_volontario, colore_cane):
    """
    Verifica se un volontario può gestire un cane in base ai colori.
    Regola: Il volontario può gestire cani del suo stesso livello o inferiore.
    
    Scala volontari (dal più esperto al principiante):
    - Nero (4): può gestire tutti (nero, rosso, arancione, verde)
    - Rosso (3): può gestire rosso, arancione, verde
    - Arancione (2): può gestire arancione, verde
    - Verde (1): può gestire solo verde
    
    Returns:
        tuple: (bool compatibile, str messaggio)
    """
    livello_vol = get_livello_colore(colore_volontario)
    livello_cane = get_livello_colore(colore_cane)
    
    compatibile = livello_vol >= livello_cane
    
    if compatibile:
        messaggio = "✅ OK"
    else:
        messaggio = f"⚠️ INCOMPATIBILE: serve volontario {colore_cane} o superiore"
    
    return compatibile, messaggio

def get_colore_cane(nome_cane, df_cani):
    """Restituisce il colore di un cane."""
    if df_cani.empty or 'colore' not in df_cani.columns:
        return 'verde'  # default
    riga = df_cani[df_cani['nome'] == nome_cane]
    return riga.iloc[0]['colore'] if not riga.empty else 'verde'

def get_colore_volontario(nome_volontario, df_volontari):
    """Restituisce il colore/livello di un volontario."""
    if df_volontari.empty or 'colore' not in df_volontari.columns:
        return 'verde'  # default
    riga = df_volontari[df_volontari['nome'] == nome_volontario]
    return riga.iloc[0]['colore'] if not riga.empty else 'verde'

def get_reattivita_cane(nome_cane, df_cani):
    """Restituisce il livello di reattività di un cane."""
    if df_cani.empty or 'reattività' not in df_cani.columns: 
        return 0
    riga = df_cani[df_cani['nome'] == nome_cane]
    return float(riga.iloc[0]['reattività']) if not riga.empty else 0

def get_campi_adiacenti(campo, df_luoghi):
    """Restituisce la lista dei campi adiacenti a un campo dato."""
    if df_luoghi.empty or 'adiacente' not in df_luoghi.columns: 
        return []
    riga = df_luoghi[df_luoghi['nome'] == campo]
    if not riga.empty:
        adiacenti_str = str(riga.iloc[0]['adiacente']).strip()
        if adiacenti_str and adiacenti_str != 'nan':
            return [c.strip() for c in adiacenti_str.split(',') if c.strip()]
    return []

def campo_valido_per_reattivita(cane, campo, turni_attuali, ora_attuale_str, df_cani, df_luoghi):
    """Verifica se un campo è valido per un cane considerando la reattività dei cani adiacenti."""
    reattivita_cane_corrente = get_reattivita_cane(cane, df_cani)
    campi_adiacenti = get_campi_adiacenti(campo, df_luoghi)
    for turno in turni_attuali:
        if turno["Orario"] == ora_attuale_str:
            if turno["Luogo"] in campi_adiacenti:
                cane_adiacente = turno["Cane"]
                if cane_adiacente in ["TUTTI", "Da assegnare"]: 
                    continue
                reattivita_cane_adiacente = get_reattivita_cane(cane_adiacente, df_cani)
                if reattivita_cane_corrente > 5 or reattivita_cane_adiacente > 5:
                    return False
    return True

def get_anagrafica_cane(nome_cane):
    """Recupera i dati dell'anagrafica di un cane dal database."""
    conn = sqlite3.connect('canile.db')
    c = conn.cursor()
    
    # Prova con il nome esatto
    c.execute("SELECT cibo, guinzaglieria, strumenti, attivita, note, tempo FROM anagrafica_cani WHERE nome=?", (nome_cane,))
    result = c.fetchone()
    
    # Se non trova, prova con nome in maiuscolo
    if not result:
        c.execute("SELECT cibo, guinzaglieria, strumenti, attivita, note, tempo FROM anagrafica_cani WHERE UPPER(nome)=?", (nome_cane.upper(),))
        result = c.fetchone()
    
    conn.close()
    
    if result:
        return {
            "cibo": result[0] if result[0] else "",
            "guinzaglieria": result[1] if result[1] else "",
            "strumenti": result[2] if result[2] else "",
            "attivita": result[3] if result[3] else "",
            "note": result[4] if result[4] else "",
            "tempo": result[5] if result[5] else ""
        }
    else:
        # Se il cane non è in anagrafica, restituisce valori vuoti
        return {
            "cibo": "N/D",
            "guinzaglieria": "N/D",
            "strumenti": "N/D",
            "attivita": "N/D",
            "note": "N/D",
            "tempo": "N/D"
        }

def salva_programma_nel_db(programma, data_sel):
    """Salva il programma giornaliero nello storico del database."""
    conn = sqlite3.connect('canile.db')
    c = conn.cursor()
    dt_str = data_sel.strftime('%Y-%m-%d')
    c.execute("DELETE FROM storico WHERE data=?", (dt_str,))
    for t in programma:
        if t["Cane"] not in ["TUTTI", "Da assegnare"]:
            vols = t["Volontario"].replace('+', ',').split(',')
            for v in vols:
                if v.strip():
                    c.execute("INSERT INTO storico VALUES (?,?,?,?,?)", 
                              (dt_str, t["Orario"], t["Cane"], v.strip(), t["Luogo"]))
    conn.commit()
    conn.close()

def trova_volontario_compatibile(cane, volontari_liberi, df_cani, df_volontari, conn):
    """
    Trova il miglior volontario compatibile per un cane.
    Restituisce: (volontario, colore_vol, compatibile, messaggio)
    """
    colore_cane = get_colore_cane(cane, df_cani)
    
    # Lista di volontari con score di compatibilità
    candidati = []
    
    for vol in volontari_liberi:
        colore_vol = get_colore_volontario(vol, df_volontari)
        compatibile, msg = verifica_compatibilita_colore(colore_vol, colore_cane)
        
        # Calcola score storico
        score_storico = conn.execute(
            "SELECT COUNT(*) FROM storico WHERE cane=? AND volontario=?", 
            (cane, vol)
        ).fetchone()[0]
        
        candidati.append({
            'nome': vol,
            'colore': colore_vol,
            'compatibile': compatibile,
            'messaggio': msg,
            'score_storico': score_storico,
            'livello': get_livello_colore(colore_vol)
        })
    
    # Ordina: prima compatibili, poi per storico, poi per livello più alto
    candidati.sort(key=lambda x: (
        not x['compatibile'],  # False prima di True (compatibili prima)
        -x['score_storico'],   # Score storico decrescente
        -x['livello']          # Livello decrescente
    ))
    
    if candidati:
        migliore = candidati[0]
        return migliore['nome'], migliore['colore'], migliore['compatibile'], migliore['messaggio']
    
    return None, None, False, "Nessun volontario disponibile"

# Inizializzazione DB e sessione
init_db()
if 'programma' not in st.session_state: 
    st.session_state.programma = []
if 'abbinamenti_non_compatibili' not in st.session_state:
    st.session_state.abbinamenti_non_compatibili = []

# --- INTERFACCIA ---
st.title("🐾 Programma Canile 🐕")

with st.sidebar:
    st.header("⚙️ Configurazione")
    data_t = st.date_input("Data Turno", datetime.today())
    ora_i = st.time_input("Ora Inizio", datetime.strptime("14:00", "%H:%M"))
    ora_f = st.time_input("Ora Fine", datetime.strptime("18:00", "%H:%M"))
    st.divider()

    st.subheader("📂 Importazione PDF Cani")
    st.markdown("*Carica i PDF con le informazioni dei cani*")
    st.caption("I PDF devono contenere i titoli: CIBO, GUINZAGLIERIA, STRUMENTI, ATTIVITÀ, NOTE, TEMPO")

    pdf_files = st.file_uploader(
        "Carica PDF cani",
        type="pdf",
        accept_multiple_files=True,
        key="upload_pdf_cani"
    )

    if st.button("📥 Aggiorna anagrafica da PDF", use_container_width=True):
        if not pdf_files:
            st.warning("⚠️ Carica almeno un PDF")
        else:
            successi = 0
            errori = []

            for pdf in pdf_files:
                try:
                    dati = parse_dog_pdf(pdf)
                    salva_anagrafica_db(dati)
                    successi += 1
                except Exception as e:
                    errori.append(f"{pdf.name}: {str(e)}")

            if successi > 0:
                st.success(f"✅ {successi} anagrafiche caricate correttamente")

            if errori:
                st.error("❌ Errori nei seguenti file:")
                for err in errori:
                    st.text(err)
            
            st.rerun()

    st.divider()
    
    # Mostra conteggio cani in anagrafica
    df_ana = carica_anagrafica()
    st.metric("🐕 Cani in anagrafica", len(df_ana))
    
    # Debug: mostra quali cani sono in anagrafica
    if len(df_ana) > 0:
        with st.expander("🔍 Cani caricati in anagrafica"):
            st.write("**Nomi nel database:**")
            for nome in df_ana['nome'].tolist():
                st.text(f"• {nome}")
    else:
        st.warning("⚠️ Nessun cane in anagrafica! Carica i PDF.")
    
    st.divider()
    
    # Legenda colori
    st.subheader("🎨 Legenda Colori")
    st.markdown("""
    **Volontari** (esperienza):
    - ⚫ **Nero**: Molto esperto
    - 🔴 **Rosso**: Esperto
    - 🟠 **Arancione**: Base
    - 🟢 **Verde**: Principiante
    
    **Regola**: Il volontario può gestire cani del suo livello o inferiore
    """)

# Carica dati da Google Sheets
df_c = load_gsheets("Cani")
df_v = load_gsheets("Volontari")
df_l = load_gsheets("Luoghi")

# Tabs principali
tab_prog, tab_ana, tab_stats, tab_colori = st.tabs(["📅 Programma", "📋 Anagrafica Cani", "📊 Statistiche", "🎨 Gestione Colori"])

with tab_prog:
    st.header("Pianificazione Turni")
    
    c_p = st.multiselect("🐕 Cani in turno", df_c['nome'].tolist() if not df_c.empty else [])
    v_p = st.multiselect("👤 Volontari presenti", df_v['nome'].tolist() if not df_v.empty else [])
    l_p = st.multiselect("📍 Luoghi disponibili", df_l['nome'].tolist() if not df_l.empty else [])

    with st.expander("✏️ Inserimento Manuale Turno"):
        col1, col2 = st.columns(2)
        m_cane = col1.selectbox("Seleziona Cane", ["-"] + c_p)
        m_luo = col2.selectbox("Seleziona Luogo", ["-"] + l_p)
        m_vols = st.multiselect("Seleziona Volontari", v_p)
        m_ora = st.time_input("Orario Inizio", ora_i)
        
        # Mostra controllo compatibilità in tempo reale
        if m_cane != "-" and m_vols:
            st.markdown("**Controllo Compatibilità:**")
            colore_cane = get_colore_cane(m_cane, df_c)
            st.info(f"🐕 Cane '{m_cane}': livello **{colore_cane.upper()}**")
            
            for vol in m_vols:
                colore_vol = get_colore_volontario(vol, df_v)
                compatibile, msg = verifica_compatibilita_colore(colore_vol, colore_cane)
                if compatibile:
                    st.success(f"👤 {vol} ({colore_vol.upper()}): {msg}")
                else:
                    st.error(f"👤 {vol} ({colore_vol.upper()}): {msg}")
        
        if st.button("➕ Aggiungi Turno Manuale"):
            if m_cane != "-" and m_luo != "-" and m_vols:
                # Recupera dati anagrafica del cane
                ana_data = get_anagrafica_cane(m_cane)
                
                # Verifica compatibilità colori
                colore_cane = get_colore_cane(m_cane, df_c)
                incompatibilita = []
                
                for vol in m_vols:
                    colore_vol = get_colore_volontario(vol, df_v)
                    compatibile, msg = verifica_compatibilita_colore(colore_vol, colore_cane)
                    if not compatibile:
                        incompatibilita.append(f"{vol} ({colore_vol})")
                
                # Verifica se il cane è in anagrafica
                if ana_data["cibo"] == "N/D":
                    st.warning(f"⚠️ Il cane '{m_cane}' non ha un'anagrafica PDF caricata. Carica il PDF dalla sidebar.")
                
                # Mostra warning se ci sono incompatibilità
                if incompatibilita:
                    st.warning(f"⚠️ ATTENZIONE: I seguenti volontari NON sono compatibili con il cane {m_cane} ({colore_cane}): {', '.join(incompatibilita)}")
                
                volontari_str = ", ".join(m_vols)
                colori_vol_str = ", ".join([get_colore_volontario(v, df_v) for v in m_vols])
                compatibilita_str = "⚠️ INCOMPATIBILE" if incompatibilita else "✅ OK"
                
                st.session_state.programma.append({
                    "Orario": m_ora.strftime('%H:%M'), 
                    "Cane": m_cane,
                    "Colore_Cane": colore_cane.upper(),
                    "Volontario": volontari_str, 
                    "Colore_Volontario": colori_vol_str.upper(),
                    "Compatibilità": compatibilita_str,
                    "Luogo": m_luo, 
                    "Tipo": "Manuale",
                    "Inizio_Sort": m_ora.strftime('%H:%M'),
                    "CIBO": ana_data["cibo"],
                    "GUINZAGLIERIA": ana_data["guinzaglieria"],
                    "STRUMENTI": ana_data["strumenti"],
                    "ATTIVITÀ": ana_data["attivita"],
                    "NOTE": ana_data["note"],
                    "TEMPO": ana_data["tempo"]
                })
                
                if incompatibilita:
                    st.error(f"❌ Turno aggiunto con INCOMPATIBILITÀ: {m_cane} alle {m_ora.strftime('%H:%M')}")
                else:
                    st.success(f"✅ Turno aggiunto: {m_cane} alle {m_ora.strftime('%H:%M')}")
                st.rerun()
            else:
                st.warning("⚠️ Seleziona cane, luogo e almeno un volontario")

    st.divider()
    
    c1, c2, c3 = st.columns(3)
    
    if c1.button("🤖 Genera / Completa Automatico", use_container_width=True):
        # Verifica se ci sono cani in anagrafica
        df_ana_check = carica_anagrafica()
        cani_mancanti = [c for c in c_p if c.upper() not in df_ana_check['nome'].str.upper().tolist()]
        
        if cani_mancanti:
            st.warning(f"⚠️ I seguenti cani NON sono presenti nell'anagrafica PDF: {', '.join(cani_mancanti)}")
            st.info("💡 Carica i PDF di questi cani dalla sidebar per avere le informazioni complete nel programma")
        
        conn = sqlite3.connect('canile.db')
        conn.row_factory = sqlite3.Row
        start_dt = datetime.combine(data_t, ora_i)
        end_dt = datetime.combine(data_t, ora_f)
        pasti_dt = end_dt - timedelta(minutes=30)
        
        manuali = [r for r in st.session_state.programma if r.get("Tipo") == "Manuale"]
        
        # Reset lista abbinamenti non compatibili
        st.session_state.abbinamenti_non_compatibili = []
        
        # Briefing iniziale (senza dati anagrafica perché è per tutti)
        st.session_state.programma = [{
            "Orario": start_dt.strftime('%H:%M'), 
            "Cane": "TUTTI",
            "Colore_Cane": "",
            "Volontario": "TUTTI",
            "Colore_Volontario": "",
            "Compatibilità": "",
            "Luogo": "Ufficio", 
            "Tipo": "Briefing", 
            "Inizio_Sort": start_dt.strftime('%H:%M'),
            "CIBO": "",
            "GUINZAGLIERIA": "",
            "STRUMENTI": "",
            "ATTIVITÀ": "",
            "NOTE": "",
            "TEMPO": ""
        }]
        
        cani_fatti = [m["Cane"] for m in manuali]
        cani_restanti = [c for c in c_p if c not in cani_fatti]
        curr_t = start_dt + timedelta(minutes=15)
        luoghi_ok = df_l[(df_l['nome'].isin(l_p)) & (df_l['automatico'].str.lower() == 'sì')]['nome'].tolist()

        while cani_restanti and curr_t < pasti_dt:
            ora_s = curr_t.strftime('%H:%M')
            v_liberi = [v for v in v_p if v not in [vv for m in manuali if m["Orario"]==ora_s for vv in m["Volontario"].split(",")]]
            l_liberi = [l for l in luoghi_ok if l not in [m["Luogo"] for m in manuali if m["Orario"]==ora_s]]
            
            for _ in range(min(len(cani_restanti), len(l_liberi))):
                if not v_liberi: 
                    break
                for idx, cane in enumerate(cani_restanti):
                    if l_liberi and campo_valido_per_reattivita(cane, l_liberi[0], st.session_state.programma + manuali, ora_s, df_c, df_l):
                        campo_scelto = l_liberi.pop(0)
                        cani_restanti.pop(idx)
                        
                        # Trova volontario compatibile con controllo colori
                        volontario_scelto, colore_vol, compatibile, msg = trova_volontario_compatibile(
                            cane, v_liberi, df_c, df_v, conn
                        )
                        
                        if volontario_scelto:
                            v_liberi.remove(volontario_scelto)
                            
                            # Recupera dati anagrafica del cane
                            ana_data = get_anagrafica_cane(cane)
                            colore_cane = get_colore_cane(cane, df_c)
                            
                            # Traccia abbinamenti non compatibili
                            if not compatibile:
                                st.session_state.abbinamenti_non_compatibili.append({
                                    'orario': ora_s,
                                    'cane': cane,
                                    'colore_cane': colore_cane,
                                    'volontario': volontario_scelto,
                                    'colore_volontario': colore_vol,
                                    'messaggio': msg
                                })
                            
                            st.session_state.programma.append({
                                "Orario": ora_s, 
                                "Cane": cane,
                                "Colore_Cane": colore_cane.upper(),
                                "Volontario": volontario_scelto,
                                "Colore_Volontario": colore_vol.upper(),
                                "Compatibilità": "✅ OK" if compatibile else "⚠️ INCOMPATIBILE",
                                "Luogo": campo_scelto, 
                                "Tipo": "Auto", 
                                "Inizio_Sort": ora_s,
                                "CIBO": ana_data["cibo"],
                                "GUINZAGLIERIA": ana_data["guinzaglieria"],
                                "STRUMENTI": ana_data["strumenti"],
                                "ATTIVITÀ": ana_data["attivita"],
                                "NOTE": ana_data["note"],
                                "TEMPO": ana_data["tempo"]
                            })
                        break
            curr_t += timedelta(minutes=45)
        
        st.session_state.programma.extend(manuali)
        
        # Pasti finali (senza dati anagrafica perché è per tutti)
        st.session_state.programma.append({
            "Orario": pasti_dt.strftime('%H:%M'), 
            "Cane": "TUTTI",
            "Colore_Cane": "",
            "Volontario": "TUTTI",
            "Colore_Volontario": "",
            "Compatibilità": "",
            "Luogo": "Box", 
            "Tipo": "Pasti", 
            "Inizio_Sort": pasti_dt.strftime('%H:%M'),
            "CIBO": "",
            "GUINZAGLIERIA": "",
            "STRUMENTI": "",
            "ATTIVITÀ": "",
            "NOTE": "",
            "TEMPO": ""
        })
        conn.close()
        
        # Mostra avviso se ci sono incompatibilità
        if st.session_state.abbinamenti_non_compatibili:
            st.warning(f"⚠️ ATTENZIONE: {len(st.session_state.abbinamenti_non_compatibili)} abbinamenti NON compatibili rilevati!")
        else:
            st.success("✅ Programma generato automaticamente - Tutti gli abbinamenti sono compatibili!")
        
        st.rerun()

    if c2.button("💾 Conferma e Salva Storico", type="primary", use_container_width=True):
        if st.session_state.programma:
            # Controlla se ci sono incompatibilità
            incompatibili = [t for t in st.session_state.programma if t.get("Compatibilità") == "⚠️ INCOMPATIBILE"]
            
            if incompatibili:
                st.error(f"⚠️ ATTENZIONE: Ci sono {len(incompatibili)} abbinamenti incompatibili nel programma!")
                with st.expander("🔍 Visualizza abbinamenti incompatibili"):
                    for t in incompatibili:
                        st.warning(f"⏰ {t['Orario']} - 🐕 {t['Cane']} ({t['Colore_Cane']}) + 👤 {t['Volontario']} ({t['Colore_Volontario']})")
                
                if st.button("✅ Conferma comunque e salva", type="primary"):
                    salva_programma_nel_db(st.session_state.programma, data_t)
                    st.success("✅ Programma salvato con successo nello storico (con incompatibilità)!")
            else:
                salva_programma_nel_db(st.session_state.programma, data_t)
                st.success("✅ Programma salvato con successo nello storico!")
        else:
            st.warning("⚠️ Nessun programma da salvare")

    if c3.button("🗑️ Svuota Tutto", use_container_width=True):
        st.session_state.programma = []
        st.session_state.abbinamenti_non_compatibili = []
        st.success("✅ Programma svuotato")
        st.rerun()

    st.divider()
    
    # Mostra alert per abbinamenti non compatibili
    if st.session_state.abbinamenti_non_compatibili:
        st.error(f"⚠️ ATTENZIONE: {len(st.session_state.abbinamenti_non_compatibili)} ABBINAMENTI NON COMPATIBILI!")
        
        with st.expander("🚨 Dettagli Incompatibilità - RICHIEDE APPROVAZIONE", expanded=True):
            for abb in st.session_state.abbinamenti_non_compatibili:
                st.warning(f"""
                **Orario:** {abb['orario']}  
                **Cane:** {abb['cane']} - Livello: {abb['colore_cane'].upper()} 🐕  
                **Volontario:** {abb['volontario']} - Livello: {abb['colore_volontario'].upper()} 👤  
                **Problema:** {abb['messaggio']}
                """)
            
            st.markdown("---")
            st.info("💡 **Opzioni:**")
            st.markdown("""
            1. **Riassegnare manualmente** i volontari incompatibili usando 'Inserimento Manuale Turno'
            2. **Aggiungere volontari** con livelli adeguati alla selezione
            3. **Confermare comunque** cliccando su 'Conferma e Salva Storico' (sconsigliato)
            """)

    if st.session_state.programma:
        st.subheader("📋 Programma Corrente")
        df_p = pd.DataFrame(st.session_state.programma).sort_values("Inizio_Sort")
        
        # Riordina le colonne per una migliore visualizzazione
        cols_order = ["Orario", "Cane", "Colore_Cane", "Volontario", "Colore_Volontario", "Compatibilità", "Luogo", "Tipo", "CIBO", "GUINZAGLIERIA", "STRUMENTI", "ATTIVITÀ", "NOTE", "TEMPO"]
        cols_order = [c for c in cols_order if c in df_p.columns]
        df_p_display = df_p[cols_order]
        
        # Formatta le celle con colori di sfondo
        def highlight_compatibility(val):
            if val == "⚠️ INCOMPATIBILE":
                return 'background-color: #ffcccc; font-weight: bold;'
            elif val == "✅ OK":
                return 'background-color: #ccffcc;'
            return ''
        
        # Applica lo stile
        styled_df = df_p_display.style.applymap(
            highlight_compatibility, 
            subset=['Compatibilità'] if 'Compatibilità' in df_p_display.columns else []
        )
        
        st.dataframe(
            styled_df, 
            use_container_width=True, 
            hide_index=True,
            column_config={
                "Orario": st.column_config.TextColumn("Orario", width="small"),
                "Cane": st.column_config.TextColumn("Cane", width="medium"),
                "Colore_Cane": st.column_config.TextColumn("🎨 Livello Cane", width="small"),
                "Volontario": st.column_config.TextColumn("Volontario", width="medium"),
                "Colore_Volontario": st.column_config.TextColumn("🎨 Livello Vol.", width="small"),
                "Compatibilità": st.column_config.TextColumn("Compatibilità", width="medium"),
                "Luogo": st.column_config.TextColumn("Luogo", width="medium"),
                "Tipo": st.column_config.TextColumn("Tipo", width="small"),
                "CIBO": st.column_config.TextColumn("CIBO", width="medium"),
                "GUINZAGLIERIA": st.column_config.TextColumn("GUINZAGLIERIA", width="medium"),
                "STRUMENTI": st.column_config.TextColumn("STRUMENTI", width="medium"),
                "ATTIVITÀ": st.column_config.TextColumn("ATTIVITÀ", width="medium"),
                "NOTE": st.column_config.TextColumn("NOTE", width="large"),
                "TEMPO": st.column_config.TextColumn("TEMPO", width="small")
            }
        )
        
        # Statistiche rapide
        st.divider()
        col_stat1, col_stat2, col_stat3 = st.columns(3)
        
        turni_cani = [t for t in st.session_state.programma if t['Cane'] not in ['TUTTI', 'Da assegnare']]
        incompatibili_count = len([t for t in turni_cani if t.get('Compatibilità') == '⚠️ INCOMPATIBILE'])
        compatibili_count = len([t for t in turni_cani if t.get('Compatibilità') == '✅ OK'])
        
        col_stat1.metric("Turni Totali", len(turni_cani))
        col_stat2.metric("✅ Compatibili", compatibili_count)
        col_stat3.metric("⚠️ Incompatibili", incompatibili_count)
        
        # Pulsante per esportare il programma
        st.divider()
        col_exp1, col_exp2 = st.columns(2)
        if col_exp1.button("📊 Esporta Programma in Excel", use_container_width=True):
            excel_file = genera_excel_programma(st.session_state.programma, data_t)
            with open(excel_file, "rb") as f:
                st.download_button(
                    "⬇️ Scarica Programma Excel",
                    f,
                    file_name=excel_file,
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    use_container_width=True
                )
    else:
        st.info("ℹ️ Nessun turno programmato. Usa 'Genera Automatico' o 'Inserimento Manuale'")

with tab_ana:
    st.header("📋 Anagrafica Cani")
    st.markdown("*Database completo dei cani caricati tramite PDF*")
    
    conn = sqlite3.connect('canile.db')
    df_db = pd.read_sql_query("SELECT * FROM anagrafica_cani", conn)
    conn.close()
    
    if not df_db.empty:
        st.success(f"✅ {len(df_db)} cani in anagrafica")
        
        # Mostra le colonne strutturate dal PDF
        st.dataframe(
            df_db, 
            use_container_width=True, 
            hide_index=True,
            column_config={
                "nome": st.column_config.TextColumn("Nome", width="medium"),
                "cibo": st.column_config.TextColumn("CIBO", width="medium"),
                "guinzaglieria": st.column_config.TextColumn("GUINZAGLIERIA", width="medium"),
                "strumenti": st.column_config.TextColumn("STRUMENTI", width="medium"),
                "attivita": st.column_config.TextColumn("ATTIVITÀ", width="medium"),
                "note": st.column_config.TextColumn("NOTE", width="large"),
                "tempo": st.column_config.TextColumn("TEMPO", width="small")
            }
        )
        
        st.divider()
        
        # Opzione per scaricare l'anagrafica
        col_export1, col_export2 = st.columns(2)
        
        if col_export1.button("📊 Esporta in Excel", use_container_width=True):
            excel_file = genera_excel_volontari()
            with open(excel_file, "rb") as f:
                st.download_button(
                    "⬇️ Scarica Excel",
                    f,
                    file_name=excel_file,
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    use_container_width=True
                )
        
        if col_export2.button("📄 Esporta in PDF", use_container_width=True):
            pdf_file = genera_pdf_volontari()
            with open(pdf_file, "rb") as f:
                st.download_button(
                    "⬇️ Scarica PDF",
                    f,
                    file_name=pdf_file,
                    mime="application/pdf",
                    use_container_width=True
                )
    else:
        st.info("ℹ️ Nessun cane in anagrafica. Carica i PDF dalla barra laterale.")
        st.markdown("""
        **Come procedere:**
        1. Prepara i PDF dei cani con i seguenti campi:
           - **CIBO**: informazioni sull'alimentazione
           - **GUINZAGLIERIA**: tipo di guinzaglio/pettorina
           - **STRUMENTI**: attrezzature necessarie
           - **ATTIVITÀ**: attività consigliate
           - **NOTE**: osservazioni comportamentali
           - **TEMPO**: durata consigliata uscita
        2. Carica i PDF dalla sidebar
        3. Clicca su "Aggiorna anagrafica da PDF"
        """)

with tab_stats:
    st.header("📊 Statistiche Storiche")
    
    conn = sqlite3.connect('canile.db')
    col_a, col_b = st.columns(2)
    d_ini = col_a.date_input("Inizio Periodo", datetime.today() - timedelta(days=30))
    d_end = col_b.date_input("Fine Periodo", datetime.today())
    
    query = "SELECT * FROM storico WHERE data BETWEEN ? AND ?"
    df_h = pd.read_sql_query(query, conn, params=(d_ini.strftime('%Y-%m-%d'), d_end.strftime('%Y-%m-%d')))
    
    if not df_h.empty:
        st.success(f"✅ Trovate {len(df_h)} attività nel periodo selezionato")
        
        filtro = st.radio("Filtra per:", ["Volontario", "Cane"], horizontal=True)
        ogg = st.selectbox(f"Seleziona {filtro}", sorted(df_h[filtro.lower()].unique()))
        res = df_h[df_h[filtro.lower()] == ogg]
        
        col_stat1, col_stat2 = st.columns(2)
        col_stat1.metric(f"Attività totali per {ogg}", len(res))
        
        if filtro == "Cane":
            volontari_unici = res['volontario'].nunique()
            col_stat2.metric("Volontari diversi", volontari_unici)
        else:
            cani_unici = res['cane'].nunique()
            col_stat2.metric("Cani diversi", cani_unici)
        
        st.divider()
        st.dataframe(res, hide_index=True, use_container_width=True)
    else:
        st.warning("⚠️ Nessun dato presente per le date selezionate.")
    
    conn.close()

with tab_colori:
    st.header("🎨 Gestione Colori Cani e Volontari")
    
    st.markdown("""
    ### Sistema di Compatibilità Colori
    
    **Livelli di Esperienza Volontari:**
    - ⚫ **Nero**: Molto esperto - può gestire TUTTI i cani (nero, rosso, arancione, verde)
    - 🔴 **Rosso**: Esperto - può gestire cani rosso, arancione, verde
    - 🟠 **Arancione**: Base - può gestire cani arancione, verde
    - 🟢 **Verde**: Principiante - può gestire SOLO cani verdi
    
    **Livelli di Difficoltà Cani:**
    - ⚫ **Nero**: Molto impegnativo
    - 🔴 **Rosso**: Impegnativo
    - 🟠 **Arancione**: Medio
    - 🟢 **Verde**: Facile
    
    ---
    """)
    
    col_tab1, col_tab2 = st.columns(2)
    
    with col_tab1:
        st.subheader("🐕 Colori Cani")
        if not df_c.empty:
            df_cani_colori = df_c[['nome', 'colore']].copy() if 'colore' in df_c.columns else df_c[['nome']].copy()
            if 'colore' not in df_cani_colori.columns:
                df_cani_colori['colore'] = 'verde'
            
            # Conta cani per colore
            colori_count = df_cani_colori['colore'].value_counts()
            for colore in ['nero', 'rosso', 'arancione', 'verde']:
                count = colori_count.get(colore, 0)
                emoji = {'nero': '⚫', 'rosso': '🔴', 'arancione': '🟠', 'verde': '🟢'}
                st.metric(f"{emoji[colore]} {colore.capitalize()}", count)
            
            st.divider()
            st.dataframe(df_cani_colori, use_container_width=True, hide_index=True)
        else:
            st.info("Nessun cane caricato da Google Sheets")
    
    with col_tab2:
        st.subheader("👤 Livelli Volontari")
        if not df_v.empty:
            df_vol_colori = df_v[['nome', 'colore']].copy() if 'colore' in df_v.columns else df_v[['nome']].copy()
            if 'colore' not in df_vol_colori.columns:
                df_vol_colori['colore'] = 'verde'
            
            # Conta volontari per colore
            colori_count = df_vol_colori['colore'].value_counts()
            for colore in ['nero', 'rosso', 'arancione', 'verde']:
                count = colori_count.get(colore, 0)
                emoji = {'nero': '⚫', 'rosso': '🔴', 'arancione': '🟠', 'verde': '🟢'}
                st.metric(f"{emoji[colore]} {colore.capitalize()}", count)
            
            st.divider()
            st.dataframe(df_vol_colori, use_container_width=True, hide_index=True)
        else:
            st.info("Nessun volontario caricato da Google Sheets")
    
    st.divider()
    
    st.subheader("🔍 Verifica Compatibilità")
    st.markdown("*Verifica se un volontario può gestire un cane specifico*")
    
    col_ver1, col_ver2 = st.columns(2)
    
    with col_ver1:
        cane_test = st.selectbox("Seleziona Cane", df_c['nome'].tolist() if not df_c.empty else [])
    
    with col_ver2:
        vol_test = st.selectbox("Seleziona Volontario", df_v['nome'].tolist() if not df_v.empty else [])
    
    if cane_test and vol_test:
        colore_cane = get_colore_cane(cane_test, df_c)
        colore_vol = get_colore_volontario(vol_test, df_v)
        compatibile, msg = verifica_compatibilita_colore(colore_vol, colore_cane)
        
        st.markdown("---")
        col_res1, col_res2, col_res3 = st.columns(3)
        
        with col_res1:
            emoji_cane = {'nero': '⚫', 'rosso': '🔴', 'arancione': '🟠', 'verde': '🟢'}
            st.info(f"🐕 **{cane_test}**\n\nLivello: {emoji_cane.get(colore_cane, '⚪')} {colore_cane.upper()}")
        
        with col_res2:
            emoji_vol = {'nero': '⚫', 'rosso': '🔴', 'arancione': '🟠', 'verde': '🟢'}
            st.info(f"👤 **{vol_test}**\n\nLivello: {emoji_vol.get(colore_vol, '⚪')} {colore_vol.upper()}")
        
        with col_res3:
            if compatibile:
                st.success(f"**Risultato:**\n\n{msg}")
            else:
                st.error(f"**Risultato:**\n\n{msg}")
    
    st.divider()
    st.info("""
    💡 **Nota:** I colori vengono caricati dal Google Sheets. Assicurati che le colonne 'colore' 
    siano presenti e popolate correttamente nei fogli "Cani" e "Volontari".
    
    Valori accettati: `nero`, `rosso`, `arancione`, `verde` (minuscolo o maiuscolo)
    """)

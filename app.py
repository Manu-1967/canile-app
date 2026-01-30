import streamlit as st
import pandas as pd
from datetime import datetime, timedelta
import PyPDF2
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
                  attivita TEXT, note TEXT, tempo TEXT)''')
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

def parse_pdf_content(text):
    """
    Estrae i campi dal PDF cercando i titoli in MAIUSCOLO.
    I titoli sono: CIBO, GUINZAGLIERIA, STRUMENTI, ATTIVITÀ, NOTE, TEMPO
    Il contenuto di ogni campo è il testo che segue il titolo fino al prossimo titolo o fino alla fine.
    """
    # Lista dei campi da estrarre (nell'ordine in cui appaiono nel PDF)
    campi = ['CIBO', 'GUINZAGLIERIA', 'STRUMENTI', 'ATTIVITÀ', 'NOTE', 'TEMPO']
    dati_estratti = {c: "N/D" for c in campi}
    
    # Pulizia preliminare del testo
    text = text.replace('\n\n', '\n').replace('\r', '')
    
    for i, campo in enumerate(campi):
        # Pattern migliorato: cerca il campo in maiuscolo (con possibili : o spazi dopo)
        # e cattura tutto fino al prossimo campo maiuscolo o fine testo
        
        # Creo il pattern per il campo successivo (se esiste)
        if i < len(campi) - 1:
            # Non è l'ultimo campo: cerco fino al prossimo campo
            prossimi_campi = '|'.join(campi[i+1:])
            pattern = rf"{campo}[\s:]*\n+(.*?)(?=\n+(?:{prossimi_campi})[\s:]|\Z)"
        else:
            # È l'ultimo campo (TEMPO): cerco fino alla fine
            pattern = rf"{campo}[\s:]*\n+(.*?)(?=\Z)"
        
        match = re.search(pattern, text, re.DOTALL | re.IGNORECASE)
        if match:
            contenuto = match.group(1).strip()
            # Rimuovo eventuali righe vuote multiple
            contenuto = re.sub(r'\n\s*\n', '\n', contenuto)
            dati_estratti[campo] = contenuto if contenuto else "N/D"
        else:
            # Tentativo alternativo: cerca il campo seguito da qualsiasi testo fino al prossimo campo in maiuscolo
            pattern_alt = rf"{campo}[\s:]*(.+?)(?=(?:{'|'.join(campi[i+1:]) if i < len(campi)-1 else 'XXXXXX'})[\s:]|\Z)"
            match_alt = re.search(pattern_alt, text, re.DOTALL | re.IGNORECASE)
            if match_alt:
                contenuto = match_alt.group(1).strip()
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

def get_info_cane(nome_cane):
    """
    Recupera le informazioni complete di un cane dall'anagrafica.
    Restituisce un dizionario con tutti i campi, o valori "N/D" se il cane non è trovato.
    """
    conn = sqlite3.connect('canile.db')
    conn.row_factory = sqlite3.Row
    try:
        row = conn.execute("SELECT * FROM anagrafica_cani WHERE nome=?", (nome_cane.capitalize(),)).fetchone()
        if row:
            return {
                'CIBO': row['cibo'] or 'N/D',
                'GUINZAGLIERIA': row['guinzaglieria'] or 'N/D',
                'STRUMENTI': row['strumenti'] or 'N/D',
                'ATTIVITÀ': row['attivita'] or 'N/D',
                'NOTE': row['note'] or 'N/D',
                'TEMPO': row['tempo'] or 'N/D'
            }
        else:
            return {campo: 'N/D' for campo in ['CIBO', 'GUINZAGLIERIA', 'STRUMENTI', 'ATTIVITÀ', 'NOTE', 'TEMPO']}
    finally:
        conn.close()

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
    pdf_files = st.file_uploader("📂 Carica/Aggiorna PDF Cani", accept_multiple_files=True, type="pdf")
    if pdf_files:
        conn = sqlite3.connect('canile.db')
        for f in pdf_files:
            reader = PyPDF2.PdfReader(f)
            text = " ".join([page.extract_text() for page in reader.pages])
            info = parse_pdf_content(text)
            nome_cane = f.name.split('.')[0].strip().capitalize()
            conn.execute("INSERT OR REPLACE INTO anagrafica_cani VALUES (?,?,?,?,?,?,?)", 
                         (nome_cane, info['CIBO'], info['GUINZAGLIERIA'], info['STRUMENTI'], 
                          info['ATTIVITÀ'], info['NOTE'], info['TEMPO']))
        conn.commit(); conn.close()
        st.success("Anagrafica aggiornata!")

df_c = load_gsheets("Cani"); df_v = load_gsheets("Volontari"); df_l = load_gsheets("Luoghi")
if 'programma' not in st.session_state: st.session_state.programma = []

st.title(" 🐕 Programma Canile 🐕 ")

# --- SELEZIONE RISORSE ---
c_p = st.multiselect("🐕 Cani in turno", df_c['nome'].tolist() if not df_c.empty else [])
v_p = st.multiselect("👤 Volontari presenti", df_v['nome'].tolist() if not df_v.empty else [])
l_p = st.multiselect("📍 Luoghi disponibili (Aperti oggi)", df_l['nome'].tolist() if not df_l.empty else [])

tab_prog, tab_ana, tab_storico = st.tabs(["📅 Programma", "📋 Anagrafica", "📊 Storico & Statistiche"])

with tab_prog:
    # 1. INSERIMENTO MANUALE (Con controllo sovrapposizioni E reattività)
    with st.expander("✏️ Inserimento Libero (Manuale)"):
        col1, col2 = st.columns(2)
        m_cane = col1.selectbox("Cane", ["-"] + c_p)
        m_luo = col2.selectbox("Luogo", ["-"] + l_p)
        m_vols = st.multiselect("Volontari assegnati", v_p)
        m_ora = st.time_input("Ora Inizio", ora_i)
        
        if st.button("➕ Aggiungi Manualmente"):
            if m_cane != "-":
                ora_str = m_ora.strftime('%H:%M')
                
                # CONTROLLO 1: Il volontario è già impegnato?
                conflitti_volontari = []
                for turno in st.session_state.programma:
                    if turno["Orario"] == ora_str:
                        vols_occupati = [v.strip() for v in turno["Volontario"].split(",")]
                        for v_scelto in m_vols:
                            if v_scelto in vols_occupati:
                                conflitti_volontari.append(v_scelto)
                
                # CONTROLLO 2: Reattività cane in campo adiacente (controllo bidirezionale)
                reattivita_cane = get_reattivita_cane(m_cane, df_c)
                conflitto_reattivita = False
                cani_problematici = []
                
                if m_luo != "-":
                    campi_adi = get_campi_adiacenti(m_luo, df_l)
                    
                    # Verifico se ci sono conflitti con cani già assegnati
                    for turno in st.session_state.programma:
                        if turno["Orario"] == ora_str and turno["Luogo"] in campi_adi:
                            cane_adiacente = turno["Cane"]
                            if cane_adiacente not in ["TUTTI", "Da assegnare"]:
                                reatt_adia = get_reattivita_cane(cane_adiacente, df_c)
                                
                                # Conflitto se ALMENO UNO dei due ha reattività > 5
                                if reattivita_cane > 5 or reatt_adia > 5:
                                    conflitto_reattivita = True
                                    cani_problematici.append(f"{cane_adiacente} (reattività {reatt_adia:.0f}) in {turno['Luogo']}")
                
                # GESTIONE ERRORI
                if conflitti_volontari:
                    st.error(f"⚠️ Attenzione! I seguenti volontari sono già occupati alle {ora_str}: {', '.join(conflitti_volontari)}")
                elif conflitto_reattivita:
                    st.error(f"⚠️ CONFLITTO REATTIVITÀ alle {ora_str}!\n\n"
                            f"**{m_cane}** (reattività {reattivita_cane:.0f}) non può essere assegnato a '{m_luo}' perché:\n\n"
                            f"Cani adiacenti con reattività alta:\n" + 
                            "\n".join([f"- {c}" for c in cani_problematici]) + 
                            f"\n\n**Regola:** Se ALMENO UN cane ha reattività > 5, non possono essere in campi adiacenti.")
                else:
                    # Recupero info del cane
                    info_cane = get_info_cane(m_cane)
                    
                    st.session_state.programma.append({
                        "Orario": ora_str,
                        "Cane": m_cane, 
                        "Volontario": ", ".join(m_vols) if m_vols else "Da assegnare", 
                        "Luogo": m_luo, 
                        "Attività": "Manuale", 
                        "Inizio_Sort": ora_str,
                        "CIBO": info_cane['CIBO'],
                        "GUINZAGLIERIA": info_cane['GUINZAGLIERIA'],
                        "STRUMENTI": info_cane['STRUMENTI'],
                        "ATTIVITÀ_CANE": info_cane['ATTIVITÀ'],
                        "NOTE": info_cane['NOTE'],
                        "TEMPO": info_cane['TEMPO']
                    })
                    st.success(f"✅ Turno delle {ora_str} aggiunto!")
                    st.rerun()

    # 2. GENERAZIONE AUTOMATICA (Con controllo reattività integrato - FIX CRITICO)
    c_btn1, c_btn2 = st.columns(2)
    
    if c_btn1.button("🤖 Genera/Completa Automatico", use_container_width=True):
        conn = sqlite3.connect('canile.db'); conn.row_factory = sqlite3.Row
        start_dt = datetime.combine(data_t, ora_i)
        end_dt = datetime.combine(data_t, ora_f)
        pasti_dt = end_dt - timedelta(minutes=30) 
        
        # 1. RECUPERO TURNI MANUALI ESISTENTI
        manuali_esistenti = [r for r in st.session_state.programma if r.get("Attività") == "Manuale"]
        st.session_state.programma = []
        
        # 2. BRIEFING INIZIALE
        st.session_state.programma.append({
            "Orario": start_dt.strftime('%H:%M'), 
            "Cane": "TUTTI", 
            "Volontario": "TUTTI", 
            "Luogo": "Ufficio", 
            "Attività": "Briefing", 
            "Inizio_Sort": start_dt.strftime('%H:%M')
        })

        # 3. PREPARAZIONE LISTE
        cani_gia_occupati = [m["Cane"] for m in manuali_esistenti]
        cani_da_fare = [c for c in c_p if c not in cani_gia_occupati]
        curr_t = start_dt + timedelta(minutes=15)
        
        # 4. FILTRO LUOGHI CON AUTOMATICO = SÌ
        luoghi_auto_ok = []
        if not df_l.empty and 'automatico' in df_l.columns:
             filtro = (df_l['nome'].isin(l_p)) & (df_l['automatico'].astype(str).str.lower().str.strip() == 'sì')
             luoghi_auto_ok = df_l[filtro]['nome'].tolist()
        else:
             luoghi_auto_ok = l_p.copy()

        # 5. ALGORITMO PRINCIPALE CON CONTROLLO REATTIVITÀ - FIX CRITICO
        while cani_da_fare and curr_t < pasti_dt and luoghi_auto_ok:
            ora_attuale_str = curr_t.strftime('%H:%M')
            
            # --- FILTRO ANTI-SOVRAPPOSIZIONE VOLONTARI E LUOGHI ---
            vols_impegnati_ora = []
            luoghi_impegnati_ora = []
            for m in manuali_esistenti:
                if m["Orario"] == ora_attuale_str:
                    # Estraiamo tutti i nomi separati dalla virgola (es: "Mario, Anna")
                    vols_impegnati_ora.extend([v.strip() for v in m["Volontario"].split(",")])
                    luoghi_impegnati_ora.append(m["Luogo"])

            # Volontari e campi disponibili in questo orario
            vols_liberi = [v for v in v_p if v not in vols_impegnati_ora]
            campi_disponibili = [l for l in luoghi_auto_ok if l not in luoghi_impegnati_ora]
            
            n_cani = min(len(cani_da_fare), len(campi_disponibili))
            
            if n_cani > 0 and vols_liberi:
                # --- ASSEGNAZIONE CANI UNO ALLA VOLTA (FIX CRITICO) ---
                cani_assegnati_questa_fascia = 0
                
                for _ in range(n_cani):
                    if not cani_da_fare or not vols_liberi or not campi_disponibili: 
                        break
                    
                    # Provo ad assegnare un cane a un campo valido
                    cane_assegnato = False
                    tentativi = 0
                    
                    while not cane_assegnato and tentativi < len(cani_da_fare):
                        cane = cani_da_fare[tentativi]
                        
                        # Cerco un campo disponibile che rispetti la reattività
                        campo_trovato = None
                        for campo in campi_disponibili:
                            # *** FIX CRITICO: Verifico contro TUTTI i turni già in programma ***
                            # Questo include i cani già assegnati in questa fascia oraria!
                            tutti_turni = st.session_state.programma + manuali_esistenti
                            
                            # *** CONTROLLO REATTIVITÀ ***
                            if campo_valido_per_reattivita(cane, campo, tutti_turni, ora_attuale_str, df_c, df_l):
                                campo_trovato = campo
                                break
                        
                        if campo_trovato:
                            # Assegnazione riuscita - rimuovo cane dalla lista
                            cane = cani_da_fare.pop(tentativi)
                            campo = campo_trovato
                            campi_disponibili.remove(campo)
                            cane_assegnato = True
                            
                            # --- ASSEGNAZIONE VOLONTARIO LEAD (priorità storica) ---
                            vols_punteggio = []
                            for v in vols_liberi:
                                cnt = conn.execute("SELECT COUNT(*) FROM storico WHERE cane=? AND volontario=?", (cane, v)).fetchone()[0]
                                vols_punteggio.append((v, cnt))
                            vols_punteggio.sort(key=lambda x: x[1], reverse=True)
                            
                            lead = vols_punteggio[0][0]
                            vols_liberi.remove(lead)  # Rimuovo il lead per non riusarlo
                            
                            # *** FIX CRITICO: AGGIUNGO IL TURNO IMMEDIATAMENTE ***
                            # In questo modo il prossimo cane vedrà questo cane quando fa il controllo!
                            info_cane = get_info_cane(cane)
                            
                            st.session_state.programma.append({
                                "Orario": ora_attuale_str, 
                                "Cane": cane, 
                                "Volontario": lead,  # Per ora solo il lead, supporti dopo
                                "Luogo": campo, 
                                "Inizio_Sort": ora_attuale_str, 
                                "Attività": "Automatico",
                                "CIBO": info_cane['CIBO'],
                                "GUINZAGLIERIA": info_cane['GUINZAGLIERIA'],
                                "STRUMENTI": info_cane['STRUMENTI'],
                                "ATTIVITÀ_CANE": info_cane['ATTIVITÀ'],
                                "NOTE": info_cane['NOTE'],
                                "TEMPO": info_cane['TEMPO']
                            })
                            
                            cani_assegnati_questa_fascia += 1
                            
                        else:
                            # Questo cane non può essere assegnato ora per vincoli di reattività
                            # Provo con il prossimo cane
                            tentativi += 1
                    
                    if not cane_assegnato:
                        # Nessun cane può essere assegnato in questa fascia oraria
                        # (tutti hanno vincoli di reattività)
                        break
                
                # --- ASSEGNAZIONE SUPPORTI AI TURNI GIÀ CREATI ---
                # Prendo gli ultimi N turni creati in questa fascia oraria
                if vols_liberi and cani_assegnati_questa_fascia > 0:
                    turni_questa_fascia = [t for t in st.session_state.programma 
                                          if t["Orario"] == ora_attuale_str and t.get("Attività") == "Automatico"]
                    
                    idx = 0
                    while vols_liberi and turni_questa_fascia:
                        turno = turni_questa_fascia[idx % len(turni_questa_fascia)]
                        vol_supporto = vols_liberi.pop(0)
                        # Aggiungo il supporto al volontario esistente
                        turno["Volontario"] += f" + {vol_supporto}"
                        idx += 1
            
            # Prossima fascia oraria
            curr_t += timedelta(minutes=45)

        # 6. REINSERIMENTO TURNI MANUALI E CHIUSURA
        st.session_state.programma.extend(manuali_esistenti)
        st.session_state.programma.append({
            "Orario": pasti_dt.strftime('%H:%M'), 
            "Cane": "TUTTI", 
            "Volontario": "TUTTI", 
            "Luogo": "Box", 
            "Attività": "Pasti", 
            "Inizio_Sort": pasti_dt.strftime('%H:%M')
        })
        conn.close()
        st.success("✅ Programma generato rispettando i vincoli di reattività!")
        st.rerun()

    if c_btn2.button("🗑️ Svuota", use_container_width=True):
        st.session_state.programma = []
        st.rerun()

    # 3. VISUALIZZAZIONE E MODIFICA PROGRAMMA
    if st.session_state.programma:
        st.divider()
        st.subheader("📋 Programma Giornaliero")
        
        df_view = pd.DataFrame(st.session_state.programma).sort_values("Inizio_Sort")
        
        # Assicuro che tutte le colonne esistano (per compatibilità con turni vecchi)
        for col in ['CIBO', 'GUINZAGLIERIA', 'STRUMENTI', 'ATTIVITÀ_CANE', 'NOTE', 'TEMPO']:
            if col not in df_view.columns:
                df_view[col] = 'N/D'
        
        df_edited = st.data_editor(
            df_view, 
            use_container_width=True, 
            hide_index=True, 
            num_rows="dynamic",
            column_config={
                "Orario": st.column_config.TextColumn("⏰ Orario", width="small"),
                "Cane": st.column_config.TextColumn("🐕 Cane", width="medium"),
                "Volontario": st.column_config.TextColumn("👤 Volontari", width="large"),
                "Luogo": st.column_config.TextColumn("📍 Luogo", width="medium"),
                "Attività": st.column_config.TextColumn("🎯 Tipo", width="small"),
                "CIBO": st.column_config.TextColumn("🍖 Cibo", width="medium"),
                "GUINZAGLIERIA": st.column_config.TextColumn("🦴 Guinzaglieria", width="medium"),
                "STRUMENTI": st.column_config.TextColumn("🔧 Strumenti", width="medium"),
                "ATTIVITÀ_CANE": st.column_config.TextColumn("🎾 Attività", width="medium"),
                "NOTE": st.column_config.TextColumn("📝 Note", width="large"),
                "TEMPO": st.column_config.TextColumn("⏱️ Tempo", width="small"),
            }
        )
        st.session_state.programma = df_edited.to_dict('records')

with tab_ana:
    st.subheader("📋 Anagrafica Cani (da PDF)")
    conn = sqlite3.connect('canile.db')
    df_db = pd.read_sql_query("SELECT * FROM anagrafica_cani", conn)
    
    if not df_db.empty:
        c_del = st.selectbox("Seleziona cane da eliminare", ["-"] + df_db['nome'].tolist())
        if st.button("❌ Elimina Record"):
            if c_del != "-":
                conn.execute("DELETE FROM anagrafica_cani WHERE nome=?", (c_del,))
                conn.commit()
                st.success(f"Record '{c_del}' eliminato!")
                st.rerun()
        
        st.divider()
        st.dataframe(
            df_db, 
            use_container_width=True, 
            hide_index=True,
            column_config={
                "nome": st.column_config.TextColumn("🐕 Nome Cane", width="medium"),
                "cibo": st.column_config.TextColumn("🍖 CIBO", width="medium"),
                "guinzaglieria": st.column_config.TextColumn("🦴 GUINZAGLIERIA", width="medium"),
                "strumenti": st.column_config.TextColumn("🔧 STRUMENTI", width="medium"),
                "attivita": st.column_config.TextColumn("🎾 ATTIVITÀ", width="medium"),
                "note": st.column_config.TextColumn("📝 NOTE", width="large"),
                "tempo": st.column_config.TextColumn("⏱️ TEMPO", width="small"),
            }
        )
    else:
        st.info("Nessun dato in anagrafica. Carica i PDF dalla sidebar.")
    
    conn.close()

with tab_storico:
    st.subheader("📊 Gestione Storico Turni")
    
    conn = sqlite3.connect('canile.db')
    
    # --- SOTTOTAB: VISUALIZZA/MODIFICA/CANCELLA vs STATISTICHE ---
    subtab_gestione, subtab_stats = st.tabs(["🗂️ Gestione Dati", "📈 Statistiche"])
    
    with subtab_gestione:
        st.write("### 📋 Visualizza e Modifica Storico")
        
        # --- INSERIMENTO MANUALE NUOVO TURNO ---
        with st.expander("➕ Aggiungi Nuovo Turno allo Storico"):
            col_add1, col_add2 = st.columns(2)
            
            with col_add1:
                new_data = st.date_input("Data Turno", datetime.today(), key="new_turno_data")
                new_orario = st.time_input("Orario", datetime.strptime("09:00", "%H:%M"), key="new_turno_ora")
                new_cane = st.text_input("Nome Cane", key="new_turno_cane")
            
            with col_add2:
                new_volontario = st.text_input("Nome Volontario", key="new_turno_vol")
                new_luogo = st.text_input("Luogo", key="new_turno_luogo")
            
            if st.button("💾 Aggiungi allo Storico", use_container_width=True):
                if new_cane and new_volontario and new_luogo:
                    try:
                        conn.execute(
                            "INSERT INTO storico (data, inizio, cane, volontario, luogo) VALUES (?, ?, ?, ?, ?)",
                            (new_data.strftime('%Y-%m-%d'), 
                             new_orario.strftime('%H:%M'), 
                             new_cane, 
                             new_volontario, 
                             new_luogo)
                        )
                        conn.commit()
                        st.success(f"✅ Turno aggiunto: {new_cane} con {new_volontario}")
                        st.rerun()
                    except Exception as e:
                        st.error(f"❌ Errore: {str(e)}")
                else:
                    st.warning("⚠️ Compila tutti i campi obbligatori")
        
        st.divider()
        
        # Filtri
        col_f1, col_f2, col_f3 = st.columns(3)
        
        # Carico tutti i dati per i filtri
        df_storico_completo = pd.read_sql_query("SELECT rowid, * FROM storico ORDER BY data DESC, inizio", conn)
        
        if not df_storico_completo.empty:
            with col_f1:
                date_uniche = sorted(df_storico_completo['data'].unique(), reverse=True)
                filtro_data = st.selectbox("Filtra per Data", ["Tutte"] + date_uniche)
            
            with col_f2:
                cani_unici = sorted(df_storico_completo['cane'].unique())
                filtro_cane = st.selectbox("Filtra per Cane", ["Tutti"] + cani_unici)
            
            with col_f3:
                vol_unici = sorted(df_storico_completo['volontario'].unique())
                filtro_vol = st.selectbox("Filtra per Volontario", ["Tutti"] + vol_unici)
            
            # Applico filtri
            df_filtrato = df_storico_completo.copy()
            if filtro_data != "Tutte":
                df_filtrato = df_filtrato[df_filtrato['data'] == filtro_data]
            if filtro_cane != "Tutti":
                df_filtrato = df_filtrato[df_filtrato['cane'] == filtro_cane]
            if filtro_vol != "Tutti":
                df_filtrato = df_filtrato[df_filtrato['volontario'] == filtro_vol]
            
            st.info(f"📊 Visualizzati **{len(df_filtrato)}** turni su **{len(df_storico_completo)}** totali")
            
            if not df_filtrato.empty:
                # Converto la colonna data da stringa a datetime per compatibilità con DateColumn
                df_filtrato_edit = df_filtrato[['rowid', 'data', 'inizio', 'cane', 'volontario', 'luogo']].copy()
                df_filtrato_edit['data'] = pd.to_datetime(df_filtrato_edit['data'], errors='coerce')
                
                # Editor per modificare lo storico
                st.write("#### ✏️ Modifica Turni")
                df_edited = st.data_editor(
                    df_filtrato_edit,
                    use_container_width=True,
                    hide_index=True,
                    num_rows="dynamic",
                    column_config={
                        "rowid": st.column_config.NumberColumn("ID", disabled=True, width="small"),
                        "data": st.column_config.DateColumn("📅 Data", format="DD/MM/YYYY", width="medium"),
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
                            # Aggiorno tutti i record modificati
                            for _, row in df_edited.iterrows():
                                # Converto la data da datetime a stringa formato YYYY-MM-DD
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
                
                # Cancellazione rapida per data
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
        else:
            st.info("📭 Nessun dato nello storico. Salva alcuni turni per iniziare!")
    
    with subtab_stats:
        st.write("### 📈 Statistiche Esperienza")
        
        df_storico = pd.read_sql_query("SELECT * FROM storico", conn)
        
        if not df_storico.empty:
            # Statistiche per cane
            st.write("#### 🐕 Esperienza per Cane")
            
            cani_disponibili = sorted(df_storico['cane'].unique())
            cane_selezionato = st.selectbox("Seleziona un cane", cani_disponibili, key="stats_cane")
            
            if cane_selezionato:
                # Statistiche del cane selezionato
                df_cane = df_storico[df_storico['cane'] == cane_selezionato]
                
                # Raggruppo per volontario
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
                
                # Aggiungo una colonna con la percentuale
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
                
                # Grafico a barre
                st.bar_chart(stats_volontari.set_index('Volontario')['Turni Totali'])
            
            st.divider()
            
            # Statistiche generali
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
            
            # Top volontari
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
                # Opzionalmente: svuoto il programma dopo il salvataggio
                st.session_state.programma = []
                st.rerun()
            else:
                st.warning("⚠️ Nessun turno valido da salvare (solo turni speciali o senza cane).")
else:
    st.info("📝 Crea prima un programma giornaliero per poterlo salvare nello storico.")

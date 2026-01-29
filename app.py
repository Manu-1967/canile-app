import streamlit as st
import pandas as pd
from datetime import datetime, timedelta
import sqlite3
import PyPDF2
import re
import io

# --- CONFIGURAZIONE ---
st.set_page_config(page_title="Canile Soft v3", layout="centered")

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
        
        # ### MODIFICA: Gestione sicurezza colonna 'automatico' per i Luoghi
        if sheet_name == "Luoghi" and 'automatico' not in df.columns:
            # Se la colonna non esiste nel foglio, assumiamo 'sì' per tutto per non rompere il codice
            df['automatico'] = 'sì'
            
        return df.dropna(how='all')
    except:
        return pd.DataFrame()

def parse_pdf_content(text):
    campi = ['CIBO', 'GUINZAGLIERIA', 'STRUMENTI', 'ATTIVITÀ', 'NOTE', 'TEMPO', 'LIVELLO']
    dati_estratti = {c: "N/D" for c in campi}
    for campo in campi:
        pattern = rf"{campo}[:\s\n]+(.*?)(?=\n(?:{'|'.join(campi)})[:\s]|$)"
        match = re.search(pattern, text, re.DOTALL | re.IGNORECASE)
        if match:
            dati_estratti[campo] = match.group(1).strip()
    return dati_estratti

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
            conn.execute("INSERT OR REPLACE INTO anagrafica_cani VALUES (?,?,?,?,?,?,?,?)", 
                         (nome_cane, info['CIBO'], info['GUINZAGLIERIA'], info['STRUMENTI'], 
                          info['ATTIVITÀ'], info['NOTE'], info['TEMPO'], info['LIVELLO']))
        conn.commit(); conn.close()
        st.success("Anagrafica aggiornata!")

df_c = load_gsheets("Cani"); df_v = load_gsheets("Volontari"); df_l = load_gsheets("Luoghi")
if 'programma' not in st.session_state: st.session_state.programma = []

st.title("📱 Canile Soft")

# --- SELEZIONE RISORSE ---
c_p = st.multiselect("🐕 Cani in turno", df_c['nome'].tolist() if not df_c.empty else [])
v_p = st.multiselect("👤 Volontari presenti", df_v['nome'].tolist() if not df_v.empty else [])
l_p = st.multiselect("📍 Luoghi disponibili (Aperti oggi)", df_l['nome'].tolist() if not df_l.empty else [])

tab_prog, tab_ana = st.tabs(["📅 Programma", "📋 Anagrafica"])

with tab_prog:
    # 1. INSERIMENTO MANUALE (Con controllo sovrapposizioni)
    with st.expander("✍️ Inserimento Libero (Manuale)"):
        col1, col2 = st.columns(2)
        m_cane = col1.selectbox("Cane", ["-"] + c_p)
        m_luo = col2.selectbox("Luogo", ["-"] + l_p)
        m_vols = st.multiselect("Volontari assegnati", v_p)
        m_ora = st.time_input("Ora Inizio", ora_i)
        
        if st.button("➕ Aggiungi Manualmente"):
            if m_cane != "-":
                ora_str = m_ora.strftime('%H:%M')
                # CONTROLLO: Il volontario è già impegnato?
                conflitti = []
                for turno in st.session_state.programma:
                    if turno["Orario"] == ora_str:
                        vols_occupati = [v.strip() for v in turno["Volontario"].split(",")]
                        for v_scelto in m_vols:
                            if v_scelto in vols_occupati:
                                conflitti.append(v_scelto)
                
                if conflitti:
                    st.error(f"Attenzione! I seguenti volontari sono già occupati alle {ora_str}: {', '.join(conflitti)}")
                else:
                    st.session_state.programma.append({
                        "Orario": ora_str,
                        "Cane": m_cane, 
                        "Volontario": ", ".join(m_vols) if m_vols else "Da assegnare", 
                        "Luogo": m_luo, 
                        "Attività": "Manuale", 
                        "Inizio_Sort": ora_str
                    })
                    st.success(f"Turno delle {ora_str} aggiunto!")
                    st.rerun()

    # 2. GENERAZIONE AUTOMATICA (Logica di esclusione potenziata)
    c_btn1, c_btn2 = st.columns(2)
    
    if c_btn1.button("🤖 Genera/Completa Automatico", use_container_width=True):
        conn = sqlite3.connect('canile.db')
        conn.row_factory = sqlite3.Row
        start_dt = datetime.combine(data_t, ora_i)
        end_dt = datetime.combine(data_t, ora_f)
        pasti_dt = end_dt - timedelta(minutes=30) 
        
        manuali_esistenti = [r for r in st.session_state.programma if r.get("Attività") == "Manuale"]
        st.session_state.programma = []
        
        # Briefing
        st.session_state.programma.append({
            "Orario": start_dt.strftime('%H:%M'), "Cane": "TUTTI", "Volontario": "TUTTI", 
            "Luogo": "Ufficio", "Attività": "Briefing", "Inizio_Sort": start_dt.strftime('%H:%M')
        })

        cani_gia_occupati = [m["Cane"] for m in manuali_esistenti]
        cani_da_fare = [c for c in c_p if c not in cani_gia_occupati]
        curr_t = start_dt + timedelta(minutes=15)
        
        # 1. FILTRO LUOGHI AUTOMATICI
        # Usiamo solo i luoghi che hanno 'automatico' == 'sì'
        if not df_l.empty and 'automatico' in df_l.columns:
             filtro = (df_l['nome'].isin(l_p)) & (df_l['automatico'].astype(str).str.lower().str.strip() == 'sì')
             luoghi_auto_ok = df_l[filtro]['nome'].tolist()
        else:
             luoghi_auto_ok = l_p.copy()

        while cani_da_fare and curr_t <asti_dt:
            ora_attuale_str = curr_t.strftime('%H:%M')
            
            # Recupero vincoli dai manuali
            vols_impegnati_ora = []
            luoghi_impegnati_ora = []
            for m in manuali_esistenti:
                if m["Orario"] == ora_attuale_str:
                    vols_impegnati_ora.extend([v.strip() for v in str(m["Volontario"]).split(",")])
                    luoghi_impegnati_ora.append(m["Luogo"])

            vols_liberi = [v for v in v_p if v not in vols_impegnati_ora]
            # 2. UNICITÀ LUOGO: Filtriamo i luoghi già presi dai manuali
            campi_disponibili = [l for l in luoghi_auto_ok if l not in luoghi_impegnati_ora]
            
            batch = []
            # Creiamo una copia della lista cani per iterare in sicurezza
            cani_correnti = cani_da_fare[:]
            
            for cane_nome in cani_correnti:
                if not campi_disponibili or not vols_liberi:
                    break
                
                # Recupero info cane (Livello di reattività)
                info_c = conn.execute("SELECT * FROM anagrafica_cani WHERE nome=?", (cane_nome.capitalize(),)).fetchone()
                livello_reattivita = int(info_c['livello']) if info_c and str(info_c['livello']).isdigit() else 0
                
                # 3. LOGICA REATTIVITÀ E ADIACENZA
                luogo_scelto = None
                for campo in campi_disponibili:
                    # Recuperiamo le adiacenze dal DF Luoghi
                    row_luogo = df_l[df_l['nome'] == campo].iloc[0]
                    adiacenze = str(row_luogo['adiacente']).split(',') if 'adiacente' in df_l.columns else []
                    adiacenze = [a.strip() for a in adiacenze]
                    
                    # Verifichiamo se un luogo adiacente è già occupato in questo batch o nei manuali
                    occupati_ora = luoghi_impegnati_ora + [b['campo'] for b in batch]
                    conflitto_adiacenza = any(adj in occupati_ora for adj in adiacenze)
                    
                    if livello_reattivita > 5 and conflitto_adiacenza:
                        continue # Salta questo campo, cercane un altro meno "affollato"
                    else:
                        luogo_scelto = campo
                        break
                
                if luogo_scelto:
                    campi_disponibili.remove(luogo_scelto)
                    cani_da_fare.remove(cane_nome)
                    
                    # Assegnazione lead
                    vols_punteggio = []
                    for v in vols_liberi:
                        cnt = conn.execute("SELECT COUNT(*) FROM storico WHERE cane=? AND volontario=?", (cane_nome, v)).fetchone()[0]
                        vols_punteggio.append((v, cnt))
                    vols_punteggio.sort(key=lambda x: x[1], reverse=True)
                    
                    lead = vols_punteggio[0][0]
                    vols_liberi.remove(lead)
                    batch.append({"cane": cane_nome, "campo": luogo_scelto, "lead": lead, "sups": [], "note": info_c['note'] if info_c else "-"})

            # (Il resto della logica per supporti e inserimento in session_state rimane uguale)
            # ...

        # ALGORITMO
        # ALGORITMO DI GENERAZIONE
        # Usiamo 'pasti_dt' per assicurarci che i turni finiscano prima dei pasti
        while cani_da_fare and curr_t < pasti_dt: 
            ora_attuale_str = curr_t.strftime('%H:%M')
            
            # Recupero vincoli dai manuali per evitare sovrapposizioni
            vols_impegnati_ora = []
            luoghi_impegnati_ora = []
            for m in manuali_esistenti:
                if m["Orario"] == ora_attuale_str:
                    vols_impegnati_ora.extend([v.strip() for v in str(m["Volontario"]).split(",")])
                    luoghi_impegnati_ora.append(m["Luogo"])

            vols_liberi = [v for v in v_p if v not in vols_impegnati_ora]
            
            # Filtriamo i luoghi: devono essere automatici E non occupati dai manuali
            campi_disponibili = [l for l in luoghi_auto_ok if l not in luoghi_impegnati_ora]
            
            batch = []
            cani_correnti = cani_da_fare[:] # Copia per iterare senza errori
            
            for cane_nome in cani_correnti:
                if not campi_disponibili or not vols_liberi:
                    break
                
                # Recupero anagrafica per reattività
                info_c = conn.execute("SELECT * FROM anagrafica_cani WHERE nome=?", (cane_nome.capitalize(),)).fetchone()
                # Se il livello non è un numero o non esiste, impostiamo 0 di default
                livello_reattivita = int(info_c['livello']) if info_c and str(info_c['livello']).isdigit() else 0
                
                luogo_scelto = None
                for campo in campi_disponibili:
                    # Controllo adiacenze
                    row_luogo = df_l[df_l['nome'] == campo].iloc[0]
                    # Gestiamo il caso in cui la colonna 'adiacente' sia vuota
                    adiacenze_str = str(row_luogo.get('adiacente', ""))
                    adiacenze = [a.strip() for a in adiacenze_str.split(',') if a.strip()]
                    
                    # Verifichiamo chi è già nel campo o nei campi vicini
                    occupati_ora = luoghi_impegnati_ora + [b['campo'] for b in batch]
                    conflitto_adiacenza = any(adj in occupati_ora for adj in adiacenze)
                    
                    # REGOLE:
                    # 1. Mai due cani nello stesso luogo (gestito da campi_disponibili)
                    # 2. Se reattivo (>5), non può stare vicino a un luogo occupato
                    if livello_reattivita > 5 and conflitto_adiacenza:
                        continue 
                    else:
                        luogo_scelto = campo
                        break
                
                if luogo_scelto:
                    campi_disponibili.remove(luogo_scelto)
                    cani_da_fare.remove(cane_nome)
                    
                    # Assegnazione lead (volontario con più esperienza con quel cane)
                    vols_punteggio = []
                    for v in vols_liberi:
                        cnt = conn.execute("SELECT COUNT(*) FROM storico WHERE cane=? AND volontario=?", (cane_nome, v)).fetchone()[0]
                        vols_punteggio.append((v, cnt))
                    vols_punteggio.sort(key=lambda x: x[1], reverse=True)
                    
                    lead = vols_punteggio[0][0]
                    vols_liberi.remove(lead)
                    
                    batch.append({
                        "Orario": ora_attuale_str, 
                        "Cane": cane_nome, 
                        "Volontario": lead, 
                        "Luogo": luogo_scelto, 
                        "Note": info_c['note'] if info_c else "-", 
                        "Inizio_Sort": ora_attuale_str, 
                        "Attività": "Automatico",
                        "sups": [] # Prepariamo per eventuali secondi volontari
                    })

            # Distribuiamo i volontari rimasti come supporto (sups)
            if vols_liberi and batch:
                idx = 0
                while vols_liberi:
                    batch[idx % len(batch)]["sups"].append(vols_liberi.pop(0))
                    idx += 1
            
            # Formattiamo i nomi dei volontari (Lead + Supporti) e aggiungiamo al programma
            for b in batch:
                if b["sups"]:
                    b["Volontario"] = f"{b['Volontario']} + {', '.join(b['sups'])}"
                # Rimuoviamo la chiave temporanea 'sups' prima di salvare
                del b["sups"]
                st.session_state.programma.append(b)
            
            curr_t += timedelta(minutes=45)

        # REINSERIMENTO E CHIUSURA
        st.session_state.programma.extend(manuali_esistenti)
        st.session_state.programma.append({
            "Orario": pasti_dt.strftime('%H:%M'), "Cane": "TUTTI", "Volontario": "TUTTI", 
            "Luogo": "Box", "Attività": "Pasti", "Inizio_Sort": pasti_dt.strftime('%H:%M')
        })
        conn.close(); st.rerun()

    if c_btn2.button("🗑️ Svuota", use_container_width=True):
        st.session_state.programma = []; st.rerun()

    # EDITOR FINALE
    if st.session_state.programma:
        df_view = pd.DataFrame(st.session_state.programma).sort_values("Inizio_Sort")
        df_edited = st.data_editor(df_view, use_container_width=True, hide_index=True, num_rows="dynamic")
        st.session_state.programma = df_edited.to_dict('records')

with tab_ana:
    conn = sqlite3.connect('canile.db')
    df_db = pd.read_sql_query("SELECT * FROM anagrafica_cani", conn)
    if not df_db.empty:
        c_del = st.selectbox("Seleziona cane da eliminare", ["-"] + df_db['nome'].tolist())
        if st.button("❌ Elimina Record"):
            if c_del != "-":
                conn.execute("DELETE FROM anagrafica_cani WHERE nome=?", (c_del,))
                conn.commit(); st.rerun()
        st.divider()
        st.dataframe(df_db, use_container_width=True, hide_index=True)
    conn.close()

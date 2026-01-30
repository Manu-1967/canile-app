import streamlit as st
import pandas as pd
from datetime import datetime, timedelta
import PyPDF2
import re
import sqlite3

# --- CONFIGURAZIONE ---
st.set_page_config(page_title="Programma Canile", layout="wide") # Layout wide aiuta su mobile/tablet

def init_db():
    conn = sqlite3.connect('canile.db')
    c = conn.cursor()
    c.execute('CREATE TABLE IF NOT EXISTS storico (data TEXT, inizio TEXT, cane TEXT, volontario TEXT, luogo TEXT)')
    # Tabella anagrafica completa
    c.execute('''CREATE TABLE IF NOT EXISTS anagrafica_cani 
                 (nome TEXT PRIMARY KEY, cibo TEXT, guinzaglieria TEXT, strumenti TEXT, 
                  attivita TEXT, note TEXT, tempo TEXT, livello TEXT)''')
    conn.commit()
    conn.close()

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
    
    # Se c'è scritto "ora" o "ore", moltiplica per 60 (es. "1 ora" = 60 min)
    if "ora" in tempo_str or "ore" in tempo_str:
        if num < 10: # Evita che "45 min (ora x)" venga moltiplicato erroneamente se scritto male
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
    # Ritorna dizionario vuoto/default se non trovato
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
        # Nota: Qui controlliamo solo l'orario di INIZIO per semplicità, 
        # ma idealmente si dovrebbero controllare le sovrapposizioni temporali.
        # Per ora manteniamo la logica a slot.
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

tab_prog, tab_ana = st.tabs(["📅 Programma", "📋 Anagrafica"])

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

                # Controllo base (semplificato per brevità)
                conflitti = [t for t in st.session_state.programma if t["Inizio_Sort"] == ora_str and t["Cane"] == m_cane]
                
                if not conflitti:
                    entry = {
                        "Orario": orario_display,
                        "Cane": m_cane, 
                        "Volontario": ", ".join(m_vols) if m_vols else "Da assegnare", 
                        "Luogo": m_luo,
                        "Inizio_Sort": ora_str,
                        # Campi aggiuntivi PDF
                        "Cibo": info_cane.get('cibo', '-'),
                        "Guinzaglieria": info_cane.get('guinzaglieria', '-'),
                        "Strumenti": info_cane.get('strumenti', '-'),
                        "Attività PDF": info_cane.get('attivita', '-'), # Rinomino per evitare conflitti con 'Attività' di sistema
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
        
        manuali_esistenti = st.session_state.programma # Manteniamo quelli manuali
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
            for m in manuali_esistenti: # Controllo grezzo contro manuali
                if m["Inizio_Sort"] == ora_attuale_str:
                    vols_impegnati.extend([v.strip() for v in m["Volontario"].split(",")])
                    luoghi_impegnati.append(m["Luogo"])

            vols_liberi = [v for v in v_p if v not in vols_impegnati]
            campi_disp = [l for l in luoghi_auto if l not in luoghi_impegnati]
            
            n_cani = min(len(cani_da_fare), len(campi_disp))
            max_durata_turno = 30 # Minuti minimi di incremento per il prossimo slot
            
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
                            
                            # Assegna volontario (Logica storica semplificata)
                            v_scelto = vols_liberi.pop(0) # Prende il primo disponibile per semplicità
                            
                            st.session_state.programma.append({
                                "Orario": orario_display,
                                "Cane": cane,
                                "Volontario": v_scelto,
                                "Luogo": campo_scelto,
                                "Inizio_Sort": ora_attuale_str,
                                # Campi PDF
                                "Cibo": info_cane.get('cibo', '-'),
                                "Guinzaglieria": info_cane.get('guinzaglieria', '-'),
                                "Strumenti": info_cane.get('strumenti', '-'),
                                "Attività PDF": info_cane.get('attivita', '-'),
                                "Note": info_cane.get('note', '-'),
                                "Tempo PDF": info_cane.get('tempo', '-')
                            })
                            
                            # Aggiorna max durata per sapere quando far partire il prossimo "blocco"
                            if durata_min > max_durata_turno:
                                max_durata_turno = durata_min
                            
                            cane_ok = True
                        else:
                            tentativi += 1
            
            # Avanza il tempo in base al turno più lungo generato (o minimo 30 min)
            # Aggiungiamo 5 minuti di pausa tecnica/cambio
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
        st.success("Programma generato con dettagli PDF!")
        st.rerun()

    if c_btn2.button("🗑️ Svuota", use_container_width=True):
        st.session_state.programma = []
        st.rerun()

    # 3. VISUALIZZAZIONE OTTIMIZZATA PER SMARTPHONE
    if st.session_state.programma:
        st.divider()
        st.subheader("📋 Programma Dettagliato")
        
        df_view = pd.DataFrame(st.session_state.programma).sort_values("Inizio_Sort")
        
        # Configurazione colonne per mobile:
        # Nascondiamo Inizio_Sort (tecnico)
        # Blocchiamo le prime colonne (Orario, Cane)
        # Permettiamo lo scroll sulle info aggiuntive
        
        st.data_editor(
            df_view,
            use_container_width=True, # Occupa tutto lo spazio
            hide_index=True,
            column_order=["Orario", "Cane", "Volontario", "Luogo", "Attività PDF", "Cibo", "Guinzaglieria", "Strumenti", "Note", "Tempo PDF"],
            column_config={
                "Inizio_Sort": None, # Nascondi
                "Orario": st.column_config.TextColumn("⏰ Orario", width="medium", help="Inizio e Fine turno"),
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
        st.caption("💡 Suggerimento: Su smartphone, scorri la tabella verso destra per vedere Cibo, Strumenti e Note.")

with tab_ana:
    st.subheader("📋 Anagrafica Cani")
    conn = sqlite3.connect('canile.db')
    df_db = pd.read_sql_query("SELECT * FROM anagrafica_cani", conn)
    st.dataframe(df_db, use_container_width=True, hide_index=True)
    conn.close()

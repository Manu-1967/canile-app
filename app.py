import streamlit as st
import pandas as pd
from datetime import datetime, timedelta
import PyPDF2
import re
import sqlite3
import io

# --- CONFIGURAZIONE E STILI ---
st.set_page_config(page_title="Canile Soft - Gestione Volontari", layout="wide")

# Mappa conflitti spaziali (Memoria Utente)
CONFLITTI = {
    "Lago Park": "Central Park", "Central Park": "Lago Park",
    "Peter Park": "Duca Park", "Duca Park": "Peter Park"
}

def init_db():
    conn = sqlite3.connect('canile.db')
    c = conn.cursor()
    c.execute('CREATE TABLE IF NOT EXISTS storico (data TEXT, inizio TEXT, cane TEXT, volontario TEXT, luogo TEXT)')
    c.execute('''CREATE TABLE IF NOT EXISTS anagrafica_cani 
                 (nome TEXT PRIMARY KEY, cibo TEXT, guinzaglieria TEXT, strumenti TEXT, attivita TEXT, note TEXT, tempo TEXT, livello TEXT)''')
    conn.commit(); conn.close()

def load_gsheets(sheet_name):
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

if 'programma' not in st.session_state: st.session_state.programma = []

st.title("📱 Canile Soft - Gestione Adattiva")

# Selezione Risorse
c1, c2, c3 = st.columns(3)
c_p = c1.multiselect("Cani Presenti", df_c['nome'].tolist() if not df_c.empty else [])
v_p = c2.multiselect("Volontari Presenti", df_v['nome'].tolist() if not df_v.empty else [])
# Duca Park escluso di default come da istruzioni
l_p = c3.multiselect("Campi Disponibili", [l for l in df_l['nome'].tolist() if l != "Duca Park"] if not df_l.empty else [])

tab_programma, tab_anagrafica = st.tabs(["📅 Programma", "🐕 Anagrafica"])

with tab_programma:
    # 1. INSERIMENTO MANUALE
    with st.expander("✍️ Inserimento Manuale (Priorità Alta)"):
        mc1, mc2, mc3, mc4 = st.columns(4)
        m_cane = mc1.selectbox("Cane", ["-"] + c_p)
        m_vol = mc2.selectbox("Volontario", ["-"] + v_p)
        m_luo = mc3.selectbox("Luogo", ["-"] + (df_l['nome'].tolist() if not df_l.empty else []))
        m_ora = mc4.time_input("Ora Inizio Attività", ora_i)
        
        if st.button("➕ Aggiungi Riga Manuale"):
            if m_cane != "-":
                durata_m = 30
                st.session_state.programma.append({
                    "Orario": f"{m_ora.strftime('%H:%M')} - {(datetime.combine(data_t, m_ora)+timedelta(minutes=durata_m)).strftime('%H:%M')}",
                    "Cane": m_cane, "Volontario": m_vol, "Luogo": m_luo, "Attività": "Manuale", 
                    "Inizio_Sort": m_ora.strftime('%H:%M'), "Tipo": "Manuale"
                })
                st.rerun()

    # 2. LOGICA AUTOMATICA (Tutti i volontari devono lavorare)
    c_btn1, c_btn2 = st.columns(2)

    if c_btn1.button("🤖 Completa Programma (Nessun Volontario Inattivo)", use_container_width=True):
        conn = sqlite3.connect('canile.db'); conn.row_factory = sqlite3.Row
        
        start_dt = datetime.combine(data_t, ora_i)
        end_dt = datetime.combine(data_t, ora_f)
        pasti_dt = end_dt - timedelta(minutes=30) 
        
        if not any(r.get('Attività') == 'Briefing' for r in st.session_state.programma):
            st.session_state.programma.insert(0, {
                "Orario": f"{start_dt.strftime('%H:%M')} - {(start_dt+timedelta(minutes=15)).strftime('%H:%M')}", 
                "Cane": "TUTTI", "Volontario": "TUTTI", "Luogo": "Ufficio", "Attività": "Briefing", 
                "Inizio_Sort": start_dt.strftime('%H:%M'), "Tipo": "Auto"
            })

        prog_temp = [r for r in st.session_state.programma if r.get('Attività') not in ['Briefing', 'Pasti']]
        cani_fatti = [r['Cane'] for r in prog_temp]
        cani_da_fare = [c for c in c_p if c not in cani_fatti]
        
        curr_t = start_dt + timedelta(minutes=15)
        
        while cani_da_fare and curr_t < pasti_dt:
            vols_disponibili = v_p.copy()
            campi_occupati_ora = [r['Luogo'] for r in prog_temp if r.get('Inizio_Sort') == curr_t.strftime('%H:%M')]
            
            # Calcolo campi realmente liberi e non in conflitto
            vietati = []
            for occ in campi_occupati_ora:
                if occ in CONFLITTI: vietati.append(CONFLITTI[occ])
            
            campi_liberi = [l for l in l_p if l not in campi_occupati_ora and l not in vietati]
            
            # Numero di cani che possiamo gestire in questo slot
            n_cani_slot = min(len(cani_da_fare), len(campi_liberi))
            
            if n_cani_slot > 0:
                batch_assegnazioni = []
                
                # Primo passaggio: Assegna un cane a un campo e trova il lead (storico)
                for _ in range(n_cani_slot):
                    cane = cani_da_fare.pop(0)
                    campo = campi_liberi.pop(0)
                    if campo in CONFLITTI and CONFLITTI[campo] in campi_liberi:
                        campi_liberi.remove(CONFLITTI[campo])
                    
                    # Trova il miglior volontario per questo cane
                    vols_con_punteggio = []
                    for v in vols_disponibili:
                        cnt = conn.execute("SELECT COUNT(*) FROM storico WHERE cane=? AND volontario=?", (cane, v)).fetchone()[0]
                        vols_con_punteggio.append((v, cnt))
                    vols_con_punteggio.sort(key=lambda x: x[1], reverse=True)
                    
                    lead = vols_con_punteggio[0][0]
                    vols_disponibili.remove(lead)
                    batch_assegnazioni.append({"cane": cane, "campo": campo, "lead": lead, "supporti": []})

                # Secondo passaggio: Distribuisci TUTTI i volontari rimasti tra i cani usciti
                idx = 0
                while vols_disponibili:
                    batch_assegnazioni[idx % len(batch_assegnazioni)]["supporti"].append(vols_disponibili.pop(0))
                    idx += 1
                
                # Creazione record definitivi
                for ass in batch_assegnazioni:
                    vol_str = ass["lead"]
                    if ass["supporti"]:
                        vol_str += "\n+ " + "\n+ ".join(ass["supporti"]) + " (Sup.)"
                    
                    info = conn.execute("SELECT * FROM anagrafica_cani WHERE nome=?", (ass["cane"].capitalize(),)).fetchone()
                    
                    st.session_state.programma.append({
                        "Orario": f"{curr_t.strftime('%H:%M')} - {(curr_t+timedelta(minutes=30)).strftime('%H:%M')}",
                        "Cane": ass["cane"], "Volontario": vol_str, "Luogo": ass["campo"],
                        "Cibo": info['cibo'] if info else "-", "Note": info['note'] if info else "-",
                        "Attività": info['attivita'] if info else "Uscita",
                        "Inizio_Sort": curr_t.strftime('%H:%M'), "Tipo": "Auto"
                    })

            curr_t += timedelta(minutes=30)

        # 3. Pasti (Ultimi 30 min)
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

    # --- EDITOR VISIVO ---
    if st.session_state.programma:
        st.divider()
        df_prog = pd.DataFrame(st.session_state.programma).sort_values("Inizio_Sort")
        
        df_edited = st.data_editor(
            df_prog,
            column_config={
                "Inizio_Sort": None, "Tipo": None,
                "Orario": st.column_config.TextColumn("Ora", width="small"),
                "Volontario": st.column_config.TextColumn("Volontari (Lead + Sup)", width="medium"),
                "Note": st.column_config.TextColumn("Note", width="large"),
            },
            use_container_width=True, hide_index=True, num_rows="dynamic"
        )
        st.session_state.programma = df_edited.to_dict('records')

        # Export Excel
        output = io.BytesIO()
        with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
            df_edited.drop(columns=['Inizio_Sort', 'Tipo'], errors='ignore').to_excel(writer, index=False)
        st.download_button("📊 Scarica Turno Excel", output.getvalue(), f"turno_{data_t}.xlsx", use_container_width=True)

with tab_anagrafica:
    st.subheader("📋 Database Cani")
    conn = sqlite3.connect('canile.db')
    df_db = pd.read_sql_query("SELECT * FROM anagrafica_cani", conn)
    conn.close()
    if not df_db.empty:
        st.dataframe(df_db, use_container_width=True)

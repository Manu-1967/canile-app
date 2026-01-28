import streamlit as st
import pandas as pd
from datetime import datetime, timedelta
import PyPDF2
import re
import sqlite3
import io

# --- CONFIGURAZIONE ---
st.set_page_config(page_title="Canile Soft - Smart Scheduler", layout="wide")

COLOR_MAP = {"ROSSO": 3, "GIALLO": 2, "VERDE": 1, "N/D": 0}

def init_db():
    conn = sqlite3.connect('canile.db')
    c = conn.cursor()
    c.execute('CREATE TABLE IF NOT EXISTS storico (data TEXT, inizio TEXT, cane TEXT, volontario TEXT, luogo TEXT)')
    c.execute('''CREATE TABLE IF NOT EXISTS anagrafica_cani 
                 (nome TEXT PRIMARY KEY, cibo TEXT, guinzaglieria TEXT, strumenti TEXT, attivita TEXT, note TEXT, tempo TEXT, livello TEXT)''')
    conn.commit(); conn.close()

init_db()

# --- CARICAMENTO DATI ---
def load_gsheets(sheet_name):
    url = f"https://docs.google.com/spreadsheets/d/1pcFa454IT1tlykbcK-BeAU9hnIQ_D8V_UuZaKI_KtYM/gviz/tq?tqx=out:csv&sheet={sheet_name}"
    try:
        df = pd.read_csv(url); df.columns = [c.strip().lower() for c in df.columns]
        return df.dropna(how='all')
    except: return pd.DataFrame()

df_c = load_gsheets("Cani"); df_v = load_gsheets("Volontari"); df_l = load_gsheets("Luoghi")

# --- SIDEBAR E PDF ---
with st.sidebar:
    st.header("⚙️ Configurazione")
    data_t = st.date_input("Data", datetime.today())
    ora_i = st.time_input("Inizio Turno", datetime.strptime("08:00", "%H:%M"))
    ora_f = st.time_input("Fine Turno", datetime.strptime("12:00", "%H:%M"))
    st.divider()
    files = st.file_uploader("Aggiorna Anagrafica (PDF)", accept_multiple_files=True, type="pdf")
    if files:
        conn = sqlite3.connect('canile.db')
        for f in files:
            reader = PyPDF2.PdfReader(f)
            text = "".join([p.extract_text() for p in reader.pages])
            d = {l: "N/D" for l in ['CIBO', 'GUINZAGLIERIA', 'STRUMENTI', 'ATTIVITÀ', 'NOTE', 'TEMPO', 'LIVELLO']}
            for l in d.keys():
                match = re.search(rf"{l}[:\s\n]+(.*?)(?=\n(?:CIBO|GUINZAGLIERIA|STRUMENTI|ATTIVITÀ|NOTE|TEMPO|LIVELLO)[:\s]|$)", text, re.DOTALL | re.IGNORECASE)
                if match: d[l] = match.group(1).strip()
            conn.execute("INSERT OR REPLACE INTO anagrafica_cani VALUES (?,?,?,?,?,?,?,?)", 
                         (f.name.split('.')[0].strip().capitalize(), d['CIBO'], d['GUINZAGLIERIA'], d['STRUMENTI'], d['ATTIVITÀ'], d['NOTE'], d['TEMPO'], d['LIVELLO']))
        conn.commit(); conn.close(); st.success("PDF caricati!")

# --- LOGICA DI SCHEDULING INTELLIGENTE ---
if 'programma' not in st.session_state: st.session_state.programma = []

st.subheader("📋 Gestione Turno Intelligente")
c1, c2, c3 = st.columns(3)
c_p = c1.multiselect("Cani", df_c['nome'].tolist() if not df_c.empty else [])
v_p = c2.multiselect("Volontari", df_v['nome'].tolist() if not df_v.empty else [])
l_p = c3.multiselect("Campi (No Duca)", [l for l in df_l['nome'].tolist() if l != "Duca Park"] if not df_l.empty else [])

# 1. AGGIUNTA MANUALE
with st.expander("✍️ Inserimento Manuale"):
    m1, m2, m3, m4 = st.columns(4)
    mc = m1.selectbox("Cane", ["-"] + c_p)
    mv = m2.selectbox("Volontario", ["-"] + v_p)
    ml = m3.selectbox("Campo", ["-"] + (df_l['nome'].tolist() if not df_l.empty else []))
    mi = m4.time_input("Inizio", ora_i)
    if st.button("Inserisci"):
        st.session_state.programma.append({
            "Orario": f"{mi.strftime('%H:%M')} - {(datetime.combine(data_t, mi)+timedelta(minutes=30)).strftime('%H:%M')}",
            "Cane": mc, "Volontario": mv, "Luogo": ml, "Inizio_Sort": mi.strftime('%H:%M'), "Manuale": True
        })
        st.rerun()

# 2. MOTORE AUTOMATICO
if st.button("🤖 Genera/Completa con Logica Timeline", use_container_width=True):
    # Setup Timeline
    start_dt = datetime.combine(data_t, ora_i)
    limit_dt = datetime.combine(data_t, ora_f) - timedelta(minutes=30)
    
    # Tracciamento disponibilità (Nome -> Orario in cui torna libero)
    v_free_at = {v: start_dt + timedelta(minutes=15) for v in v_p}
    l_free_at = {l: start_dt + timedelta(minutes=15) for l in l_p}
    
    # Includi le righe manuali nella timeline per evitare sovrapposizioni
    new_prog = []
    # Briefing
    new_prog.append({"Orario": f"{ora_i.strftime('%H:%M')} - {(start_dt+timedelta(minutes=15)).strftime('%H:%M')}", "Cane": "TUTTI", "Volontario": "TUTTI", "Luogo": "Ufficio", "Inizio_Sort": ora_i.strftime('%H:%M')})
    
    for r in st.session_state.programma:
        if r.get("Manuale"):
            new_prog.append(r)
            # Aggiorna timeline per i manuali
            fine_m = datetime.strptime(r['Orario'].split(" - ")[1], "%H:%M").time()
            dt_fine_m = datetime.combine(data_t, fine_m)
            if r['Volontario'] in v_free_at: v_free_at[r['Volontario']] = dt_fine_m
            if r['Luogo'] in l_free_at: l_free_at[r['Luogo']] = dt_fine_m

    cani_fatti = [r['Cane'] for r in new_prog]
    cani_restanti = [c for c in c_p if c not in cani_fatti]
    
    conn = sqlite3.connect('canile.db'); conn.row_factory = sqlite3.Row
    
    # Ciclo Temporale (ogni 15 min controlla chi è libero)
    curr_t = start_dt + timedelta(minutes=15)
    while cani_restanti and curr_t < limit_dt:
        # Trova volontari e campi liberi in QUESTO momento
        vols_liberi = [v for v, t in v_free_at.items() if t <= curr_t]
        campi_liberi = [l for l in l_free_at.items() if l[1] <= curr_t]
        
        while cani_restanti and campi_liberi and vols_liberi:
            cane = cani_restanti.pop(0)
            info = conn.execute("SELECT * FROM anagrafica_cani WHERE nome=?", (cane.capitalize(),)).fetchone()
            cane_lvl = COLOR_MAP.get(str(info['livello']).upper(), 0) if info else 1
            durata = int(re.search(r'\d+', info['tempo']).group()) if info and info['tempo'] != "N/D" else 30
            
            # 1. Trova il miglior volontario principale per livello e storico
            vols_idonei = []
            for vn in vols_liberi:
                v_row = df_v[df_v['nome'] == vn].iloc[0]
                v_lvl = COLOR_MAP.get(str(v_row['livello']).upper(), 1)
                if v_lvl >= cane_lvl:
                    st_cnt = conn.execute("SELECT COUNT(*) FROM storico WHERE cane=? AND volontario=?", (cane, vn)).fetchone()[0]
                    vols_idonei.append((vn, st_cnt))
            
            if not vols_idonei: # Se nessuno è idoneo, prendi il più alto disponibile per sicurezza
                vols_idonei = [(vn, 0) for vn in vols_liberi]
            
            vols_idonei.sort(key=lambda x: x[1], reverse=True)
            v_main = vols_idonei[0][0]
            vols_liberi.remove(v_main)
            v_final = v_main
            
            # 2. Assegna supporti (se ci sono troppi volontari rispetto ai cani rimasti)
            while len(vols_liberi) > len(cani_restanti) and vols_liberi:
                v_sup = vols_liberi.pop(0)
                v_final += f" + {v_sup} (Sup.)"
                v_free_at[v_sup] = curr_t + timedelta(minutes=durata)

            # 3. Assegna campo e aggiorna timeline
            luogo_nome, _ = campi_liberi.pop(0)
            new_prog.append({
                "Orario": f"{curr_t.strftime('%H:%M')} - {(curr_t+timedelta(minutes=durata)).strftime('%H:%M')}",
                "Cane": cane, "Volontario": v_final, "Luogo": luogo_nome, "Inizio_Sort": curr_t.strftime('%H:%M'),
                "Cibo": info['cibo'] if info else "-", "Note": info['note'] if info else "-", "Attività": info['attivita'] if info else "Uscita"
            })
            v_free_at[v_main] = curr_t + timedelta(minutes=durata)
            l_free_at[luogo_nome] = curr_t + timedelta(minutes=durata)

        curr_t += timedelta(minutes=15)

    # 3. Pasti
    pasti_t = limit_dt
    new_prog.append({"Orario": f"{pasti_t.strftime('%H:%M')} - {ora_f.strftime('%H:%M')}", "Cane": "TUTTI", "Volontario": "TUTTI", "Luogo": "Box", "Attività": "Pasti", "Inizio_Sort": pasti_t.strftime('%H:%M')})
    st.session_state.programma = new_prog
    conn.close(); st.rerun()

# --- EDITOR FINALE ---
if st.session_state.programma:
    df_res = pd.DataFrame(st.session_state.programma).sort_values("Inizio_Sort")
    df_mod = st.data_editor(df_res.drop(columns=['Inizio_Sort', 'Manuale'], errors='ignore'), use_container_width=True, hide_index=True)
    st.session_state.programma = df_mod.to_dict('records')
    
    if st.button("🗑️ Reset Tutto"): st.session_state.programma = []; st.rerun()

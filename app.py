import streamlit as st
import pandas as pd
from datetime import datetime, timedelta
import PyPDF2
import re
import sqlite3
import io

# --- CONFIGURAZIONE ---
st.set_page_config(page_title="Canile Soft - Safety Scheduler", layout="wide")

COLOR_MAP = {"ROSSO": 3, "GIALLO": 2, "VERDE": 1, "N/D": 0}
# Definizione dei conflitti tra campi
CONFLITTI_CAMPI = {
    "Lago Park": "Central Park",
    "Central Park": "Lago Park",
    "Peter Park": "Duca Park",
    "Duca Park": "Peter Park"
}

def init_db():
    conn = sqlite3.connect('canile.db')
    c = conn.cursor()
    c.execute('CREATE TABLE IF NOT EXISTS storico (data TEXT, inizio TEXT, cane TEXT, volontario TEXT, luogo TEXT)')
    c.execute('''CREATE TABLE IF NOT EXISTS anagrafica_cani 
                 (nome TEXT PRIMARY KEY, cibo TEXT, guinzaglieria TEXT, strumenti TEXT, attivita TEXT, note TEXT, tempo TEXT, livello TEXT)''')
    conn.commit(); conn.close()

init_db()

def load_gsheets(sheet_name):
    url = f"https://docs.google.com/spreadsheets/d/1pcFa454IT1tlykbcK-BeAU9hnIQ_D8V_UuZaKI_KtYM/gviz/tq?tqx=out:csv&sheet={sheet_name}"
    try:
        df = pd.read_csv(url); df.columns = [c.strip().lower() for c in df.columns]
        return df.dropna(how='all')
    except: return pd.DataFrame()

df_c = load_gsheets("Cani"); df_v = load_gsheets("Volontari"); df_l = load_gsheets("Luoghi")

if 'programma' not in st.session_state: st.session_state.programma = []

st.title("🛡️ Canile Soft - Scheduler con Sicurezza Campi")

# --- INTERFACCIA INPUT ---
c1, c2, c3 = st.columns(3)
with c1: c_p = st.multiselect("Cani pronti", df_c['nome'].tolist() if not df_c.empty else [])
with c2: v_p = st.multiselect("Volontari presenti", df_v['nome'].tolist() if not df_v.empty else [])
with c3: l_p = st.multiselect("Campi agibili (Duca escluso auto)", [l for l in df_l['nome'].tolist() if l != "Duca Park"] if not df_l.empty else [])

# 1. INSERIMENTO MANUALE
with st.expander("✍️ Inserimento Manuale"):
    m1, m2, m3, m4, m5 = st.columns(5)
    mc = m1.selectbox("Cane", ["-"] + c_p)
    mv = m2.selectbox("Volontario", ["-"] + v_p)
    ml = m3.selectbox("Campo", ["-"] + (df_l['nome'].tolist() if not df_l.empty else []))
    mi = m4.time_input("Inizio", datetime.strptime("08:15", "%H:%M"))
    md = m5.number_input("Durata (min)", 15, 90, 30)
    if st.button("Aggiungi riga"):
        mf = (datetime.combine(datetime.today(), mi) + timedelta(minutes=md)).time()
        st.session_state.programma.append({
            "Orario": f"{mi.strftime('%H:%M')} - {mf.strftime('%H:%M')}",
            "Cane": mc, "Volontario": mv, "Luogo": ml, "Inizio_Sort": mi.strftime('%H:%M'), "Manuale": True, "Durata_Min": md
        })
        st.rerun()

# 2. MOTORE AUTOMATICO CON CONFLITTI ADIACENTI
if st.button("🤖 Genera Programma Sicuro", use_container_width=True):
    # Sidebar params
    start_turn = datetime.combine(datetime.today(), datetime.strptime("08:00", "%H:%M").time())
    limit_turn = datetime.combine(datetime.today(), datetime.strptime("12:00", "%H:%M").time()) - timedelta(minutes=30)
    
    v_free_at = {v: start_turn + timedelta(minutes=15) for v in v_p}
    l_free_at = {l: start_turn + timedelta(minutes=15) for l in (df_l['nome'].tolist() if not df_l.empty else [])}
    
    final_prog = []
    # Briefing
    final_prog.append({"Orario": "08:00 - 08:15", "Cane": "TUTTI", "Volontario": "TUTTI", "Luogo": "Ufficio", "Inizio_Sort": "08:00"})
    
    # Integrazione Manuali
    for r in st.session_state.programma:
        if r.get("Manuale"):
            final_prog.append(r)
            f_m = datetime.strptime(r['Orario'].split(" - ")[1], "%H:%M")
            dt_f_m = datetime.combine(datetime.today(), f_m.time())
            if r['Volontario'] in v_free_at: v_free_at[r['Volontario']] = dt_f_m
            if r['Luogo'] in l_free_at: l_free_at[r['Luogo']] = dt_f_m

    cani_todo = [c for c in c_p if c not in [r['Cane'] for r in final_prog]]
    conn = sqlite3.connect('canile.db'); conn.row_factory = sqlite3.Row
    
    curr_t = start_turn + timedelta(minutes=15)
    while cani_todo and curr_t < limit_turn:
        vols_lib = [v for v, t in v_free_at.items() if t <= curr_t]
        
        # Filtro Campi con logica adiacenza
        campi_occupati_ora = [r['Luogo'] for r in final_prog if datetime.strptime(r['Orario'].split(" - ")[0], "%H:%M").time() <= curr_t.time() < datetime.strptime(r['Orario'].split(" - ")[1], "%H:%M").time()]
        
        campi_liberi = []
        for l in l_p:
            if l_free_at[l] <= curr_t and l not in campi_occupati_ora:
                conf = CONFLITTI_CAMPI.get(l)
                if conf not in campi_occupati_ora:
                    campi_liberi.append(l)

        while cani_todo and campi_liberi and vols_lib:
            cane = cani_todo.pop(0)
            info = conn.execute("SELECT * FROM anagrafica_cani WHERE nome=?", (cane.capitalize(),)).fetchone()
            c_lvl = COLOR_MAP.get(str(info['livello']).upper(), 1) if info else 1
            dur = int(re.search(r'\d+', info['tempo']).group()) if info and info['tempo'] != "N/D" else 30
            
            # Selezione Volontario per Colore
            v_main = None
            for vn in vols_lib:
                v_lvl = COLOR_MAP.get(str(df_v[df_v['nome']==vn]['livello'].values[0]).upper(), 1) if not df_v[df_v['nome']==vn].empty else 1
                if v_lvl >= c_lvl:
                    v_main = vn; break
            
            if not v_main: v_main = vols_lib[0] # Fallback
            vols_lib.remove(v_main)
            v_str = v_main
            
            # Supporto
            while len(vols_lib) > len(cani_todo) and vols_lib:
                v_s = vols_lib.pop(0)
                v_str += f" + {v_s} (Sup.)"
                v_free_at[v_s] = curr_t + timedelta(minutes=dur)

            campo_scelto = campi_liberi.pop(0)
            # Aggiunta riga e blocco dei campi adiacenti nella timeline
            final_prog.append({
                "Orario": f"{curr_t.strftime('%H:%M')} - {(curr_t+timedelta(minutes=dur)).strftime('%H:%M')}",
                "Cane": cane, "Volontario": v_str, "Luogo": campo_scelto, "Inizio_Sort": curr_t.strftime('%H:%M'),
                "Cibo": info['cibo'] if info else "-", "Note": info['note'] if info else "-", "Attività": info['attivita'] if info else "Uscita"
            })
            v_free_at[v_main] = curr_t + timedelta(minutes=dur)
            l_free_at[campo_scelto] = curr_t + timedelta(minutes=dur)
            # Nota: il conflitto adiacente viene ricalcolato dinamicamente ad ogni iterazione di curr_t

        curr_t += timedelta(minutes=15)

    # Pasti
    pasti_t = limit_turn
    final_prog.append({"Orario": f"{pasti_t.strftime('%H:%M')} - 12:00", "Cane": "TUTTI", "Volontario": "TUTTI", "Luogo": "Box", "Attività": "Pasti", "Inizio_Sort": pasti_t.strftime('%H:%M')})
    st.session_state.programma = final_prog
    conn.close(); st.rerun()

# --- EDITOR E DOWNLOAD ---
if st.session_state.programma:
    df_f = pd.DataFrame(st.session_state.programma).sort_values("Inizio_Sort")
    df_edit = st.data_editor(df_f.drop(columns=['Inizio_Sort','Manuale','Durata_Min'], errors='ignore'), use_container_width=True, hide_index=True)
    st.session_state.programma = df_edit.to_dict('records')
    
    if st.button("🗑️ Reset"): st.session_state.programma = []; st.rerun()

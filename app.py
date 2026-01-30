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
    # Storico per statistiche e affinità volontario-cane
    c.execute('''CREATE TABLE IF NOT EXISTS storico 
                 (data TEXT, inizio TEXT, cane TEXT, volontario TEXT, luogo TEXT)''')
    c.execute('''CREATE TABLE IF NOT EXISTS anagrafica_cani 
                 (nome TEXT PRIMARY KEY, cibo TEXT, guinzaglieria TEXT, strumenti TEXT, 
                  attivita TEXT, note TEXT, tempo TEXT, livello TEXT)''')
    conn.commit()
    conn.close()

def load_gsheets(sheet_name):
    """Carica i dati dai fogli Google in modo dinamico."""
    url = f"https://docs.google.com/spreadsheets/d/1pcFa454IT1tlykbcK-BeAU9hnIQ_D8V_UuZaKI_KtYM/gviz/tq?tqx=out:csv&sheet={sheet_name}"
    try:
        df = pd.read_csv(url)
        df.columns = [c.strip().lower() for c in df.columns]
        if sheet_name == "Luoghi":
            if 'automatico' not in df.columns: df['automatico'] = 'sì'
            if 'adiacente' not in df.columns: df['adiacente'] = ''
        if sheet_name == "Cani":
            if 'reattività' not in df.columns: df['reattività'] = 0
            df['reattività'] = pd.to_numeric(df['reattività'], errors='coerce').fillna(0)
        return df.dropna(how='all')
    except:
        return pd.DataFrame()

def get_reattivita_cane(nome_cane, df_cani):
    if df_cani.empty or 'reattività' not in df_cani.columns: return 0
    riga = df_cani[df_cani['nome'] == nome_cane]
    return float(riga.iloc[0]['reattività']) if not riga.empty else 0

def get_campi_adiacenti(campo, df_luoghi):
    """Recupera i vicini definiti nel foglio Google."""
    if df_luoghi.empty or 'adiacente' not in df_luoghi.columns: return []
    riga = df_luoghi[df_luoghi['nome'] == campo]
    if not riga.empty:
        adiacenti_str = str(riga.iloc[0]['adiacente']).strip()
        if adiacenti_str and adiacenti_str != 'nan':
            return [c.strip() for c in adiacenti_str.split(',') if c.strip()]
    return []

def campo_valido_per_reattivita(cane, campo, turni_attuali, ora_attuale_str, df_cani, df_luoghi):
    """Controlla se il campo è sicuro in base alla reattività del cane."""
    reattivita_cane_corrente = get_reattivita_cane(cane, df_cani)
    campi_adiacenti = get_campi_adiacenti(campo, df_luoghi)
    
    for turno in turni_attuali:
        if turno["Orario"] == ora_attuale_str:
            if turno["Luogo"] in campi_adiacenti:
                cane_adiacente = turno["Cane"]
                if cane_adiacente in ["TUTTI", "Da assegnare"]: continue
                reattivita_cane_adiacente = get_reattivita_cane(cane_adiacente, df_cani)
                if reattivita_cane_corrente > 5 or reattivita_cane_adiacente > 5:
                    return False
    return True

def salva_programma_nel_db(programma, data_sel):
    """Archivia il programma definitivo per le statistiche future."""
    conn = sqlite3.connect('canile.db')
    c = conn.cursor()
    dt_str = data_sel.strftime('%Y-%m-%d')
    c.execute("DELETE FROM storico WHERE data=?", (dt_str,))
    for t in programma:
        if t["Cane"] not in ["TUTTI", "Da assegnare"]:
            # Gestione volontari multipli o singoli
            vols = t["Volontario"].replace('+', ',').split(',')
            for v in vols:
                if v.strip():
                    c.execute("INSERT INTO storico VALUES (?,?,?,?,?)", 
                              (dt_str, t["Orario"], t["Cane"], v.strip(), t["Luogo"]))
    conn.commit()
    conn.close()

init_db()

# --- INTERFACCIA ---
st.title("🐾 Programma Canile - Gestione Dinamica")

with st.sidebar:
    st.header("⚙️ Configurazione")
    data_t = st.date_input("Data Turno", datetime.today())
    ora_i = st.time_input("Inizio", datetime.strptime("08:00", "%H:%M"))
    ora_f = st.time_input("Fine", datetime.strptime("12:00", "%H:%M"))
    st.divider()
    # (Il parsing PDF rimane come nella versione precedente)
    pdf_files = st.file_uploader("📂 Carica PDF Cani", accept_multiple_files=True, type="pdf")

df_c = load_gsheets("Cani")
df_v = load_gsheets("Volontari")
df_l = load_gsheets("Luoghi")

if 'programma' not in st.session_state: st.session_state.programma = []

tab_prog, tab_ana, tab_stats = st.tabs(["📅 Programma", "📋 Anagrafica", "📊 Statistiche & Storico"])

with tab_prog:
    c_p = st.multiselect("🐕 Cani in turno", df_c['nome'].tolist() if not df_c.empty else [])
    v_p = st.multiselect("👤 Volontari presenti", df_v['nome'].tolist() if not df_v.empty else [])
    l_p = st.multiselect("📍 Luoghi disponibili", df_l['nome'].tolist() if not df_l.empty else [])

    # Inserimento Manuale
    with st.expander("✏️ Inserimento Manuale"):
        col1, col2 = st.columns(2)
        m_cane = col1.selectbox("Cane", ["-"] + c_p)
        m_luo = col2.selectbox("Luogo", ["-"] + l_p)
        m_vols = st.multiselect("Volontari", v_p)
        m_ora = st.time_input("Ora Inizio", ora_i)
        if st.button("➕ Aggiungi Turno Manuale"):
            st.session_state.programma.append({
                "Orario": m_ora.strftime('%H:%M'), "Cane": m_cane, 
                "Volontario": ", ".join(m_vols), "Luogo": m_luo, 
                "Attività": "Manuale", "Inizio_Sort": m_ora.strftime('%H:%M')
            })
            st.rerun()

    c1, c2, c3 = st.columns(3)
    if c1.button("🤖 Genera / Completa Automatico", use_container_width=True):
        conn = sqlite3.connect('canile.db'); conn.row_factory = sqlite3.Row
        start_dt = datetime.combine(data_t, ora_i)
        end_dt = datetime.combine(data_t, ora_f)
        pasti_dt = end_dt - timedelta(minutes=30) # Alimentazione ultimi 30 min
        
        manuali = [r for r in st.session_state.programma if r.get("Attività") == "Manuale"]
        st.session_state.programma = [{"Orario": start_dt.strftime('%H:%M'), "Cane": "TUTTI", "Volontario": "TUTTI", "Luogo": "Ufficio", "Attività": "Briefing", "Inizio_Sort": start_dt.strftime('%H:%M')}]
        
        cani_fatti = [m["Cane"] for m in manuali]
        cani_restanti = [c for c in c_p if c not in cani_fatti]
        curr_t = start_dt + timedelta(minutes=15)
        
        luoghi_ok = df_l[(df_l['nome'].isin(l_p)) & (df_l['automatico'].str.lower() == 'sì')]['nome'].tolist()

        while cani_restanti and curr_t < pasti_dt:
            ora_s = curr_t.strftime('%H:%M')
            v_liberi = [v for v in v_p if v not in [vv for m in manuali if m["Orario"]==ora_s for vv in m["Volontario"].split(",")]]
            l_liberi = [l for l in luoghi_ok if l not in [m["Luogo"] for m in manuali if m["Orario"]==ora_s]]
            
            for _ in range(min(len(cani_restanti), len(l_liberi))):
                if not v_liberi: break
                for idx, cane in enumerate(cani_restanti):
                    campo_scelto = next((ll for ll in l_liberi if campo_valido_per_reattivita(cane, ll, st.session_state.programma + manuali, ora_s, df_c, df_l)), None)
                    if campo_scelto:
                        cani_restanti.pop(idx)
                        l_liberi.remove(campo_scelto)
                        # Ranking basato sullo storico per affinità
                        v_scores = [(v, conn.execute("SELECT COUNT(*) FROM storico WHERE cane=? AND volontario=?", (cane, v)).fetchone()[0]) for v in v_liberi]
                        v_scores.sort(key=lambda x: x[1], reverse=True)
                        lead = v_scores[0][0]
                        v_liberi.remove(lead)
                        st.session_state.programma.append({"Orario": ora_s, "Cane": cane, "Volontario": lead, "Luogo": campo_scelto, "Attività": "Auto", "Inizio_Sort": ora_s})
                        break
            curr_t += timedelta(minutes=45)
        
        st.session_state.programma.extend(manuali)
        st.session_state.programma.append({"Orario": pasti_dt.strftime('%H:%M'), "Cane": "TUTTI", "Volontario": "TUTTI", "Luogo": "Box", "Attività": "Pasti", "Inizio_Sort": pasti_dt.strftime('%H:%M')})
        conn.close()
        st.rerun()

    if c2.button("💾 Conferma e Salva Storico", type="primary", use_container_width=True):
        salva_programma_nel_db(st.session_state.programma, data_t)
        st.success(f"Dati salvati in {st.session_state.programma[0]['Orario']} per la giornata!")

    if c3.button("🗑️ Svuota Tutto", use_container_width=True):
        st.session_state.programma = []
        st.rerun()

    if st.session_state.programma:
        df_p = pd.DataFrame(st.session_state.programma).sort_values("Inizio_Sort")
        st.data_editor(df_p, use_container_width=True, hide_index=True)

with tab_stats:
    st.header("📊 Statistiche Lavoro")
    conn = sqlite3.connect('canile.db')
    
    col_x, col_y = st.columns(2)
    d_ini = col_x.date_input("Data Inizio", datetime.today() - timedelta(days=30))
    d_end = col_y.date_input("Data Fine", datetime.today())
    
    filtro = st.segmented_control("Analizza:", ["Volontario", "Cane", "Luogo"], default="Volontario")
    
    query = "SELECT * FROM storico WHERE data BETWEEN ? AND ?"
    df_h = pd.read_sql_query(query, conn, params=(d_ini.strftime('%Y-%m-%d'), d_end.strftime('%Y-%m-%d')))
    
    if not df_h.empty:
        if filtro == "Volontario":
            scelta = st.selectbox("Seleziona Volontario", sorted(df_h['volontario'].unique()))
            res = df_h[df_h['volontario'] == scelta]
            st.metric("Turni totali", len(res))
            st.bar_chart(res['cane'].value_counts())
            st.dataframe(res, hide_index=True)
        elif filtro == "Cane":
            scelta = st.selectbox("Seleziona Cane", sorted(df_h['cane'].unique()))
            res = df_h[df_h['cane'] == scelta]
            st.metric("Uscite totali", len(res))
            st.bar_chart(res['volontario'].value_counts())
            st.dataframe(res, hide_index=True)
        else:
            scelta = st.selectbox("Seleziona Luogo", sorted(df_h['luogo'].unique()))
            res = df_h[df_h['luogo'] == scelta]
            st.metric("Utilizzi totali", len(res))
            st.bar_chart(res['cane'].value_counts())
            st.dataframe(res, hide_index=True)
    else:
        st.warning("Nessun dato trovato nel database per questo periodo.")
    conn.close()

with tab_ana:
    conn = sqlite3.connect('canile.db')
    df_db = pd.read_sql_query("SELECT * FROM anagrafica_cani", conn)
    st.dataframe(df_db, use_container_width=True, hide_index=True)
    conn.close()

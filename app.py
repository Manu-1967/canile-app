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
    # Anagrafica basata sui titoli del PDF
    c.execute('''CREATE TABLE IF NOT EXISTS anagrafica_cani 
                 (nome TEXT PRIMARY KEY, cibo TEXT, guinzaglieria TEXT, strumenti TEXT, 
                  attivita TEXT, note TEXT, tempo TEXT, livello TEXT)''')
    conn.commit()
    conn.close()

def parse_dog_pdf(uploaded_file):
    reader = PyPDF2.PdfReader(uploaded_file)
    text = ""

    for page in reader.pages:
        text += page.extract_text() + "\n"

    lines = [l.strip() for l in text.splitlines() if l.strip()]

    dati = {
        "nome": uploaded_file.name.replace(".pdf", "").upper(),
        "cibo": "",
        "guinzaglieria": "",
        "strumenti": "",
        "attivita": "",
        "note": "",
        "tempo": ""
    }

    for line in lines:
        u = line.upper()
        if u.startswith("CIBO"):
            dati["cibo"] = line.replace("CIBO", "").strip()
        elif u.startswith("GUINZAGLIERIA"):
            dati["guinzaglieria"] = line.replace("GUINZAGLIERIA", "").strip()
        elif u.startswith("STRUMENTI"):
            dati["strumenti"] = line.replace("STRUMENTI", "").strip()
        elif u.startswith("ATTIV"):
            dati["attivita"] = line.split(" ", 1)[1].strip()
        elif u.startswith("NOTE"):
            dati["note"] = line.replace("NOTE", "").strip()
        elif u.startswith("TEMPO"):
            dati["tempo"] = line.replace("TEMPO", "").strip()

    return dati

def salva_anagrafica(dati):
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
    conn = sqlite3.connect("canile.db")
    df = pd.read_sql("SELECT * FROM anagrafica_cani", conn)
    conn.close()

    file_excel = "programma_volontari.xlsx"
    df.to_excel(file_excel, index=False)

    return file_excel

def genera_pdf_volontari():
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
        if turno["Orario"] == ora_attuale_str:
            if turno["Luogo"] in campi_adiacenti:
                cane_adiacente = turno["Cane"]
                if cane_adiacente in ["TUTTI", "Da assegnare"]: continue
                reattivita_cane_adiacente = get_reattivita_cane(cane_adiacente, df_cani)
                if reattivita_cane_corrente > 5 or reattivita_cane_adiacente > 5:
                    return False
    return True

def salva_programma_nel_db(programma, data_sel):
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

# Inizializzazione DB e sessione
init_db()
if 'programma' not in st.session_state: st.session_state.programma = []

# --- INTERFACCIA ---
st.title("🐾 Programma Canile - Gestione Dinamica")

with st.sidebar:
    st.header("⚙️ Configurazione")
    data_t = st.date_input("Data Turno", datetime.today())
    ora_i = st.time_input("Ora Inizio", datetime.strptime("08:00", "%H:%M"))
    ora_f = st.time_input("Ora Fine", datetime.strptime("12:00", "%H:%M"))
    st.divider()
    
    st.header("📂 Importazione PDF")
    pdf_files = st.file_uploader("Carica PDF Cani", accept_multiple_files=True, type="pdf")
    if pdf_files:
        if st.button("Aggiorna Anagrafica da PDF", use_container_width=True):
            for pdf in pdf_files:
                dati = parse_dog_pdf(pdf)
                salva_anagrafica(dati)
            st.success(f"Aggiornati {len(pdf_files)} cani!")
            st.rerun()

df_c = load_gsheets("Cani")
df_v = load_gsheets("Volontari")
df_l = load_gsheets("Luoghi")

tab_prog, tab_ana, tab_stats = st.tabs(["📅 Programma", "📋 Anagrafica Cani", "📊 Statistiche"])

with tab_prog:
    c_p = st.multiselect("🐕 Cani in turno", df_c['nome'].tolist() if not df_c.empty else [])
    v_p = st.multiselect("👤 Volontari presenti", df_v['nome'].tolist() if not df_v.empty else [])
    l_p = st.multiselect("📍 Luoghi disponibili", df_l['nome'].tolist() if not df_l.empty else [])

    with st.expander("✏️ Inserimento Manuale"):
        col1, col2 = st.columns(2)
        m_cane = col1.selectbox("Seleziona Cane", ["-"] + c_p)
        m_luo = col2.selectbox("Seleziona Luogo", ["-"] + l_p)
        m_vols = st.multiselect("Seleziona Volontari", v_p)
        m_ora = st.time_input("Orario Inizio", ora_i)
        if st.button("➕ Aggiungi Turno"):
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
        pasti_dt = end_dt - timedelta(minutes=30)
        
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
                    # Controllo reattività
                    if campo_valido_per_reattivita(cane, l_liberi[0], st.session_state.programma + manuali, ora_s, df_c, df_l):
                        campo_scelto = l_liberi.pop(0)
                        cani_restanti.pop(idx)
                        
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
        st.success("Programma salvato con successo!")

    if c3.button("🗑️ Svuota Tutto", use_container_width=True):
        st.session_state.programma = []
        st.rerun()

    if st.session_state.programma:
        df_p = pd.DataFrame(st.session_state.programma).sort_values("Inizio_Sort")
        st.data_editor(df_p, use_container_width=True, hide_index=True)

with tab_ana:
    # st.header("📋 Database Anagrafica Cani")
    # conn = sqlite3.connect('canile.db')
    # df_db = pd.read_sql_query("SELECT * FROM anagrafica_cani", conn)
    # conn.close()
    # if not df_db.empty:
      #   st.write("Dati estratti dai PDF caricati:")
      #   st.dataframe(df_db, use_container_width=True, hide_index=True)
    # else:
      #   st.info("Nessun cane in anagrafica. Carica i PDF dalla barra laterale.")

    st.header("Caricamento anagrafiche cani")

    pdf_files = st.file_uploader(
        "Carica uno o più PDF anagrafica",
        type="pdf",
        accept_multiple_files=True
)

if pdf_files:
    successi = 0

    for pdf in pdf_files:
        try:
            dati = parse_dog_pdf(pdf)
            salva_anagrafica(dati)
            successi += 1
        except Exception as e:
            st.error(f"Errore con {pdf.name}: {e}")

    st.success(f"{successi} anagrafiche caricate correttamente 🐕")

    
    # st.header("Carica anagrafica cane")

    # pdf_file = st.file_uploader("Carica PDF cane", type="pdf")

    # if pdf_file:
        # dati = parse_dog_pdf(pdf_file)
        # salva_anagrafica(dati)

        # st.success(f"Anagrafica {dati['nome']} caricata correttamente")

        # if st.button("Genera programma volontari"):
         # excel = genera_excel_volontari()
         # pdf = genera_pdf_volontari()

            # st.download_button("Scarica Excel", open(excel, "rb"), file_name=excel)
            # st.download_button("Scarica PDF", open(pdf, "rb"), file_name=pdf)


with tab_stats:
    st.header("📊 Statistiche Storiche")
    conn = sqlite3.connect('canile.db')
    col_a, col_b = st.columns(2)
    d_ini = col_a.date_input("Inizio Periodo", datetime.today() - timedelta(days=30))
    d_end = col_b.date_input("Fine Periodo", datetime.today())
    
    query = "SELECT * FROM storico WHERE data BETWEEN ? AND ?"
    df_h = pd.read_sql_query(query, conn, params=(d_ini.strftime('%Y-%m-%d'), d_end.strftime('%Y-%m-%d')))
    
    if not df_h.empty:
        filtro = st.radio("Filtra per:", ["Volontario", "Cane"], horizontal=True)
        ogg = st.selectbox(f"Seleziona {filtro}", sorted(df_h[filtro.lower()].unique()))
        res = df_h[df_h[filtro.lower()] == ogg]
        st.metric(f"Attività totali per {ogg}", len(res))
        st.dataframe(res, hide_index=True)
    else:
        st.warning("Nessun dato presente per le date selezionate.")
    conn.close()

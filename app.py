import streamlit as st
import pandas as pd
from datetime import datetime, timedelta
import PyPDF2
import re
import sqlite3
import io

# --- CONFIGURAZIONE ---
st.set_page_config(page_title="Canile Soft - Dashboard", layout="wide")

SHEET_ID = "1pcFa454IT1tlykbcK-BeAU9hnIQ_D8V_UuZaKI_KtYM"

# --- LOGICA ESTRAZIONE PDF ---
def extract_pdf_data(uploaded_file):
    try:
        reader = PyPDF2.PdfReader(uploaded_file)
        text = "".join([page.extract_text() + "\n" for page in reader.pages])
        labels = ['CIBO', 'GUINZAGLIERIA', 'STRUMENTI', 'ATTIVITÀ', 'NOTE', 'TEMPO']
        extracted = {label: "N/D" for label in labels}
        for label in labels:
            altre = "|".join([l for l in labels if l != label])
            pattern = rf"{label}[:\s\n]+(.*?)(?=\n(?:{altre})[:\s]|$)"
            match = re.search(pattern, text, re.DOTALL | re.IGNORECASE)
            if match: extracted[label] = match.group(1).strip()
        return extracted
    except: return None

# --- DATABASE ---
def init_db():
    conn = sqlite3.connect('canile.db')
    c = conn.cursor()
    c.execute('CREATE TABLE IF NOT EXISTS storico (data TEXT, inizio TEXT, fine TEXT, cane TEXT, volontario TEXT, luogo TEXT)')
    c.execute('''CREATE TABLE IF NOT EXISTS anagrafica_cani 
                 (nome TEXT PRIMARY KEY, cibo TEXT, guinzaglieria TEXT, 
                  strumenti TEXT, attivita TEXT, note TEXT, tempo TEXT)''')
    conn.commit(); conn.close()

def load_data(sheet_name):
    url = f"https://docs.google.com/spreadsheets/d/{SHEET_ID}/gviz/tq?tqx=out:csv&sheet={sheet_name}"
    try:
        df = pd.read_csv(url)
        df.columns = [c.strip().lower() for c in df.columns]
        return df.dropna(how='all')
    except: return pd.DataFrame(columns=['nome'])

init_db()

# --- NAVIGAZIONE ---
menu = st.sidebar.radio("Navigazione", ["📅 Gestione Turno", "📋 Database Cani"])

if menu == "📅 Gestione Turno":
    st.title("🐾 Canile Soft - Dashboard")

    with st.sidebar:
        data_t = st.date_input("Data", datetime.today())
        ora_i = st.time_input("Inizio", datetime.strptime("08:00", "%H:%M"))
        ora_f = st.time_input("Fine", datetime.strptime("12:00", "%H:%M"))
        st.divider()
        files = st.file_uploader("Aggiorna Schede PDF", accept_multiple_files=True, type="pdf")
        if files:
            conn = sqlite3.connect('canile.db')
            for f in files:
                d = extract_pdf_data(f)
                if d:
                    nome_cane = f.name.split('.')[0].strip().capitalize()
                    conn.execute("INSERT OR REPLACE INTO anagrafica_cani VALUES (?,?,?,?,?,?,?)", 
                                 (nome_cane, d['CIBO'], d['GUINZAGLIERIA'], d['STRUMENTI'], d['ATTIVITÀ'], d['NOTE'], d['TEMPO']))
            conn.commit(); conn.close()
            st.success("Dati PDF Aggiornati")

    df_c = load_data("Cani"); df_v = load_data("Volontari"); df_l = load_data("Luoghi")

    st.subheader("✅ 1. Check-in Disponibilità")
    c1, col2, col3 = st.columns(3)
    c_p = c1.multiselect("Cani", df_c['nome'].tolist() if 'nome' in df_c.columns else [], default=df_c['nome'].tolist())
    v_p = col2.multiselect("Volontari", df_v['nome'].tolist() if 'nome' in df_v.columns else [], default=df_v['nome'].tolist())
    l_p = col3.multiselect("Campi", df_l['nome'].tolist() if 'nome' in df_l.columns else [], default=df_l['nome'].tolist())

    st.divider()
    if c_p and v_p and l_p:
        st.subheader("🔗 2. Nuova Attività")
        r1 = st.columns(3)
        sel_c = r1[0].selectbox("Cane", c_p)
        
        conn = sqlite3.connect('canile.db'); conn.row_factory = sqlite3.Row
        info = conn.execute("SELECT * FROM anagrafica_cani WHERE nome=?", (sel_c.capitalize(),)).fetchone()
        v_sug = pd.read_sql_query(f"SELECT volontario FROM storico WHERE cane='{sel_c}' GROUP BY volontario ORDER BY COUNT(*) DESC LIMIT 1", sqlite3.connect('canile.db'))
        conn.close()
        
        v_nome = v_sug['volontario'].iloc[0] if not v_sug.empty else None
        sel_v = r1[1].selectbox("Volontario", v_p, index=v_p.index(v_nome) if v_nome in v_p else 0)
        sel_l = r1[2].selectbox("Luogo", l_p)

        r2 = st.columns(2)
        t_start = datetime.combine(data_t, ora_i) + timedelta(minutes=15)
        h_dal = r2[0].time_input("Inizio", t_start.time())
        durata_min = 30
        if info:
            try: durata_min = int(re.search(r'\d+', info['tempo']).group())
            except: pass
        h_al = r2[1].time_input("Fine", (datetime.combine(data_t, h_dal) + timedelta(minutes=durata_min)).time())

        if st.button("➕ Aggiungi al Programma", use_container_width=True):
            if 'programma' not in st.session_state: st.session_state.programma = []
            st.session_state.programma.append({
                "Orario": f"{h_dal.strftime('%H:%M')} - {h_al.strftime('%H:%M')}",
                "Inizio": h_dal.strftime('%H:%M'),
                "Cane": sel_c, "Volontario": sel_v, "Luogo": sel_l,
                "Cibo": info['cibo'] if info else "-", "Note": info['note'] if info else "-",
                "Attività": info['attivita'] if info else "-", "Strumenti": info['strumenti'] if info else "-",
                "Guinzaglieria": info['guinzaglieria'] if info else "-"
            })
            st.rerun()

    if 'programma' in st.session_state and st.session_state.programma:
        st.divider()
        df_prog = pd.DataFrame(st.session_state.programma).sort_values("Inizio")
        df_view = df_prog.drop(columns=['Inizio'])
        st.dataframe(df_view, use_container_width=True)

        b1, b2, b3 = st.columns(3)
        if b1.button("💾 Salva Storico", use_container_width=True):
            conn = sqlite3.connect('canile.db')
            for r in st.session_state.programma:
                conn.execute("INSERT INTO storico VALUES (?,?,?,?,?,?)", (str(data_t), r['Inizio'], "-", r['Cane'], r['Volontario'], r['Luogo']))
            conn.commit(); conn.close(); st.success("Salvato!")
        
        # --- EXPORT EXCEL COMPATTO ---
        output = io.BytesIO()
        with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
            df_view.to_excel(writer, index=False, sheet_name='Turno')
            workbook = writer.book
            worksheet = writer.sheets['Turno']
            
            # Formati: Testo piccolo e a capo
            header_fmt = workbook.add_format({'bold': True, 'bg_color': '#EBF1DE', 'border': 1, 'align': 'center', 'font_size': 10})
            cell_fmt = workbook.add_format({'text_wrap': True, 'valign': 'top', 'border': 1, 'font_size': 9})
            
            for i, col in enumerate(df_view.columns):
                worksheet.write(0, i, col, header_fmt)
                # Riduzione larghezza per forzare il ritorno a capo
                if col in ['Note', 'Attività', 'Cibo']:
                    width = 22
                elif col in ['Guinzaglieria', 'Strumenti']:
                    width = 18
                elif col in ['Orario']:
                    width = 12
                else:
                    width = 15
                worksheet.set_column(i, i, width, cell_fmt)

        b2.download_button("📊 Scarica Excel Compatto", output.getvalue(), f"turno_{data_t}.xlsx", use_container_width=True)
        if b3.button("🗑️ Svuota Tutto", use_container_width=True): 
            st.session_state.programma = []
            st.rerun()

elif menu == "📋 Database Cani":
    st.title("📋 Anagrafica Cani")
    conn = sqlite3.connect('canile.db')
    try:
        df_ana = pd.read_sql_query("SELECT * FROM anagrafica_cani", conn)
        st.dataframe(df_ana, use_container_width=True)
    except:
        st.info("Database vuoto.")
    conn.close()

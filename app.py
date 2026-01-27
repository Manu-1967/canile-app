import streamlit as st
import pandas as pd
from datetime import datetime, timedelta
import PyPDF2
import re
import sqlite3
from fpdf import FPDF
import io

st.set_page_config(page_title="Canile Soft - Gestionale", layout="wide")

# --- GESTIONE DATABASE STORICO (canile.db) ---
def init_db():
    conn = sqlite3.connect('canile.db')
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS storico 
                 (data TEXT, inizio TEXT, fine TEXT, cane TEXT, volontario TEXT, luogo TEXT)''')
    conn.commit()
    conn.close()

def salva_storico(programma, data_turno):
    conn = sqlite3.connect('canile.db')
    for att in programma:
        conn.execute("INSERT INTO storico VALUES (?, ?, ?, ?, ?, ?)",
                     (data_turno, att['Inizio'], att['Fine'], att['Cane'], att['Volontario'], att['Luogo']))
    conn.commit()
    conn.close()

def suggerisci_volontario(cane):
    conn = sqlite3.connect('canile.db')
    query = f"SELECT volontario, COUNT(*) as volte FROM storico WHERE cane = '{cane}' GROUP BY volontario ORDER BY volte DESC LIMIT 1"
    res = pd.read_sql_query(query, conn)
    conn.close()
    return res['volontario'].iloc[0] if not res.empty else None

init_db()

# --- FUNZIONI EXPORT ---
def to_excel(df):
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        df.to_excel(writer, index=False, sheet_name='Programma')
    return output.getvalue()

def to_pdf(df, data_t):
    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("Arial", 'B', 16)
    pdf.cell(190, 10, f"Programma Canile - {data_t}", ln=True, align='C')
    pdf.set_font("Arial", size=10)
    for i, r in df.iterrows():
        text = f"{r['Inizio']}-{r['Fine']} | {r['Cane']} con {r['Volontario']} in {r['Luogo']}"
        pdf.cell(190, 8, text, border=1, ln=True)
    return pdf.output(dest='S').encode('latin-1')

# --- LOGICA APP ---
SHEET_ID = "1pcFa454IT1tlykbcK-BeAU9hnIQ_D8V_UuZaKI_KtYM"
# (Inserire qui la funzione load_data e extract_pdf_data già create in precedenza)

st.title("🐾 Canile Soft Online - Smart Scheduler & Storico")

# --- 1. SETUP & PDF ---
with st.sidebar:
    data_turno = st.date_input("Data Turno", datetime.today())
    ora_inizio = st.time_input("Inizio", datetime.strptime("08:00", "%H:%M"))
    ora_fine = st.time_input("Fine", datetime.strptime("12:00", "%H:%M"))
    files = st.file_uploader("Carica PDF Cani", accept_multiple_files=True, type="pdf")

# Caricamento dati Google Sheets (già implementato)
df_cani_db = load_data("Cani")
df_volontari_db = load_data("Volontari")
df_luoghi_db = load_data("Luoghi")

# --- 2. ASSEGNAZIONE ---
st.divider()
c1, c2, c3 = st.columns(3)
c_sel = c1.selectbox("Cane", df_cani_db['nome'].tolist() if 'nome' in df_cani_db.columns else [])

# Suggerimento automatico basato sullo storico
v_suggerito = suggerisci_volontario(c_sel)
vol_list = df_volontari_db['nome'].tolist() if 'nome' in df_volontari_db.columns else []
v_index = vol_list.index(v_suggerito) if v_suggerito in vol_list else 0

v_sel = c2.selectbox("Volontario", vol_list, index=v_index)
if v_suggerito:
    st.caption(f"✨ Suggerito: {v_suggerito} (hanno già lavorato insieme)")

# (Inserire qui il resto del form attività e tabella riepilogo...)

# --- 3. SALVATAGGIO E EXPORT ---
if st.session_state.get('programma'):
    st.divider()
    col_ex1, col_ex2, col_ex3 = st.columns(3)
    
    if col_ex1.button("💾 Salva in Storico"):
        salva_storico(st.session_state.programma, str(data_turno))
        st.success("Programma salvato nel database storico!")

    df_export = pd.DataFrame(st.session_state.programma)
    
    col_ex2.download_button("📊 Scarica Excel", data=to_excel(df_export), file_name=f"programma_{data_turno}.xlsx")
    col_ex3.download_button("📄 Scarica PDF", data=to_pdf(df_export, data_turno), file_name=f"programma_{data_turno}.pdf")

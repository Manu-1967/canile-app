import streamlit as st
import pandas as pd
from datetime import datetime, timedelta
import PyPDF2
import re
import sqlite3
import io

# --- CONFIGURAZIONE ---
st.set_page_config(page_title="Canile Soft v3", layout="centered")

# Campi ammessi nel Database e nel Programma
CAMPI_DB = ['CIBO', 'GUINZAGLIERIA', 'STRUMENTI', 'ATTIVITÀ', 'NOTE', 'TEMPO', 'LIVELLO']

def init_db():
    conn = sqlite3.connect('canile.db')
    c = conn.cursor()
    c.execute('CREATE TABLE IF NOT EXISTS storico (data TEXT, inizio TEXT, cane TEXT, volontario TEXT, luogo TEXT)')
    c.execute(f'''CREATE TABLE IF NOT EXISTS anagrafica_cani 
                 (nome TEXT PRIMARY KEY, {", ".join([f"{c.lower()} TEXT" for c in CAMPI_DB])})''')
    conn.commit(); conn.close()

def parse_minuti(testo):
    """Estrae i minuti dal testo (es: '20 min' -> 20). Default 30."""
    match = re.search(r'(\d+)', str(testo))
    return int(match.group(1)) if match else 30

def extract_pdf_data(file):
    """Estrae solo i titoli previsti in MAIUSCOLO."""
    reader = PyPDF2.PdfReader(file)
    text = "\n".join([p.extract_text() for p in reader.pages])
    
    # Pattern per catturare TITOLO: contenuto
    pattern = r'([A-ZÀ-Ú]{2,}(?:\s+[A-ZÀ-Ú]{2,})*)[:\s\n]+(.*?)(?=\n[A-ZÀ-Ú]{2,}(?:\s+[A-ZÀ-Ú]{2,})*[:\s]|$)'
    matches = re.findall(pattern, text, re.DOTALL)
    
    data = {m[0].strip().upper(): m[1].strip() for m in matches}
    # Filtra solo i titoli previsti
    return {k: v for k, v in data.items() if k in CAMPI_DB}

init_db()

# --- SIDEBAR ---
with st.sidebar:
    st.header("⚙️ Setup")
    data_t = st.date_input("Data", datetime.today())
    ora_i = st.time_input("Inizio", datetime.strptime("08:00", "%H:%M"))
    ora_f = st.time_input("Fine", datetime.strptime("12:00", "%H:%M"))
    
    files = st.file_uploader("📂 Carica PDF Schede", accept_multiple_files=True, type="pdf")
    if files:
        conn = sqlite3.connect('canile.db')
        for f in files:
            d = extract_pdf_data(f)
            nome = f.name.split('.')[0].strip().capitalize()
            vals = [nome] + [d.get(c, "N/D") for c in CAMPI_DB]
            conn.execute(f"INSERT OR REPLACE INTO anagrafica_cani VALUES ({','.join(['?']*(len(CAMPI_DB)+1))})", vals)
        conn.commit(); conn.close()
        st.success("Schede aggiornate!")

df_c = load_gsheets("Cani") if 'load_gsheets' in globals() else pd.DataFrame()
df_v = load_gsheets("Volontari") if 'load_gsheets' in globals() else pd.DataFrame()
df_l = load_gsheets("Luoghi") if 'load_gsheets' in globals() else pd.DataFrame()

if 'programma' not in st.session_state: st.session_state.programma = []

st.title("📱 Canile Soft")

# --- UI RISORSE ---
cani_p = st.multiselect("🐕 Cani", df_c['nome'].tolist() if not df_c.empty else [])
vols_p = st.multiselect("👤 Volontari", df_v['nome'].tolist() if not df_v.empty else [])
luoghi_p = st.multiselect("📍 Luoghi", df_l['nome'].tolist() if not df_l.empty else [])

t1, t2 = st.tabs(["📅 Turno", "📋 Database"])

with t1:
    col_a, col_b = st.columns(2)
    
    if col_a.button("🤖 Genera Auto", use_container_width=True):
        conn = sqlite3.connect('canile.db'); conn.row_factory = sqlite3.Row
        curr_dt = datetime.combine(data_t, ora_i)
        end_dt = datetime.combine(data_t, ora_f)
        pasti_dt = end_dt - timedelta(minutes=30)
        
        st.session_state.programma = [] # Reset
        cani_restanti = cani_p.copy()
        
        # Briefing
        st.session_state.programma.append({
            "Ora": curr_dt.strftime('%H:%M'), "🐕": "TUTTI", "👤": "TUTTI", 
            "📍": "Ufficio", "Note": "Briefing", "Sort": curr_dt.strftime('%H:%M')
        })
        curr_dt += timedelta(minutes=15)

        while cani_restanti and curr_dt < pasti_dt:
            v_liberi = vols_p.copy(); l_liberi = luoghi_p.copy()
            n_disp = min(len(cani_restanti), len(l_liberi))
            
            if n_disp > 0:
                slot_batch = []
                durata_massima_slot = 30 # Default
                
                for _ in range(n_disp):
                    cane_nome = cani_restanti.pop(0)
                    info = conn.execute("SELECT * FROM anagrafica_cani WHERE nome=?", (cane_nome.capitalize(),)).fetchone()
                    luogo = l_liberi.pop(0)
                    
                    # Calcolo tempo specifico dalla scheda
                    tempo_cane = parse_minuti(info['tempo']) if info else 30
                    durata_massima_slot = max(durata_massima_slot, tempo_cane)
                    
                    # Assegnazione Lead (Storico)
                    lead = v_liberi[0] # Semplificato per brevità, usa logica storico se presente
                    v_liberi.remove(lead)
                    
                    slot_batch.append({
                        "c": cane_nome, "l": luogo, "v": lead, "s": [],
                        "cibo": info['cibo'] if info else "-",
                        "guinz": info['guinzaglieria'] if info else "-",
                        "note": info['note'] if info else "-"
                    })

                # Distribuzione SUPPORTI (tutti lavorano)
                idx = 0
                while v_liberi:
                    slot_batch[idx % len(slot_batch)]["s"].append(v_liberi.pop(0))
                    idx += 1
                
                for b in slot_batch:
                    vol_tot = b["v"] + (f"\n+ {', '.join(b['s'])}" if b["s"] else "")
                    st.session_state.programma.append({
                        "Ora": curr_dt.strftime('%H:%M'), "🐕": b["c"], "👤": vol_tot, 
                        "📍": b["l"], "Cibo": b["cibo"], "Guinz.": b["guinz"], 
                        "Note": b["note"], "Sort": curr_dt.strftime('%H:%M')
                    })
                curr_dt += timedelta(minutes=durata_massima_slot)
            else: break

        # Pasti
        st.session_state.programma.append({
            "Ora": pasti_dt.strftime('%H:%M'), "🐕": "TUTTI", "👤": "TUTTI", 
            "📍": "Box", "Note": "Pasti", "Sort": pasti_dt.strftime('%H:%M')
        })
        conn.close(); st.rerun()

    if col_b.button("🗑️ Svuota", use_container_width=True):
        st.session_state.programma = []; st.rerun()

    # --- TABELLA EDITABILE (Mobile Friendly) ---
    if st.session_state.programma:
        df_p = pd.DataFrame(st.session_state.programma).fillna("-").sort_values("Sort")
        
        df_ed = st.data_editor(
            df_p,
            column_config={
                "Sort": None,
                "Ora": st.column_config.TextColumn("🕒", width="small"),
                "🐕": st.column_config.TextColumn("🐕", width="small"),
                "👤": st.column_config.TextColumn("👤 Volontari", width="medium"),
                "📍": st.column_config.TextColumn("📍", width="small"),
                "Cibo": st.column_config.TextColumn("🍖", width="small"),
                "Guinz.": st.column_config.TextColumn("🦮", width="small"),
                "Note": st.column_config.TextColumn("📝 Note", width="medium"),
            },
            use_container_width=True, hide_index=True
        )
        st.session_state.programma = df_ed.to_dict('records')

        # --- EXCEL EXPORT (Con Wrap Testo) ---
        output = io.BytesIO()
        with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
            df_ed.drop(columns=['Sort'], errors='ignore').to_excel(writer, index=False, sheet_name='Turno')
            wb = writer.book; ws = writer.sheets['Turno']
            fmt = wb.add_format({'text_wrap': True, 'valign': 'top', 'border': 1})
            
            # Formattazione colonne Excel
            ws.set_column('A:B', 10, fmt) # Ora, Cane
            ws.set_column('C:C', 20, fmt) # Volontari
            ws.set_column('D:F', 12, fmt) # Luogo, Cibo, Guinz.
            ws.set_column('G:G', 35, fmt) # Note
            
        st.download_button("📊 Scarica Excel", output.getvalue(), "turno.xlsx", use_container_width=True)

with t2:
    conn = sqlite3.connect('canile.db')
    df_db = pd.read_sql_query("SELECT * FROM anagrafica_cani", conn)
    conn.close()
    st.dataframe(df_db, use_container_width=True, hide_index=True)

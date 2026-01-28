import streamlit as st
import pandas as pd
from datetime import datetime, timedelta
import PyPDF2
import re
import sqlite3
import io

# --- CONFIGURAZIONE E STILI MOBILE-FIRST ---
st.set_page_config(page_title="Canile Soft", layout="centered") # 'centered' aiuta su mobile

def init_db():
    conn = sqlite3.connect('canile.db') # Nome database come da istruzioni
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

# --- SIDEBAR COMPATTA ---
with st.sidebar:
    st.header("⚙️ Setup")
    data_t = st.date_input("Data", datetime.today())
    ora_i = st.time_input("Inizio", datetime.strptime("08:00", "%H:%M"))
    ora_f = st.time_input("Fine", datetime.strptime("12:00", "%H:%M"))
    files = st.file_uploader("📂 PDF Cani", accept_multiple_files=True, type="pdf")
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

st.title("📱 Canile Soft")

# --- SELEZIONE RISORSE (Layout Verticale per Mobile) ---
c_p = st.multiselect("🐕 Cani Presenti", df_c['nome'].tolist() if not df_c.empty else [])
v_p = st.multiselect("👤 Volontari Presenti", df_v['nome'].tolist() if not df_v.empty else [])
l_p = st.multiselect("📍 Luoghi Disponibili", df_l['nome'].tolist() if not df_l.empty else [])

tab_programma, tab_anagrafica = st.tabs(["📅 Programma", "📋 Anagrafica"])

with tab_programma:
    # 1. INSERIMENTO MANUALE
    with st.expander("✍️ Inserimento Rapido"):
        m_cane = st.selectbox("Cane", ["-"] + c_p)
        m_vol = st.selectbox("Volontario", ["-"] + v_p)
        m_luo = st.selectbox("Luogo", ["-"] + l_p)
        m_ora = st.time_input("Ora Inizio", ora_i)
        
        if st.button("➕ Aggiungi"):
            if m_cane != "-":
                st.session_state.programma.append({
                    "Orario": f"{m_ora.strftime('%H:%M')}",
                    "Cane": m_cane, "Volontario": m_vol, "Luogo": m_luo, "Attività": "Manuale", 
                    "Inizio_Sort": m_ora.strftime('%H:%M')
                })
                st.rerun()

    # 2. LOGICA AUTOMATICA
    c_btn1, c_btn2 = st.columns(2)

    if c_btn1.button("🤖 Genera Auto", use_container_width=True):
        conn = sqlite3.connect('canile.db'); conn.row_factory = sqlite3.Row
        start_dt = datetime.combine(data_t, ora_i)
        end_dt = datetime.combine(data_t, ora_f)
        pasti_dt = end_dt - timedelta(minutes=30) # Regola feeding end shift
        
        # Briefing iniziale
        if not any(r.get('Attività') == 'Briefing' for r in st.session_state.programma):
            st.session_state.programma.append({
                "Orario": start_dt.strftime('%H:%M'), "Cane": "TUTTI", "Volontario": "TUTTI", 
                "Luogo": "Ufficio", "Attività": "Briefing", "Inizio_Sort": start_dt.strftime('%H:%M')
            })

        cani_fatti = [r['Cane'] for r in st.session_state.programma if r.get('Cane') != "TUTTI"]
        cani_da_fare = [c for c in c_p if c not in cani_fatti]
        curr_t = start_dt + timedelta(minutes=15)
        
        while cani_da_fare and curr_t < pasti_dt:
            vols_liberi = v_p.copy()
            campi_liberi = l_p.copy()
            
            n_cani = min(len(cani_da_fare), len(campi_liberi))
            if n_cani > 0:
                batch = []
                for _ in range(n_cani):
                    cane = cani_da_fare.pop(0)
                    campo = campi_liberi.pop(0)
                    # Selezione Lead con storico
                    vols_punteggio = []
                    for v in vols_liberi:
                        cnt = conn.execute("SELECT COUNT(*) FROM storico WHERE cane=? AND volontario=?", (cane, v)).fetchone()[0]
                        vols_punteggio.append((v, cnt))
                    vols_punteggio.sort(key=lambda x: x[1], reverse=True)
                    lead = vols_punteggio[0][0]
                    vols_liberi.remove(lead)
                    batch.append({"cane": cane, "campo": campo, "lead": lead, "sups": []})

                # Assegna volontari rimasti come supporto (nessuno resta fermo)
                idx = 0
                while vols_liberi:
                    batch[idx % len(batch)]["sups"].append(vols_liberi.pop(0))
                    idx += 1
                
                for b in batch:
                    v_str = b["lead"] + (f"\n+ {', '.join(b['sups'])}" if b["sups"] else "")
                    info = conn.execute("SELECT * FROM anagrafica_cani WHERE nome=?", (b["cane"].capitalize(),)).fetchone()
                    st.session_state.programma.append({
                        "Orario": curr_t.strftime('%H:%M'), "Cane": b["cane"], "Volontario": v_str, 
                        "Luogo": b["campo"], "Note": info['note'] if info else "-", 
                        "Inizio_Sort": curr_t.strftime('%H:%M')
                    })
            curr_t += timedelta(minutes=30)

        # Pasti finale
        st.session_state.programma.append({
            "Orario": pasti_dt.strftime('%H:%M'), "Cane": "TUTTI", "Volontario": "TUTTI", 
            "Luogo": "Box", "Attività": "Pasti", "Inizio_Sort": pasti_dt.strftime('%H:%M')
        })
        conn.close(); st.rerun()

    if c_btn2.button("🗑️ Svuota", use_container_width=True):
        st.session_state.programma = []; st.rerun()

    # --- EDITOR OTTIMIZZATO MOBILE ---
    if st.session_state.programma:
        df_prog = pd.DataFrame(st.session_state.programma).sort_values("Inizio_Sort")
        
        # Configurazione colonne strette con wrap
        mobile_config = {
            "Inizio_Sort": None,
            "Orario": st.column_config.TextColumn("🕒", width="small"),
            "Cane": st.column_config.TextColumn("🐕", width="small"),
            "Volontario": st.column_config.TextColumn("👤 Volontari", width="medium"),
            "Luogo": st.column_config.TextColumn("📍", width="small"),
            "Note": st.column_config.TextColumn("📝 Note", width="medium"),
        }
        
        df_edited = st.data_editor(
            df_prog, column_config=mobile_config, 
            use_container_width=True, hide_index=True, num_rows="dynamic"
        )
        st.session_state.programma = df_edited.to_dict('records')

        # Excel Export con Wrap
        output = io.BytesIO()
        with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
            df_save = df_edited.drop(columns=['Inizio_Sort'], errors='ignore')
            df_save.to_excel(writer, index=False, sheet_name='Turno')
            workbook = writer.book
            worksheet = writer.sheets['Turno']
            wrap_format = workbook.add_format({'text_wrap': True, 'align': 'left', 'valign': 'top'})
            # Colonne strette per Excel
            worksheet.set_column('A:B', 8, wrap_format)
            worksheet.set_column('C:C', 15, wrap_format)
            worksheet.set_column('D:D', 10, wrap_format)
            worksheet.set_column('E:E', 25, wrap_format)

        st.download_button("📊 Scarica Excel", output.getvalue(), f"turno.xlsx", use_container_width=True)

with tab_anagrafica:
    conn = sqlite3.connect('canile.db')
    df_db = pd.read_sql_query("SELECT nome, cibo, note, livello FROM anagrafica_cani", conn)
    conn.close()
    if not df_db.empty:
        st.dataframe(
            df_db, 
            column_config={
                "nome": st.column_config.TextColumn("Nome", width="small"),
                "note": st.column_config.TextColumn("Note", width="medium"),
                "cibo": st.column_config.TextColumn("Cibo", width="small"),
            },
            use_container_width=True, hide_index=True
        )

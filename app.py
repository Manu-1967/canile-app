import streamlit as st
import pandas as pd
from datetime import datetime, timedelta
import PyPDF2
import re
import sqlite3
import io

# --- CONFIGURAZIONE ---
st.set_page_config(page_title="Canile Soft", layout="centered")

def init_db():
    conn = sqlite3.connect('canile.db')
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS anagrafica_cani 
                 (nome TEXT PRIMARY KEY, cibo TEXT, guinzaglieria TEXT, 
                  strumenti TEXT, attivita TEXT, note TEXT, tempo TEXT, livello TEXT)''')
    c.execute('CREATE TABLE IF NOT EXISTS storico (data TEXT, cane TEXT, volontario TEXT)')
    conn.commit()
    conn.close()

def load_gsheets(sheet_name):
    url = f"https://docs.google.com/spreadsheets/d/1pcFa454IT1tlykbcK-BeAU9hnIQ_D8V_UuZaKI_KtYM/gviz/tq?tqx=out:csv&sheet={sheet_name}"
    try:
        df = pd.read_csv(url)
        df.columns = [c.strip().lower() for c in df.columns]
        return df.dropna(how='all')
    except: return pd.DataFrame()

init_db()

# --- LOGICA PDF ---
def parse_pdf(file):
    reader = PyPDF2.PdfReader(file)
    text = "\n".join([p.extract_text() for p in reader.pages])
    
    # Chiavi richieste (Maiuscolo e Grassetto nei PDF solitamente estratte come testo semplice)
    keys = ['CIBO', 'GUINZAGLIERIA', 'STRUMENTI', 'ATTIVITÀ', 'NOTE', 'TEMPO', 'LIVELLO']
    d = {k: "N/D" for k in keys}
    
    for i, key in enumerate(keys):
        # Regex: Cerca la parola chiave e prendi tutto fino alla prossima parola chiave o fine doc
        next_keys = "|".join(keys[i+1:])
        pattern = rf"{key}[:\s\n]+(.*?)(?=\n(?:{next_keys})[:\s]|$)"
        match = re.search(pattern, text, re.DOTALL | re.IGNORECASE)
        if match:
            d[key] = match.group(1).strip()
            
    nome = file.name.split('.')[0].strip().capitalize()
    return nome, d

# --- SIDEBAR ---
with st.sidebar:
    st.header("⚙️ Impostazioni")
    data_t = st.date_input("Data Turno", datetime.today())
    ora_i = st.time_input("Inizio Turno", datetime.strptime("08:00", "%H:%M"))
    ora_f = st.time_input("Fine Turno", datetime.strptime("12:00", "%H:%M"))
    
    st.divider()
    st.subheader("📄 Aggiorna Anagrafica")
    files = st.file_uploader("Carica PDF Cani", accept_multiple_files=True, type="pdf")
    if st.button("Aggiorna Database", use_container_width=True):
        if files:
            conn = sqlite3.connect('canile.db')
            for f in files:
                nome, dati = parse_pdf(f)
                conn.execute("""INSERT OR REPLACE INTO anagrafica_cani 
                                VALUES (?,?,?,?,?,?,?,?)""", 
                             (nome, dati['CIBO'], dati['GUINZAGLIERIA'], dati['STRUMENTI'], 
                              dati['ATTIVITÀ'], dati['NOTE'], dati['TEMPO'], dati['LIVELLO']))
            conn.commit(); conn.close()
            st.success("Cani aggiornati!")
        else:
            st.warning("Carica almeno un file.")

# --- DATI ---
df_c = load_gsheets("Cani")
df_v = load_gsheets("Volontari")
df_l = load_gsheets("Luoghi")

if 'programma' not in st.session_state: st.session_state.programma = []

st.title("🐕 Canile Soft")

# --- SELEZIONE RISORSE ---
# Layout ottimizzato per mobile: multiselect occupano spazio verticale
c_p = st.multiselect("🐕 Cani Presenti", df_c['nome'].tolist() if not df_c.empty else [])
v_p = st.multiselect("👤 Volontari Presenti", df_v['nome'].tolist() if not df_v.empty else [])
l_p = st.multiselect("📍 Luoghi Disponibili", df_l['nome'].tolist() if not df_l.empty else [])

tab_prog, tab_ana = st.tabs(["📅 Programma", "📋 Anagrafica"])

with tab_prog:
    # 1. INSERIMENTO MANUALE
    with st.expander("✍️ Inserimento Manuale"):
        col1, col2 = st.columns(2)
        m_cane = col1.selectbox("Cane", ["-"] + c_p)
        m_luo = col2.selectbox("Luogo", ["-"] + l_p)
        m_vol = st.selectbox("Volontario", ["-"] + v_p)
        m_ora = st.time_input("Ora", ora_i)
        if st.button("Aggiungi Manualmente", use_container_width=True):
            if m_cane != "-":
                st.session_state.programma.append({
                    "Orario": m_ora.strftime('%H:%M'), "Cane": m_cane, 
                    "Volontario": m_vol, "Luogo": m_luo, "Note": "", "Sort": m_ora.strftime('%H:%M')
                })
                st.rerun()

    # 2. GENERAZIONE AUTOMATICA
    c1, c2 = st.columns(2)
    if c1.button("🤖 Genera Auto", use_container_width=True):
        conn = sqlite3.connect('canile.db'); conn.row_factory = sqlite3.Row
        curr_t = datetime.combine(data_t, ora_i)
        end_t = datetime.combine(data_t, ora_f)
        pasti_t = end_t - timedelta(minutes=30)
        
        # Briefing
        st.session_state.programma = [{
            "Orario": curr_t.strftime('%H:%M'), "Cane": "TUTTI", "Volontario": "TUTTI", 
            "Luogo": "Ufficio", "Note": "Briefing", "Sort": curr_t.strftime('%H:%M')
        }]
        
        cani_fatti = []
        curr_t += timedelta(minutes=15)
        
        # Conflitti
        conflitti = {"Lago Park": "Central Park", "Central Park": "Lago Park", 
                     "Peter Park": "Duca Park", "Duca Park": "Peter Park"}

        while (len(cani_fatti) < len(c_p)) and (curr_t < pasti_t):
            v_liberi = v_p.copy()
            l_liberi = [l for l in l_p if l != "Duca Park"] # Evita Duca Park se possibile
            if not l_liberi and "Duca Park" in l_p: l_liberi = ["Duca Park"]
            
            batch = []
            occupati_ora = []
            
            cani_restanti = [c for c in c_p if c not in cani_fatti]
            n_slot = min(len(cani_restanti), len(l_liberi), len(v_liberi))
            
            for _ in range(n_slot):
                if not cani_restanti or not l_liberi: break
                
                # Selezione luogo con controllo conflitti
                scelto_l = None
                for l in l_liberi:
                    if conflitti.get(l) not in occupati_ora:
                        scelto_l = l
                        break
                
                if scelto_l:
                    c_att = cani_restanti.pop(0)
                    # Storico per Lead
                    res = conn.execute("SELECT COUNT(*) FROM storico WHERE cane=? AND volontario=?", (c_att, v_liberi[0])).fetchone()
                    v_att = v_liberi.pop(0)
                    
                    batch.append({"Cane": c_att, "Luogo scelto": scelto_l, "Vol": v_att})
                    l_liberi.remove(scelto_l)
                    occupati_ora.append(scelto_l)
                    cani_fatti.append(c_att)

            for b in batch:
                info = conn.execute("SELECT note FROM anagrafica_cani WHERE nome=?", (b['Cane'],)).fetchone()
                st.session_state.programma.append({
                    "Orario": curr_t.strftime('%H:%M'), "Cane": b['Cane'], 
                    "Volontario": b['Vol'], "Luogo": b['Luogo scelto'], 
                    "Note": info['note'] if info else "-", "Sort": curr_t.strftime('%H:%M')
                })
            curr_t += timedelta(minutes=45)

        # Pasti (30 min fine turno)
        st.session_state.programma.append({
            "Orario": pasti_t.strftime('%H:%M'), "Cane": "TUTTI", "Volontario": "TUTTI", 
            "Luogo": "Box", "Note": "Pasti", "Sort": pasti_t.strftime('%H:%M')
        })
        conn.close(); st.rerun()

    if c2.button("🗑️ Svuota", use_container_width=True):
        st.session_state.programma = []; st.rerun()

    # --- TABELLA PROGRAMMA EDITABILE ---
    if st.session_state.programma:
        df_view = pd.DataFrame(st.session_state.programma).sort_values("Sort")
        df_view = df_view.drop(columns=["Sort"])
        
        # Configurazione Mobile-Friendly
        edited_df = st.data_editor(
            df_view,
            use_container_width=True,
            num_rows="dynamic",
            column_config={
                "Orario": st.column_config.TextColumn("⏰", width="small"),
                "Cane": st.column_config.TextColumn("🐕", width="small"),
                "Volontario": st.column_config.TextColumn("👤", width="medium"),
                "Luogo": st.column_config.TextColumn("📍", width="small"),
                "Note": st.column_config.TextColumn("📝", width="medium"),
            },
            hide_index=True
        )
        st.session_state.programma = edited_df.to_dict('records')

        # EXCEL EXPORT OTTIMIZZATO
        output = io.BytesIO()
        with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
            edited_df.to_excel(writer, index=False, sheet_name='Programma')
            workbook = writer.book
            worksheet = writer.sheets['Programma']
            fmt = workbook.add_format({'text_wrap': True, 'valign': 'top', 'border': 1})
            header_fmt = workbook.add_format({'bold': True, 'bg_color': '#D7E4BC', 'border': 1})
            
            # Larghezze colonne per leggibilità su tablet/mobile
            widths = [10, 15, 25, 15, 40]
            for i, width in enumerate(widths):
                worksheet.set_column(i, i, width, fmt)
            
        st.download_button("📥 Scarica Turno (Excel)", output.getvalue(), "turno.xlsx", use_container_width=True)

with tab_ana:
    conn = sqlite3.connect('canile.db')
    
    # Rimozione Cani
    cani_db = pd.read_sql_query("SELECT nome FROM anagrafica_cani", conn)['nome'].tolist()
    if cani_db:
        to_delete = st.multiselect("🗑️ Seleziona cani da rimuovere", cani_db)
        if st.button("Elimina selezionati", type="primary"):
            for n in to_delete:
                conn.execute("DELETE FROM anagrafica_cani WHERE nome=?", (n,))
            conn.commit(); st.rerun()
    
    # Visualizzazione
    df_ana = pd.read_sql_query("SELECT * FROM anagrafica_cani", conn)
    conn.close()
    
    if not df_ana.empty:
        st.subheader("📋 Lista Anagrafica")
        st.dataframe(
            df_ana,
            use_container_width=True,
            hide_index=True,
            column_config={
                "nome": st.column_config.TextColumn("Nome", width="small"),
                "livello": st.column_config.TextColumn("Liv", width="small"),
                "cibo": st.column_config.TextColumn("Cibo", width="medium"),
                "note": st.column_config.TextColumn("Note", width="large"),
            }
        )
    else:
        st.info("Nessun cane in anagrafica. Carica i PDF nella sidebar.")

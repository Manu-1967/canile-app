import sqlite3

# --- 1. AGGIORNAMENTO DATABASE PER ANAGRAFICA CANI ---
def init_db():
    conn = sqlite3.connect('canile.db')
    c = conn.cursor()
    # Tabella per lo storico dei turni
    c.execute('''CREATE TABLE IF NOT EXISTS storico 
                 (data TEXT, inizio TEXT, fine TEXT, cane TEXT, volontario TEXT, luogo TEXT)''')
    # NUOVA Tabella per l'anagrafica estratta dai PDF
    c.execute('''CREATE TABLE IF NOT EXISTS anagrafica_cani 
                 (nome TEXT PRIMARY KEY, cibo TEXT, guinzaglieria TEXT, 
                  strumenti TEXT, attivita TEXT, note TEXT, tempo TEXT)''')
    conn.commit()
    conn.close()

def salva_o_aggiorna_cane(nome, dati):
    conn = sqlite3.connect('canile.db')
    c = conn.cursor()
    c.execute('''INSERT OR REPLACE INTO anagrafica_cani 
                 VALUES (?, ?, ?, ?, ?, ?, ?)''', 
              (nome, dati['CIBO'], dati['GUINZAGLIERIA'], dati['STRUMENTI'], 
               dati['ATTIVITÀ'], dati['NOTE'], dati['TEMPO']))
    conn.commit()
    conn.close()

def recupera_info_cane(nome):
    conn = sqlite3.connect('canile.db')
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    c.execute("SELECT * FROM anagrafica_cani WHERE nome = ?", (nome,))
    res = c.fetchone()
    conn.close()
    return dict(res) if res else None

# --- 2. LOGICA NELL'INTERFACCIA STREAMLIT ---

# Analisi e salvataggio PDF
if pdf_files:
    for f in pdf_files:
        nome_cane = f.name.split('.')[0].strip().capitalize()
        dati_estratti = extract_pdf_data(f)
        if dati_estratti:
            salva_o_aggiorna_cane(nome_cane, dati_estratti)
            st.sidebar.success(f"✅ Scheda di {nome_cane} salvata/aggiornata!")

# --- 3. RECUPERO DATI DURANTE L'ASSEGNAZIONE ---

# Quando selezioni il cane nel form:
info_cane = recupera_info_cane(c_sel.capitalize())

if info_cane:
    # Se il cane esiste nel DB, usa i suoi dati
    tempo_val = 30
    try:
        tempo_val = int(re.search(r'\d+', info_cane['tempo']).group())
    except: pass
    
    # Mostra un'anteprima dei dati salvati
    with st.expander(f"ℹ️ Dati salvati per {c_sel}"):
        st.write(f"**Cibo:** {info_cane['cibo']}")
        st.write(f"**Note:** {info_cane['note']}")
else:
    st.warning(f"⚠️ Nessuna scheda PDF salvata per {c_sel}. Caricala nella sidebar se necessario.")
    tempo_val = 30

import streamlit as st
import pandas as pd
from datetime import datetime, timedelta
import PyPDF2
import re
import sqlite3
import io
import plotly.express as px
import plotly.graph_objects as go

# --- CONFIGURAZIONE ---
st.set_page_config(page_title="Programma Canile Pro", layout="wide")

def init_db():
    """Inizializza il database canile.db con le tabelle necessarie."""
    conn = sqlite3.connect('canile.db')
    c = conn.cursor()
    
    # Storico per statistiche e affinità volontario-cane
    c.execute('''CREATE TABLE IF NOT EXISTS storico 
                 (id INTEGER PRIMARY KEY AUTOINCREMENT,
                  data TEXT, 
                  inizio TEXT, 
                  fine TEXT,
                  cane TEXT, 
                  volontario TEXT, 
                  luogo TEXT,
                  attivita TEXT,
                  durata_minuti INTEGER,
                  timestamp_inserimento TEXT DEFAULT CURRENT_TIMESTAMP)''')
    
    # Anagrafica cani
    c.execute('''CREATE TABLE IF NOT EXISTS anagrafica_cani 
                 (nome TEXT PRIMARY KEY, 
                  cibo TEXT, 
                  guinzaglieria TEXT, 
                  strumenti TEXT, 
                  attivita TEXT, 
                  note TEXT, 
                  tempo TEXT, 
                  livello TEXT)''')
    
    # Tabella per programmi salvati completi
    c.execute('''CREATE TABLE IF NOT EXISTS programmi_salvati
                 (id INTEGER PRIMARY KEY AUTOINCREMENT,
                  data TEXT,
                  nome_programma TEXT,
                  contenuto TEXT,
                  timestamp_creazione TEXT DEFAULT CURRENT_TIMESTAMP)''')
    
    # Tabella per note e feedback sui turni
    c.execute('''CREATE TABLE IF NOT EXISTS feedback_turni
                 (id INTEGER PRIMARY KEY AUTOINCREMENT,
                  data TEXT,
                  cane TEXT,
                  volontario TEXT,
                  valutazione INTEGER,
                  note TEXT,
                  timestamp TEXT DEFAULT CURRENT_TIMESTAMP)''')
    
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

def calcola_durata_minuti(ora_inizio, ora_fine=None):
    """Calcola la durata in minuti tra due orari."""
    if ora_fine is None:
        return 45  # Default
    try:
        t1 = datetime.strptime(ora_inizio, '%H:%M')
        t2 = datetime.strptime(ora_fine, '%H:%M')
        return int((t2 - t1).total_seconds() / 60)
    except:
        return 45

def salva_programma_nel_db(programma, data_sel):
    """Archivia il programma definitivo per le statistiche future con durate."""
    conn = sqlite3.connect('canile.db')
    c = conn.cursor()
    dt_str = data_sel.strftime('%Y-%m-%d')
    
    # Elimina turni esistenti per questa data
    c.execute("DELETE FROM storico WHERE data=?", (dt_str,))
    
    # Ordina i turni per calcolare le durate
    prog_sorted = sorted([t for t in programma if t["Cane"] not in ["TUTTI", "Da assegnare"]], 
                         key=lambda x: x.get("Inizio_Sort", x["Orario"]))
    
    for i, t in enumerate(prog_sorted):
        vols = t["Volontario"].replace('+', ',').split(',')
        
        # Calcola ora fine (prossimo turno o +45 min)
        ora_fine = prog_sorted[i+1]["Orario"] if i+1 < len(prog_sorted) else None
        durata = calcola_durata_minuti(t["Orario"], ora_fine)
        
        for v in vols:
            if v.strip():
                c.execute("""INSERT INTO storico 
                            (data, inizio, fine, cane, volontario, luogo, attivita, durata_minuti) 
                            VALUES (?,?,?,?,?,?,?,?)""", 
                         (dt_str, t["Orario"], ora_fine or "", t["Cane"], 
                          v.strip(), t["Luogo"], t.get("Attività", "Standard"), durata))
    
    conn.commit()
    conn.close()

def get_affinita_volontario_cane(conn, cane, volontari_disponibili):
    """
    Calcola l'affinità tra un cane e i volontari disponibili basandosi su:
    - Numero di turni passati insieme
    - Valutazioni feedback (se presenti)
    - Varietà (penalizza chi ha già lavorato molto recentemente)
    """
    scores = []
    
    for vol in volontari_disponibili:
        # Turni totali insieme
        turni_tot = conn.execute(
            "SELECT COUNT(*) FROM storico WHERE cane=? AND volontario=?", 
            (cane, vol)
        ).fetchone()[0]
        
        # Turni ultimi 7 giorni (per favorire la rotazione)
        data_7gg = (datetime.now() - timedelta(days=7)).strftime('%Y-%m-%d')
        turni_recenti = conn.execute(
            "SELECT COUNT(*) FROM storico WHERE cane=? AND volontario=? AND data >= ?",
            (cane, vol, data_7gg)
        ).fetchone()[0]
        
        # Valutazioni positive (se ci sono feedback)
        feedback = conn.execute(
            "SELECT AVG(valutazione) FROM feedback_turni WHERE cane=? AND volontario=?",
            (cane, vol)
        ).fetchone()[0]
        feedback_score = feedback if feedback else 0
        
        # Formula: esperienza passata + feedback - penalità per turni molto recenti
        score = (turni_tot * 2) + (feedback_score * 3) - (turni_recenti * 1.5)
        scores.append((vol, score, turni_tot))
    
    return sorted(scores, key=lambda x: x[1], reverse=True)

def get_statistiche_avanzate(conn, data_inizio, data_fine):
    """Recupera statistiche avanzate dal database."""
    query = """
        SELECT 
            data, inizio, cane, volontario, luogo, durata_minuti, attivita
        FROM storico 
        WHERE data BETWEEN ? AND ?
    """
    df = pd.read_sql_query(query, conn, params=(data_inizio, data_fine))
    return df

init_db()

# --- INTERFACCIA ---
st.title("🐾 Programma Canile - Gestione Avanzata")

with st.sidebar:
    st.header("⚙️ Configurazione")
    data_t = st.date_input("Data Turno", datetime.today())
    ora_i = st.time_input("Inizio", datetime.strptime("08:00", "%H:%M"))
    ora_f = st.time_input("Fine", datetime.strptime("12:00", "%H:%M"))
    st.divider()
    
    # Opzioni algoritmo
    st.subheader("🎯 Algoritmo Assegnazione")
    usa_affinita = st.checkbox("Usa affinità storica", value=True, 
                               help="Favorisce volontari che hanno già lavorato con il cane")
    favorisci_rotazione = st.checkbox("Favorisci rotazione", value=True,
                                     help="Evita di assegnare sempre gli stessi volontari")
    
    st.divider()
    pdf_files = st.file_uploader("📂 Carica PDF Cani", accept_multiple_files=True, type="pdf")

df_c = load_gsheets("Cani")
df_v = load_gsheets("Volontari")
df_l = load_gsheets("Luoghi")

if 'programma' not in st.session_state: 
    st.session_state.programma = []

tab_prog, tab_ana, tab_stats, tab_feedback = st.tabs([
    "📅 Programma", "📋 Anagrafica", "📊 Statistiche Avanzate", "⭐ Feedback"
])

with tab_prog:
    st.header("Gestione Turni")
    
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
            if m_cane != "-" and m_luo != "-" and m_vols:
                st.session_state.programma.append({
                    "Orario": m_ora.strftime('%H:%M'), 
                    "Cane": m_cane, 
                    "Volontario": ", ".join(m_vols), 
                    "Luogo": m_luo, 
                    "Attività": "Manuale", 
                    "Inizio_Sort": m_ora.strftime('%H:%M')
                })
                st.success(f"Turno aggiunto per {m_cane}")
                st.rerun()
            else:
                st.error("Compila tutti i campi!")

    c1, c2, c3, c4 = st.columns(4)
    
    if c1.button("🤖 Genera Automatico", use_container_width=True):
        conn = sqlite3.connect('canile.db')
        conn.row_factory = sqlite3.Row
        
        start_dt = datetime.combine(data_t, ora_i)
        end_dt = datetime.combine(data_t, ora_f)
        pasti_dt = end_dt - timedelta(minutes=30)
        
        manuali = [r for r in st.session_state.programma if r.get("Attività") == "Manuale"]
        st.session_state.programma = [{
            "Orario": start_dt.strftime('%H:%M'), 
            "Cane": "TUTTI", 
            "Volontario": "TUTTI", 
            "Luogo": "Ufficio", 
            "Attività": "Briefing", 
            "Inizio_Sort": start_dt.strftime('%H:%M')
        }]
        
        cani_fatti = [m["Cane"] for m in manuali]
        cani_restanti = [c for c in c_p if c not in cani_fatti]
        curr_t = start_dt + timedelta(minutes=15)
        
        luoghi_ok = df_l[(df_l['nome'].isin(l_p)) & 
                         (df_l['automatico'].str.lower() == 'sì')]['nome'].tolist()

        while cani_restanti and curr_t < pasti_dt:
            ora_s = curr_t.strftime('%H:%M')
            v_liberi = [v for v in v_p if v not in 
                       [vv.strip() for m in manuali if m["Orario"]==ora_s 
                        for vv in m["Volontario"].split(",")]]
            l_liberi = [l for l in luoghi_ok if l not in 
                       [m["Luogo"] for m in manuali if m["Orario"]==ora_s]]
            
            if not v_liberi or not l_liberi:
                curr_t += timedelta(minutes=45)
                continue
            
            for idx in range(len(cani_restanti)-1, -1, -1):
                if not v_liberi or not l_liberi:
                    break
                    
                cane = cani_restanti[idx]
                campo_scelto = next((ll for ll in l_liberi if 
                                   campo_valido_per_reattivita(cane, ll, 
                                   st.session_state.programma + manuali, 
                                   ora_s, df_c, df_l)), None)
                
                if campo_scelto:
                    # Usa algoritmo avanzato se abilitato
                    if usa_affinita:
                        v_scores = get_affinita_volontario_cane(conn, cane, v_liberi)
                        lead = v_scores[0][0] if v_scores else v_liberi[0]
                    else:
                        lead = v_liberi[0]
                    
                    cani_restanti.pop(idx)
                    l_liberi.remove(campo_scelto)
                    v_liberi.remove(lead)
                    
                    st.session_state.programma.append({
                        "Orario": ora_s, 
                        "Cane": cane, 
                        "Volontario": lead, 
                        "Luogo": campo_scelto, 
                        "Attività": "Auto", 
                        "Inizio_Sort": ora_s
                    })
            
            curr_t += timedelta(minutes=45)
        
        st.session_state.programma.extend(manuali)
        st.session_state.programma.append({
            "Orario": pasti_dt.strftime('%H:%M'), 
            "Cane": "TUTTI", 
            "Volontario": "TUTTI", 
            "Luogo": "Box", 
            "Attività": "Pasti", 
            "Inizio_Sort": pasti_dt.strftime('%H:%M')
        })
        
        conn.close()
        st.success(f"Programma generato con {len(cani_restanti)} cani non assegnati")
        st.rerun()

    if c2.button("💾 Salva Storico", type="primary", use_container_width=True):
        if st.session_state.programma:
            salva_programma_nel_db(st.session_state.programma, data_t)
            st.success(f"✅ Programma salvato per {data_t.strftime('%d/%m/%Y')}")
            st.balloons()
        else:
            st.error("Nessun programma da salvare!")

    if c3.button("📤 Esporta CSV", use_container_width=True):
        if st.session_state.programma:
            df_export = pd.DataFrame(st.session_state.programma)
            csv = df_export.to_csv(index=False)
            st.download_button(
                label="⬇️ Scarica CSV",
                data=csv,
                file_name=f"programma_canile_{data_t.strftime('%Y%m%d')}.csv",
                mime="text/csv"
            )

    if c4.button("🗑️ Svuota", use_container_width=True):
        st.session_state.programma = []
        st.rerun()

    # Visualizzazione programma
    if st.session_state.programma:
        st.subheader("📋 Programma Attuale")
        df_p = pd.DataFrame(st.session_state.programma).sort_values("Inizio_Sort")
        
        # Editor con possibilità di modifica
        edited_df = st.data_editor(
            df_p[['Orario', 'Cane', 'Volontario', 'Luogo', 'Attività']], 
            use_container_width=True, 
            hide_index=True,
            num_rows="dynamic"
        )
        
        # Vista timeline
        with st.expander("📅 Vista Timeline"):
            fig = px.timeline(
                df_p,
                x_start="Orario",
                y="Cane",
                color="Volontario",
                title="Timeline Turni",
                hover_data=['Luogo', 'Attività']
            )
            st.plotly_chart(fig, use_container_width=True)

with tab_stats:
    st.header("📊 Statistiche Avanzate")
    
    conn = sqlite3.connect('canile.db')
    
    col_x, col_y = st.columns(2)
    d_ini = col_x.date_input("Data Inizio", datetime.today() - timedelta(days=30))
    d_end = col_y.date_input("Data Fine", datetime.today())
    
    df_h = get_statistiche_avanzate(conn, d_ini.strftime('%Y-%m-%d'), d_end.strftime('%Y-%m-%d'))
    
    if not df_h.empty:
        # Metriche generali
        col1, col2, col3, col4 = st.columns(4)
        col1.metric("Turni Totali", len(df_h))
        col2.metric("Cani Unici", df_h['cane'].nunique())
        col3.metric("Volontari Attivi", df_h['volontario'].nunique())
        col4.metric("Ore Totali", f"{df_h['durata_minuti'].sum() / 60:.1f}h")
        
        st.divider()
        
        # Filtro visualizzazione
        vista = st.segmented_control(
            "Analizza per:", 
            ["Volontario", "Cane", "Luogo", "Confronti"], 
            default="Volontario"
        )
        
        if vista == "Volontario":
            col_a, col_b = st.columns([1, 2])
            
            with col_a:
                vol_sel = st.selectbox("Seleziona Volontario", sorted(df_h['volontario'].unique()))
                res = df_h[df_h['volontario'] == vol_sel]
                
                st.metric("Turni Totali", len(res))
                st.metric("Ore Lavorate", f"{res['durata_minuti'].sum() / 60:.1f}h")
                st.metric("Cani Seguiti", res['cane'].nunique())
                
                # Top 5 cani più seguiti
                st.subheader("Top 5 Cani")
                top_cani = res['cane'].value_counts().head(5)
                for cane, count in top_cani.items():
                    st.write(f"🐕 {cane}: {count} turni")
            
            with col_b:
                # Grafico turni per cane
                fig_cani = px.bar(
                    res['cane'].value_counts().reset_index(),
                    x='cane', y='count',
                    title=f"Distribuzione turni - {vol_sel}",
                    labels={'cane': 'Cane', 'count': 'Numero Turni'}
                )
                st.plotly_chart(fig_cani, use_container_width=True)
                
                # Timeline settimanale
                res_copy = res.copy()
                res_copy['data'] = pd.to_datetime(res_copy['data'])
                turni_giorno = res_copy.groupby('data').size().reset_index(name='turni')
                fig_time = px.line(
                    turni_giorno, x='data', y='turni',
                    title="Turni nel tempo",
                    markers=True
                )
                st.plotly_chart(fig_time, use_container_width=True)
            
            # Dettaglio completo
            with st.expander("📋 Dettaglio Turni"):
                st.dataframe(res, use_container_width=True, hide_index=True)
        
        elif vista == "Cane":
            col_a, col_b = st.columns([1, 2])
            
            with col_a:
                cane_sel = st.selectbox("Seleziona Cane", sorted(df_h['cane'].unique()))
                res = df_h[df_h['cane'] == cane_sel]
                
                st.metric("Uscite Totali", len(res))
                st.metric("Ore Attività", f"{res['durata_minuti'].sum() / 60:.1f}h")
                st.metric("Volontari Diversi", res['volontario'].nunique())
                
                # Top 5 volontari
                st.subheader("Top 5 Volontari")
                top_vol = res['volontario'].value_counts().head(5)
                for vol, count in top_vol.items():
                    st.write(f"👤 {vol}: {count} turni")
            
            with col_b:
                # Grafico volontari
                fig_vol = px.bar(
                    res['volontario'].value_counts().reset_index(),
                    x='volontario', y='count',
                    title=f"Chi ha lavorato con {cane_sel}",
                    labels={'volontario': 'Volontario', 'count': 'Numero Turni'}
                )
                st.plotly_chart(fig_vol, use_container_width=True)
                
                # Luoghi preferiti
                fig_luoghi = px.pie(
                    res, names='luogo',
                    title="Distribuzione Luoghi",
                    hole=0.4
                )
                st.plotly_chart(fig_luoghi, use_container_width=True)
            
            with st.expander("📋 Storico Uscite"):
                st.dataframe(res, use_container_width=True, hide_index=True)
        
        elif vista == "Luogo":
            col_a, col_b = st.columns([1, 2])
            
            with col_a:
                luogo_sel = st.selectbox("Seleziona Luogo", sorted(df_h['luogo'].unique()))
                res = df_h[df_h['luogo'] == luogo_sel]
                
                st.metric("Utilizzi Totali", len(res))
                st.metric("Ore Utilizzo", f"{res['durata_minuti'].sum() / 60:.1f}h")
                st.metric("Tasso Utilizzo", f"{(len(res) / len(df_h) * 100):.1f}%")
            
            with col_b:
                fig_uso = px.bar(
                    res['cane'].value_counts().reset_index(),
                    x='cane', y='count',
                    title=f"Cani che hanno usato {luogo_sel}",
                    labels={'cane': 'Cane', 'count': 'Volte'}
                )
                st.plotly_chart(fig_uso, use_container_width=True)
            
            with st.expander("📋 Dettaglio Utilizzi"):
                st.dataframe(res, use_container_width=True, hide_index=True)
        
        else:  # Confronti
            st.subheader("🔄 Analisi Comparative")
            
            tab_c1, tab_c2, tab_c3 = st.tabs(["Carico Lavoro", "Affinità", "Tendenze"])
            
            with tab_c1:
                # Carico di lavoro per volontario
                carico = df_h.groupby('volontario').agg({
                    'cane': 'count',
                    'durata_minuti': 'sum'
                }).reset_index()
                carico.columns = ['Volontario', 'Turni', 'Minuti']
                carico['Ore'] = carico['Minuti'] / 60
                
                fig_carico = px.bar(
                    carico.sort_values('Ore', ascending=False),
                    x='Volontario', y='Ore',
                    title="Ore Lavorate per Volontario",
                    color='Turni',
                    text='Ore'
                )
                fig_carico.update_traces(texttemplate='%{text:.1f}h', textposition='outside')
                st.plotly_chart(fig_carico, use_container_width=True)
                
                st.dataframe(carico.sort_values('Ore', ascending=False), 
                           use_container_width=True, hide_index=True)
            
            with tab_c2:
                # Matrice affinità cane-volontario
                st.write("**Matrice Affinità** (numero di turni insieme)")
                
                pivot = df_h.pivot_table(
                    index='cane', 
                    columns='volontario', 
                    values='data',
                    aggfunc='count',
                    fill_value=0
                )
                
                fig_heat = px.imshow(
                    pivot,
                    labels=dict(x="Volontario", y="Cane", color="Turni"),
                    title="Mappa Affinità Cane-Volontario",
                    color_continuous_scale="Blues"
                )
                st.plotly_chart(fig_heat, use_container_width=True)
                
                # Top 10 coppie
                st.subheader("Top 10 Coppie Cane-Volontario")
                coppie = df_h.groupby(['cane', 'volontario']).size().reset_index(name='turni')
                coppie = coppie.sort_values('turni', ascending=False).head(10)
                
                for _, row in coppie.iterrows():
                    st.write(f"🤝 **{row['cane']}** + **{row['volontario']}**: {row['turni']} turni")
            
            with tab_c3:
                # Tendenze temporali
                df_trend = df_h.copy()
                df_trend['data'] = pd.to_datetime(df_trend['data'])
                df_trend['settimana'] = df_trend['data'].dt.isocalendar().week
                
                turni_sett = df_trend.groupby('settimana').size().reset_index(name='turni')
                
                fig_trend = px.line(
                    turni_sett, x='settimana', y='turni',
                    title="Andamento Turni per Settimana",
                    markers=True
                )
                st.plotly_chart(fig_trend, use_container_width=True)
                
                # Distribuzione giorni settimana
                df_trend['giorno_sett'] = df_trend['data'].dt.day_name()
                giorni_ord = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday']
                giorno_count = df_trend['giorno_sett'].value_counts().reindex(giorni_ord, fill_value=0)
                
                fig_giorni = px.bar(
                    x=['Lun', 'Mar', 'Mer', 'Gio', 'Ven', 'Sab', 'Dom'],
                    y=giorno_count.values,
                    title="Distribuzione per Giorno della Settimana",
                    labels={'x': 'Giorno', 'y': 'Numero Turni'}
                )
                st.plotly_chart(fig_giorni, use_container_width=True)
    else:
        st.warning("⚠️ Nessun dato trovato per questo periodo.")
    
    conn.close()

with tab_feedback:
    st.header("⭐ Feedback e Valutazioni")
    
    conn = sqlite3.connect('canile.db')
    
    col_f1, col_f2 = st.columns(2)
    
    with col_f1:
        st.subheader("Aggiungi Feedback")
        
        # Recupera coppie recenti per facilitare l'inserimento
        query_recenti = """
            SELECT DISTINCT cane, volontario 
            FROM storico 
            WHERE data >= date('now', '-7 days')
            ORDER BY data DESC
        """
        coppie_recenti = pd.read_sql_query(query_recenti, conn)
        
        if not coppie_recenti.empty:
            fb_cane = st.selectbox("Cane", coppie_recenti['cane'].unique())
            fb_vol = st.selectbox("Volontario", 
                                 coppie_recenti[coppie_recenti['cane']==fb_cane]['volontario'].unique())
        else:
            fb_cane = st.text_input("Cane")
            fb_vol = st.text_input("Volontario")
        
        fb_data = st.date_input("Data Turno", datetime.today())
        fb_rating = st.slider("Valutazione", 1, 5, 3, 
                             help="1=Pessimo, 5=Eccellente")
        fb_note = st.text_area("Note/Osservazioni")
        
        if st.button("💾 Salva Feedback"):
            if fb_cane and fb_vol:
                c = conn.cursor()
                c.execute("""INSERT INTO feedback_turni 
                            (data, cane, volontario, valutazione, note) 
                            VALUES (?,?,?,?,?)""",
                         (fb_data.strftime('%Y-%m-%d'), fb_cane, fb_vol, fb_rating, fb_note))
                conn.commit()
                st.success("✅ Feedback salvato!")
                st.rerun()
            else:
                st.error("Compila cane e volontario!")
    
    with col_f2:
        st.subheader("Ultimi Feedback")
        
        query_fb = """
            SELECT data, cane, volontario, valutazione, note, 
                   datetime(timestamp) as inserito
            FROM feedback_turni 
            ORDER BY timestamp DESC 
            LIMIT 10
        """
        df_fb = pd.read_sql_query(query_fb, conn)
        
        if not df_fb.empty:
            for _, row in df_fb.iterrows():
                with st.container():
                    st.write(f"**{row['cane']}** + **{row['volontario']}** - {row['data']}")
                    st.write("⭐" * int(row['valutazione']))
                    if row['note']:
                        st.caption(row['note'])
                    st.divider()
        else:
            st.info("Nessun feedback ancora inserito")
    
    # Statistiche feedback
    st.subheader("📈 Analisi Feedback")
    
    query_stats_fb = """
        SELECT volontario, 
               AVG(valutazione) as media,
               COUNT(*) as num_valutazioni
        FROM feedback_turni
        GROUP BY volontario
        HAVING num_valutazioni >= 3
        ORDER BY media DESC
    """
    df_stats_fb = pd.read_sql_query(query_stats_fb, conn)
    
    if not df_stats_fb.empty:
        fig_feedback = px.bar(
            df_stats_fb,
            x='volontario',
            y='media',
            title="Valutazione Media Volontari (min 3 valutazioni)",
            labels={'volontario': 'Volontario', 'media': 'Media'},
            text='media',
            color='media',
            color_continuous_scale='RdYlGn'
        )
        fig_feedback.update_traces(texttemplate='%{text:.2f}', textposition='outside')
        fig_feedback.update_layout(yaxis_range=[0, 5])
        st.plotly_chart(fig_feedback, use_container_width=True)
    else:
        st.info("Raccogli almeno 3 feedback per volontario per vedere le statistiche")
    
    conn.close()

with tab_ana:
    st.header("📋 Anagrafica Cani")
    
    conn = sqlite3.connect('canile.db')
    df_db = pd.read_sql_query("SELECT * FROM anagrafica_cani", conn)
    
    if not df_db.empty:
        st.dataframe(df_db, use_container_width=True, hide_index=True)
    else:
        st.info("Nessun dato in anagrafica")
    
    conn.close()

# Footer
st.divider()
st.caption("🐾 Programma Canile Pro v2.0 - Gestione Avanzata con Storico e Statistiche")

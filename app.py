import streamlit as st
import pandas as pd
from datetime import datetime, timedelta

st.set_page_config(page_title="Canile Soft - Programma", layout="wide")

SHEET_ID = "1pcFa454IT1tlykbcK-BeAU9hnIQ_D8V_UuZaKI_KtYM"

def load_data(sheet_name):
    url = f"https://docs.google.com/spreadsheets/d/{SHEET_ID}/gviz/tq?tqx=out:csv&sheet={sheet_name}"
    try:
        df = pd.read_csv(url)
        df.columns = [c.strip().lower() for c in df.columns]
        return df.dropna(how='all')
    except:
        return pd.DataFrame()

# --- CARICAMENTO DATI ---
df_cani_db = load_data("Cani")
df_volontari_db = load_data("Volontari")
df_luoghi_db = load_data("Luoghi")

st.title("🐾 Canile Soft Online - Gestione Turno")

# --- 1. IMPOSTAZIONI TURNI ---
with st.expander("📅 1. Orario e Data", expanded=True):
    c1, c2, c3 = st.columns(3)
    data_turno = c1.date_input("Data del turno", datetime.today())
    ora_inizio = c2.time_input("Inizio Turno", datetime.strptime("08:00", "%H:%M"))
    ora_fine = c3.time_input("Fine Turno", datetime.strptime("12:00", "%H:%M"))

# --- 2. SELEZIONE DISPONIBILI ---
st.header("✅ 2. Check-in Disponibilità")
col_c, col_v, col_l = st.columns(3)

with col_c:
    st.subheader("Cani")
    lista_c = df_cani_db['nome'].tolist() if 'nome' in df_cani_db.columns else []
    cani_oggi = st.multiselect("Cani pronti per uscita", lista_c, default=lista_c)

with col_v:
    st.subheader("Volontari")
    lista_v = df_volontari_db['nome'].tolist() if 'nome' in df_volontari_db.columns else []
    vol_oggi = st.multiselect("Volontari in turno", lista_v, default=lista_v)

with col_l:
    st.subheader("Luoghi")
    lista_l = df_luoghi_db['nome'].tolist() if 'nome' in df_luoghi_db.columns else []
    luoghi_oggi = st.multiselect("Campi agibili oggi", lista_l, default=lista_l)

# --- 3. GENERAZIONE PROGRAMMA ---
st.divider()
st.header("🔗 3. Assegnazioni e Programma")

if not (cani_oggi and vol_oggi and luoghi_oggi):
    st.info("Seleziona i presenti per procedere.")
else:
    # --- BRIEFING INIZIALE (FISSO 15 MIN) ---
    briefing_fine = (datetime.combine(data_turno, ora_inizio) + timedelta(minutes=15)).time()
    st.info(f"📋 **{ora_inizio.strftime('%H:%M')} - {briefing_fine.strftime('%H:%M')}**: Briefing in Ufficio (15 min)")

    if 'programma' not in st.session_state:
        st.session_state.programma = []

    # Form per aggiunta attività
    with st.form("aggiungi_assegnazione"):
        st.write("**Aggiungi accoppiata attività**")
        a1, a2, a3 = st.columns(3)
        v_sel = a1.selectbox("Volontario", vol_oggi)
        c_sel = a2.selectbox("Cane", cani_oggi)
        l_sel = a3.selectbox("Luogo", luoghi_oggi)
        
        submit = st.form_submit_button("Aggiungi al Programma")
        
        if submit:
            # Logica adiacenze dinamica da DB
            col_adj = next((c for c in df_luoghi_db.columns if 'adiacen' in c), None)
            alert_msg = ""
            if col_adj:
                info_luogo = df_luoghi_db[df_luoghi_db['nome'] == l_sel]
                if not info_luogo.empty:
                    adj_val = str(info_luogo[col_adj].values[0])
                    if adj_val in luoghi_oggi:
                        alert_msg = f"⚠️ Vicino a {adj_val}"

            st.session_state.programma.append({
                "Volontario": v_sel,
                "Cane": c_sel,
                "Luogo": l_sel,
                "Note": alert_msg
            })

    # Tabella Riepilogo
    if st.session_state.programma:
        st.write("### 📝 Attività Programmate")
        df_prog = pd.DataFrame(st.session_state.programma)
        st.table(df_prog)
        
        if st.button("Pulisci Tutto"):
            st.session_state.programma = []
            st.rerun()

    # --- LOGICA PASTI FISSA (ULTIMI 30 MIN) ---
    st.write("---")
    pasti_inizio = (datetime.combine(data_turno, ora_fine) - timedelta(minutes=30)).time()
    st.error(f"🥣 **{pasti_inizio.strftime('%H:%M')} - {ora_fine.strftime('%H:%M')}**: Fine attività e Distribuzione Pasti (30 min)")

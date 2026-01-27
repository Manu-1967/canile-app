import streamlit as st
import pandas as pd
from datetime import datetime, timedelta

st.set_page_config(page_title="Canile Soft - Gestione Turno", layout="wide")

SHEET_ID = "1pcFa454IT1tlykbcK-BeAU9hnIQ_D8V_UuZaKI_KtYM"

def load_data(sheet_name):
    url = f"https://docs.google.com/spreadsheets/d/{SHEET_ID}/gviz/tq?tqx=out:csv&sheet={sheet_name}"
    try:
        df = pd.read_csv(url)
        return df.dropna(how='all')
    except:
        return pd.DataFrame()

# --- CARICAMENTO DATI ---
df_cani_db = load_data("Cani")
df_volontari_db = load_data("Volontari")
df_luoghi_db = load_data("Luoghi")

st.title("🐾 Canile Soft Online - Configurazione Turno")

# --- STEP 1: IMPOSTAZIONI GENERALI ---
with st.expander("📅 1. Impostazioni Orario e Data", expanded=True):
    c1, c2, c3 = st.columns(3)
    data_turno = c1.date_input("Data del turno", datetime.today())
    ora_inizio = c2.time_input("Inizio Turno", datetime.strptime("08:00", "%H:%M"))
    ora_fine = c3.time_input("Fine Turno", datetime.strptime("12:00", "%H:%M"))

# --- STEP 2: DISPONIBILITÀ DEL GIORNO ---
st.header("✅ 2. Seleziona Disponibili per oggi")

col_c, col_v, col_l = st.columns(3)

with col_c:
    st.subheader("Cani")
    cani_presenti = st.multiselect("Quali cani escono?", df_cani_db['nome'].tolist(), default=df_cani_db['nome'].tolist())

with col_v:
    st.subheader("Volontari")
    vol_presenti = st.multiselect("Chi è presente?", df_volontari_db['nome'].tolist(), default=df_volontari_db['nome'].tolist())

with col_l:
    st.subheader("Luoghi")
    # Escludiamo Duca Park dal default per sicurezza, ma è selezionabile
    luoghi_base = [l for l in df_luoghi_db['nome'].tolist() if "Duca" not in l]
    luoghi_presenti = st.multiselect("Quali campi usiamo?", df_luoghi_db['nome'].tolist(), default=luoghi_base)

# --- STEP 3: GENERAZIONE PROGRAMMA ---
st.divider()
if st.button("🚀 Genera Programma con questi dati"):
    if not cani_presenti or not vol_presenti or not luoghi_presenti:
        st.error("Devi selezionare almeno un cane, un volontario e un luogo!")
    else:
        st.success(f"Programma in generazione per il {data_turno} dalle {ora_inizio} alle {ora_fine}")
        
        # Filtriamo i dataframe in base alle scelte fatte sopra
        cani_oggi = df_cani_db[df_cani_db['nome'].isin(cani_presenti)]
        vol_oggi = df_volontari_db[df_volontari_db['nome'].isin(vol_presenti)]
        luoghi_oggi = df_luoghi_db[df_luoghi_db['nome'].isin(luoghi_presenti)]

        # Visualizzazione Tabella Lavoro
        st.write("### 📋 Bozza Programma Attività")
        
        # Logica adiacenze dinamica
        for _, luogo in luoghi_oggi.iterrows():
            if pd.notna(luogo['adiacente']):
                if luogo['adiacente'] in luoghi_presenti:
                    st.warning(f"⚠️ Attenzione: **{luogo['nome']}** e **{luogo['adiacente']}** sono entrambi attivi. Non mettere cani reattivi vicini.")

        # Logica Pasti (Sempre 30 min prima della fine)
        pasti_dt = datetime.combine(data_turno, ora_fine) - timedelta(minutes=30)
        
        st.error(f"🥣 ORE {pasti_dt.strftime('%H:%M')} - FINE ATTIVITÀ E DISTRIBUZIONE PASTI (30 min)")

        # Qui potrai procedere al link manuale o automatico
        st.info("💡 Ora puoi procedere a collegare i volontari ai cani selezionati.")

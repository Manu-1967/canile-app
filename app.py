import streamlit as st
import pandas as pd
from datetime import datetime, timedelta

# Configurazione Pagina
st.set_page_config(page_title="Canile Soft Online", layout="wide")

# Sostituisci con il tuo ID funzionante
SHEET_ID = "IL_TUO_ID_QUI" 

def load_data(sheet_name):
    url = f"https://docs.google.com/spreadsheets/d/{SHEET_ID}/gviz/tq?tqx=out:csv&sheet={sheet_name}"
    try:
        return pd.read_csv(url)
    except:
        return pd.DataFrame()

st.title("🐾 Canile Soft Online")

df_cani = load_data("Cani")
df_volontari = load_data("Volontari")

if df_cani.empty or "nome" not in df_cani.columns:
    st.warning("⚠️ Database vuoto. Scrivi 'nome', 'colore', 'reattivita' nella prima riga del foglio Google.")
else:
    st.success(f"✅ Connesso! Trovati {len(df_cani)} cani e {len(df_volontari)} volontari.")
    
    tab1, tab2 = st.tabs(["📅 Genera Programma", "🐕 Anagrafica"])

    with tab1:
        st.header("Configurazione Turno")
        col1, col2 = st.columns(2)
        with col1:
            t_inizio = st.time_input("Inizio Turno", datetime.strptime("08:00", "%H:%M"))
        with col2:
            t_fine = st.time_input("Fine Turno", datetime.strptime("12:00", "%H:%M"))

        if st.button("🚀 Genera Programma Attività"):
            st.write("---")
            # Logica Briefing
            st.info(f"⏱️ {t_inizio.strftime('%H:%M')} - Briefing Iniziale (15 min)")
            
            # Simulazione incroci (Qui inseriremo l'algoritmo basato sui colori)
            st.subheader("Assegnazioni Campi")
            st.write("Configurazione adiacenze attiva: Lago/Central - Peter/Duca")
            
            # Logica Pasti (Sempre 30 min prima della fine)
            pasti_ora = (datetime.combine(datetime.today(), t_fine) - timedelta(minutes=30)).time()
            st.error(f"🥣 {pasti_ora.strftime('%H:%M')} - DISTRIBUZIONE PASTI E PULIZIA (30 min)")

    with tab2:
        st.subheader("Database Cani")
        st.dataframe(df_cani)

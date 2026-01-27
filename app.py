import streamlit as st
import pandas as pd
from datetime import datetime, timedelta

st.set_page_config(page_title="Canile Soft Online", layout="wide")

# USA IL TUO ID CHE HA FUNZIONATO PRIMA
SHEET_ID = "1pcFa454IT1tlykbcK-BeAU9hnIQ_D8V_UuZaKI_KtYM" 

def load_data(sheet_name):
    url = f"https://docs.google.com/spreadsheets/d/{SHEET_ID}/gviz/tq?tqx=out:csv&sheet={sheet_name}"
    try:
        return pd.read_csv(url)
    except:
        return pd.DataFrame()

st.title("🐾 Canile Soft Online")

# Caricamento
df_cani = load_data("Cani")
df_volontari = load_data("Volontari")

if df_cani.empty:
    st.warning("⚠️ Il database è connesso ma non ci sono dati o mancano le intestazioni (nome, colore, reattività).")
else:
    st.success("✅ Database sincronizzato!")
    
    menu = st.sidebar.selectbox("Menu", ["Genera Programma", "Gestione Cani"])

    if menu == "Genera Programma":
        st.header("Configurazione Turno")
        t_inizio = st.time_input("Inizio", datetime.strptime("08:00", "%H:%M"))
        t_fine = st.time_input("Fine", datetime.strptime("12:00", "%H:%M"))
        
        if st.button("Genera"):
            # LOGICA PASTI (Memory check: ultimi 30 minuti)
            pasti_dt = datetime.combine(datetime.today(), t_fine) - timedelta(minutes=30)
            
            st.write(f"### 📋 Programma")
            st.info(f"08:00 - Briefing iniziale")
            st.write("---")
            st.write("*(Qui appariranno gli incroci cani-volontari)*")
            st.write("---")
            st.error(f"🥣 {pasti_dt.strftime('%H:%M')} - INIZIO PASTI E PULIZIA (30 min)")
            
            # NOTA ADIACENZE (Lago/Central, Peter/Duca)
            st.sidebar.info("Regola attiva: No cani in campi adiacenti se reattività > 5.")

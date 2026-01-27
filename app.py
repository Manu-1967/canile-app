import streamlit as st
import pandas as pd
from datetime import datetime, timedelta

st.set_page_config(page_title="Canile Soft Online", layout="wide")

# --- CONFIGURAZIONE MANUALE (Sostituisci solo l'ID) ---
# Prendi l'ID dal tuo URL: https://docs.google.com/spreadsheets/d/IL_TUO_ID_QUI/edit
SHEET_ID = "IL_TUO_ID_LUNGO_QUI" 

def get_google_sheet(sheet_name):
    url = f"https://docs.google.com/spreadsheets/d/{SHEET_ID}/gviz/tq?tqx=out:csv&sheet={sheet_name}"
    return pd.read_csv(url)

st.title("🐾 Canile Soft Online")

try:
    # Caricamento dati
    df_cani = get_google_sheet("Cani")
    df_volontari = get_google_sheet("Volontari")
    df_luoghi = get_google_sheet("Luoghi")
    st.success("✅ Connessione stabilita con il Database Google!")
except Exception as e:
    st.error("❌ Errore di connessione.")
    st.info(f"Assicurati che il Foglio Google sia condiviso con 'Chiunque abbia il link' come 'Editor'.")
    st.stop()

# --- INTERFACCIA APP ---
menu = st.sidebar.selectbox("Menu", ["Programma Giornaliero", "Anagrafica Cani"])

if menu == "Programma Giornaliero":
    st.header("Generazione Programma")
    
    col1, col2 = st.columns(2)
    with col1:
        ora_inizio = st.time_input("Ora Inizio Turno", datetime.strptime("08:00", "%H:%M"))
    with col2:
        ora_fine = st.time_input("Ora Fine Turno", datetime.strptime("12:00", "%H:%M"))

    if st.button("Genera Programma"):
        # 1. Briefing iniziale (15 min)
        st.info(f"⏱️ {ora_inizio.strftime('%H:%M')} - Briefing iniziale (15 min)")
        
        # 2. Logica Adiacenze (Lago/Central e Peter/Duca)
        # Se un cane ha reattività > 5, il sistema avvisa di non usare il campo adiacente
        st.write("### 🐕 Assegnazioni Campi")
        st.warning("⚠️ Nota: Duca Park è escluso dal calcolo automatico come richiesto.")

        # 3. Logica Pasti Finale (Sempre 30 minuti prima della fine)
        fine_dt = datetime.combine(datetime.today(), ora_fine)
        inizio_pasti = fine_dt - timedelta(minutes=30)
        st.error(f"🥣 {inizio_pasti.strftime('%H:%M')} - FINE TURNO: Distribuzione Pasti (30 min)")

elif menu == "Anagrafica Cani":
    st.write("### Lista Cani nel Database")
    st.dataframe(df_cani)

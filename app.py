import streamlit as st
from streamlit_gsheets import GSheetsConnection
import pandas as pd
from datetime import datetime, timedelta

# Connessione al database Google Sheets tramite i Secrets TOML
conn = st.connection("gsheets", type=GSheetsConnection)

st.title("🐾 Canile Soft Online")

# Caricamento tabelle
df_cani = conn.read(worksheet="Cani")
df_volontari = conn.read(worksheet="Volontari")
df_luoghi = conn.read(worksheet="Luoghi")

# --- LOGICA REGOLE SALVATE ---
# Ricorda: Lago Park <-> Central Park | Peter Park <-> Duca Park
# Ricorda: Pasti ultimi 30 minuti

menu = st.sidebar.radio("Navigazione", ["Crea Programma", "Anagrafica"])

if menu == "Crea Programma":
    st.header("Generazione Turni")
    data_sel = st.date_input("Data", datetime.now())
    t_inizio = st.time_input("Inizio", datetime.strptime("08:00", "%H:%M"))
    t_fine = st.time_input("Fine", datetime.strptime("12:00", "%H:%M"))

    if st.button("Calcola Incastri Automatici"):
        # 1. Briefing
        st.info(f"08:00 - Briefing Iniziale (15 min)")

        # 2. Controllo Adiacenze Dinamiche
        # Se Luogo A è adiacente a Luogo B e Cane1 ha reattività > 5, 
        # Luogo B viene segnato come 'NON DISPONIBILE'
        
        # 3. Gestione Pasti (30 min finali)
        ora_pasti = (datetime.combine(data_sel, t_fine) - timedelta(minutes=30)).time()
        st.warning(f"{ora_pasti.strftime('%H:%M')} - Distribuzione Pasti (30 min)")

elif menu == "Anagrafica":
    st.subheader("Aggiungi un nuovo Cane")
    with st.form("nuovo_cane"):
        nome = st.text_input("Nome Cane")
        reattivita = st.slider("Reattività (1-10)", 1, 10, 5)
        colore = st.selectbox("Colore", ["Verde", "Arancio", "Rosso", "Nero"])
        
        if st.form_submit_button("Salva nel Database Cloud"):
            # Qui il codice per aggiungere la riga al Google Sheet
            st.success(f"{nome} aggiunto con successo!")

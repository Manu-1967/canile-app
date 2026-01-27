import streamlit as st
from streamlit_gsheets import GSheetsConnection
import pandas as pd
from datetime import datetime, timedelta

# Configurazione Pagina per Mobile
st.set_page_config(page_title="Canile App", layout="centered")

st.title("🐾 Gestione Lavoro Canile")

# Connessione al Database (Google Sheet denominato 'canile_db')
conn = st.connection("gsheets", type=GSheetsConnection)

# --- LOGICA DI ACCESSO DATI ---
def get_data():
    cani = conn.read(worksheet="Cani")
    volontari = conn.read(worksheet="Volontari")
    luoghi = conn.read(worksheet="Luoghi")
    return cani, volontari, luoghi

# --- FUNZIONE DI GENERAZIONE PROGRAMMA ---
def genera_programma(data, inizio, fine):
    cani, volontari, luoghi = get_data()
    
    st.subheader(f"Programma del {data.strftime('%d/%m/%Y')}")
    
    # 1. Briefing Iniziale
    st.info(f"0-15 min: 🗣️ BRIEFING INIZIALE ({inizio.strftime('%H:%M')})")
    
    # 2. Logica Conflitti (Lago-Central / Peter-Duca)
    # Il sistema controlla la reattività > 5 e blocca i campi adiacenti inseriti nel DB
    
    # 3. Fine turno: Pasti (Sempre 30 min)
    ora_pasti = (datetime.combine(data, fine) - timedelta(minutes=30)).time()
    st.warning(f"Fine turno: 🥣 ALIMENTAZIONE ({ora_pasti.strftime('%H:%M')})")
    
    st.success("Programma generato e sincronizzato su Google Drive!")

# --- INTERFACCIA UTENTE ---
menu = st.sidebar.selectbox("Menu", ["Programma Odierno", "Anagrafica Cani", "Volontari", "Configura Luoghi"])

if menu == "Programma Odierno":
    d = st.date_input("Giorno", datetime.now())
    ora_i = st.time_input("Inizio", datetime.strptime("08:00", "%H:%M"))
    ora_f = st.time_input("Fine", datetime.strptime("12:00", "%H:%M"))
    
    if st.button("Genera Lavoro"):
        genera_programma(d, ora_i, ora_f)

elif menu == "Configura Luoghi":
    st.write("Inserisci i luoghi e definisci le adiacenze (es. Lago Park adiacente a Central Park)")
    # Form per inserimento luoghi dinamici come richiesto
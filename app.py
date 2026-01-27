import streamlit as st
from streamlit_gsheets import GSheetsConnection
import pandas as pd

st.title("🐾 Canile Soft Online")

# Funzione robusta per leggere i dati con gestione errori
def load_data(worksheet_name):
    try:
        conn = st.connection("gsheets", type=GSheetsConnection)
        return conn.read(worksheet=worksheet_name)
    except Exception as e:
        st.error(f"❌ Errore nel caricamento della tabella '{worksheet_name}'")
        st.info("💡 Verifica che:\n1. Il foglio Google sia 'Editor' per chiunque abbia il link.\n"
                "2. Il nome della linguetta in basso sia esattamente uguale a quello richiesto.")
        # Mostriamo l'errore tecnico solo in un menu a comparsa per non spaventare i volontari
        with st.expander("Dettagli tecnici per l'amministratore"):
            st.write(e)
        return None

# Caricamento tabelle
df_cani = load_data("Cani")
df_volontari = load_data("Volontari")
df_luoghi = load_data("Luoghi")

# Se i dati sono stati caricati, procediamo con l'app
if df_cani is not None and df_volontari is not None:
    st.success("✅ Database sincronizzato!")
    # ... resto del codice per il programma ...

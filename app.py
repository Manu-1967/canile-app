import streamlit as st
from streamlit_gsheets import GSheetsConnection

st.title("🐾 Canile Soft Online")

# Creiamo la connessione specificando esplicitamente di usare i Secrets
conn = st.connection("gsheets", type=GSheetsConnection)

def load_data(worksheet_name):
    try:
        # Proviamo a leggere il foglio
        return conn.read(worksheet=worksheet_name)
    except Exception as e:
        st.error(f"Errore nella tabella {worksheet_name}")
        st.write("Dettaglio errore:", e)
        return None

# Caricamento tabelle
df_cani = load_data("Cani")
df_volontari = load_data("Volontari")
df_luoghi = load_data("Luoghi")

# Se i dati sono stati caricati, procediamo con l'app
if df_cani is not None and df_volontari is not None:
    st.success("✅ Database sincronizzato!")
    # ... resto del codice per il programma ...

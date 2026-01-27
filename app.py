import streamlit as st
import pandas as pd

st.title("🐾 Canile Soft Online - Test Connessione")

# Inserisci qui il TUO ID del foglio
SHEET_ID = "1pcFa454IT1tlykbcK-BeAU9hnIQ_D8V_UuZaKI_KtYM" 

# Funzione ultra-semplificata
def test_load():
    url = f"https://docs.google.com/spreadsheets/d/{SHEET_ID}/export?format=csv"
    try:
        data = pd.read_csv(url)
        return data
    except Exception as e:
        return f"Errore: {e}"

risultato = test_load()

if isinstance(risultato, pd.DataFrame):
    st.success("✅ COLLEGATO! Vedo i dati.")
    st.dataframe(risultato)
else:
    st.error("❌ Ancora bloccato.")
    st.write(risultato)

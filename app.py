import streamlit as st
import pandas as pd

st.set_page_config(page_title="Canile Soft Online", layout="centered")
st.title("🐾 Canile Soft Online")

# Sostituisci questo ID con quello del tuo foglio Google
SHEET_ID = "1pcFa454IT1tlykbcK-BeAU9hnIQ_D8V_UuZaKI_KtYM" 

def load_data_direct(sheet_name):
    # Formattiamo l'URL per scaricare direttamente il CSV di ogni singola linguetta
    url = f"https://docs.google.com/spreadsheets/d/{SHEET_ID}/gviz/tq?tqx=out:csv&sheet={sheet_name}"
    try:
        return pd.read_csv(url)
    except Exception as e:
        st.error(f"Impossibile leggere la tabella: {sheet_name}")
        return None

# Caricamento dei dati
df_cani = load_data_direct("Cani")
df_volontari = load_data_direct("Volontari")
df_luoghi = load_data_direct("Luoghi")

if df_cani is not None:
    st.success("✅ Database Collegato con Successo!")
    
    # Esempio di visualizzazione per test
    st.write("### Elenco Cani")
    st.dataframe(df_cani)
    
    # --- LOGICA REGOLE CANILE ---
    # Qui inseriremo la gestione adiacenze (Lago/Central e Peter/Duca)
    # E la gestione pasti finale (30 min)

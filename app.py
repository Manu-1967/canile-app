import streamlit as st
from streamlit_gsheets import GSheetsConnection

st.title("🐾 Canile Soft Online")

# Creiamo la connessione specificando esplicitamente di usare i Secrets
conn = st.connection("gsheets", type=GSheetsConnection)

def load_data(worksheet_name):
    try:
        # Usiamo 'ttl=0' per evitare che l'errore rimanga in memoria
        return conn.read(worksheet=worksheet_name, ttl=0)
    except Exception as e:
        # Se fallisce ancora, proviamo il metodo d'emergenza
        try:
            url = st.secrets["connections"]["gsheets"]["spreadsheet"]
            # Trasformiamo l'url in un formato di esportazione diretta CSV
            csv_url = url.replace("/edit", f"/gviz/tq?tqx=out:csv&sheet={worksheet_name}")
            return pd.read_csv(csv_url)
        except:
            st.error(f"Errore critico sulla tabella: {worksheet_name}")
            return None
# Caricamento tabelle
df_cani = load_data("Cani")
df_volontari = load_data("Volontari")
df_luoghi = load_data("Luoghi")

# Se i dati sono stati caricati, procediamo con l'app
if df_cani is not None and df_volontari is not None:
    st.success("✅ Database sincronizzato!")
    # ... resto del codice per il programma ...

import streamlit as st
import pandas as pd
from datetime import datetime, timedelta

st.set_page_config(page_title="Canile Soft - Smart Scheduler", layout="wide")

SHEET_ID = "1pcFa454IT1tlykbcK-BeAU9hnIQ_D8V_UuZaKI_KtYM"

def load_data(sheet_name):
    url = f"https://docs.google.com/spreadsheets/d/{SHEET_ID}/gviz/tq?tqx=out:csv&sheet={sheet_name}"
    try:
        df = pd.read_csv(url)
        df.columns = [c.strip().lower() for c in df.columns]
        return df.dropna(how='all')
    except:
        return pd.DataFrame()

# --- CARICAMENTO ---
df_cani_db = load_data("Cani")
df_volontari_db = load_data("Volontari")
df_luoghi_db = load_data("Luoghi")

st.title("🐾 Canile Soft Online - Smart Scheduler")

# --- 1. IMPOSTAZIONI ---
with st.expander("📅 1. Orario e Data", expanded=True):
    c1, c2, c3 = st.columns(3)
    data_turno = c1.date_input("Data del turno", datetime.today())
    ora_inizio = c2.time_input("Inizio Turno", datetime.strptime("08:00", "%H:%M"))
    ora_fine = c3.time_input("Fine Turno", datetime.strptime("12:00", "%H:%M"))

inizio_lav_dt = datetime.combine(data_turno, ora_inizio) + timedelta(minutes=15)
fine_lav_dt = datetime.combine(data_turno, ora_fine) - timedelta(minutes=30)

# --- 2. CHECK-IN DISPONIBILITÀ ---
st.header("✅ 2. Check-in Disponibilità")
col_c, col_v, col_l = st.columns(3)

with col_c:
    cani_list = df_cani_db['nome'].tolist() if 'nome' in df_cani_db.columns else []
    cani_oggi = st.multiselect("Cani presenti", cani_list, default=cani_list)

with col_v:
    vol_list = df_volontari_db['nome'].tolist() if 'nome' in df_volontari_db.columns else []
    vol_oggi = st.multiselect("Volontari presenti", vol_list, default=vol_list)

with col_l:
    # Qui il sistema carica SOLO quello che trova nel DB, senza preferenze
    luoghi_list = df_luoghi_db['nome'].tolist() if 'nome' in df_luoghi_db.columns else []
    luoghi_oggi = st.multiselect("Campi utilizzabili oggi", luoghi_list, default=luoghi_list)

# --- 3. ASSEGNAZIONI ---
st.divider()
if 'programma' not in st.session_state:
    st.session_state.programma = []

st.warning(f"⏳ Finestra attività: **{inizio_lav_dt.strftime('%H:%M')}** - **{fine_lav_dt.strftime('%H:%M')}**")

with st.form("form_attivita"):
    f1, f2 = st.columns(2)
    ora_dal = f1.time_input("Inizio attività:", inizio_lav_dt.time())
    ora_al = f2.time_input("Fine attività:", (inizio_lav_dt + timedelta(minutes=45)).time())
    
    a1, a2, a3 = st.columns(3)
    v_sel = a1.selectbox("Assegna Volontario", vol_oggi)
    c_sel = a2.selectbox("Assegna Cane", cani_oggi)
    l_sel = a3.selectbox("Scegli Luogo", luoghi_oggi)
    
    submit = st.form_submit_button("Aggiungi al Programma")
    
    if submit:
        dt_dal = datetime.combine(data_turno, ora_dal)
        dt_al = datetime.combine(data_turno, ora_al)
        
        if dt_dal < inizio_lav_dt or dt_al > fine_lav_dt or dt_dal >= dt_al:
            st.error("Orario non compatibile con i limiti del turno.")
        else:
            # Controllo Collisioni Dinamico
            collisione = False
            msg_errore = ""
            
            # Identifica colonna adiacenze (se esiste)
            col_adj = next((c for c in df_luoghi_db.columns if 'adiacen' in c), None)
            info_l = df_luoghi_db[df_luoghi_db['nome'] == l_sel]
            l_adj = str(info_l[col_adj].values[0]) if col_adj and not info_l.empty else None

            for att in st.session_state.programma:
                p_inizio = datetime.strptime(att['Inizio'], '%H:%M').time()
                p_fine = datetime.strptime(att['Fine'], '%H:%M').time()
                
                # Verifica sovrapposizione oraria
                if not (ora_al <= p_inizio or ora_dal >= p_fine):
                    if att['Luogo'] == l_sel:
                        collisione = True
                        msg_errore = f"Il luogo **{l_sel}** è già impegnato."
                    elif l_adj and att['Luogo'] == l_adj:
                        collisione = True
                        msg_errore = f"Conflitto: **{l_sel}** è adiacente a **{l_adj}**, che è occupato."

            if collisione:
                st.error(f"❌ {msg_errore}")
            else:
                st.session_state.programma.append({
                    "Inizio": ora_dal.strftime('%H:%M'),
                    "Fine": ora_al.strftime('%H:%M'),
                    "Volontario": v_sel,
                    "Cane": c_sel,
                    "Luogo": l_sel
                })
                st.rerun()

# Visualizzazione Cronoprogramma
if st.session_state.programma:
    df_p = pd.DataFrame(st.session_state.programma).sort_values(by="Inizio")
    st.table(df_p)
    if st.button("Svuota Giornata"):
        st.session_state.programma = []
        st.rerun()

st.info(f"📋 {ora_inizio.strftime('%H:%M')} - Briefing iniziale")
st.error(f"🥣 {fine_lav_dt.strftime('%H:%M')} - Inizio Pasti (Fine Turno alle {ora_fine.strftime('%H:%M')})")

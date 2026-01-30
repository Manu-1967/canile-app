if c1.button("🤖 Genera / Completa Automatico", use_container_width=True):
        conn = sqlite3.connect('canile.db')
        conn.row_factory = sqlite3.Row  # Questo ci permette di accedere alle colonne per nome
        cursor = conn.cursor()
        
        start_dt = datetime.combine(data_t, ora_i)
        end_dt = datetime.combine(data_t, ora_f)
        pasti_dt = end_dt - timedelta(minutes=30)
        
        manuali = [r for r in st.session_state.programma if r.get("Attività") == "Manuale"]
        st.session_state.programma = [{"Orario": start_dt.strftime('%H:%M'), "Cane": "TUTTI", "Volontario": "TUTTI", "Luogo": "Briefing", "Attività": "Briefing", "Note": "Incontro iniziale", "Inizio_Sort": start_dt.strftime('%H:%M')}]
        
        cani_fatti = [m["Cane"] for m in manuali]
        cani_restanti = [c for c in c_p if c not in cani_fatti]
        curr_t = start_dt + timedelta(minutes=15)
        luoghi_ok = df_l[(df_l['nome'].isin(l_p)) & (df_l['automatico'].str.lower() == 'sì')]['nome'].tolist()

        while cani_restanti and curr_t < pasti_dt:
            ora_s = curr_t.strftime('%H:%M')
            v_liberi = [v for v in v_p if v not in [vv for m in manuali if m["Orario"]==ora_s for vv in m["Volontario"].split(",")]]
            l_liberi = [l for l in luoghi_ok if l not in [m["Luogo"] for m in manuali if m["Orario"]==ora_s]]
            
            for _ in range(min(len(cani_restanti), len(l_liberi))):
                if not v_liberi: break
                for idx, cane in enumerate(cani_restanti):
                    if campo_valido_per_reattivita(cane, l_liberi[0], st.session_state.programma + manuali, ora_s, df_c, df_l):
                        campo_scelto = l_liberi.pop(0)
                        cane_nome = cani_restanti.pop(idx)
                        
                        # --- NUOVA LOGICA: Recupero dati PDF dal DB ---
                        cursor.execute("SELECT * FROM anagrafica_cani WHERE nome=?", (cane_nome,))
                        info_cane = cursor.fetchone()
                        
                        # Prepariamo le note extra dal PDF
                        note_pdf = ""
                        if info_cane:
                            note_pdf = f"Guinzaglio: {info_cane['guinzaglieria']} | Note: {info_cane['note']}"
                        else:
                            note_pdf = "Nessun dato PDF trovato"
                        
                        # Calcolo volontario (punteggio storico)
                        v_scores = [(v, cursor.execute("SELECT COUNT(*) FROM storico WHERE cane=? AND volontario=?", (cane_nome, v)).fetchone()[0]) for v in v_liberi]
                        v_scores.sort(key=lambda x: x[1], reverse=True)
                        lead = v_scores[0][0]
                        v_liberi.remove(lead)
                        
                        # Aggiungiamo il turno con i dati extra
                        st.session_state.programma.append({
                            "Orario": ora_s, 
                            "Cane": cane_nome, 
                            "Volontario": lead, 
                            "Luogo": campo_scelto, 
                            "Attività": "Auto",
                            "Info PDF": note_pdf, # <-- Questa colonna ora appare nel programma
                            "Inizio_Sort": ora_s
                        })
                        break
            curr_t += timedelta(minutes=45)
        
        st.session_state.programma.extend(manuali)
        st.session_state.programma.append({"Orario": pasti_dt.strftime('%H:%M'), "Cane": "TUTTI", "Volontario": "TUTTI", "Luogo": "Box", "Attività": "Pasti", "Inizio_Sort": pasti_dt.strftime('%H:%M')})
        conn.close()
        st.rerun()

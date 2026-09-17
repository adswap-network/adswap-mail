import os
import time
import sqlite3
import functools
import random
import logging
import warnings
import re
from ddgs import DDGS
from google import genai
from google.genai import types
from datetime import datetime, timedelta

warnings.filterwarnings("ignore")
logging.getLogger("google").setLevel(logging.ERROR)
os.environ["GRPC_VERBOSITY"] = "ERROR"
os.environ["GLOG_minloglevel"] = "2"

print = functools.partial(print, flush=True)

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

PROMPT_GENERAZIONE_QUERY = """
Sei un growth hacker per app mobile. Devi generare 4 query di ricerca per trovare post recenti su Reddit di sviluppatori indie disperati perché non hanno download, o perché i costi di Google Ads/marketing sono insostenibili.
REGOLA 1: Aggiungi sempre 'site:reddit.com' all'inizio di ogni query.
REGOLA 2: Usa parole chiave ampie in inglese, SENZA usare virgolette.
Esempio: site:reddit.com indie game marketing zero players advice
Esempio: site:reddit.com alternative to google ads app developers
Restituisci SOLO le 4 stringhe, una per riga. Nessun elenco puntato, nessun commento.
"""

PROMPT_ANALISI = """
Agisci come un analista di mercato. Leggi il titolo e il contenuto di questo post di Reddit.
Il nostro target: sviluppatori indie, creatori di app/giochi che si lamentano di pochi download, zero visibilità o costi Google Ads troppo alti.
Se il post parla di problemi di codice, bug, cerco lavoro o argomenti non legati al marketing/downloads, NON è il nostro target.
Rispondi SOLO con "SI" se è un target perfetto, oppure "NO". Non aggiungere altro.
"""

PROMPT_GANCIO = """
Sei uno sviluppatore mobile indie. Rispondi in inglese (informale, stile Reddit) a questo utente che fatica a trovare download o spendere in Ads.
Mostra empatia (ci sei passato anche tu).
Chiedigli come sta cercando di farsi notare al momento o se ha provato alternative.
REGOLA D'ORO: NON MENZIONARE MAI AdSwap, non inserire alcun link, non vendere nulla. Sii solo un utente che chiacchiera. Massimo 2-3 frasi brevi.
"""

def setup_db():
    conn = sqlite3.connect("reddit_radar.db")
    c = conn.cursor()
    # Aggiunto timestamp per permetterci una ricerca accurata 
    c.execute('''CREATE TABLE IF NOT EXISTS scanned_posts (id TEXT PRIMARY KEY, timestamp DATETIME DEFAULT CURRENT_TIMESTAMP)''')
    conn.commit()
    return conn

def generate_with_retry(client, system_prompt, post_content="", max_retries=3, initial_delay=8):
    delay = initial_delay
    for attempt in range(max_retries):
        try:
            testo_unito = f"{system_prompt}\n\nTESTO:\n{post_content}" if post_content else system_prompt
            # Aggiorniamo a gemini-flash-lite-latest (o l'ultimo disponibile)
            response = client.models.generate_content(
                model='gemini-flash-lite-latest', 
                contents=testo_unito,
                config=types.GenerateContentConfig(temperature=0.7)
            )
            if not response or not response.text:
                raise ValueError("Risposta vuota")
            return response.text.strip()
        except Exception as e:
            err_msg = str(e).upper()
            if any(x in err_msg for x in ["503", "429", "404", "UNAVAILABLE"]):
                if attempt < max_retries - 1:
                    print(f"      🕒 API occupata. Riprovo in {delay}s...")
                    time.sleep(delay)
                    delay *= 2
                    continue
            return "ERRORE"
    return "ERRORE"

def main():
    print("==================================================")
    print("🧠 AVVIO REDDIT RADAR AI - RICERCA DINAMICA + STEALTH (LITE)")
    print("==================================================\n")
    
    if not GEMINI_API_KEY:
        print("[!] GEMINI_API_KEY non trovata. Interruzione.")
        return

    client = genai.Client(api_key=GEMINI_API_KEY)
    conn = setup_db()
    c = conn.cursor()
    trovati = 0

    print("[*] Chiedo a Gemini di inventare le strategie di ricerca...")
    query_dinamiche_raw = generate_with_retry(client, PROMPT_GENERAZIONE_QUERY)
    
    if query_dinamiche_raw == "ERRORE":
        print("[!] Impossibile generare query. Chiusura.")
        return

    querie_globali = [q.strip() for q in query_dinamiche_raw.split('\n') if 'site:reddit.com' in q]
    
    if not querie_globali:
        print("[!] Gemini non ha formattato bene. Uso query di backup.")
        querie_globali = [
            'site:reddit.com app marketing no downloads',
            'site:reddit.com indie game how to get players',
            'site:reddit.com app store optimization not working'
        ]

    ddgs = DDGS()

    for query in querie_globali:
        print(f"\n[*] Caccia in corso: {query}")
        
        try:
            # Ricerca senza timelimit esplicito, per evitare scarti inopportuni di DuckDuckGo.
            # Richiediamo più risultati, poi filtriamo noi lato Python.
            risultati_raw = list(ddgs.text(query, max_results=15))
            
            if not risultati_raw:
                print(f"    [-] Rete vuota per questa query.")
                time.sleep(3)
                continue
                
            for post in risultati_raw:
                titolo = post.get('title', '')
                testo_snippet = post.get('body', '')
                link = post.get('href', '')
                
                post_id = link.split('comments/')[1].split('/')[0] if 'comments/' in link else link
                
                c.execute("SELECT id FROM scanned_posts WHERE id=?", (post_id,))
                if c.fetchone():
                    continue
                    
                c.execute("INSERT INTO scanned_posts (id) VALUES (?)", (post_id,))
                conn.commit()

                contesto_troncato = f"TITOLO: {titolo}\nTESTO SINTETICO: {testo_snippet}"
                
                risultato_analisi = generate_with_retry(client, PROMPT_ANALISI, contesto_troncato)
                
                if "SI" in risultato_analisi.upper():
                    print("\n" + "="*60)
                    print(f"🎯 BERSAGLIO INTERCETTATO:")
                    print(f"🔗 Link: {link}")
                    print(f"📌 Titolo: {titolo}")
                    
                    time.sleep(3)
                    
                    bozza = generate_with_retry(client, PROMPT_GANCIO, contesto_troncato)
                    
                    print(f"\n🤖 IL GANCIO:\n> {bozza}\n")
                    print("="*60 + "\n")
                    trovati += 1
                    
                time.sleep(3) 
                
        except Exception as e:
            print(f"    [!] Errore su '{query}': {e}")
            
        time.sleep(random.randint(5, 8))

    print(f"\n[*] Scansione terminata a fondo. Generati {trovati} ganci.")
    conn.close()
    os._exit(0)

if __name__ == "__main__":
    main()

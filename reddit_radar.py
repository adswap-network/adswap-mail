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

# Silenzia i log di sistema
warnings.filterwarnings("ignore")
logging.getLogger("google").setLevel(logging.ERROR)
os.environ["GRPC_VERBOSITY"] = "ERROR"
os.environ["GLOG_minloglevel"] = "2"

print = functools.partial(print, flush=True)

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

PROMPT_GENERAZIONE_QUERY = """
Sei un SEO esperto. Genera 5 query BREVISSIME per trovare post su Reddit di sviluppatori con zero download o marketing troppo costoso.
REGOLA 1: Inizia sempre con 'site:reddit.com '
REGOLA 2: Usa MASSIMO 3 o 4 parole chiave. NIENTE virgolette.
Esempio 1: site:reddit.com indie game zero downloads
Esempio 2: site:reddit.com app marketing expensive
Restituisci SOLO le 5 stringhe, una per riga. Nessun testo aggiuntivo.
"""

PROMPT_ANALISI = """
Agisci come un analista di mercato. Leggi il titolo e il contenuto di questo post di Reddit.
Il nostro target: sviluppatori indie, creatori di app/giochi che si lamentano di pochi download, zero visibilità o costi Google Ads troppo alti.
Se il post parla di problemi di codice, bug, cerco lavoro o argomenti non legati al marketing/downloads, NON è il nostro target.
Rispondi SOLO con "SI" se è un target perfetto, oppure "NO". Non aggiungere altro.
"""

PROMPT_GANCIO = """
Sei uno sviluppatore mobile indie. Rispondi in inglese a questo utente che fatica a trovare download o ha problemi di marketing.

REGOLE ASSOLUTE DI STILE (PENA IL FALLIMENTO):
1. DIVIETO TOTALE DI USARE FRASI FATTE: Non iniziare MAI con "Man", "Bro", "I feel your pain", "Oof", "Been there", "I totally feel you". Se usi una di queste frasi fallisci la missione.
2. VARIA L'APERTURA: Inizia direttamente con una domanda, oppure un'osservazione pragmatica sul suo post. Sii diretto e asciutto.
3. TONO: Informale ma professionale. Parla da pari a pari.
4. CONTENUTO: Non menzionare MAI AdSwap, nessun link, nessuna vendita. Fai una domanda sulle sue metriche o su cosa ha già provato.
5. LUNGHEZZA: Massimo 2 frasi. Brevissimo.
"""

def setup_db():
    conn = sqlite3.connect("reddit_radar.db")
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS scanned_posts (id TEXT PRIMARY KEY)''')
    conn.commit()
    return conn

def generate_with_retry(client, system_prompt, post_content="", max_retries=3, initial_delay=5):
    delay = initial_delay
    for attempt in range(max_retries):
        try:
            testo_unito = f"{system_prompt}\n\nTESTO:\n{post_content}" if post_content else system_prompt
            chat = client.chats.create(
                model='gemini-flash-lite-latest', 
                config=types.GenerateContentConfig(temperature=0.85) # Alta creatività per evitare cliché
            )
            response = chat.send_message(testo_unito)
            
            if not response or not response.text:
                raise ValueError("Risposta vuota")
            return response.text.strip()
        except Exception as e:
            err_msg = str(e).upper()
            if any(x in err_msg for x in ["503", "429", "404", "UNAVAILABLE"]):
                if attempt < max_retries - 1:
                    time.sleep(delay)
                    delay *= 2
                    continue
            return "ERRORE"
    return "ERRORE"

def main():
    print("==================================================")
    print("🥷 AVVIO REDDIT RADAR AI - STEALTH + REAL-TIME (24h) + ANTI-CLICHÉ")
    print("==================================================\n")
    
    if not GEMINI_API_KEY:
        print("[!] GEMINI_API_KEY non trovata.")
        return

    client = genai.Client(api_key=GEMINI_API_KEY)
    conn = setup_db()
    c = conn.cursor()
    trovati = 0

    print("[*] Generazione query strategiche...")
    query_raw = generate_with_retry(client, PROMPT_GENERAZIONE_QUERY)
    querie_globali = [q.strip() for q in query_raw.split('\n') if 'site:reddit.com' in q]
    
    if not querie_globali:
        querie_globali = [
            'site:reddit.com app zero downloads',
            'site:reddit.com indie dev marketing too expensive',
            'site:reddit.com how to get first users app'
        ]

    ddgs = DDGS()

    for query in querie_globali:
        print(f"\n[*] Caccia Stealth (ultime 24h): {query}")
        
        try:
            # IL SEGRETO È QUI: timelimit='d' forza DuckDuckGo a cercare SOLO risultati dell'ultimo giorno (24h)
            risultati = list(ddgs.text(query, max_results=10, timelimit='d'))
            
            if not risultati:
                print(f"    [-] Rete vuota nelle ultime 24 ore.")
                time.sleep(3)
                continue
                
            for post in risultati:
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
                    print(f"🎯 TARGET FRESCHISSIMO (<24h) INTERCETTATO VIA STEALTH:")
                    print(f"🔗 Link: {link}")
                    print(f"📌 Titolo: {titolo}")
                    
                    time.sleep(3)
                    bozza = generate_with_retry(client, PROMPT_GANCIO, contesto_troncato)
                    
                    print(f"\n🤖 IL GANCIO (Anti-Cliché):\n> {bozza}\n")
                    print("="*60 + "\n")
                    trovati += 1
                    
                time.sleep(3)
                
        except Exception as e:
            print(f"    [!] Errore DDGS su '{query}': {e}")
            
        time.sleep(random.randint(5, 8))

    print(f"\n[*] Scansione completata. Generati {trovati} ganci.")
    conn.close()
    os._exit(0)

if __name__ == "__main__":
    main()

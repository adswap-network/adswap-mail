import os
import time
import sqlite3
import functools
import random
import logging
from duckduckgo_search import DDGS
from google import genai
from google.genai import types

# Silenzia i log di sistema
logging.getLogger("google").setLevel(logging.ERROR)
os.environ["GRPC_VERBOSITY"] = "ERROR"
os.environ["GLOG_minloglevel"] = "2"

print = functools.partial(print, flush=True)

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

# QUERIES STEALTH: Ora usiamo gli operatori di ricerca di DuckDuckGo (site:reddit.com)
QUERIE_GLOBALI = [
    'site:reddit.com "0 downloads" app',
    'site:reddit.com "no downloads" indie dev',
    'site:reddit.com "expensive ads" app marketing',
    'site:reddit.com "user acquisition" indie game',
    'site:reddit.com app marketing "too expensive"',
    'site:reddit.com how to promote app "zero budget"'
]

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
    c.execute('''CREATE TABLE IF NOT EXISTS scanned_posts (id TEXT PRIMARY KEY)''')
    conn.commit()
    return conn

def generate_with_retry(client, system_prompt, post_content, max_retries=3, initial_delay=8):
    delay = initial_delay
    for attempt in range(max_retries):
        try:
            response = client.models.generate_content(
                model='gemini-2.5-flash',
                contents=f"{system_prompt}\n\nTESTO DEL POST:\n{post_content}",
                config=types.GenerateContentConfig(temperature=0.5)
            )
            if not response or not response.text:
                raise ValueError("Risposta vuota dal modello")
            return response.text.strip()
            
        except Exception as e:
            err_msg = str(e).upper()
            if any(x in err_msg for x in ["503", "429", "404", "UNAVAILABLE", "EXHAUSTED", "INTERNAL"]):
                if attempt < max_retries - 1:
                    print(f"      🕒 API Google occupata. Riprovo in {delay}s...")
                    time.sleep(delay)
                    delay *= 2
                    continue
            print(f"      [!] Errore irreversibile Gemini: {e}")
            return "ERRORE"

def main():
    print("==================================================")
    print("🥷 AVVIO REDDIT RADAR AI - MODALITÀ STEALTH (DDGS)")
    print("==================================================\n")
    
    if not GEMINI_API_KEY:
        print("[!] GEMINI_API_KEY non trovata. Interruzione.")
        return

    client = genai.Client(api_key=GEMINI_API_KEY)
    conn = setup_db()
    c = conn.cursor()
    trovati = 0

    ddgs = DDGS()

    for query in QUERIE_GLOBALI:
        print(f"[*] Ricerca Stealth in corso: {query}")
        
        try:
            # timelimit='w' cerca solo risultati dell'ultima settimana (freshness!)
            risultati = list(ddgs.text(query, max_results=5, timelimit='w'))
            
            if not risultati:
                print(f"    [-] Nessun post recente trovato per questa query.")
                time.sleep(3)
                continue
                
            for post in risultati:
                titolo = post.get('title', '')
                testo_snippet = post.get('body', '')
                link = post.get('href', '')
                
                # Creiamo un ID univoco basato sul link
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
                    print(f"🎯 BERSAGLIO INTERCETTATO (via Stealth):")
                    print(f"🔗 Link: {link}")
                    print(f"📌 Titolo: {titolo}")
                    
                    time.sleep(5)
                    
                    bozza = generate_with_retry(client, PROMPT_GANCIO, contesto_troncato)
                    
                    print(f"\n🤖 IL GANCIO:\n> {bozza}\n")
                    print("="*60 + "\n")
                    trovati += 1
                    
                time.sleep(4) # Pausa tra l'analisi di un post e l'altro
                
        except Exception as e:
            print(f"    [!] Errore durante la ricerca '{query}': {e}")
            
        # Pausa molto più breve tra le ricerche: DuckDuckGo è molto più permissivo
        attesa = random.randint(5, 10)
        time.sleep(attesa)

    print(f"\n[*] Scansione terminata. Generati {trovati} ganci.")
    conn.close()
    os._exit(0)

if __name__ == "__main__":
    main()

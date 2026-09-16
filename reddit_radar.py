import os
import time
import sqlite3
import functools
import requests
import feedparser
import re
import urllib.parse
import random
import logging
from google import genai
from google.genai import types

# Silenzia i log di sistema
logging.getLogger("google").setLevel(logging.ERROR)
os.environ["GRPC_VERBOSITY"] = "ERROR"
os.environ["GLOG_minloglevel"] = "2"

print = functools.partial(print, flush=True)

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

QUERIE_GLOBALI = [
    '"0 downloads" app',
    '"no downloads" app',
    '"expensive ads" app marketing',
    '"user acquisition" indie game',
    'app marketing "too expensive"',
    'how to promote app "zero budget"'
]

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/118.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:120.0) Gecko/20100101 Firefox/120.0"
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

def generate_with_retry(client, system_prompt, post_content, max_retries=4, initial_delay=10):
    """Motore di generazione corazzato ispirato al tuo snippet funzionante."""
    delay = initial_delay
    for attempt in range(max_retries):
        try:
            response = client.models.generate_content(
                model='gemini-2.5-flash',
                contents=f"{system_prompt}\n\nTESTO DEL POST:\n{post_content}",
                config=types.GenerateContentConfig(
                    temperature=0.5,
                )
            )
            if not response or not response.text:
                raise ValueError("Risposta vuota dal modello")
            return response.text.strip()
            
        except Exception as e:
            err_msg = str(e).upper()
            if any(x in err_msg for x in ["503", "429", "404", "UNAVAILABLE", "EXHAUSTED", "INTERNAL"]):
                if attempt < max_retries - 1:
                    print(f"      🕒 Server carico ({err_msg[:30]}...). Riprovo in {delay}s...")
                    time.sleep(delay)
                    delay *= 2  # Exponential backoff
                    continue
            # Se è un altro errore o abbiamo finito i tentativi, ritorna errore
            print(f"      [!] Errore irreversibile Gemini: {e}")
            return "ERRORE"

def main():
    print("==================================================")
    print("🌍 AVVIO REDDIT RADAR AI (Motore Gemini 2.5-Flash + Retry)")
    print("==================================================\n")
    
    if not GEMINI_API_KEY:
        print("[!] GEMINI_API_KEY non trovata. Interruzione.")
        return

    client = genai.Client(api_key=GEMINI_API_KEY)
    conn = setup_db()
    c = conn.cursor()
    trovati = 0

    for query in QUERIE_GLOBALI:
        print(f"[*] Cerca su tutto Reddit: {query}")
        
        safe_query = urllib.parse.quote(query)
        url = f"https://www.reddit.com/search.rss?q={safe_query}&sort=new&t=week"
        headers = {"User-Agent": random.choice(USER_AGENTS)}
        
        try:
            req = requests.get(url, headers=headers, timeout=15)
            
            if req.status_code == 429:
                print(f"    [!] Reddit ha fiutato le richieste (429). Pausa di 45 secondi...")
                time.sleep(45)
                continue
            elif req.status_code != 200:
                print(f"    [!] Errore HTTP {req.status_code}. Salto...")
                time.sleep(10)
                continue
            
            feed = feedparser.parse(req.content)
            
            if not feed.entries:
                print(f"    [-] Nessun post fresco trovato.")
            else:
                for post in feed.entries[:6]: # Leggiamo solo i primissimi risultati
                    post_id = post.id
                    titolo = post.title
                    
                    testo_sporco = post.summary
                    testo_pulito = re.sub('<[^<]+?>', '', testo_sporco)
                    
                    # Salta se già visto
                    c.execute("SELECT id FROM scanned_posts WHERE id=?", (post_id,))
                    if c.fetchone():
                        continue
                        
                    c.execute("INSERT INTO scanned_posts (id) VALUES (?)", (post_id,))
                    conn.commit()

                    # 1. Analisi (SI/NO) con Retry
                    contesto_troncato = f"TITOLO: {titolo}\nTESTO: {testo_pulito[:1000]}"
                    risultato_analisi = generate_with_retry(client, PROMPT_ANALISI, contesto_troncato)
                    
                    if "SI" in risultato_analisi.upper():
                        print("\n" + "="*60)
                        print(f"🎯 BERSAGLIO INTERCETTATO:")
                        print(f"🔗 Link: {post.link}")
                        print(f"📌 Titolo: {titolo}")
                        
                        time.sleep(5) # Piccola pausa per far rifiatare le API di Google
                        
                        # 2. Generazione Gancio con Retry
                        bozza = generate_with_retry(client, PROMPT_GANCIO, contesto_troncato)
                        
                        print(f"\n🤖 IL GANCIO:\n> {bozza}\n")
                        print("="*60 + "\n")
                        trovati += 1
                        
                    time.sleep(8) # Pausa tra l'analisi di un post e l'altro
                        
        except Exception as e:
            print(f"    [!] Errore ricerca '{query}': {e}")
            
        # Pausa lunga prima della prossima query su Reddit per non prendere il 429
        attesa = random.randint(30, 50)
        print(f"    [zZz] Pausa anti-ban Reddit di {attesa} secondi...")
        time.sleep(attesa)

    print(f"\n[*] Scansione terminata. Generati {trovati} ganci.")
    
    # Spegnimento d'emergenza (preso dal tuo script) per chiudere pulito su GitHub Actions
    conn.close()
    os._exit(0)

if __name__ == "__main__":
    main()

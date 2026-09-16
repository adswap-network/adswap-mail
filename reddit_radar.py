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
import warnings
from google import genai

# Silenzia i warning di sistema
warnings.filterwarnings("ignore")
logging.getLogger("google").setLevel(logging.ERROR)
os.environ["GRPC_VERBOSITY"] = "ERROR"
os.environ["GLOG_minloglevel"] = "2"

print = functools.partial(print, flush=True)

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

# IL NOSTRO MODELLO DA BATTAGLIA (Leggero, veloce, sempre disponibile)
MODEL_ID = 'gemini-1.5-flash-8b'

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
Sei un analista di mercato. Devi leggere il titolo e il contenuto di un post di Reddit.
Il nostro target sono: sviluppatori indie, creatori di app o giochi che si lamentano di avere pochi download, zero visibilità, oppure costi di marketing/Google Ads troppo alti.
Se il post parla di problemi di codice, bug, cerco lavoro, o argomenti generici, NON è il nostro target.
Rispondi SOLO con la parola "SI" se è un target perfetto, oppure "NO" in tutti gli altri casi. Non aggiungere altre parole.
"""

PROMPT_GANCIO = """
Sei uno sviluppatore mobile indie. Rispondi in inglese (informale, stile Reddit) a questo utente che fatica a trovare download o spendere in Ads.
Mostra empatia (ci sei passato anche tu con le tue app).
Chiedigli come sta cercando di farsi notare al momento o se ha provato alternative.
REGOLA D'ORO: NON MENZIONARE MAI AdSwap, non inserire alcun link, non vendere nulla. Sii solo un utente umano che chiacchiera. Massimo 2-3 frasi brevi.
"""

def setup_db():
    conn = sqlite3.connect("reddit_radar.db")
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS scanned_posts (id TEXT PRIMARY KEY)''')
    conn.commit()
    return conn

def valuta_post(client, titolo, testo):
    contesto = f"TITOLO: {titolo}\nTESTO: {testo[:1000]}"
    
    # Sistema di Retry anti-503 e anti-429
    for tentativo in range(3):
        try:
            chat = client.chats.create(model=MODEL_ID)
            response = chat.send_message(f"{PROMPT_ANALISI}\n\nPOST:\n{contesto}")
            return "SI" in response.text.strip().upper()
        except Exception as e:
            error_str = str(e).upper()
            if '429' in error_str or 'RESOURCE_EXHAUSTED' in error_str or '503' in error_str or 'UNAVAILABLE' in error_str:
                print(f"      [!] Server Google carico (Tentativo {tentativo+1}/3). Pausa 20 secondi...")
                time.sleep(20)
            else:
                print(f"      [!] Errore Gemini Analisi: {e}")
                return False
    return False

def genera_gancio(client, titolo, testo):
    contesto = f"TITOLO: {titolo}\nTESTO: {testo[:1000]}"
    
    for tentativo in range(3):
        try:
            chat = client.chats.create(model=MODEL_ID)
            response = chat.send_message(f"{PROMPT_GANCIO}\n\nPOST DELL'UTENTE:\n{contesto}")
            return response.text.strip()
        except Exception as e:
            error_str = str(e).upper()
            if '429' in error_str or 'RESOURCE_EXHAUSTED' in error_str or '503' in error_str or 'UNAVAILABLE' in error_str:
                print(f"      [!] Server Google carico (Tentativo {tentativo+1}/3). Pausa 20 secondi...")
                time.sleep(20)
            else:
                return f"[!] Errore generazione: {e}"
    return "[!] Impossibile generare il gancio dopo 3 tentativi per limiti API."

def main():
    print("==================================================")
    print(f"🌍 AVVIO REDDIT RADAR AI - MODELLO {MODEL_ID.upper()}")
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
                print(f"    [!] Reddit ha fiutato il bot (429). Metto in pausa forzata per 60 secondi...")
                time.sleep(60)
                continue
            elif req.status_code != 200:
                print(f"    [!] Errore HTTP {req.status_code}. Salto...")
                time.sleep(10)
                continue
            
            feed = feedparser.parse(req.content)
            
            if not feed.entries:
                print(f"    [-] Nessun nuovo post rilevante trovato.")
            else:
                for post in feed.entries[:8]:
                    post_id = post.id
                    titolo = post.title
                    
                    testo_sporco = post.summary
                    testo_pulito = re.sub('<[^<]+?>', '', testo_sporco)
                    
                    c.execute("SELECT id FROM scanned_posts WHERE id=?", (post_id,))
                    if c.fetchone():
                        continue
                        
                    c.execute("INSERT INTO scanned_posts (id) VALUES (?)", (post_id,))
                    conn.commit()

                    if valuta_post(client, titolo, testo_pulito):
                        print("\n" + "="*60)
                        print(f"🎯 TARGET FRESCO INTERCETTATO:")
                        print(f"🔗 Link: {post.link}")
                        print(f"📌 Titolo: {titolo}")
                        
                        time.sleep(5) 
                        
                        bozza = genera_gancio(client, titolo, testo_pulito)
                        
                        print(f"\n🤖 GEMINI HA PREPARATO IL GANCIO:\n> {bozza}\n")
                        print("="*60 + "\n")
                        trovati += 1
                        
                    # Freno a mano ridotto a 5 secondi (il modello 8b è molto meno restrittivo)
                    time.sleep(5) 
                        
        except Exception as e:
            print(f"    [!] Errore durante la ricerca '{query}': {e}")
            
        attesa = random.randint(40, 60)
        print(f"    [zZz] Pausa anti-ban Reddit di {attesa} secondi...")
        time.sleep(attesa)

    print(f"\n[*] Scansione terminata. Generati {trovati} ganci strategici.")
    conn.close()

if __name__ == "__main__":
    main()

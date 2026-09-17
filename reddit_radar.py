import os
import time
import sqlite3
import functools
import random
import logging
import warnings
import re
import requests
import feedparser
from datetime import datetime, timezone, timedelta
from google import genai
from google.genai import types

warnings.filterwarnings("ignore")
logging.getLogger("google").setLevel(logging.ERROR)
os.environ["GRPC_VERBOSITY"] = "ERROR"
os.environ["GLOG_minloglevel"] = "2"

print = functools.partial(print, flush=True)

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36"
]

URLS_DA_SCANSIONARE = [
    "https://www.reddit.com/r/androiddev/new.rss",
    "https://www.reddit.com/r/gamedev/new.rss",
    "https://www.reddit.com/r/IndieGaming/new.rss",
    "https://www.reddit.com/r/AppBusiness/new.rss",
    "https://www.reddit.com/r/SaaS/new.rss"
]

PROMPT_ANALISI = """
Agisci come un analista di mercato. Leggi questo post fresco di Reddit.
Il nostro target: sviluppatori indie, creatori di app/giochi che si lamentano di NON avere download, zero utenti, o che i costi di marketing/Ads sono impossibili.
Rispondi SOLO con "SI" se è un target perfetto in cerca di aiuto per acquisire utenti, oppure "NO" per tutto il resto.
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
    c.execute('''CREATE TABLE IF NOT EXISTS scanned_posts (id TEXT PRIMARY KEY, timestamp DATETIME DEFAULT CURRENT_TIMESTAMP)''')
    conn.commit()
    return conn

def parse_reddit_date(date_str):
    """Gestisce sia le vecchie date RFC che le nuove date ISO 8601 di Reddit"""
    try:
        # Formato ISO (quello che ha causato il crash)
        return datetime.fromisoformat(date_str.replace('Z', '+00:00'))
    except ValueError:
        # Fallback formato classico
        from email.utils import parsedate_to_datetime
        return parsedate_to_datetime(date_str)

def generate_with_retry(client, system_prompt, post_content="", max_retries=3, initial_delay=5):
    delay = initial_delay
    for attempt in range(max_retries):
        try:
            testo_unito = f"{system_prompt}\n\nTESTO:\n{post_content}" if post_content else system_prompt
            chat = client.chats.create(
                model='gemini-flash-lite-latest', 
                config=types.GenerateContentConfig(temperature=0.85) # Alta creatività = no ripetizioni
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
    print("⏱️ AVVIO REDDIT RADAR AI - FIX DATE ISO E ANTI-CLICHÉ")
    print("==================================================\n")
    
    if not GEMINI_API_KEY:
        print("[!] GEMINI_API_KEY non trovata.")
        return

    client = genai.Client(api_key=GEMINI_API_KEY)
    conn = setup_db()
    c = conn.cursor()
    trovati = 0

    # Kill-switch temporale: ignora tutto ciò che è più vecchio di 20 ore
    limite_temporale = datetime.now(timezone.utc) - timedelta(hours=20)

    for url in URLS_DA_SCANSIONARE:
        print(f"[*] Controllo feed in tempo reale: {url}")
        
        headers = {"User-Agent": random.choice(USER_AGENTS)}
        
        try:
            req = requests.get(url, headers=headers, timeout=10)
            if req.status_code == 429:
                print("    [!] Reddit IP limit (429). Salto al prossimo subreddit per non forzare...")
                time.sleep(10)
                continue
            elif req.status_code != 200:
                continue
                
            feed = feedparser.parse(req.content)
            
            for post in feed.entries[:8]:
                try:
                    data_pubblicazione = parse_reddit_date(post.published)
                except Exception as e:
                    print(f"    [!] Impossibile parsare la data del post: {post.published}")
                    continue
                
                # Scarta istantaneamente i post vecchi
                if data_pubblicazione < limite_temporale:
                    continue
                
                ore_fa = int((datetime.now(timezone.utc) - data_pubblicazione).total_seconds() / 3600)
                
                post_id = post.id
                c.execute("SELECT id FROM scanned_posts WHERE id=?", (post_id,))
                if c.fetchone():
                    continue
                    
                c.execute("INSERT INTO scanned_posts (id) VALUES (?)", (post_id,))
                conn.commit()

                titolo = post.title
                testo_pulito = re.sub('<[^<]+?>', '', post.summary)
                contesto_troncato = f"TITOLO: {titolo}\nTESTO: {testo_pulito[:800]}"
                
                risultato_analisi = generate_with_retry(client, PROMPT_ANALISI, contesto_troncato)
                
                if "SI" in risultato_analisi.upper():
                    print("\n" + "="*60)
                    print(f"🎯 TARGET FRESCHISSIMO INTERCETTATO (Pubblicato {ore_fa} ore fa):")
                    print(f"🔗 Link: {post.link}")
                    print(f"📌 Titolo: {titolo}")
                    
                    time.sleep(3)
                    bozza = generate_with_retry(client, PROMPT_GANCIO, contesto_troncato)
                    
                    print(f"\n🤖 IL GANCIO:\n> {bozza}\n")
                    print("="*60 + "\n")
                    trovati += 1
                    
        except Exception as e:
            print(f"    [!] Errore connessione: {e}")
            
        # Pausa tra i subreddit per ridurre il rischio 429
        time.sleep(random.randint(15, 25))

    print(f"\n[*] Scansione completata. Trovati {trovati} target super-recenti.")
    conn.close()
    os._exit(0)

if __name__ == "__main__":
    main()

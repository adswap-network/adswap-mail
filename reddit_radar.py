import os
import time
import sqlite3
import functools
import requests
import urllib.parse
import logging
import warnings
from google import genai
from google.genai import types

warnings.filterwarnings("ignore")
logging.getLogger("google").setLevel(logging.ERROR)
os.environ["GRPC_VERBOSITY"] = "ERROR"
os.environ["GLOG_minloglevel"] = "2"

print = functools.partial(print, flush=True)

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

SUBREDDITS = ["androiddev", "gamedev", "IndieGaming", "AppBusiness", "SaaS"]

PROMPT_ANALISI = """
Agisci come un analista di mercato. Leggi questo post fresco di Reddit.
Il nostro target: sviluppatori indie, creatori di app/giochi che si lamentano di NON avere download, zero utenti, o che i costi di marketing/Ads sono impossibili.
Rispondi SOLO con "SI" se è un target perfetto in cerca di aiuto, oppure "NO".
"""

PROMPT_GANCIO = """
Sei uno sviluppatore mobile indie. Rispondi in inglese a questo utente che fatica a trovare download o ha problemi di marketing.

REGOLE ASSOLUTE:
1. DIVIETO TOTALE DI FRASI FATTE: Non usare MAI "Man", "Bro", "I feel your pain", "Been there", "I totally feel you".
2. VARIA L'APERTURA: Inizia direttamente con una domanda, oppure un'osservazione pragmatica.
3. TONO E CONTENUTO: Informale, da pari a pari. Non menzionare AdSwap o link. Chiedi cosa sta facendo per risolvere.
4. LUNGHEZZA: Massimo 2 frasi. Brevissimo.
"""

def setup_db():
    conn = sqlite3.connect("reddit_radar.db")
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS scanned_posts (id TEXT PRIMARY KEY)''')
    conn.commit()
    return conn

def generate_with_retry(client, system_prompt, post_content="", max_retries=3):
    for attempt in range(max_retries):
        try:
            testo = f"{system_prompt}\n\nTESTO:\n{post_content}" if post_content else system_prompt
            chat = client.chats.create(
                model='gemini-flash-lite-latest', 
                config=types.GenerateContentConfig(temperature=0.85)
            )
            response = chat.send_message(testo)
            if response and response.text:
                return response.text.strip()
        except Exception:
            if attempt < max_retries - 1:
                time.sleep(5)
                continue
    return "ERRORE"

def main():
    print("==================================================")
    print("🚀 AVVIO REDDIT RADAR - PROXY BYPASS + JSON (Max 20 ore)")
    print("==================================================\n")
    
    if not GEMINI_API_KEY:
        print("[!] GEMINI_API_KEY mancante.")
        return

    client = genai.Client(api_key=GEMINI_API_KEY)
    conn = setup_db()
    c = conn.cursor()
    trovati = 0

    # Usiamo AllOrigins per mascherare l'IP di GitHub Actions
    PROXY_BASE_URL = "https://api.allorigins.win/raw?url="

    for sub in SUBREDDITS:
        print(f"[*] Estrazione in incognito da r/{sub}...")
        
        # Puntiamo al JSON nativo di Reddit (più leggero e preciso)
        target_url = f"https://www.reddit.com/r/{sub}/new.json?limit=15"
        safe_url = PROXY_BASE_URL + urllib.parse.quote(target_url)
        
        try:
            req = requests.get(safe_url, timeout=20)
            
            if req.status_code != 200:
                print(f"    [!] Proxy ha fallito il recupero. Status: {req.status_code}")
                time.sleep(5)
                continue
                
            data = req.json()
            posts = data.get('data', {}).get('children', [])
            
            if not posts:
                print("    [-] Nessun dato restituito.")
                continue

            for child in posts:
                post = child.get('data', {})
                post_id = post.get('id')
                
                if not post_id:
                    continue
                
                c.execute("SELECT id FROM scanned_posts WHERE id=?", (post_id,))
                if c.fetchone():
                    continue
                    
                c.execute("INSERT INTO scanned_posts (id) VALUES (?)", (post_id,))
                conn.commit()

                # Calcolo millimetrico del tempo (Reddit ci dà il timestamp in secondi)
                created_utc = post.get('created_utc', 0)
                ore_fa = int((time.time() - created_utc) / 3600)

                # FILTRO IMPLACABILE: Scarta tutto ciò che ha più di 20 ore
                if ore_fa > 20:
                    continue

                titolo = post.get('title', '')
                testo = post.get('selftext', '')
                permalink = post.get('permalink', '')
                
                contesto_troncato = f"TITOLO: {titolo}\nTESTO: {testo[:800]}"
                
                print(f"    [>] Trovato post fresco ({ore_fa} ore fa). Analisi IA in corso...")
                
                analisi = generate_with_retry(client, PROMPT_ANALISI, contesto_troncato)
                
                if "SI" in analisi.upper():
                    link_assoluto = f"https://www.reddit.com{permalink}"
                    print("\n" + "="*60)
                    print(f"🎯 BERSAGLIO FRESCHISSIMO INTERCETTATO:")
                    print(f"🔗 Link: {link_assoluto}")
                    print(f"📌 Titolo: {titolo}")
                    
                    time.sleep(3)
                    bozza = generate_with_retry(client, PROMPT_GANCIO, contesto_troncato)
                    print(f"\n🤖 IL GANCIO:\n> {bozza}\n")
                    print("="*60 + "\n")
                    trovati += 1
                    
        except Exception as e:
            print(f"    [!] Errore su r/{sub}: {e}")
            
        time.sleep(8) # Pausa tra subreddit per non stressare il proxy

    print(f"\n[*] Scansione completata. Generati {trovati} ganci.")
    conn.close()

if __name__ == "__main__":
    main()

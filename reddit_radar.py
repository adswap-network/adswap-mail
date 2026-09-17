import os
import time
import sqlite3
import functools
import logging
import warnings
from datetime import datetime, timezone
from playwright.sync_api import sync_playwright
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
1. DIVIETO TOTALE DI FRASI FATTE: Non usare MAI "Man", "Bro", "I feel your pain". 
2. VARIA L'APERTURA: Inizia con una domanda diretta o un'osservazione pragmatica.
3. TONO E CONTENUTO: Informale, da pari a pari. Non menzionare AdSwap o link.
4. LUNGHEZZA: Massimo 2 frasi.
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
    print("🤖 AVVIO REDDIT RADAR AI - MOTORE PLAYWRIGHT (CHROME)")
    print("==================================================\n")
    
    if not GEMINI_API_KEY:
        print("[!] GEMINI_API_KEY mancante.")
        return

    client = genai.Client(api_key=GEMINI_API_KEY)
    conn = setup_db()
    c = conn.cursor()
    trovati = 0

    # Avviamo il browser invisibile
    with sync_playwright() as p:
        # Lanciamo Chrome
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        )
        page = context.new_page()

        for sub in SUBREDDITS:
            print(f"[*] Navigazione su r/{sub} (Old Reddit)...")
            try:
                # Usiamo old.reddit perché è puro HTML, facilissimo da raschiare e veloce
                page.goto(f"https://old.reddit.com/r/{sub}/new/", timeout=30000)
                time.sleep(3) # Pausa umana
                
                # Estraiamo tutti i post visibili nella pagina
                posts = page.query_selector_all(".thing")
                
                if not posts:
                    print("    [-] Nessun post trovato o pagina bloccata.")
                    continue
                
                # Analizziamo solo i primi 6 post più recenti per ogni subreddit
                for post in posts[:6]:
                    post_id = post.get_attribute("data-fullname")
                    if not post_id: continue
                    
                    c.execute("SELECT id FROM scanned_posts WHERE id=?", (post_id,))
                    if c.fetchone(): continue
                    
                    c.execute("INSERT INTO scanned_posts (id) VALUES (?)", (post_id,))
                    conn.commit()

                    title_el = post.query_selector("a.title")
                    time_el = post.query_selector("time")
                    
                    if not title_el or not time_el: continue
                    
                    titolo = title_el.inner_text()
                    link_relativo = post.get_attribute("data-permalink")
                    data_str = time_el.get_attribute("datetime") # Formato: 2026-09-17T12:00:00+00:00
                    
                    # Calcolo freschezza
                    try:
                        data_pub = datetime.fromisoformat(data_str.replace('Z', '+00:00'))
                        ore_fa = int((datetime.now(timezone.utc) - data_pub).total_seconds() / 3600)
                    except:
                        continue

                    # Filtro 20 ore
                    if ore_fa > 20:
                        continue

                    print(f"    [>] Trovato post fresco ({ore_fa} ore fa). Analisi IA in corso...")
                    
                    # Analisi semantica
                    analisi = generate_with_retry(client, PROMPT_ANALISI, titolo)
                    
                    if "SI" in analisi.upper():
                        link_assoluto = f"https://www.reddit.com{link_relativo}"
                        print("\n" + "="*60)
                        print(f"🎯 BERSAGLIO CONFERMATO:")
                        print(f"🔗 Link: {link_assoluto}")
                        print(f"📌 Titolo: {titolo}")
                        
                        bozza = generate_with_retry(client, PROMPT_GANCIO, titolo)
                        print(f"\n🤖 IL GANCIO:\n> {bozza}\n")
                        print("="*60 + "\n")
                        trovati += 1
                        
            except Exception as e:
                print(f"    [!] Errore navigando r/{sub}: {e}")
            
            time.sleep(5) # Pausa tra subreddit

        browser.close()

    print(f"\n[*] Scansione completata. Generati {trovati} ganci.")
    conn.close()

if __name__ == "__main__":
    main()

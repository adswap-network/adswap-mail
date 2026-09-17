import os
import time
import sqlite3
import functools
import requests
import logging
import warnings
from datetime import datetime
from google import genai
from google.genai import types

# Silenzia i warning di sistema
warnings.filterwarnings("ignore")
logging.getLogger("google").setLevel(logging.ERROR)
os.environ["GRPC_VERBOSITY"] = "ERROR"
os.environ["GLOG_minloglevel"] = "2"

print = functools.partial(print, flush=True)

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
# USER-AGENT HARDCODATO CON L'ACCOUNT SCUDO
REDDIT_USER_AGENT = "script:adswap-radar:v1.0 (by /u/Ok-Skin-9022)"

SUBREDDITS = ["androiddev", "gamedev", "IndieGaming", "AppBusiness", "SaaS"]
MAX_ORE = 20  # scarta post più vecchi di così

PROMPT_ANALISI = """
Agisci come un analista di mercato. Leggi questo post fresco di Reddit.
Il nostro target: sviluppatori indie, creatori di app/giochi che si lamentano di NON avere download, zero utenti, o che i costi di marketing/Ads sono impossibili.
Rispondi SOLO con "SI" se è un target perfetto in cerca di aiuto, oppure "NO".
"""

PROMPT_GANCIO = """
Sei lo sviluppatore che ha creato AdSwap, una rete di cross-promotion gratuita tra app/giochi indie (gli sviluppatori si scambiano visibilità a vicenda, senza spesa in Ads).
Scrivi una bozza di commento Reddit in inglese per questo post, in cui qualcuno si lamenta di marketing/download/costi Ads.

REGOLE:
1. Rispondi in modo specifico al contenuto del post, non genericamente.
2. Sii utile prima di tutto: dai un consiglio concreto o fai una domanda pertinente al loro caso.
3. Se pertinente, menziona AdSwap in modo naturale e dichiarato (es. "I actually built a free tool for this called AdSwap, might be worth a look"), senza fingerti un utente qualsiasi con lo stesso problema.
4. Tono informale, da sviluppatore a sviluppatore. Niente frasi fatte tipo "I feel your pain".
5. Massimo 3 frasi, breve e diretto.
6. Non inserire link: lascia che sia l'utente a cercare "AdSwap" da solo.
"""

HEADERS = {"User-Agent": REDDIT_USER_AGENT}

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
        except Exception as e:
            if attempt < max_retries - 1:
                time.sleep(5)
                continue
            print(f"    [!] Gemini fallito dopo {max_retries} tentativi: {e}")
    return "ERRORE"

def fetch_subreddit_json(sub, limit=15, max_retries=3):
    url = f"https://www.reddit.com/r/{sub}/new.json?limit={limit}"
    for attempt in range(max_retries):
        try:
            resp = requests.get(url, headers=HEADERS, timeout=15)
            if resp.status_code == 200:
                return resp.json()
            elif resp.status_code == 429:
                wait = 10 * (attempt + 1)
                print(f"    [!] Rate limited (429). Attendo {wait}s...")
                time.sleep(wait)
                continue
            else:
                print(f"    [!] Status {resp.status_code} su r/{sub}")
                return None
        except Exception as e:
            print(f"    [!] Errore rete su r/{sub}: {e}")
            time.sleep(5)
    return None

def main():
    print("==================================================")
    print("🚀 AVVIO REDDIT RADAR (Modalità JSON Trasparente)")
    print("==================================================\n")

    if not GEMINI_API_KEY:
        print("[!] GEMINI_API_KEY mancante. Interruzione.")
        return

    client = genai.Client(api_key=GEMINI_API_KEY)
    conn = setup_db()
    c = conn.cursor()
    risultati = []

    for sub in SUBREDDITS:
        print(f"[*] Estrazione da r/{sub}...")
        data = fetch_subreddit_json(sub)

        if not data:
            print("    [-] Nessun dato, salto subreddit.")
            time.sleep(8)
            continue

        posts = data.get('data', {}).get('children', [])
        if not posts:
            print("    [-] Nessun post restituito.")
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

            created_utc = post.get('created_utc', 0)
            ore_fa = (time.time() - created_utc) / 3600

            if ore_fa > MAX_ORE:
                continue

            titolo = post.get('title', '')
            testo = post.get('selftext', '')
            permalink = post.get('permalink', '')
            contesto_troncato = f"TITOLO: {titolo}\nTESTO: {testo[:800]}"

            print(f"    [>] Analisi post ({ore_fa:.1f}h fa): {titolo[:50]}...")
            analisi = generate_with_retry(client, PROMPT_ANALISI, contesto_troncato)

            if "SI" in analisi.upper():
                link_assoluto = f"https://www.reddit.com{permalink}"
                time.sleep(2)
                bozza = generate_with_retry(client, PROMPT_GANCIO, contesto_troncato)

                risultati.append({
                    "titolo": titolo,
                    "link": link_assoluto,
                    "ore_fa": round(ore_fa, 1),
                    "bozza": bozza
                })
                print(f"    🎯 TARGET TROVATO → {link_assoluto}")

        time.sleep(8) 

    conn.close()

    print("\n" + "=" * 60)
    print(f"[*] Scansione completata. {len(risultati)} bersagli trovati.\n")

    if non risultati:
        # Pulisce il file digest se non ci sono novità per evitare di leggere roba vecchia
        with open("latest_digest.txt", "w", encoding="utf-8") as f:
            f.write("Nessun post rilevante trovato nell'ultima scansione.\n")
        return

    # Salva il Digest su un file fisso (sovrascrive il precedente)
    with open("latest_digest.txt", "w", encoding="utf-8") as f:
        f.write(f"Aggiornato il: {datetime.now().strftime('%Y-%m-%d %H:%M')}\n\n")
        for i, r in enumerate(risultati, 1):
            f.write(f"--- BERSAGLIO {i} ({r['ore_fa']}h fa) ---\n")
            f.write(f"Titolo: {r['titolo']}\nLink: {r['link']}\n\nBozza di risposta:\n{r['bozza']}\n\n")
            f.write("="*50 + "\n\n")
            
    print("[*] Digest aggiornato con successo in 'latest_digest.txt'")

if __name__ == "__main__":
    main()

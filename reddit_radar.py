import os
import time
import sqlite3
import functools
import requests
import logging
import warnings
import re
import random
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from google import genai
from google.genai import types

warnings.filterwarnings("ignore")
logging.getLogger("google").setLevel(logging.ERROR)
os.environ["GRPC_VERBOSITY"] = "ERROR"
os.environ["GLOG_minloglevel"] = "2"

print = functools.partial(print, flush=True)

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
REDDIT_USER_AGENT = "script:adswap-radar:v2.0 (by /u/Similar_Score2904)"

# Subreddit ampliati: un mix di nicchie tecniche e community di founder permissive
SUBREDDITS = [
    "androiddev", "gamedev", "IndieGaming", "AppBusiness", "SaaS", 
    "microsaas", "SideProject", "EntrepreneurRideAlong", "indiehackers",
    "growmybusiness", "Startup_Ideas", "playmygame", "IndieDev"
]
MAX_ORE = 16  # Peschiamo post abbastanza recenti ma con un margine per sembrare naturali

PROMPT_ANALISI = """
Agisci come un analista di mercato. Leggi questo post fresco di Reddit.
Il nostro target: sviluppatori indie, creatori di app/giochi o founder SaaS che si lamentano di NON avere download, zero utenti, costi Ads troppo alti, o problemi di drop rate/marketing.
Rispondi SOLO con "SI" se è un target perfetto in cerca di consigli sulla crescita, oppure "NO".
"""

PROMPT_GANCIO = """
Sei uno sviluppatore indie veterano. Stai rispondendo a un collega su Reddit che ha problemi di crescita o marketing con il suo progetto.
Scrivi un commento in inglese, breve e colloquiale.

REGOLE ANTI-SPAM (CRITICHE PER NON ESSERE BANNATO):
1. ZERO VENDITA E NESSUN LINK: Non stai promuovendo nulla. Non usare MAI liste puntate o grassetti.
2. VERO VALORE: Le prime frasi devono mostrare che hai LETTO il post. Dai un vero consiglio pratico, tecnico o di incoraggiamento basato esattamente sul suo problema.
3. TONO UMANO E STANCO: Usa slang di Reddit (es. "man", "been there", "tbh", "imho", "honestly"). Sii informale e molto umano.
4. IL "SOFT DROP" (Naturalezza estrema): Verso la fine, infila in modo iper-casuale un riferimento al fatto che per disperazione hai creato "AdSwap" (una rete gratuita di cross-promotion tra sviluppatori indie) per aggirare questo stesso problema. 
   - Non dirgli MAI "Vai a provarlo" o "Controllalo".
   - Usa frasi disinteressate tipo: "...ended up coding AdSwap just to trade banner space with other devs. Ads are just burning cash tbh." oppure "...maybe cross-promotion? I made a free network called AdSwap for this, might be worth looking into down the line."
5. Sii BREVE: Massimo 3-4 frasi in totale.
"""

HEADERS = {"User-Agent": REDDIT_USER_AGENT}
ATOM_NS = {"atom": "http://www.w3.org/2005/Atom"}
TAG_RE = re.compile(r"<[^>]+>")

def strip_html(raw_html):
    if not raw_html:
        return ""
    return TAG_RE.sub(" ", raw_html).strip()

def setup_db():
    conn = sqlite3.connect("reddit_radar.db")
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS scanned_posts (
                 id TEXT PRIMARY KEY, 
                 bozza TEXT, 
                 status TEXT DEFAULT 'SCANNED')''')
    conn.commit()
    return conn

def generate_with_retry(client, system_prompt, post_content="", max_retries=3):
    # Il seed casuale costringe l'IA a percorrere alberi neurali diversi ogni volta, evitando la ripetitività
    seed_variazione = random.randint(1, 99999)
    for attempt in range(max_retries):
        try:
            testo = f"{system_prompt}\n\n[Seed variazione stile: {seed_variazione}]\n\nTESTO DEL POST:\n{post_content}" if post_content else system_prompt
            chat = client.chats.create(
                model='gemini-2.5-flash', 
                # Temperatura molto alta (0.95) per costringere a usare parole/strutture sempre diverse
                config=types.GenerateContentConfig(temperature=0.95)
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

def fetch_subreddit_feed(sub, limit=15, max_retries=3):
    url = f"https://www.reddit.com/r/{sub}/new.rss?limit={limit}"
    for attempt in range(max_retries):
        try:
            resp = requests.get(url, headers=HEADERS, timeout=15)
            if resp.status_code == 200:
                return resp.text
            elif resp.status_code == 429:
                wait = 20 * (attempt + 1)
                time.sleep(wait)
                continue
            else:
                return None
        except Exception:
            time.sleep(5)
    return None

def parse_feed(xml_text):
    posts = []
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return posts
    for entry in root.findall("atom:entry", ATOM_NS):
        entry_id_el = entry.find("atom:id", ATOM_NS)
        title_el = entry.find("atom:title", ATOM_NS)
        link_el = entry.find("atom:link", ATOM_NS)
        updated_el = entry.find("atom:updated", ATOM_NS)
        content_el = entry.find("atom:content", ATOM_NS)
        if entry_id_el is None or link_el is None:
            continue
        post_id = entry_id_el.text or ""
        
        clean_id = post_id
        if "comments/" in link_el.attrib.get("href", ""):
            clean_id = link_el.attrib.get("href", "").split("comments/")[1].split("/")[0]

        created_utc = 0
        if updated_el is not None and updated_el.text:
            try:
                dt = datetime.fromisoformat(updated_el.text.replace("Z", "+00:00"))
                created_utc = dt.timestamp()
            except ValueError:
                pass
        posts.append({
            "id": clean_id,
            "titolo": title_el.text if title_el is not None else "",
            "testo": strip_html(content_el.text if content_el is not None else ""),
            "link": link_el.attrib.get("href", ""),
            "created_utc": created_utc,
        })
    return posts

def main():
    print("==================================================")
    print("🚀 AVVIO REDDIT RADAR V2 (Stealth Mode)")
    print("==================================================\n")

    if not GEMINI_API_KEY:
        print("[!] GEMINI_API_KEY mancante.")
        return

    client = genai.Client(api_key=GEMINI_API_KEY)
    conn = setup_db()
    c = conn.cursor()
    risultati = []

    # Mescoliamo i subreddit in modo che non scansioni sempre nello stesso ordine
    random.shuffle(SUBREDDITS)

    for sub in SUBREDDITS:
        print(f"[*] Scansione invisibile su r/{sub}...")
        xml_text = fetch_subreddit_feed(sub)
        if not xml_text:
            time.sleep(random.randint(5, 12))
            continue

        posts = parse_feed(xml_text)
        for post in posts:
            post_id = post["id"]
            if not post_id: continue

            c.execute("SELECT id FROM scanned_posts WHERE id=?", (post_id,))
            if c.fetchone(): continue
            
            c.execute("INSERT INTO scanned_posts (id) VALUES (?)", (post_id,))
            conn.commit()

            created_utc = post["created_utc"]
            if not created_utc: continue

            ore_fa = (time.time() - created_utc) / 3600
            if ore_fa > MAX_ORE or ore_fa < 0: continue

            contesto_troncato = f"TITOLO: {post['titolo']}\nTESTO: {post['testo'][:800]}"
            analisi = generate_with_retry(client, PROMPT_ANALISI, contesto_troncato)

            if "SI" in analisi.upper():
                time.sleep(random.randint(2, 5))
                bozza = generate_with_retry(client, PROMPT_GANCIO, contesto_troncato)

                if bozza == "ERRORE" or not bozza:
                    print(f"    [!] Generazione bozza fallita per {post_id}. Salto.")
                    continue

                c.execute("UPDATE scanned_posts SET bozza=?, status='PENDING' WHERE id=?", (bozza, post_id))
                conn.commit()

                risultati.append(post)
                print(f"    🎯 BERSAGLIO ACQUISITO E MASCHERATO → {post['link']}")

        # Pausa casuale tra un subreddit e l'altro per ingannare i controlli anti-scraping
        time.sleep(random.randint(8, 20))

    conn.close()
    print(f"\n[*] Scansione completata in Stealth. {len(risultati)} esche piazzate nel database.\n")

if __name__ == "__main__":
    main()

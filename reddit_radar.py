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
REDDIT_USER_AGENT = "script:adswap-radar:v2.2 (by /u/Similar_Score2904)"

SUBREDDITS = [
    "androiddev", "gamedev", "IndieGaming", "AppBusiness", "SaaS", 
    "microsaas", "SideProject", "EntrepreneurRideAlong", "indiehackers",
    "growmybusiness", "Startup_Ideas", "playmygame", "IndieDev"
]
MAX_ORE = 24  

# PROMPT BATCH: Cerca post dove possiamo essere genuinamente d'aiuto
PROMPT_ANALISI_BATCH = """
Agisci come un utente esperto di Reddit. Di seguito troverai una lista di post appena pubblicati in subreddit di sviluppo, SaaS e startup.
Seleziona SOLO gli ID dei post dove è possibile dare un consiglio utile, un incoraggiamento genuino o rispondere a una domanda tecnica/di business.
Ignora post di spam, meme o post che non richiedono risposta.
Restituisci SOLO gli "ID" separati da virgola (es: 1wip5m7,1witl8z).
Se NESSUN post è adatto, rispondi testualmente: NESSUNO.
Non aggiungere alcuna spiegazione o testo extra.
"""

PROMPT_GANCIO = """
Sei uno sviluppatore e founder appassionato, stai navigando su Reddit.
Scrivi un commento in inglese per rispondere a questo post.
OBIETTIVO: Ottenere upvote (karma) essendo estremamente utile e genuino.

REGOLE ASSOLUTE:
1. NESSUNA PROMOZIONE. Zero assoluto. Non menzionare MAI app, strumenti, cross-promotion, AdSwap o link.
2. VERO VALORE: Dai un consiglio pratico, un insight o un forte incoraggiamento basato esattamente su ciò che ha scritto l'utente.
3. TONO DA REDDITOR: Molto informale, umano. Usa slang colloquiale (es. "tbh", "imho", "makes sense", "been there", "man"). Non devi assolutamente sembrare un'AI aziendale. Niente liste puntate, niente introduzioni robotiche ("Here is some advice").
4. BREVITÀ: 2-3 frasi massimo. Diretto al punto.
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

def generate_with_retry(client, system_prompt, post_content="", max_retries=5):
    seed_variazione = random.randint(1, 99999)
    for attempt in range(max_retries):
        try:
            testo = f"{system_prompt}\n\n[Seed variazione: {seed_variazione}]\n\n{post_content}" if post_content else system_prompt
            chat = client.chats.create(
                model='gemini-flash-lite-latest',
                config=types.GenerateContentConfig(temperature=0.85)
            )
            response = chat.send_message(testo)
            if response and response.text:
                return response.text.strip()
        except Exception as e:
            error_str = str(e)
            
            # 🛡️ BACKOFF DINAMICO ASSOLUTO
            if "429" in error_str or "RESOURCE_EXHAUSTED" in error_str:
                delay = 30.0 # Default
                
                # Cerca il valore numerico nell'errore (es: "retry in 21.17s" o "'retryDelay': '21s'")
                match_s = re.search(r"retry in ([\d\.]+)s", error_str)
                match_delay = re.search(r"'retryDelay':\s*'([\d\.]+)s'", error_str)
                
                if match_s:
                    delay = float(match_s.group(1)) + 2.0
                elif match_delay:
                    delay = float(match_delay.group(1)) + 2.0
                
                print(f"    [!] Quota API superata! Mi iberno per {delay:.1f} secondi come richiesto da Google...")
                time.sleep(delay)
                continue # Riprova dopo la pausa
            
            if attempt < max_retries - 1:
                time.sleep(5)
                continue
            print(f"    [!] Gemini fallito definitivamente: {e}")
            
    return "ERRORE"

def fetch_subreddit_feed(sub, limit=15, max_retries=3):
    url = f"https://www.reddit.com/r/{sub}/new.rss?limit={limit}"
    for attempt in range(max_retries):
        try:
            resp = requests.get(url, headers=HEADERS, timeout=15)
            if resp.status_code == 200:
                return resp.text
            elif resp.status_code == 429:
                time.sleep(20 * (attempt + 1))
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
    print("🚀 AVVIO REDDIT RADAR V2.2 (Batch Analysis & Backoff)")
    print("==================================================\n")

    if not GEMINI_API_KEY:
        print("[!] GEMINI_API_KEY mancante.")
        return

    client = genai.Client(api_key=GEMINI_API_KEY)
    conn = setup_db()
    c = conn.cursor()
    risultati = []
    
    random.shuffle(SUBREDDITS)

    for sub in SUBREDDITS:
        print(f"[*] Estrazione da r/{sub}...")
        xml_text = fetch_subreddit_feed(sub)
        if not xml_text:
            time.sleep(random.randint(3, 7))
            continue

        posts = parse_feed(xml_text)
        batch_da_analizzare = []

        for post in posts:
            post_id = post["id"]
            if not post_id: continue

            c.execute("SELECT id FROM scanned_posts WHERE id=?", (post_id,))
            if c.fetchone(): continue
            
            created_utc = post["created_utc"]
            if not created_utc: continue

            ore_fa = (time.time() - created_utc) / 3600
            if ore_fa > MAX_ORE or ore_fa < 0: continue

            # Lo segniamo nel DB per non scansionarlo mai più
            c.execute("INSERT INTO scanned_posts (id) VALUES (?)", (post_id,))
            batch_da_analizzare.append(post)
        
        conn.commit()

        if not batch_da_analizzare:
            continue

        # COSTRUZIONE MEGA-TESTO: Inviamo tutti i post in un colpo solo
        testo_batch = "POSTS DA ANALIZZARE:\n\n"
        for p in batch_da_analizzare:
            testo_batch += f"ID: {p['id']}\nTITOLO: {p['titolo']}\nTESTO: {p['testo'][:400]}\n---\n"
        
        # 1 Singola chiamata API per l'intero subreddit!
        analisi_ids = generate_with_retry(client, PROMPT_ANALISI_BATCH, testo_batch)

        if analisi_ids and "NESSUNO" not in analisi_ids.upper() and "ERRORE" not in analisi_ids:
            target_selezionati = [x.strip() for x in analisi_ids.split(",") if x.strip()]
            
            for p in batch_da_analizzare:
                # Generiamo la bozza SOLO per i post che Gemini ha selezionato
                if any(t_id in p['id'] for t_id in target_selezionati):
                    time.sleep(random.randint(2, 4))
                    contesto_singolo = f"TITOLO: {p['titolo']}\nTESTO: {p['testo'][:800]}"
                    bozza = generate_with_retry(client, PROMPT_GANCIO, contesto_singolo)

                    if bozza == "ERRORE" or not bozza:
                        print(f"    [!] Generazione bozza fallita per {p['id']}.")
                        continue

                    c.execute("UPDATE scanned_posts SET bozza=?, status='PENDING' WHERE id=?", (bozza, p['id']))
                    conn.commit()

                    risultati.append(p)
                    print(f"    🎯 BERSAGLIO ACQUISITO E MASCHERATO → {p['link']}")

        time.sleep(random.randint(5, 10))

    conn.close()
    print(f"\n[*] Scansione completata. {len(risultati)} esche piazzate.\n")

if __name__ == "__main__":
    main()

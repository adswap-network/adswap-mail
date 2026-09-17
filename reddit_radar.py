import os
import time
import sqlite3
import functools
import requests
import logging
import warnings
import re
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
REDDIT_USER_AGENT = "script:adswap-radar:v1.0 (by /u/Ok-Skin-9022)"

SUBREDDITS = ["androiddev", "gamedev", "IndieGaming", "AppBusiness", "SaaS"]
MAX_ORE = 20  # scarta post più vecchi di così

PROMPT_ANALISI = """
Agisci come un analista di mercato. Leggi questo post fresco di Reddit.
Il nostro target: sviluppatori indie, creatori di app/giochi che si lamentano di NON avere download, zero utenti, o che i costi di marketing/Ads sono impossibili.
Rispondi SOLO con "SI" se è un target perfetto in cerca di aiuto, oppure "NO".
"""

PROMPT_GANCIO = """
Sei lo sviluppatore che ha creato AdSwap, una rete di cross-promotion gratuita tra app/giochi indie.
Scrivi una bozza di commento Reddit in inglese per questo post.

REGOLE:
1. Rispondi in modo specifico al post.
2. Sii utile: dai un consiglio o fai una domanda.
3. Menziona AdSwap in modo naturale e dichiarato (es. "I actually built a free tool for this called AdSwap...").
4. Tono informale, da sviluppatore a sviluppatore.
5. Massimo 3 frasi, breve e diretto.
6. ASSOLUTAMENTE NESSUN LINK.
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
    # Modificato per supportare la comunicazione con il Cecchino
    c.execute('''CREATE TABLE IF NOT EXISTS scanned_posts (
                 id TEXT PRIMARY KEY, 
                 bozza TEXT, 
                 status TEXT DEFAULT 'SCANNED')''')
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
        
        # Estraiamo l'ID pulito per il link
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
    print("🚀 AVVIO REDDIT RADAR (Salvataggio Bozze in DB)")
    print("==================================================\n")

    if not GEMINI_API_KEY:
        print("[!] GEMINI_API_KEY mancante.")
        return

    client = genai.Client(api_key=GEMINI_API_KEY)
    conn = setup_db()
    c = conn.cursor()
    risultati = []

    for sub in SUBREDDITS:
        print(f"[*] Estrazione da r/{sub}...")
        xml_text = fetch_subreddit_feed(sub)
        if not xml_text:
            time.sleep(8)
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
                time.sleep(2)
                bozza = generate_with_retry(client, PROMPT_GANCIO, contesto_troncato)

                # CONTROLLO DI SICUREZZA: Salta se Gemini fallisce
                if bozza == "ERRORE" or not bozza:
                    print(f"    [!] Generazione bozza fallita per {post_id}. Salto.")
                    continue

                # Salva la bozza come PENDING per il Cecchino
                c.execute("UPDATE scanned_posts SET bozza=?, status='PENDING' WHERE id=?", (bozza, post_id))
                conn.commit()

                risultati.append(post)
                print(f"    🎯 TARGET TROVATO E SALVATO IN CODA → {post['link']}")

        time.sleep(8)

    conn.close()
    print(f"\n[*] Scansione completata. {len(risultati)} bersagli aggiunti in coda.\n")

if __name__ == "__main__":
    main()

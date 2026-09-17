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
REDDIT_USER_AGENT = os.getenv("REDDIT_USER_AGENT", "script:adswap-radar:v1.0 (by /u/CHANGE_ME)")

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
4. Tono informale, da sviluppatore a sviluppatore. Niente frasi fatte tipo "I feel your pain", "Been there".
5. Massimo 3 frasi, breve e diretto.
6. Non inserire link (Reddit spesso shadowbanna i primi commenti con link da account nuovi): lascia che sia l'utente a chiedere info o cercare "AdSwap" da solo.
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


def fetch_subreddit_feed(sub, limit=15, max_retries=3):
    """Legge il feed Atom pubblico di Reddit (i .json non autenticati rispondono 403 dal 30/05/2026)."""
    url = f"https://www.reddit.com/r/{sub}/new.rss?limit={limit}"
    for attempt in range(max_retries):
        try:
            resp = requests.get(url, headers=HEADERS, timeout=15)
            if resp.status_code == 200:
                return resp.text
            elif resp.status_code == 429:
                wait = 20 * (attempt + 1)
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


def parse_feed(xml_text):
    """Estrae id, titolo, testo, link e data da un feed Atom di Reddit."""
    posts = []
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as e:
        print(f"    [!] Feed non valido: {e}")
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
        titolo = title_el.text if title_el is not None else ""
        link = link_el.attrib.get("href", "")
        testo = strip_html(content_el.text if content_el is not None else "")

        created_utc = 0
        if updated_el is not None and updated_el.text:
            try:
                dt = datetime.fromisoformat(updated_el.text.replace("Z", "+00:00"))
                created_utc = dt.timestamp()
            except ValueError:
                pass

        posts.append({
            "id": post_id,
            "titolo": titolo,
            "testo": testo,
            "link": link,
            "created_utc": created_utc,
        })
    return posts


def main():
    print("==================================================")
    print("🚀 AVVIO REDDIT RADAR (JSON diretto, no auto-posting)")
    print("==================================================\n")

    if not GEMINI_API_KEY:
        print("[!] GEMINI_API_KEY mancante.")
        return
    if "CHANGE_ME" in REDDIT_USER_AGENT:
        print("[!] Imposta la variabile d'ambiente REDDIT_USER_AGENT con il tuo username reddit reale, es:")
        print('    REDDIT_USER_AGENT="script:adswap-radar:v1.0 (by /u/tuo_username)"')
        return

    client = genai.Client(api_key=GEMINI_API_KEY)
    conn = setup_db()
    c = conn.cursor()
    risultati = []

    for sub in SUBREDDITS:
        print(f"[*] Estrazione da r/{sub}...")
        xml_text = fetch_subreddit_feed(sub)

        if not xml_text:
            print("    [-] Nessun dato, salto subreddit.")
            time.sleep(8)
            continue

        posts = parse_feed(xml_text)
        if not posts:
            print("    [-] Nessun post restituito.")
            continue

        for post in posts:
            post_id = post["id"]
            if not post_id:
                continue

            c.execute("SELECT id FROM scanned_posts WHERE id=?", (post_id,))
            if c.fetchone():
                continue
            c.execute("INSERT INTO scanned_posts (id) VALUES (?)", (post_id,))
            conn.commit()

            created_utc = post["created_utc"]
            if not created_utc:
                continue  # data non leggibile, saltiamo per sicurezza

            ore_fa = (time.time() - created_utc) / 3600
            if ore_fa > MAX_ORE or ore_fa < 0:
                continue

            titolo = post["titolo"]
            testo = post["testo"]
            link_assoluto = post["link"]
            contesto_troncato = f"TITOLO: {titolo}\nTESTO: {testo[:800]}"

            print(f"    [>] Post fresco ({ore_fa:.1f}h fa): {titolo[:60]}... Analisi...")
            analisi = generate_with_retry(client, PROMPT_ANALISI, contesto_troncato)

            if "SI" in analisi.upper():
                time.sleep(2)
                bozza = generate_with_retry(client, PROMPT_GANCIO, contesto_troncato)

                risultati.append({
                    "titolo": titolo,
                    "link": link_assoluto,
                    "ore_fa": round(ore_fa, 1),
                    "bozza": bozza
                })

                print(f"    🎯 TARGET TROVATO → {link_assoluto}")

        time.sleep(8)  # ~10 richieste/min è il limite anonimo di Reddit per le RSS: restiamo larghi

    conn.close()

    print("\n" + "=" * 60)
    print(f"[*] Scansione completata. {len(risultati)} bersagli trovati.\n")

    if not risultati:
        with open("latest_digest.txt", "w", encoding="utf-8") as f:
            f.write(f"Aggiornato il: {datetime.now().strftime('%Y-%m-%d %H:%M')}\n\n")
            f.write("Nessun post rilevante trovato nell'ultima scansione.\n")
        print("Nessun post in target trovato in questo giro.")
        return

    for i, r in enumerate(risultati, 1):
        print(f"--- BERSAGLIO {i} ({r['ore_fa']}h fa) ---")
        print(f"📌 {r['titolo']}")
        print(f"🔗 {r['link']}")
        print(f"🤖 Bozza commento:\n> {r['bozza']}\n")

    # Digest sovrascritto ad ogni run: comodo se lo pianifichi come cron/scheduled task
    with open("latest_digest.txt", "w", encoding="utf-8") as f:
        f.write(f"Aggiornato il: {datetime.now().strftime('%Y-%m-%d %H:%M')}\n\n")
        for i, r in enumerate(risultati, 1):
            f.write(f"--- BERSAGLIO {i} ({r['ore_fa']}h fa) ---\n")
            f.write(f"Titolo: {r['titolo']}\nLink: {r['link']}\n\nBozza di risposta:\n{r['bozza']}\n\n")
            f.write("=" * 50 + "\n\n")
    print("[*] Digest aggiornato in 'latest_digest.txt'")


if __name__ == "__main__":
    main()

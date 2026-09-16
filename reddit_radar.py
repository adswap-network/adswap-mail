import os
import time
import sqlite3
import functools
import requests
import feedparser
import re
from google import genai

# Forza la stampa immediata nei log di GitHub Actions
print = functools.partial(print, flush=True)

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

SUBREDDITS = ["androiddev", "gamedev", "IndieGaming", "AppBusiness", "marketing", "game_development", "startups"]

# PROMPT 1: L'Analista.
PROMPT_ANALISI = """
Sei un analista di mercato. Devi leggere il titolo e il contenuto di un post di Reddit.
Il nostro target sono: sviluppatori indie, creatori di app o giochi che si lamentano di avere pochi download, zero visibilità, oppure costi di marketing/Google Ads troppo alti.
Se il post parla di problemi di codice, bug, o argomenti generici, NON è il nostro target.
Rispondi SOLO con la parola "SI" se è un target perfetto, oppure "NO" in tutti gli altri casi. Non aggiungere altre parole.
"""

# PROMPT 2: Il Copywriter.
PROMPT_GANCIO = """
Sei Matteo, sviluppatore mobile indie. Rispondi in inglese (informale, stile Reddit) a questo utente che fatica a trovare download o spendere in Ads.
Mostra empatia (ci sei passato anche tu con le tue app).
Chiedigli come sta cercando di farsi notare al momento.
REGOLA D'ORO: NON MENZIONARE AdSwap, non inserire link. Sii solo un utente umano che chiacchiera e offre supporto morale. Massimo 2-3 frasi brevi.
"""

def setup_db():
    conn = sqlite3.connect("reddit_radar.db")
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS scanned_posts (id TEXT PRIMARY KEY)''')
    conn.commit()
    return conn

def valuta_post(client, titolo, testo):
    contesto = f"TITOLO: {titolo}\nTESTO: {testo[:1000]}"
    try:
        # AGGIORNATO AL NUOVO MODELLO GEMINI 3.6 COME RICHIESTO DAI LOG
        response = client.models.generate_content(
            model='gemini-3.6-flash',
            contents=f"{PROMPT_ANALISI}\n\nPOST:\n{contesto}"
        )
        risultato = response.text.strip().upper()
        return "SI" in risultato
    except Exception as e:
        print(f"      [!] Errore Gemini Analisi: {e}")
        return False

def genera_gancio(client, titolo, testo):
    contesto = f"TITOLO: {titolo}\nTESTO: {testo[:1000]}"
    try:
        response = client.models.generate_content(
            model='gemini-3.6-flash',
            contents=f"{PROMPT_GANCIO}\n\nPOST DELL'UTENTE:\n{contesto}"
        )
        return response.text.strip()
    except Exception as e:
        return f"[!] Errore generazione: {e}"

def main():
    print("==================================================")
    print("🚀 AVVIO REDDIT RADAR AI (Motore Gemini 3.6-Flash)")
    print("==================================================\n")
    
    if not GEMINI_API_KEY:
        print("[!] GEMINI_API_KEY non trovata. Interruzione.")
        return

    client = genai.Client(api_key=GEMINI_API_KEY)
    conn = setup_db()
    c = conn.cursor()
    trovati = 0

    # USER-AGENT AGGRESSIVO: Fingiamo di essere un vero browser Chrome su Windows
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/114.0.0.0 Safari/537.36"
    }

    for sub in SUBREDDITS:
        print(f"[*] Estrazione post da r/{sub} tramite RSS...")
        url = f"https://www.reddit.com/r/{sub}/new.rss"
        
        try:
            # Bypass del blocco usando requests invece del fetcher nativo di feedparser
            req = requests.get(url, headers=headers, timeout=15)
            
            if req.status_code == 403 or req.status_code == 429:
                print(f"    [!] Reddit ha bloccato r/{sub} (Status: {req.status_code}). Salto...")
                time.sleep(3)
                continue
            
            feed = feedparser.parse(req.content)
            
            if not feed.entries:
                print(f"    [-] Nessun post trovato per r/{sub}.")
                time.sleep(2)
                continue

            for post in feed.entries[:10]: # Legge i 10 post più recenti
                post_id = post.id
                titolo = post.title
                
                # Pulizia dell'HTML
                testo_sporco = post.summary
                testo_pulito = re.sub('<[^<]+?>', '', testo_sporco)
                
                c.execute("SELECT id FROM scanned_posts WHERE id=?", (post_id,))
                if c.fetchone():
                    continue
                    
                c.execute("INSERT INTO scanned_posts (id) VALUES (?)", (post_id,))
                conn.commit()

                # Gemini valuta se è il target
                is_target = valuta_post(client, titolo, testo_pulito)
                
                if is_target:
                    print("\n" + "="*60)
                    print(f"🎯 BERSAGLIO CONFERMATO DALL'IA SU r/{sub}!")
                    print(f"🔗 Link: {post.link}")
                    print(f"📌 Titolo: {titolo}")
                    
                    bozza = genera_gancio(client, titolo, testo_pulito)
                    
                    print(f"\n🤖 RISPOSTA PRONTA DA INCOLLARE:\n> {bozza}\n")
                    print("="*60 + "\n")
                    trovati += 1
                    
        except Exception as e:
            print(f"    [!] Errore generico su r/{sub}: {e}")
            
        time.sleep(3) # Pausa fissa tra un subreddit e l'altro

    print(f"\n[*] Scansione terminata. Generati {trovati} ganci strategici.")
    conn.close()

if __name__ == "__main__":
    main()

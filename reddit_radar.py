import requests
import json
import sqlite3
import time
import os
import functools
import google.generativeai as genai

# Forza la stampa immediata nei log di GitHub Actions
print = functools.partial(print, flush=True)

# --- CONFIGURAZIONE ---
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

SUBREDDITS = ["androiddev", "gamedev", "IndieGaming", "AppBusiness", "marketing", "game_development"]
KEYWORDS = ["google ads", "marketing", "user acquisition", "too expensive", "no downloads", "grow my app", "ua costs", "zero downloads", "how to promote"]

# Prompt ultra-restrittivo per la Fase 1 (Solo Gancio)
PROMPT_FASE_1 = """
Sei Matteo, uno sviluppatore mobile indie su Reddit. Stai leggendo un post di un altro sviluppatore che ha problemi con i costi di marketing o l'acquisizione utenti.
Scrivi un commento breve, empatico e genuino in inglese (max 2-3 frasi).
Mostra comprensione, digli che ci sei passato anche tu con le tue app e hai bruciato soldi in ads a vuoto.
Chiedigli che strategie alternative sta provando ora per stimolare una risposta.
REGOLA ASSOLUTA: NON menzionare MAI AdSwap, non inserire alcun link, non vendere nulla. Devi sembrare solo un utente che vuole chiacchierare. Scrivi in modo molto informale, come se parlassi a un amico su discord.
"""

def setup_db():
    conn = sqlite3.connect("reddit_radar.db")
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS scanned_posts (id TEXT PRIMARY KEY, timestamp DATETIME DEFAULT CURRENT_TIMESTAMP)''')
    conn.commit()
    return conn

def genera_risposta(prompt, titolo, testo):
    if not GEMINI_API_KEY:
        return "ERRORE: GEMINI_API_KEY mancante."
    
    genai.configure(api_key=GEMINI_API_KEY)
    model = genai.GenerativeModel('gemini-1.5-flash')
    
    contesto = f"TITOLO: {titolo}\n\nTESTO: {testo}"
    response = model.generate_content(f"{prompt}\n\nPOST DELL'UTENTE DA LEGGERE:\n{contesto}")
    return response.text.strip()

def main():
    print("==================================================")
    print("🚀 AVVIO REDDIT RADAR (Modalità JSON Sola Lettura)")
    print("==================================================\n")
    
    conn = setup_db()
    c = conn.cursor()
    
    # Header essenziale per non farsi bloccare da Reddit (No 429 Too Many Requests)
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 AdSwapRadar/1.0"
    }

    trovati = 0

    for sub in SUBREDDITS:
        print(f"[*] Scansione in corso su r/{sub}...")
        url = f"https://www.reddit.com/r/{sub}/new.json?limit=15"
        
        try:
            response = requests.get(url, headers=headers, timeout=10)
            if response.status_code != 200:
                print(f"    [!] Reddit ha bloccato la richiesta su r/{sub} (Status: {response.status_code})")
                time.sleep(2)
                continue
                
            data = response.json()
            posts = data.get('data', {}).get('children', [])
            
            for child in posts:
                post = child['data']
                post_id = post.get('id')
                titolo = post.get('title', '')
                testo = post.get('selftext', '')
                url_post = f"https://www.reddit.com{post.get('permalink')}"
                
                # Verifica se lo abbiamo già analizzato
                c.execute("SELECT id FROM scanned_posts WHERE id=?", (post_id,))
                if c.fetchone():
                    continue
                
                # Filtra per keyword
                testo_completo = (titolo + " " + testo).lower()
                if any(kw in testo_completo for kw in KEYWORDS):
                    print("\n" + "="*50)
                    print(f"🎯 BERSAGLIO TROVATO SU r/{sub}!")
                    print(f"🔗 Link: {url_post}")
                    print(f"📌 Titolo: {titolo}")
                    print("="*50)
                    
                    print("[*] Generazione risposta con Gemini in corso...")
                    bozza_gemini = genera_risposta(PROMPT_FASE_1, titolo, testo)
                    
                    print(f"\n🤖 GEMINI PROPONE QUESTO COMMENTO:\n")
                    print(f"> {bozza_gemini}\n")
                    print("="*50 + "\n")
                    
                    # Salva nel DB per non riprocessarlo al prossimo giro
                    c.execute("INSERT INTO scanned_posts (id) VALUES (?)", (post_id,))
                    conn.commit()
                    trovati += 1
                    
        except Exception as e:
            print(f"    [!] Errore durante l'analisi di r/{sub}: {e}")
            
        # Pausa per rispettare i limiti di Reddit ed evitare ban IP
        time.sleep(3)

    if trovati == 0:
        print("\nNessuna nuova discussione rilevante trovata in questa sessione.")
    else:
        print(f"\nSessione conclusa. Trovati {trovati} potenziali lead.")
        
    conn.close()

if __name__ == "__main__":
    main()

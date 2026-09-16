import os
import time
import sqlite3
import functools
import feedparser
from google import genai

# Forza la stampa immediata nei log di GitHub Actions
print = functools.partial(print, flush=True)

# Imposta un finto browser per non farsi bloccare da Reddit RSS
feedparser.USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 AdSwapRadar/2.0"

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

SUBREDDITS = ["androiddev", "gamedev", "IndieGaming", "AppBusiness", "marketing", "game_development", "startups"]

# PROMPT 1: L'Analista. Decide se il post è un nostro target.
PROMPT_ANALISI = """
Sei un analista di mercato. Devi leggere il titolo e il contenuto di un post di Reddit.
Il nostro target sono: sviluppatori indie, creatori di app o giochi che si lamentano di avere pochi download, zero visibilità, oppure costi di marketing/Google Ads troppo alti.
Se il post parla di problemi di codice, bug, o argomenti generici, NON è il nostro target.
Rispondi SOLO con la parola "SI" se è un target perfetto, oppure "NO" in tutti gli altri casi. Non aggiungere altre parole.
"""

# PROMPT 2: Il Copywriter. Scrive il gancio se il post è in target.
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
    """Chiede a Gemini se il post è rilevante."""
    contesto = f"TITOLO: {titolo}\nTESTO: {testo[:1000]}" # Limita a 1000 char per non sprecare token
    try:
        response = client.models.generate_content(
            model='gemini-2.5-flash',
            contents=f"{PROMPT_ANALISI}\n\nPOST:\n{contesto}"
        )
        risultato = response.text.strip().upper()
        return "SI" in risultato
    except Exception as e:
        print(f"      [!] Errore Gemini Analisi: {e}")
        return False

def genera_gancio(client, titolo, testo):
    """Chiede a Gemini di scrivere il commento empatico."""
    contesto = f"TITOLO: {titolo}\nTESTO: {testo[:1000]}"
    try:
        response = client.models.generate_content(
            model='gemini-2.5-flash',
            contents=f"{PROMPT_GANCIO}\n\nPOST DELL'UTENTE:\n{contesto}"
        )
        return response.text.strip()
    except Exception as e:
        return f"[!] Errore generazione: {e}"

def main():
    print("==================================================")
    print("🚀 AVVIO REDDIT RADAR AI (Motore Gemini 2.5)")
    print("==================================================\n")
    
    if not GEMINI_API_KEY:
        print("[!] GEMINI_API_KEY non trovata. Interruzione.")
        return

    # Inizializza il nuovo client Google GenAI
    client = genai.Client(api_key=GEMINI_API_KEY)
    
    conn = setup_db()
    c = conn.cursor()
    trovati = 0

    for sub in SUBREDDITS:
        print(f"[*] Estrazione post da r/{sub} tramite RSS...")
        url = f"https://www.reddit.com/r/{sub}/new.rss"
        
        feed = feedparser.parse(url)
        
        if getattr(feed, 'status', 0) == 403:
            print(f"    [!] Accesso 403 Negato per r/{sub}. (Server IP Bloccato)")
            time.sleep(2)
            continue
            
        if not feed.entries:
            print(f"    [-] Nessun post trovato o feed bloccato per r/{sub}.")
            time.sleep(2)
            continue

        for post in feed.entries[:10]: # Analizza gli ultimi 10 post
            post_id = post.id
            titolo = post.title
            
            # Pulisce i tag HTML che Reddit mette nell'RSS
            testo_sporco = post.summary
            import re
            testo_pulito = re.sub('<[^<]+?>', '', testo_sporco)
            
            # Salta se già analizzato
            c.execute("SELECT id FROM scanned_posts WHERE id=?", (post_id,))
            if c.fetchone():
                continue
                
            # Salva subito per non riprocessarlo (anche se non è in target)
            c.execute("INSERT INTO scanned_posts (id) VALUES (?)", (post_id,))
            conn.commit()

            # 1. Chiediamo a Gemini se è un target valido
            is_target = valuta_post(client, titolo, testo_pulito)
            
            if is_target:
                link = post.link
                print("\n" + "="*60)
                print(f"🎯 BERSAGLIO CONFERMATO DALL'IA SU r/{sub}!")
                print(f"🔗 Link: {link}")
                print(f"📌 Titolo: {titolo}")
                
                print("[*] Generazione della risposta umana in corso...")
                bozza = genera_gancio(client, titolo, testo_pulito)
                
                print(f"\n🤖 RISPOSTA PRONTA DA INCOLLARE:\n")
                print(f"> {bozza}\n")
                print("="*60 + "\n")
                trovati += 1
                
        time.sleep(2) # Pausa tra un subreddit e l'altro

    print(f"\n[*] Scansione terminata. Generati {trovati} ganci strategici.")
    conn.close()

if __name__ == "__main__":
    main()

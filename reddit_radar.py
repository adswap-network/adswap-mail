import os
import time
import sqlite3
import functools
import random
import logging
import warnings
import re
from ddgs import DDGS
from google import genai
from google.genai import types

# Silenzia completamente i log di sistema per un terminale pulito
warnings.filterwarnings("ignore")
logging.getLogger("google").setLevel(logging.ERROR)
os.environ["GRPC_VERBOSITY"] = "ERROR"
os.environ["GLOG_minloglevel"] = "2"

print = functools.partial(print, flush=True)

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

PROMPT_GENERAZIONE_QUERY = """
Sei un SEO esperto. Genera 4 query BREVISSIME per trovare post su Reddit di sviluppatori con zero download o marketing troppo costoso.
REGOLA 1: Inizia sempre con 'site:reddit.com '
REGOLA 2: Usa MASSIMO 3 o 4 parole chiave. Sii iper-sintetico. NIENTE virgolette.
Esempio 1: site:reddit.com indie game zero downloads
Esempio 2: site:reddit.com app marketing expensive
Restituisci SOLO le 4 stringhe, una per riga. Nessun testo aggiuntivo.
"""

PROMPT_ANALISI = """
Agisci come un analista di mercato. Leggi il titolo e il contenuto di questo post di Reddit.
Il nostro target: sviluppatori indie, creatori di app/giochi che si lamentano di pochi download, zero visibilità o costi Google Ads troppo alti.
Se il post parla di problemi di codice, bug, cerco lavoro o argomenti non legati al marketing/downloads, NON è il nostro target.
Rispondi SOLO con "SI" se è un target perfetto, oppure "NO". Non aggiungere altro.
"""

PROMPT_GANCIO = """
Sei uno sviluppatore mobile indie. Rispondi in inglese (informale, stile Reddit) a questo utente che fatica a trovare download o spendere in Ads.
Mostra empatia (ci sei passato anche tu).
Chiedigli come sta cercando di farsi notare al momento o se ha provato alternative.
REGOLA D'ORO: NON MENZIONARE MAI AdSwap, non inserire alcun link, non vendere nulla. Sii solo un utente che chiacchiera. Massimo 2-3 frasi brevi.
"""

def setup_db():
    conn = sqlite3.connect("reddit_radar.db")
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS scanned_posts (id TEXT PRIMARY KEY)''')
    conn.commit()
    return conn

def seleziona_modello_leggero(client):
    """
    Interroga segretamente le API di Google per trovare il modello più veloce e con
    i rate limits migliori associato a questa specifica API Key, bypassando i modelli intasati.
    """
    print("[*] Ricerca del modello AI più leggero e stabile consentito dalla tua API Key...")
    try:
        modelli_disponibili = [m.name for m in client.models.list() if "gemini" in m.name]
        
        # 1. Cerchiamo modelli High-Speed (8b, lite, nano)
        for m in modelli_disponibili:
            if "8b" in m.lower() or "lite" in m.lower() or "nano" in m.lower():
                print(f"    [✓] Trovato modello Ultra-Leggero (Anti-Blocco): {m}")
                return m
                
        # 2. Se non esistono, prendiamo un flash meno intasato
        for m in modelli_disponibili:
            if "flash" in m.lower() and "3.6" not in m.lower():
                print(f"    [✓] Trovato modello Flash alternativo: {m}")
                return m
                
        print("    [!] Nessuna alternativa trovata. Ripiego su gemini-3.6-flash.")
        return 'gemini-3.6-flash'
    except Exception as e:
        print(f"    [!] Lettura modelli fallita ({e}). Uso gemini-3.6-flash di default.")
        return 'gemini-3.6-flash'

def generate_with_retry(client, modello, system_prompt, post_content="", max_retries=4, initial_delay=8):
    """Motore corazzato che usa l'API Chat raccomandata per evitare i warning AFC."""
    delay = initial_delay
    for attempt in range(max_retries):
        try:
            testo_unito = f"{system_prompt}\n\nTESTO:\n{post_content}" if post_content else system_prompt
            
            # Usando .chats.create aggiriamo per sempre l'errore del warning "AFC in Models.generate_content"
            chat = client.chats.create(
                model=modello,
                config=types.GenerateContentConfig(temperature=0.7)
            )
            response = chat.send_message(testo_unito)
            
            if not response or not response.text:
                raise ValueError("Risposta vuota")
            return response.text.strip()
            
        except Exception as e:
            err_msg = str(e).upper()
            if any(x in err_msg for x in ["503", "429", "404", "UNAVAILABLE", "EXHAUSTED", "INTERNAL"]):
                if attempt < max_retries - 1:
                    print(f"      🕒 API ({modello}) occupata. Riprovo in {delay}s...")
                    time.sleep(delay)
                    delay *= 2
                    continue
            print(f"      [!] Errore irreversibile: {e}")
            return "ERRORE"
    return "ERRORE"

def main():
    print("==================================================")
    print("🧠 AVVIO REDDIT RADAR AI - AUTO-DISCOVERY MODELLO")
    print("==================================================\n")
    
    if not GEMINI_API_KEY:
        print("[!] GEMINI_API_KEY non trovata. Interruzione.")
        return

    client = genai.Client(api_key=GEMINI_API_KEY)
    
    # Rilevamento dinamico del modello perfetto
    modello_scelto = seleziona_modello_leggero(client)
    
    conn = setup_db()
    c = conn.cursor()
    trovati = 0

    print("\n[*] Chiedo a Gemini di inventare le strategie di ricerca...")
    query_dinamiche_raw = generate_with_retry(client, modello_scelto, PROMPT_GENERAZIONE_QUERY)
    
    if query_dinamiche_raw == "ERRORE":
        print("[!] Impossibile generare query. Chiusura.")
        return

    querie_globali = [q.strip() for q in query_dinamiche_raw.split('\n') if 'site:reddit.com' in q]
    
    if not querie_globali:
        print("[!] Gemini non ha formattato bene. Uso query di backup molto ampie.")
        querie_globali = [
            'site:reddit.com app marketing expensive',
            'site:reddit.com indie game zero downloads',
            'site:reddit.com app store optimization failed'
        ]

    ddgs = DDGS()

    for query in querie_globali:
        print(f"\n[*] Caccia Stealth in corso: {query}")
        
        try:
            # Ricerca di post recenti (ultimo mese) per garantire risultati
            risultati = list(ddgs.text(query, max_results=6, timelimit='m'))
            
            if not risultati:
                print(f"    [-] Rete vuota per questa query.")
                time.sleep(3)
                continue
                
            for post in risultati:
                titolo = post.get('title', '')
                testo_snippet = post.get('body', '')
                link = post.get('href', '')
                
                post_id = link.split('comments/')[1].split('/')[0] if 'comments/' in link else link
                
                c.execute("SELECT id FROM scanned_posts WHERE id=?", (post_id,))
                if c.fetchone():
                    continue
                    
                c.execute("INSERT INTO scanned_posts (id) VALUES (?)", (post_id,))
                conn.commit()

                contesto_troncato = f"TITOLO: {titolo}\nTESTO SINTETICO: {testo_snippet}"
                
                risultato_analisi = generate_with_retry(client, modello_scelto, PROMPT_ANALISI, contesto_troncato)
                
                if "SI" in risultato_analisi.upper():
                    print("\n" + "="*60)
                    print(f"🎯 BERSAGLIO INTERCETTATO:")
                    print(f"🔗 Link: {link}")
                    print(f"📌 Titolo: {titolo}")
                    
                    time.sleep(4)
                    
                    bozza = generate_with_retry(client, modello_scelto, PROMPT_GANCIO, contesto_troncato)
                    
                    print(f"\n🤖 IL GANCIO:\n> {bozza}\n")
                    print("="*60 + "\n")
                    trovati += 1
                    
                time.sleep(3) 
                
        except Exception as e:
            print(f"    [!] Errore su '{query}': {e}")
            
        time.sleep(random.randint(5, 8))

    print(f"\n[*] Scansione terminata a fondo. Generati {trovati} ganci.")
    conn.close()
    os._exit(0)

if __name__ == "__main__":
    main()

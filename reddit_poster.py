import os
import sqlite3
import time
import functools
from playwright.sync_api import sync_playwright

print = functools.partial(print, flush=True)

COOKIE_VALUE = os.getenv("REDDIT_SESSION_COOKIE")

def get_db():
    conn = sqlite3.connect("reddit_radar.db")
    return conn

def main():
    print("==================================================")
    print("🔫 AVVIO CECCHINO REDDIT (PLAYWRIGHT STEALTH)")
    print("==================================================\n")
    
    if not COOKIE_VALUE:
        print("[!] Errore: REDDIT_SESSION_COOKIE mancante nei Secrets.")
        return

    conn = get_db()
    c = conn.cursor()
    
    # Pesca UNA SOLA bozza in sospeso
    c.execute("SELECT id, bozza FROM scanned_posts WHERE status='PENDING' LIMIT 1")
    record = c.fetchone()
    
    if not record:
        print("[*] Nessuna bozza in attesa. Il cecchino torna a dormire.")
        conn.close()
        return
        
    post_id, bozza = record
    post_url = f"https://www.reddit.com/comments/{post_id}"
    print(f"[*] Obiettivo acquisito: {post_url}")
    print(f"[*] Testo da pubblicare:\n> {bozza}\n")

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        )
        
        # Inietta il cookie di sessione
        context.add_cookies([{
            "name": "reddit_session",
            "value": COOKIE_VALUE,
            "domain": ".reddit.com",
            "path": "/"
        }])
        
        page = context.new_page()
        
        try:
            print("    [>] Caricamento pagina Reddit...")
            page.goto(post_url, wait_until="domcontentloaded", timeout=30000)
            time.sleep(5) 
            
            print("    [>] Ricerca del box di testo...")
            # L'interfaccia moderna di Reddit usa shreddit-composer
            composer = page.locator('shreddit-composer').first
            composer.click(timeout=10000)
            time.sleep(2)
            
            print("    [>] Digitazione (simulazione umana)...")
            page.keyboard.type(bozza, delay=40) 
            time.sleep(3)
            
            print("    [>] Clic su 'Comment'...")
            composer.locator('button[type="submit"], button[slot="submitButton"]').first.click()
            time.sleep(5) # Attende che la richiesta POST parta
            
            # Segna come pubblicato
            c.execute("UPDATE scanned_posts SET status='POSTED' WHERE id=?", (post_id,))
            conn.commit()
            print("    [✓] Commento pubblicato con successo!")
            
        except Exception as e:
            print(f"    [!] Errore durante l'interazione Playwright: {e}")
            # Se fallisce, rimane 'PENDING' e ci riproverà al prossimo giro!
            
        finally:
            browser.close()
            
    conn.close()

if __name__ == "__main__":
    main()

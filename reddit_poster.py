import os
import sqlite3
import time
import functools
from playwright.sync_api import sync_playwright

print = functools.partial(print, flush=True)

COOKIE_VALUE = os.getenv("REDDIT_SESSION_COOKIE")

def get_db():
    return sqlite3.connect("reddit_radar.db")

def main():
    print("==================================================")
    print("🔫 AVVIO CECCHINO REDDIT (APPROCCIO SEMPLICE 2.8)")
    print("==================================================\n")
    
    if not COOKIE_VALUE:
        print("[!] Errore: REDDIT_SESSION_COOKIE mancante nei Secrets.")
        return

    conn = get_db()
    c = conn.cursor()
    
    c.execute("SELECT id, bozza FROM scanned_posts WHERE status='PENDING' LIMIT 1")
    record = c.fetchone()
    
    if not record:
        print("[*] Nessuna bozza in attesa. Il cecchino torna a dormire.")
        conn.close()
        return
        
    post_id, bozza = record
    post_url = f"https://www.reddit.com/comments/{post_id}"
    print(f"[*] Obiettivo acquisito: {post_url}")

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            viewport={"width": 1920, "height": 1080},
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        )
        
        context.add_cookies([{
            "name": "reddit_session",
            "value": COOKIE_VALUE,
            "domain": ".reddit.com",
            "path": "/"
        }])
        
        page = context.new_page()
        
        try:
            print("    [>] Caricamento pagina...")
            page.goto(post_url, wait_until="domcontentloaded", timeout=45000)
            time.sleep(8) # Attendiamo che React carichi tutta la pagina
            
            # 1. Clicchiamo ESATTAMENTE la casella di testo usando l'attributo del tuo HTML
            print("    [>] Clicco su 'Join the conversation'...")
            editor = page.locator('div[aria-placeholder="Join the conversation"], div[contenteditable="true"]').first
            editor.scroll_into_view_if_needed()
            editor.click(force=True, timeout=10000)
            time.sleep(2)
            
            # 2. Inseriamo il testo
            print("    [>] Inserisco il testo...")
            editor.type(bozza, delay=15)
            time.sleep(2)
            
            # 3. Clicchiamo ESATTAMENTE il bottone 'Comment' tramite il suo ID univoco
            print("    [>] Clicco il pulsante Comment...")
            submit_btn = page.locator('button#comment-composer-submit-button, shreddit-composer button[type="submit"]').first
            submit_btn.click(force=True, timeout=10000)
            time.sleep(6) # Tempo per permettere al server di salvare il commento
            
            # Controllo visivo finale
            page.screenshot(path="conferma_pubblicazione.png")
            print("    [i] 📸 Screenshot salvato (conferma_pubblicazione.png).")
            
            c.execute("UPDATE scanned_posts SET status='POSTED' WHERE id=?", (post_id,))
            conn.commit()
            print("    [✓] Commento pubblicato con successo!")
            
        except Exception as e:
            print(f"    [!] Errore: {e}")
            try:
                page.screenshot(path="errore_reddit.png")
                print("    [i] 📸 Screenshot errore salvato.")
            except:
                pass
            
        finally:
            browser.close()
            
    conn.close()

if __name__ == "__main__":
    main()

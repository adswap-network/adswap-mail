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
    print("🔫 AVVIO CECCHINO REDDIT (MOBILE EMULATOR 5.1)")
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
        # Carichiamo il profilo iPhone originale senza duplicare l'User Agent
        iphone = p.devices['iPhone 13']
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(**iphone)
        
        context.add_cookies([{
            "name": "reddit_session",
            "value": COOKIE_VALUE,
            "domain": ".reddit.com",
            "path": "/"
        }])
        
        page = context.new_page()
        
        try:
            print("    [>] Caricamento pagina Mobile...")
            page.goto(post_url, wait_until="networkidle", timeout=60000)
            time.sleep(5) 
            
            page.screenshot(path="debug_mobile_view.png")

            print("    [>] Ricerca dell'editor di commenti...")
            # Copriamo tutte le varianti mobile di Reddit (textarea classica o div contenteditable)
            editor_locator = page.locator('div[contenteditable="true"], textarea').first
            
            editor_locator.scroll_into_view_if_needed(timeout=10000)
            time.sleep(1)
            
            print("    [>] Click e focus...")
            editor_locator.click(force=True)
            time.sleep(1)

            print("    [>] Scrittura del commento...")
            # Usiamo la tastiera per simulare perfettamente i tap su schermo
            page.keyboard.type(bozza, delay=15)
            time.sleep(2)
            
            print("    [>] Pressione tasto Reply...")
            # Aggancio ampio per coprire i bottoni della UI mobile
            submit_btn = page.locator('button:has-text("Reply"), button:has-text("Comment"), button:has-text("Add a comment"), button[type="submit"]').first
            submit_btn.click(force=True)
            
            print("    [>] Attesa server...")
            time.sleep(6) 
            
            page.screenshot(path="conferma_pubblicazione.png")
            print("    [i] 📸 Screenshot di conferma salvato negli Artifacts!")
            
            c.execute("UPDATE scanned_posts SET status='POSTED' WHERE id=?", (post_id,))
            conn.commit()
            print("    [✓] Commento pubblicato con successo!")
            
        except Exception as e:
            print(f"    [!] Errore critico in emulazione Mobile: {e}")
            try:
                page.screenshot(path="errore_reddit.png")
            except:
                pass
                
            c.execute("UPDATE scanned_posts SET status='FAILED' WHERE id=?", (post_id,))
            conn.commit()
            
        finally:
            browser.close()
            
    conn.close()

if __name__ == "__main__":
    main()

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
    print("🔫 AVVIO CECCHINO REDDIT (PLAYWRIGHT STEALTH 2.0)")
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
        
        # 1. FIX: Impostiamo uno schermo Desktop Full HD per evitare che la UI collassi
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
            print("    [>] Caricamento pagina Reddit...")
            page.goto(post_url, wait_until="domcontentloaded", timeout=45000)
            time.sleep(6) 
            
            print("    [>] Ricerca del box di testo...")
            composer = page.locator('shreddit-composer').first
            
            # 2. FIX: Scorriamo giù la pagina fino a inquadrare il box (scroll_into_view)
            composer.scroll_into_view_if_needed()
            time.sleep(2)
            
            # 3. FIX: Clicchiamo con force=True per bypassare qualsiasi banner invisibile o pop-up
            print("    [>] Forzatura del click sul composer...")
            composer.click(force=True, timeout=5000)
            time.sleep(2)
            
            # 4. FIX: Clicchiamo esattamente dentro l'editor di testo vero e proprio
            editor = page.locator('div[contenteditable="true"]').first
            if editor.count() > 0:
                editor.click(force=True)
            
            print("    [>] Digitazione (simulazione umana)...")
            page.keyboard.type(bozza, delay=35) 
            time.sleep(3)
            
            print("    [>] Clic su 'Comment'...")
            page.locator('button[type="submit"], button[slot="submitButton"]').first.click(force=True)
            
            time.sleep(6) # Attende che la richiesta POST parta al server di Reddit
            
            # Segna come pubblicato
            c.execute("UPDATE scanned_posts SET status='POSTED' WHERE id=?", (post_id,))
            conn.commit()
            print("    [✓] Commento pubblicato con successo!")
            
        except Exception as e:
            print(f"    [!] Errore durante l'interazione Playwright: {e}")
            # SALVATAGGIO SCREENSHOT: Se fallisce scatta una foto per farti vedere il problema
            try:
                page.screenshot(path="errore_reddit.png")
                print("    [i] 📸 Screenshot scattato! Scarica 'errore_reddit.png' da GitHub per vedere cosa copriva lo schermo.")
            except:
                pass
            
        finally:
            browser.close()
            
    conn.close()

if __name__ == "__main__":
    main()

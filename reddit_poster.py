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
    print("🔫 AVVIO CECCHINO REDDIT (INIEZIONE JAVASCRIPT 2.3)")
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
            print("    [>] Caricamento pagina Reddit...")
            page.goto(post_url, wait_until="domcontentloaded", timeout=45000)
            time.sleep(6)
            
            # 1. INIEZIONE JS: Ordina al browser di portare il box al centro perfetto dello schermo
            print("    [>] Iniezione JS: Scroll forzato al centro...")
            try:
                page.evaluate("document.querySelector('shreddit-composer').scrollIntoView({behavior: 'smooth', block: 'center'});")
                time.sleep(3)
            except Exception as e:
                print("    [!] JS Scroll fallito, il box potrebbe non esistere.")
            
            # 2. INIEZIONE JS: Clicca il box aggirando i controlli di visibilità
            print("    [>] Iniezione JS: Click forzato...")
            try:
                page.evaluate("document.querySelector('shreddit-composer').click();")
                time.sleep(2)
            except:
                pass
                
            # Piano B per il focus: se JS non l'ha attivato, Playwright clicca brutalmente in mezzo allo schermo
            page.mouse.click(1920 / 2, 1080 / 2)
            time.sleep(1)
            
            print("    [>] Digitazione bozza (tastiera virtuale)...")
            # Usa la tastiera di sistema, scriverà ovunque si trovi il focus in quel momento
            page.keyboard.type(bozza, delay=35) 
            time.sleep(3)
            
            print("    [>] Cerca e clicca il tasto Comment...")
            # Usa il selettore più generico possibile supportato da Playwright (penetrerà lo Shadow DOM)
            submit_btn = page.locator('button:has-text("Comment")').last
            submit_btn.click(force=True, timeout=10000)
            time.sleep(6)
            
            c.execute("UPDATE scanned_posts SET status='POSTED' WHERE id=?", (post_id,))
            conn.commit()
            print("    [✓] Commento pubblicato con successo!")
            
        except Exception as e:
            print(f"    [!] Errore critico finale: {e}")
            try:
                page.screenshot(path="errore_reddit.png")
                print("    [i] 📸 Screenshot salvato.")
            except:
                pass
            
        finally:
            browser.close()
            
    conn.close()

if __name__ == "__main__":
    main()

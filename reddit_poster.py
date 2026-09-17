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
    print("🔫 AVVIO CECCHINO REDDIT (PLAYWRIGHT STEALTH 2.2)")
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
            
            # Chiude eventuali banner se presenti
            try:
                cookie_btn = page.locator('button:has-text("Accept all"), button:has-text("Accept")').first
                if cookie_btn.is_visible(timeout=2000):
                    cookie_btn.click(force=True)
                    time.sleep(2)
            except:
                pass
            
            print("    [>] Clicco sul box 'Join the conversation'...")
            # Miriamo ESATTAMENTE al testo che vediamo nel tuo screenshot
            trigger = page.locator('text="Join the conversation", text="Add a comment"').first
            
            if trigger.count() > 0:
                trigger.scroll_into_view_if_needed()
                time.sleep(1)
                trigger.click(force=True)
            else:
                # Se non trova il testo, clicca sul fumetto dei commenti in alto come piano B
                print("    [>] Box testo non trovato, clicco l'icona del commento...")
                page.locator('shreddit-post-action-row button[icon-name="comment-outline"], button[aria-label*="Comment"]').first.click(force=True)
            
            time.sleep(3)
            
            print("    [>] Aggancio l'editor di testo attivato...")
            editor = page.locator('div[contenteditable="true"]').first
            editor.wait_for(state="visible", timeout=10000)
            editor.click(force=True)
            
            print("    [>] Digitazione in corso...")
            page.keyboard.type(bozza, delay=35) 
            time.sleep(3)
            
            print("    [>] Clic su 'Comment'...")
            # Individua il bottone di invio dentro lo shreddit-composer
            page.locator('shreddit-composer button[slot="submitButton"], shreddit-composer button[type="submit"]').first.click(force=True)
            time.sleep(6)
            
            c.execute("UPDATE scanned_posts SET status='POSTED' WHERE id=?", (post_id,))
            conn.commit()
            print("    [✓] Commento pubblicato con successo!")
            
        except Exception as e:
            print(f"    [!] Errore durante l'interazione Playwright: {e}")
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

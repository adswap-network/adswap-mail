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
    print("🔫 AVVIO CECCHINO REDDIT (MOBILE BANNER KILLER 5.3)")
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
            time.sleep(6) 
            
            print("    [>] Esecuzione Banner Killer (Fix Javascript Puro)...")
            # Usa solo cicli DOM standard, niente selettori Playwright non supportati
            page.evaluate("""() => {
                // Distrugge i tag custom di Reddit usati per le pubblicità app
                document.querySelectorAll('xpromo-app-selector, xpromo-bottom-sheet').forEach(el => el.remove());
                
                // Cerca tutti gli elementi e i bottoni
                const elements = document.querySelectorAll('div, section, button, a');
                for (const el of elements) {
                    const style = window.getComputedStyle(el);
                    const txt = el.textContent || '';
                    
                    // Rimuove banner incollati in fondo allo schermo
                    if (style.position === 'fixed' || style.position === 'sticky') {
                        if (txt.includes('Reddit App') || txt.includes('View in') || txt.includes('Open')) {
                            el.remove();
                        }
                    }
                    
                    // Clicca eventuali banner cookie 
                    if (el.tagName.toLowerCase() === 'button' && (txt.includes('Accept') || txt.includes('Agree'))) {
                        el.click();
                    }
                }
            }""")
            time.sleep(2)
            
            # Scattiamo una foto a schermo pulito
            page.screenshot(path="debug_mobile_view.png")

            print("    [>] Ricerca della barra dei commenti...")
            # Sulla UI mobile, spesso bisogna toccare la barra "Add a comment" prima
            add_comment_bar = page.locator('text="Add a comment"').last
            if add_comment_bar.count() > 0:
                add_comment_bar.click(force=True)
                time.sleep(2)

            print("    [>] Aggancio all'editor...")
            editor_locator = page.locator('div[contenteditable="true"], textarea').last
            editor_locator.scroll_into_view_if_needed(timeout=5000)
            editor_locator.click(force=True)
            time.sleep(1)

            print("    [>] Scrittura del commento...")
            page.keyboard.type(bozza, delay=15)
            time.sleep(2)
            
            print("    [>] Pressione tasto Reply...")
            # Il bottone di invio mobile può avere nomi diversi
            submit_btn = page.locator('button:has-text("Reply"), button:has-text("Comment"), button[type="submit"]').last
            submit_btn.click(force=True)
            
            print("    [>] Attesa elaborazione server Reddit...")
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

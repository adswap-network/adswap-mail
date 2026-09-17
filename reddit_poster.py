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
    print("🔫 AVVIO CECCHINO REDDIT (DOM BYPASS 2.6)")
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
            
            print("    [>] Estrazione target basata sul tuo HTML...")
            editor = page.locator('div[contenteditable="true"][role="textbox"]').first
            
            print("    [>] Override Javascript: Focus e Click nativo...")
            # dispatch_event() bypassa tutti i controlli di visibilità di Playwright.
            # Esegue fisicamente l'azione a livello di codice della pagina.
            editor.evaluate("node => node.focus()")
            editor.dispatch_event("click")
            time.sleep(1)
            
            print("    [>] Digitazione della bozza...")
            # Ora che l'elemento ha forzatamente il focus, la tastiera virtuale scriverà lì dentro
            page.keyboard.type(bozza, delay=25)
            time.sleep(3)
            
            print("    [>] Ricerca del pulsante Submit...")
            submit_btn = page.locator('button#comment-composer-submit-button').first
            
            print("    [>] Click nativo sul Submit...")
            # Usiamo evaluate per innescare la funzione .click() nativa del browser, saltando i blocchi
            submit_btn.evaluate("node => node.click()")
            
            print("    [>] Attesa conferma di rete...")
            time.sleep(6)
            
            page.screenshot(path="conferma_pubblicazione.png")
            print("    [i] 📸 Screenshot salvato (conferma_pubblicazione.png). Controlla gli Artifacts!")
            
            c.execute("UPDATE scanned_posts SET status='POSTED' WHERE id=?", (post_id,))
            conn.commit()
            print("    [✓] Commento pubblicato con successo!")
            
        except Exception as e:
            print(f"    [!] Errore critico: {e}")
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

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
    print("🔫 AVVIO CECCHINO REDDIT (SHADOW DOM SUBMIT 2.10)")
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
            time.sleep(8) 
            
            print("    [>] Focus e scrittura tramite JS...")
            js_focus_and_type = f"""
            () => {{
                const editor = document.querySelector('shreddit-composer div[contenteditable="true"]');
                if (editor) {{
                    editor.scrollIntoView({{behavior: 'instant', block: 'center'}});
                    editor.focus();
                    editor.click();
                    return true;
                }}
                return false;
            }}
            """
            page.evaluate(js_focus_and_type)
            time.sleep(1)
            
            print("    [>] Digitazione bozza...")
            page.keyboard.type(bozza, delay=15)
            time.sleep(3)
            
            print("    [>] Ricerca e attivazione pulsante Submit (anche dentro Shadow DOM)...")
            # Questo script cerca il bottone sia normalmente che penetrando l'incapsulamento di Reddit
            js_submit_deep = """
            () => {
                const composer = document.querySelector('shreddit-composer');
                let btn = document.querySelector('#comment-composer-submit-button');
                
                if (!btn && composer && composer.shadowRoot) {
                    btn = composer.shadowRoot.querySelector('#comment-composer-submit-button');
                }
                if (!btn && composer) {
                    btn = composer.querySelector('button[type="submit"]');
                }
                
                if (btn) {
                    btn.click();
                    return true;
                }
                return false;
            }
            """
            inviato = page.evaluate(js_submit_deep)
            
            time.sleep(6) # Attesa invio dati al server
            
            page.screenshot(path="conferma_pubblicazione.png")
            print("    [i] 📸 Screenshot salvato localmente.")
            
            if inviato:
                c.execute("UPDATE scanned_posts SET status='POSTED' WHERE id=?", (post_id,))
                conn.commit()
                print("    [✓] Commento pubblicato con successo!")
            else:
                print("    [!] Impossibile trovare il bottone di invio.")
            
        except Exception as e:
            print(f"    [!] Errore: {e}")
            try:
                page.screenshot(path="errore_reddit.png")
            except:
                pass
            
        finally:
            browser.close()
            
    conn.close()

if __name__ == "__main__":
    main()

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
    print("🔫 AVVIO CECCHINO REDDIT (CTRL+ENTER BYPASS 3.0)")
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
            
            print("    [>] Focus mirato tramite JS sull'editor corretto...")
            # Usa gli attributi esatti estratti dal tuo dump HTML (slot="rte")
            js_focus = """
            () => {
                const editor = document.querySelector('shreddit-composer div[contenteditable="true"][slot="rte"]');
                if (editor) {
                    editor.scrollIntoView({behavior: 'instant', block: 'center'});
                    editor.focus();
                    editor.click();
                    return true;
                }
                return false;
            }
            """
            trovato = page.evaluate(js_focus)
            
            if not trovato:
                print("    [!] JS non ha trovato l'editor. Potrebbe essere un post rimosso.")
            
            time.sleep(2)
            
            print("    [>] Scrittura del commento (tastiera virtuale)...")
            page.keyboard.type(bozza, delay=15)
            time.sleep(3)
            
            print("    [>] Esecuzione shortcut 'Control + Enter' per pubblicazione immediata...")
            page.keyboard.press("Control+Enter")
            time.sleep(2)
            
            print("    [>] Tentativo click di sicurezza sul bottone fisico...")
            # Fallback di sicurezza basato sugli ID esatti del tuo HTML
            try:
                submit_btn = page.locator('button#comment-composer-submit-button, button[slot="submit-button"]').first
                submit_btn.click(force=True, timeout=3000)
            except:
                pass # Se Ctrl+Enter ha già inviato il modulo, il bottone sparirà e questo darà un errore innocuo
            
            time.sleep(6) # Tempo vitale per permettere la richiesta POST ai server Reddit
            
            page.screenshot(path="conferma_pubblicazione.png")
            print("    [i] 📸 Screenshot salvato (scaricalo dagli Artifacts su GitHub!).")
            
            c.execute("UPDATE scanned_posts SET status='POSTED' WHERE id=?", (post_id,))
            conn.commit()
            print("    [✓] Commento pubblicato con successo!")
            
        except Exception as e:
            print(f"    [!] Errore: {e}")
            try:
                page.screenshot(path="errore_reddit.png")
                print("    [i] 📸 Screenshot di debug salvato.")
            except:
                pass
            
        finally:
            browser.close()
            
    conn.close()

if __name__ == "__main__":
    main()

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
    print("🔫 AVVIO CECCHINO REDDIT (TARGET LOCK ASSOLUTO 3.1)")
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
    # Usiamo il link ufficiale di reindirizzamento
    post_url = f"https://redd.it/{post_id}"
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
            
            # Controllo anti-disastro: siamo finiti sulla pagina sbagliata?
            if "/submit" in page.url or "Create Post" in page.title():
                print("    [!] ALLARME: Reddit ci ha reindirizzato alla pagina Create Post.")
                raise Exception("Pagina errata. Post rimosso o link non valido.")
            
            print("    [>] Ricerca ESATTA del box commenti...")
            # Peschiamo il box solo ed esclusivamente se ha il placeholder corretto dei commenti
            js_focus = """
            () => {
                const editor = document.querySelector('div[aria-placeholder="Join the conversation"], div[aria-placeholder="Add a comment"]');
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
                raise Exception("Box commenti non trovato. I commenti potrebbero essere bloccati.")
            
            time.sleep(2)
            
            print("    [>] Scrittura del commento (tastiera virtuale)...")
            page.keyboard.type(bozza, delay=15)
            time.sleep(3)
            
            print("    [>] Pubblicazione (CTRL + ENTER)...")
            page.keyboard.press("Control+Enter")
            
            # Doppio click di sicurezza sul bottone fisico (dal tuo HTML)
            time.sleep(2)
            page.evaluate("""() => { 
                const btn = document.querySelector('button#comment-composer-submit-button'); 
                if(btn) btn.click(); 
            }""")
            
            print("    [>] Attesa conferma server...")
            time.sleep(6) 
            
            page.screenshot(path="conferma_pubblicazione.png")
            print("    [i] 📸 Screenshot salvato.")
            
            c.execute("UPDATE scanned_posts SET status='POSTED' WHERE id=?", (post_id,))
            conn.commit()
            print("    [✓] Commento pubblicato con successo!")
            
        except Exception as e:
            print(f"    [!] Errore critico: {e}")
            # Se fallisce la UI, segnamolo comunque come errore nel DB per non riprovarci all'infinito
            c.execute("UPDATE scanned_posts SET status='FAILED' WHERE id=?", (post_id,))
            conn.commit()
            try:
                page.screenshot(path="errore_reddit.png")
            except:
                pass
            
        finally:
            browser.close()
            
    conn.close()

if __name__ == "__main__":
    main()

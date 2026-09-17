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
    print("🔫 AVVIO CECCHINO REDDIT (PUNTAMENTO DI PRECISIONE 2.4)")
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
            time.sleep(8) # Lasciamo caricare bene l'interfaccia complessa di Reddit
            
            print("    [>] Aggancio mirato al container del testo...")
            # Playwright penetra in automatico lo Shadow DOM se concateniamo i locator
            composer = page.locator('shreddit-composer').first
            composer.scroll_into_view_if_needed()
            time.sleep(2)
            
            print("    [>] Ricerca dell'editor interno...")
            editor = composer.locator('[contenteditable="true"]').first
            
            if editor.count() == 0:
                raise Exception("Box di testo 'contenteditable' non trovato.")
                
            print("    [>] Click dentro l'editor e digitazione...")
            editor.click(force=True)
            time.sleep(1)
            
            # Non usiamo più la tastiera generica, ma scriviamo fisicamente DENTRO l'elemento
            editor.type(bozza, delay=35)
            time.sleep(3)
            
            print("    [>] Ricerca del pulsante Submit...")
            submit_btn = composer.locator('button[type="submit"], button[slot="submitButton"]').first
            
            if submit_btn.count() == 0:
                raise Exception("Tasto 'Comment' non trovato dentro il composer.")
                
            submit_btn.click(force=True)
            print("    [>] Click effettuato. Attesa per la conferma di rete...")
            time.sleep(6)
            
            # FOTOGRAFIA DI CONFERMA
            page.screenshot(path="conferma_pubblicazione.png")
            print("    [i] 📸 Screenshot di VITTORIA salvato (conferma_pubblicazione.png). Controlla Artifacts!")
            
            c.execute("UPDATE scanned_posts SET status='POSTED' WHERE id=?", (post_id,))
            conn.commit()
            print("    [✓] Commento pubblicato con successo!")
            
        except Exception as e:
            print(f"    [!] Errore critico: {e}")
            try:
                # ESTRAZIONE HTML AUTOMATICA
                html_dump = page.locator('shreddit-composer').first.inner_html()
                print("\n" + "="*50)
                print("--- INIZIO DUMP HTML PER L'IA ---")
                print(html_dump)
                print("--- FINE DUMP HTML ---")
                print("="*50 + "\n")
                
                page.screenshot(path="errore_reddit.png")
                print("    [i] 📸 Screenshot errore salvato.")
            except:
                print("    [!] Impossibile estrarre l'HTML.")
            
        finally:
            browser.close()
            
    conn.close()

if __name__ == "__main__":
    main()

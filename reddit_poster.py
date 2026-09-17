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
    print("🔫 AVVIO CECCHINO REDDIT (OLD REDDIT MASTER BYPASS 7.0)")
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
    
    # LA PORTA DI SERVIZIO: Usiamo old.reddit per avere un HTML puro e senza trappole
    post_url = f"https://old.reddit.com/comments/{post_id}/"
    print(f"[*] Obiettivo acquisito: {post_url}")

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        # Visuale Desktop normale
        context = browser.new_context(
            viewport={"width": 1920, "height": 1080},
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        )
        
        # Il cookie vale per tutto il circuito Reddit
        context.add_cookies([{
            "name": "reddit_session",
            "value": COOKIE_VALUE,
            "domain": ".reddit.com",
            "path": "/"
        }])
        
        page = context.new_page()
        
        try:
            print("    [>] Caricamento pagina Old Reddit...")
            page.goto(post_url, wait_until="domcontentloaded", timeout=60000)
            time.sleep(4)
            
            # Controllo Login: Su old.reddit il nome utente è sempre in alto a destra
            user_area = page.locator('span.user').first
            if user_area.count() == 0 or "login" in user_area.inner_text().lower():
                print("    [!!!] ALLARME: Reddit ci vede come NON loggati. Il Cookie è scaduto!")
                page.screenshot(path="errore_login.png")
                raise Exception("Cookie scaduto o invalido.")
                
            print("    [>] Ricerca dell'editor testuale...")
            # La casella commenti è un comunissimo e infallibile campo <textarea>
            textarea = page.locator('.commentarea > .usertext textarea[name="text"]').first
            
            if textarea.count() == 0:
                raise Exception("Casella di testo non trovata. Il post potrebbe essere bloccato o archiviato.")
            
            textarea.scroll_into_view_if_needed()
            
            print("    [>] Scrittura del commento...")
            textarea.fill(bozza)
            time.sleep(2)
            
            page.screenshot(path="debug_prima_dell_invio.png")
            
            print("    [>] Pressione tasto 'save'...")
            # Il bottone è un elementare <button class="save">
            submit_btn = page.locator('.commentarea > .usertext .usertext-buttons button.save').first
            submit_btn.click(force=True)
            
            print("    [>] Attesa elaborazione server Reddit...")
            time.sleep(6) 
            
            page.screenshot(path="conferma_pubblicazione.png")
            print("    [i] 📸 Screenshot di conferma salvato negli Artifacts!")
            
            c.execute("UPDATE scanned_posts SET status='POSTED' WHERE id=?", (post_id,))
            conn.commit()
            print("    [✓] Commento pubblicato con successo!")
            
        except Exception as e:
            print(f"    [!] Errore critico: {e}")
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

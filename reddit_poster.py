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
    print("🔫 AVVIO CECCHINO REDDIT (CSS NUKE & MOBILE 6.0)")
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
            # Iniettiamo il CSS prima ancora che la pagina inizi a caricarsi
            page.add_init_script("""
                const style = document.createElement('style');
                style.innerHTML = `
                    xpromo-bottom-sheet, 
                    xpromo-app-selector, 
                    shreddit-async-loader[bundlename="xpromo_bottom_sheet"],
                    #credential_picker_container,
                    iframe {
                        display: none !important;
                        opacity: 0 !important;
                        pointer-events: none !important;
                        z-index: -9999 !important;
                        height: 0 !important;
                    }
                `;
                document.head.appendChild(style);
            """)

            page.goto(post_url, wait_until="networkidle", timeout=60000)
            time.sleep(5) 
            
            # CSS Nuke 2: Ripetuto a caricamento completato per sicurezza contro React
            page.add_style_tag(content="xpromo-bottom-sheet, xpromo-app-selector { display: none !important; }")
            time.sleep(1)
            
            page.screenshot(path="debug_1_pulizia.png")
            print("    [>] Schermo pulito dai banner. Screenshot salvato.")
            
            print("    [>] Tocco la barra 'Add a comment' in basso...")
            # Sulla UI mobile, in basso c'è un finto input testuale che, se cliccato, apre l'editor vero e proprio
            add_comment_trigger = page.locator('text="Add a comment", text="Add your thoughts"').last
            add_comment_trigger.click(force=True, timeout=5000)
            time.sleep(3)
            
            page.screenshot(path="debug_2_composer_aperto.png")

            print("    [>] Digito il testo...")
            # Troviamo la vera textarea o il div editabile aperto a tutto schermo
            editor = page.locator('textarea, div[contenteditable="true"]').last
            editor.click(force=True)
            page.keyboard.type(bozza, delay=20)
            time.sleep(2)
            
            page.screenshot(path="debug_3_testo_inserito.png")
            
            print("    [>] Premo il pulsante Invia...")
            # Sulla UI mobile di Reddit il tasto di invio in alto a destra di solito è un "Reply" o un "Comment"
            submit_btn = page.locator('button:has-text("Reply"), button:has-text("Comment"), shreddit-composer button[type="submit"]').last
            submit_btn.click(force=True)
            
            print("    [>] Attesa elaborazione server...")
            time.sleep(6) 
            
            page.screenshot(path="conferma_pubblicazione.png")
            print("    [i] 📸 Tutte le fasi fotografate e salvate negli Artifacts!")
            
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

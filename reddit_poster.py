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
    print("🔫 AVVIO CECCHINO REDDIT (MOUSE FISICO & DUMP 4.1)")
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
            
            # 1. DUMP HTML INCONDIZIONATO (Lo salviamo SEMPRE prima di fare danni)
            print("    [>] Salvataggio HTML preventivo...")
            with open("debug_pre_azione.html", "w", encoding="utf-8") as f:
                f.write(page.content())
            
            if "/comments/" not in page.url:
                raise Exception(f"Redirect anomalo su {page.url}.")

            # 2. RICERCA COORDINATE DEL BOX
            print("    [>] Calcolo coordinate X,Y del box commenti...")
            box_coords = page.evaluate("""() => {
                let el = document.querySelector('shreddit-composer');
                if (el) {
                    el.scrollIntoView({behavior: 'instant', block: 'center'});
                    let rect = el.getBoundingClientRect();
                    // Restituisce il centro esatto dell'elemento
                    return {x: rect.x + rect.width / 2, y: rect.y + rect.height / 2};
                }
                return null;
            }""")
            
            if not box_coords:
                raise Exception("Impossibile calcolare le coordinate del box commenti.")
                
            print(f"    [>] Click FISICO del mouse alle coordinate: {box_coords}")
            page.mouse.click(box_coords["x"], box_coords["y"])
            time.sleep(2)
            
            print("    [>] Digitazione con tastiera di sistema...")
            page.keyboard.type(bozza, delay=20)
            time.sleep(3)
            
            # 3. RICERCA COORDINATE BOTTONE SUBMIT
            print("    [>] Calcolo coordinate X,Y del bottone Submit...")
            btn_coords = page.evaluate("""() => {
                let btn = document.querySelector('button#comment-composer-submit-button') || 
                          document.querySelector('shreddit-composer button[type="submit"]');
                
                // Ricerca nello shadowRoot se non lo trova nel DOM normale
                if (!btn) {
                    let composer = document.querySelector('shreddit-composer');
                    if (composer && composer.shadowRoot) {
                        btn = composer.shadowRoot.querySelector('button[type="submit"]');
                    }
                }
                
                if (btn) {
                    let rect = btn.getBoundingClientRect();
                    return {x: rect.x + rect.width / 2, y: rect.y + rect.height / 2};
                }
                return null;
            }""")
            
            if not btn_coords:
                raise Exception("Impossibile calcolare le coordinate del bottone Submit.")
                
            print(f"    [>] Click FISICO del mouse sul Submit alle coordinate: {btn_coords}")
            page.mouse.click(btn_coords["x"], btn_coords["y"])
            time.sleep(6)
            
            # 4. VERIFICA ANTI FALSO-POSITIVO
            print("    [>] Verifica della presenza del commento sulla pagina...")
            # Prende le prime 40 lettere della bozza e controlla se la pagina le sta visualizzando
            snippet = bozza[:40] 
            if snippet not in page.content():
                raise Exception("Il bottone è stato premuto, ma il commento non è apparso. Reddit ha rifiutato l'input.")
            
            page.screenshot(path="conferma_pubblicazione.png")
            print("    [i] 📸 Screenshot salvato.")
            
            c.execute("UPDATE scanned_posts SET status='POSTED' WHERE id=?", (post_id,))
            conn.commit()
            print("    [✓] Commento pubblicato e VERIFICATO visivamente con successo!")
            
        except Exception as e:
            print(f"    [!] Errore critico: {e}")
            
            print("    [>] Salvataggio DUMP HTML post-errore...")
            try:
                with open("errore_pagina_completa.html", "w", encoding="utf-8") as f:
                    f.write(page.content())
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

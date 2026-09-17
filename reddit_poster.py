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
    print("🔫 AVVIO CECCHINO REDDIT (JS DOM MANIPULATION & HTML DUMP 4.0)")
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
    # Torniamo all'URL lungo completo, previene i redirect ambigui del link corto
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
            
            # VERIFICA STRUTTURALE RIGIDA: Se non siamo in una pagina "comments", blocca tutto.
            if "/comments/" not in page.url:
                print(f"    [!] ALLARME REDIRECT: Siamo finiti su {page.url} invece della sezione commenti.")
                raise Exception("Redirect anomalo. Il post potrebbe essere stato rimosso.")

            print("    [>] Esecuzione manipolazione DOM nativa (Javascript puro)...")
            
            # Iniezione JS che cerca l'editor profondo, manipola l'inner text e forza il click
            js_inject = f"""
            (bozza) => {{
                // 1. Cerca il container del compositore
                const composer = document.querySelector('shreddit-composer');
                if (!composer) return "ERRORE: shreddit-composer non trovato.";
                
                // 2. Cerca l'editor di testo (nel DOM normale o nello shadowRoot)
                let editor = document.querySelector('div[contenteditable="true"]');
                if (!editor && composer.shadowRoot) {{
                    editor = composer.shadowRoot.querySelector('div[contenteditable="true"]');
                }}
                if (!editor) return "ERRORE: div contenteditable non trovato.";
                
                // 3. Modifica direttamente il testo bypassando la tastiera virtuale
                editor.scrollIntoView({{behavior: 'instant', block: 'center'}});
                editor.focus();
                
                // Assegna il testo e lancia un evento "input" per svegliare React
                editor.innerText = bozza;
                editor.dispatchEvent(new Event('input', {{ bubbles: true }}));
                
                // 4. Cerca il bottone Submit e forza il click nativo
                let btn = document.querySelector('button#comment-composer-submit-button') || document.querySelector('button[slot="submit-button"]');
                if (!btn && composer.shadowRoot) {{
                    btn = composer.shadowRoot.querySelector('button[type="submit"]');
                }}
                if (!btn && composer) {{
                    btn = composer.querySelector('button[type="submit"]');
                }}
                
                if (btn) {{
                    btn.removeAttribute('disabled');
                    btn.click();
                    return "SUCCESSO";
                }} else {{
                    return "ERRORE: Bottone Submit non trovato.";
                }}
            }}
            """
            
            risultato_js = page.evaluate(js_inject, bozza)
            
            if risultato_js != "SUCCESSO":
                raise Exception(risultato_js)
            
            print("    [>] Attesa conferma server...")
            time.sleep(6) 
            
            page.screenshot(path="conferma_pubblicazione.png")
            print("    [i] 📸 Screenshot salvato.")
            
            c.execute("UPDATE scanned_posts SET status='POSTED' WHERE id=?", (post_id,))
            conn.commit()
            print("    [✓] Commento pubblicato con successo!")
            
        except Exception as e:
            print(f"    [!] Errore: {e}")
            
            # ========================================================
            # DUMP HTML TOTALE
            # ========================================================
            print("    [>] Estrazione HTML totale della pagina...")
            try:
                html_content = page.content()
                
                # Salva su file (sarà caricato negli Artifacts dal tuo file .yml)
                with open("errore_pagina_completa.html", "w", encoding="utf-8") as f:
                    f.write(html_content)
                print("    [i] 📄 HTML salvato in 'errore_pagina_completa.html' (scaricalo da GitHub Artifacts).")
                
                # Stampa a video una porzione massiccia per sicurezza
                print("\n" + "="*50)
                print("--- INIZIO DUMP HTML COMPLETO ---")
                print(html_content[:50000]) # Limite di sicurezza per non far crashare la console di GitHub
                if len(html_content) > 50000:
                    print("\n... [TRONCATO PER LIMITI DI LOG. SCARICA IL FILE .html DAGLI ARTIFACTS PER IL CODICE COMPLETO] ...\n")
                print("--- FINE DUMP HTML COMPLETO ---")
                print("="*50 + "\n")
                
                page.screenshot(path="errore_reddit.png")
            except Exception as dump_e:
                print(f"    [!] Fallimento DUMP HTML: {dump_e}")
            
            # Evita di riprovare all'infinito un post guasto
            c.execute("UPDATE scanned_posts SET status='FAILED' WHERE id=?", (post_id,))
            conn.commit()
            
        finally:
            browser.close()
            
    conn.close()

if __name__ == "__main__":
    main()

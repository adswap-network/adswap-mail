import os
import sqlite3
import time
from pathlib import Path

from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError


DB_PATH = "reddit_radar.db"
COOKIE_VALUE = os.getenv("REDDIT_SESSION_COOKIE")

PAGE_TIMEOUT_MS = 45_000
WAIT_AFTER_LOAD_MS = 8_000
WAIT_AFTER_CLICK_MS = 8_000


def get_db():
    return sqlite3.connect(DB_PATH)


def save_debug(page, name):
    """
    Salva screenshot e HTML nella directory corrente.
    Questi file verranno poi caricati come artifact da GitHub Actions.
    """

    try:
        screenshot_path = f"{name}.png"
        page.screenshot(
            path=screenshot_path,
            full_page=True
        )
        print(f"[i] Screenshot salvato: {screenshot_path}")
    except Exception as e:
        print(f"[!] Errore salvataggio screenshot: {e}")

    try:
        html_path = f"{name}.html"
        Path(html_path).write_text(
            page.content(),
            encoding="utf-8"
        )
        print(f"[i] HTML salvato: {html_path}")
    except Exception as e:
        print(f"[!] Errore salvataggio HTML: {e}")


def get_pending_post(conn):
    cursor = conn.cursor()

    cursor.execute(
        """
        SELECT id, bozza
        FROM scanned_posts
        WHERE status = 'PENDING'
        ORDER BY id
        LIMIT 1
        """
    )

    return cursor.fetchone()


def find_editor(page):
    """
    Cerca un elemento contenteditable visibile.
    Playwright attraversa automaticamente gli Shadow DOM aperti.
    """

    selectors = [
        'shreddit-composer [contenteditable="true"]',
        '[contenteditable="true"]'
    ]

    for selector in selectors:

        try:
            locator = page.locator(selector)

            count = locator.count()

            print(
                f"[i] Selector editor '{selector}': "
                f"{count} elemento/i"
            )

            for i in range(count):

                candidate = locator.nth(i)

                try:
                    if candidate.is_visible():
                        print(
                            "[✓] Editor trovato."
                        )
                        return candidate

                except Exception:
                    continue

        except Exception as e:
            print(
                f"[i] Errore selector editor "
                f"'{selector}': {e}"
            )

    return None


def find_submit_button(page):
    """
    Cerca il pulsante per pubblicare il commento.
    """

    selectors = [
        "#comment-composer-submit-button",
        'button[type="submit"]',
        'shreddit-composer button'
    ]

    for selector in selectors:

        try:
            locator = page.locator(selector)

            count = locator.count()

            print(
                f"[i] Selector submit '{selector}': "
                f"{count} elemento/i"
            )

            for i in range(count):

                button = locator.nth(i)

                try:
                    if not button.is_visible():
                        continue

                    if not button.is_enabled():
                        continue

                    text = (
                        button.inner_text(timeout=1000)
                        .strip()
                        .lower()
                    )

                    aria = (
                        button.get_attribute("aria-label")
                        or ""
                    ).lower()

                    button_id = (
                        button.get_attribute("id")
                        or ""
                    ).lower()

                    combined = (
                        f"{text} {aria} {button_id}"
                    )

                    print(
                        f"[i] Bottone candidato: "
                        f"text='{text}', "
                        f"aria='{aria}', "
                        f"id='{button_id}'"
                    )

                    # Se è il bottone con ID specifico,
                    # lo accettiamo immediatamente.
                    if button_id == "comment-composer-submit-button":
                        print(
                            "[✓] Submit trovato tramite ID."
                        )
                        return button

                    # Altrimenti controlliamo il testo/aria-label.
                    keywords = [
                        "comment",
                        "submit",
                        "reply",
                        "post"
                    ]

                    if any(
                        word in combined
                        for word in keywords
                    ):
                        print(
                            "[✓] Submit trovato."
                        )
                        return button

                except Exception:
                    continue

        except Exception as e:
            print(
                f"[i] Errore ricerca "
                f"'{selector}': {e}"
            )

    return None


def is_logged_in(page):
    """
    Controllo basilare della sessione Reddit.
    """

    try:
        # Se compare il composer, normalmente siamo autenticati.
        composer = page.locator("shreddit-composer")

        if composer.count() > 0:
            print("[✓] shreddit-composer presente.")
            return True

    except Exception:
        pass

    # Controlliamo anche eventuali segnali di login.
    try:
        body = page.locator("body").inner_text().lower()

        login_words = [
            "log in",
            "login",
            "sign in"
        ]

        for word in login_words:
            if word in body:
                print(
                    f"[!] Trovato possibile "
                    f"segnale di login: '{word}'"
                )
                return False

    except Exception:
        pass

    return False


def verify_comment_posted(page, comment_text):
    """
    Verifica che Reddit abbia effettivamente mostrato
    il commento pubblicato.
    """

    normalized = " ".join(
        comment_text.split()
    ).strip()

    if not normalized:
        return False

    deadline = time.time() + 20

    while time.time() < deadline:

        # ---------------------------------------------------------
        # Metodo 1: ricerca del testo completo
        # ---------------------------------------------------------

        try:
            body_text = page.locator("body").inner_text()

            if normalized in body_text:
                print(
                    "[✓] Testo del commento trovato "
                    "nella pagina."
                )
                return True

        except Exception:
            pass

        # ---------------------------------------------------------
        # Metodo 2: ricerca get_by_text
        # ---------------------------------------------------------

        try:
            locator = page.get_by_text(
                normalized,
                exact=True
            )

            if locator.count() > 0:
                print(
                    "[✓] Commento trovato tramite "
                    "get_by_text()."
                )
                return True

        except Exception:
            pass

        time.sleep(1)

    return False


def main():

    print("==================================================")
    print(" REDDIT POSTER - PLAYWRIGHT")
    print("==================================================")
    print()

    # -------------------------------------------------------------
    # COOKIE
    # -------------------------------------------------------------

    if not COOKIE_VALUE:
        print(
            "[!] ERRORE: REDDIT_SESSION_COOKIE "
            "non presente nei Secrets."
        )
        return 1

    # -------------------------------------------------------------
    # DATABASE
    # -------------------------------------------------------------

    conn = get_db()

    try:

        record = get_pending_post(conn)

        if not record:
            print(
                "[*] Nessuna bozza PENDING."
            )
            return 0

        post_id, bozza = record

        if not bozza or not bozza.strip():
            print(
                f"[!] La bozza {post_id} è vuota."
            )
            return 1

        post_url = (
            f"https://www.reddit.com/comments/{post_id}"
        )

        print(
            f"[*] Obiettivo acquisito: {post_url}"
        )

        # ---------------------------------------------------------
        # PLAYWRIGHT
        # ---------------------------------------------------------

        with sync_playwright() as p:

            browser = p.chromium.launch(
                headless=True
            )

            context = browser.new_context(
                viewport={
                    "width": 1920,
                    "height": 1080
                },
                user_agent=(
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 "
                    "(KHTML, like Gecko) "
                    "Chrome/120.0.0.0 Safari/537.36"
                )
            )

            # -----------------------------------------------------
            # COOKIE REDDIT
            # -----------------------------------------------------

            context.add_cookies(
                [
                    {
                        "name": "reddit_session",
                        "value": COOKIE_VALUE,
                        "domain": ".reddit.com",
                        "path": "/",
                        "secure": True,
                        "httpOnly": True
                    }
                ]
            )

            page = context.new_page()

            try:

                # -------------------------------------------------
                # APERTURA POST
                # -------------------------------------------------

                print(
                    "[>] Caricamento pagina..."
                )

                page.goto(
                    post_url,
                    wait_until="domcontentloaded",
                    timeout=PAGE_TIMEOUT_MS
                )

                page.wait_for_timeout(
                    WAIT_AFTER_LOAD_MS
                )

                print(
                    f"[i] URL finale: {page.url}"
                )

                print(
                    f"[i] Titolo: {page.title()}"
                )

                # Screenshot iniziale.
                save_debug(
                    page,
                    "01_pagina_iniziale"
                )

                # -------------------------------------------------
                # CONTROLLO LOGIN
                # -------------------------------------------------

                print(
                    "[>] Controllo sessione Reddit..."
                )

                if not is_logged_in(page):

                    print(
                        "[!] Sessione Reddit non riconosciuta."
                    )

                    save_debug(
                        page,
                        "02_errore_login"
                    )

                    return 1

                print(
                    "[✓] Sessione Reddit apparentemente valida."
                )

                # -------------------------------------------------
                # TROVA EDITOR
                # -------------------------------------------------

                print(
                    "[>] Ricerca editor commento..."
                )

                editor = find_editor(page)

                if editor is None:

                    print(
                        "[!] Editor non trovato."
                    )

                    save_debug(
                        page,
                        "03_errore_editor"
                    )

                    return 1

                # -------------------------------------------------
                # FOCUS
                # -------------------------------------------------

                print(
                    "[>] Focus editor..."
                )

                editor.scroll_into_view_if_needed()

                editor.click()

                page.wait_for_timeout(500)

                # -------------------------------------------------
                # SCRITTURA
                # -------------------------------------------------

                print(
                    "[>] Inserimento bozza..."
                )

                try:

                    editor.fill(bozza)

                except Exception as fill_error:

                    print(
                        "[i] fill() non riuscito:"
                        f" {fill_error}"
                    )

                    print(
                        "[i] Provo keyboard.insert_text()..."
                    )

                    editor.click()

                    page.keyboard.insert_text(
                        bozza
                    )

                page.wait_for_timeout(1_000)

                # -------------------------------------------------
                # VERIFICA TESTO INSERITO
                # -------------------------------------------------

                try:

                    editor_text = editor.inner_text()

                    print(
                        "[i] Testo presente "
                        f"nell'editor: {len(editor_text)} caratteri"
                    )

                    if not editor_text.strip():

                        print(
                            "[!] L'editor è vuoto dopo "
                            "l'inserimento."
                        )

                        save_debug(
                            page,
                            "04_errore_scrittura"
                        )

                        return 1

                except Exception as e:

                    print(
                        "[!] Non posso verificare "
                        f"l'editor: {e}"
                    )

                    save_debug(
                        page,
                        "04_errore_scrittura"
                    )

                    return 1

                print(
                    "[✓] Bozza inserita."
                )

                save_debug(
                    page,
                    "05_prima_del_submit"
                )

                # -------------------------------------------------
                # TROVA SUBMIT
                # -------------------------------------------------

                print(
                    "[>] Ricerca pulsante Submit..."
                )

                submit = find_submit_button(page)

                if submit is None:

                    print(
                        "[!] Pulsante Submit non trovato."
                    )

                    save_debug(
                        page,
                        "06_errore_submit"
                    )

                    return 1

                # -------------------------------------------------
                # CLICK SUBMIT
                # -------------------------------------------------

                print(
                    "[>] Click sul pulsante Submit..."
                )

                submit.scroll_into_view_if_needed()

                submit.click(
                    timeout=10_000
                )

                print(
                    "[>] Submit eseguito."
                )

                page.wait_for_timeout(
                    WAIT_AFTER_CLICK_MS
                )

                # -------------------------------------------------
                # SCREEN DOPO CLICK
                # -------------------------------------------------

                save_debug(
                    page,
                    "07_dopo_submit"
                )

                # -------------------------------------------------
                # VERIFICA PUBBLICAZIONE
                # -------------------------------------------------

                print(
                    "[>] Verifica pubblicazione..."
                )

                published = verify_comment_posted(
                    page,
                    bozza
                )

                if published:

                    print(
                        "[✓] Commento trovato nella pagina."
                    )

                    # -------------------------------------------------
                    # UPDATE DATABASE
                    # -------------------------------------------------

                    cursor = conn.cursor()

                    cursor.execute(
                        """
                        UPDATE scanned_posts
                        SET status = 'POSTED'
                        WHERE id = ?
                        """,
                        (post_id,)
                    )

                    conn.commit()

                    print(
                        "[✓] Database aggiornato: POSTED"
                    )

                    save_debug(
                        page,
                        "08_conferma_pubblicazione"
                    )

                    print(
                        "[✓] OPERAZIONE COMPLETATA."
                    )

                    return 0

                # -------------------------------------------------
                # PUBBLICAZIONE NON VERIFICATA
                # -------------------------------------------------

                print(
                    "[!] Il click è stato eseguito, "
                    "ma il commento non è stato "
                    "verificato nella pagina."
                )

                print(
                    "[!] Il record rimane PENDING."
                )

                save_debug(
                    page,
                    "09_errore_verifica"
                )

                return 1

            except PlaywrightTimeoutError as e:

                print(
                    f"[!] Timeout Playwright: {e}"
                )

                save_debug(
                    page,
                    "errore_timeout"
                )

                return 1

            except Exception as e:

                print(
                    f"[!] Errore {type(e).__name__}: {e}"
                )

                save_debug(
                    page,
                    "errore_reddit"
                )

                return 1

            finally:

                browser.close()

    finally:

        conn.close()


if __name__ == "__main__":
    raise SystemExit(
        main()
    )

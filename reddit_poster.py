import os
import sqlite3
import time
from pathlib import Path

from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError


DB_PATH = "reddit_radar.db"
COOKIE_VALUE = os.getenv("REDDIT_SESSION_COOKIE")

POST_WAIT_SECONDS = 8
PAGE_TIMEOUT_MS = 45_000


def get_db():
    return sqlite3.connect(DB_PATH)


def save_debug(page, prefix="debug"):
    """
    Salva screenshot + HTML per poter capire cosa vede realmente
    GitHub Actions.
    """
    try:
        page.screenshot(
            path=f"{prefix}.png",
            full_page=True
        )
        print(f"[i] Screenshot salvato: {prefix}.png")
    except Exception as e:
        print(f"[!] Impossibile salvare screenshot: {e}")

    try:
        Path(f"{prefix}.html").write_text(
            page.content(),
            encoding="utf-8"
        )
        print(f"[i] HTML salvato: {prefix}.html")
    except Exception as e:
        print(f"[!] Impossibile salvare HTML: {e}")


def get_pending_post(conn):
    cursor = conn.cursor()

    cursor.execute("""
        SELECT id, bozza
        FROM scanned_posts
        WHERE status = 'PENDING'
        ORDER BY id
        LIMIT 1
    """)

    return cursor.fetchone()


def inspect_reddit_page(page):
    """
    Raccoglie informazioni diagnostiche sulla pagina Reddit.
    Non modifica la pagina.
    """

    return page.evaluate("""
    () => {
        function describeElement(el) {
            if (!el) return null;

            return {
                tag: el.tagName,
                id: el.id || "",
                className:
                    typeof el.className === "string"
                        ? el.className
                        : "",
                text: (el.innerText || "").substring(0, 200),
                contenteditable:
                    el.getAttribute("contenteditable"),
                ariaLabel:
                    el.getAttribute("aria-label"),
                type:
                    el.getAttribute("type")
            };
        }

        const composers = [
            ...document.querySelectorAll("shreddit-composer")
        ];

        const normalEditors = [
            ...document.querySelectorAll(
                '[contenteditable="true"]'
            )
        ];

        const normalButtons = [
            ...document.querySelectorAll(
                'button[type="submit"], button'
            )
        ];

        return {
            url: location.href,
            title: document.title,

            loggedInHints: {
                shredditComposer:
                    !!document.querySelector("shreddit-composer"),

                loginLinks:
                    [...document.querySelectorAll("a")]
                        .filter(a =>
                            (a.innerText || "")
                                .toLowerCase()
                                .includes("log in")
                        )
                        .length
            },

            composers: composers.map(c => ({
                outerHTML: c.outerHTML.substring(0, 1500),
                hasShadowRoot: !!c.shadowRoot,

                shadowEditors: c.shadowRoot
                    ? [
                        ...c.shadowRoot.querySelectorAll(
                            '[contenteditable="true"]'
                        )
                    ].map(describeElement)
                    : [],

                shadowButtons: c.shadowRoot
                    ? [
                        ...c.shadowRoot.querySelectorAll(
                            "button"
                        )
                    ].map(describeElement)
                    : []
            })),

            normalEditors:
                normalEditors.map(describeElement),

            buttons:
                normalButtons
                    .slice(0, 30)
                    .map(describeElement)
        };
    }
    """)


def find_editor(page):
    """
    Cerca l'editor in:
    1. DOM normale
    2. Shadow DOM del shreddit-composer
    """

    # Prima proviamo gli editor normali.
    normal = page.locator('[contenteditable="true"]')

    try:
        count = normal.count()

        for i in range(count):
            element = normal.nth(i)

            if element.is_visible():
                print("[✓] Editor trovato nel DOM normale.")
                return element

    except Exception:
        pass

    # Poi cerchiamo dentro gli shadow root.
    composers = page.locator("shreddit-composer")

    try:
        count = composers.count()

        for i in range(count):
            composer = composers.nth(i)

            # Playwright permette di attraversare lo Shadow DOM
            # usando locator discendenti.
            editor = composer.locator(
                '[contenteditable="true"]'
            )

            if editor.count() > 0:
                for j in range(editor.count()):
                    candidate = editor.nth(j)

                    try:
                        if candidate.is_visible():
                            print(
                                "[✓] Editor trovato dentro "
                                "shreddit-composer."
                            )
                            return candidate
                    except Exception:
                        pass

    except Exception as e:
        print(f"[!] Errore ricerca editor: {e}")

    return None


def find_submit_button(page):
    """
    Cerca il pulsante Submit/Comment.
    """

    # Prima: ID specifico, se Reddit lo utilizza.
    selectors = [
        "#comment-composer-submit-button",
        'button[type="submit"]'
    ]

    for selector in selectors:
        try:
            locator = page.locator(selector)

            for i in range(locator.count()):
                candidate = locator.nth(i)

                if candidate.is_visible() and candidate.is_enabled():
                    print(
                        f"[✓] Pulsante trovato con selector: {selector}"
                    )
                    return candidate

        except Exception:
            pass

    # Cerca dentro shreddit-composer.
    try:
        composers = page.locator("shreddit-composer")

        for i in range(composers.count()):
            composer = composers.nth(i)

            buttons = composer.locator("button")

            for j in range(buttons.count()):
                button = buttons.nth(j)

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

                    if any(word in combined for word in [
                        "comment",
                        "submit",
                        "reply",
                        "post"
                    ]):
                        print(
                            "[✓] Pulsante trovato dentro "
                            "shreddit-composer."
                        )
                        return button

                except Exception:
                    pass

    except Exception as e:
        print(f"[!] Errore ricerca pulsante: {e}")

    return None


def verify_logged_in(page):
    """
    Controllo basilare: il composer deve essere presente.
    """

    try:
        composer = page.locator("shreddit-composer")

        if composer.count() > 0:
            print("[✓] Composer Reddit presente.")
            return True
    except Exception:
        pass

    print("[!] Composer Reddit non trovato.")
    return False


def comment_was_posted(page, original_text):
    """
    Controlla se Reddit mostra il testo del commento nella pagina.

    Non consideriamo il semplice click come prova di successo.
    """

    normalized = " ".join(
        original_text.split()
    ).strip()

    if not normalized:
        return False

    # Aspettiamo che Reddit aggiorni il DOM.
    deadline = time.time() + 15

    while time.time() < deadline:

        try:
            # Testo esatto, quando possibile.
            locator = page.get_by_text(
                normalized,
                exact=True
            )

            if locator.count() > 0:
                for i in range(locator.count()):
                    try:
                        if locator.nth(i).is_visible():
                            return True
                    except Exception:
                        pass

        except Exception:
            pass

        # Controllo più permissivo per testi lunghi.
        try:
            body_text = page.locator("body").inner_text()

            if normalized in body_text:
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

    if not COOKIE_VALUE:
        print(
            "[!] REDDIT_SESSION_COOKIE non presente "
            "nei GitHub Secrets."
        )
        return 1

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
                f"[!] La bozza per {post_id} è vuota."
            )
            return 1

        post_url = (
            f"https://www.reddit.com/comments/{post_id}"
        )

        print(f"[*] Obiettivo: {post_url}")
        print(f"[*] ID database: {post_id}")
        print()

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
                }
            )

            context.add_cookies([
                {
                    "name": "reddit_session",
                    "value": COOKIE_VALUE,
                    "domain": ".reddit.com",
                    "path": "/",
                    "httpOnly": True,
                    "secure": True
                }
            ])

            page = context.new_page()

            try:

                print("[>] Caricamento pagina...")

                page.goto(
                    post_url,
                    wait_until="domcontentloaded",
                    timeout=PAGE_TIMEOUT_MS
                )

                # Diamo tempo ai Web Components di Reddit
                # di essere inizializzati.
                page.wait_for_timeout(
                    POST_WAIT_SECONDS * 1000
                )

                print(f"[i] URL finale: {page.url}")
                print(f"[i] Titolo: {page.title()}")

                # -------------------------------------------------
                # DEBUG / DIAGNOSTICA
                # -------------------------------------------------

                print("[>] Analisi struttura Reddit...")

                diagnostics = inspect_reddit_page(page)

                print(
                    f"[i] Composer presenti: "
                    f"{len(diagnostics['composers'])}"
                )

                print(
                    f"[i] Editor normali: "
                    f"{len(diagnostics['normalEditors'])}"
                )

                if diagnostics["loggedInHints"]["loginLinks"]:
                    print(
                        "[!] La pagina contiene un possibile "
                        "link di login."
                    )

                # -------------------------------------------------
                # LOGIN / COMPOSER
                # -------------------------------------------------

                if not verify_logged_in(page):

                    save_debug(
                        page,
                        "errore_composer"
                    )

                    print(
                        "[!] Reddit non mostra il composer."
                    )
                    print(
                        "[!] Il cookie potrebbe essere "
                        "scaduto/non valido oppure Reddit "
                        "potrebbe aver cambiato la pagina."
                    )

                    return 1

                # -------------------------------------------------
                # EDITOR
                # -------------------------------------------------

                print("[>] Ricerca editor...")

                editor = find_editor(page)

                if editor is None:

                    save_debug(
                        page,
                        "errore_editor"
                    )

                    print(
                        "[!] Editor non trovato."
                    )

                    return 1

                # -------------------------------------------------
                # SCRITTURA
                # -------------------------------------------------

                print("[>] Focus editor...")

                editor.scroll_into_view_if_needed()

                editor.click()

                page.wait_for_timeout(500)

                print("[>] Inserimento bozza...")

                # fill() è preferibile a keyboard.type()
                # per contenteditable.
                try:
                    editor.fill(bozza)
                except Exception:
                    # Fallback nel caso Reddit blocchi fill()
                    print(
                        "[i] fill() non riuscito, "
                        "uso keyboard.insert_text()."
                    )

                    editor.click()
                    page.keyboard.insert_text(bozza)

                page.wait_for_timeout(1500)

                # Verifica che il testo sia effettivamente
                # entrato nell'editor.
                try:
                    current_text = editor.inner_text()

                    if bozza.strip() not in current_text:
                        print(
                            "[!] La bozza non risulta "
                            "correttamente inserita."
                        )

                        save_debug(
                            page,
                            "errore_scrittura"
                        )

                        return 1

                except Exception as e:
                    print(
                        f"[!] Impossibile verificare "
                        f"il contenuto dell'editor: {e}"
                    )

                print("[✓] Bozza inserita.")

                # -------------------------------------------------
                # SUBMIT
                # -------------------------------------------------

                print("[>] Ricerca pulsante Submit...")

                submit = find_submit_button(page)

                if submit is None:

                    save_debug(
                        page,
                        "errore_submit"
                    )

                    print(
                        "[!] Pulsante Submit non trovato."
                    )

                    return 1

                print("[>] Click Submit...")

                submit.scroll_into_view_if_needed()

                submit.click()

                print(
                    "[>] Attesa risposta Reddit..."
                )

                page.wait_for_timeout(
                    POST_WAIT_SECONDS * 1000
                )

                # -------------------------------------------------
                # VERIFICA PUBBLICAZIONE
                # -------------------------------------------------

                print(
                    "[>] Verifica pubblicazione..."
                )

                published = comment_was_posted(
                    page,
                    bozza
                )

                if published:

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

                    print()
                    print(
                        "[✓] COMMENTO PUBBLICATO."
                    )
                    print(
                        "[✓] Database aggiornato: POSTED"
                    )

                    save_debug(
                        page,
                        "conferma_pubblicazione"
                    )

                    return 0

                # -------------------------------------------------
                # FALLIMENTO
                # -------------------------------------------------

                print()
                print(
                    "[!] Il click è stato eseguito, "
                    "ma non ho potuto verificare "
                    "la pubblicazione."
                )

                print(
                    "[!] Il DB NON viene modificato."
                )

                save_debug(
                    page,
                    "errore_verifica"
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
                    f"[!] Errore: {type(e).__name__}: {e}"
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
    raise SystemExit(main())

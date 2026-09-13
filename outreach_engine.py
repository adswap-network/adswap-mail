import json
import time
import random
import smtplib
import imaplib
import re
import requests
import os
from datetime import datetime, timedelta
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from google_play_scraper import app as play_scraper_app
import functools
# Forza ogni print() a svuotare il buffer immediatamente
print = functools.partial(print, flush=True)

# --- CONFIGURAZIONE ---
STATE_FILE = "outreach_state.json"
SMTP_SERVER = "smtp.gmail.com"
IMAP_SERVER = "imap.gmail.com"
PORT = 465

EMAIL_ACCOUNT = os.getenv("GMAIL_ADDRESS")
APP_PASSWORD = os.getenv("GMAIL_APP_PASSWORD")
SENDER_NAME = "Matteo"

DAYS_BEFORE_FOLLOWUP = 4
MAX_CAPACITY = 50
WARMUP_SCHEDULE = [5, 10, 15, 25, 35, 50]

# --- KEYWORD ADSWAP ---
ADSWAP_KEYWORDS = [
    # Categorie dirette e semplici
    "finance", "health", "productivity", "social", "dating", 
    "ecommerce", "entertainment", "travel", "news", "education",
    "action games", "casual games", "rpg games", "casino games",
    
    # Sotto-categorie ampie e termini generici
    "money", "fitness", "diet", "to do list", "calendar", 
    "shopping", "movies", "flights", "local news", "study",
    "budget", "crypto", "investing", "meditation", "workout", 
    "notes", "chat", "meet", "buy and sell", "music",
    
    # Coda lunga (fondamentali per pescare gli sviluppatori indie nella fascia 500-25k)
    "action offline game indie", "zombie survival game 2d", "retro platformer action",
    "match 3 puzzle free offline", "color sort puzzle hard", "idle clicker simulator",
    "expense tracker minimalist", "budget planner offline", "crypto portfolio widget",
    "pomodoro timer aesthetic", "habit tracker offline", "kanban board personal",
    "water reminder fasting", "step counter offline pedometer", "home workout no equipment",
    "anonymous chat local", "icebreaker questions app", "couple calendar shared",
    "flashcards maker study", "learn vocabulary daily", "rss reader minimalist fast",
    "daily journal secret", "workout logger gym", "time blocker schedule"
]

def load_state():
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {
        "config": {}, 
        "leads": {}, 
        "scanned_apps": [], 
        "used_keywords": []
    }

def save_state(state):
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=4)

def auto_scrape_new_leads(state, needed_amount):
    """Cerca sul Play Store finché non accumula abbastanza leads nella fascia 500-25k."""
    print(f"[*] Coda in esaurimento. Avvio scraping automatico per {needed_amount} nuovi dev...")
    added = 0
    
    available_kws = [kw for kw in ADSWAP_KEYWORDS if kw not in state["used_keywords"]]
    if not available_kws:
        print("[!] Tutte le keyword esaurite! Resetto l'elenco keyword.")
        state["used_keywords"] = []
        available_kws = ADSWAP_KEYWORDS

    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
    
    for kw in available_kws:
        if added >= needed_amount:
            break
            
        print(f"    -> Esploro keyword: '{kw}'")
        state["used_keywords"].append(kw)
        
        try:
            url = f"https://play.google.com/store/search?q={kw}&c=apps"
            response = requests.get(url, headers=headers, timeout=10)
            app_ids = list(dict.fromkeys(re.findall(r'href="/store/apps/details\?id=([a-zA-Z0-9._]+)"', response.text)))
            
            for app_id in app_ids:
                if app_id in state["scanned_apps"]:
                    continue
                state["scanned_apps"].append(app_id)
                
                try:
                    # Estrazione e filtraggio 500 - 25.000 download
                    details = play_scraper_app(app_id, lang='en', country='us')
                    min_installs = details.get('minInstalls', 0)
                    email = details.get('developerEmail')
                    
                    if 500 <= min_installs <= 25000 and email and "@" in email:
                        if email not in state["leads"]:
                            raw_title = details.get('title', 'your app')
                            clean_title = raw_title.split(" - ")[0].split(" – ")[0].split(" | ")[0].split(":")[0].strip()
                            
                            state["leads"][email] = {
                                "app_name": clean_title,
                                "package": app_id,
                                "status": "PENDING",
                                "first_sent_at": None,
                                "followup_sent_at": None
                            }
                            added += 1
                            print(f"       [+] Trovato: {clean_title} ({min_installs} DL)")
                            save_state(state)
                            if added >= needed_amount:
                                break
                except:
                    pass
                time.sleep(0.5)
        except Exception as e:
            print(f"    [!] Errore ricerca: {e}")

def get_daily_limit(state):
    now_str = datetime.utcnow().strftime("%Y-%m-%d")
    if "start_date" not in state["config"]:
        state["config"]["start_date"] = now_str
    days_passed = (datetime.utcnow() - datetime.strptime(state["config"]["start_date"], "%Y-%m-%d")).days
    return WARMUP_SCHEDULE[days_passed] if days_passed < len(WARMUP_SCHEDULE) else MAX_CAPACITY

def has_replied(target_email):
    """Legge la casella email per bloccare i follow-up se hanno già risposto."""
    try:
        mail = imaplib.IMAP4_SSL(IMAP_SERVER)
        mail.login(EMAIL_ACCOUNT, APP_PASSWORD)
        mail.select("inbox")
        status, response = mail.search(None, f'(FROM "{target_email}")')
        mail.logout()
        return status == "OK" and bool(response[0])
    except:
        return False

def get_email_templates(app_name):
    first_subject = f"Quick question regarding {app_name}"
    first_body = f"""Hi there,

I came across {app_name} on Google Play while looking for standout indie projects—really great work on it.

As a fellow independent developer, I know firsthand that building the app is only half the battle. Affording the massive User Acquisition (UA) costs to get it noticed is the real hurdle, and competing with big studios on traditional networks is a losing game.

To solve this, I built AdSwap (adswap.netlify.app). 

It is a completely free, transparent cross-promotion network. You integrate a lightweight SDK, show native ads for other indie apps to earn Credits, and spend those exact Credits to get {app_name} promoted across the network. 

Zero fiat money required, zero financial risk. The absolute worst-case scenario is that your campaigns don't get enough traction, but you lose absolutely nothing. (I cover the server and infrastructure costs myself to help bootstrap the ecosystem).

It takes just a few minutes to generate your SDK snippet. You can check out the dashboard here:
👉 adswap.netlify.app

Let’s stop paying for traffic and start exchanging it.

Best regards,

{SENDER_NAME}
Founder, AdSwap
"""

    followup_subject = f"Re: Quick question regarding {app_name}"
    followup_body = f"""Hi again,

Knowing how chaotic dev life gets, I just wanted to float this to the top of your inbox. 

Several independent developers have already started swapping traffic through AdSwap to cut their UA budgets to zero. Since there is no credit card required and no financial risk, it's essentially pure organic growth for {app_name}.

No worries at all if you're fully focused on other channels right now, but the console is ready for you whenever you want to test it out: adswap.netlify.app

Keep up the great work with the app!

Best,

{SENDER_NAME}
AdSwap
"""
    return (first_subject, first_body), (followup_subject, followup_body)

def main():
    if not EMAIL_ACCOUNT or not APP_PASSWORD:
        print("Errore: Credenziali email mancanti.")
        return

    state = load_state()
    daily_limit = get_daily_limit(state)
    now = datetime.utcnow()
    cutoff_date = now - timedelta(days=DAYS_BEFORE_FOLLOWUP)
    
    # 1. Trova candidati per Follow-up
    followup_queue = []
    for email, data in state["leads"].items():
        if data["status"] == "FIRST_SENT" and data["first_sent_at"]:
            if datetime.fromisoformat(data["first_sent_at"]) <= cutoff_date:
                followup_queue.append((email, data["app_name"]))
                
    # 2. Verifica se serve fare scraping per rimpinguare la coda
    pending_count = sum(1 for d in state["leads"].values() if d["status"] == "PENDING")
    needed_new = daily_limit - len(followup_queue)
    if pending_count < needed_new:
        auto_scrape_new_leads(state, needed_new - pending_count + 10) # Ne raccoglie qualcuno in più
    
    # 3. Costruisci la lista finale
    new_queue = [(e, d["app_name"]) for e, d in state["leads"].items() if d["status"] == "PENDING"]
    tasks = [(item, "FOLLOWUP") for item in followup_queue] + [(item, "FIRST") for item in new_queue]
    tasks_to_run = tasks[:daily_limit]

    if not tasks_to_run:
        print("Nessuna azione in coda per oggi.")
        return

    server = smtplib.SMTP_SSL(SMTP_SERVER, PORT)
    server.login(EMAIL_ACCOUNT, APP_PASSWORD)
    print(f"\n[*] Avvio invio SMTP: {len(tasks_to_run)} email (Limite Warm-up: {daily_limit})")

    for (email, app_name), task_type in tasks_to_run:
        if task_type == "FOLLOWUP" and has_replied(email):
            print(f"    [SKIP] {email} ha già risposto. Escluso dal follow-up.")
            state["leads"][email]["status"] = "REPLIED"
            save_state(state)
            continue

        (first_subj, first_txt), (fup_subj, fup_txt) = get_email_templates(app_name)
        msg = MIMEMultipart()
        msg["From"] = f"{SENDER_NAME} <{EMAIL_ACCOUNT}>"
        msg["To"] = email
        msg["Subject"] = fup_subj if task_type == "FOLLOWUP" else first_subj
        msg.attach(MIMEText(fup_txt if task_type == "FOLLOWUP" else first_txt, "plain", "utf-8"))

        try:
            server.sendmail(EMAIL_ACCOUNT, email, msg.as_string())
            state["leads"][email]["status"] = "FIRST_SENT" if task_type == "FIRST" else "FOLLOWUP_SENT"
            state["leads"][email]["first_sent_at" if task_type == "FIRST" else "followup_sent_at"] = now.isoformat()
            
            print(f"    [OK - {task_type}] -> {email} ({app_name})")
            save_state(state)

            # Ritardo randomizzato (45 - 110 secondi) anti-ban
            time.sleep(random.uniform(45, 110))
        except Exception as e:
            print(f"    [!] Errore su {email}: {e}")

    server.quit()
    print("\n[*] Esecuzione terminata. JSON aggiornato.")

if __name__ == "__main__":
    main()

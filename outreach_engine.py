import json
import time
import random
import smtplib
import imaplib
import re
import requests
import os
import csv
import functools
from datetime import datetime, timedelta
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from google_play_scraper import app as play_scraper_app

# Forza la stampa immediata a video su GitHub Actions
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
    "finance", "health", "productivity", "social", "dating", 
    "ecommerce", "entertainment", "travel", "news", "education",
    "action games", "casual games", "rpg games", "casino games",
    "money", "fitness", "diet", "to do list", "calendar", 
    "shopping", "movies", "flights", "local news", "study",
    "budget", "crypto", "investing", "meditation", "workout", 
    "notes", "chat", "meet", "buy and sell", "music",
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
        "config": {
            "start_date": datetime.utcnow().strftime("%Y-%m-%d"),
            "last_run_date": datetime.utcnow().strftime("%Y-%m-%d"),
            "sent_today": 0
        }, 
        "leads": {}, 
        "scanned_apps": [], 
        "used_keywords": []
    }

def save_state(state):
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=4)

def auto_import_existing_csv(state):
    """
    Importa vecchi file CSV retrocompatibili.
    Se hai già inviato la prima email a queste liste, le registra come FIRST_SENT.
    """
    possible_files = ["adswap_target_developers.csv", "adswap_leads.csv"]
    for csv_file in possible_files:
        if os.path.exists(csv_file):
            print(f"[*] Rilevato file storico: {csv_file}. Sincronizzazione in corso...")
            with open(csv_file, mode="r", encoding="utf-8") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    email = row.get("Email", "").strip().lower()
                    title = row.get("App Name", "").strip()
                    app_id = row.get("Package ID", "")
                    
                    if email and "@" in email and email not in state["leads"]:
                        clean_title = title.split(" - ")[0].split(" – ")[0].split(" | ")[0].split(":")[0].strip()
                        # Impostiamo la data a ieri per calcolare correttamente i 4 giorni per il follow-up
                        yesterday = (datetime.utcnow() - timedelta(days=1)).isoformat()
                        
                        state["leads"][email] = {
                            "app_name": clean_title,
                            "package": app_id,
                            "status": "FIRST_SENT",  # Già contattati ieri
                            "first_sent_at": yesterday,
                            "followup_sent_at": None
                        }
                        if app_id and app_id not in state["scanned_apps"]:
                            state["scanned_apps"].append(app_id)
            save_state(state)
            print(f"[✓] CSV sincronizzato. Database aggiornato con i contatti pregressi.")

def auto_scrape_new_leads(state, needed_amount):
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
                    details = play_scraper_app(app_id, lang='en', country='us')
                    min_installs = details.get('minInstalls', 0)
                    email = details.get('developerEmail')
                    
                    if 500 <= min_installs <= 25000 and email and "@" in email:
                        clean_email = email.strip().lower()
                        if clean_email not in state["leads"]:
                            raw_title = details.get('title', 'your app')
                            clean_title = raw_title.split(" - ")[0].split(" – ")[0].split(" | ")[0].split(":")[0].strip()
                            
                            state["leads"][clean_email] = {
                                "app_name": clean_title,
                                "package": app_id,
                                "status": "PENDING",
                                "first_sent_at": None,
                                "followup_sent_at": None
                            }
                            added += 1
                            print(f"       [+] Trovato: {clean_title} ({min_installs} DL) | {clean_email}")
                            save_state(state)
                            if added >= needed_amount:
                                break
                except:
                    pass
                time.sleep(0.5)
        except Exception as e:
            print(f"    [!] Errore ricerca: {e}")

def get_run_batch_size(state):
    """Calcola la quota residua giornaliera e restituisce il numero di email per questo run."""
    now_str = datetime.utcnow().strftime("%Y-%m-%d")
    
    # Reset del contatore giornaliero al cambio di data
    if state["config"].get("last_run_date") != now_str:
        state["config"]["last_run_date"] = now_str
        state["config"]["sent_today"] = 0
        
    start_date = datetime.strptime(state["config"].get("start_date", now_str), "%Y-%m-%d")
    days_passed = (datetime.utcnow() - start_date).days
    total_daily_limit = WARMUP_SCHEDULE[days_passed] if days_passed < len(WARMUP_SCHEDULE) else MAX_CAPACITY
    
    sent_today = state["config"].get("sent_today", 0)
    remaining_today = max(0, total_daily_limit - sent_today)
    
    if remaining_today == 0:
        print(f"[*] Quota giornaliera completata ({sent_today}/{total_daily_limit}). Nessun invio in questo slot.")
        return 0
        
    # Micro-scaglioni da 3 a 8 email per run per simulare comportamento umano
    batch_size = min(remaining_today, random.randint(3, 8))
    print(f"[*] Quota odierna: {sent_today}/{total_daily_limit}. Invio batch programmato per questa run: {batch_size} email.")
    return batch_size

def has_replied(target_email):
    """Verifica via IMAP se l'utente ha risposto nella nostra casella."""
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
        print("Errore: Credenziali email mancanti nelle variabili d'ambiente.")
        return

    state = load_state()
    auto_import_existing_csv(state)
    
    batch_size = get_run_batch_size(state)
    if batch_size == 0:
        save_state(state)
        return

    now = datetime.utcnow()
    cutoff_date = now - timedelta(days=DAYS_BEFORE_FOLLOWUP)
    
    # 1. Candidati per Follow-up (priorità assoluta)
    followup_queue = []
    for email, data in state["leads"].items():
        if data["status"] == "FIRST_SENT" and data.get("first_sent_at"):
            if datetime.fromisoformat(data["first_sent_at"]) <= cutoff_date:
                followup_queue.append((email, data["app_name"]))
                
    # 2. Reperimento nuovi contatti se la coda scarseggia
    pending_count = sum(1 for d in state["leads"].values() if d["status"] == "PENDING")
    needed_new = batch_size - len(followup_queue)
    if pending_count < max(10, needed_new):
        auto_scrape_new_leads(state, max(15, needed_new))
    
    # 3. Assemblaggio coda di invio
    new_queue = [(e, d["app_name"]) for e, d in state["leads"].items() if d["status"] == "PENDING"]
    tasks = [(item, "FOLLOWUP") for item in followup_queue] + [(item, "FIRST") for item in new_queue]
    tasks_to_run = tasks[:batch_size]

    if not tasks_to_run:
        print("[*] Nessuna email pronta da inviare per questa sessione.")
        save_state(state)
        return

    server = smtplib.SMTP_SSL(SMTP_SERVER, PORT)
    server.login(EMAIL_ACCOUNT, APP_PASSWORD)
    print(f"\n[*] Connesso al server SMTP. Esecuzione batch di {len(tasks_to_run)} email...")

    for (email, app_name), task_type in tasks_to_run:
        # Se deve inviare il follow-up, controlla che non abbiano risposto
        if task_type == "FOLLOWUP" and has_replied(email):
            print(f"    [SKIP] {email} ha già risposto via email. Escluso definitivamente.")
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
            
            # Aggiornamento stato
            if task_type == "FIRST":
                state["leads"][email]["status"] = "FIRST_SENT"
                state["leads"][email]["first_sent_at"] = now.isoformat()
            else:
                state["leads"][email]["status"] = "FOLLOWUP_SENT"
                state["leads"][email]["followup_sent_at"] = now.isoformat()
                
            state["config"]["sent_today"] = state["config"].get("sent_today", 0) + 1
            print(f"    [OK - {task_type}] -> {email} ({app_name})")
            save_state(state)

            # Ritardo casuale per rompere la cadenza da bot
            time.sleep(random.uniform(45, 95))
        except Exception as e:
            print(f"    [!] Errore nell'invio a {email}: {e}")

    server.quit()
    save_state(state)
    print("\n[*] Esecuzione batch completata con successo.")

if __name__ == "__main__":
    main()

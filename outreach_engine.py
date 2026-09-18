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

print = functools.partial(print, flush=True)

# --- CONFIGURAZIONE ---
STATE_FILE = "outreach_state.json"
SMTP_SERVER = "smtp.gmail.com"
IMAP_SERVER = "imap.gmail.com"
PORT = 465

EMAIL_ACCOUNT = os.getenv("GMAIL_ADDRESS")
APP_PASSWORD = os.getenv("GMAIL_APP_PASSWORD")
SENDER_NAME = "Daniele"

DAYS_BEFORE_FOLLOWUP = 4
MAX_CAPACITY = 50
WARMUP_SCHEDULE = [5, 10, 15, 25, 35, 50]

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
            state = json.load(f)
            if "scanned_developers" not in state: state["scanned_developers"] = []
            
            # Retrocompatibilità: assegna una 'source' ai vecchi lead se manca
            for email, data in state.get("leads", {}).items():
                if "source" not in data:
                    data["source"] = "product_hunt" if data.get("package") == "product_hunt" else "google_play"
            return state
            
    return {
        "config": {
            "start_date": datetime.utcnow().strftime("%Y-%m-%d"),
            "last_run_date": datetime.utcnow().strftime("%Y-%m-%d"),
            "sent_today": 0
        }, 
        "leads": {}, 
        "scanned_apps": [],
        "scanned_developers": [],
        "used_keywords": []
    }

def save_state(state):
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=4)

def auto_import_existing_csv(state):
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
                        yesterday = (datetime.utcnow() - timedelta(days=1)).isoformat()
                        
                        state["leads"][email] = {
                            "app_name": clean_title,
                            "package": app_id,
                            "source": "google_play", # Storici assunti come google_play
                            "status": "FIRST_SENT",
                            "first_sent_at": yesterday,
                            "followup_sent_at": None
                        }
                        if app_id and app_id not in state["scanned_apps"]:
                            state["scanned_apps"].append(app_id)
            save_state(state)
            print(f"[✓] CSV sincronizzato.")

def auto_scrape_new_leads(state, needed_amount):
    print(f"[*] Coda in esaurimento. Avvio scraping automatico per {needed_amount} nuovi dev...")
    added = 0
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}

    # --- 1. PRODUCT HUNT SCRAPING ---
    try:
        print("    [*] Ricerca nuovi lanci su Product Hunt...")
        res = requests.get("https://www.producthunt.com/feed", timeout=10, headers=headers)
        items = re.findall(r'<item>.*?<title><!\[CDATA\[(.*?)\]\]></title>.*?<link>(.*?)</link>', res.text, re.DOTALL)
        
        for title, ph_link in items:
            if added >= needed_amount: break
            try:
                ph_page = requests.get(ph_link, timeout=10, headers=headers)
                out_links = set(re.findall(r'href="(https://www\.producthunt\.com/r/p/[^"]+)"', ph_page.text))
                emails_found = set()
                play_ids_found = set(re.findall(r'play\.google\.com/store/apps/details\?id=([a-zA-Z0-9._]+)', ph_page.text))
                
                for out_link in out_links:
                    try:
                        site_page = requests.get(out_link, timeout=8, headers=headers)
                        emails_found.update(re.findall(r'mailto:([a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,})', site_page.text))
                        raw_emails = re.findall(r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b', site_page.text)
                        
                        for em in raw_emails:
                            if not any(x in em.lower() for x in ['sentry', 'wix', 'example', '.png', '.jpg', 'domain', 'test']):
                                emails_found.add(em)
                                
                        play_ids_found.update(re.findall(r'play\.google\.com/store/apps/details\?id=([a-zA-Z0-9._]+)', site_page.text))
                    except: pass
                
                for email in emails_found:
                    if added >= needed_amount: break
                    clean_email = email.lower().strip()
                    if clean_email not in state["leads"]:
                        clean_title = title.split(" - ")[0].strip()
                        state["leads"][clean_email] = {
                            "app_name": clean_title,
                            "package": "product_hunt",
                            "source": "product_hunt", # TAG: Product Hunt
                            "status": "PENDING",
                            "first_sent_at": None,
                            "followup_sent_at": None
                        }
                        added += 1
                        print(f"       [+ PH Lead] {clean_title} -> {clean_email}")
                        
                for app_id in play_ids_found:
                    if added >= needed_amount: break
                    if app_id in state["scanned_apps"]: continue
                    state["scanned_apps"].append(app_id)
                    
                    try:
                        details = play_scraper_app(app_id, lang='en', country='us')
                        dev_email = details.get('developerEmail')
                        dev_id = str(details.get('developerId', ''))
                        
                        if dev_id in state["scanned_developers"]: continue
                        if dev_id: state["scanned_developers"].append(dev_id)
                        
                        if dev_email and "@" in dev_email:
                            clean_email = dev_email.strip().lower()
                            if clean_email not in state["leads"]:
                                clean_title = details.get('title', title).split(" - ")[0].strip()
                                state["leads"][clean_email] = {
                                    "app_name": clean_title,
                                    "package": app_id,
                                    "source": "product_hunt", # TAG: Trovato tramite PH
                                    "status": "PENDING",
                                    "first_sent_at": None,
                                    "followup_sent_at": None
                                }
                                added += 1
                                print(f"       [+ PH->Store] {clean_title}")
                    except: pass
            except: pass
    except Exception as e:
        print(f"    [!] Errore modulo Product Hunt: {e}")

    # --- 2. GOOGLE PLAY SCRAPING ---
    if added >= needed_amount:
        save_state(state)
        return

    print("    [*] Ricerca su Google Play Store (Cross-Scraping)...")
    available_kws = [kw for kw in ADSWAP_KEYWORDS if kw not in state["used_keywords"]]
    if not available_kws:
        state["used_keywords"] = []
        available_kws = ADSWAP_KEYWORDS

    for kw in available_kws:
        if added >= needed_amount: break
        state["used_keywords"].append(kw)
        
        try:
            url = f"https://play.google.com/store/search?q={kw}&c=apps"
            response = requests.get(url, headers=headers, timeout=10)
            root_app_ids = list(dict.fromkeys(re.findall(r'href="/store/apps/details\?id=([a-zA-Z0-9._]+)"', response.text)))
            
            queue = root_app_ids[:15]
            visited_in_session = set()
            
            while queue and added < needed_amount:
                app_id = queue.pop(0)
                if app_id in state["scanned_apps"] or app_id in visited_in_session:
                    continue
                    
                state["scanned_apps"].append(app_id)
                visited_in_session.add(app_id)
                
                try:
                    details = play_scraper_app(app_id, lang='en', country='us')
                    min_installs = details.get('minInstalls', 0)
                    email = details.get('developerEmail')
                    dev_id = str(details.get('developerId', ''))
                    
                    if dev_id in state["scanned_developers"]:
                        continue
                    if dev_id:
                        state["scanned_developers"].append(dev_id)
                    
                    if 500 <= min_installs <= 25000 and email and "@" in email:
                        clean_email = email.strip().lower()
                        if clean_email not in state["leads"]:
                            raw_title = details.get('title', 'your app')
                            clean_title = raw_title.split(" - ")[0].split(" – ")[0].split(" | ")[0].split(":")[0].strip()
                            
                            state["leads"][clean_email] = {
                                "app_name": clean_title,
                                "package": app_id,
                                "source": "google_play", # TAG: Google Play Store
                                "status": "PENDING",
                                "first_sent_at": None,
                                "followup_sent_at": None
                            }
                            added += 1
                            print(f"       [+ Store] {clean_title} ({min_installs} DL)")
                            save_state(state)
                            
                    try:
                        app_page = requests.get(f"https://play.google.com/store/apps/details?id={app_id}", headers=headers, timeout=5)
                        page_app_ids = re.findall(r'href="/store/apps/details\?id=([a-zA-Z0-9._]+)"', app_page.text)
                        for related_id in dict.fromkeys(page_app_ids):
                            if related_id not in state["scanned_apps"] and related_id not in visited_in_session:
                                if len(queue) < 60:
                                    queue.append(related_id)
                    except: pass
                    
                except: pass
                time.sleep(0.4)
                
        except Exception as e:
            print(f"    [!] Errore ricerca Play Store per '{kw}': {e}")
            
    save_state(state)

def get_run_batch_size(state):
    now_utc = datetime.utcnow()
    now_str = now_utc.strftime("%Y-%m-%d")
    
    if state["config"].get("last_run_date") != now_str:
        state["config"]["last_run_date"] = now_str
        state["config"]["sent_today"] = 0
        
    start_date = datetime.strptime(state["config"].get("start_date", now_str), "%Y-%m-%d")
    days_passed = (now_utc - start_date).days
    total_daily_limit = WARMUP_SCHEDULE[days_passed] if days_passed < len(WARMUP_SCHEDULE) else MAX_CAPACITY
    
    sent_today = state["config"].get("sent_today", 0)
    remaining_today = max(0, total_daily_limit - sent_today)
    
    if remaining_today == 0:
        print(f"[*] Quota giornaliera completata ({sent_today}/{total_daily_limit}). Nessun invio in questo slot.")
        return 0
        
    hours_left = max(1, 24 - now_utc.hour)
    
    if hours_left <= 3:
        batch_size = remaining_today
        print(f"[!] Ultime ore del giorno. Recupero finale: {batch_size} email.")
    else:
        base_rate = remaining_today / hours_left
        batch_size = min(remaining_today, random.randint(int(base_rate), int(base_rate) + 2))
        batch_size = max(1, batch_size) if remaining_today > 0 else 0
        print(f"[*] Quota: {sent_today}/{total_daily_limit}. Ore a mezzanotte UTC: {hours_left}. Batch assegnato: {batch_size} email.")
        
    return batch_size

def has_replied(mail_client, target_email):
    if not mail_client: return False
    try:
        mail_client.select("inbox")
        status, response = mail_client.search(None, f'(FROM "{target_email}")')
        return status == "OK" and bool(response[0])
    except:
        return False

def get_email_templates(app_name):
    first_subject = f"Quick question regarding {app_name}"
    first_body = f"""Hi there,

I came across {app_name} while looking for standout indie projects—really great work on it.

As a fellow independent developer, I know firsthand that building the app is only half the battle. Affording the massive User Acquisition (UA) costs to get it noticed is the real hurdle, and competing with big studios on traditional networks is a losing game.

To solve this, I built AdSwap (adswap.netlify.app). 

It is a completely free, transparent cross-promotion network. You integrate a lightweight SDK, show native ads for other indie apps to earn Credits, and spend those exact Credits to get {app_name} promoted across the network. 

Zero fiat money required, zero financial risk. The absolute worst-case scenario is that your campaigns don't get enough traction, but you lose absolutely nothing. (I cover the server and infrastructure costs myself to help bootstrap the ecosystem).

It takes just a few minutes to generate your SDK snippet. You can check out the dashboard here:
👉 adswap.netlify.app

Let's stop paying for traffic and start exchanging it.

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

def get_pending_leads_prioritized(state):
    """Restituisce le email pendenti dando assoluta precedenza a Product Hunt"""
    ph_leads = [(e, d["app_name"], d.get("source", "product_hunt")) 
                for e, d in state["leads"].items() 
                if d["status"] == "PENDING" and d.get("source") == "product_hunt"]
                
    play_leads = [(e, d["app_name"], d.get("source", "google_play")) 
                  for e, d in state["leads"].items() 
                  if d["status"] == "PENDING" and d.get("source") != "product_hunt"]
                  
    return ph_leads + play_leads # Concatena mettendo Product Hunt in cima

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
    
    all_followup_candidates = []
    for email, data in state["leads"].items():
        if data["status"] == "FIRST_SENT" and data.get("first_sent_at"):
            if datetime.fromisoformat(data["first_sent_at"]) <= cutoff_date:
                all_followup_candidates.append((email, data["app_name"], data.get("source", "unknown")))
                
    max_followups = max(1, int(batch_size * 0.4)) if all_followup_candidates else 0
    selected_followups = all_followup_candidates[:max_followups]
    needed_new = batch_size - len(selected_followups)
    
    # Ottieni i lead pendenti già ordinati (Product Hunt prima)
    pending_leads = get_pending_leads_prioritized(state)
    
    if len(pending_leads) < needed_new:
        auto_scrape_new_leads(state, (needed_new - len(pending_leads)) + 15)
        # Ricalcola dopo lo scraping
        pending_leads = get_pending_leads_prioritized(state)
        
    selected_new = pending_leads[:needed_new]
    
    if len(selected_new) < needed_new:
        remaining_slots = needed_new - len(selected_new)
        extra_followups = all_followup_candidates[max_followups:max_followups + remaining_slots]
        selected_followups.extend(extra_followups)

    tasks_to_run = [(item, "FOLLOWUP") for item in selected_followups] + [(item, "FIRST") for item in selected_new]

    if not tasks_to_run:
        print("[*] Nessuna email pronta da inviare per questa sessione.")
        save_state(state)
        return

    imap_client = None
    try:
        imap_client = imaplib.IMAP4_SSL(IMAP_SERVER)
        imap_client.login(EMAIL_ACCOUNT, APP_PASSWORD)
    except Exception as e:
        print(f"[!] Impossibile connettersi a IMAP (controllo risposte saltato): {e}")

    server = smtplib.SMTP_SSL(SMTP_SERVER, PORT)
    server.login(EMAIL_ACCOUNT, APP_PASSWORD)
    print(f"\n[*] Esecuzione batch di {len(tasks_to_run)} email ({len(selected_followups)} Follow-up, {len(selected_new)} Nuove)...")

    for (email, app_name, source), task_type in tasks_to_run:
        if task_type == "FOLLOWUP" and has_replied(imap_client, email):
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
            
            if task_type == "FIRST":
                state["leads"][email]["status"] = "FIRST_SENT"
                state["leads"][email]["first_sent_at"] = now.isoformat()
            else:
                state["leads"][email]["status"] = "FOLLOWUP_SENT"
                state["leads"][email]["followup_sent_at"] = now.isoformat()
                
            state["config"]["sent_today"] = state["config"].get("sent_today", 0) + 1
            # Ora il log mostra chiaramente la fonte!
            print(f"    [OK - {task_type}] -> {email} ({app_name}) [Via: {source}]")
            save_state(state)

            time.sleep(random.uniform(45, 95))
        except Exception as e:
            print(f"    [!] Errore nell'invio a {email}: {e}")

    server.quit()
    if imap_client:
        try: imap_client.logout()
        except: pass

    save_state(state)
    print("\n[*] Esecuzione batch completata con successo.")

if __name__ == "__main__":
    main()

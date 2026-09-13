import json
import time
import random
import smtplib
from datetime import datetime, timedelta
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import os
import csv

STATE_FILE = "outreach_state.json"
CSV_SOURCE = "adswap_target_developers.csv"

SMTP_SERVER = "smtp.gmail.com"
SMTP_PORT = 465
SENDER_EMAIL = os.getenv("GMAIL_ADDRESS")
APP_PASSWORD = os.getenv("GMAIL_APP_PASSWORD")
SENDER_NAME = "Daniele"

DAYS_BEFORE_FOLLOWUP = 4
MAX_CAPACITY = 50

# Progressione del warm-up: Giorno 0 -> 5 email, Giorno 1 -> 10, ecc.
WARMUP_SCHEDULE = [5, 10, 15, 25, 35, 50] 

def load_state():
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {"config": {}, "leads": {}}

def save_state(state):
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=4)

def sync_csv_to_state(state):
    if not os.path.exists(CSV_SOURCE):
        return state
        
    with open(CSV_SOURCE, mode="r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            email = row.get("Email", "").strip().lower()
            title = row.get("App Name", "").strip()
            
            if email and "@" in email and email not in state["leads"]:
                clean_title = title.split(" - ")[0].split(" – ")[0].split(" | ")[0].split(":")[0].strip()
                state["leads"][email] = {
                    "app_name": clean_title,
                    "status": "PENDING",
                    "first_sent_at": None,
                    "followup_sent_at": None
                }
    return state

def get_daily_limit(state):
    now_str = datetime.utcnow().strftime("%Y-%m-%d")
    if "start_date" not in state["config"]:
        state["config"]["start_date"] = now_str
        
    start_date = datetime.strptime(state["config"]["start_date"], "%Y-%m-%d")
    days_passed = (datetime.utcnow() - start_date).days
    
    if days_passed < len(WARMUP_SCHEDULE):
        return WARMUP_SCHEDULE[days_passed]
    return MAX_CAPACITY

def get_email_templates(app_name):
    first_subject = f"Quick question regarding {app_name}"
    first_body = f"""Hi there,

I came across {app_name} on Google Play while looking for standout indie projects—great work on it!

As an independent developer myself, I know firsthand that user acquisition is brutally expensive. Competing against big ad budgets with traditional ad networks is unsustainable.

To solve this, I built AdSwap (https://adswap.netlify.app), a completely free, automated cross-promotion network for mobile devs. 

You display lightweight native/interstitial ads for other indie apps to earn Credits, and use those Credits to get {app_name} installed by users across the network. Zero fiat budget required, zero financial risk—I fund the cloud infrastructure myself to help bootstrap the ecosystem.

If you'd like to check out the dashboard and grab the SDK snippet:
👉 https://adswap.netlify.app

Best regards,

{SENDER_NAME}
Founder, AdSwap
"""

    followup_subject = f"Re: Quick question regarding {app_name}"
    followup_body = f"""Hi again,

Just following up briefly in case my previous message got buried.

I wanted to make sure you saw the concept behind AdSwap for {app_name}: it's purely an organic traffic-swap network. If you aren't running paid UA right now, it costs nothing to keep your campaigns running on earned credits.

No worries at all if you're fully focused on other channels right now, but feel free to check out the integration guide whenever convenient: https://adswap.netlify.app

Keep up the great work!

Best,

{SENDER_NAME}
AdSwap
"""
    return (first_subject, first_body), (followup_subject, followup_body)

def run_outreach():
    state = load_state()
    state = sync_csv_to_state(state)
    
    daily_limit = get_daily_limit(state)
    print(f"Limite invio per oggi calcolato dal Warm-up: {daily_limit} email.")

    now = datetime.utcnow()
    cutoff_date = now - timedelta(days=DAYS_BEFORE_FOLLOWUP)
    
    # 1. Cerca candidati per Follow-up
    followup_queue = []
    for email, data in state["leads"].items():
        if data["status"] == "FIRST_SENT" and data["first_sent_at"]:
            sent_time = datetime.fromisoformat(data["first_sent_at"])
            if sent_time <= cutoff_date:
                followup_queue.append((email, data["app_name"]))
                
    # 2. Cerca nuovi contatti
    new_queue = [(email, data["app_name"]) for email, data in state["leads"].items() if data["status"] == "PENDING"]
    
    tasks = [(item, "FOLLOWUP") for item in followup_queue] + [(item, "FIRST") for item in new_queue]
    tasks_to_run = tasks[:daily_limit]

    if not tasks_to_run:
        print("Nessuna email in coda per questa sessione.")
        save_state(state)
        return

    server = smtplib.SMTP_SSL(SMTP_SERVER, SMTP_PORT)
    server.login(SENDER_EMAIL, APP_PASSWORD)
    
    print(f"Avvio invio per {len(tasks_to_run)} destinatari...\n")

    for (email, app_name), task_type in tasks_to_run:
        (first_subj, first_txt), (fup_subj, fup_txt) = get_email_templates(app_name)
        
        subject = fup_subj if task_type == "FOLLOWUP" else first_subj
        body = fup_txt if task_type == "FOLLOWUP" else first_txt

        msg = MIMEMultipart()
        msg["From"] = f"{SENDER_NAME} <{SENDER_EMAIL}>"
        msg["To"] = email
        msg["Subject"] = subject
        msg.attach(MIMEText(body, "plain", "utf-8"))

        try:
            server.sendmail(SENDER_EMAIL, email, msg.as_string())
            timestamp_str = now.isoformat()
            
            if task_type == "FIRST":
                state["leads"][email]["status"] = "FIRST_SENT"
                state["leads"][email]["first_sent_at"] = timestamp_str
            else:
                state["leads"][email]["status"] = "FOLLOWUP_SENT"
                state["leads"][email]["followup_sent_at"] = timestamp_str
                
            print(f"[INVIATA - {task_type}] -> {email}")
            
            # Salva lo stato dopo ogni singolo invio riuscito per evitare perdite di dati
            save_state(state)

            sleep_seconds = random.uniform(40, 90)
            time.sleep(sleep_seconds)
            
        except Exception as e:
            print(f"[!] Errore su {email}: {e}")

    server.quit()
    print("\nSessione giornaliera completata.")

if __name__ == "__main__":
    run_outreach()

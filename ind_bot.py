"""
IND Утрехт -> Telegram
Стежить за вільним часом на "Verblijfssticker Oekraine"
у пункті "IND Utrecht Oekraine - Flexloket" (сторінка https://oap.ind.nl/nl/#/OEK).
Запускає його cron-job.org кожні 10 хвилин через GitHub Actions (файл .github/workflows/ind.yml).

Кожен запуск кілька хвилин поспіль перевіряє сайт щохвилини-півтори,
тож вільне місце бот помічає за 1-2 хвилини.
"""
import json
import os
import random
import sys
import time
import urllib.parse
import urllib.request

# ---------------- НАЛАШТУВАННЯ ----------------
PERSONS = 1                      # скільки людей іде на прийом
DESK_NAME_CONTAINS = "utrecht"   # який пункт IND стежити
PRODUCT_CODE = "OEK"             # Verblijfssticker Oekraine
RUN_MINUTES = 9                  # скільки хвилин працює один запуск (cron-job.org запускає кожні 10 хв)
CHECK_EVERY_SEC = 75             # пауза між перевірками
# ----------------------------------------------

BASE = "https://oap.ind.nl/oap/api"
BOOKING_PAGE = "https://oap.ind.nl/nl/#/OEK"
TOKEN = os.environ.get("TELEGRAM_TOKEN", "").strip()
CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "").strip()
HERE = os.path.dirname(os.path.abspath(__file__))
STATE_FILE = os.path.join(HERE, "ind_state.json")

MONTHS = ["", "січня", "лютого", "березня", "квітня", "травня", "червня",
          "липня", "серпня", "вересня", "жовтня", "листопада", "грудня"]


def log(msg):
    print(time.strftime("%H:%M:%S"), msg, flush=True)


def ind(path, params=None):
    url = BASE + path + ("?" + urllib.parse.urlencode(params) if params else "")
    req = urllib.request.Request(url, headers={
        "oap-locale": "nl",
        "Accept": "application/json",
        "User-Agent": "Mozilla/5.0 (ind-bot)",
        "Referer": "https://oap.ind.nl/nl/",
    })
    with urllib.request.urlopen(req, timeout=30) as r:
        text = r.read().decode("utf-8")
    if text.startswith(")]}'"):          # захисний префікс IND перед JSON
        text = text.split("\n", 1)[1]
    return json.loads(text)


def get_slots():
    """Ключі продукту й пункту IND час від часу міняє, тому щоразу шукаємо їх заново."""
    product = ind(f"/products/{PRODUCT_CODE}")["data"]
    desks = ind("/desks/", {"productKey": product["key"]})["data"] or []
    desk = next((d for d in desks if DESK_NAME_CONTAINS in d.get("name", "").lower()), None)
    if not desk:
        return None, []
    slots = ind(f"/desks/{desk['key']}/slots",
                {"productKey": product["key"], "persons": PERSONS}).get("data") or []
    return desk, slots


def slot_id(s):
    if isinstance(s, dict):
        return f"{s.get('date','')} {s.get('startTime','')}".strip() or json.dumps(s, sort_keys=True)
    return str(s)


def nice_date(iso):
    try:
        y, m, d = iso[:10].split("-")
        return f"{int(d)} {MONTHS[int(m)]}"
    except Exception:
        return iso


def message(slots):
    by_day = {}
    for s in slots:
        if isinstance(s, dict) and s.get("date"):
            by_day.setdefault(s["date"], []).append(s.get("startTime", "")[:5])
    lines = ["🔔 <b>IND Утрехт: з'явився вільний час!</b>",
             "Verblijfssticker Oekraine", ""]
    if by_day:
        for day in sorted(by_day)[:10]:
            times = ", ".join(t for t in sorted(by_day[day]) if t)
            lines.append(f"📅 {nice_date(day)}: {times}")
    else:
        lines.append(f"Вільних місць: {len(slots)}")
    lines += ["", "Бронюйте швидко, місця розбирають за хвилини:", BOOKING_PAGE]
    return "\n".join(lines)


def tg(text):
    data = urllib.parse.urlencode({"chat_id": CHAT_ID, "text": text, "parse_mode": "HTML",
                                   "disable_web_page_preview": "true"}).encode()
    urllib.request.urlopen(f"https://api.telegram.org/bot{TOKEN}/sendMessage", data=data, timeout=30)


def load_state():
    try:
        return json.load(open(STATE_FILE))
    except Exception:
        return {"started": False, "sent": []}


def main():
    if not TOKEN or not CHAT_ID:
        sys.exit("Немає TELEGRAM_TOKEN або TELEGRAM_CHAT_ID у Secrets.")
    state = load_state()
    sent = set(state.get("sent", []))

    if not state.get("started"):
        desk, slots = get_slots()
        tg("✅ Бот IND підключено! Стежу за записом на Verblijfssticker Oekraine в Утрехті"
           + (f" ({desk['name']})." if desk else ".")
           + " Напишу, щойно з'явиться вільний час.")
        state["started"] = True

    deadline = time.time() + RUN_MINUTES * 60
    while True:
        try:
            desk, slots = get_slots()
            ids = {slot_id(s) for s in slots}
            new = [s for s in slots if slot_id(s) not in sent]
            log(f"Пункт: {desk['name'] if desk else 'немає'}, вільних: {len(slots)}, нових: {len(new)}")
            if new:
                tg(message(new))
                sent |= {slot_id(s) for s in new}
            sent &= ids               # забуваємо зайняті місця, щоб повідомити, якщо звільняться знову
        except Exception as e:
            log(f"Помилка перевірки, спробую ще раз: {e}")
        if time.time() + CHECK_EVERY_SEC > deadline:
            break
        time.sleep(CHECK_EVERY_SEC + random.randint(0, 20))

    state["sent"] = sorted(sent)
    json.dump(state, open(STATE_FILE, "w"))


if __name__ == "__main__":
    main()

"""Intent Engine — customer ka message samajhna (rules + keywords).

AI ka mood kharab ho sakta hai, rules nahi. Isliye saari important cheezein
(complaint, payment, handover, STOP) pehle yahin pakdi jati hain — uske baad
AI sirf baat ka andaaz banata hai.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

# order: check ka order bhi important hai (complaint pehle, greeting baad me)
INTENT_PATTERNS: list[tuple[str, list[str]]] = [
    ("opt_out", [r"\bstop\b", r"\bunsubscribe\b", r"message band", r"mat bhejo", r"pareshan", r"block kar"]),
    ("opt_in", [r"^\s*start\s*$", r"haan bhejo", r"offers? bhej", r"haan.*offer"]),
    ("handover", [r"insaan", r"staff", r"manager", r"human", r"asli banda", r"baat kara", r"call kara", r"talk to"]),
    ("complaint", [
        r"bakwaas", r"bekaar", r"bekar", r"ghatiya", r"kharab", r"thanda", r"thandi", r"galat", r"ganda",
        r"nahi aaya", r"nahi mila", r"late", r"deri", r"paisa kat", r"refund", r"complaint", r"shikayat",
        r"gussa", r"bad", r"worst", r"tasteless", r"unhygienic", r"hair", r"makkhi", r"insect",
    ]),
    ("party_booking", [r"party", r"catering", r"bulk", r"kitty", r"birthday party", r"20 log", r"function", r"event"]),
    ("feedback_rating", [r"^\s*[1-5]\s*$", r"[1-5]\s*star", r"^\s*[1-5]\s*/\s*5"]),
    ("menu", [r"\bmenu\b", r"kya kya", r"kya milega", r"card bhej", r"list bhej", r"kya hai", r"dishes", r"dikha"]),
    ("price_query", [r"kitna", r"price", r"rate", r"cost", r"kitne ka", r"kitne ki"]),
    ("reservation_cancel", [r"cancel.*(table|booking|reservation)", r"(table|booking|reservation).*cancel"]),
    ("reservation", [
        r"table", r"book kar", r"booking", r"reserve", r"reservation", r"seat", r"baje.*(aana|aayen|aa rahe)",
        r"(aana|aayenge|aa rahe).*baje",
    ]),
    ("order_status", [r"order kaha", r"kahan hai", r"kitni der", r"status", r"kab tak", r"kab aayega", r"track", r"rider", r"delivery boy"]),
    ("pay", [r"pay", r"payment", r"upi", r"link bhej", r"paise bhej", r"online pay", r"gpay", r"phonepe", r"paytm"]),
    ("bill", [r"\bbill\b", r"total kitna", r"kitna hua", r"hisaab", r"invoice"]),
    ("feedback_positive", [r"achha tha", r"accha tha", r"mazedaar", r"maza aa", r"swadisht", r"tasty", r"lajawaab", r"best tha", r"love it", r"dhanyavad", r"thank"]),
    ("loyalty", [r"points?", r"loyalty", r"free coffee", r"reward"]),
    ("special", [r"aaj ka special", r"special", r"recommend", r"suggest", r"kya achha", r"kuch achha", r"best kya", r"aaj kya"]),
    ("repeat_order", [r"wahi", r"wohi", r"same", r"repeat", r"phir se", r"pichla", r"pichhla", r"last order", r"pehle wala"]),
    ("order", [
        r"\b\d{1,2}\s*(?:x|×|\*)\s*[a-zA-Z]", r"\b(kar do|kardo|de do|dedo|chahiye|lena hai|le lo|bhej do|order|mangwa|pack)\b",
        r"\b(ek|do|teen|char|chaar|paanch|panch)\b.*\b(paneer|pizza|naan|coffee|chai|dosa|biryani|roti|rice|burger|roll|samosa|lassi|momo)\b",
    ]),
    ("owner_report", [r"aaj ki sale", r"report", r"kitni sale", r"business kaisa", r"total order aaj"]),
    ("broadcast", [r"broadcast", r"sabko bhej", r"offer bhej sabko", r"campaign"]),
    ("address_hours", [r"kaha ho", r"kahan ho", r"address", r"location", r"timing", r"kitne baje khul", r"band kab", r"open"]),
    ("name_provided", [r"\bmera naam\b", r"\bmy name is\b", r"\bnaam\b.*\b(hai|h)\b", r"\bi am\b", r"^main\s+\w+"]),
    ("birthday_set", [r"mera birthday", r"birthday.*\b(hai|h)\b", r"my birthday"]),
    ("greeting", [r"^(hi|hii+|hello|hey|namaste|namaskar|ram ram|salaam|good morning|good evening|gm|sir)\b", r"^[\W\s]*$"]),
]

_ORDER_WORDS = {
    "paneer", "pizza", "naan", "nan", "coffee", "chai", "tea", "dosa", "biryani", "roti", "rice", "burger",
    "roll", "samosa", "lassi", "momo", "sandwich", "noodles", "manchurian", "paratha", "cake", "shake",
    "pasta", "fries", "papad", "dal", "kofta", "chicken", "mutton", "egg", "tikka", "lassi", "idli",
    "uttapam", "poha", "chole", "bhature", "combo", "meal", "ice", "cream", "jamun", "rasmalai", "soda",
}

MONTHS = {
    "jan": "01", "feb": "02", "mar": "03", "apr": "04", "may": "05", "jun": "06",
    "jul": "07", "aug": "08", "sep": "09", "oct": "10", "nov": "11", "dec": "12",
    "january": "01", "february": "02", "march": "03", "april": "04", "june": "06",
    "july": "07", "august": "08", "september": "09", "october": "10", "november": "11", "december": "12",
}
NUM_WORDS = {
    "ek": 1, "do": 2, "teen": 3, "tin": 3, "char": 4, "chaar": 4, "paanch": 5, "panch": 5,
    "chhe": 6, "che": 6, "saat": 7, "aath": 8, "nau": 9, "das": 10, "one": 1, "two": 2,
    "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10,
}


@dataclass
class Intent:
    name: str = "unknown"
    confidence: float = 0.0
    entities: dict = field(default_factory=dict)
    all_matches: list[str] = field(default_factory=list)
    raw: str = ""

    def is_one_of(self, *names: str) -> bool:
        return self.name in names

    def has(self, *names: str) -> bool:
        return self.name in names


def _find_rating(text: str) -> int | None:
    """Sirf saaf rating: '5 star', '4 stars', '3/5' — '4 logo' ko rating nahi samajhna."""
    m = re.search(r"\b([1-5])\s*(?:star|stars|/\s*5|out of 5)\b", text.lower())
    if m:
        return int(m.group(1))
    m = re.fullmatch(r"\s*([1-5])\s*", text)
    if m:
        return int(m.group(1))
    return None


def _find_persons(text: str) -> int | None:
    low = text.lower()
    m = re.search(r"(\d+)\s*(?:log|logo|people|person|persons|banda|bande|admi|aadmi|guest)", low)
    if m:
        return int(m.group(1))
    m = re.search(r"(\d+)\s*(?:ki|ke)\s*(?:table|seat)", low)
    if m:
        return int(m.group(1))
    for word, value in NUM_WORDS.items():
        if re.search(rf"\b{word}\s*(log|logo|people|person|banda|bande|aadmi)\b", low):
            return value
    return None


def _find_time(text: str) -> str | None:
    low = text.lower()
    m = re.search(r"\b(\d{1,2})[:.](\d{2})\s*(am|pm)?\b", low)
    if m:
        hour, minute, mer = int(m.group(1)), m.group(2), m.group(3)
        if mer == "pm" and hour < 12:
            hour += 12
        if mer == "am" and hour == 12:
            hour = 0
        if not mer and 1 <= hour <= 9:  # "7 baje" = shaam 7
            hour += 12
        return f"{hour:02d}:{minute}"
    is_pm = bool(re.search(r"\b(pm|shaam|sham|evening|raat|night)\b", low))
    is_am = bool(re.search(r"\b(am|subah|subha|morning)\b", low))
    m = re.search(r"\b(\d{1,2})\s*(?:baje|bje|pm|am|o.?clock)\b", low)
    if m:
        hour = int(m.group(1))
        if is_pm and hour < 12:
            hour += 12
        elif not is_am and not is_pm and 1 <= hour <= 9:
            hour += 12  # "7 baje" ka matlab India me shaam 7
        return f"{hour:02d}:00"
    for word, value in NUM_WORDS.items():
        if re.search(rf"\b{word}\s*(baje|bje)\b", low):
            hour = value if value >= 10 else value + 12
            return f"{hour:02d}:00"
    return None


def _find_date(text: str) -> str | None:
    from datetime import timedelta

    from .utils import today_ist_date

    low = text.lower()
    today = today_ist_date()
    if "parso" in low:
        return str(today + timedelta(days=2))
    if "kal" in low:
        return str(today + timedelta(days=1))
    if "aaj" in low or "today" in low or "tonight" in low:
        return str(today)
    m = re.search(r"\b(\d{1,2})\s*(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\b", low)
    if m:
        day = int(m.group(1))
        month_word = re.search(r"\b(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*", low).group(0)
        month = MONTHS.get(month_word[:3], "01")
        year = today.year if (int(month) >= today.month) else today.year + 1
        return f"{year}-{month}-{day:02d}"
    m = re.search(r"\b(\d{1,2})[/-](\d{1,2})(?:[/-](\d{2,4}))?\b", low)
    if m:
        day, month = int(m.group(1)), int(m.group(2))
        if 1 <= day <= 31 and 1 <= month <= 12:
            year = today.year if month >= today.month else today.year + 1
            return f"{year}-{month:02d}-{day:02d}"
    return None


def _find_birthday(text: str) -> str | None:
    """'mera birthday 15 March hai' -> '03-15'."""
    low = text.lower()
    if "birthday" not in low:
        return None
    m = re.search(r"\b(\d{1,2})\s*(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\b", low)
    if m:
        return f"{MONTHS[m.group(2)[:3]]}-{int(m.group(1)):02d}"
    m = re.search(r"\b(\d{1,2})[/-](\d{1,2})\b", low)
    if m and 1 <= int(m.group(1)) <= 31 and 1 <= int(m.group(2)) <= 12:
        return f"{int(m.group(2)):02d}-{int(m.group(1)):02d}"
    return None


def _find_name(text: str) -> str | None:
    """'mera naam Rahul hai' / 'main Rahul' / 'my name is Rahul'."""
    patterns = [
        r"mera naam\s+([A-Za-z\u0900-\u097F][\w\u0900-\u097F]*(?:\s+[A-Za-z\u0900-\u097F][\w\u0900-\u097F]*)?)",
        r"my name is\s+([A-Za-z][\w]*(?:\s+[A-Za-z][\w]*)?)",
        r"\bnaam\s+([A-Za-z\u0900-\u097F][\w\u0900-\u097F]*(?:\s+[A-Za-z\u0900-\u097F][\w\u0900-\u097F]*)?)\s*(?:hai|h)\b",
        r"^\s*(?:main|mai|me|i am|this is)\s+([A-Za-z][\w]*(?:\s+[A-Za-z][\w]*)?)\s*$",
    ]
    for pattern in patterns:
        m = re.search(pattern, text, flags=re.IGNORECASE)
        if m:
            candidate = m.group(1).strip()
            if candidate.lower() in {"hai", "h", "hoon", "hu", "the", "a", "not", "nahi"}:
                continue
            return candidate
    return None


def detect(text: str, has_pending_bill: bool = False, awaiting_feedback: bool = False, last_intent: str | None = None) -> Intent:
    """Message se intent nikaalo. `entities` me naam, rating, time, date, birthday aa jate hain."""
    raw = text or ""
    low = raw.lower().strip()
    intent = Intent(raw=raw)
    entity_text = raw

    # ---- pehle rating (sirf number aya ho aur feedback ka intezaar ho) ----
    if awaiting_feedback and re.fullmatch(r"\s*[1-5]\s*", low):
        intent.name = "feedback_rating"
        intent.confidence = 0.95
        intent.entities["rating"] = int(low.strip())
        return intent

    matches: list[tuple[int, str]] = []
    for idx, (name, patterns) in enumerate(INTENT_PATTERNS):
        for pattern in patterns:
            try:
                if re.search(pattern, low, flags=re.IGNORECASE | re.MULTILINE):
                    matches.append((idx, name))
                    break
            except re.error:
                continue
    for idx, name in matches:
        intent.all_matches.append(name)
    if matches:
        best_idx, best_name = min(matches, key=lambda row: row[0])
        intent.name = best_name
        intent.confidence = 0.9 if len(matches) == 1 else 0.75

    # ---- entities ----
    name = _find_name(entity_text)
    if name:
        intent.entities["name"] = name
    if intent.name == "name_provided" and name:
        intent.confidence = 0.9
    birthday = _find_birthday(entity_text)
    if birthday:
        intent.entities["birthday"] = birthday
        if intent.name in {"unknown", "name_provided"}:
            intent.name = "birthday_set"
    rating = _find_rating(entity_text)
    if rating is not None:
        intent.entities["rating"] = rating
        if intent.name in {"unknown", "feedback_positive"} and awaiting_feedback:
            intent.name = "feedback_rating"
    persons = _find_persons(entity_text)
    if persons:
        intent.entities["persons"] = persons
    time_str = _find_time(entity_text)
    if time_str:
        intent.entities["time"] = time_str
    date_str = _find_date(entity_text)
    if date_str:
        intent.entities["date"] = date_str
    if intent.name in {"reservation", "reservation_cancel"}:
        if persons or time_str:
            intent.name = "reservation"
            intent.confidence = 0.9
    if "pay" in intent.all_matches or entity_text.lower().strip() in {"paise bhej diye", "pay kar diya", "paid", "done payment"}:
        intent.entities["paid_claim"] = True

    # ---- pending bill ke time "haan / ok / kar do" = confirm ----
    if has_pending_bill and re.search(r"\b(haan|han|yes|ok|okay|theek|thik|kar do|kardo|confirm|bhej|send|karo)\b", low):
        if intent.name in {"unknown", "greeting", "menu"}:
            intent.name = "confirm_order"
            intent.confidence = 0.85

    # ---- feedback ka intewaar + shukriya waale shabd = comment ----
    if awaiting_feedback and intent.name in {"unknown", "feedback_positive"} and len(low) > 3:
        intent.name = "feedback_comment"
        intent.confidence = 0.6

    # ---- order detect: menu ka item + qty/order word ----
    if intent.name in {"unknown", "greeting", "special"} and _looks_like_order(low):
        intent.name = "order"
        intent.confidence = 0.7
        if last_intent == "menu":
            intent.confidence = 0.85

    if intent.name == "unknown" and low:
        intent.confidence = 0.2
    return intent


def _looks_like_order(low: str) -> bool:
    words = set(re.findall(r"[a-z]+", low))
    if words & _ORDER_WORDS and len(low) <= 120:
        return True
    if re.search(r"\b\d{1,2}\s*(x|×|\*)\s*[a-z]", low):
        return True
    return False


def is_stop_command(text: str) -> bool:
    return bool(re.search(r"\b(stop|unsubscribe)\b", (text or "").lower()))


def is_start_command(text: str) -> bool:
    return bool(re.search(r"^\s*start\s*$", (text or "").lower()))

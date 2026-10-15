"""Menu engine — digital menu, price nikaalna aur chat se order padhna.

**Golden Rule (report Section 3):** Price aur item ka faisla hamesha is file se
hoga, AI se nahi. AI sirf baat banata hai.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import MenuItem
from .utils import money, rupees

# --------------------------------------------------------------------------
# Sharma Cafe ka starter menu (dashboard se badal sakte ho)
# --------------------------------------------------------------------------
DEFAULT_MENU: list[dict] = [
    # --- Chaat & Starters ---
    dict(name="Paneer Tikka", price=260, category="Starters", is_veg=True, is_signature=True,
         aliases=["paneer tikka", "tikka", "paneer tika"], description="Tandoor me sekha hua, dhuandaar!"),
    dict(name="Veg Spring Roll", price=180, category="Starters", is_veg=True, aliases=["spring roll", "roll"]),
    dict(name="Chilli Paneer", price=240, category="Starters", is_veg=True, aliases=["chilli paneer", "chili paneer"]),
    dict(name="Chicken Tikka", price=320, category="Starters", is_veg=False, aliases=["chicken tikka"], description="Juicy, dhungar 1 number"),
    dict(name="Masala Papad", price=80, category="Starters", is_veg=True, aliases=["papad", "masala papad"]),
    dict(name="French Fries", price=150, category="Starters", is_veg=True, aliases=["fries", "french fries"]),

    # --- Main Course (Veg) ---
    dict(name="Paneer Butter Masala", price=280, category="Main Course", is_veg=True, is_signature=True,
         aliases=["pbm", "paneer butter masala", "paneer masala", "paneer butter"], description="Makkhan wali gravy, best seller"),
    dict(name="Dal Makhani", price=220, category="Main Course", is_veg=True, aliases=["dal makhani", "dal makhni", "daal makhani"]),
    dict(name="Mix Veg", price=200, category="Main Course", is_veg=True, aliases=["mix veg", "mix vegetable"]),
    dict(name="Dal Tadka", price=180, category="Main Course", is_veg=True, aliases=["dal tadka", "daal tadka", "dal fry"]),
    dict(name="Kadhai Paneer", price=270, category="Main Course", is_veg=True, aliases=["kadhai paneer", "kadai paneer"]),
    dict(name="Malai Kofta", price=260, category="Main Course", is_veg=True, aliases=["malai kofta", "kofta"]),

    # --- Main Course (Non-Veg) ---
    dict(name="Butter Chicken", price=340, category="Main Course", is_veg=False, is_signature=True,
         aliases=["butter chicken", "bc", "murgh makhani"], description="Gravy me doob ke, rumali ke saath"),
    dict(name="Chicken Curry", price=300, category="Main Course", is_veg=False, aliases=["chicken curry", "chicken"]),
    dict(name="Mutton Rogan Josh", price=420, category="Main Course", is_veg=False, aliases=["mutton", "rogan josh", "mutton curry"]),
    dict(name="Egg Curry", price=220, category="Main Course", is_veg=False, aliases=["egg curry", "anda curry", "egg"]),

    # --- Breads & Rice ---
    dict(name="Butter Naan", price=50, category="Breads & Rice", is_veg=True, aliases=["butter naan", "naan", "nan"]),
    dict(name="Tandoori Roti", price=25, category="Breads & Rice", is_veg=True, aliases=["tandoori roti", "roti"]),
    dict(name="Laccha Paratha", price=60, category="Breads & Rice", is_veg=True, aliases=["laccha paratha", "paratha", "lachha parantha"]),
    dict(name="Garlic Naan", price=70, category="Breads & Rice", is_veg=True, aliases=["garlic naan"]),
    dict(name="Jeera Rice", price=160, category="Breads & Rice", is_veg=True, aliases=["jeera rice", "rice", "chawal"]),
    dict(name="Veg Biryani", price=240, category="Breads & Rice", is_veg=True, aliases=["veg biryani", "biryani"]),
    dict(name="Chicken Biryani", price=320, category="Breads & Rice", is_veg=False, aliases=["chicken biryani", "non veg biryani"]),

    # --- Chinese ---
    dict(name="Veg Manchurian Dry", price=210, category="Chinese", is_veg=True, aliases=["manchurian", "veg manchurian"]),
    dict(name="Veg Hakka Noodles", price=190, category="Chinese", is_veg=True, aliases=["hakka noodles", "noodles", "chowmein"]),
    dict(name="Chicken Fried Rice", price=250, category="Chinese", is_veg=False, aliases=["chicken fried rice", "fried rice"]),

    # --- Pizza & Burger ---
    dict(name="Margherita Pizza", price=250, category="Pizza & Burger", is_veg=True, aliases=["margherita", "margarita", "pizza"]),
    dict(name="Farmhouse Pizza", price=340, category="Pizza & Burger", is_veg=True, aliases=["farmhouse pizza", "farmhouse"]),
    dict(name="Veg Burger", price=120, category="Pizza & Burger", is_veg=True, aliases=["burger", "veg burger"]),
    dict(name="Chicken Burger", price=160, category="Pizza & Burger", is_veg=False, aliases=["chicken burger"]),

    # --- South Indian ---
    dict(name="Masala Dosa", price=140, category="South Indian", is_veg=True, aliases=["dosa", "masala dosa", "dosai"]),
    dict(name="Idli Sambar", price=110, category="South Indian", is_veg=True, aliases=["idli", "idli sambar"]),
    dict(name="Uttapam", price=150, category="South Indian", is_veg=True, aliases=["uttapam", "utthapam"]),

    # --- Breakfast ---
    dict(name="Aloo Paratha", price=120, category="Breakfast", is_veg=True, aliases=["aloo paratha", "aloo parantha"]),
    dict(name="Poha", price=70, category="Breakfast", is_veg=True, aliases=["poha", "pohe"]),
    dict(name="Chole Bhature", price=160, category="Breakfast", is_veg=True, aliases=["chole bhature", "chole", "bhature"]),

    # --- Coffee & Beverages ---
    dict(name="Cold Coffee", price=180, category="Coffee & Beverages", is_veg=True, is_signature=True,
         aliases=["cold coffee", "coffee", "cold cofee"], description="Thick, creamy, sar-dard bhaga de"),
    dict(name="Filter Coffee", price=90, category="Coffee & Beverages", is_veg=True, aliases=["filter coffee", "hot coffee"]),
    dict(name="Cappuccino", price=160, category="Coffee & Beverages", is_veg=True, aliases=["cappuccino", "capuccino"]),
    dict(name="Masala Chai", price=40, category="Coffee & Beverages", is_veg=True, aliases=["chai", "tea", "masala tea"]),
    dict(name="Sweet Lassi", price=120, category="Coffee & Beverages", is_veg=True, aliases=["lassi", "sweet lassi"]),
    dict(name="Fresh Lime Soda", price=100, category="Coffee & Beverages", is_veg=True, aliases=["lime soda", "nimbu soda", "lime water"]),
    dict(name="Chocolate Shake", price=200, category="Coffee & Beverages", is_veg=True, aliases=["chocolate shake", "shake"]),

    # --- Desserts ---
    dict(name="Gulab Jamun", price=90, category="Desserts", is_veg=True, aliases=["gulab jamun", "jamun"]),
    dict(name="Choco Lava Cake", price=180, category="Desserts", is_veg=True, aliases=["lava cake", "choco lava", "cake"]),
    dict(name="Rasmalai", price=140, category="Desserts", is_veg=True, aliases=["rasmalai", "ras malai"]),
    dict(name="Vanilla Ice Cream", price=110, category="Desserts", is_veg=True, aliases=["ice cream", "vanilla"]),

    # --- Combos ---
    dict(name="Meal for 2 (Dal Makhani + PBM + 4 Naan + 2 Lassi)", price=749, category="Combos", is_veg=True,
         is_signature=True, aliases=["meal for 2", "combo", "family combo", "meal for two"]),
    dict(name="Chai + Samosa Combo", price=90, category="Combos", is_veg=True, aliases=["chai samosa", "samosa combo"]),
]
DEFAULT_MENU.append(dict(name="Samosa (2 pc)", price=60, category="Starters", is_veg=True, aliases=["samosa"]))

FREEBIE_CANDIDATES = ["Gulab Jamun", "Vanilla Ice Cream", "Cold Coffee", "Sweet Lassi", "Choco Lava Cake"]

WORD_QTY = {
    "ek": 1, "one": 1, "a": 1,
    "do": 2, "two": 2, "dono": 2,
    "teen": 3, "tin": 3, "three": 3,
    "char": 4, "chaar": 4, "four": 4, "for": 4,
    "paanch": 5, "panch": 5, "five": 5,
    "chhe": 6, "che": 6, "six": 6,
    "saat": 7, "seven": 7,
    "aath": 8, "eight": 8,
    "nau": 9, "nine": 9,
    "das": 10, "ten": 10,
    "aadha": 0.5, "half": 0.5,
}


def normalize(text: str) -> str:
    text = (text or "").lower()
    text = re.sub(r"[^a-z0-9\s]", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def ensure_menu(db: Session, force: bool = False) -> int:
    """Menu khaali ho to default menu daal do. Return: kitne item naye."""
    existing = db.scalar(select(MenuItem).limit(1))
    if existing and not force:
        return 0
    added = 0
    for row in DEFAULT_MENU:
        name = row["name"]
        if db.scalar(select(MenuItem).where(MenuItem.name == name)):
            continue
        db.add(MenuItem(**{**row, "aliases": row.get("aliases", [])}))
        added += 1
    db.flush()
    return added


def available_items(db: Session) -> list[MenuItem]:
    return list(db.scalars(select(MenuItem).where(MenuItem.is_available.is_(True)).order_by(MenuItem.category, MenuItem.name)))


def find_item(db: Session, query: str) -> MenuItem | None:
    """Naam ya alias se item dhundo (fuzzy thoda sa)."""
    q = normalize(query)
    if not q:
        return None
    items = available_items(db)
    # 1) poora naam/alias match
    for item in items:
        names = [normalize(item.name)] + [normalize(a) for a in (item.aliases or [])]
        if q in names:
            return item
    # 2) query ke andar item ka naam
    best, best_len = None, 0
    for item in items:
        for cand in [normalize(item.name)] + [normalize(a) for a in (item.aliases or [])]:
            if cand and cand in q and len(cand) > best_len:
                best, best_len = item, len(cand)
    if best:
        return best
    # 3) item ke naam me query
    for item in items:
        for cand in [normalize(item.name)] + [normalize(a) for a in (item.aliases or [])]:
            if q in cand and len(q) >= 4:
                return item
    return None


def menu_text(db: Session, category: str | None = None) -> str:
    """WhatsApp par bhejne layak menu (Hinglish, emoji ke saath)."""
    items = available_items(db)
    if category:
        items = [i for i in items if i.category.lower() == category.lower()]
    if not items:
        return "Menu abhi update ho raha hai sir, 2 minute me bhejta hoon!"

    lines = ["*Aaj ka Menu* 📖", ""]
    current = None
    for item in items:
        if item.category != current:
            current = item.category
            lines.append(f"*— {current} —*")
        veg = "🟢" if item.is_veg else "🔴"
        star = " ⭐" if item.is_signature else ""
        lines.append(f"{veg} {item.name} — {rupees(item.price)}{star}")
    lines.append("")
    lines.append("Order type kar dijiye — jaise *2 paneer butter masala, 4 butter naan* 🙂")
    return "\n".join(lines)


def menu_categories(db: Session) -> list[str]:
    return sorted({i.category for i in available_items(db)})


def signature_items(db: Session, limit: int = 3) -> list[MenuItem]:
    items = [i for i in available_items(db) if i.is_signature]
    return items[:limit]


def most_sold(db: Session, limit: int = 3) -> list[MenuItem]:
    items = sorted(available_items(db), key=lambda i: i.sold_count, reverse=True)
    return [i for i in items if i.sold_count > 0][:limit] or items[:limit]


# --------------------------------------------------------------------------
# Chat se order padhna
# --------------------------------------------------------------------------
@dataclass
class ParsedLine:
    menu_item_id: int | None
    name: str
    qty: int
    unit_price: float
    matched: bool
    raw: str = ""

    @property
    def line_total(self) -> float:
        return money(self.unit_price * self.qty)


@dataclass
class ParsedOrder:
    lines: list[ParsedLine] = field(default_factory=list)
    unmatched: list[str] = field(default_factory=list)

    @property
    def has_items(self) -> bool:
        return any(line.matched for line in self.lines)

    @property
    def subtotal(self) -> float:
        return money(sum(line.line_total for line in self.lines if line.matched))


def _split_segments(text: str) -> list[str]:
    text = re.sub(r"\band\b|\baur\b|\bplus\b|\+", ",", text, flags=re.IGNORECASE)
    text = text.replace("।", ",").replace("\n", ",")
    parts = [p.strip(" .-") for p in re.split(r"[,;]+", text)]
    # "2 paneer butter masala" jaise segment ko aage tod do (qty + item)
    return [p for p in parts if p]


def _extract_qty(segment: str) -> tuple[int, str]:
    """Segment se quantity nikaalo: '2 x naan', 'do naan', 'naan 2'."""
    s = segment.strip()
    m = re.match(r"^(\d+)\s*[xX×*]?\s+(.*)$", s)
    if m:
        return int(m.group(1)), m.group(2)
    m = re.match(r"^([xX×*])\s*(\d+)\s+(.*)$", s)
    if m:
        return int(m.group(2)), m.group(3)
    m = re.match(r"^(.*?)\s+[xX×*]\s*(\d+)$", s)
    if m:
        return int(m.group(2)), m.group(1)
    parts = s.split()
    if len(parts) >= 2:
        first = parts[0].lower().rstrip(".")
        if first in WORD_QTY:
            qty = int(WORD_QTY[first]) or 1
            return max(qty, 1), " ".join(parts[1:])
    m = re.match(r"^(.*?)\s+(\d+)$", s)
    if m and not re.search(r"\d", m.group(1)):
        return int(m.group(2)), m.group(1)
    return 1, s


def parse_order_text(db: Session, text: str) -> ParsedOrder:
    """Free text se order banao. Jo item na mile wo `unmatched` me jayega."""
    result = ParsedOrder()
    for segment in _split_segments(text):
        if len(segment) < 2:
            continue
        qty, rest = _extract_qty(segment)
        if not rest:
            continue
        item = find_item(db, rest)
        if item is None:
            # "2 butter naan extra cheese" type me se sabse lambe match ki koshish
            words = rest.split()
            found = None
            for size in range(len(words), 0, -1):
                probe = " ".join(words[:size])
                if len(probe) < 4:
                    continue
                item = find_item(db, probe)
                if item:
                    found = (item, size)
                    break
            if found:
                item, size = found
            else:
                result.unmatched.append(segment)
                continue
        result.lines.append(
            ParsedLine(
                menu_item_id=item.id,
                name=item.name,
                qty=max(1, int(qty)),
                unit_price=item.price,
                matched=True,
                raw=segment,
            )
        )
    return result


REPEAT_WORDS = ["wahi", "wohi", "same", "repeat", "phir se", "pichla", "pichhla", "last order", "pehle wala", "purana order"]


def wants_repeat(text: str) -> bool:
    low = normalize(text)
    return any(w in low for w in REPEAT_WORDS)


def order_from_last(db: Session, last_items: list | None) -> ParsedOrder:
    """'Wahi wala kar do' — pichle order ko dobara banao (aaj ke price par)."""
    result = ParsedOrder()
    for row in last_items or []:
        name = row.get("name") if isinstance(row, dict) else str(row)
        qty = int(row.get("qty", 1)) if isinstance(row, dict) else 1
        item = find_item(db, name or "")
        if item:
            result.lines.append(ParsedLine(item.id, item.name, qty, item.price, True, raw=name))
        elif name:
            result.unmatched.append(name)
    return result


def order_summary_text(lines: list[ParsedLine] | list[dict]) -> str:
    """'2 x Paneer Butter Masala, 4 x Butter Naan'."""
    chunks = []
    for line in lines:
        if isinstance(line, dict):
            chunks.append(f"{line.get('qty', 1)} x {line.get('name', '')}")
        else:
            chunks.append(f"{line.qty} x {line.name}")
    return ", ".join(chunks)


def free_item_suggestion(db: Session, veg_only: bool = False) -> MenuItem | None:
    """Dessert/coffee me se freebie ke liye ek item."""
    for name in FREEBIE_CANDIDATES:
        item = find_item(db, name)
        if item and (not veg_only or item.is_veg):
            return item
    return None

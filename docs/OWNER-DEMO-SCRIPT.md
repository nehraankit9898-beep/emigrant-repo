# OWNER DEMO SCRIPT — cafe wale ko 12 minute me convince kaise karein

> Report ka Section 19 (business plan) + ye script = pehla paying customer.
> Rule: **zubaan se nahi, dikha ke becho.** Laptop le jao, dashboard kholo, unke saamne chal ke dikhao.

---

## 0. Pehle taiyaari (ghar par, 10 minute)

```bash
python -m scripts.demo_chat --reset            # terminal me kya hota hai wo dekh lo
uvicorn app.main:app --host 0.0.0.0 --port 8000
```
Dashboard me **Menu tab** me unke cafe ka asli menu daal do (5-10 items kaafi hain),
**Settings** me restaurant ka naam, aur **Offers** me unke hisaab se discount rules.
Pehle se done ho to demo me "hamara system aapke naam se hi bana hai" wala feel aata hai.

---

## 1. Opening (60 second, mood banao)

> "Sir, aap Zomato par har order par 25-30% dete ho. Main aapko aapka **khud ka WhatsApp waiter** deta hoon —
> commission zero, customer aapka, aur wo aapke customers ko **naam se yaad** rakhta hai.
> 5 minute me apne phone se dekh lo, mujhe kuch bolna hi nahi padega."

Owner apne phone se WhatsApp karega — **bas yahi sabse bada moment hai.**

---

## 2. Live demo — 5 step (order bhi wahi karo jo unka best-seller hai)

| # | Owner karega | Kya hoga | Kya bolna hai |
|---|---|---|---|
| 1 | "Hi" bhejega | "Namaste! Sharma Cafe me swagat..." | "Ye response 2 second me aaya — staff busy ho ya raat 1 baje, yahi milega" |
| 2 | "2 [best-seller], 4 naan" | Bill banega — pehli baar 10% OFF, UPI link | "Pehla order par WELCOME10 — ab ye code sirf ek baar chalta hai, koi jugaad nahi" |
| 3 | Link kholke pay karega | Thanks message + agla code + 88 loyalty points | "Payment ka confirmation aur marketing message, dono automatic" |
| 4 | Phir "Hi" bolega | "12 din baad darshan diye! Pichli baar wala hi karun?" | "Dekhiye — usne aapko yaad kar liya, aur aapki pasand bhi" |
| 5 | Dashboard kholo → Overview | Aaj ki sale, order, top item | "Raat 11 baje ye poori report aapke WhatsApp par aa jaayegi" |

Agar wo non-technical hai to sirf ye 3 cheezein dikao: **naam se yaad karna, discount rule, payment + thanks.**

---

## 3. "Bhai, isme kitna kharcha?" (seedha jawab)

| Cheez | Kitna |
|---|---|
| Setup (menu, dashboard, testing) | ₹9,999 – ₹24,999 (ek baar) |
| Mahine ki fees | ₹1,999 – ₹4,999 |
| Meta ke message fees | ~₹0.13–0.86 per message (marketing) — chat ke jawab 24 ghante window me free |
| AI | ₹500 – ₹2,000 / mahina (ya free tier me ₹0) |
| Payment gateway | ~2% per order |

> "Sir, ek mahine me 40 order bhi WhatsApp par shift ho gaye to 25% commission bach gaya.
> Baaki sab uske upar."

---

## 4. Uski 4 common objections (aur taiyaar jawab)

1. **"Mera staff already WhatsApp par reply karta hai."**
   → "Bilkul, 10 baje se pehle? Raat 11 baje bhi? Le aaye sir, ek order miss hone ka matlab hai — ye miss nahi karta.
   Aur aapka staff **sirf** unhi chats me jaata hai jahan insaan chahiye (complaint/handover)."

2. **"Number band ho jayega?"**
   → "Sir main spam nahi karta. Offer sirf unhi ko jaata hai jo pehle bola ho 'haan bhejo' — har message me STOP ka option hai.
   Roz ki limit bhi set hai. Rule todne par number band hota hai, rule maan ne par nahi."

3. **"Customer ko robot wala feel hoga."**
   → "Isliye ye Hinglish me baat karta hai, mazak bhi karta hai — par price aur discount ke maamle me ise kuch bolne ki
   permission hi nahi hai. Number sirf aapke menu/discount rule se aate hain, isliye galti ka chance zero."

4. **"Baad me dekhte hain."**
   → "Ek hafta free trial lagwa deta hoon — apka number, apka menu, mera kaam. Ek bhi order aaya to baat karenge,
   warna main khud hat jaunga."

---

## 5. Free trial → Paid (7 din ka plan)

| Din | Tum karo | Owner dekhe kya |
|---|---|---|
| 1 | Number + menu + rules set, apne phone se testing | Uske menu ka agent ready |
| 2 | Owner ko dashboard ka link + aaj ki report WhatsApp par | "Sale itni hui, top item ye raha" |
| 3 | 2-3 customers ko discount code (jinke wo jaante hain) | Naya order + repeat order |
| 4 | Feedback form chalu (Google review wala message) | Google par naya review |
| 5 | Birthday/winback campaign chalao | Purana customer wapas aaya |
| 6 | Complaint alert ka demo (khud ek banake dikhao) | "Problem owner se pehle pata chal gayi" |
| 7 | Hisaab: kitne order, kitni sale, kitne repeat | **Paisa bolo** |

**Closing line:**
> "Sir, is hafte agent ne X order liye aur Y repeat customer wapas laaye. Aap bas month end ka ek order Zomato par
> chhod dena — utne me mera poora mahina chal jayega. Chalu karein?"

---

## 6. Ye script kis repo-kaam par tikti hai

| Demo me tum jo dikhaoge | Code kahan hai |
|---|---|
| Naam se yaad, "12 din baad darshan diye" | `app/memory.py` + `app/llm.py` (demo brain) |
| Bill + 10% welcome + ek code ek baar | `app/pricing.py`, `app/discounts.py` |
| Payment link → thanks + agla code | `app/payments.py`, `app/orchestrator.py` |
| Birthday / winback / broadcast | `app/automations.py` |
| Owner report / dashboard | `app/reports.py`, `app/static/dashboard.html` |
| Complaint → owner alert, insaan ko handover | `app/orchestrator.py` (alerts + human_mode) |

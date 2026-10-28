# AttendSmart — Attendance & Grade Planner

Futuristic, dark-themed Django web application for college students to track attendance thresholds, simulate completion risk via Monte Carlo, and predict required external exam marks.

## Setup & Run

```bash
# 1. Install dependencies
pip install -r requirements.txt

# 2. Run migrations & seed demo account
python manage.py migrate
python manage.py seed_demo

# 3. Start development server
python manage.py runserver
```
Visit `http://127.0.0.1:8000/`. Demo login: `demo@plannerapp.com` / `Demo@1234`.

## Testing

Run the full automated test suite (76 tests):
```bash
python manage.py test
```

## How Calculations Work

### 1. Attendance Logic (`core/services/attendance.py`)
- **Remaining classes:** $R = T - H$, where $T$ is total planned and $H$ is held so far.
- **Required attendance:** $\text{req} = \lceil \frac{\text{threshold} \times T}{100} \rceil$ using exact integer ceiling division.
- **Must attend:** $\max(0, \text{req} - A)$ where $A$ is classes attended.
- **Safe skips:** $\max(0, R - \text{must\_attend})$.
- **Status:**
  - `detention_zone`: if $\text{must\_attend} > R$.
  - `warning`: if $\text{safe\_skips} \le 2$ or $A \times 100 < \text{threshold} \times H$.
  - `safe`: otherwise.
- **What-if slider:** Skipping $k$ remaining classes yields final best-possible $\frac{A + R - k}{T} \times 100$ and momentary $\frac{A}{H + k} \times 100$.

### 2. Risk Simulation (`core/services/risk.py`)
- **Habit rate ($p$):** Laplace-smoothed attendance rate $p = \frac{A + 1}{H + 2}$.
- **Analytic probability:** Exact binomial survival probability $\sum_{k=\text{must}}^{R} \binom{R}{k} p^k (1-p)^{R-k}$.
- **Monte Carlo:** 5,000 seeded runs generating distribution histograms and completion risk labels (Low $\ge 80\%$, Medium $50\text{--}79\%$, High $< 50\%$).

### 3. Grade Predictor (`core/services/marks.py`)
- External paper (out of 75) scales to 40 via $\text{external} \times \frac{40}{75}$.
- Minimum external needed for target grade $M$: $\lceil (2M - 1 - 2 \times \text{internal}) \times \frac{15}{16} \rceil$.
- Final score rounds half-up once at the end: $\lfloor \text{internal} + \frac{\text{external} \times 40}{75} + 0.5 \rfloor$.
- Highlights highest grade with $0 < \text{needed} \le 60$ (fallback to easiest reachable). Fail warning flagged when $\text{internal} \le 9$.

### 4. Automatic Class Counting & Schedule Extraction (`core/services/calendar_count.py` & `core/services/extract.py`)
- **Calendar Range & Weekends:** Start and last working day are inclusive. Weekends (Saturdays and Sundays) are excluded unless explicitly overridden.
- **Holidays:** Fixed national holidays (26 Jan, 15 Aug, 2 Oct) within the range are prefilled. Holidays falling on weekends are counted once and never double-subtracted.
- **Schedule Modes:**
  - *Weekday Mode:* Class periods (e.g. 1 for lecture, 2 or 3 for lab) are mapped to weekdays (Mon=0..Sun=6).
  - *Day Order Mode:* Working days sequentially cycle through day orders 1–5, advancing only on active instructional days.
- **Held vs Total:**
  - $T$ (Total): Sum of periods scheduled across all working days from start date to last working day.
  - $H$ (Held): Sum of periods scheduled strictly on dates before today (calculated in Indian Standard Time, UTC+5:30; today's classes count after the day concludes).
  - Cancelled or extra lectures are adjusted via `Subject.held_adjustment` ($H_{\text{adj}} = \max(0, H + \text{held\_adjustment})$).
- **Photo Upload & Privacy:** Timetable and holiday circular images or PDFs are processed via Google Gemini Vision API to extract structured schedule data. Uploaded files (max 5 MB) are discarded immediately after in-memory parsing. Note that document images are sent to an external LLM API; students may also choose manual entry without uploading images.


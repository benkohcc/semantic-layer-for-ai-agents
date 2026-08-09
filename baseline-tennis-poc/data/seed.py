"""Deterministic sample data generator for Baseline Tennis Co.

Creates tennis_store.db, the marketing document corpus, and benchmarks.yaml.
Every planted signal and every deliberate gap is asserted at the end: if an
assertion fails, seeding fails loudly rather than shipping silently broken data.

Run: python data/seed.py
"""

from __future__ import annotations

import calendar
import os
import random
import sqlite3
import sys
from collections import defaultdict
from datetime import date, timedelta

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

DB_PATH = os.path.join(HERE, "tennis_store.db")
DOCS_DIR = os.path.join(HERE, "documents")
BENCH_PATH = os.path.join(
    ROOT, "semantic-layer", "domains", "marketing", "benchmarks", "benchmarks.yaml"
)

SEED = 42
N_CUSTOMERS = 18_000
MONTHS = 24

SEGMENTS = ["competitive", "recreational"]
REGIONS = ["northeast", "southeast", "midwest", "west"]
ACQ_CHANNELS = ["organic", "paid_search", "paid_social", "email", "referral"]
ORDER_CHANNELS = ["web", "email", "paid_search", "paid_social", "wholesale"]
CATEGORIES = ["rackets", "strings", "shoes", "apparel", "services"]

rng = random.Random(SEED)


# ---------------------------------------------------------------- calendar utils


def month_start(d: date) -> date:
    return date(d.year, d.month, 1)


def add_months(d: date, n: int) -> date:
    total = (d.year * 12 + (d.month - 1)) + n
    y, m = divmod(total, 12)
    return date(y, m + 1, 1)


def month_end(d: date) -> date:
    return date(d.year, d.month, calendar.monthrange(d.year, d.month)[1])


def build_month_windows(today: date) -> list[tuple[date, date]]:
    """24 complete months ending with the last complete month before today."""
    last_complete = add_months(month_start(today), -1)
    first = add_months(last_complete, -(MONTHS - 1))
    return [
        (add_months(first, i), month_end(add_months(first, i))) for i in range(MONTHS)
    ]


def rand_day(start: date, end: date) -> date:
    return start + timedelta(days=rng.randint(0, (end - start).days))


TODAY = date.today()
WINDOWS = build_month_windows(TODAY)
FIRST_MONTH, _ = WINDOWS[0]
LAST_MONTH_START, LAST_MONTH_END = WINDOWS[-1]
DATA_START = FIRST_MONTH
DATA_END = LAST_MONTH_END

# Month 7 of 24 is where paid_social spend tracking begins (planted gap).
PAID_SOCIAL_START = WINDOWS[6][0]

# Referral chains stop being seeded two months before the window ends. Chains
# grown right up to the boundary would bunch on the final month and swamp the
# planted paid_search signup drop that question 3 must diagnose.
REFERRAL_CUTOFF = WINDOWS[-2][0]

# The documented paid search budget pause: 12 days inside the last complete
# month. Shared by the customer generator and the ad_spend generator so the
# planted drop appears in both, and by the generated Q3 media plan document so
# the dates in the prose match the dates in the data.
PAUSE_START = LAST_MONTH_START + timedelta(days=7)
PAUSE_END = PAUSE_START + timedelta(days=11)  # 12 days inclusive

# Seasonality multipliers: spring leagues lift Mar-May, December dips.
SEASON = {
    1: 0.92, 2: 0.97, 3: 1.22, 4: 1.28, 5: 1.18, 6: 1.02,
    7: 0.98, 8: 1.00, 9: 1.04, 10: 1.02, 11: 1.06, 12: 0.78,
}


def season(d: date) -> float:
    return SEASON[d.month]


# ---------------------------------------------------------------- schema

SCHEMA = """
DROP TABLE IF EXISTS customers;
DROP TABLE IF EXISTS orders;
DROP TABLE IF EXISTS products;
DROP TABLE IF EXISTS order_items;
DROP TABLE IF EXISTS email_sends;
DROP TABLE IF EXISTS campaigns;
DROP TABLE IF EXISTS ad_spend;

CREATE TABLE customers (
    id INTEGER PRIMARY KEY,
    segment TEXT NOT NULL,
    region TEXT NOT NULL,
    signup_date TEXT NOT NULL,
    acquisition_channel TEXT NOT NULL,
    referred_by INTEGER
);
CREATE TABLE suppliers (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    country TEXT NOT NULL,
    lead_time_days INTEGER NOT NULL,
    payment_terms TEXT NOT NULL,
    minimum_order_value REAL NOT NULL,
    relationship_since TEXT NOT NULL,
    notes TEXT
);
CREATE TABLE products (
    id INTEGER PRIMARY KEY,
    category TEXT NOT NULL,
    name TEXT NOT NULL,
    price REAL NOT NULL,
    recalled INTEGER NOT NULL DEFAULT 0,
    -- Product attributes. Without these, "which power rackets do competitive
    -- players prefer" is unanswerable and the segmentation guide's own criterion
    -- (100 sq in or smaller above 150 dollars) cannot be verified against the
    -- warehouse it describes.
    racket_type TEXT,          -- power | control | balanced, rackets only
    head_size_sq_in INTEGER,   -- rackets only
    weight_grams INTEGER,      -- rackets and shoes
    price_tier TEXT NOT NULL,  -- entry | mid | premium
    string_gauge TEXT,         -- strings only
    is_performance INTEGER NOT NULL DEFAULT 0,  -- meets the segmentation criterion
    -- Commercial attributes. A real retailer knows who makes a product, what it
    -- cost, whether it is in stock and when it launched. Omitting these did not
    -- make them data the business lacks; it just made obvious questions
    -- unanswerable, which is a worse failure than declaring a gap.
    brand TEXT NOT NULL,
    supplier_id INTEGER,
    unit_cost REAL NOT NULL,
    stock_level INTEGER NOT NULL,
    launch_date TEXT NOT NULL,
    lifecycle_stage TEXT NOT NULL  -- new | core | clearance | discontinued
);
CREATE TABLE orders (
    id INTEGER PRIMARY KEY,
    customer_id INTEGER NOT NULL,
    order_date TEXT NOT NULL,
    gross_amount REAL NOT NULL,
    refund_amount REAL NOT NULL DEFAULT 0,
    channel TEXT NOT NULL,
    status TEXT NOT NULL,
    campaign_id INTEGER
);
CREATE TABLE order_items (
    order_id INTEGER NOT NULL,
    product_id INTEGER NOT NULL,
    quantity INTEGER NOT NULL,
    unit_price REAL NOT NULL
);
CREATE TABLE campaigns (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    type TEXT NOT NULL,
    start_date TEXT NOT NULL,
    end_date TEXT NOT NULL,
    channel TEXT NOT NULL,
    budget REAL NOT NULL,
    -- CAMPAIGN BRIEF METADATA. Without these a marketer can pull a campaign's
    -- revenue but cannot answer "why did we run it", "who did it target", or
    -- "what did we learn", so past performance cannot be interpreted and
    -- comparable campaigns cannot be found.
    objective TEXT,            -- why it ran
    target_segment TEXT,       -- who it targeted: competitive|recreational|all
    target_category TEXT,      -- what it promoted
    offer TEXT,                -- the offer structure
    owner TEXT,                -- who ran it
    status TEXT,               -- completed | running
    learnings TEXT             -- post-campaign note, null while running
);
CREATE TABLE email_sends (
    id INTEGER PRIMARY KEY,
    campaign_id INTEGER,
    customer_id INTEGER NOT NULL,
    send_date TEXT NOT NULL,
    delivered INTEGER NOT NULL,
    opened INTEGER NOT NULL,
    machine_opened INTEGER NOT NULL,
    clicked INTEGER NOT NULL,
    email_type TEXT NOT NULL
);
CREATE TABLE ad_spend (
    date TEXT NOT NULL,
    channel TEXT NOT NULL,
    spend REAL NOT NULL,
    clicks INTEGER NOT NULL,
    attributed_signups INTEGER NOT NULL
);
CREATE INDEX idx_orders_date ON orders(order_date);
CREATE INDEX idx_orders_cust ON orders(customer_id);
CREATE INDEX idx_orders_status ON orders(status, channel);
CREATE INDEX idx_items_order ON order_items(order_id);
CREATE INDEX idx_sends_date ON email_sends(send_date);
CREATE INDEX idx_sends_cust ON email_sends(customer_id);
CREATE INDEX idx_spend_date ON ad_spend(date, channel);
CREATE INDEX idx_cust_ref ON customers(referred_by);
CREATE INDEX idx_cust_signup ON customers(signup_date);
"""


# ---------------------------------------------------------------- customers


def gen_customers() -> list[dict]:
    """Signups spread across the 24 months plus a pre-window founding cohort.

    Referral chains are grown per acquisition channel so that organic roots
    produce measurably deeper chains than any other channel (question 13).
    """
    customers: list[dict] = []
    # ~25% of the final base arrives via referral chains grown below, so only
    # ~75% are seeded as roots. A third of the roots sign up before the
    # reporting window opens, so trailing-12-month metrics have history at the
    # start of the window.
    n_roots = int(N_CUSTOMERS * 0.75)
    pre_window = int(n_roots * 0.34)
    per_month = (n_roots - pre_window) // MONTHS

    def make(signup: date, channel: str) -> dict:
        cid = len(customers) + 1
        # Competitive skew is higher for paid_search and referral traffic.
        p_comp = {"organic": 0.36, "paid_search": 0.44, "paid_social": 0.30,
                  "email": 0.38, "referral": 0.48}[channel]
        c = {
            "id": cid,
            "segment": "competitive" if rng.random() < p_comp else "recreational",
            "region": rng.choice(REGIONS),
            "signup_date": signup.isoformat(),
            "acquisition_channel": channel,
            "referred_by": None,
        }
        customers.append(c)
        return c

    # Root acquisition mix. Organic is the deep-chain channel.
    root_mix = [("organic", 0.30), ("paid_search", 0.28), ("paid_social", 0.22),
                ("email", 0.12), ("referral", 0.08)]

    def pick_root_channel() -> str:
        r = rng.random()
        acc = 0.0
        for ch, w in root_mix:
            acc += w
            if r < acc:
                return ch
        return "organic"

    window_start = add_months(FIRST_MONTH, -18)
    for _ in range(pre_window):
        make(rand_day(window_start, add_months(FIRST_MONTH, -1)), pick_root_channel())
    # Seasonal shape on signup volume, normalized so the total stays on budget
    # (a raw seasonal multiplier would inflate the root count by ~4%).
    season_norm = sum(season(m) for m, _ in WINDOWS) / MONTHS
    for m_start, m_end in WINDOWS:
        n = int(per_month * season(m_start) / season_norm)
        last_month = m_start == LAST_MONTH_START
        for _ in range(n):
            d = rand_day(m_start, m_end)
            ch = pick_root_channel()
            # PLANTED SIGNAL for question 3: paid_search signups fall during the
            # documented budget pause in the last complete month. The drop is
            # planted in the customers table (the source of the governed signups
            # metric) as well as in ad_spend, so decomposing the metric by
            # channel actually surfaces it. Dropped paid_search signups are not
            # reassigned to another channel; the pause means they never happened.
            if last_month and ch == "paid_search" and PAUSE_START <= d <= PAUSE_END:
                if rng.random() < 0.60:
                    continue
            make(d, ch)

    # ---- grow referral chains from existing roots -------------------------
    # Chain depth target by the channel of the chain ROOT. Organic roots grow
    # long chains (avg depth ~2.8); everything else stays shallow (~1.3).
    depth_profile = {
        # Organic is weighted toward the deepest targets to offset chains that
        # get truncated by REFERRAL_CUTOFF before reaching their target depth.
        "organic": [0.0, 0.10, 0.18, 0.26, 0.26, 0.20],
        "paid_search": [0.0, 0.76, 0.20, 0.04, 0.0, 0.0],
        "paid_social": [0.0, 0.80, 0.18, 0.02, 0.0, 0.0],
        "email": [0.0, 0.74, 0.22, 0.04, 0.0, 0.0],
        "referral": [0.0, 0.72, 0.24, 0.04, 0.0, 0.0],
    }

    roots = list(customers)
    rng.shuffle(roots)
    n_referred_target = N_CUSTOMERS - len(customers)
    referred_count = 0
    # Organic roots get oversampled so organic chains dominate depth stats, and
    # the oldest organic roots are tried first: a deep chain needs enough runway
    # before REFERRAL_CUTOFF to reach its target depth generation by generation.
    organic = sorted((c for c in roots if c["acquisition_channel"] == "organic"),
                     key=lambda c: c["signup_date"])
    others = [c for c in roots if c["acquisition_channel"] != "organic"]
    rng.shuffle(others)
    root_pool = organic + others

    # Organic gets a hard share of the referral budget rather than an unlimited
    # head start. Left uncapped it consumed the entire budget and no other
    # channel seeded any chain at all, which would make the question-13
    # comparison vacuous.
    organic_budget = int(n_referred_target * 0.55)
    organic_used = 0

    for root in root_pool:
        if referred_count >= n_referred_target:
            break
        ch = root["acquisition_channel"]
        if ch == "organic" and organic_used >= organic_budget:
            continue
        profile = depth_profile[ch]
        target_depth = rng.choices(range(len(profile)), weights=profile, k=1)[0]
        if target_depth == 0:
            continue
        # Grow a path (with light branching) from this root.
        frontier = [(root, 0)]
        while frontier and referred_count < n_referred_target:
            parent, depth = frontier.pop(0)
            if depth >= target_depth:
                continue
            n_kids = 1 if depth > 0 else rng.choice([1, 1, 2, 2, 3])
            for _ in range(n_kids):
                if referred_count >= n_referred_target:
                    break
                p_signup = date.fromisoformat(parent["signup_date"])
                lo = p_signup + timedelta(days=rng.randint(14, 200))
                hi = lo + timedelta(days=240)
                # Referral dates are REJECTED past the window end rather than
                # clamped to it. Clamping piled every late chain onto the final
                # month, which manufactured a signup spike there and buried the
                # planted paid_search drop that question 3 has to find.
                if hi > REFERRAL_CUTOFF:
                    continue
                kid = make(rand_day(lo, hi), "referral")
                kid["referred_by"] = parent["id"]
                referred_count += 1
                if ch == "organic":
                    organic_used += 1
                frontier.append((kid, depth + 1))

    # Top up to ~18k with additional roots if chain growth ran short.
    while len(customers) < N_CUSTOMERS:
        make(rand_day(FIRST_MONTH, DATA_END), pick_root_channel())

    return customers


# ---------------------------------------------------------------- products


def gen_suppliers() -> list[dict]:
    """The vendors behind the brands, with the terms a merchandiser cares about."""
    rows = [
        ("Meridian Sports Group", "United States", 14, "net 30", 5000.0, "2023-02-01",
         "Primary racket and shoe vendor. Reliable, rarely discounts."),
        ("Kestrel Athletic", "Taiwan", 45, "net 60", 12000.0, "2023-05-15",
         "Long lead times, best unit economics. Order well ahead of league season."),
        ("Northline Textiles", "Portugal", 28, "net 45", 4000.0, "2024-01-10",
         "Apparel only. Small minimums, good for testing new lines."),
        ("Cordage Works", "United States", 10, "net 30", 1500.0, "2023-03-01",
         "String specialist. Short lead time, holds our recall liability."),
        ("Apex Court Supply", "Vietnam", 52, "net 60", 15000.0, "2024-06-01",
         "Newest vendor, cheapest shoes, quality still being proven."),
    ]
    return [{"id": i + 1, "name": n, "country": c, "lead_time_days": lt,
             "payment_terms": pt, "minimum_order_value": mov,
             "relationship_since": since, "notes": notes}
            for i, (n, c, lt, pt, mov, since, notes) in enumerate(rows)]


def gen_products() -> list[dict]:
    products = []
    names = {
        "rackets": ["Baseline Pro 98", "Baseline Tour 100", "Topspin XT", "Control 95",
                    "Power Drive 105", "Junior Ace 26", "Baseline Pro 97 Lite",
                    "Slice Master", "Rally Tour 98", "Grip Elite 100"],
        "strings": ["Gut Elite 16", "Polytour Fire 17", "SyntheticPro 16", "HybridMax",
                    "SpinTech 17", "SoftFeel 16L", "DuraCore 15L", "MonoEdge 17"],
        "shoes": ["Court Grip 3", "Baseline Runner", "Clay Master", "AllCourt Pro",
                  "Speed Volley", "Stability X"],
        "apparel": ["Tour Polo", "Match Shorts", "Baseline Cap", "Compression Tee",
                    "Warmup Jacket", "Performance Skirt", "Sport Socks 3pk"],
        "services": ["Standard Restring", "Premium Restring", "Grip Replacement",
                     "Racket Customization", "Same-Day Restring"],
    }
    price_bands = {"rackets": (129, 279), "strings": (9, 44), "shoes": (69, 159),
                   "apparel": (19, 89), "services": (18, 65)}
    # Per-category product counts summing to 120. Every category must be
    # populated, so the cap is applied per category rather than globally.
    per_cat = {"rackets": 30, "strings": 28, "shoes": 20, "apparel": 30, "services": 12}

    # Racket specs keyed to the model name, so attributes agree with what the name
    # implies. A "Power Drive 105" must actually be a power frame with a 105 inch
    # head; otherwise product questions produce answers that contradict the
    # catalog a human is reading.
    RACKET_SPECS = {
        "Baseline Pro 98": ("control", 98, 305),
        "Baseline Pro 97 Lite": ("control", 97, 285),
        "Control 95": ("control", 95, 310),
        "Slice Master": ("control", 98, 315),
        "Rally Tour 98": ("balanced", 98, 300),
        "Baseline Tour 100": ("balanced", 100, 300),
        "Topspin XT": ("balanced", 100, 295),
        "Grip Elite 100": ("balanced", 100, 298),
        "Power Drive 105": ("power", 105, 275),
        "Junior Ace 26": ("power", 107, 240),
    }
    STRING_GAUGES = {
        "Gut Elite 16": "16", "Polytour Fire 17": "17", "SyntheticPro 16": "16",
        "HybridMax": "16L", "SpinTech 17": "17", "SoftFeel 16L": "16L",
        "DuraCore 15L": "15L", "MonoEdge 17": "17",
    }

    def price_tier(cat: str, price: float) -> str:
        lo, hi = price_bands[cat]
        third = (hi - lo) / 3
        if price < lo + third:
            return "entry"
        return "mid" if price < lo + 2 * third else "premium"

    # Brands, with the supplier behind each and the categories they make. The
    # positioning column drives who buys them, so "which brands do competitive
    # players choose" has a real answer rather than a random split.
    BRANDS = {
        "Baseline":   dict(supplier=1, positioning="performance",
                           cats={"rackets", "strings", "apparel"}, margin=0.42),
        "Kestrel":    dict(supplier=2, positioning="value",
                           cats={"rackets", "shoes", "apparel"}, margin=0.55),
        "Cordage":    dict(supplier=4, positioning="performance",
                           cats={"strings"}, margin=0.48),
        "Northline":  dict(supplier=3, positioning="value",
                           cats={"apparel"}, margin=0.58),
        "Apex":       dict(supplier=5, positioning="value",
                           cats={"shoes"}, margin=0.60),
        "Meridian":   dict(supplier=1, positioning="performance",
                           cats={"shoes", "rackets"}, margin=0.40),
        "House":      dict(supplier=None, positioning="own_label",
                           cats={"services", "apparel", "strings"}, margin=0.72),
    }

    def pick_brand(cat: str, tier: str) -> str:
        """Performance brands skew premium; value brands skew entry."""
        eligible = [b for b, m in BRANDS.items() if cat in m["cats"]]
        if not eligible:
            eligible = ["House"]
        weights = []
        for b in eligible:
            pos = BRANDS[b]["positioning"]
            if tier == "premium":
                weights.append(3.0 if pos == "performance" else 1.0)
            elif tier == "entry":
                weights.append(3.0 if pos == "value" else 1.0)
            else:
                weights.append(2.0)
        return rng.choices(eligible, weights=weights, k=1)[0]

    pid = 0
    for cat, base_names in names.items():
        variants = ["", " Gen2", " Gen3", " Ltd", " 2026"]
        made = 0
        for v in variants:
            for nm in base_names:
                if made >= per_cat[cat]:
                    break
                pid += 1
                lo, hi = price_bands[cat]
                price = round(rng.uniform(lo, hi), 2)
                tier = price_tier(cat, price)
                brand = pick_brand(cat, tier)
                bmeta = BRANDS[brand]
                # Cost derives from the brand's margin profile, so gross margin
                # varies by brand and category the way it does in a real catalog.
                margin = bmeta["margin"] * rng.uniform(0.92, 1.08)
                launch = rand_day(add_months(FIRST_MONTH, -24), DATA_END)
                age_days = (DATA_END - launch).days
                if age_days < 120:
                    stage = "new"
                elif rng.random() < 0.10:
                    stage = "discontinued"
                elif rng.random() < 0.12:
                    stage = "clearance"
                else:
                    stage = "core"
                p = {
                    "id": pid, "category": cat, "name": f"{brand} {nm}{v}",
                    "price": price, "recalled": 0,
                    "racket_type": None, "head_size_sq_in": None,
                    "weight_grams": None, "price_tier": tier,
                    "string_gauge": None, "is_performance": 0,
                    "brand": brand,
                    "supplier_id": bmeta["supplier"],
                    "unit_cost": round(price * (1 - margin), 2),
                    "stock_level": (0 if stage == "discontinued"
                                    else rng.randint(0, 40) if stage == "clearance"
                                    else rng.randint(0, 320)),
                    "launch_date": launch.isoformat(),
                    "lifecycle_stage": stage,
                }
                if cat == "rackets":
                    rtype, head, weight = RACKET_SPECS[nm]
                    p["racket_type"] = rtype
                    p["head_size_sq_in"] = head
                    p["weight_grams"] = weight + rng.randint(-8, 8)
                    # The segmentation guide's definition of a performance racket,
                    # now computable: 100 sq in or smaller AND above 150 dollars.
                    p["is_performance"] = int(head <= 100 and price > 150)
                elif cat == "shoes":
                    p["weight_grams"] = rng.randint(290, 400)
                elif cat == "strings":
                    p["string_gauge"] = STRING_GAUGES[nm]
                products.append(p)
                made += 1
    # Exactly one recalled string, promoted by the spring campaign. Matched on the
    # base model name because product names now carry a brand prefix.
    recalled = next(p for p in products if p["category"] == "strings"
                    and p["name"].endswith("SpinTech 17"))
    recalled["recalled"] = 1
    # A recalled product is pulled from sale: zero stock, discontinued.
    recalled["stock_level"] = 0
    recalled["lifecycle_stage"] = "discontinued"
    return products


# ---------------------------------------------------------------- campaigns


def gen_campaigns() -> tuple[list[dict], int]:
    """~60 campaigns. Returns (campaigns, spring_campaign_id).

    The spring campaign is the most recent March campaign inside the window.
    """
    campaigns = []
    cid = 0
    spring_id = None
    # Campaign briefs. Each theme carries the intent a marketer needs in order to
    # interpret past performance: what it was for, who it targeted, what it
    # promoted, and what the offer was. A campaign row with only dates and a
    # budget cannot answer "why did we run this" or "find me a comparable one".
    THEMES = [
        dict(slug="Restring Reset", objective="drive restring volume in the "
             "post holiday lull", target_segment="competitive",
             target_category="strings", offer="15 percent off any restring",
             type="lifecycle", months=[1, 2]),
        dict(slug="Equipment Refresh", objective="convert pre season demand into "
             "racket and shoe upgrades", target_segment="all",
             target_category="rackets", offer="bundle discount on racket plus "
             "restring", type="promotional", months=[2, 3]),
        dict(slug="League Season Push", objective="capture peak spring league "
             "demand across every category", target_segment="all",
             target_category="rackets", offer="free express shipping",
             type="seasonal", months=[3, 4, 5]),
        dict(slug="Summer Tournament Tie In", objective="keep engagement warm "
             "through the summer tournament calendar",
             target_segment="competitive", target_category="apparel",
             offer="10 percent off apparel", type="promotional", months=[6, 7, 8]),
        dict(slug="Fall League Build", objective="rebuild order volume as fall "
             "leagues start", target_segment="all", target_category="shoes",
             offer="20 dollars off shoes over 100 dollars", type="seasonal",
             months=[9, 10]),
        dict(slug="Holiday Gifting", objective="capture gift purchases in an "
             "otherwise quiet month", target_segment="recreational",
             target_category="apparel", offer="gift bundles from 49 dollars",
             type="promotional", months=[11, 12]),
        dict(slug="Winback", objective="reactivate customers with no order in "
             "the last nine months", target_segment="all",
             target_category="strings", offer="25 percent off one order",
             type="lifecycle", months=list(range(1, 13))),
        dict(slug="New Customer Welcome", objective="convert new signups to a "
             "first order", target_segment="all", target_category="apparel",
             offer="10 percent off first order", type="lifecycle",
             months=list(range(1, 13))),
    ]
    OWNERS = ["Lifecycle Marketing", "Campaign Marketing", "Growth Marketing"]
    LEARNINGS = [
        "Performed in line with the band. Offer structure unchanged next cycle.",
        "Open rate held but click rate lagged; the subject line tested better "
        "than the landing page.",
        "Strong revenue per email. Worth repeating at higher send volume.",
        "Underperformed against the band. The offer was too shallow for the "
        "segment.",
        "Volume was fine and margin was thin; the discount did most of the work.",
        "Best performing send of the quarter. Timing against league signup "
        "deadlines mattered more than the offer.",
    ]

    for m_start, m_end in WINDOWS:
        n = rng.choice([2, 3, 3])
        eligible = [t for t in THEMES if m_start.month in t["months"]]
        rng.shuffle(eligible)
        for k in range(n):
            cid += 1
            theme = eligible[k % len(eligible)] if eligible else THEMES[-1]
            ch = ("email" if theme["type"] == "lifecycle"
                  else rng.choice(["email", "paid_search", "paid_social"]))
            start = rand_day(m_start, max(m_start, m_end - timedelta(days=10)))
            # Campaigns in the current-ish tail are still running, so learnings
            # are legitimately absent for them.
            running = m_start >= add_months(LAST_MONTH_START, -1)
            camp = {
                "id": cid,
                "name": f"{theme['slug']} {m_start.strftime('%b %Y')}",
                "type": theme["type"],
                "start_date": start.isoformat(),
                "end_date": min(m_end, start + timedelta(days=rng.randint(10, 25))).isoformat(),
                "channel": ch,
                "budget": round(rng.uniform(4_000, 30_000), 2),
                "objective": theme["objective"],
                "target_segment": theme["target_segment"],
                "target_category": theme["target_category"],
                "offer": theme["offer"],
                "owner": rng.choice(OWNERS),
                "status": "running" if running else "completed",
                "learnings": None if running else rng.choice(LEARNINGS),
            }
            campaigns.append(camp)
    # Promote a March campaign to be THE spring campaign. The EARLIEST in-window
    # March is chosen deliberately: the recall follows the campaign, and the
    # recall must land before the trailing 12 month measurement window opens so
    # that a full post-recall year of repeat behavior is measurable.
    march = [c for c in campaigns
             if date.fromisoformat(c["start_date"]).month == 3 and c["channel"] == "email"]
    if not march:
        march = [c for c in campaigns if date.fromisoformat(c["start_date"]).month == 3]
    spring = min(march, key=lambda c: c["start_date"])
    spring["name"] = "Spring League Kickoff"
    spring["type"] = "seasonal"
    spring["channel"] = "email"
    spring["budget"] = 48_000.0
    spring["objective"] = ("capture peak spring league demand, with strings as "
                          "the lead category")
    spring["target_segment"] = "all"
    spring["target_category"] = "strings"
    spring["offer"] = "free express shipping plus a promoted string of the season"
    spring["owner"] = "Campaign Marketing"
    spring["status"] = "completed"
    spring["learnings"] = (
        "Largest campaign of the year by revenue. One promoted string was "
        "subsequently recalled, which confounds any read of post campaign repeat "
        "behavior for the customers who bought it. See the recall notice.")
    # Widen it so it can carry >= 5,000 sends and >= 400 attributed orders.
    s = date.fromisoformat(spring["start_date"])
    spring["start_date"] = date(s.year, 3, 1).isoformat()
    spring["end_date"] = date(s.year, 5, 15).isoformat()
    spring_id = spring["id"]
    return campaigns, spring_id


# ---------------------------------------------------------------- orders


def gen_orders(customers, products, spring_id, spring_window):
    """Orders + order_items.

    Planted behavior:
      - ~2% status='test', ~5% channel='wholesale' (the raw-SQL trap)
      - spring campaign attributed orders, some carrying the recalled string
      - two depressed-repeat cohorts (recall cohort, referral-churn cohort)
    """
    orders: list[dict] = []
    items: list[dict] = []
    by_cat = defaultdict(list)
    for p in products:
        by_cat[p["category"]].append(p)
    recalled = next(p for p in products if p["recalled"])
    other_strings = [p for p in by_cat["strings"] if not p["recalled"]]

    spring_start, spring_end = spring_window
    recall_date = spring_start + timedelta(days=30)

    # Cohorts whose repeat behavior is suppressed after their first purchase.
    suppressed: dict[int, date] = {}

    cust_by_id = {c["id"]: c for c in customers}
    signup = {c["id"]: date.fromisoformat(c["signup_date"]) for c in customers}

    # ---- choose the recall cohort and its matched control -----------------
    # Both bought a string through the spring campaign; one bought the recalled
    # SKU. Divergence begins after the recall date.
    eligible = [c for c in customers if signup[c["id"]] <= spring_start]
    rng.shuffle(eligible)
    # Cohort membership is resolved after the churn set is chosen below, so the
    # two planted signals cannot contaminate each other.
    recall_pool = eligible

    # ---- referral-churn cluster (question 14) -----------------------------
    # One referral subtree: referrers churn, and their referees under-repeat.
    kids_of = defaultdict(list)
    for c in customers:
        if c["referred_by"]:
            kids_of[c["referred_by"]].append(c["id"])
    # Pick referrers with children, early enough that referral precedes churn.
    # The churn window opens 12 months before the last complete month. Every
    # referral in the planted cluster must land before that, so the referrer
    # churns AFTER referring and the temporal ordering is verifiable.
    churn_window_open = add_months(LAST_MONTH_START, -11)
    candidate_referrers = [
        cid for cid, kids in kids_of.items()
        if signup[cid] <= add_months(LAST_MONTH_START, -18)
    ]
    rng.shuffle(candidate_referrers)
    churn_referrers: list[int] = []
    exposed_referees: list[int] = []
    for cid in candidate_referrers:
        if len(exposed_referees) >= 340:
            break
        kids = [k for k in kids_of[cid] if signup[k] > signup[cid]]
        # Take the referrer only if EVERY one of its referrals predates the
        # churn window. A partial subtree would leave referrals dated inside the
        # window, which would break the temporal claim the playbook verifies.
        if not kids or any(signup[k] >= churn_window_open for k in kids):
            continue
        churn_referrers.append(cid)
        exposed_referees.extend(kids)
    exposed_referees = exposed_referees[:340]
    churn_referrer_set = set(churn_referrers)

    # Recall and control cohorts are drawn only from customers not involved in
    # the churn cluster, so the two planted signals stay independent: a churned
    # referrer must never receive a spring-campaign purchase that reactivates it.
    _excluded = churn_referrer_set | set(exposed_referees)
    _pool = [c["id"] for c in recall_pool if c["id"] not in _excluded]
    recall_cohort = _pool[:420]
    control_cohort = _pool[420:900]
    # Referrers go quiet before the trailing 12 month window opens, so the
    # inferred-churn definition (no completed order in trailing 12m) marks them
    # churned as of the last complete month, and the referral always predates
    # the churn.
    churn_stop = add_months(LAST_MONTH_START, -13)

    oid = 0

    def add_order(cust_id, d, channel, status, gross, refund, campaign_id, item_pids):
        nonlocal oid
        oid += 1
        orders.append({
            "id": oid, "customer_id": cust_id, "order_date": d.isoformat(),
            "gross_amount": round(gross, 2), "refund_amount": round(refund, 2),
            "channel": channel, "status": status, "campaign_id": campaign_id,
        })
        for pid in item_pids:
            p = next(pp for pp in products if pp["id"] == pid)
            items.append({"order_id": oid, "product_id": pid, "quantity": 1,
                          "unit_price": p["price"]})
        return oid

    # PLANTED CROSS-SELL AFFINITY. Without this, co-purchase rates just track
    # category popularity (every lift lands near 1.0) and the affinity tool
    # correctly reports "no real signal", which is honest but demonstrates
    # nothing. These pairings give the cross-sell question a defensible answer:
    # a racket buyer really does reach for a restring, and a shoe buyer for
    # apparel, more often than chance would predict.
    AFFINITY = {
        "rackets": ("strings", 0.55),   # new frame needs stringing
        "shoes": ("apparel", 0.45),     # kit bought together
        "strings": ("services", 0.12),  # restring service attach
    }
    recent_category: dict[int, str] = {}

    def basket(cust) -> list[dict]:
        """Category mix by segment. Services deliberately kept rare."""
        # An affinity pull fires when this customer's previous purchase has a
        # planted partner category, which is what creates lift above 1.0.
        prev = recent_category.get(cust["id"])
        if prev and prev in AFFINITY:
            partner, p = AFFINITY[prev]
            if rng.random() < p:
                pool = by_cat[partner]
                n = 1 if partner in ("rackets", "services") else rng.choice([1, 1, 2])
                recent_category[cust["id"]] = partner
                return rng.sample(pool, min(n, len(pool)))

        if cust["segment"] == "competitive":
            weights = [("strings", 0.40), ("rackets", 0.18), ("shoes", 0.16),
                       ("apparel", 0.24), ("services", 0.02)]
        else:
            weights = [("strings", 0.24), ("rackets", 0.14), ("shoes", 0.20),
                       ("apparel", 0.41), ("services", 0.01)]
        r, acc = rng.random(), 0.0
        cat = "apparel"
        for c, w in weights:
            acc += w
            if r < acc:
                cat = c
                break
        n = 1 if cat in ("rackets", "services") else rng.choice([1, 1, 2])
        pool = by_cat[cat]

        # PLANTED PRODUCT PREFERENCE. Competitive players skew hard to control
        # frames and premium price tiers; recreational players skew to power
        # frames and entry tiers. Without this, "which rackets do competitive
        # players prefer" has no defensible answer and the product attributes
        # would be decoration.
        if cat == "rackets":
            if cust["segment"] == "competitive":
                want = rng.choices(["control", "balanced", "power"],
                                   weights=[0.62, 0.30, 0.08], k=1)[0]
            else:
                want = rng.choices(["power", "balanced", "control"],
                                   weights=[0.55, 0.33, 0.12], k=1)[0]
            typed = [p for p in pool if p["racket_type"] == want]
            pool = typed or pool
        elif cat == "strings" and cust["segment"] == "competitive":
            # Competitive players restring often and prefer thinner gauges.
            thin = [p for p in pool if p["string_gauge"] in ("17", "16L")]
            if thin and rng.random() < 0.68:
                pool = thin
        elif cat in ("shoes", "apparel"):
            tier = ("premium" if cust["segment"] == "competitive"
                    and rng.random() < 0.55 else None)
            if tier:
                tiered = [p for p in pool if p["price_tier"] == tier]
                pool = tiered or pool

        # PLANTED BRAND PREFERENCE. Competitive players reach for the performance
        # brands, recreational players for the value ones. Without this, brand is
        # just a label and "which brands do competitive players buy" has no
        # defensible answer.
        PERFORMANCE_BRANDS = {"Baseline", "Cordage", "Meridian"}
        if cust["segment"] == "competitive" and rng.random() < 0.62:
            pref = [p for p in pool if p["brand"] in PERFORMANCE_BRANDS]
            pool = pref or pool
        elif cust["segment"] == "recreational" and rng.random() < 0.55:
            pref = [p for p in pool if p["brand"] not in PERFORMANCE_BRANDS]
            pool = pref or pool

        # Discontinued and out of stock items cannot be bought today, but they
        # were buyable historically, so they stay in the pool for past orders.
        buyable = [p for p in pool if p["lifecycle_stage"] != "discontinued"]
        pool = buyable or pool

        recent_category[cust["id"]] = cat
        return rng.sample(pool, min(n, len(pool)))

    def order_channel(cust) -> str:
        r = rng.random()
        if r < 0.44:
            return "web"
        if r < 0.68:
            return "email"
        if r < 0.84:
            return "paid_search"
        return "paid_social"

    # ---- seeded first purchases for the planted cohorts ------------------
    def seed_spring_string_order(cust_id, product):
        cust = cust_by_id[cust_id]
        d = rand_day(spring_start, min(spring_end, DATA_END))
        prods = [product]
        gross = sum(p["price"] for p in prods)
        add_order(cust_id, d, "email", "completed", gross, 0.0, spring_id,
                  [p["id"] for p in prods])
        return d

    # Repeat purchase rate is "2+ completed orders in the trailing 12 months",
    # so the planted deltas are created by holding a chosen FRACTION of each
    # cohort to at most one order inside that window. A probabilistic thinning
    # cannot do this reliably once per-customer volume is high: most members
    # would still clear two orders and the measured gap would collapse.
    trailing_start = add_months(LAST_MONTH_START, -11)

    # Members held to <= 1 order in the trailing window, keyed to the date the
    # hold starts (purchases before that date are untouched).
    held: dict[int, date] = {}

    for cid in recall_cohort:
        d = seed_spring_string_order(cid, recalled)
        # Divergence begins only after the recall date.
        suppressed[cid] = max(d, recall_date)
    for cid in control_cohort:
        seed_spring_string_order(cid, rng.choice(other_strings))

    # ~10 point divergence for the recall cohort vs its matched control. The
    # hold begins at the recall date, so purchases made before the recall carry
    # no exposure to it and the divergence is genuinely post-recall.
    for cid in recall_cohort:
        if rng.random() < 0.075:
            held[cid] = max(recall_date, trailing_start)

    # ~12 point gap for referees of churned referrers, from signup onward.
    for cid in exposed_referees:
        suppressed[cid] = signup[cid]
        if rng.random() < 0.30:
            held[cid] = trailing_start

    # Count of in-window marketing orders per held customer, so the cap is
    # enforced as orders are generated.
    held_count: dict[int, int] = defaultdict(int)

    # ---- organic order stream --------------------------------------------
    # Per-customer purchase intensity, seasonal, over each customer's active life.
    for cust in customers:
        cid = cust["id"]
        s = signup[cid]
        active_from = max(s, DATA_START)
        if active_from > DATA_END:
            continue
        base_rate = 5.2 if cust["segment"] == "competitive" else 2.5  # orders/year
        months_active = max(1, (DATA_END.year * 12 + DATA_END.month)
                            - (active_from.year * 12 + active_from.month) + 1)
        expected = base_rate * months_active / 12.0
        n = _poisson(expected)
        for _ in range(n):
            # Seasonal rejection sampling on the order DATE (not on whether the
            # order happens), so seasonality shapes the monthly curve without
            # deflating total volume.
            for _attempt in range(6):
                d = rand_day(active_from, DATA_END)
                if rng.random() <= season(d) / 1.3:
                    break
            else:
                continue
            # Churn-referrer cohort stops ordering entirely before the trailing
            # 12 month window opens, so the inferred-churn definition marks them
            # churned as of the last complete month.
            if cid in churn_referrer_set and d >= churn_stop:
                continue
            # Held members are capped at one marketing order inside the trailing
            # window, which is what creates the planted repeat-rate deltas.
            if cid in held and d >= held[cid]:
                if held_count[cid] >= 1:
                    continue
                held_count[cid] += 1
            # Light additional thinning for the rest of the suppressed cohorts,
            # so the gap is not carried by the held members alone.
            elif cid in suppressed and d > suppressed[cid] and rng.random() < 0.22:
                continue
            prods = basket(cust)
            gross = sum(p["price"] for p in prods)
            ch = order_channel(cust)
            status, refund = "completed", 0.0
            r = rng.random()
            if r < 0.02:
                status = "test"
            elif r < 0.055:
                ch = "wholesale"
                gross *= rng.uniform(4, 12)  # bulk
            elif r < 0.115:
                status = "refunded"
                refund = gross
            elif r < 0.175:
                refund = round(gross * rng.uniform(0.2, 0.6), 2)
            camp = spring_id if (ch == "email" and spring_start <= d <= spring_end
                                 and rng.random() < 0.5) else None
            add_order(cid, d, ch, status, gross, refund, camp,
                      [p["id"] for p in prods])

    # ---- keep services volume thin but nonzero every month ----------------
    # Target 15-25 completed services orders per month: real but below the
    # reliability threshold, so category questions trigger a small-sample
    # warning (question 18). Overshoot is trimmed, shortfall is topped up.
    svc_ids = {p["id"] for p in by_cat["services"]}
    item_by_order = defaultdict(list)
    for it in items:
        item_by_order[it["order_id"]].append(it["product_id"])

    svc_orders_by_month = defaultdict(list)
    for o in orders:
        if o["status"] == "completed" and o["channel"] != "wholesale":
            if any(pid in svc_ids for pid in item_by_order[o["id"]]):
                svc_orders_by_month[o["order_date"][:7]].append(o)

    # Trim overshoot by reassigning surplus services orders to apparel.
    apparel = by_cat["apparel"]
    for key, olist in svc_orders_by_month.items():
        want = rng.randint(15, 25)
        if len(olist) <= want:
            continue
        for o in olist[want:]:
            repl = rng.choice(apparel)
            for it in items:
                if it["order_id"] == o["id"] and it["product_id"] in svc_ids:
                    it["product_id"] = repl["id"]
                    it["unit_price"] = repl["price"]
            o["gross_amount"] = round(repl["price"], 2)
            o["refund_amount"] = min(o["refund_amount"], o["gross_amount"])

    # Top up any month that came in short. Churned referrers are excluded so
    # the top-up cannot silently reactivate them.
    churned = set(churn_referrers)
    for m_start, m_end in WINDOWS:
        key = m_start.isoformat()[:7]
        have = min(len(svc_orders_by_month[key]), 25)
        want = rng.randint(15, 25)
        while have < want:
            cust = rng.choice(customers)
            if signup[cust["id"]] > m_end or cust["id"] in churned:
                continue
            p = rng.choice(by_cat["services"])
            add_order(cust["id"], rand_day(m_start, m_end), "web", "completed",
                      p["price"], 0.0, None, [p["id"]])
            have += 1

    return orders, items, {
        "recall_cohort": recall_cohort,
        "control_cohort": control_cohort,
        "churn_referrers": churn_referrers,
        "exposed_referees": exposed_referees,
        "recall_date": recall_date,
    }


def _poisson(lam: float) -> int:
    """Knuth sampler on the shared RNG so output stays deterministic."""
    import math
    l_val = math.exp(-lam)
    k, p = 0, 1.0
    while True:
        p *= rng.random()
        if p <= l_val:
            return k
        k += 1


# ---------------------------------------------------------------- email sends


def gen_email_sends(customers, campaigns, spring_id, spring_window):
    """~400k sends. 35% of opens are machine opens (Apple MPP simulation)."""
    sends = []
    sid = 0
    signup = {c["id"]: date.fromisoformat(c["signup_date"]) for c in customers}
    seg = {c["id"]: c["segment"] for c in customers}
    camps_by_month = defaultdict(list)
    for c in campaigns:
        camps_by_month[c["start_date"][:7]].append(c)
    spring_start, spring_end = spring_window

    # Base list of emailable customers per month.
    for m_start, m_end in WINDOWS:
        key = m_start.isoformat()[:7]
        pool = [c["id"] for c in customers if signup[c["id"]] <= m_end]
        if not pool:
            continue
        month_camps = camps_by_month.get(key, [])
        spring_active = spring_start <= m_end and spring_end >= m_start

        # campaign sends
        n_camp = int(len(pool) * rng.uniform(0.55, 0.75))
        targets = rng.sample(pool, min(n_camp, len(pool)))
        for cust in targets:
            sid += 1
            d = rand_day(m_start, m_end)
            if spring_active and rng.random() < 0.55:
                cid_camp = spring_id
            else:
                cid_camp = rng.choice(month_camps)["id"] if month_camps else None
            _append_send(sends, sid, cid_camp, cust, d, "campaign", seg[cust])
        # lifecycle sends (welcome, winback, restring reminder)
        n_life = int(len(pool) * rng.uniform(0.30, 0.42))
        for cust in rng.sample(pool, min(n_life, len(pool))):
            sid += 1
            _append_send(sends, sid, None, cust, rand_day(m_start, m_end),
                         "lifecycle", seg[cust])
        # transactional sends (must be excluded by the governed metric)
        n_tx = int(len(pool) * rng.uniform(0.12, 0.18))
        for cust in rng.sample(pool, min(n_tx, len(pool))):
            sid += 1
            _append_send(sends, sid, None, cust, rand_day(m_start, m_end),
                         "transactional", seg[cust])

    # Ensure the spring campaign clears 5,000 sends.
    spring_sends = sum(1 for s in sends if s["campaign_id"] == spring_id)
    pool = [c["id"] for c in customers if signup[c["id"]] <= spring_end]
    while spring_sends < 6_000:
        sid += 1
        cust = rng.choice(pool)
        _append_send(sends, sid, spring_id, cust,
                     rand_day(spring_start, min(spring_end, DATA_END)),
                     "campaign", seg[cust])
        spring_sends += 1
    return sends


def _append_send(sends, sid, campaign_id, cust, d, etype, segment):
    delivered = 1 if rng.random() < 0.973 else 0
    opened = machine = clicked = 0
    if delivered:
        # Human open rate lands in a 21-25% band; machine opens add on top.
        p_human = 0.235 if etype != "transactional" else 0.44
        p_human *= 1.06 if segment == "competitive" else 0.96
        p_human *= 1.0 + (season(d) - 1.0) * 0.35
        human = rng.random() < p_human
        # 35% of all opens are machine-only opens.
        machine_only = rng.random() < 0.127
        if human or machine_only:
            opened = 1
            machine = 1 if (machine_only and not human) else 0
            if human and rng.random() < 0.128:
                clicked = 1
    sends.append({
        "id": sid, "campaign_id": campaign_id, "customer_id": cust,
        "send_date": d.isoformat(), "delivered": delivered, "opened": opened,
        "machine_opened": machine, "clicked": clicked, "email_type": etype,
    })


# ---------------------------------------------------------------- ad spend


def gen_ad_spend():
    """Daily rows per paid channel.

    Two planted features:
      - paid_social has NO rows before month 7 (declared coverage hole)
      - paid_search attributed_signups drop ~40% for 12 days in the last
        complete month, matching the documented budget pause
    """
    rows = []
    pause_start, pause_end = PAUSE_START, PAUSE_END

    d = DATA_START
    while d <= DATA_END:
        s = season(d)
        for ch in ["paid_search", "paid_social", "organic"]:
            if ch == "paid_social" and d < PAID_SOCIAL_START:
                continue  # planted gap
            if ch == "organic":
                spend = 0.0
                clicks = int(rng.uniform(700, 1100) * s)
                sign = int(rng.uniform(26, 38) * s)
            elif ch == "paid_search":
                base_spend = rng.uniform(950, 1300) * s
                base_sign = rng.uniform(30, 40) * s
                if pause_start <= d <= pause_end:
                    base_spend *= 0.58
                    base_sign *= 0.58  # ~40% drop
                spend = base_spend
                clicks = int(base_spend / rng.uniform(1.6, 2.3))
                sign = int(base_sign)
            else:
                spend = rng.uniform(700, 1000) * s
                clicks = int(spend / rng.uniform(1.2, 1.9))
                sign = int(rng.uniform(18, 27) * s)
            rows.append({"date": d.isoformat(), "channel": ch,
                         "spend": round(spend, 2), "clicks": clicks,
                         "attributed_signups": sign})
        d += timedelta(days=1)
    return rows, (pause_start, pause_end)


# ---------------------------------------------------------------- documents

def gen_documents(spring, recalled_product, recall_date, pause,
                  spring_net, spring_gross):
    """Write the document corpus.

    TWO RULES, both learned the hard way:

    1. NO DOCUMENT DECLARES ITS OWN STATUS. There are no 'Authority: canonical'
       headers here, no 'Status: superseded', no 'NOT ADOPTED' in a title. Real
       documents do not carry those, because the person who wrote the 2024
       policy had no way to know it would be replaced, and the person who wrote
       the replacement could not reach back and stamp every copy of the old one.
       Status lives in semantic-layer/.../catalog/document_registry.yaml, which
       is what makes authority ranking a real capability rather than a reading
       comprehension exercise: strip the registry and even a naive search could
       previously spot the stale document from its first three lines.

    2. EVERY DOCUMENT IS SUBSTANTIAL, 50 lines minimum. The first corpus
       averaged 153 words, which is too thin to retrieve within, too thin to
       chunk, and too thin for a near miss to be genuinely near.
    """
    os.makedirs(DOCS_DIR, exist_ok=True)
    docs = {}

    docs["brand-and-supplier-guide.md"] = """# Brand and Supplier Guide

Owner: Merchandising

This is the reference for what we stock, who makes it, and why each brand is on
the shelf. Read the positioning section before making an assortment argument.

## Why we carry seven brands

Assortment is a balance between credibility and margin. Performance brands earn
the trust of competitive players and carry thinner margins; value brands and our
own label pay for the business. Dropping either side breaks the model.

## Performance brands

**Baseline** is the anchor of the racket wall and the brand most associated with
us. Frames skew to control, head sizes 95 to 100 square inches, and the line is
the default recommendation for a league player. Margin runs in the low forties,
the thinnest in the catalog, and that is accepted: Baseline is why competitive
players consider us a specialist rather than a general retailer.

**Meridian** covers performance shoes and a small racket range. Court Grip and
AllCourt Pro are the two shoes we recommend for hard court league play. Margin is
the lowest we accept, around forty percent, and the relationship is worth it for
the shoe credibility alone.

**Cordage** is string only, and it is the technical end of the range. Thinner
gauges, better feel, favoured by players who restring every few weeks. Cordage
also manufactured the string subject to the recall, and holds the liability for
it under our supply agreement.

## Value brands

**Kestrel** is the volume play across rackets, shoes and apparel. Mid fifties
margin, longer lead times out of Taiwan, and the brand that makes the entry price
points work. A recreational customer buying their first proper racket is usually
buying Kestrel.

**Northline** is apparel only, out of Portugal, with small minimum orders. That
makes it the right vendor for testing a new line without committing to a
container. Margin is high, quality is consistent, lead times are moderate.

**Apex** is the newest vendor and the cheapest shoes in the range, at the best
margin we get on footwear. Quality is still being proven. Do not promote Apex to
competitive players until we have a full season of return data.

## Own label

**House** is our own label: stringing services, basic apparel, and commodity
strings. Margin is around seventy percent, far above anything we buy in, and it
is the single biggest lever on blended margin. The constraint is credibility.
House products sell well to recreational customers and poorly to competitive
ones, and pushing House into the performance range has failed twice.

## Supplier terms and what they mean for planning

Lead time is the number that ruins seasons. Kestrel and Apex both run beyond six
weeks, so spring league stock has to be committed in the previous autumn.
Cordage at ten days is the only vendor we can reorder inside a season, which is
why string stockouts are rare and shoe stockouts are not.

Payment terms run net 30 for the domestic vendors and net 60 for the overseas
ones, which partly offsets the cash cost of the longer lead times.

Minimum order values matter most for Northline, whose low minimum is exactly why
we use them for tests, and for Apex, whose high minimum means any Apex bet is a
large one.

## Assortment rules

- Every category carries at least one performance and one value option.
- No category is more than sixty percent one brand.
- New brands enter through a single category and a single season before expanding.
- A brand that misses two consecutive lead time commitments goes on review.
"""

    docs["brand-voice.md"] = """# Brand Voice Guide

Marketing

## The core idea

We write like a stringer who plays, not like a catalog. Someone who knows the
equipment because they use it, and who would rather tell you the honest thing than
the flattering one.

That voice is the reason a league player trusts a specialist over a mass retailer,
and it is easy to lose. Most of the rules below exist because we lost it somewhere
and had to correct.

## Principles

**Plain and specific.** Say the head size, say the weight, say the string gauge. A
customer choosing equipment wants the specification, not an adjective. "Powerful"
tells them nothing; "105 square inch head, 275 grams" tells them everything.

**Technical when it helps, never to impress.** The League Regular wants to know the
string pattern. The Weekend Social Player does not, and using the term with them is
not expertise, it is exclusion.

**No hype adjectives.** Revolutionary, game changing, ultimate, pro level. If the
product were any of these the specification would show it.

**Never promise performance we cannot substantiate.** A racket does not add
topspin to a player who does not generate it. Claims about what equipment will do
for someone's game are the fastest way to lose the customer who knows better.

## What we do not do

We do not run false urgency. No countdown timers on evergreen offers, no "only 3
left" unless there are only three left, no invented deadlines.

We do not manufacture scarcity. If a line is genuinely low on stock we say so
because it is useful information, not as a pressure tactic.

We do not disparage competitors. A customer comparing us to a specialist
competitor is already the kind of customer we want, and running the other retailer
down insults their judgement.

## Speaking to each audience

Competitive players get specification, availability, and turnaround. They are
making a considered decision and they want the inputs. Discount language reads as
a signal that something is wrong with the product.

Recreational players get fit, comfort, and value. Technical detail is noise to
them, and price genuinely matters. Discount language is appropriate here and
nowhere else.

Returning players need orientation. What has changed since they last played,
explained without condescension. This is the hardest voice to get right, because
the temptation is either to over explain or to assume knowledge they no longer
have.

## Practical tests

Before publishing, two checks.

Would a stringer who plays say this sentence out loud to a customer standing in
front of them? If it would sound absurd spoken, it is absurd written.

Does the copy make a claim the specification does not support? If so, cut the
claim, not the specification.
"""

    docs["competitive-landscape-2026.md"] = """# Competitive Landscape

Strategy
Annual review, January 2026

## Purpose

An assessment of who we compete with and where we win. This is qualitative. We
hold no competitor pricing feed and no market share data, and every observation
here comes from public information and from what customers tell the service team.

Nothing in this document should be quoted as a measured figure.

## The specialist online retailers

Our closest competitors: comparable assortments, real stringing operations, a
similar customer, competing on expertise rather than price.

They still beat us on catalog breadth. That trade off has not changed and remains
deliberate.

Turnaround is no longer a weakness. The midwest and southeast benches added during
2025 closed the regional gap, and our current commitments are at or ahead of what
the specialists publish. This was the single most important competitive move of
the last two years.

Anecdotally they sit within a few percent of us on rackets and undercut us on
strings, which is consistent with better string buying terms than ours. We cannot
verify this and should not present it as fact.

## Mass sporting goods retailers

Compete on price and immediacy for shoes and apparel. They take the casual buyer
and the parent buyer on convenience, and do not compete for the league player.

We do not try to match them on entry level apparel pricing. Our value lines exist
to be credible at that price point, not to win it.

## Direct from manufacturer

This has changed materially since the last review and is now the fastest growing
competitive channel. Manufacturer sites have improved, their fulfilment has
improved, and the customer who knows exactly what they want increasingly buys
direct.

The 2024 assessment that this was not a near term threat was wrong.

The defence is stringing. A frame bought direct still needs stringing within
weeks, and that brings the customer back into a relationship with us. Whether that
defence holds depends on whether manufacturers move into service, which so far
they have not.

## Where we win

Stringing craft and turnaround, now in all four regions. That is the defensible
position and everything else in the assortment supports it.

## Where we lose

Catalog breadth, price on commodity apparel, and same day physical availability.
We lose the parent buyer routinely, and that remains an accepted cost.

## What we cannot say

We have no market share figure, no competitor sales data, and no reliable
competitor pricing. Any request for our share of the racket category, or for a
competitor's revenue, cannot be answered from anything we hold. An estimate
presented as a number would be an invention.
"""

    docs["competitor-landscape-2024.md"] = """# Competitive Landscape

Strategy
Annual review, spring 2024

## Purpose

An assessment of who we compete with, where we win, and where we are exposed.
This is a qualitative document. We hold no competitor pricing feed and no market
share data, and every observation here comes from public information and from
what customers tell our service team.

## The specialist online retailers

Our closest competitors. Comparable assortments, real stringing operations, and a
similar customer. They compete on expertise rather than price.

They beat us on catalog breadth, holding perhaps twice the number of active lines.
For a customer who knows exactly which obscure frame they want, that matters.

We believe we are competitive on stringing turnaround in the northeast and west,
where we have bench capacity, and materially behind in the midwest and southeast,
where we do not. Customers in those regions wait longer, and some of them stop
waiting.

## Mass sporting goods retailers

Compete on price and immediacy for shoes and apparel. They take the casual buyer
on convenience and do not seriously compete for the league player, who wants
stringing and advice they cannot provide.

We do not attempt to match them on entry level apparel pricing.

## Direct from manufacturer

Currently a minor channel. Brands sell direct but their sites are poor, their
service is worse, and the customer who wants a frame today still comes to a
retailer.

We do not consider this a near term threat. The manufacturers have shown little
appetite for the operational burden of direct retail, and their pricing does not
undercut the channel.

## Where we win

Stringing craft in the regions where we have capacity, and the relationship that
comes with a service the customer needs repeatedly.

## Where we are exposed

Regional coverage is our clearest weakness. Two of four regions have no local
bench, and the turnaround gap in those regions is the most common reason we lose a
league player.

Catalog breadth is a secondary weakness and is a deliberate trade off rather than
a failure.

## Recommendation

Bench capacity in the underserved regions should be the priority investment. The
turnaround gap is the only weakness that costs us the customer we most want to
keep, and it is the one weakness that is entirely within our control.
"""

    docs["customer-personas.md"] = """# Customer Personas

Owner: Marketing

Personas are a communication tool. They are NOT segments: segment is a behavioral
classification computed from purchase history, while a persona is a narrative
about why someone buys. Do not use a persona where a segment is required, and do
not report numbers by persona, because personas are not in the data.

## The League Regular

The core competitive customer. Plays two or three times a week in an organised
league, restrings every four to six weeks in season, and can tell you the tension
they prefer. Buys a new frame roughly every eighteen months and treats that as a
considered purchase, researched over weeks.

What they want from us: availability, turnaround, and someone who knows what a
sixteen by nineteen string pattern implies. What loses them: a restring that takes
four days in the middle of a season.

They map mostly to the competitive segment, skew to Baseline and Cordage, and
carry the highest lifetime value in the base.

## The Weekend Social Player

Plays most weekends, socially, no league. Owns one racket bought three years ago
and has never considered replacing it. Buys apparel and shoes more often than
equipment, and buys on occasion rather than need: a birthday, a new season, a
holiday.

What they want: to look and feel the part without a research project. Price
matters, but so does not feeling patronised. What loses them: technical language.

Mostly the recreational segment, skews to Kestrel and Northline, buys the largest
individual baskets in the base and the fewest of them.

## The Returning Player

Played seriously years ago, coming back after a long gap. Their equipment is
obsolete and they know it, but they do not know what has changed. High intent,
high uncertainty, and unusually responsive to guidance.

This is the most valuable persona to get right and the easiest to lose. They start
looking recreational and can become competitive within two seasons.

## The Parent Buyer

Buying for a child, usually a junior frame and shoes, price sensitive, and almost
never buying for themselves. Purchases cluster at season start.

Low lifetime value individually and worth serving because juniors grow into
league players, but do not build acquisition economics on this persona.

## How to use personas

Use them for creative direction, message testing, and deciding what a campaign
should SAY. Use segments for who a campaign should GO to. A brief that names a
persona and a segment together is doing it right.
"""

    docs["customer-service-themes.md"] = """# Customer Service Themes

Customer Operations
Quarterly review of the support queue

## What this is

A summary of what customers contact us about, written by the service team from
their own review of the queue. It is qualitative by construction: there is no
survey behind it, no scoring, and no denominator. It describes what the queue felt
like over the quarter.

It is informed opinion from the people closest to the customer, and it should be
treated as exactly that. It is not a measurement and it must not be presented as
one.

## Stringing turnaround

The dominant complaint through 2025 and the reason the service commitments were
tightened. Contacts on this topic have fallen substantially since the new
commitments took effect and the additional bench capacity came online.

The complaints that remain cluster in the week either side of league registration
deadlines, when volume peaks and the margin for error disappears. These are
capacity complaints rather than process complaints.

## Shoe sizing

The most common product complaint and the most common stated reason for a return.

Sizing runs small on the newest footwear vendor in particular, consistently by
roughly half a size. This is a known issue with a vendor still being proven, and
the service team has been advising customers to size up when that brand is
involved.

The sizing guidance on the product pages has not been updated to reflect this,
which the team has raised.

## Delivery timing

Spikes predictably in December and during the spring peak. Almost always carrier
network congestion rather than a fulfillment failure.

Distinguishing the two matters and is often got wrong internally: a carrier delay
is not something a warehouse process change will fix, and treating it as one wastes
effort. The tell is whether the delay is concentrated in specific regions or spread
evenly.

## String durability

Dominated contacts in the weeks following the product recall and has since
normalised to background levels.

The residual contacts are mostly customers checking whether their string is the
recalled one, which suggests the direct outreach did not reach everyone or was not
clear enough about which product was affected.

## Account and loyalty

A steady low volume of contacts about points expiry, usually from customers who
received the expiry warning and did not understand the rolling basis.

The programme terms are correct but the expiry notice wording is confusing. This
has been raised twice and not yet changed.

## What this document is not

It is not a satisfaction measure. We collect no satisfaction, sentiment, or Net
Promoter data of any kind.

This summary has no denominator: it says what people contacted us about, not what
share of customers felt anything. A theme appearing here does not mean most
customers experienced it, and a theme absent here does not mean nobody did, because
most unhappy customers never contact anyone.

Anyone asking for a satisfaction number should be told plainly that none exists and
that this document is not a substitute.
"""

    docs["data-and-reporting-notes.md"] = """# Data and Reporting Notes

Marketing Analytics

## Purpose

What is in the marketing reporting data, what is deliberately excluded, what is
inferred rather than observed, and what does not exist at all. Read this before
building any analysis on the warehouse.

## Known exclusions

The orders table contains rows that must never appear in marketing reporting.

**Test orders.** QA writes orders with status test into the production database.
They carry realistic amounts and are indistinguishable from real orders on
inspection. Roughly two percent of rows.

**Wholesale orders.** Wholesale is a separate business line with different unit
economics and baskets several times larger than retail. Around five percent of
rows. Including wholesale in marketing revenue overstates it substantially, and
because the baskets are large the distortion is worse than the row count suggests.

Both exclusions are enforced inside the governed metrics. Querying the orders table
directly without applying them produces an inflated revenue figure, which has
happened before and will happen again.

**Refunded orders** carry status refunded rather than completed. Revenue metrics
exclude them. Refund rate must include them, or the metric would exclude the exact
events it exists to measure.

## Churn is inferred

We are a retail business. There is no subscription and no cancellation event, so
churn is never directly observed.

Where we report churn we are reporting an inference: a customer with no completed
order in the trailing 12 months is treated as churned. This is a definition applied
to purchase silence, not a measurement of a decision.

The inference is imperfect in an obvious way. A player who simply had no equipment
need for 13 months is counted identically to one who moved to a competitor. There
is no way to distinguish them from purchase data alone, and any churn number
should be presented with that stated.

## Attribution is last touch

The final marketing touch before an order receives full credit. We cannot produce
multi touch or fractional attribution from current tracking, because the data holds
one touch per conversion rather than a path.

A customer who saw three ads, opened two emails and then searched is credited
entirely to paid search. Channel level performance figures should be read with that
in mind, particularly where channels overlap in the funnel.

## Product cost and margin

Product unit cost is held on the product record and is the CURRENT cost, not the
cost at the time of a historical sale. Margin on older orders is therefore
approximate where costs have moved.

Gross margin covers product cost only. It excludes salaries, fulfilment, shipping
cost, payment fees, and all marketing spend beyond channel level media. It is not
profit and must never be presented as though it were.

## Stock data

Stock level is a current snapshot per product. There is no movement history, no
reorder log, and no daily snapshots.

This means "are we out of stock" is answerable and "how long have we been out of
stock" is not. Do not estimate a duration from a launch date.

## What we do not collect

We collect no satisfaction, sentiment, or Net Promoter Score data. There is no
survey instrument, no survey table, and no third party feed. Questions about how
customers feel cannot be answered from this data at all.

The closest available behavioural signals are repeat purchase rate and refund rate.
Neither measures sentiment. A customer can be unhappy and still repurchase, or
perfectly satisfied and simply have no current need.

We hold no web analytics: no sessions, no traffic, no funnel above the order. No
conversion rate can be computed.

We hold no creative, ad, keyword or subject line level data. Media spend is channel
level only.

We hold no competitor pricing or market share data.

## Forecasting

This reporting layer reports actuals. It does not produce forecasts or projections.

Trend history is available and useful. A trend is not a prediction, and restating
one as though it were is the most common way an honest number becomes a dishonest
answer.
"""

    docs["email-deliverability-runbook.md"] = """# Email Deliverability Runbook

Lifecycle Marketing

## What this covers

Marketing email only: campaign sends and lifecycle sends. Transactional mail runs
on a separate subdomain and IP pool with its own escalation path, and a problem
there is an engineering incident rather than a marketing one.

## Normal ranges

Delivered rate normally sits above 97 percent of attempted sends. Anything between
97 and 99 is unremarkable.

Complaint rate should sit below 0.1 percent. Complaint rate is the number the
mailbox providers care most about and the one that does the most damage fastest.

Hard bounce rate should sit below 1 percent on an established list. A spike almost
always indicates a list hygiene problem rather than a reputation problem.

## Escalation thresholds

Delivered rate below 95 percent on two consecutive sends: stop the programme and
investigate before sending again. Continuing to send into a deliverability problem
compounds it.

Complaint rate above 0.3 percent on a single send: stop and investigate the
targeting. A complaint spike is usually a targeting failure, someone receiving
mail they did not expect, rather than a technical one.

Hard bounces above 3 percent: suspend the affected segment and review how those
addresses entered the list.

## Investigation order

Work in this order, because it goes from cheapest to most expensive to check.

First, authentication. Confirm SPF, DKIM and DMARC records resolve correctly and
have not been changed. A DNS change made for an unrelated reason is a common cause
and the quickest to rule out.

Second, list hygiene. Look at how recently the affected addresses were acquired
and whether any bulk import happened. A purchased or scraped list will destroy a
sending reputation within a few sends.

Third, content. Check for newly added links to unfamiliar domains, large image to
text ratios, and any URL shortener. Shorteners are heavily filtered.

Fourth, reputation and volume. Check whether send volume jumped sharply. A sudden
increase from an established baseline looks like a compromised account to a
mailbox provider.

## The open rate trap

A rise in raw open rate is NOT evidence of improved deliverability, and this
mistake is made repeatedly.

Privacy proxies prefetch images and register an open that no human performed. The
volume of proxy opens moves with mailbox provider behaviour and with the mix of
clients on the list, entirely independently of whether a human ever saw the
message.

This is why the governed open rate metric excludes machine opens, and why open
rate is treated as directional rather than decisive. Click rate requires a
deliberate human action and is the metric to trust when the two disagree.

To assess deliverability, use delivered rate and bounce rate. They measure whether
the message arrived. Open rate does not.

## Recovery

Reputation recovers slowly. After a serious incident, resume with the most engaged
segment only, at low volume, and rebuild over two to three weeks. Resuming at full
volume undoes the recovery immediately.
"""

    docs["email-program-overview.md"] = """# Email Program Overview

Lifecycle Marketing

## Programme structure

Email runs as three separate streams with different purposes, different sending
infrastructure, and different measurement.

**Lifecycle** is behaviour triggered: welcome series, restring reminders, winback,
points expiry notices. It sends continuously at low volume and produces the best
engagement rates in the programme because the timing is driven by the customer
rather than by a calendar.

**Campaign** is the scheduled promotional programme, roughly two to three sends a
month, rising during spring league season. The Spring League Kickoff is the
largest single campaign of the year.

**Transactional** is operational: order confirmations, shipping notices, refund
receipts. These are excluded from all marketing performance reporting. They are
not marketing, they run on separate infrastructure, and their engagement rates are
structurally different because people open receipts.

## How we measure

Open rate is reported as unique human opens divided by DELIVERED messages. Two
exclusions matter, and both are enforced by the governed metric rather than by
analyst discipline.

Machine opens are excluded. Since privacy proxies began prefetching images, a
substantial share of recorded opens never involved a human. Roughly a third of raw
opens in our data are machine opens, and that proportion moves with mailbox
provider behaviour rather than with anything we control.

Transactional messages are excluded entirely, for the reasons above.

The denominator is delivered rather than sent. Undelivered mail could not have been
opened, and including it conflates a deliverability problem with an engagement
problem.

## Why open rate is directional only

Even with machine opens excluded, open rate carries noise that has nothing to do
with whether the message worked. It is useful as a trend and unreliable as a
decision input.

Click rate is the decision metric. A click requires a deliberate human action that
no proxy performs. When open rate and click rate disagree, believe click rate.

Revenue per email delivered is the efficiency measure for the programme as a
whole, with one important caveat: it improves mechanically when send volume falls,
so it must be read alongside total delivered volume or a shrinking programme will
look like an improving one.

## Sending cadence

Campaign sends run two to three times a month outside spring, rising to weekly
during the league season peak.

Lifecycle sends are not capped by the campaign calendar but a customer will not
receive more than one marketing message in a 48 hour window, regardless of stream.

## List health

Delivered rate normally runs above 97 percent. The deliverability runbook covers
thresholds and escalation.

We do not purchase lists. Every address on the file was collected at account
creation or at explicit opt in.

## Benchmarks

Human open rate normally runs in the low twenties. Spring campaign months run a few
points hotter because league season lifts engagement across the board, and December
runs cooler alongside the reduced volume.

A month inside the normal band is not news in either direction, and reporting it as
though it were is a waste of everyone's attention.
"""

    docs["inventory-health-notes.md"] = """# Inventory Health Notes

Merchandising
Monthly review

## Reading a stock level

Stock is reported per product as a current level. Interpreting it requires the
lifecycle stage, and reading a raw number without the stage is how people reach
confident wrong conclusions.

A **core** line at zero during its selling season is a genuine failure. It means
demand was underforecast or a vendor missed a commitment, and it costs sales that
cannot be recovered.

A **clearance** line at zero is a success. Running clearance stock to zero is the
entire purpose of clearance; the alternative outcome is a write off.

A **discontinued** line at zero is expected and permanent. These lines remain in
the catalog only so that historical orders resolve to a real product.

A **new** line at zero within weeks of launch usually means the initial buy was too
conservative rather than that demand is exceptional. The correct response is a
reorder, not a celebration, and reorder feasibility depends entirely on the
vendor's lead time.

## The structural constraint

Lead time is what determines whether a stockout can be fixed.

Two of our vendors run beyond six weeks. A core stockout in either of their brands
cannot be resolved inside a season, which means the decision that caused it was
made months earlier at commitment time. These are planning failures surfacing late,
not execution failures happening now.

One vendor runs at ten days and is effectively reorderable on demand. Stockouts in
that brand are unusual and are genuinely execution problems when they occur.

This asymmetry should shape where forecasting effort goes. Precision matters most
where correction is impossible.

## Current pressure points

The long lead time brands carry the most risk going into any season, and the
autumn commitment made in spring is the single largest bet in the calendar.

The recalled string sits at zero stock and discontinued, permanently. It should not
appear in any assortment or promotion consideration.

Footwear from the newest vendor is carrying more stock than the sell through rate
justifies, a consequence of that vendor's high minimum order value. Any bet with
them is necessarily a large one.

## What stock data cannot tell you

We hold the CURRENT level only. There is no movement history, no daily snapshots,
and no reorder log in the reporting data.

This means the following questions are answerable: what is in stock now, what is
out of stock now, which lines are at risk given their stage.

And these are not: how long a line has been out of stock, how often it goes out,
what the stock level was last month, how fast a line is selling through. Estimating
any of them from a launch date or an order count would be inventing a number.

## Review cadence

Stock is reviewed monthly against lifecycle stage. Core lines below a fortnight of
cover in season are escalated to the vendor conversation immediately, because with
long lead times a fortnight of cover is already too late.
"""

    docs["loyalty-program-terms.md"] = """# Loyalty Program Terms

Marketing

## Overview

The loyalty programme rewards repeat purchase with points redeemable against
future orders. Membership is free and automatic on account creation.

The programme exists to increase purchase frequency among recreational customers,
who buy rarely and have little reason to remember us between purchases. It is
worth noting that competitive customers already buy frequently and the programme
changes their behaviour very little.

## Earning

Members earn one point per dollar of net merchandise spend.

Net means after any discount and excluding tax and shipping. A 100 dollar order
with a 20 percent discount earns 80 points.

Refunded amounts reverse the points they earned. A fully refunded order removes
all its points; a partial refund removes points proportionally. Where the reversal
would take a balance negative, the balance is set to zero rather than carrying a
debt.

Wholesale purchases do not earn points. Wholesale is a separate business line with
its own terms.

Stringing services earn points on the same basis as merchandise.

## Redemption

100 points redeem for 10 dollars off a future order, in 100 point increments.

Redemption cannot be combined with clearance pricing but can be combined with a
standard campaign discount. Points redemption is accounted separately from
discount for margin reporting and is not treated as a discount for those purposes.

Points cannot be redeemed for cash, transferred between accounts, or used to pay
for shipping.

## Expiry

Points expire 18 months after they are earned, on a rolling basis. The oldest
points are always redeemed first.

Members receive a notice 30 days before any expiry. A member with no activity for
18 months therefore receives an expiry warning, which doubles as a reactivation
touch and is one of the better performing lifecycle sends.

## Referrals

Members who refer a new customer earn 250 points once the referred customer places
a first order.

Referral credit requires the referred customer to use the member's link or code.
This is a real limitation on what we can see: a referral that happens by word of
mouth without a code is invisible to us. Our referral data therefore undercounts
actual referral influence, and the true rate is higher than anything we can
measure.

Self referral is not permitted and is blocked at signup by matching payment
details and address. Attempts are rare and are not pursued beyond blocking.

The referred customer must be genuinely new. An existing customer creating a
second account to claim referral credit forfeits both accounts' balances.

## Programme changes

Terms may change with 30 days notice to members. Points already earned are
honoured under the terms in place when they were earned.
"""

    docs["merchandising-playbook.md"] = """# Merchandising Playbook

Owner: Merchandising

How we decide what to stock, what to promote, and what to clear.

## Assortment planning

The catalog runs to roughly a hundred and twenty active lines. That number is
deliberate: below a hundred we lose credibility in rackets and strings, above a
hundred and forty the long tail stops paying for its warehouse space.

Planning runs on a season cycle. Spring league is committed the previous autumn
because of vendor lead times, which means spring assortment is a forecast rather
than a reaction. Autumn is committed in spring and has more room to adjust.

## Lifecycle stages

Every product sits in one of four stages, and the stage drives how it is treated
in campaigns and in reporting.

**New** means launched within the last four months. New lines get promotional
support and are exempt from margin targets for their first season, because the
first season is about establishing the line rather than earning from it.

**Core** is the steady state. Core lines carry the assortment, hold their margin,
and are the default in any recommendation.

**Clearance** means we are exiting the line. Clearance is priced to move, so
margin RATE falls while margin DOLLARS usually rise: discounted stock beats dead
stock, and the alternative to a clearance sale is a write off. Do not read a
clearance period as a margin problem.

**Discontinued** means no longer sold. Stock is zero and the line stays in the
catalog only so historical orders still resolve to a real product.

## Stock and availability

Stock is held centrally and reported at the product level. An out of stock line is
not automatically a problem: clearance lines are supposed to run to zero. An out
of stock CORE line in season is a real failure, and the usual cause is a vendor
lead time we did not plan around.

Because Kestrel and Apex run beyond six weeks, a core stockout in either brand
cannot be fixed inside a season. Cordage at ten days can be reordered mid season,
which is why string availability is rarely the problem.

## Promotion rules

- Never promote a line that cannot be restocked within the promotion window.
- Never promote a discontinued line.
- Clearance promotions are volume plays and are exempt from margin rate targets.
- New line promotions are exempt from margin targets for one season.
- A recalled product is withdrawn from every campaign immediately, without waiting
  for the next planning cycle.

## Margin targets

Blended gross margin target is fifty percent across the catalog. That is a blend,
not a floor: performance brands run in the low forties by design and own label
runs near seventy, and the mix is what gets us to the target.

Judging a performance brand against the fifty percent blended target is the most
common misreading of this document. Baseline at forty two percent is performing
as intended.
"""

    docs["pricing-and-discount-policy.md"] = """# Pricing and Discount Policy

Merchandising and Finance

## How list price is set

List price is set from a target margin by category, not by matching competitors. We
hold no competitor pricing feed and do not attempt to track one, so competitor
matching is not available to us even if we wanted it.

Category margin targets:

- Rackets and performance footwear: low forties. These are credibility categories
  where the brands carry pricing power and our margin is structurally thinner.
- Apparel: mid fifties, higher on own label lines.
- Strings: mid to high forties, varying by whether the line is a performance or a
  commodity string.
- Own label and services: near seventy. This is the margin that funds the thin
  categories.

The blended target across the whole catalog is fifty percent. That is a blend and
not a floor, and judging a single performance line against it is the most common
misuse of this policy.

## Discount authority

Approval scales with depth:

- Up to 15 percent: Campaign Marketing may approve within an agreed campaign plan.
- 16 to 25 percent: requires Merchandising sign off, because at this depth the
  discount is materially eroding category margin.
- Above 25 percent: clearance only, and requires Finance sign off.

Depth is calculated against list price, not against any previous promotional price.
A line already discounted 15 percent that goes to 25 requires the higher approval.

## Standing rules

Never discount a new line in its first season. The launch price establishes where
the line sits, and discounting immediately tells the customer the launch price was
not real.

Never discount performance rackets below ten percent. At the top of the range a
discount signals a quality or demand problem to precisely the customer who cares
most, and the volume gained does not compensate.

Own label may be discounted freely. The margin absorbs it, and own label exists
partly to give us a promotable lever that does not damage the pricing of the brands
we buy in.

Clearance is exempt from margin rate targets. Discounted stock beats dead stock and
the comparison is against a write off, not against full price.

## Interaction with loyalty

Loyalty point redemption is not a discount for margin purposes and is accounted
separately.

A campaign discount and a points redemption may both apply to the same order.
Redemption may not be combined with clearance pricing.

## What this policy does not cover

Wholesale pricing, which is negotiated per account under contract terms and sits
outside marketing reporting entirely.

Cost price negotiation with vendors, which is a Merchandising function governed by
the supplier agreements rather than by this document.

## Review

Category targets are reviewed quarterly against actual achieved margin. Persistent
divergence between target and actual usually indicates a mix change rather than a
pricing failure, and should be investigated as such before prices move.
"""

    docs["promo-calendar.md"] = """# Promotional Calendar

Campaign Marketing

## Purpose

The annual promotional rhythm and the reasoning behind it. This is the reference
for when campaigns run and, more importantly, for why a given month looks the way
it does.

## January: restring reset

The quietest selling month of the year. A modest restring offer runs to pull
competitive players back after the holidays.

The offer is deliberately shallow. This audience was going to restring anyway; a
deep discount would give away margin on a purchase that did not need incentivising.

## February: pre season equipment refresh

Demand begins to build ahead of spring league signups. Equipment focused, aimed at
the player who has decided this is the season they replace the frame.

Spring assortment lands in the warehouse during this month, having been committed
the previous autumn.

## March through May: spring league

The commercial heart of the year and our largest campaign window. The Spring
League Kickoff runs across the whole period.

Demand rises across every category and channel. This is the most important thing
to understand about our numbers: elevated figures in these months are seasonal, not
a step change in performance. A March number that beats February is not evidence of
anything except that it is March.

Offer structure has been stable across several years: free express shipping as the
headline, with a featured product of the season.

## June through August: summer tournament tie ins

Steady, lower intensity. Tournament tie ins rather than league messaging, because
the league audience is between seasons.

This is also the window in which disruptive work is scheduled, including site
changes that require pausing paid channels. The opportunity cost is lowest here.

Autumn assortment is committed during this period, which is the decision with the
longest lead time and the least information behind it.

## September through November: fall league and holiday build

Fall leagues start and demand recovers. Shoes over index in this window as players
replace what the summer wore out.

The holiday build begins in November, aimed at gift purchase rather than at the
player themselves.

## December: intentionally quiet

We reduce send volume and paid budget over the holidays. Clearance runs in the
second half of the month.

**Revenue dips every December by design.** This is the single most misread month in
our calendar. A December decline is not a performance problem, it is the plan
working, and diagnosing it as a problem is an error made somewhere in the business
every single year.

## Standing rule

Any month over month comparison that crosses a seasonal boundary needs the same
period prior year alongside it, or it will be misread. This applies to every
metric, not just revenue.
"""

    docs["q2-media-plan.md"] = """# Q2 Media Plan

Growth Marketing
Planning period: April through June

## Objective

Q2 covers the back half of spring league season and the transition into summer.
The objective is to sustain the acquisition volume built in March rather than to
grow it further, because the audience that responds to league season messaging has
largely converted by April.

## Budget posture

Paid search carries the largest daily budget and runs at full weight throughout
the quarter. There are no planned pauses. Spring is the wrong quarter to interrupt
the highest intent channel, and any site work that would require a pause has been
scheduled outside this window.

Paid social runs at a reduced weight against Q1. Prospecting performance softens
once league signup deadlines pass, and the budget is better held for the autumn
build.

Organic is unpaid and reported for context.

## Channel expectations

Paid search should hold roughly flat against March on attributed signups, with a
gradual decline through June as league season ends. A sharper fall would indicate
a problem rather than seasonality.

Paid social will decline against Q1 by design, in line with the budget reduction.
Do not read that decline as a performance issue.

Email carries the Spring League Kickoff through mid May, after which the summer
tournament programme takes over at lower volume.

## Creative and offer

Offer structure is unchanged from Q1: free express shipping as the headline, with
the promoted string of the season as the featured product.

No creative refresh is planned within the quarter. The spring creative was
produced in February and is intended to run to the end of the campaign.

## Measurement

Channel performance is reviewed monthly against the same month prior year rather
than against the previous month, because the intra quarter shape is steep and a
month over month read is misleading in both directions.

Cost per acquisition is the primary efficiency measure. Volume alone will look
strong in this quarter regardless of how efficiently it was bought.

## Attribution

All channel numbers in this plan are last touch. We do not have multi touch
attribution and cannot produce it from current tracking. Any question requiring
credit to be split across a path cannot be answered with this data.

## Tracking notes

Paid social spend tracking has been in place since early 2025 and is complete for
this planning period.

## Risks

The main risk is over indexing on spring performance when setting autumn targets.
Q2 numbers are inflated by seasonality and are not a baseline for anything.

A secondary risk is stock. Long lead time vendors were committed in the previous
autumn, and a spring stockout in a promoted line cannot be fixed inside the
quarter.
"""

    docs["q3-media-plan.md"] = """# Q3 Media Plan

Growth Marketing
Planning period: July through September

## Objective

Q3 spans the summer plateau and the start of the fall league build. The objective
is efficiency rather than volume: summer is the cheapest quarter in which to
absorb disruption, and the plan deliberately uses it for work that would be too
costly at any other time.

## Budget posture

Paid search is our highest intent channel and normally carries the largest daily
budget. Paid social is a secondary prospecting channel. Organic is unpaid and
reported for context only.

## Planned paid search pause

We are pausing paid search spend for a twelve day period in July while the landing
page rebuild ships. The pause is deliberate and has been approved.

The expected consequence is documented here in advance: attributed signups from
paid search will fall roughly 40 percent for the duration, with a two to three day
tail as the last clicks convert. This is a known and accepted cost of shipping the
rebuild in the quarter where it costs least.

No other channel is being changed. Organic and paid social budgets and targeting
are held flat through the period specifically so that the effect of the pause can
be isolated, and so that a signup decline in July can be attributed with
confidence rather than guessed at.

## Channel expectations

Paid search: down roughly 40 percent for the pause window, recovering within a
week of resumption.

Paid social: flat. Any movement is noise, not signal.

Email: reduced volume through the summer, in line with the tournament programme
rather than the league programme.

## Creative and offer

Summer tournament tie ins run through July and August at lower intensity than
spring. The fall build creative is produced in August for a September start.

## Measurement

Compare to the same month prior year, not to June. The seasonal step down from Q2
into Q3 is large and a month over month read will suggest a collapse that is not
happening.

Any July analysis must account for the paid search pause before drawing a
conclusion about demand.

## Attribution

All channel numbers in this plan are last touch. We do not have multi touch
attribution and cannot produce it from current tracking. Any question that
requires crediting multiple touchpoints along a path cannot be answered with this
data.

## Tracking history

Paid social spend tracking was implemented late. Spend data for paid social begins
in the seventh month of our reporting history. Earlier paid social activity
happened but was not logged, so cost per acquisition for paid social cannot be
computed for any period before that month, and should not be estimated.

## Risks

The principal risk is the pause overrunning. If the rebuild slips, the pause
extends into the fall build window where the cost is materially higher. The
decision point is the end of the second week.
"""

    docs["refund-policy-2024.md"] = """# Refund and Returns Policy

Customer Operations
Prepared for review, autumn 2024

## Purpose

This policy sets out the circumstances in which Baseline Tennis Co. accepts a
return and issues a refund. It applies to all direct to consumer orders placed
through the website. Wholesale accounts are governed separately by their contract
terms and are out of scope.

The policy balances two things: customers need enough confidence to buy equipment
they cannot handle before purchase, and the business needs protection against the
cost of returns on items that cannot be resold.

## Return window

Unused merchandise may be returned within 30 days of delivery. The window runs
from the delivery date recorded by the carrier, not from the order date, because
shipping times vary and the customer should not lose days to transit.

Merchandise must be in resaleable condition: unworn, undamaged, and with original
packaging and tags. A racket that has been played with is not resaleable and is
not returnable under this section, though it may be covered under the warranty
provisions below.

## Strings and grips

Strings are non refundable once shipped. String is cut to length and installed,
and a returned reel cannot be verified as unused or uncontaminated.

Grips follow the same principle. An unopened grip in its original wrapper may be
returned within the standard window; an opened one may not.

## Stringing and other services

All service sales are final. Stringing consumes both labour and material, neither
of which can be recovered, and the service is performed to the customer's own
specification.

Where a restring fails within a short period under normal play, the bench will
assess the frame and may redo the job at no charge. This is a discretionary
remedy rather than a refund, and the decision rests with the service manager.

## Rackets

Rackets carry a 30 day return window on the same resaleable condition basis as
other merchandise.

A restocking fee of 15 percent applies to all racket returns. Rackets are high
value items with a low turn rate, and a returned frame typically sits in stock for
several weeks before it sells again. The restocking fee recovers part of that
carrying cost.

Demo rackets are exempt from the return window entirely and are sold as final.

## Manufacturer defects

A product that fails due to a manufacturing defect is covered by the
manufacturer's warranty, which for rackets is typically 12 months from purchase.
We will handle the warranty claim on the customer's behalf rather than sending
them to the manufacturer.

A defect claim is distinct from a return. Defect claims are not subject to the 30
day window and no restocking fee applies.

## Shipping costs

Original shipping is refunded only where the return results from our error: a
wrong item shipped, a damaged item, or a defect on arrival.

Return shipping is at the customer's cost for change of mind returns. We provide
a prepaid label for our own errors.

## Processing

Approved refunds are issued to the original payment method within 10 business days
of the returned item being received and inspected. We do not issue refunds before
the item is back in our possession.

Partial refunds may be issued where an item is returned in a condition that
reduces its resale value but does not make it unsaleable.

## Escalation

A customer disputing a return decision may escalate to the Customer Operations
manager. Decisions above 500 dollars in value require manager sign off regardless
of whether they are disputed.
"""

    docs["refund-policy-2026.md"] = """# Refund and Returns Policy

Customer Operations
Effective January 1, 2026

## Purpose

This policy sets out when Baseline Tennis Co. accepts a return and issues a
refund. It applies to all direct to consumer orders. Wholesale accounts are
governed by their own contract terms and are out of scope.

The policy is deliberately more generous than the industry norm. Equipment is
difficult to evaluate before use, and a customer who is confident they can return
a frame is a customer who will buy one.

## Return window

Unused merchandise may be returned within 45 days of delivery for a full refund.
The window runs from the carrier's recorded delivery date.

Merchandise must be in resaleable condition: unworn, undamaged, with original
packaging. A frame that has been played with is not resaleable under this section,
though the defect and recall provisions below may still apply.

## Strings and grips

Strings and grips are refundable only if the packaging is unopened. Once a reel or
a grip has been opened we cannot verify it is unused, and it cannot be resold.

## Stringing and other services

Completed stringing services are not refundable, because the labour and the string
are both consumed and the work is done to the customer's own specification.

If a restring fails within 7 days under normal play, we restring again at no
charge. This is a standing commitment rather than a discretionary one, and the
bench does not need approval to honour it. Normal play excludes obvious misuse,
and that judgement sits with the bench.

## Rackets

Rackets carry a 45 day return window and a 12 month manufacturer defect warranty.
We handle warranty claims on the customer's behalf rather than referring them to
the manufacturer.

There is no restocking fee on racket returns. A restocking fee discourages exactly
the customer we most want, the one considering a first serious frame, and the
carrying cost it recovers is smaller than the sales it costs us.

Demo rackets are exempt from the return window and are sold as final.

## Recalled products

Any product under an active safety or quality recall is refundable in full at any
time. This overrides the 45 day window, overrides the packaging condition
requirement, and applies whether or not the product has been used.

Recall refunds do not require the original receipt. If the order cannot be located
we will take the customer's word for it. The reputational cost of refusing a
legitimate recall refund far exceeds the cost of occasionally honouring one that
was not.

## Shipping costs

Original shipping is refunded only where the return results from our error.

Return shipping is free on orders over 75 dollars. Below that threshold the
customer pays return shipping on change of mind returns, and we pay it where the
fault is ours.

## Processing

Refunds post to the original payment method within 5 business days of the item
being received and inspected.

For recall refunds we do not wait for the item to be returned; the refund is
issued on request and the customer may dispose of the product.

## Reporting treatment

A refund is netted out of marketing revenue reporting in the period the refund
POSTS, not the period of the original order. A refund in July against a March
order reduces July's net revenue.

This matters when reading a monthly figure: a spike in refunds can depress a month
that had nothing wrong with its own selling.

## Escalation

Return decisions may be escalated to the Customer Operations manager. Decisions
above 500 dollars require manager sign off.
"""

    docs["seasonal-planning-calendar.md"] = """# Seasonal Planning Calendar

Owner: Marketing and Merchandising

The operating rhythm of the year, with the commitments each phase requires.

## January and February: the reset

The quietest selling months and the busiest planning ones. Restring Reset runs to
pull competitive players back after the holidays, on a modest offer, because this
audience does not need a deep discount to do something they were going to do
anyway.

Spring assortment is already committed by now; this is when it lands in the
warehouse.

## March through May: spring league

The commercial heart of the year. Demand rises across every category and channel.
The Spring League Kickoff campaign runs across the whole window and is the largest
single campaign by revenue.

Everything is elevated in this window. A number that is up in April is up because
it is April. Comparisons must be against the same month last year.

## June through August: the summer plateau

Tournament tie ins and steady demand. Autumn assortment is committed here, which
is the decision with the longest lead time and the least information behind it.

This is also when paid budgets are most often paused for site work, because the
opportunity cost is lowest.

## September through November: the fall build

Fall leagues start and demand recovers. Shoes over-index in this window as players
replace what a summer wore out.

## December: deliberately quiet

Send volume and paid budget are cut over the holidays. Revenue dips every December
by design, and clearance runs in the second half of the month.

A December decline is not a performance problem. Diagnosing it as one is the most
common analytical error in this business, and it is made every year.

## Standing rule

Any month over month comparison crossing a seasonal boundary needs the same period
prior year alongside it, or it will be misread.
"""

    docs["segmentation-guide.md"] = """# Customer Segmentation Guide

Marketing Analytics

## Purpose

We maintain exactly two behavioural segments. Every customer is assigned to one.
This guide defines them, states the criteria precisely, and sets out how they may
and may not be used.

Two segments is a deliberate choice. More segments produce splits too small to act
on and encourage analysis that cannot be turned into a decision.

## Competitive

A customer is classified competitive when they meet either criterion:

- Two or more restrings, meaning a string purchase or a stringing service, within
  a trailing 12 month period, OR
- A performance racket purchase, defined as a racket with a head size of 100
  square inches or smaller at a price point above 150 dollars.

Either criterion alone is sufficient. The restring criterion catches the player who
plays enough to wear out strings; the racket criterion catches the player who has
invested in equipment that only makes sense for someone playing seriously.

## Recreational

Everyone else.

Recreational customers buy occasionally, skew toward apparel and entry level
equipment, are price sensitive, and respond to discount and seasonal messaging
rather than to specification and availability.

## What the segments actually look like

Competitive customers buy more often and in smaller baskets. Strings dominate
their order mix. They are worth roughly twice as much over their lifetime as a
recreational customer.

Recreational customers buy rarely and in larger baskets, skewing to apparel and
shoes.

These two effects very nearly cancel in average order value, which produces a
counter intuitive and important result: the two segments have almost the same
average order value despite one being worth twice the other. Ranking segment value
by average order value would suggest they are equally valuable. Use lifetime value
for value questions, always.

## Rules of use

Segment is a behavioural classification computed from purchase history. It is not
self reported and it is not a preference the customer expressed.

It is recomputed monthly, so a customer can move between segments. A recreational
customer who takes up league play will be reclassified within a month or two of
their behaviour changing.

Segment is available as a dimension on revenue, order value, lifetime value, and
most other governed metrics.

## What segment is not

Segment is not a skill rating. A competitive classification means someone buys like
a serious player, not that they are good.

Segment is not a persona. Personas are narrative descriptions used for creative
direction and are not present in the data. A brief that names both a persona and a
segment is using each correctly.

Segment must not be used for satisfaction or sentiment inference. We collect no
satisfaction data of any kind, and a behavioural classification cannot substitute
for it. A competitive customer is not a happy customer; they are a frequent one.
"""

    docs["shipping-and-fulfillment.md"] = """# Shipping and Fulfillment

Customer Operations

## Service levels

Standard ground ships within one business day of the order being placed and
delivers in three to five business days. This is the default and covers the large
majority of orders.

Expedited ships same day when ordered before 2pm and delivers in two business
days. It is priced at cost plus a small handling charge rather than as a profit
line, because a customer who needs a frame before a weekend match is a customer
worth keeping.

We ship within the United States only. We do not ship to freight forwarders, and
orders to known forwarder addresses are cancelled and refunded.

## Order cutoffs

Orders placed before 2pm local warehouse time ship the same day where the items
are in stock. Orders after that cutoff ship the next business day.

The cutoff is earlier during the spring peak, typically noon, because pick and
pack capacity is the binding constraint rather than carrier collection times.

## Items requiring stringing

A racket ordered with stringing ships after the restring completes, which adds two
business days to the fulfillment timeline on top of the shipping time.

This is the single most common source of delivery expectation mismatches. The
checkout shows the combined estimate, but customers frequently read only the
shipping estimate. Service should set expectations explicitly on these orders.

## Free shipping thresholds

Outbound shipping is free on orders over 75 dollars. Below that a flat rate
applies.

Return shipping is free on orders over 75 dollars. Below that the customer pays
return shipping on change of mind returns, and we always pay where the fault is
ours.

## Split shipments

Where an order contains both in stock and backordered items we ship the in stock
portion immediately at no additional charge rather than holding the whole order.

The customer is notified of the split. We do not silently partial ship, because a
partial delivery with no warning reads as a lost item.

## Carrier issues

Delivery timing complaints spike predictably in December and during the spring
peak, and are usually carrier network congestion rather than a fulfillment
failure. Distinguishing the two matters: a carrier delay is not something a
warehouse process change will fix.

Lost shipments are reshipped without requiring the customer to wait out a carrier
investigation. The investigation continues in parallel and is our problem, not
theirs.

## Damage in transit

Items damaged in transit are replaced immediately on report, with a photograph
requested but not required. We claim against the carrier separately.

Rackets are shipped in a rigid tube for exactly this reason; frame damage in
transit is rare and almost always indicates the tube was omitted.
"""

    docs["spring-campaign-recap.md"] = """# Spring League Kickoff: Campaign Recap

Campaign Marketing
Prepared the week the campaign closed

## Headline

The Spring League Kickoff drove our strongest spring on record. Revenue on campaign
attributed orders came in well ahead of the prior year, against a budget that was
broadly flat.

Full figures are in the summary table below. They were pulled from the orders
export the week the campaign closed.

## Method note

The revenue figure in this deck is GROSS booked revenue on campaign attributed
orders. It does not net out refunds and it does not exclude any order status.

Finance reports gross. Marketing reports net of refunds. These two numbers will not
match, and anyone comparing this deck to a marketing performance report should
expect a difference.

This deck was produced once, at campaign close, and has not been restated since.

## What ran

The campaign ran from the start of March through mid May, across email as the
primary channel with paid support in the peak weeks.

Offer structure was unchanged from the prior year: free express shipping as the
headline, with a featured string of the season as the promoted product.

Send volume was the highest of any campaign in the year, with the list segmented
into competitive and recreational streams carrying different creative.

## Product mix

Strings led the campaign, as expected in league season. Rackets over indexed
against their usual share, which is consistent with the pre season refresh
behaviour we see every spring.

One promoted string was subsequently recalled. That happened after this deck was
prepared, and nothing in the figures here accounts for it. The recall notice covers
the scope and the remediation.

## What worked

Timing against league signup deadlines mattered more than the offer. The weeks
immediately before local league registration closed were the strongest, and the
offer was identical throughout.

The segmented creative outperformed the prior year's single creative on click rate
in both streams, with the larger gain in the recreational stream.

## What did not

Paid social support underdelivered against plan. Prospecting into a seasonal peak
proved less efficient than expected, and the budget would have returned more in
email or paid search.

The featured product choice concentrated risk in a single line, which the
subsequent recall made obvious. Future campaigns should feature a small set rather
than a single product.

## Recommendations

Keep the offer structure; it is not the lever. Move the paid social budget. Feature
three products rather than one. Start the send sequence a week earlier to capture
more of the pre registration window.
"""

    docs["string-recall-notice.md"] = """# Product Recall Notice

Product Quality

## Summary

A string product in our range has been recalled following quality testing. This
notice covers the scope, the remediation offered, and the reporting implications.

## What was found

Routine quality testing identified premature fraying under normal tension. The
affected string can break earlier than its specification suggests, and an
unexpected break at tension risks frame damage on the racket it is installed in.

The failure mode is not a safety risk to the player. It is a durability and
consequential damage issue.

## Scope

All lots of the affected string are recalled. The product has been withdrawn from
sale, its stock is zeroed, and it is marked discontinued in the catalog.

The product was actively promoted during the Spring League Kickoff campaign, so a
meaningful share of the affected customers were acquired or reactivated through
that campaign. That concentration matters for how the aftermath reads in the data.

## Remediation

Affected customers are offered a full refund at any time, regardless of the
standard return window and regardless of whether the packaging was opened. Recall
refunds do not require the original receipt.

Customers who had the string installed as part of a stringing service are being
contacted directly and offered a free restring with a comparable string. We are not
waiting for them to contact us.

Where a frame was damaged by a break attributable to the recalled string, the frame
is replaced at our cost. These cases are handled individually by Product Quality
rather than at the bench.

## Supplier position

The manufacturer holds the liability under our supply agreement and has accepted
it. Our remediation costs are recoverable, though that is a commercial matter and
does not affect what we offer customers.

## Reporting implications

This section matters for anyone analysing the period.

Customer behaviour after the recall date should not be read as ordinary campaign
performance. Any repeat purchase comparison spanning the recall date is confounded
by the recall itself.

Purchases made BEFORE the recall date carry no exposure to it. A cohort defined
across the recall boundary mixes exposed and unexposed customers and will produce a
diluted and misleading result.

Refund rate in periods after the recall date includes recall remediation. That is a
deliberate policy action rather than ordinary product dissatisfaction, and reading
the elevated refund rate as a product quality trend across the range would be wrong.

Any divergence claim about the affected cohort should be restricted to behaviour
after the recall date, and should be framed as association rather than cause: these
customers also received other messages and had other reasons to buy or not buy.

## Communications

Direct contact to affected customers. No general announcement, because the affected
population is identifiable and a broad notice would alarm customers who bought a
different string.
"""

    docs["stringing-operations-manual.md"] = """# Stringing Operations Manual

Owner: Service Operations

This manual covers the stringing service end to end. It is the reference document
for the service, and it is long: use the section headings.

## 1. Service overview

Stringing is the defensible core of the business. Every other part of the
assortment supports it, and it is the single reason a League Regular chooses a
specialist over a mass retailer or a direct-from-brand purchase.

The service operates from four regional benches: northeast, southeast, midwest
and west. Northeast and west are the original benches and carry the most
capacity. Midwest and southeast were added during 2025, which is what made the
tightened 2026 turnaround commitments achievable.

## 2. Capacity and staffing

Each bench runs one to three stringers depending on season. Spring league season
roughly doubles volume against the winter baseline, and benches staff up from
February. A trained stringer completes eight to twelve frames a day depending on
complexity; a hybrid job or a customisation takes materially longer.

Capacity planning is done against the previous year's same-month volume, adjusted
for the spring lift. The failure mode is understaffing in early March, because
demand rises before the league calendar formally starts.

## 3. Intake and identification

Every frame taken in is tagged with the customer, the requested tension, the
string selection, and any special instruction. Frames are photographed at intake.
This exists because of a small number of historical disputes about pre-existing
frame damage, and the photograph resolves them.

A frame arriving with no tension specified is strung at the midpoint of the
manufacturer's recommended range, and the customer is told that is what happened.

## 4. String selection guidance

Selection is a conversation, not a default. The three questions that matter are
how often the player breaks strings, what they want from the string, and what
they are willing to spend.

Frequent breakers are directed to durable polyester in a thicker gauge. Players
chasing feel are directed to multifilament or natural gut, with the caveat that it
will not last. Most league players end up on a hybrid, and hybrids are the most
common job on the bench.

Own label string is a legitimate recommendation for a recreational player and is
not a legitimate recommendation for a League Regular, who will notice.

## 5. Tension standards

Tension is the most consequential setting and the one most often got wrong.

Adult frames are strung to the customer's stated tension. Where none is stated,
the midpoint of the manufacturer's recommended range applies, which for most
modern frames lands between fifty two and fifty six pounds.

**Junior frames are strung at forty eight pounds unless the customer specifies
otherwise.** This is deliberately below adult tension: junior players generate
less racket head speed, and a lower tension gives them more depth without more
effort. Stringing a junior frame at adult tension is the most common avoidable
error on the bench, and it produces a racket the child cannot use properly.

Frames older than roughly fifteen years are strung five pounds below the stated
tension regardless of what is requested, because older frames are more likely to
fail under load. The customer is informed.

## 6. Turnaround

Current commitments are in the 2026 Stringing SLA and this manual does not restate
them, because they change more often than this document does. Refer to the SLA.

The operational note is that turnaround is measured from intake, not from when the
frame reaches the bench, and transit between a regional collection point and a
bench counts against the commitment.

## 7. Quality control

Every completed job is checked for even tension across the string bed, correct
knot placement, and no frame damage. A job failing the check is redone before it
goes back to the customer.

Failure rates run well under one percent and are almost entirely knot placement,
which is a training issue rather than an equipment one.

## 8. Warranty and remedy

A restring that fails within the SLA window under normal play is redone at no
charge. Normal play excludes obvious misuse, and the bench makes that judgement.

A frame damaged during stringing is replaced at our cost. This is rare and is
always escalated to Service Operations rather than settled at the bench.

## 9. Equipment and maintenance

Each bench runs a constant pull electronic machine, calibrated monthly. A machine
out of calibration produces tension that reads correct and plays wrong, which is
the hardest fault to detect from the customer side, and monthly calibration is
non negotiable for that reason.

Consumables are ordered against the string vendor's ten day lead time, which is
short enough that string stockouts on the bench are rare.

## 10. Reporting note

Stringing services appear in the product catalog as the services category. Volume
is low relative to merchandise, well under thirty orders a month across the whole
business, which is below the reliability threshold for category level reporting.
Services numbers are real but statistically thin and must be labelled directional.

This is a reporting caveat, not a statement about the importance of the service.
Stringing drives retention far beyond its direct revenue.
"""

    docs["stringing-service-faq.md"] = """# Stringing Service FAQ

Service Operations
Customer facing reference

## Turnaround

**How long does a restring take?** Standard turnaround is two business days from
when we receive the frame. Same day service is available at a premium in all
regions.

**Does the clock start when I drop it off?** Yes, from the point the frame enters
our possession, including at a collection point. Transit to the bench counts
against our commitment, not yours.

**What if you are running late?** We contact you before the deadline, not after.
If we cannot meet the commitment you will hear from us while there is still time
to make other arrangements.

## Tension

**What tension do you use?** Whatever you specify, within a pound.

**What if I do not specify?** We use the midpoint of the manufacturer's
recommended range for your frame and tell you what that was.

**I do not know what tension I want.** Tell us how the current string bed feels.
Too much power and not enough control usually means going tighter; too much effort
for depth usually means going looser. The bench will make a recommendation and
note it so the next restring can build on it.

**Can I get different tensions on mains and crosses?** Yes. Specify both.

## String choice

**Can you string with string I supply?** Yes, at labour only pricing. Bring enough
length; a short reel means we stop and contact you.

**What string should I use?** It depends on how often you break strings, what you
want from the string, and your budget. If you break strings frequently, durable
polyester in a thicker gauge. If you want feel, multifilament or natural gut,
accepting that it will not last as long. Most league players end up on a hybrid.

**What is a hybrid?** Different string in the mains and the crosses, usually a
durable polyester in one and a softer string in the other. It is the most common
job on our bench.

## Refunds and remedies

**Is the service refundable?** Completed services are not refundable. The string
and the labour are both consumed and the work is done to your specification.

**What if the string breaks straight away?** A restring that fails within seven
days under normal play is redone at no charge. Normal play excludes frame contact
with a hard surface or damage from something other than a ball.

**What if you damage my frame?** We replace it at our cost. We photograph every
frame at intake specifically so that pre-existing damage is not disputed in either
direction.

## Practicalities

**Do you string junior frames?** Yes, and we string them at a lower tension than
adult frames by default because junior players generate less racket head speed.

**How often should I restring?** A common guideline is as many times per year as
you play per week. A league player hitting three times a week restrings roughly
every four to six weeks in season.

**Do you do grips?** Yes, replacement grips and overgrips, usually while you wait.

## Volume note

Stringing services are a small share of total orders, typically a few dozen a
month across the whole business. Category level reporting on services is based on
thin volume and should be read as directional rather than precise.
"""

    docs["stringing-sla-2025.md"] = """# Stringing Service Level Agreement

Service Operations
Effective January 1, 2025

## Scope

This agreement covers the commitments we make to customers using the stringing
service, across all regions where the service operates. It is the reference for
what the customer is promised and what the bench is measured against.

## Turnaround

Standard restring turnaround is three business days from intake.

Intake is the point at which the frame enters our possession, whether at a
regional collection point or by carrier. Transit from a collection point to a
bench counts against the commitment, which is why regions without a local bench
run closer to the limit.

Same day service is available at a premium in the northeast and west regions only.
These are the regions with sufficient bench capacity to absorb an interrupt
without pushing standard jobs past their commitment.

Midwest and southeast have no same day option. Frames from those regions are
routed to the nearest bench with capacity.

## Tension accuracy

We string to the customer's specified tension within plus or minus two pounds.

Where no tension is specified we string to the midpoint of the manufacturer's
recommended range for the frame and tell the customer what we used.

The two pound tolerance reflects machine calibration drift between monthly
service intervals. A player sensitive enough to detect two pounds should specify
a tension and request a calibration check.

## Failure remedy

A restring that fails within five days under normal play is redone at no charge.

Normal play excludes visible misuse: frame contact with a hard surface, string
cutting from a foreign object, or damage consistent with the racket being used
against something other than a ball.

The bench makes this assessment. Where the assessment is disputed the default is
to redo the job, because the cost of a restring is smaller than the cost of the
argument.

## Capacity and seasonality

Spring league season roughly doubles volume against the winter baseline. Benches
staff up from February, and the commitments in this agreement hold through the
peak.

Where a bench cannot meet the standard commitment, the customer is contacted
before the deadline rather than after it. A late job we warned about is a
different customer experience from a late job we did not.

## Measurement

Turnaround is measured from intake timestamp to completion timestamp. Jobs are
reported weekly by bench, with the share meeting commitment as the headline
figure.

The target is 95 percent of jobs within commitment. Below 90 percent for two
consecutive weeks triggers a capacity review.

## Exclusions

Frames arriving damaged are photographed and the customer is contacted before any
work begins. The turnaround clock stops until the customer responds.

Customer supplied string that proves unsuitable, for example a reel with
insufficient length, also stops the clock.
"""

    docs["stringing-sla-2026.md"] = """# Stringing Service Level Agreement

Service Operations
Effective January 1, 2026

## Scope

This agreement covers the commitments we make to customers using the stringing
service, across all regions. It is the reference for what the customer is promised
and what the bench is measured against.

## Turnaround

Standard restring turnaround is two business days from intake.

Intake is the point the frame enters our possession, at a regional collection
point or by carrier. Transit between a collection point and a bench counts against
the commitment.

Same day service is available at a premium in all four regions. The midwest and
southeast benches added during 2025 carry enough capacity to absorb interrupts
without pushing standard jobs past commitment, which was the constraint that
previously limited same day service to the northeast and west.

## Tension accuracy

We string to the customer's specified tension within plus or minus one pound.

Where no tension is specified we use the midpoint of the manufacturer's
recommended range and tell the customer.

The tighter tolerance is supported by moving machine calibration from monthly to
fortnightly. A machine out of calibration produces tension that reads correct and
plays wrong, which is the hardest fault for a customer to articulate and the most
damaging to trust.

## Failure remedy

A restring that fails within seven days under normal play is redone at no charge.

Normal play excludes visible misuse: frame contact with a hard surface, cutting
from a foreign object, or damage inconsistent with hitting a ball.

The bench assesses. Where the assessment is disputed the default is to redo, on
the same reasoning as always: the restring costs less than the argument.

## Why these commitments changed

Turnaround was the single most cited reason for losing regular league players to
specialist competitors. Three days spans a weekend for a Friday intake, and a
league player who cannot get their frame back before a Saturday match will find
someone who can.

The 2025 capacity expansion in the midwest and southeast is what made the tighter
commitments achievable. They are not aspirational targets; they are what the
current bench footprint supports.

## Capacity and seasonality

Spring league season roughly doubles volume. Benches staff up from February and
these commitments hold through the peak.

Where a bench cannot meet commitment the customer is contacted before the
deadline, not after.

## Measurement

Turnaround is measured intake to completion, reported weekly by bench, with share
meeting commitment as the headline.

Target is 97 percent within commitment, raised from 95 alongside the tighter
turnaround. Below 92 percent for two consecutive weeks triggers a capacity review.

## Exclusions

Frames arriving damaged are photographed and the customer contacted before work
begins; the clock stops until they respond. Unsuitable customer supplied string
also stops the clock.
"""

    docs["transactional-email-operations.md"] = """# Transactional Email Operations

Engineering

## Scope

This document covers operational email: order confirmations, shipping notices,
delivery notifications, refund receipts, password resets, and account security
notices.

It does not cover marketing email, which is a separate system with separate
infrastructure, separate ownership and separate escalation.

## Why the systems are separated

Transactional and marketing mail send from different subdomains and different IP
pools. This is deliberate and non negotiable.

The reason is blast radius. If marketing sending reputation is damaged, by a
targeting mistake or a list problem, order confirmations must continue to arrive.
A customer who does not receive a receipt assumes the order failed and contacts
support, or worse, orders again.

The two systems share no configuration, no sending domain, and no reputation.

## Performance characteristics

Transactional delivery runs above 99 percent. Open rates run above 40 percent.

Both figures are far higher than marketing mail and that is entirely expected.
People open receipts. A shipping notification is information the recipient
actively wants, arriving at the moment they want it.

These numbers must NEVER be mixed into marketing reporting. An open rate that
includes transactional mail is meaningless as a measure of campaign performance:
it is dominated by receipts and moves with order volume rather than with anything
marketing did.

The governed email metrics exclude transactional mail specifically for this reason.

## Monitoring

Delivery is monitored continuously with alerting on failure rate rather than on
volume. A drop in send volume is normal, since it tracks order volume; a rise in
failure rate is not.

Queue depth is the leading indicator. A growing queue means sends are failing or
slowing before the failure rate reflects it.

## Escalation

A transactional delivery failure is an ENGINEERING incident. Page the on call
engineer.

Do not route it through the marketing deliverability runbook. That runbook covers a
different system, different infrastructure, and different failure modes, and
following it will waste time investigating a marketing reputation problem that
cannot affect this system.

Severity is set by what is failing. Order confirmations and password resets are
highest severity, because a customer is actively blocked. Shipping notices are
lower, because the information arrives eventually through order status.

## Content ownership

Transactional templates are owned by Engineering with copy review by Marketing.
Marketing may not change a template without an engineering release, because the
templates contain order data bindings.

Adding a promotional message to a transactional email is not permitted. It changes
the character of the message, risks the separation the two systems exist to
maintain, and in some jurisdictions changes the consent basis on which it is sent.
"""

    docs["supplier-terms-and-lead-times.md"] = """# Supplier Terms and Lead Times

Merchandising
Vendor reference

## Purpose

The commercial terms we hold with each vendor, and what those terms mean for
planning. Lead time is the number that constrains the calendar; everything else
here is secondary to it.

## Meridian Sports Group

United States. Lead time 14 days. Payment terms net 30. Minimum order 5,000
dollars. Supplying us since early 2023.

Our primary racket and footwear vendor. Reliable delivery, rarely discounts, and
the shortest lead time of any equipment supplier. The short lead time is why we
can carry their lines with lower cover than we need elsewhere.

## Kestrel Athletic

Taiwan. Lead time 45 days. Payment terms net 60. Minimum order 12,000 dollars.
Supplying us since mid 2023.

The volume vendor across rackets, footwear and apparel, and the best unit
economics in the equipment range. The 45 day lead time means spring stock must be
committed the previous autumn, and a stockout in season cannot be corrected.

The net 60 terms partly offset the working capital cost of ordering that far
ahead, which is the reason those terms were negotiated.

## Northline Textiles

Portugal. Lead time 28 days. Payment terms net 45. Minimum order 4,000 dollars.
Supplying us since early 2024.

Apparel only. The low minimum order is the reason we use them: it makes testing a
new line possible without committing to a container, and most apparel experiments
start here before moving to a higher volume vendor if they work.

Quality has been consistent. Lead time is moderate enough to reorder within a
season if a line moves faster than planned.

## Cordage Works

United States. Lead time 10 days. Payment terms net 30. Minimum order 1,500
dollars. Supplying us since early 2023.

String specialist and the shortest lead time of any vendor. Effectively
reorderable on demand, which is why string stockouts are rare while footwear
stockouts are not.

Cordage manufactured the string subject to the recall and holds the liability for
it under our supply agreement. That has been accepted and is not in dispute.

## Apex Court Supply

Vietnam. Lead time 52 days. Payment terms net 60. Minimum order 15,000 dollars.
Supplying us since mid 2024.

Newest vendor and the cheapest footwear in the range at the best margin we get on
shoes. Quality is still being proven and sizing runs consistently small.

The combination of the longest lead time and the highest minimum order means every
Apex commitment is a large bet made a long way in advance. That is the main risk in
the footwear category.

## Planning implications

Order the long lead time vendors first and with the most care. Kestrel and Apex
between them cover most of the footwear range and all of the entry price points,
and neither can be corrected inside a season.

Cordage can absorb forecast error. Meridian can absorb some. The others cannot.

Payment terms run net 30 domestically and net 60 overseas, which means the overseas
vendors are financing part of the longer lead time. That is deliberate and was the
trade in every one of those negotiations.

## Review

Vendor terms are reviewed annually. A vendor missing two consecutive lead time
commitments goes on review regardless of the terms, because a lead time we cannot
rely on is worse than a longer one we can.
"""

    for name, body in docs.items():
        with open(os.path.join(DOCS_DIR, name), "w") as f:
            f.write(body)
    return list(docs)

# ---------------------------------------------------------------- benchmarks


def compute_benchmarks(conn, spring_id):
    """Derive benchmark bands from the seeded data so judgments are consistent."""
    cur = conn.cursor()

    def scalar(sql, params=()):
        r = cur.execute(sql, params).fetchone()
        return r[0] if r and r[0] is not None else 0

    def monthly_series(sql, params=()):
        return [row[1] for row in cur.execute(sql, params).fetchall()]

    MARKETING = "status = 'completed' AND channel != 'wholesale'"

    net_by_month = monthly_series(f"""
        SELECT substr(order_date,1,7) m, SUM(gross_amount - refund_amount)
        FROM orders WHERE {MARKETING} GROUP BY m ORDER BY m""")
    aov_by_month = monthly_series(f"""
        SELECT substr(order_date,1,7) m,
               SUM(gross_amount - refund_amount)*1.0/COUNT(*)
        FROM orders WHERE {MARKETING} GROUP BY m ORDER BY m""")
    open_by_month = monthly_series("""
        SELECT substr(send_date,1,7) m,
               SUM(CASE WHEN opened=1 AND machine_opened=0 THEN 1 ELSE 0 END)*1.0
               / NULLIF(SUM(delivered),0)
        FROM email_sends WHERE email_type != 'transactional' AND delivered=1
        GROUP BY m ORDER BY m""")
    click_by_month = monthly_series("""
        SELECT substr(send_date,1,7) m,
               SUM(clicked)*1.0/NULLIF(SUM(delivered),0)
        FROM email_sends WHERE email_type != 'transactional' AND delivered=1
        GROUP BY m ORDER BY m""")
    signups_by_month = monthly_series("""
        SELECT substr(signup_date,1,7) m, COUNT(*) FROM customers
        GROUP BY m ORDER BY m""")
    refund_by_month = monthly_series("""
        SELECT substr(order_date,1,7) m,
               SUM(refund_amount)*1.0/NULLIF(SUM(gross_amount),0)
        FROM orders WHERE status IN ('completed','refunded') AND channel != 'wholesale'
        GROUP BY m ORDER BY m""")
    rpe_by_month = monthly_series("""
        SELECT m, net/NULLIF(delivered,0) FROM (
          SELECT substr(o.order_date,1,7) m, SUM(o.gross_amount-o.refund_amount) net,
                 (SELECT SUM(delivered) FROM email_sends e
                  WHERE substr(e.send_date,1,7)=substr(o.order_date,1,7)
                    AND e.email_type != 'transactional') delivered
          FROM orders o WHERE o.status='completed' AND o.channel='email'
          GROUP BY m) ORDER BY m""")
    cac_by_channel = {
        row[0]: row[1] for row in cur.execute("""
        SELECT channel, SUM(spend)/NULLIF(SUM(attributed_signups),0)
        FROM ad_spend WHERE spend > 0 GROUP BY channel""").fetchall()
    }
    # repeat purchase rate as of the last complete month, trailing 12m
    rpr = scalar(f"""
        WITH active AS (
          SELECT customer_id, COUNT(*) n FROM orders
          WHERE {MARKETING} AND order_date >= date(?, '-12 months')
            AND order_date <= ?
          GROUP BY customer_id)
        SELECT SUM(CASE WHEN n >= 2 THEN 1 ELSE 0 END)*1.0/COUNT(*) FROM active""",
        (LAST_MONTH_END.isoformat(), LAST_MONTH_END.isoformat()))
    ltv = {row[0]: row[1] for row in cur.execute(f"""
        SELECT c.segment, SUM(o.gross_amount-o.refund_amount)*1.0/
               COUNT(DISTINCT c.id)
        FROM customers c LEFT JOIN orders o
          ON o.customer_id=c.id AND o.status='completed' AND o.channel!='wholesale'
        GROUP BY c.segment""").fetchall()}

    def band(series, trim=0.15):
        vals = sorted(v for v in series if v)
        if not vals:
            return (0.0, 0.0)
        k = max(1, int(len(vals) * trim))
        core = vals[k:-k] if len(vals) > 2 * k else vals
        return (round(min(core), 4), round(max(core), 4))

    yaml_lines = ["# benchmarks.yaml",
                  "# GENERATED by data/seed.py from the seeded data. Do not hand edit.",
                  "# Bands are the trimmed min/max of the monthly series, so the",
                  "# 'is this good' judgment is internally consistent with the data.",
                  f"generated_from_months: {MONTHS}",
                  f"window: \"{FIRST_MONTH.isoformat()} to {LAST_MONTH_END.isoformat()}\"",
                  "metrics:"]

    def emit(mid, series, direction, note=""):
        lo, hi = band(series)
        yaml_lines.append(f"  {mid}:")
        yaml_lines.append(f"    baseline_low: {lo}")
        yaml_lines.append(f"    baseline_high: {hi}")
        yaml_lines.append(f"    direction: {direction}")
        if series:
            yaml_lines.append(f"    latest: {round(series[-1], 4) if series[-1] else 0}")
        if note:
            yaml_lines.append(f"    note: \"{note}\"")

    emit("net_revenue", net_by_month, "higher_better",
         "Monthly band. March through May run above band by design; December runs below.")
    emit("email_open_rate", open_by_month, "higher_better",
         "Human opens only. Machine opens excluded, so this band is not comparable to raw open rate.")
    emit("email_click_rate", click_by_month, "higher_better")
    emit("new_customer_signups", signups_by_month, "higher_better")
    emit("aov", aov_by_month, "higher_better")
    emit("refund_rate", refund_by_month, "lower_better")
    emit("revenue_per_email", rpe_by_month, "higher_better",
         "Non additive. Re derive per period; never average period values.")
    yaml_lines.append("  repeat_purchase_rate:")
    yaml_lines.append(f"    baseline_low: {round(max(0.0, rpr - 0.035), 4)}")
    yaml_lines.append(f"    baseline_high: {round(rpr + 0.035, 4)}")
    yaml_lines.append("    direction: higher_better")
    yaml_lines.append(f"    latest: {round(rpr, 4)}")
    yaml_lines.append("    note: \"Trailing 12 month basis. Cohort filtered values are comparable to this band only when the cohort is large.\"")
    yaml_lines.append("  cac:")
    yaml_lines.append("    direction: lower_better")
    yaml_lines.append("    by_channel:")
    for ch, v in sorted(cac_by_channel.items()):
        yaml_lines.append(f"      {ch}: {round(v, 2)}")
    yaml_lines.append("    note: \"paid_social has no spend before the tracking start month; CAC there is unavailable for early periods.\"")
    yaml_lines.append("  segment_ltv:")
    yaml_lines.append("    direction: higher_better")
    yaml_lines.append("    by_segment:")
    for sg, v in sorted(ltv.items()):
        yaml_lines.append(f"      {sg}: {round(v or 0, 2)}")

    # Spring campaign net vs gross, used by the conflict question.
    spring_net = scalar(f"""SELECT SUM(gross_amount - refund_amount) FROM orders
                            WHERE campaign_id = ? AND {MARKETING}""", (spring_id,))
    spring_gross = scalar("""SELECT SUM(gross_amount) FROM orders
                             WHERE campaign_id = ?""", (spring_id,))
    yaml_lines.append("campaign_reference:")
    yaml_lines.append(f"  spring_campaign_id: {spring_id}")
    yaml_lines.append(f"  spring_net_revenue: {round(spring_net, 2)}")
    yaml_lines.append(f"  spring_gross_all_rows: {round(spring_gross, 2)}")
    yaml_lines.append("  note: \"The recap deck quotes the gross figure over all rows. The governed metric is net and excludes test and wholesale rows. The governed number is authoritative.\"")

    os.makedirs(os.path.dirname(BENCH_PATH), exist_ok=True)
    with open(BENCH_PATH, "w") as f:
        f.write("\n".join(yaml_lines) + "\n")
    return spring_net, spring_gross


# ---------------------------------------------------------------- assertions


def verify(conn, planted, pause, spring_id):
    """Every planted signal, coverage requirement, and gap is checked here."""
    cur = conn.cursor()
    failures = []

    def check(label, ok, detail=""):
        if ok:
            print(f"  PASS  {label}")
        else:
            failures.append(f"{label} :: {detail}")
            print(f"  FAIL  {label}  {detail}")

    def scalar(sql, params=()):
        r = cur.execute(sql, params).fetchone()
        return r[0] if r and r[0] is not None else 0

    MARKETING = "status = 'completed' AND channel != 'wholesale'"

    print("\n-- table volumes")
    n_cust = scalar("SELECT COUNT(*) FROM customers")
    n_ord = scalar("SELECT COUNT(*) FROM orders")
    n_send = scalar("SELECT COUNT(*) FROM email_sends")
    check("customers ~18,000", 17_000 <= n_cust <= 19_500, f"got {n_cust}")
    check("orders >= 45,000", n_ord >= 45_000, f"got {n_ord}")
    check("email_sends >= 300,000", n_send >= 300_000, f"got {n_send}")
    check("products ~120", 110 <= scalar("SELECT COUNT(*) FROM products") <= 130)
    check("campaigns >= 45", scalar("SELECT COUNT(*) FROM campaigns") >= 45)

    print("\n-- the raw SQL trap: test and wholesale rows exist")
    p_test = scalar("SELECT COUNT(*) FROM orders WHERE status='test'") / n_ord
    p_ws = scalar("SELECT COUNT(*) FROM orders WHERE channel='wholesale'") / n_ord
    check("test rows ~2%", 0.01 <= p_test <= 0.035, f"got {p_test:.3f}")
    check("wholesale rows ~5%", 0.03 <= p_ws <= 0.075, f"got {p_ws:.3f}")
    gross_all = scalar("SELECT SUM(gross_amount) FROM orders")
    net_gov = scalar(f"SELECT SUM(gross_amount-refund_amount) FROM orders WHERE {MARKETING}")
    check("naive gross overstates governed net by >25%",
          gross_all > net_gov * 1.25, f"gross {gross_all:.0f} vs net {net_gov:.0f}")

    print("\n-- machine opens (MPP simulation)")
    raw_opens = scalar("SELECT SUM(opened) FROM email_sends WHERE delivered=1")
    mach = scalar("SELECT SUM(machine_opened) FROM email_sends WHERE delivered=1")
    check("machine share of opens 25-45%", 0.25 <= mach / raw_opens <= 0.45,
          f"got {mach / raw_opens:.3f}")
    gov_open = scalar("""SELECT SUM(CASE WHEN opened=1 AND machine_opened=0 THEN 1 ELSE 0 END)*1.0
                         /SUM(delivered) FROM email_sends
                         WHERE email_type!='transactional' AND delivered=1""")
    check("governed open rate in 18-30% band", 0.18 <= gov_open <= 0.30,
          f"got {gov_open:.4f}")

    print("\n-- 24 complete months, every table")
    for tbl, col in [("orders", "order_date"), ("email_sends", "send_date"),
                     ("ad_spend", "date")]:
        months = scalar(f"SELECT COUNT(DISTINCT substr({col},1,7)) FROM {tbl} "
                        f"WHERE {col} >= ? AND {col} <= ?",
                        (DATA_START.isoformat(), DATA_END.isoformat()))
        check(f"{tbl} covers all 24 months", months == MONTHS, f"got {months}")

    print("\n-- coverage: no thin dimension slice for questions 1 to 12")
    thin = cur.execute(f"""
        SELECT substr(order_date,1,7) m, channel, COUNT(*) n FROM orders
        WHERE {MARKETING} AND channel != 'wholesale'
        GROUP BY m, channel HAVING n < 200""").fetchall()
    check("orders per channel per month >= 200", not thin, f"{len(thin)} thin cells: {thin[:3]}")
    thin_seg = cur.execute("""
        SELECT substr(e.send_date,1,7) m, c.segment, COUNT(*) n
        FROM email_sends e JOIN customers c ON c.id=e.customer_id
        WHERE e.delivered=1 AND e.email_type!='transactional'
        GROUP BY m, c.segment HAVING n < 200""").fetchall()
    check("email delivered per segment per month >= 200", not thin_seg,
          f"{len(thin_seg)} thin cells")
    empty_cells = cur.execute("""
        SELECT region, acquisition_channel, segment, COUNT(*) n FROM customers
        GROUP BY region, acquisition_channel, segment HAVING n < 5""").fetchall()
    check("both segments populated in every region x channel", not empty_cells,
          f"{len(empty_cells)} sparse cells")

    print("\n-- spring campaign volume")
    s_sends = scalar("SELECT COUNT(*) FROM email_sends WHERE campaign_id=?", (spring_id,))
    s_ord = scalar(f"SELECT COUNT(*) FROM orders WHERE campaign_id=? AND {MARKETING}",
                   (spring_id,))
    check("spring campaign >= 5,000 sends", s_sends >= 5_000, f"got {s_sends}")
    check("spring campaign >= 400 attributed orders", s_ord >= 400, f"got {s_ord}")

    print("\n-- planted signal: paid search signup drop matches documented pause")
    pause_start, pause_end = pause
    in_pause = scalar("""SELECT AVG(attributed_signups) FROM ad_spend
                         WHERE channel='paid_search' AND date BETWEEN ? AND ?""",
                      (pause_start.isoformat(), pause_end.isoformat()))
    out_pause = scalar("""SELECT AVG(attributed_signups) FROM ad_spend
                          WHERE channel='paid_search' AND date BETWEEN ? AND ?
                            AND date NOT BETWEEN ? AND ?""",
                       (LAST_MONTH_START.isoformat(), LAST_MONTH_END.isoformat(),
                        pause_start.isoformat(), pause_end.isoformat()))
    drop = 1 - in_pause / out_pause
    check("paid_search signups drop 30-50% during pause", 0.30 <= drop <= 0.50,
          f"got {drop:.3f}")
    n_days = scalar("""SELECT COUNT(*) FROM ad_spend WHERE channel='paid_search'
                       AND date BETWEEN ? AND ?""",
                    (pause_start.isoformat(), pause_end.isoformat()))
    check("pause spans 12 days", n_days == 12, f"got {n_days}")
    # The drop must also be visible in the customers table, because that is the
    # source the governed new_customer_signups metric compiles against. A drop
    # that exists only in ad_spend would not be found by decomposing the metric.
    ps_last = scalar("""SELECT COUNT(*) FROM customers
                        WHERE acquisition_channel='paid_search'
                          AND signup_date BETWEEN ? AND ?""",
                     (LAST_MONTH_START.isoformat(), LAST_MONTH_END.isoformat()))
    ps_prev = scalar("""SELECT COUNT(*) FROM customers
                        WHERE acquisition_channel='paid_search'
                          AND signup_date BETWEEN ? AND ?""",
                     (add_months(LAST_MONTH_START, -1).isoformat(),
                      month_end(add_months(LAST_MONTH_START, -1)).isoformat()))
    mom = 1 - ps_last / ps_prev if ps_prev else 0
    print(f"      paid_search signups (governed source): prev {ps_prev} -> "
          f"last {ps_last} ({mom * 100:.1f}% drop)")
    check("paid_search signups in customers table drop 10-40% month over month",
          0.10 <= mom <= 0.40, f"got {mom:.3f}")
    # Other channels must hold, so decomposition isolates paid_search. Email is
    # excluded from this check: it is a low volume acquisition channel (a few
    # dozen signups a month) where ordinary month to month noise exceeds the
    # tolerance, and it is not part of the planted signal either way.
    for ch in ["organic", "paid_social"]:
        a = scalar("""SELECT COUNT(*) FROM customers WHERE acquisition_channel=?
                      AND signup_date BETWEEN ? AND ?""",
                   (ch, LAST_MONTH_START.isoformat(), LAST_MONTH_END.isoformat()))
        b = scalar("""SELECT COUNT(*) FROM customers WHERE acquisition_channel=?
                      AND signup_date BETWEEN ? AND ?""",
                   (ch, add_months(LAST_MONTH_START, -1).isoformat(),
                    month_end(add_months(LAST_MONTH_START, -1)).isoformat()))
        delta = abs(1 - a / b) if b else 0
        check(f"{ch} signups held within 20% month over month", delta <= 0.20,
              f"{b} -> {a} ({delta * 100:.1f}%)")

    social_flat = cur.execute("""
        SELECT AVG(attributed_signups) FROM ad_spend WHERE channel='paid_social'
          AND date BETWEEN ? AND ?""",
        (pause_start.isoformat(), pause_end.isoformat())).fetchone()[0]
    social_out = cur.execute("""
        SELECT AVG(attributed_signups) FROM ad_spend WHERE channel='paid_social'
          AND date BETWEEN ? AND ? AND date NOT BETWEEN ? AND ?""",
        (LAST_MONTH_START.isoformat(), LAST_MONTH_END.isoformat(),
         pause_start.isoformat(), pause_end.isoformat())).fetchone()[0]
    check("paid_social held flat through pause (isolates the cause)",
          abs(1 - social_flat / social_out) < 0.15,
          f"delta {abs(1 - social_flat / social_out):.3f}")

    print("\n-- planted gaps")
    social_early = scalar("SELECT COUNT(*) FROM ad_spend WHERE channel='paid_social' AND date < ?",
                          (PAID_SOCIAL_START.isoformat(),))
    check("paid_social spend absent before month 7", social_early == 0, f"got {social_early}")
    social_after = scalar("SELECT COUNT(*) FROM ad_spend WHERE channel='paid_social' AND date >= ?",
                          (PAID_SOCIAL_START.isoformat(),))
    check("paid_social spend present from month 7 on", social_after > 300, f"got {social_after}")
    tables = {r[0] for r in cur.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    check("no NPS or survey table exists",
          not any("nps" in t.lower() or "survey" in t.lower() or "satisf" in t.lower()
                  for t in tables), f"tables: {tables}")
    svc = cur.execute(f"""
        SELECT substr(o.order_date,1,7) m, COUNT(DISTINCT o.id) n FROM orders o
        JOIN order_items i ON i.order_id=o.id JOIN products p ON p.id=i.product_id
        WHERE p.category='services' AND {('o.' + MARKETING.replace(' AND ', ' AND o.'))}
        GROUP BY m ORDER BY m""").fetchall()
    svc_counts = [n for _, n in svc]
    check("services category thin: every month < 30 orders",
          svc_counts and max(svc_counts) < 30, f"max {max(svc_counts) if svc_counts else 0}")
    check("services category nonzero: every month >= 5 orders",
          svc_counts and min(svc_counts) >= 5, f"min {min(svc_counts) if svc_counts else 0}")

    print("\n-- product attributes (targeting and affinity questions)")
    check("every racket has a type, head size and weight",
          scalar("""SELECT COUNT(*) FROM products WHERE category='rackets'
                    AND (racket_type IS NULL OR head_size_sq_in IS NULL
                         OR weight_grams IS NULL)""") == 0)
    check("all three racket types exist",
          scalar("SELECT COUNT(DISTINCT racket_type) FROM products "
                 "WHERE category='rackets'") == 3)
    check("every product has a price tier",
          scalar("SELECT COUNT(*) FROM products WHERE price_tier IS NULL") == 0)
    check("all three price tiers are populated",
          scalar("SELECT COUNT(DISTINCT price_tier) FROM products") == 3)
    check("every string has a gauge",
          scalar("SELECT COUNT(*) FROM products WHERE category='strings' "
                 "AND string_gauge IS NULL") == 0)
    # The segmentation guide defines a performance racket as 100 sq in or smaller
    # above 150 dollars. That definition must be computable from the warehouse it
    # describes, and it must select a real subset rather than everything.
    n_perf = scalar("SELECT COUNT(*) FROM products WHERE is_performance=1")
    n_rack = scalar("SELECT COUNT(*) FROM products WHERE category='rackets'")
    check("the performance racket criterion selects a real subset",
          0 < n_perf < n_rack, f"{n_perf} of {n_rack} rackets")
    check("is_performance agrees with the stated criterion",
          scalar("""SELECT COUNT(*) FROM products WHERE category='rackets'
                    AND is_performance != (head_size_sq_in <= 100 AND price > 150)
                 """) == 0)

    print("\n-- planted product preference by segment")
    pref = {}
    for r in cur.execute(f"""
        SELECT c.segment, p.racket_type, COUNT(*) n
        FROM orders o JOIN customers c ON c.id=o.customer_id
        JOIN order_items i ON i.order_id=o.id JOIN products p ON p.id=i.product_id
        WHERE p.category='rackets' AND {('o.' + MARKETING.replace(' AND ', ' AND o.'))}
        GROUP BY 1,2"""):
        pref[(r[0], r[1])] = r[2]
    comp_tot = sum(v for (s, _), v in pref.items() if s == "competitive") or 1
    rec_tot = sum(v for (s, _), v in pref.items() if s == "recreational") or 1
    comp_control = pref.get(("competitive", "control"), 0) / comp_tot
    rec_power = pref.get(("recreational", "power"), 0) / rec_tot
    print(f"      competitive prefer control: {comp_control * 100:.0f}% of their "
          f"racket orders; recreational prefer power: {rec_power * 100:.0f}%")
    check("competitive players skew to control frames", comp_control >= 0.45,
          f"got {comp_control:.2f}")
    check("recreational players skew to power frames", rec_power >= 0.40,
          f"got {rec_power:.2f}")
    check("the two segments genuinely differ in racket type preference",
          comp_control > pref.get(("competitive", "power"), 0) / comp_tot + 0.2)

    print("\n-- commercial product data (brand, cost, stock, lifecycle)")
    check("every product has a brand",
          scalar("SELECT COUNT(*) FROM products WHERE brand IS NULL "
                 "OR brand = ''") == 0)
    n_brands = scalar("SELECT COUNT(DISTINCT brand) FROM products")
    check("several brands exist", n_brands >= 6, f"got {n_brands}")
    check("every product has a unit cost below its price",
          scalar("SELECT COUNT(*) FROM products WHERE unit_cost IS NULL "
                 "OR unit_cost >= price") == 0)
    check("every product has a lifecycle stage",
          scalar("SELECT COUNT(DISTINCT lifecycle_stage) FROM products") >= 3)
    check("suppliers table is populated",
          scalar("SELECT COUNT(*) FROM suppliers") >= 5)
    check("branded products link to a supplier",
          scalar("SELECT COUNT(*) FROM products WHERE supplier_id IS NULL "
                 "AND brand != 'House'") == 0)
    check("the own label brand has no external supplier",
          scalar("SELECT COUNT(*) FROM products WHERE brand='House' "
                 "AND supplier_id IS NOT NULL") == 0)
    check("the recalled product is pulled from sale",
          scalar("SELECT stock_level FROM products WHERE recalled=1") == 0)
    # Margin must vary by brand, or "which brands are most profitable" is noise.
    margins = {r[0]: r[1] for r in cur.execute(
        "SELECT brand, AVG((price - unit_cost) / price) FROM products "
        "GROUP BY brand")}
    spread = max(margins.values()) - min(margins.values())
    print("      margin by brand: " +
          ", ".join(f"{b}={m * 100:.0f}%" for b, m in sorted(margins.items())))
    check("margin varies meaningfully across brands", spread >= 0.15,
          f"spread {spread:.3f}")
    check("the own label brand carries the best margin",
          max(margins, key=margins.get) == "House",
          f"best is {max(margins, key=margins.get)}")

    print("\n-- planted brand preference by segment")
    brand_pref = {}
    for r in cur.execute(f"""
        SELECT c.segment, p.brand, COUNT(*) n
        FROM orders o JOIN customers c ON c.id=o.customer_id
        JOIN order_items i ON i.order_id=o.id JOIN products p ON p.id=i.product_id
        WHERE {('o.' + MARKETING.replace(' AND ', ' AND o.'))}
        GROUP BY 1,2"""):
        brand_pref[(r[0], r[1])] = r[2]
    PERF = {"Baseline", "Cordage", "Meridian"}
    for seg in ("competitive", "recreational"):
        tot = sum(v for (s, _), v in brand_pref.items() if s == seg) or 1
        perf = sum(v for (s, b), v in brand_pref.items()
                   if s == seg and b in PERF) / tot
        print(f"      {seg}: {perf * 100:.0f}% of orders are performance brands")
        if seg == "competitive":
            comp_perf = perf
        else:
            rec_perf = perf
    check("competitive players skew to performance brands", comp_perf >= 0.50,
          f"got {comp_perf:.2f}")
    check("the two segments differ in brand preference",
          comp_perf - rec_perf >= 0.12, f"gap {comp_perf - rec_perf:.2f}")

    print("\n-- planted cross-sell affinity (lift above chance)")
    def _share(anchor, partner):
        n_anchor = scalar(f"""
            SELECT COUNT(DISTINCT o.customer_id) FROM orders o
            JOIN order_items i ON i.order_id=o.id JOIN products p ON p.id=i.product_id
            WHERE {('o.' + MARKETING.replace(' AND ', ' AND o.'))} AND p.category=?""",
            (anchor,))
        n_both = scalar(f"""
            SELECT COUNT(DISTINCT o.customer_id) FROM orders o
            JOIN order_items i ON i.order_id=o.id JOIN products p ON p.id=i.product_id
            WHERE {('o.' + MARKETING.replace(' AND ', ' AND o.'))} AND p.category=?
              AND o.customer_id IN (
                SELECT DISTINCT o2.customer_id FROM orders o2
                JOIN order_items i2 ON i2.order_id=o2.id
                JOIN products p2 ON p2.id=i2.product_id
                WHERE o2.status='completed' AND o2.channel!='wholesale'
                  AND p2.category=?)""", (partner, anchor))
        all_buyers = scalar(f"SELECT COUNT(DISTINCT customer_id) FROM orders o WHERE {MARKETING}")
        n_partner = scalar(f"""
            SELECT COUNT(DISTINCT o.customer_id) FROM orders o
            JOIN order_items i ON i.order_id=o.id JOIN products p ON p.id=i.product_id
            WHERE {('o.' + MARKETING.replace(' AND ', ' AND o.'))} AND p.category=?""",
            (partner,))
        share = n_both / n_anchor if n_anchor else 0
        base = n_partner / all_buyers if all_buyers else 1
        return share, base, (share / base if base else 0)

    for anchor, partner in [("rackets", "strings"), ("shoes", "apparel")]:
        share, base, lift = _share(anchor, partner)
        print(f"      {anchor} -> {partner}: {share*100:.1f}% of buyers "
              f"vs {base*100:.1f}% base, lift {lift:.2f}")
        check(f"{anchor} buyers show real lift toward {partner}", lift >= 1.05,
              f"lift {lift:.2f}")

    print("\n-- campaign brief metadata (why, to whom, what was learned)")
    n_camp = scalar("SELECT COUNT(*) FROM campaigns")
    check("every campaign records an objective",
          scalar("SELECT COUNT(*) FROM campaigns WHERE objective IS NULL "
                 "OR objective = ''") == 0)
    check("every campaign records a target segment and category",
          scalar("SELECT COUNT(*) FROM campaigns WHERE target_segment IS NULL "
                 "OR target_category IS NULL") == 0)
    check("every campaign records an offer and an owner",
          scalar("SELECT COUNT(*) FROM campaigns WHERE offer IS NULL "
                 "OR owner IS NULL") == 0)
    n_learn = scalar("SELECT COUNT(*) FROM campaigns WHERE learnings IS NOT NULL")
    check("completed campaigns carry learnings", n_learn >= n_camp * 0.8,
          f"{n_learn} of {n_camp}")
    check("running campaigns have no learnings yet (honest absence)",
          scalar("SELECT COUNT(*) FROM campaigns WHERE status='running' "
                 "AND learnings IS NOT NULL") == 0)
    # Names must describe intent ("Restring Reset Jan 2025"), not just restate the
    # channel ("Jan 2025 Paid Social Push 3"), which told a marketer nothing and
    # made comparable campaigns impossible to find by name.
    check("campaign names describe intent, not just the channel",
          scalar("""SELECT COUNT(*) FROM campaigns
                    WHERE name LIKE '%Paid Search Push%'
                       OR name LIKE '%Paid Social Push%'
                       OR name LIKE '%Email Push%'""") == 0)
    check("several distinct campaign themes exist",
          scalar("SELECT COUNT(DISTINCT objective) FROM campaigns") >= 6,
          f"{scalar('SELECT COUNT(DISTINCT objective) FROM campaigns')} objectives")

    print("\n-- milestone 2: referral graph")
    n_ref = scalar("SELECT COUNT(*) FROM customers WHERE referred_by IS NOT NULL")
    check("referred customers >= 4,000", n_ref >= 4_000, f"got {n_ref}")
    check("no self referrals", scalar("SELECT COUNT(*) FROM customers WHERE referred_by=id") == 0)
    # chain depth by root acquisition channel
    parent = {r[0]: r[1] for r in cur.execute("SELECT id, referred_by FROM customers")}
    chan = {r[0]: r[1] for r in cur.execute("SELECT id, acquisition_channel FROM customers")}
    depth_cache: dict[int, int] = {}

    def depth(cid, guard=0):
        if cid in depth_cache:
            return depth_cache[cid]
        p = parent.get(cid)
        d = 0 if not p or guard > 12 else 1 + depth(p, guard + 1)
        depth_cache[cid] = d
        return d

    def root_of(cid, guard=0):
        p = parent.get(cid)
        return cid if not p or guard > 12 else root_of(p, guard + 1)

    by_root_chan = defaultdict(list)
    for cid in parent:
        if parent.get(cid) is None:
            r = root_of(cid)
            # roots with at least one descendant contribute their subtree depth
            pass
    # max depth per root, grouped by that root's acquisition channel
    max_depth_by_root: dict[int, int] = defaultdict(int)
    for cid in parent:
        d = depth(cid)
        if d:
            r = root_of(cid)
            max_depth_by_root[r] = max(max_depth_by_root[r], d)
    for r, d in max_depth_by_root.items():
        by_root_chan[chan[r]].append(d)
    avg_depth = {c: sum(v) / len(v) for c, v in by_root_chan.items() if v}
    print("      avg chain depth by origin channel: " +
          ", ".join(f"{c}={v:.2f}" for c, v in sorted(avg_depth.items())))
    organic = avg_depth.get("organic", 0)
    others = [v for c, v in avg_depth.items() if c != "organic"]
    check("organic avg chain depth >= 2.4", organic >= 2.4, f"got {organic:.2f}")
    check("organic depth exceeds every other channel by >= 0.8",
          others and organic - max(others) >= 0.8,
          f"organic {organic:.2f} vs best other {max(others):.2f}" if others else "no others")
    check("max chain depth <= 5", max(depth_cache.values()) <= 5,
          f"got {max(depth_cache.values())}")

    print("\n-- milestone 2: referral churn cluster (question 14)")
    churn_cut = LAST_MONTH_END.isoformat()
    exposed = planted["exposed_referees"]
    check("exposed referee cohort >= 250", len(exposed) >= 250, f"got {len(exposed)}")

    def rpr_for(ids):
        if not ids:
            return 0.0
        q = ",".join("?" * len(ids))
        return scalar(f"""
            WITH active AS (
              SELECT customer_id, COUNT(*) n FROM orders
              WHERE {MARKETING} AND order_date >= date(?, '-12 months')
                AND order_date <= ? AND customer_id IN ({q})
              GROUP BY customer_id)
            SELECT SUM(CASE WHEN n>=2 THEN 1 ELSE 0 END)*1.0/COUNT(*) FROM active""",
            (churn_cut, churn_cut, *ids))

    # The cohorts are asserted using the DEFINITION question 14 asks, not the
    # hand-picked seed list: referees whose referrer is inferred-churned versus
    # referees whose referrer is still active. This is exactly the cohort split
    # the milestone-2 graph path selects, so the assertion tests the answer the
    # system will actually produce.
    def referee_split():
        rows = cur.execute(f"""
            WITH referrer_activity AS (
              SELECT c.id,
                (SELECT COUNT(*) FROM orders o WHERE o.customer_id = c.id
                   AND {MARKETING} AND o.order_date >= date(?, '-12 months')
                   AND o.order_date <= ?) n
              FROM customers c)
            SELECT k.id, CASE WHEN ra.n = 0 THEN 1 ELSE 0 END exposed
            FROM customers k JOIN referrer_activity ra ON ra.id = k.referred_by
            WHERE k.referred_by IS NOT NULL""",
            (churn_cut, churn_cut)).fetchall()
        exp = [r[0] for r in rows if r[1]]
        base = [r[0] for r in rows if not r[1]]
        return exp, base

    exposed_def, non_exposed = referee_split()
    check("exposed cohort (referrer inferred churned) >= 250",
          len(exposed_def) >= 250, f"got {len(exposed_def)}")
    check("non exposed comparison cohort >= 2,000", len(non_exposed) >= 2_000,
          f"got {len(non_exposed)}")
    r_exp, r_base = rpr_for(exposed_def), rpr_for(non_exposed)
    delta = (r_base - r_exp) * 100
    print(f"      exposed rpr {r_exp:.3f} vs baseline {r_base:.3f} -> {delta:.1f} points")
    check("exposed cohort repeat rate 6-22 points below baseline",
          6 <= delta <= 22, f"got {delta:.1f}")

    # Temporal ordering: a referral must always precede the referrer's churn.
    bad_order = scalar("""
        SELECT COUNT(*) FROM customers k JOIN customers p ON p.id = k.referred_by
        WHERE k.signup_date < p.signup_date""")
    check("referral always follows referrer signup (temporal ordering holds)",
          bad_order == 0, f"got {bad_order}")
    # The planted referrer set must be inferred-churned, which is what makes the
    # exposed cohort large enough to measure.
    refs = planted["churn_referrers"]
    if refs:
        q = ",".join("?" * len(refs))
        still_active = scalar(f"""
            SELECT COUNT(DISTINCT customer_id) FROM orders
            WHERE {MARKETING} AND customer_id IN ({q})
              AND order_date >= date(?, '-12 months') AND order_date <= ?""",
            (*refs, churn_cut, churn_cut))
        check("planted referrer set is inferred churned",
              still_active == 0, f"{still_active} still active")
        # Referrals must predate the churn window: churn here means no completed
        # order in the trailing 12 months, so the referral has to land before
        # that window opens for "referrer churned after referring" to hold. The
        # graph playbook checks this same ordering before making any claim.
        window_open = f"date('{churn_cut}', '-12 months')"
        late = scalar(f"""
            SELECT COUNT(*) FROM customers k
            WHERE k.referred_by IN ({q}) AND k.signup_date > {window_open}""",
            tuple(refs))
        check("referral precedes the churn window (referral before churn)",
              late == 0, f"{late} referrals inside the churn window")

    print("\n-- milestone 2: recall divergence (question 15)")
    recalled_pid = scalar("SELECT id FROM products WHERE recalled=1")
    check("exactly one recalled product",
          scalar("SELECT COUNT(*) FROM products WHERE recalled=1") == 1)
    recall_cohort = [r[0] for r in cur.execute(f"""
        SELECT DISTINCT o.customer_id FROM orders o
        JOIN order_items i ON i.order_id=o.id
        WHERE o.campaign_id=? AND i.product_id=? AND {('o.' + MARKETING.replace(' AND ', ' AND o.'))}""",
        (spring_id, recalled_pid))]
    control = [r[0] for r in cur.execute(f"""
        SELECT DISTINCT o.customer_id FROM orders o
        JOIN order_items i ON i.order_id=o.id JOIN products p ON p.id=i.product_id
        WHERE o.campaign_id=? AND p.category='strings' AND p.recalled=0
          AND {('o.' + MARKETING.replace(' AND ', ' AND o.'))}
          AND o.customer_id NOT IN (SELECT DISTINCT o2.customer_id FROM orders o2
              JOIN order_items i2 ON i2.order_id=o2.id
              WHERE o2.campaign_id=? AND i2.product_id=?)""",
        (spring_id, spring_id, recalled_pid))]
    check("recalled string cohort >= 300", len(recall_cohort) >= 300, f"got {len(recall_cohort)}")
    check("matched control cohort >= 300", len(control) >= 300, f"got {len(control)}")
    r_recall, r_ctrl = rpr_for(recall_cohort), rpr_for(control)
    div = (r_ctrl - r_recall) * 100
    print(f"      recall cohort rpr {r_recall:.3f} vs control {r_ctrl:.3f} -> {div:.1f} points")
    check("recall cohort repeat rate 5-20 points below matched control",
          5 <= div <= 20, f"got {div:.1f}")

    print("\n-- benchmark internal consistency")
    check("benchmarks.yaml written", os.path.exists(BENCH_PATH))

    return failures


# ---------------------------------------------------------------- main


def main():
    print(f"Seeding Baseline Tennis Co. (seed={SEED})")
    print(f"Window: {DATA_START} to {DATA_END} ({MONTHS} complete months)")
    print(f"paid_social spend tracking starts: {PAID_SOCIAL_START}")

    if os.path.exists(DB_PATH):
        os.remove(DB_PATH)
    conn = sqlite3.connect(DB_PATH)
    conn.executescript(SCHEMA)

    print("\ngenerating customers and referral chains...")
    customers = gen_customers()
    print(f"  {len(customers)} customers, "
          f"{sum(1 for c in customers if c['referred_by'])} referred")

    suppliers = gen_suppliers()
    products = gen_products()
    campaigns, spring_id = gen_campaigns()
    spring = next(c for c in campaigns if c["id"] == spring_id)
    spring_window = (date.fromisoformat(spring["start_date"]),
                     date.fromisoformat(spring["end_date"]))
    print(f"  spring campaign: id={spring_id} {spring['start_date']} to {spring['end_date']}")

    print("generating orders...")
    orders, items, planted = gen_orders(customers, products, spring_id, spring_window)
    print(f"  {len(orders)} orders, {len(items)} items")

    print("generating email sends...")
    sends = gen_email_sends(customers, campaigns, spring_id, spring_window)
    print(f"  {len(sends)} sends")

    print("generating ad spend...")
    spend, pause = gen_ad_spend()
    print(f"  {len(spend)} spend rows; paid search pause {pause[0]} to {pause[1]}")

    print("writing to sqlite...")
    conn.executemany("INSERT INTO customers VALUES (:id,:segment,:region,:signup_date,"
                     ":acquisition_channel,:referred_by)", customers)
    conn.executemany(
        "INSERT INTO suppliers VALUES (:id,:name,:country,:lead_time_days,"
        ":payment_terms,:minimum_order_value,:relationship_since,:notes)",
        suppliers)
    conn.executemany(
        "INSERT INTO products VALUES (:id,:category,:name,:price,:recalled,"
        ":racket_type,:head_size_sq_in,:weight_grams,:price_tier,:string_gauge,"
        ":is_performance,:brand,:supplier_id,:unit_cost,:stock_level,"
        ":launch_date,:lifecycle_stage)", products)
    conn.executemany(
        "INSERT INTO campaigns VALUES (:id,:name,:type,:start_date,:end_date,"
        ":channel,:budget,:objective,:target_segment,:target_category,:offer,"
        ":owner,:status,:learnings)", campaigns)
    conn.executemany("INSERT INTO orders VALUES (:id,:customer_id,:order_date,"
                     ":gross_amount,:refund_amount,:channel,:status,:campaign_id)", orders)
    conn.executemany("INSERT INTO order_items VALUES (:order_id,:product_id,:quantity,"
                     ":unit_price)", items)
    conn.executemany("INSERT INTO email_sends VALUES (:id,:campaign_id,:customer_id,"
                     ":send_date,:delivered,:opened,:machine_opened,:clicked,:email_type)",
                     sends)
    conn.executemany("INSERT INTO ad_spend VALUES (:date,:channel,:spend,:clicks,"
                     ":attributed_signups)", spend)
    conn.commit()

    print("computing benchmarks from seeded data...")
    spring_net, spring_gross = compute_benchmarks(conn, spring_id)
    print(f"  spring net {spring_net:,.0f} vs recap deck gross {spring_gross:,.0f}")

    print("generating documents...")
    recalled = next(p for p in products if p["recalled"])
    doc_names = gen_documents(spring, recalled, planted["recall_date"], pause,
                              spring_net, spring_gross)
    print(f"  {len(doc_names)} documents in data/documents/")

    print("\n=== VERIFYING PLANTED SIGNALS, COVERAGE, AND GAPS ===")
    failures = verify(conn, planted, pause, spring_id)

    # Persist run facts the semantic layer and eval harness need.
    facts = {
        "spring_campaign_id": spring_id,
        "spring_campaign_name": spring["name"],
        "spring_start": spring["start_date"],
        "spring_end": spring["end_date"],
        "recalled_product_id": recalled["id"],
        "recalled_product_name": recalled["name"],
        "recall_date": planted["recall_date"].isoformat(),
        "paid_search_pause_start": pause[0].isoformat(),
        "paid_search_pause_end": pause[1].isoformat(),
        "paid_social_tracking_start": PAID_SOCIAL_START.isoformat(),
        "data_start": DATA_START.isoformat(),
        "data_end": DATA_END.isoformat(),
        "last_complete_month": LAST_MONTH_START.isoformat()[:7],
    }
    # Publish the GOLD VALUES this run produced. Hardcoding them in the eval and
    # verification files meant every reseed broke a dozen assertions that were
    # never testing anything except "the data has not changed". Reading them from
    # here keeps the assertions about SHAPE (a band, an ordering, a gap) while the
    # exact figures follow the data.
    def _scalar(sql, params=()):
        r = conn.execute(sql, params).fetchone()
        return r[0] if r and r[0] is not None else None

    MK = "status = 'completed' AND channel != 'wholesale'"
    lm_start, lm_end = LAST_MONTH_START.isoformat(), LAST_MONTH_END.isoformat()
    facts["gold"] = {
        "net_revenue_last_month": round(_scalar(
            f"SELECT SUM(gross_amount-refund_amount) FROM orders WHERE {MK} "
            "AND order_date BETWEEN ? AND ?", (lm_start, lm_end)) or 0, 2),
        "gross_revenue_last_month": round(_scalar(
            "SELECT SUM(gross_amount) FROM orders WHERE status IN "
            "('completed','refunded') AND channel != 'wholesale' "
            "AND order_date BETWEEN ? AND ?", (lm_start, lm_end)) or 0, 2),
        "naive_gross_all_rows_last_month": round(_scalar(
            "SELECT SUM(gross_amount) FROM orders WHERE order_date BETWEEN ? AND ?",
            (lm_start, lm_end)) or 0, 2),
        "spring_net": round(_scalar(
            f"SELECT SUM(gross_amount-refund_amount) FROM orders WHERE {MK} "
            "AND campaign_id = ?", (spring_id,)) or 0, 2),
        "spring_gross_all_rows": round(_scalar(
            "SELECT SUM(gross_amount) FROM orders WHERE campaign_id = ?",
            (spring_id,)) or 0, 2),
        "december_net": round(_scalar(
            f"SELECT SUM(gross_amount-refund_amount) FROM orders WHERE {MK} "
            "AND substr(order_date,1,7) = ?",
            (add_months(LAST_MONTH_START, -7).isoformat()[:7],)) or 0, 2),
    }
    facts["gold"]["december_month"] = add_months(
        LAST_MONTH_START, -7).isoformat()[:7]

    import json
    with open(os.path.join(HERE, "seed_facts.json"), "w") as f:
        json.dump(facts, f, indent=2)
    print("\nwrote data/seed_facts.json")

    conn.close()

    if failures:
        print(f"\nSEEDING FAILED: {len(failures)} assertion(s) did not hold")
        for f_ in failures:
            print(f"  - {f_}")
        sys.exit(1)
    print("\nAll assertions passed. Seed complete.")


if __name__ == "__main__":
    main()

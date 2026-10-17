#!/usr/bin/env python3
"""Seeded synthetic data generator for the customer-tagging plugin.

Writes, next to this script by default:
    customers.csv       about 300 synthetic customers
    transactions.csv    about 5,000 synthetic transactions over 12 months
    expected_tags.json  the tags each labelled scenario customer should get

Everything is invented: names are "Synthetic Customer NNNN", accounts and
counterparties are "SYN-..." identifiers, and amounts are generated. No real
person, bank, host or login appears anywhere. Card rows carry an ISO
18245-style merchant code; some counterparties are spelt the way a bank feed
spells them ("SYN STREAMCO*0412") so the normalisation table is exercised;
and some customers carry the balance after each transaction.

The first customers (C0001 to C0062) are labelled scenarios. Each is built
from a small number of behaviours, and its expected tags were worked out
from the rules by hand, not copied from the engine's output. The rest are
random background customers with no labels. A few deliberately malformed
rows are added at the end to show how the engine reports skipped data.

The same seed always produces byte-identical files. Only random.random()
is used, through small helpers, so the output does not depend on the
Python version's implementation of randint or choice.
"""

import argparse
import calendar
import csv
import datetime
import json
import os
import random
from decimal import Decimal, ROUND_HALF_EVEN

SEED = 20261017
AS_OF = datetime.date(2026, 9, 30)
MONTHS = [(2025, 10), (2025, 11), (2025, 12)] + [(2026, m) for m in range(1, 10)]
LAST6 = MONTHS[6:]
LAST3 = MONTHS[9:]
HOME_COUNTRY = "US"
HOME_CURRENCY = "USD"
RATES = {
    "USD": Decimal("1"), "EUR": Decimal("1.10"), "GBP": Decimal("1.30"),
    "AED": Decimal("0.27"), "CAD": Decimal("0.73"), "JPY": Decimal("0.0070"),
}
CENT = Decimal("0.01")
PURCHASE_CATEGORIES = ("groceries", "dining", "shopping", "fuel", "transport", "entertainment")
PURCHASE_DAYS = {1: [14], 2: [8, 20], 3: [6, 14, 22], 4: [5, 12, 19, 26], 5: [4, 9, 15, 21, 26],
                 6: [4, 8, 12, 16, 20, 24]}

CUSTOMER_COLUMNS = ["customer_id", "display_name", "account_id", "account_open_date", "home_country", "home_currency"]
TRANSACTION_COLUMNS = ["txn_id", "customer_id", "account_id", "posted_date", "amount", "currency", "direction",
                       "channel", "category", "counterparty", "txn_country", "mcc", "balance_after"]
CARD_MCC = {"groceries": "5411", "dining": "5812", "shopping": "5311", "fuel": "5541", "transport": "4111",
            "entertainment": "7832", "subscription": "5815", "travel": "4511", "cash_withdrawal": "6011"}
# Tags whose every condition reads the balance: customers without balance data
# cannot be evaluated for them. (idle-balance also counts activity, so it is
# simply not met for an active customer; see V2_NOT_EVALUATED.)
BALANCE_TAGS = ["balance-growing", "healthy-buffer", "overdrawn-months", "repeated-low-balance"]

# Tags added in taxonomy 2.0.0 that the stage 1 scenarios also get, worked out
# by hand from each scenario's behaviour.
V2_EXPECTED = {
    # Self-service activity in each of the last 3 complete months; not given
    # where a higher lifecycle stage (new, going dormant, re-engaged, dormant) wins.
    "active-customer": [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20, 21, 22, 23, 24, 25,
                        26, 27, 28, 29, 30, 33, 34, 38, 39, 40, 41, 42],
    # Household spending follows the 40% salary rise.
    "spending-rising": [7],
    # Salary in every month to June, none in August and September, account still used.
    "salary-moved-away": [8],
    # Rent, utility and phone paid at steady amounts every month.
    "recurring-bills": [11],
    # Three or more app payments every month: 9 or more in 90 days.
    "mobile-active": [17, 18, 38],
    # Card used from October to December only.
    "card-dormant": [35],
}
# Not evaluated in v2: idle-balance for customers with 6 or fewer self-service
# transactions in 90 days and no balance data; recent-traveller without a home country.
V2_NOT_EVALUATED = {
    "idle-balance": [3, 4, 21, 31, 32, 35, 36, 42],
    "recent-traveller": [41],
}


class Rng(object):
    """Stable helpers on top of random.random() only."""

    def __init__(self, seed):
        self._random = random.Random(seed)

    def unit(self):
        return self._random.random()

    def int(self, low, high):
        return low + int(self._random.random() * (high - low + 1))

    def pick(self, seq):
        return seq[self.int(0, len(seq) - 1)]

    def chance(self, p):
        return self._random.random() < p

    def jitter(self, amount, cents):
        return (Decimal(amount) + Decimal(self.int(-cents, cents)) / 100).quantize(CENT)


def money(value):
    return Decimal(value).quantize(CENT, rounding=ROUND_HALF_EVEN)


def on(year_month, day):
    year, month = year_month
    return datetime.date(year, month, min(day, calendar.monthrange(year, month)[1]))


def ago(days):
    return AS_OF - datetime.timedelta(days=days)


class Person(object):
    def __init__(self, gen, number, open_date, scenario=None, expected=None, expected_not_evaluated=None,
                 home_country=HOME_COUNTRY, home_currency=HOME_CURRENCY, clip=False, opening_balance=None):
        self.gen = gen
        self.clip = clip
        self.rng = gen.rng
        self.number = number
        self.cid = "C{:04d}".format(number)
        self.account = "SYN-ACC-{:06d}".format(number)
        self.open_date = open_date
        self.home_country = home_country
        self.home_currency = home_currency
        self.scenario = scenario
        self.expected = expected
        self.expected_not_evaluated = expected_not_evaluated
        self.opening_balance = None if opening_balance is None else money(opening_balance)
        self.rows = []
        gen.people.append(self)

    # -- primitives ---------------------------------------------------------
    def add(self, when, amount, direction, channel, category, counterparty="", currency="USD", country=HOME_COUNTRY,
            mcc=None):
        if self.clip and self.open_date is not None and when < self.open_date:
            return  # background customers simply have no activity before opening
        if mcc is None:
            mcc = CARD_MCC.get(category, "") if channel in ("card_pos", "card_online", "atm") else ""
        self.rows.append({
            "date": when, "amount": money(amount), "direction": direction, "channel": channel,
            "category": category, "counterparty": counterparty, "currency": currency, "country": country,
            "mcc": mcc, "seq": len(self.gen.rows_in_order),
        })
        self.gen.rows_in_order.append((self, self.rows[-1]))

    def _sum(self, year_month, direction):
        total = Decimal(0)
        for row in self.rows:
            if row["direction"] == direction and (row["date"].year, row["date"].month) == year_month:
                total += row["amount"] * RATES[row["currency"]]
        return total

    def active_months(self, months=MONTHS):
        start = (self.open_date.year, self.open_date.month)
        return [ym for ym in months if ym >= start]

    # -- behaviours ---------------------------------------------------------
    def monthly(self, category, amount, direction, channel, months=MONTHS, day=10, counterparty="",
                jitter=0, currency="USD", country=HOME_COUNTRY):
        for ym in months:
            self.add(on(ym, day), self.rng.jitter(amount, jitter), direction, channel, category,
                     counterparty, currency, country)

    def salary(self, amount, months=MONTHS, day=25, employer="SYN-EMPLOYER-001", jitter=0):
        self.monthly("salary", amount, "credit", "incoming", months, day, employer, jitter)

    def spend(self, year_month, total, n=3, channel="card_pos", minimum=Decimal("20"), days=None,
              category=None, currency="USD", country=HOME_COUNTRY):
        """Split a month's total into n purchases on fixed days."""
        total = money(total)
        if total < minimum * n:
            total = minimum * n
        weights = [Decimal(80 + self.rng.int(0, 40)) for _ in range(n)]
        scale = sum(weights)
        parts = [money(total * w / scale) for w in weights[:-1]]
        parts.append(total - sum(parts))
        if parts[-1] < minimum:
            parts = [money(total / n)] * (n - 1)
            parts.append(total - sum(parts))
        for day, amount in zip(days or PURCHASE_DAYS[n], parts):
            merchant = "SYN-MERCHANT-{:04d}".format(self.rng.int(1, 400))
            self.add(on(year_month, day), amount, "debit", channel,
                     category or self.rng.pick(PURCHASE_CATEGORIES), merchant, currency, country)

    def household(self, outflow_fraction, n=3, months=MONTHS, channel="card_pos", minimum=Decimal("20")):
        """Card spending that brings the month's total money out to a fraction of money in."""
        for ym in months:
            target = self._sum(ym, "credit") * Decimal(str(outflow_fraction)) - self._sum(ym, "debit")
            self.spend(ym, target, n, channel, minimum)


class Generator(object):
    def __init__(self, seed):
        self.rng = Rng(seed)
        self.seed = seed
        self.people = []
        self.rows_in_order = []
        self.extra_rows = []


# ---------------------------------------------------------------------------
# Labelled scenarios. The comment on each states the behaviour and why the
# expected tags follow from the rules in taxonomy/tags.json.
# ---------------------------------------------------------------------------

def scenarios(g):
    T = 700  # default tenure in days: not new, not established

    # Salary every month; spending is 90% of money in, so no saver tag.
    p = Person(g, 1, ago(T), "salary every month", ["salary-earner"])
    p.salary(3000)
    p.household(0.90)

    # Near miss: salary missing in June 2026, so 5 of the last 6 months.
    p = Person(g, 2, ago(T), "salary 5 of last 6 months (near miss)", [])
    p.salary(3000, [ym for ym in MONTHS if ym != (2026, 6)])
    for ym in MONTHS:
        p.spend(ym, 2700)

    # Freelancer whose income swings: 9 of 12 months with income, most months
    # far from the usual (median) month, and no salary.
    p = Person(g, 3, ago(T), "freelance income that swings month to month",
               ["business-income", "irregular-income"])
    amounts = [4000, 0, 1500, 6000, 0, 2600, 800, 5000, 0, 3000, 1200, 4500]
    for i, (ym, amount) in enumerate(zip(MONTHS, amounts)):
        if amount:
            p.add(on(ym, 15), amount, "credit", "incoming", "business_income", "SYN-CLIENT-{:03d}".format(1 + i % 2))
        p.spend(ym, 2000, n=2)

    # Gig worker paid by several clients each month; steady total.
    p = Person(g, 4, ago(550), "gig work from several clients", ["business-income", "multi-source-income"])
    for i, ym in enumerate(MONTHS):
        for k, day in enumerate((5, 14, 23)):
            client = "SYN-CLIENT-{:03d}".format(10 + (i + k) % 5)
            p.add(on(ym, day), p.rng.jitter(700, 5000), "credit", "incoming", "business_income", client)
    p.household(0.88, n=2)

    # Money from abroad every month, in a foreign currency.
    p = Person(g, 5, ago(T), "money received from abroad every month", ["remittance-receiver"])
    p.monthly("remittance_in", 3700, "credit", "incoming", day=5, counterparty="SYN-SENDER-001",
              currency="AED", country="AE")
    p.household(0.85)

    # Near miss: money from abroad in only 2 of the last 6 months.
    p = Person(g, 6, ago(T), "money from abroad 2 of last 6 months (near miss)", [])
    remit = MONTHS[:6] + [(2026, 4), (2026, 8)]
    p.monthly("remittance_in", 3700, "credit", "incoming", months=remit, day=5,
              counterparty="SYN-SENDER-002", currency="AED", country="AE")
    p.household(0.85)

    # Salary rises from 2,000 to 2,800 for the last 3 months (140%).
    p = Person(g, 7, ago(T), "salary rise in the last 3 months", ["rising-income", "salary-earner"])
    p.salary(2000, MONTHS[:9])
    p.salary(2800, LAST3)
    p.household(0.88)

    # Salary stops after June; small freelance income after (27% of before).
    p = Person(g, 8, ago(T), "salary replaced by small freelance income", ["falling-income"])
    p.salary(3000, MONTHS[:9])
    for ym in LAST3:
        p.add(on(ym, 15), 800, "credit", "incoming", "business_income", "SYN-CLIENT-020")
    p.household(0.88)

    # One large transfer in August, 4.8 times the usual monthly money in.
    p = Person(g, 9, ago(T), "one large transfer received in August", ["large-recent-inflow", "salary-earner"])
    p.salary(2500)
    p.add(datetime.date(2026, 8, 12), 12000, "credit", "incoming", "transfer_in", "SYN-PERSON-050")
    for ym in MONTHS:
        p.spend(ym, 2200)

    # High salary.
    p = Person(g, 10, ago(T), "high monthly salary", ["high-inflow", "salary-earner"])
    p.salary(7000)
    p.household(0.88)

    # Bills, rent and a loan every month, all paid digitally; card for the rest.
    p = Person(g, 11, ago(T), "rent, loan and bills every month",
               ["bill-payer", "loan-repayer", "rent-payer", "salary-earner"])
    p.salary(3500)
    p.monthly("rent", 1200, "debit", "internet_banking", day=4, counterparty="SYN-LANDLORD-001")
    p.monthly("utilities", 120, "debit", "internet_banking", day=10, counterparty="SYN-UTILITY-01", jitter=1500)
    p.monthly("telecom", 45, "debit", "mobile_app", day=12, counterparty="SYN-TELECOM-01")
    p.monthly("loan_repayment", 400, "debit", "internet_banking", day=15, counterparty="SYN-LENDER-01")
    p.household(0.90)

    # Near miss: utility bill missed in May and July (4 of last 6 months).
    p = Person(g, 12, ago(T), "utility bill 4 of last 6 months (near miss)", ["salary-earner"])
    p.salary(3000)
    p.monthly("utilities", 100, "debit", "internet_banking",
              months=[ym for ym in MONTHS if ym not in ((2026, 5), (2026, 7))], day=10,
              counterparty="SYN-UTILITY-02")
    p.household(0.90)

    # Quarterly insurance premiums (4 of 12 months).
    p = Person(g, 13, ago(T), "quarterly insurance premiums", ["insurance-payer", "salary-earner"])
    p.salary(3000)
    p.monthly("insurance", 150, "debit", "internet_banking", months=[MONTHS[1], MONTHS[4], MONTHS[7], MONTHS[10]],
              day=10, counterparty="SYN-INSURER-01")
    p.household(0.90)

    # Six card payments a month: 18 in 90 days and 88% of spending.
    p = Person(g, 14, ago(T), "most spending by card", ["card-heavy-spender", "salary-earner"])
    p.salary(4000)
    p.monthly("transfer_out", 400, "debit", "mobile_app", day=27, counterparty="SYN-PERSON-001")
    for ym in MONTHS:
        p.spend(ym, 2000, n=4, days=[5, 12, 19, 26])
        p.spend(ym, 1000, n=2, channel="card_online", days=[9, 21], category="shopping")

    # Near miss: four card payments a month, 12 in 90 days.
    p = Person(g, 15, ago(T), "card spending, 12 card payments in 90 days (near miss)", ["salary-earner"])
    p.salary(4000)
    p.monthly("transfer_out", 400, "debit", "mobile_app", day=27, counterparty="SYN-PERSON-002")
    for ym in MONTHS:
        p.spend(ym, 2200, n=3)
        p.spend(ym, 800, n=1, channel="card_online", days=[17], category="shopping")

    # Online shopping and three subscriptions, all digital; a large monthly
    # transfer keeps card spending under 60%.
    p = Person(g, 16, ago(T), "online shopping and three subscriptions",
               ["digital-first", "online-shopper", "salary-earner", "subscription-user"])
    p.salary(3000)
    p.monthly("transfer_out", 1800, "debit", "mobile_app", day=27, counterparty="SYN-PERSON-003")
    for k, (name, price) in enumerate((("01", "12.99"), ("02", "9.99"), ("03", "14.99"))):
        p.monthly("subscription", price, "debit", "card_online", day=3 + 5 * k, counterparty="SYN-SUBSCRIPTION-" + name)
    for ym in MONTHS:
        p.spend(ym, 900, n=3, channel="card_online", category="shopping")

    # Every self-service payment in the app.
    p = Person(g, 17, ago(T), "all payments in the mobile app", ["digital-first", "salary-earner"])
    p.salary(2500)
    p.household(0.88, n=4, channel="mobile_app")

    # Near miss: 3 app payments and 1 card payment a month, 75% digital.
    p = Person(g, 18, ago(T), "75% of payments digital (near miss)", ["salary-earner"])
    p.salary(2500)
    for ym in MONTHS:
        p.spend(ym, 1500, n=3, channel="mobile_app")
        p.spend(ym, 700, n=1, days=[25])

    # Bill and transfer paid in a branch, one card payment: 67% branch.
    p = Person(g, 19, ago(T), "pays bills and transfers in a branch", ["bill-payer", "branch-reliant", "salary-earner"])
    p.salary(2200)
    p.monthly("utilities", 110, "debit", "branch", day=10, counterparty="SYN-UTILITY-03")
    p.monthly("transfer_out", 500, "debit", "branch", day=18, counterparty="SYN-PERSON-004")
    p.household(0.90, n=1)

    # Two ATM withdrawals a month, 72% of spending.
    p = Person(g, 20, ago(T), "most spending taken as cash", ["high-cash-user", "salary-earner"])
    p.salary(2000)
    p.monthly("cash_withdrawal", 650, "debit", "atm", day=7)
    p.monthly("cash_withdrawal", 650, "debit", "atm", day=21)
    for ym in MONTHS:
        p.spend(ym, 500, n=1)

    # Near miss: one large ATM withdrawal a month, 3 in 90 days.
    p = Person(g, 21, ago(T), "cash withdrawals, 3 in 90 days (near miss)", ["salary-earner"])
    p.salary(2000)
    p.monthly("cash_withdrawal", 1300, "debit", "atm", day=7)
    for ym in MONTHS:
        p.spend(ym, 500, n=1)

    # Small trader: cash deposits twice a month in a branch (40% of
    # self-service, below the branch-reliant threshold).
    p = Person(g, 22, ago(T), "cash deposits twice a month", ["cash-depositor"])
    for ym in MONTHS:
        p.add(on(ym, 9), p.rng.jitter(700, 10000), "credit", "branch", "cash_deposit")
        p.add(on(ym, 23), p.rng.jitter(700, 10000), "credit", "branch", "cash_deposit")
        inflow = p._sum(ym, "credit")
        p.add(on(ym, 25), money(inflow * Decimal("0.44")), "debit", "internet_banking", "transfer_out", "SYN-SUPPLIER-01")
        p.spend(ym, inflow * Decimal("0.44"), n=2)

    # Moves money to savings every month.
    p = Person(g, 23, ago(T), "monthly transfer to savings", ["salary-earner", "saver"])
    p.salary(3200)
    p.monthly("savings_transfer", 500, "debit", "mobile_app", day=26, counterparty="SYN-SAVINGS-023")
    p.household(0.904)

    # Keeps 35% of money in every month.
    p = Person(g, 24, ago(T), "keeps a third of income each month", ["salary-earner", "saver"])
    p.salary(2600)
    p.household(0.65)

    # Near miss: savings transfers in 4 of the last 6 months; spending leaves
    # 20% or more only in the 2 months without a transfer.
    p = Person(g, 25, ago(T), "savings transfers 4 of last 6 months (near miss)", ["salary-earner"])
    p.salary(3200)
    p.monthly("savings_transfer", 500, "debit", "mobile_app",
              months=[ym for ym in MONTHS if ym not in ((2026, 5), (2026, 7))], day=26, counterparty="SYN-SAVINGS-025")
    for ym in MONTHS:
        p.spend(ym, 2376)

    # Two investment purchases in the last 180 days.
    p = Person(g, 26, ago(T), "two investment purchases", ["investor", "salary-earner"])
    p.salary(4500)
    p.household(0.85)
    p.add(datetime.date(2026, 4, 15), 1000, "debit", "internet_banking", "investment", "SYN-BROKER-01")
    p.add(datetime.date(2026, 8, 10), 1500, "debit", "internet_banking", "investment", "SYN-BROKER-01")

    # Spends 300 more than the salary in each of the last 6 months.
    p = Person(g, 27, ago(T), "spending above income for 6 months", ["salary-earner", "spending-exceeds-inflow"])
    p.salary(2000)
    for ym in MONTHS:
        p.spend(ym, 2300 if ym in LAST6 else 1800)

    # Card and ATM use abroad in 4 months, in 3 countries.
    p = Person(g, 28, ago(T), "four trips abroad", ["frequent-traveller", "salary-earner"])
    p.salary(4000)
    p.household(0.88)
    for ym, country, currency in ((MONTHS[1], "GB", "GBP"), (MONTHS[4], "FR", "EUR"),
                                  (MONTHS[7], "AE", "AED"), (MONTHS[10], "GB", "GBP")):
        local = Decimal(150) / RATES[currency] * Decimal("1.30") if currency == "AED" else Decimal(150)
        p.spend(ym, local * 3, n=3, days=[16, 17, 18], currency=currency, country=country)
        p.add(on(ym, 16), money(local * Decimal("1.333")), "debit", "atm", "cash_withdrawal", "", currency, country)

    # Near miss: abroad in only 2 months.
    p = Person(g, 29, ago(T), "two trips abroad (near miss)", ["salary-earner"])
    p.salary(4000)
    p.household(0.88)
    for ym, country, currency in ((MONTHS[4], "FR", "EUR"), (MONTHS[10], "GB", "GBP")):
        p.spend(ym, 450, n=3, days=[16, 17, 18], currency=currency, country=country)

    # Online purchases in euros for the last 3 months: 29% of card spending.
    p = Person(g, 30, ago(T), "online purchases in euros", ["foreign-currency-spender", "salary-earner"])
    p.salary(3000)
    p.monthly("transfer_out", 1700, "debit", "mobile_app", day=27, counterparty="SYN-PERSON-005")
    for ym in MONTHS:
        p.spend(ym, 800, n=2)
    for ym in LAST3:
        p.spend(ym, 300, n=2, channel="card_online", days=[11, 24], category="shopping", currency="EUR", country="DE")

    # Opened 40 days ago, with an opening deposit and a first salary.
    p = Person(g, 31, ago(40), "new customer with first transactions", ["new-customer"])
    p.add(ago(39), 500, "credit", "branch", "cash_deposit")
    p.add(datetime.date(2026, 9, 5), 120, "debit", "card_pos", "groceries", "SYN-MERCHANT-0031")
    p.add(datetime.date(2026, 9, 15), 480, "debit", "card_pos", "shopping", "SYN-MERCHANT-0032")
    p.add(datetime.date(2026, 9, 25), 2500, "credit", "incoming", "salary", "SYN-EMPLOYER-031")

    # Opened 10 days ago, no transactions yet.
    Person(g, 32, ago(10), "new customer with no transactions", ["new-customer"])

    # Six years a customer, active every month.
    p = Person(g, 33, ago(2190), "long-standing and active", ["established-customer", "salary-earner"])
    p.salary(2800)
    p.household(0.90)

    # Near miss: same activity, but 1,060 days a customer (under 3 years).
    p = Person(g, 34, ago(1060), "almost three years a customer (near miss)", ["salary-earner"])
    p.salary(2800)
    p.household(0.90)

    # Active until December 2025, then nothing but quarterly interest.
    p = Person(g, 35, ago(1461), "no activity since December", ["dormant"])
    p.salary(1500, MONTHS[:3])
    p.household(0.88, months=MONTHS[:3])
    for when in (datetime.date(2026, 3, 31), datetime.date(2026, 6, 30), datetime.date(2026, 9, 30)):
        p.add(when, "2.15", "credit", "system", "interest")

    # Six card payments a month until June, then one a month.
    p = Person(g, 36, ago(T), "activity dropped sharply after June", ["going-dormant", "salary-earner"])
    p.salary(2500)
    p.household(0.88, n=6, months=MONTHS[:9])
    for ym in LAST3:
        p.add(on(ym, 15), 300, "debit", "card_pos", "groceries", "SYN-MERCHANT-0036")

    # Active, quiet from January to June, active again from July.
    p = Person(g, 37, ago(T), "quiet for six months, then active again", ["re-engaged"])
    active = MONTHS[:3] + LAST3
    p.monthly("transfer_in", 1500, "credit", "incoming", months=active, day=3, counterparty="SYN-PERSON-060")
    p.household(0.88, months=active)

    # Three transfers out and one in each month: 12 in 90 days.
    p = Person(g, 38, ago(T), "many person-to-person transfers", ["p2p-transfer-active", "salary-earner"])
    p.salary(2600)
    p.monthly("transfer_in", 150, "credit", "incoming", day=12, counterparty="SYN-PERSON-006")
    for k, day in enumerate((6, 16, 26)):
        p.monthly("transfer_out", 200, "debit", "mobile_app", day=day, counterparty="SYN-PERSON-{:03d}".format(7 + k))
    p.household(0.90, n=2)

    # Four bank charges in the last 90 days.
    p = Person(g, 39, ago(T), "frequent bank charges", ["frequent-fee-payer", "salary-earner"])
    p.salary(2000)
    for when in (datetime.date(2026, 7, 9), datetime.date(2026, 7, 20), datetime.date(2026, 8, 11),
                 datetime.date(2026, 9, 8)):
        p.add(when, 25, "debit", "system", "fee")
    p.household(0.88)

    # Sends money abroad every month.
    p = Person(g, 40, ago(T), "sends money abroad every month", ["remittance-sender", "salary-earner"])
    p.salary(2400)
    p.monthly("remittance_out", 400, "debit", "mobile_app", day=26, counterparty="SYN-RECIPIENT-01")
    p.household(0.88)

    # Missing opening date and home country: tenure and abroad rules cannot be
    # evaluated and are reported as such, never guessed.
    p = Person(g, 41, None, "opening date and home country missing", ["salary-earner"],
               expected_not_evaluated=["established-customer", "frequent-traveller", "new-customer"],
               home_country="")
    p.salary(3000)
    p.household(0.90)

    # Light, balanced activity funded by a monthly transfer: only the active tag applies.
    p = Person(g, 42, ago(500), "light balanced activity, only the active tag", [])
    p.monthly("transfer_in", 500, "credit", "incoming", day=2, counterparty="SYN-PERSON-070")
    p.household(0.88, n=2)

    # ---- Scenarios for the tags added in taxonomy 2.0.0 ------------------

    # A retainer from one business client every month, no salary.
    p = Person(g, 43, ago(T), "monthly retainer from one business client",
               ["active-customer", "business-income", "regular-other-income"])
    p.monthly("business_income", 1800, "credit", "incoming", day=6, counterparty="SYN-CLIENT-100")
    p.household(0.85)

    # Five restaurant and five grocery card payments every month.
    p = Person(g, 44, ago(T), "eats out and buys groceries every week",
               ["active-customer", "card-heavy-spender", "dining-out", "groceries-regular", "salary-earner"])
    p.salary(3500)
    for ym in MONTHS:
        p.spend(ym, 300, n=5, category="dining", days=[3, 9, 15, 21, 27])
        p.spend(ym, 500, n=5, category="groceries", days=[2, 8, 14, 20, 26])
    p.household(0.90, n=2)

    # Seven transport and fuel payments every month.
    p = Person(g, 45, ago(T), "commutes by transport and car",
               ["active-customer", "card-heavy-spender", "commuter", "salary-earner"])
    p.salary(3000)
    for ym in MONTHS:
        p.spend(ym, 160, n=4, category="transport", days=[3, 10, 17, 24])
        p.spend(ym, 180, n=3, category="fuel", days=[6, 13, 20])
    p.household(0.88, n=1)

    # One 2,600 electronics purchase in August, against 900 a month of card spending.
    p = Person(g, 46, ago(T), "one large purchase in August", ["active-customer", "big-ticket-purchase", "salary-earner"])
    p.salary(4000)
    p.monthly("transfer_out", 2400, "debit", "mobile_app", day=27, counterparty="SYN-PERSON-020")
    for ym in MONTHS:
        p.spend(ym, 900, n=3)
    p.add(datetime.date(2026, 8, 12), 2600, "debit", "card_pos", "shopping", "SYN-MERCHANT-0901", mcc="5732")

    # Monthly spending rises from 2,500 to 3,500 for the last 3 months (140%).
    p = Person(g, 47, ago(T), "spending up 40% in the last 3 months", ["active-customer", "salary-earner", "spending-rising"])
    p.salary(2800)
    p.monthly("transfer_out", 1500, "debit", "mobile_app", day=27, counterparty="SYN-PERSON-021")
    for ym in MONTHS:
        p.spend(ym, 2000 if ym in LAST3 else 1000)

    # Card used every month until June, then everything moves to the app.
    p = Person(g, 48, ago(T), "stopped using the card after June",
               ["active-customer", "card-dormant", "mobile-active", "salary-earner"])
    p.salary(3000)
    p.household(0.88, months=MONTHS[:9])
    p.household(0.88, months=LAST3, channel="mobile_app")

    # Two bills a month whose amounts swing by up to 40%: bills, but not steady
    # enough to count as recurring streams (near miss).
    p = Person(g, 49, ago(T), "bills whose amounts swing (near miss for recurring bills)",
               ["active-customer", "bill-payer", "salary-earner"])
    p.salary(3000)
    swings = [100, 140, 70, 125, 60, 135, 75, 130, 65, 140, 70, 130]
    for ym, amount in zip(MONTHS, swings):
        p.add(on(ym, 9), amount, "debit", "internet_banking", "utilities", "SYN-UTILITY-30")
        p.add(on(ym, 11), amount / 2, "debit", "internet_banking", "telecom", "SYN-TELECOM-30")
    p.household(0.90)

    # Four card payments abroad in September.
    p = Person(g, 50, ago(T), "a trip abroad this month", ["active-customer", "recent-traveller", "salary-earner"])
    p.salary(4000)
    p.household(0.88)
    p.spend((2026, 9), 450, n=3, days=[10, 12, 14], currency="EUR", country="FR")
    p.add(datetime.date(2026, 9, 11), 100, "debit", "atm", "cash_withdrawal", "", "EUR", "FR")

    # Flights and hotels in February, June and September, sent with a merchant
    # code but no category: the code table fills the category in.
    p = Person(g, 51, ago(T), "books flights and hotels", ["active-customer", "salary-earner", "travel-booker"])
    p.salary(4500)
    p.household(0.85)
    for when, amount, mcc in ((datetime.date(2026, 2, 3), 600, "4511"), (datetime.date(2026, 2, 5), 450, "7011"),
                              (datetime.date(2026, 6, 8), 700, "4511"), (datetime.date(2026, 9, 2), 300, "7011")):
        p.add(when, amount, "debit", "card_online", "", "SYN-MERCHANT-{}".format(mcc), mcc=mcc)

    # Opening balance 15,000 and keeps 15% a month: a buffer of seven months
    # of spending, but growing too slowly for "balance growing".
    p = Person(g, 52, ago(T), "keeps a healthy buffer", ["active-customer", "healthy-buffer", "salary-earner"],
               opening_balance=15000)
    p.salary(3000)
    p.household(0.85)

    # Keeps half of a 3,000 salary every month from an opening 1,500: the
    # month-end balance grows by 60% against the 6 months before.
    p = Person(g, 53, ago(T), "balance growing fast",
               ["active-customer", "balance-growing", "healthy-buffer", "salary-earner", "saver"],
               opening_balance=1500)
    p.salary(3000)
    p.household(0.50)

    # 25,000 on the account, one small card payment every other month and
    # quarterly interest.
    p = Person(g, 54, ago(T), "large balance, little activity", ["idle-balance"], opening_balance=25000)
    for ym in MONTHS[::2]:
        p.add(on(ym, 14), 60, "debit", "card_pos", "groceries", "SYN-MERCHANT-0954")
    for when in (datetime.date(2025, 12, 31), datetime.date(2026, 3, 31), datetime.date(2026, 6, 30),
                 datetime.date(2026, 9, 30)):
        p.add(when, "31.25", "credit", "system", "interest")

    # Rent, a utility and a phone bill at steady amounts every month.
    p = Person(g, 55, ago(T), "rent, utility and phone at steady amounts",
               ["active-customer", "bill-payer", "recurring-bills", "rent-payer", "salary-earner"])
    p.salary(3200)
    p.monthly("rent", 1100, "debit", "internet_banking", day=3, counterparty="SYN-LANDLORD-002")
    p.monthly("utilities", 95, "debit", "internet_banking", day=10, counterparty="SYN-UTILITY-31", jitter=800)
    p.monthly("telecom", 40, "debit", "mobile_app", day=12, counterparty="SYN-TELECOM-31")
    p.household(0.90)

    # Five subscriptions, two of them spelt differently from month to month as
    # bank feeds do; the counterparty table recognises one merchant behind each.
    p = Person(g, 56, ago(T), "five subscriptions, some spelt differently each month",
               ["active-customer", "card-heavy-spender", "many-subscriptions", "online-shopper", "salary-earner",
                "subscription-user"])
    p.salary(3000)
    stream_names = ["SYN STREAMCO*0412", "SYNSTREAMCO.EXAMPLE 2201", "SYN-STREAMCO"]
    music_names = ["SYN MUSICBOX 7781", "SYN-MUSICBOX"]
    for i, ym in enumerate(MONTHS):
        p.add(on(ym, 4), "15.99", "debit", "card_online", "subscription", stream_names[i % 3])
        p.add(on(ym, 7), "9.99", "debit", "card_online", "subscription", music_names[i % 2])
        for k, (name, price) in enumerate((("04", "6.99"), ("05", "11.99"), ("06", "4.99"))):
            p.add(on(ym, 10 + 3 * k), price, "debit", "card_online", "subscription", "SYN-SUBSCRIPTION-" + name)
    p.household(0.90, n=2)

    # Salary every month until June, none after; the account is still used.
    p = Person(g, 57, ago(T), "salary stopped after June, account still used",
               ["active-customer", "falling-income", "income-gap", "salary-moved-away"])
    p.salary(3200, MONTHS[:9])
    p.household(0.90)

    # Spends 2,050 before each 2,050 payday from a 2,100 balance: the lowest
    # balance is 50 every month, never below zero.
    p = Person(g, 58, ago(T), "balance dips to 50 before each payday",
               ["active-customer", "repeated-low-balance", "salary-earner"], opening_balance=2100)
    p.salary(2050)
    for ym in MONTHS:
        p.spend(ym, 2050)

    # Spending rises above the salary from April: overdrawn before every payday since.
    p = Person(g, 59, ago(T), "overdrawn before payday since April",
               ["active-customer", "overdrawn-months", "repeated-low-balance", "salary-earner",
                "spending-exceeds-inflow"], opening_balance=400)
    p.salary(2000)
    for ym in MONTHS:
        p.spend(ym, 2150 if ym >= (2026, 4) else 1900)

    # Two payments returned unpaid, in June and August.
    p = Person(g, 60, ago(T), "two payments returned unpaid",
               ["active-customer", "returned-payments", "salary-earner"])
    p.salary(2500)
    p.household(0.88)
    for when in (datetime.date(2026, 6, 18), datetime.date(2026, 8, 22)):
        p.add(when, 15, "debit", "system", "returned_payment")

    # Business income from one client every month until July, none since.
    p = Person(g, 61, ago(T), "business income stopped after July",
               ["active-customer", "business-income", "falling-income", "income-gap"])
    p.monthly("business_income", 2500, "credit", "incoming", months=MONTHS[:10], day=8,
              counterparty="SYN-CLIENT-200")
    p.household(0.85, months=MONTHS[:10])
    for ym in LAST3[1:]:
        p.spend(ym, 300)

    # Balance reaches zero before every payday and goes 50 below zero once,
    # in July (near miss for overdrawn months).
    p = Person(g, 62, ago(T), "overdrawn in only one month (near miss)",
               ["active-customer", "repeated-low-balance", "salary-earner"], opening_balance=2000)
    p.salary(2000)
    for ym in MONTHS:
        p.spend(ym, {(2026, 7): 2050, (2026, 8): 1950}.get(ym, 2000))


# ---------------------------------------------------------------------------
# Background customers: random, unlabelled.
# ---------------------------------------------------------------------------

def background(g, number):
    """A random background customer; 60% of them carry the balance after each transaction."""
    _background(g, number)
    person = g.people[-1]
    if g.rng.chance(0.6):
        person.opening_balance = money(g.rng.int(200, 6000))


def _background(g, number):
    r = g.rng
    roll = r.unit()
    if roll < 0.57:
        p = Person(g, number, ago(r.int(200, 3000)), clip=True)
        for _ in range(r.int(1, 7)):
            when = AS_OF - datetime.timedelta(days=r.int(0, 364))
            if when < p.open_date:
                continue
            if r.chance(0.35):
                p.add(when, r.int(100, 1500), "credit", "incoming", "transfer_in",
                      "SYN-PERSON-{:03d}".format(r.int(100, 999)))
            elif r.chance(0.5):
                p.add(when, r.int(20, 300), "debit", "atm", "cash_withdrawal")
            else:
                p.add(when, r.int(10, 400), "debit", r.pick(("card_pos", "card_online", "mobile_app")),
                      r.pick(PURCHASE_CATEGORIES), "SYN-MERCHANT-{:04d}".format(r.int(1, 400)))
        return
    if roll < 0.69:
        p = Person(g, number, ago(r.int(200, 3000)), clip=True)
        months = p.active_months()
        p.salary(50 * r.int(30, 90), months, day=r.int(24, 28), employer="SYN-EMPLOYER-{:03d}".format(r.int(100, 300)),
                 jitter=r.pick((0, 0, 5000)))
        if r.chance(0.35):
            p.monthly("utilities", r.int(60, 160), "debit", r.pick(("internet_banking", "mobile_app", "branch")),
                      months, day=10, counterparty="SYN-UTILITY-{:02d}".format(r.int(4, 20)), jitter=1500)
        p.household(0.75 + r.int(0, 22) / 100.0, n=1, months=months,
                    channel=r.pick(("card_pos", "card_pos", "mobile_app", "card_online")))
        return
    if roll < 0.75:
        p = Person(g, number, ago(r.int(300, 3000)), clip=True)
        currency, country = r.pick((("AED", "AE"), ("GBP", "GB"), ("EUR", "DE"), ("CAD", "CA")))
        base = Decimal(r.int(300, 900)) / RATES[currency]
        months = [ym for ym in p.active_months() if r.chance(0.7)]
        p.monthly("remittance_in", base, "credit", "incoming", months, day=r.int(2, 9),
                  counterparty="SYN-SENDER-{:03d}".format(r.int(100, 300)), jitter=2000, currency=currency,
                  country=country)
        for ym in months:
            inflow = p._sum(ym, "credit")
            p.add(on(ym, 12), money(inflow * Decimal("0.5")), "debit", "atm", "cash_withdrawal")
            if r.chance(0.5):
                p.add(on(ym, 24), money(inflow * Decimal("0.3")), "debit", "atm", "cash_withdrawal")
        return
    if roll < 0.80:
        p = Person(g, number, ago(r.int(120, 2000)), clip=True)
        months = p.active_months()
        p.monthly("transfer_in", r.int(800, 2500), "credit", "incoming", months, day=1,
                  counterparty="SYN-PERSON-{:03d}".format(r.int(100, 999)), jitter=3000)
        p.household(0.8 + r.int(0, 15) / 100.0, n=r.int(1, 2), months=months,
                    channel=r.pick(("mobile_app", "card_online", "internet_banking")))
        return
    if roll < 0.83:
        p = Person(g, number, ago(r.int(400, 3000)), clip=True)
        for ym in p.active_months():
            p.add(on(ym, 8), r.int(300, 1200), "credit", "branch", "cash_deposit")
            p.add(on(ym, 22), r.int(300, 1200), "credit", "branch", "cash_deposit")
            inflow = p._sum(ym, "credit")
            p.add(on(ym, 24), money(inflow * Decimal("0.6")), "debit", "internet_banking", "transfer_out",
                  "SYN-SUPPLIER-{:02d}".format(r.int(2, 30)))
            p.spend(ym, inflow * Decimal("0.3"), n=1)
        return
    if roll < 0.89:
        p = Person(g, number, ago(r.int(500, 3000)), clip=True)
        months = MONTHS[:r.int(1, 4)]
        p.salary(50 * r.int(30, 60), months, day=26, employer="SYN-EMPLOYER-{:03d}".format(r.int(100, 300)))
        p.household(0.9, n=1, months=months)
        return
    if roll < 0.94:
        p = Person(g, number, ago(r.int(3, 85)), clip=True)
        for _ in range(r.int(0, 3)):
            when = AS_OF - datetime.timedelta(days=r.int(0, (AS_OF - p.open_date).days))
            p.add(when, r.int(20, 600), r.pick(("credit", "debit")), r.pick(("branch", "card_pos", "mobile_app")),
                  r.pick(("cash_deposit", "groceries", "shopping")))
        return
    if roll < 0.96:
        p = Person(g, number, ago(r.int(400, 3000)), clip=True)
        p.salary(50 * r.int(60, 110), day=25, employer="SYN-EMPLOYER-{:03d}".format(r.int(100, 300)))
        p.household(0.85, n=1)
        for _ in range(r.int(1, 4)):
            ym = r.pick(MONTHS)
            currency, country = r.pick((("EUR", "FR"), ("GBP", "GB"), ("JPY", "JP"), ("EUR", "ES")))
            local = Decimal(r.int(80, 200)) / RATES[currency]
            p.spend(ym, local * 2, n=2, days=[17, 19], currency=currency, country=country)
        return
    if roll < 0.98:
        p = Person(g, number, ago(r.int(300, 2500)), clip=True)
        months = p.active_months()
        for i, ym in enumerate(months):
            for k in range(r.int(1, 3)):
                p.add(on(ym, 4 + 9 * k), r.int(300, 1400), "credit", "incoming", "business_income",
                      "SYN-CLIENT-{:03d}".format(100 + (number + i + k) % 7))
        p.household(0.85, n=1, months=months)
        return
    p = Person(g, number, ago(r.int(300, 3000)), clip=True)
    months = p.active_months()
    p.salary(50 * r.int(40, 80), months, day=25, employer="SYN-EMPLOYER-{:03d}".format(r.int(100, 300)))
    p.monthly("savings_transfer", 50 * r.int(4, 12), "debit", "mobile_app", months, day=26,
              counterparty="SYN-SAVINGS-{:03d}".format(number))
    p.household(0.85, n=1, months=months)


def malformed_rows(g):
    """A few deliberately bad rows, to show the engine's data notes."""
    bad = [
        ("C0050", "2026-05-14", "-25.00", "ZZZ", "debit", "card_online", "shopping"),   # unknown currency
        ("C0060", "2026-06-02", "-80.00", "USD", "credit", "incoming", "transfer_in"),  # sign conflict
        ("C0070", "", "-40.00", "USD", "debit", "card_pos", "groceries"),               # missing date
        ("C0080", "2026-07-19", "0.00", "USD", "debit", "card_pos", "dining"),          # zero amount
    ]
    for cid, posted, amount, currency, direction, channel, category in bad:
        g.extra_rows.append({
            "customer_id": cid, "account_id": "SYN-ACC-{:06d}".format(int(cid[1:])), "posted_date": posted,
            "amount": amount, "currency": currency, "direction": direction, "channel": channel,
            "category": category, "counterparty": "", "txn_country": HOME_COUNTRY, "mcc": "", "balance_after": "",
        })


def apply_v2_labels(g):
    by_number = {p.number: p for p in g.people}
    for tag_id, numbers in V2_EXPECTED.items():
        for number in numbers:
            by_number[number].expected.append(tag_id)
    for tag_id, numbers in V2_NOT_EVALUATED.items():
        for number in numbers:
            person = by_number[number]
            person.expected_not_evaluated = list(person.expected_not_evaluated or []) + [tag_id]


def build(seed=SEED, customers=300):
    g = Generator(seed)
    scenarios(g)
    apply_v2_labels(g)
    for number in range(len(g.people) + 1, customers + 1):
        background(g, number)
    malformed_rows(g)
    return g


def _check_dates(g):
    for person in g.people:
        for row in person.rows:
            if row["date"] > AS_OF:
                raise AssertionError("{} has a transaction after the as-of date".format(person.cid))
            if person.open_date is not None and row["date"] < person.open_date:
                raise AssertionError("{} has a transaction before the account opened".format(person.cid))


def write(g, out_dir):
    _check_dates(g)
    os.makedirs(out_dir, exist_ok=True)
    with open(os.path.join(out_dir, "customers.csv"), "w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle, lineterminator="\n")
        writer.writerow(CUSTOMER_COLUMNS)
        for p in sorted(g.people, key=lambda x: x.cid):
            writer.writerow([p.cid, "Synthetic Customer {:04d}".format(p.number), p.account,
                             p.open_date.isoformat() if p.open_date else "", p.home_country, p.home_currency])

    balances = {}
    for person in g.people:
        if person.opening_balance is None:
            continue
        running = person.opening_balance
        for row in sorted(person.rows, key=lambda r: (r["date"], r["seq"])):
            change = money(row["amount"] * RATES[row["currency"]])
            running += change if row["direction"] == "credit" else -change
            balances[row["seq"]] = running

    rows = []
    for person, row in g.rows_in_order:
        signed = row["amount"] if row["direction"] == "credit" else -row["amount"]
        balance = balances.get(row["seq"])
        rows.append({
            "customer_id": person.cid, "account_id": person.account, "posted_date": row["date"].isoformat(),
            "amount": "{:.2f}".format(signed), "currency": row["currency"], "direction": row["direction"],
            "channel": row["channel"], "category": row["category"], "counterparty": row["counterparty"],
            "txn_country": row["country"], "mcc": row["mcc"],
            "balance_after": "" if balance is None else "{:.2f}".format(balance),
            "_key": (row["date"].isoformat(), person.cid, row["seq"]),
        })
    rows.sort(key=lambda r: r["_key"])
    rows.extend(dict(r, _key=None) for r in g.extra_rows)
    with open(os.path.join(out_dir, "transactions.csv"), "w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle, lineterminator="\n")
        writer.writerow(TRANSACTION_COLUMNS)
        for index, row in enumerate(rows, start=1):
            row["txn_id"] = "T{:07d}".format(index)
            writer.writerow([row[c] for c in TRANSACTION_COLUMNS])

    labelled = []
    for p in g.people:
        if p.expected is None:
            continue
        entry = {"customer_id": p.cid, "scenario": p.scenario, "expected_tags": sorted(p.expected)}
        not_evaluated = set(p.expected_not_evaluated or ())
        if p.opening_balance is None:
            not_evaluated.update(BALANCE_TAGS)
        entry["expected_not_evaluated"] = sorted(not_evaluated)
        labelled.append(entry)
    expected = {
        "description": ("Expected tags for the labelled scenario customers in this synthetic data set. "
                        "Worked out by hand from each scenario's behaviour and the rules in "
                        "taxonomy/tags.json; the test suite checks the engine against them."),
        "as_of": AS_OF.isoformat(),
        "seed": g.seed,
        "customers": labelled,
    }
    with open(os.path.join(out_dir, "expected_tags.json"), "w", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(expected, indent=2) + "\n")
    return len(g.people), len(rows), len(labelled)


def main(argv=None):
    parser = argparse.ArgumentParser(description="Generate synthetic customers and transactions.")
    parser.add_argument("--seed", type=int, default=SEED)
    parser.add_argument("--customers", type=int, default=300)
    parser.add_argument("--out-dir", default=os.path.dirname(os.path.abspath(__file__)))
    args = parser.parse_args(argv)
    people, txns, labelled = write(build(args.seed, args.customers), args.out_dir)
    print("wrote {} customers, {} transactions, {} labelled scenarios to {}".format(
        people, txns, labelled, args.out_dir))


if __name__ == "__main__":
    main()

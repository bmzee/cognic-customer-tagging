"""One positive case and one near miss for every tag.

Most positives sit exactly on the threshold and most near misses sit just
below it, so the tests also pin down the boundary (>= versus >, window
edges, rounding to the displayed precision).
"""

import datetime

from tests.helpers import Case, LAST3, LAST6, MONTHS, days_ago, on

EARLIER6 = MONTHS[3:9]  # the 6 complete months before the last 3


def _salary(skip=()):
    return Case().salary(3000, [m for m in MONTHS if m not in skip])


def _earned(amounts, tenure=700):
    case = Case(open_days=tenure)
    for ym, amount in zip(MONTHS, amounts):
        if amount:
            case.add(on(ym, 15), amount, "credit", "incoming", "business_income", "SYN-CLIENT-001")
    return case


def _months_with(category, months, direction="debit", channel="internet_banking"):
    return Case().monthly(category, 100, direction, channel, months=months)


def _payers(n):
    case = Case()
    for k in range(n):
        case.add(days_ago(10 + k), 500, "credit", "incoming", "business_income", "SYN-CLIENT-{:03d}".format(k))
    case.add(days_ago(30), 500, "credit", "incoming", "business_income", "SYN-CLIENT-000")
    return case


def _income_change(recent):
    case = Case()
    for ym in EARLIER6:
        case.add(on(ym, 25), 2000, "credit", "incoming", "salary", "SYN-EMPLOYER-001")
    for ym in LAST3:
        case.add(on(ym, 25), recent, "credit", "incoming", "salary", "SYN-EMPLOYER-001")
    return case


def _large_inflow(amount):
    case = Case().salary(2000)
    case.add(datetime.date(2026, 8, 12), amount, "credit", "incoming", "transfer_in", "SYN-PERSON-001")
    return case


def _p2p(n):
    case = Case()
    for k in range(n):
        category, direction = ("transfer_out", "debit") if k % 2 else ("transfer_in", "credit")
        case.add(days_ago(5 + 7 * k), 50, direction, "mobile_app" if direction == "debit" else "incoming",
                 category, "SYN-PERSON-{:03d}".format(k))
    return case


def _subscriptions(n):
    case = Case()
    for ym in LAST3:
        for k in range(n):
            case.add(on(ym, 3 + k), 9.99, "debit", "card_online", "subscription", "SYN-SUBSCRIPTION-{:02d}".format(k))
    return case


def _fees(dates):
    case = Case()
    for when in dates:
        case.add(when, 25, "debit", "system", "fee")
    return case


def _card_heavy(cards, transfer):
    case = Case()
    for k in range(cards):
        case.add(days_ago(2 + 5 * k), 100, "debit", "card_pos", "groceries", "SYN-MERCHANT-0001")
    case.add(days_ago(20), transfer, "debit", "mobile_app", "transfer_out", "SYN-PERSON-001")
    return case


def _online(n):
    case = Case()
    for k in range(n):
        case.add(days_ago(3 + 9 * k), 40, "debit", "card_online", "shopping", "SYN-MERCHANT-0002")
    return case


def _cash(other_spend):
    case = Case()
    for k in range(4):
        case.add(days_ago(5 + 20 * k), 100, "debit", "atm", "cash_withdrawal")
    case.add(days_ago(12), other_spend, "debit", "card_pos", "groceries", "SYN-MERCHANT-0003")
    return case


def _fx(domestic):
    case = Case()
    for k in range(3):
        case.add(days_ago(10 + 20 * k), 100, "debit", "card_online", "shopping", "SYN-MERCHANT-0004", "EUR", "DE")
    case.add(days_ago(15), domestic, "debit", "card_pos", "groceries", "SYN-MERCHANT-0005")
    return case


def _channels(main_channel, main, card):
    case = Case()
    for k in range(main):
        case.add(days_ago(1 + 4 * k), 20, "debit", main_channel, "shopping", "SYN-MERCHANT-0006")
    for k in range(card):
        case.add(days_ago(3 + 4 * k), 20, "debit", "card_pos", "groceries", "SYN-MERCHANT-0007")
    return case


def _surplus(months_kept):
    case = Case().salary(1000)
    for i, ym in enumerate(MONTHS):
        case.purchases(ym, 2, 400 if i < months_kept else 450)
    return case


def _investments(dates):
    case = Case()
    for when in dates:
        case.add(when, 1000, "debit", "internet_banking", "investment", "SYN-BROKER-01")
    return case


def _deficits(last_gap):
    case = Case().salary(2000)
    for i, ym in enumerate(MONTHS):
        if ym in LAST6[:3]:
            spend = 2100
        elif ym == LAST6[3]:
            spend = 2000 + last_gap
        else:
            spend = 1500
        case.purchases(ym, 1, spend)  # one purchase, so no rounding of halves
    return case


def _abroad(trips):
    case = Case()
    for ym, country, currency in trips:
        case.add(on(ym, 16), 80, "debit", "card_pos", "dining", "SYN-MERCHANT-0008", currency, country)
    return case


def _established(tenure):
    case = Case(open_days=tenure)
    for ym in MONTHS[2:]:
        case.add(on(ym, 9), 30, "debit", "card_pos", "groceries", "SYN-MERCHANT-0009")
    return case


def _going_dormant(recent):
    case = Case()
    for ym in MONTHS[:9]:
        for day in (10, 14, 18, 22):
            case.add(on(ym, day), 30, "debit", "card_pos", "groceries", "SYN-MERCHANT-0010")
    for k in range(recent):
        case.add(on(LAST3[k % 3], 10 + k), 30, "debit", "card_pos", "groceries", "SYN-MERCHANT-0010")
    return case


def _dormant(last_activity):
    case = Case()
    case.add(last_activity, 30, "debit", "card_pos", "groceries", "SYN-MERCHANT-0011")
    case.add(datetime.date(2026, 6, 30), 2.15, "credit", "system", "interest")
    return case


def _re_engaged(earlier):
    case = Case()
    for ym in MONTHS[:3]:
        case.purchases(ym, 3, 30)
    for k in range(earlier):
        case.add(datetime.date(2026, 3, 10 + k), 30, "debit", "card_pos", "groceries", "SYN-MERCHANT-0012")
    for ym in LAST3:
        case.purchases(ym, 2, 30)
    return case


# -- cases for the tags added in taxonomy 2.0.0 -------------------------------

def _retainer(months):
    case = Case()
    for ym in months:
        case.add(on(ym, 6), 1000, "credit", "incoming", "business_income", "SYN-CLIENT-300")
    return case


def _monthly_purchases(months, plan):
    """plan: [(category, count), ...] card purchases in each month."""
    case = Case()
    for ym in months:
        day = 2
        for category, count in plan:
            for _ in range(count):
                case.add(on(ym, day), 25, "debit", "card_pos", category, "SYN-MERCHANT-0020")
                day += 1
    return case


def _big_ticket(amount):
    case = Case()
    for ym in EARLIER6:
        case.add(on(ym, 10), 1000, "debit", "card_pos", "shopping", "SYN-MERCHANT-0021")
    case.add(datetime.date(2026, 8, 12), amount, "debit", "card_pos", "shopping", "SYN-MERCHANT-0022", mcc="5732")
    return case


def _spending_change(recent):
    case = Case()
    for ym in EARLIER6:
        case.add(on(ym, 10), 1000, "debit", "card_pos", "shopping", "SYN-MERCHANT-0023")
    for ym in LAST3:
        case.add(on(ym, 10), recent, "debit", "card_pos", "shopping", "SYN-MERCHANT-0023")
    return case


def _card_dormant(recent_cards):
    case = Case()
    for ym in EARLIER6:
        case.add(on(ym, 10), 40, "debit", "card_pos", "groceries", "SYN-MERCHANT-0024")
    for k in range(recent_cards):
        case.add(on(LAST3[k], 10), 40, "debit", "card_pos", "groceries", "SYN-MERCHANT-0024")
    case.monthly("transfer_out", 100, channel="mobile_app", months=LAST3, counterparty="SYN-PERSON-030")
    return case


def _app(per_month):
    case = Case()
    for ym, count in zip(LAST3, per_month):
        for k in range(count):
            case.add(on(ym, 5 + k), 20, "debit", "mobile_app", "transfer_out", "SYN-PERSON-031")
    return case


def _recent_abroad(second_days_ago):
    case = Case()
    case.add(days_ago(5), 60, "debit", "card_pos", "dining", "SYN-MERCHANT-0025", "EUR", "FR")
    case.add(days_ago(second_days_ago), 60, "debit", "atm", "cash_withdrawal", "", "EUR", "FR")
    return case


def _travel(months):
    case = Case()
    for ym in months:
        case.add(on(ym, 3), 400, "debit", "card_online", "", "SYN-MERCHANT-4511", mcc="4511")
    return case


def _buffer(month_end):
    case = Case()
    for ym in LAST6:
        case.add(on(ym, 5), 1000, "credit", "incoming", "salary", "SYN-EMPLOYER-001", balance=month_end + 1000)
        case.add(on(ym, 20), 1000, "debit", "card_pos", "shopping", "SYN-MERCHANT-0026", balance=month_end)
    return case


def _balance_growth(recent_end):
    case = Case()
    for ym in EARLIER6:
        case.add(on(ym, 15), 10, "credit", "incoming", "transfer_in", "SYN-PERSON-032", balance=2000)
    for ym in LAST3:
        case.add(on(ym, 15), 10, "credit", "incoming", "transfer_in", "SYN-PERSON-032", balance=recent_end)
    return case


def _idle(purchases):
    case = Case()
    for ym in LAST6:
        case.add(on(ym, 28), 2, "credit", "system", "interest", balance=10000)
    for k in range(purchases):
        case.add(days_ago(10 + 9 * k), 10, "debit", "card_pos", "groceries", "SYN-MERCHANT-0027", balance=10000)
    return case


def _bills(telecom_months):
    case = Case()
    case.monthly("utilities", 100, months=LAST6[2:], counterparty="SYN-UTILITY-01")
    case.monthly("telecom", 50, months=telecom_months, day=12, counterparty="SYN-TELECOM-01")
    return case


def _active(months):
    case = Case()
    for ym in months:
        case.add(on(ym, 10), 30, "debit", "card_pos", "groceries", "SYN-MERCHANT-0028")
    return case


def _salary_stopped(salary_months):
    case = Case()
    for ym in salary_months:
        case.add(on(ym, 25), 3000, "credit", "incoming", "salary", "SYN-EMPLOYER-001")
    for ym in LAST3:
        case.add(on(ym, 10), 30, "debit", "card_pos", "groceries", "SYN-MERCHANT-0029")
    return case


def _low_balance(lows, low_value):
    """One balance a month for the last 6 months; the first `lows` months are low."""
    case = Case()
    for i, ym in enumerate(LAST6):
        value = low_value if i < lows else 500
        case.add(on(ym, 12), 20, "debit", "card_pos", "groceries", "SYN-MERCHANT-0030", balance=value)
        case.add(on(ym, 26), 20, "credit", "incoming", "transfer_in", "SYN-PERSON-033", balance=value + 400)
    return case


def _returned(second_days_ago):
    case = Case()
    for days in (10, second_days_ago):
        case.add(days_ago(days), 15, "debit", "system", "returned_payment")
    return case


def _earned_then_gap(months):
    case = Case()
    for ym in months:
        case.add(on(ym, 25), 2000, "credit", "incoming", "salary", "SYN-EMPLOYER-001")
    return case


CASES = {
    "salary-earner": (lambda: _salary(), lambda: _salary(skip=[(2026, 6)])),
    "irregular-income": (lambda: _earned([2000] * 7 + [4000] * 5), lambda: _earned([2000] * 8 + [4000] * 4)),
    "multi-source-income": (lambda: _payers(3), lambda: _payers(2)),
    "business-income": (
        lambda: _earned([0] * 6 + [1000, 1000, 0, 1000, 0, 1000]),
        lambda: _earned([1000] * 6 + [1000, 0, 0, 1000, 0, 1000])),
    "remittance-receiver": (
        lambda: _months_with("remittance_in", LAST6[:3], "credit", "incoming"),
        lambda: _months_with("remittance_in", MONTHS[:6] + LAST6[:2], "credit", "incoming")),
    "rising-income": (lambda: _income_change(2500), lambda: _income_change(2490)),
    "falling-income": (lambda: _income_change(1200), lambda: _income_change(1210)),
    "large-recent-inflow": (lambda: _large_inflow(6000), lambda: _large_inflow(5900)),
    "high-inflow": (lambda: Case().salary(5000), lambda: Case().salary(4999.99)),
    "bill-payer": (lambda: _months_with("utilities", LAST6[1:]), lambda: _months_with("telecom", MONTHS[:6] + LAST6[2:])),
    "rent-payer": (lambda: _months_with("rent", LAST6[:5]), lambda: _months_with("rent", LAST6[:4])),
    "loan-repayer": (lambda: _months_with("loan_repayment", LAST6[1:]), lambda: _months_with("loan_repayment", LAST6[2:])),
    "insurance-payer": (lambda: _months_with("insurance", MONTHS[0::4]), lambda: _months_with("insurance", MONTHS[0::6])),
    "remittance-sender": (
        lambda: _months_with("remittance_out", LAST6[0::2], channel="mobile_app"),
        lambda: _months_with("remittance_out", MONTHS[:6] + LAST6[0::3], channel="mobile_app")),
    "p2p-transfer-active": (lambda: _p2p(10), lambda: _p2p(9)),
    "subscription-user": (lambda: _subscriptions(3), lambda: _subscriptions(2)),
    "frequent-fee-payer": (
        lambda: _fees([datetime.date(2026, 7, 3), datetime.date(2026, 8, 1), datetime.date(2026, 9, 1)]),
        lambda: _fees([datetime.date(2026, 7, 2), datetime.date(2026, 8, 1), datetime.date(2026, 9, 1)])),
    "card-heavy-spender": (lambda: _card_heavy(15, 1000), lambda: _card_heavy(15, 1001)),
    "online-shopper": (lambda: _online(8), lambda: _online(7)),
    "high-cash-user": (lambda: _cash(600), lambda: _cash(601)),
    "foreign-currency-spender": (lambda: _fx(990), lambda: _fx(991)),
    "digital-first": (lambda: _channels("mobile_app", 8, 2), lambda: _channels("mobile_app", 11, 3)),
    "branch-reliant": (lambda: _channels("branch", 3, 3), lambda: _channels("branch", 3, 4)),
    "cash-depositor": (
        lambda: _months_with("cash_deposit", LAST6[2:], "credit", "branch"),
        lambda: _months_with("cash_deposit", LAST6[3:], "credit", "branch")),
    "saver": (
        lambda: _months_with("savings_transfer", LAST6[1:], channel="mobile_app"),
        lambda: _months_with("savings_transfer", LAST6[2:], channel="mobile_app")),
    "investor": (
        lambda: _investments([datetime.date(2026, 4, 4), datetime.date(2026, 9, 1)]),
        lambda: _investments([datetime.date(2026, 4, 3), datetime.date(2026, 9, 1)])),
    "spending-exceeds-inflow": (lambda: _deficits(100), lambda: _deficits(99.99)),
    "frequent-traveller": (
        lambda: _abroad([(MONTHS[1], "GB", "GBP"), (MONTHS[5], "FR", "EUR"), (MONTHS[9], "GB", "GBP")]),
        lambda: _abroad([(MONTHS[1], "GB", "GBP"), (MONTHS[5], "GB", "GBP"), (MONTHS[9], "GB", "GBP")])),
    "new-customer": (lambda: Case(open_days=90), lambda: Case(open_days=91)),
    "established-customer": (lambda: _established(1095), lambda: _established(1094)),
    "going-dormant": (lambda: _going_dormant(3), lambda: _going_dormant(4)),
    "dormant": (lambda: _dormant(datetime.date(2026, 4, 3)), lambda: _dormant(datetime.date(2026, 4, 4))),
    "re-engaged": (lambda: _re_engaged(1), lambda: _re_engaged(2)),
    # taxonomy 2.0.0
    "regular-other-income": (lambda: _retainer(LAST6[2:]), lambda: _retainer(LAST6[3:])),
    "dining-out": (lambda: _monthly_purchases(LAST6[2:], [("dining", 4)]),
                   lambda: _monthly_purchases(LAST6[2:], [("dining", 3)])),
    "groceries-regular": (lambda: _monthly_purchases(LAST6[1:], [("groceries", 4)]),
                          lambda: _monthly_purchases(LAST6[2:], [("groceries", 4)])),
    "commuter": (lambda: _monthly_purchases(LAST6[2:], [("transport", 3), ("fuel", 3)]),
                 lambda: _monthly_purchases(LAST6[2:], [("transport", 3), ("fuel", 2)])),
    "big-ticket-purchase": (lambda: _big_ticket(1500), lambda: _big_ticket(1499.99)),
    "spending-rising": (lambda: _spending_change(1300), lambda: _spending_change(1299)),
    "card-dormant": (lambda: _card_dormant(0), lambda: _card_dormant(1)),
    "mobile-active": (lambda: _app([2, 2, 2]), lambda: _app([2, 2, 1])),
    "recent-traveller": (lambda: _recent_abroad(29), lambda: _recent_abroad(30)),
    "travel-booker": (lambda: _travel([MONTHS[2], MONTHS[8]]), lambda: _travel([MONTHS[8]])),
    "healthy-buffer": (lambda: _buffer(3000), lambda: _buffer(2990)),
    "balance-growing": (lambda: _balance_growth(3000), lambda: _balance_growth(2990)),
    "idle-balance": (lambda: _idle(6), lambda: _idle(7)),
    "recurring-bills": (lambda: _bills(LAST6[2:]), lambda: _bills(LAST6[3:])),
    "many-subscriptions": (lambda: _subscriptions(4), lambda: _subscriptions(3)),
    "active-customer": (lambda: _active(LAST3), lambda: _active(LAST3[1:])),
    "salary-moved-away": (lambda: _salary_stopped(MONTHS[4:9]), lambda: _salary_stopped(MONTHS[5:9])),
    "repeated-low-balance": (lambda: _low_balance(3, 99.99), lambda: _low_balance(2, 99.99)),
    "overdrawn-months": (lambda: _low_balance(2, -0.01), lambda: _low_balance(1, -0.01)),
    "returned-payments": (lambda: _returned(179), lambda: _returned(180)),
    "income-gap": (lambda: _earned_then_gap(MONTHS[5:10]), lambda: _earned_then_gap(MONTHS[6:10])),
}

# The saver rule has two branches; the second is tested separately.
SAVER_SURPLUS = (lambda: _surplus(9), lambda: _surplus(8))

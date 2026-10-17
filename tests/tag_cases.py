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
}

# The saver rule has two branches; the second is tested separately.
SAVER_SURPLUS = (lambda: _surplus(9), lambda: _surplus(8))

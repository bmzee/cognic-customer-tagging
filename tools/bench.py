#!/usr/bin/env python3
"""Benchmarks for the builder: rebuild time and continuous-update latency.

python3 tools/bench.py data --customers 200000 --per-customer 25 --out DIR
    A fast, dense, seeded synthetic data set (customers.csv and
    transactions.csv) for scale tests. Everything is invented.

python3 tools/bench.py rebuild --data DIR --store STORE
    Time a full rebuild of the profile store from DIR.

python3 tools/bench.py follow --store STORE --events 2000
    Copy STORE, then apply live events to the copy one at a time (one
    transaction each), as a change feed would deliver them, and report
    events per second and the p50 and p99 time per event. Ticks are timed
    separately: a tick re-evaluates every customer by design.

Each command prints one JSON line with its measurements. Run large data sets
in CI only (.github/workflows/benchmark.yml); keep local runs small.
"""

import argparse
import csv
import datetime
import json
import os
import random
import shutil
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from engine import events as ev  # noqa: E402
from engine import load_taxonomy, DEFAULT_TAXONOMY  # noqa: E402

AS_OF = datetime.date(2026, 9, 30)
FIRST = datetime.date(2025, 10, 1)
SPEND = (("card_pos", "groceries"), ("card_pos", "dining"), ("card_pos", "fuel"), ("card_online", "shopping"),
         ("card_online", "subscription"), ("mobile_app", "transfer_out"), ("atm", "cash_withdrawal"),
         ("internet_banking", "utilities"), ("internet_banking", "rent"), ("system", "fee"))


def generate(customers, per_customer, out_dir, seed=20261018):
    os.makedirs(out_dir, exist_ok=True)
    rng = random.Random(seed)
    span = (AS_OF - FIRST).days
    rows = 0
    with open(os.path.join(out_dir, "customers.csv"), "w", encoding="utf-8", newline="") as cfile, \
            open(os.path.join(out_dir, "transactions.csv"), "w", encoding="utf-8", newline="") as tfile:
        cw, tw = csv.writer(cfile, lineterminator="\n"), csv.writer(tfile, lineterminator="\n")
        cw.writerow(["customer_id", "account_open_date", "home_country", "home_currency"])
        tw.writerow(["txn_id", "customer_id", "posted_date", "amount", "currency", "direction", "channel",
                     "category", "counterparty", "txn_country", "mcc", "balance_after"])
        for number in range(1, customers + 1):
            cid = "B{:07d}".format(number)
            opened = datetime.date(2015, 1, 1) + datetime.timedelta(days=rng.randint(0, 3800))
            cw.writerow([cid, opened.isoformat(), "US", "USD"])
            txns = []
            salaried = rng.random() < 0.7
            if salaried:
                pay = 50 * rng.randint(30, 120)
                employer = "SYN-EMPLOYER-{:03d}".format(rng.randint(1, 200))
                for k in range(12):
                    month = (FIRST.month - 1 + k) % 12 + 1
                    year = FIRST.year + (FIRST.month - 1 + k) // 12
                    txns.append((datetime.date(year, month, 25), pay, "credit", "incoming", "salary", employer))
            while len(txns) < per_customer:
                when = FIRST + datetime.timedelta(days=rng.randint(0, span))
                if when < opened:
                    when = opened if opened <= AS_OF else AS_OF
                channel, category = SPEND[rng.randrange(len(SPEND))]
                if category == "transfer_out" and rng.random() < 0.3:
                    txns.append((when, rng.randint(20, 900), "credit", "incoming", "transfer_in",
                                 "SYN-PERSON-{:04d}".format(rng.randint(1, 5000))))
                    continue
                counterparty = ("SYN-PERSON-{:04d}".format(rng.randint(1, 5000)) if category == "transfer_out"
                                else "SYN-MERCHANT-{:04d}".format(rng.randint(1, 800)))
                txns.append((when, round(rng.uniform(3, 600), 2), "debit", channel, category, counterparty))
            txns.sort(key=lambda t: t[0])
            balance = rng.randint(100, 8000) if rng.random() < 0.5 else None
            for k, (when, amount, direction, channel, category, counterparty) in enumerate(txns):
                if balance is not None:
                    balance = round(balance + (amount if direction == "credit" else -amount), 2)
                tw.writerow(["{}-{:03d}".format(cid, k), cid, when.isoformat(),
                             "{:.2f}".format(amount if direction == "credit" else -amount), "USD", direction,
                             channel, category, counterparty, "US", "", "" if balance is None else
                             "{:.2f}".format(balance)])
                rows += 1
    return {"customers": customers, "transactions": rows}


def rebuild(data_dir, store):
    from engine import build
    started = time.perf_counter()
    summary = build.rebuild(os.path.join(data_dir, "customers.csv"), os.path.join(data_dir, "transactions.csv"),
                            store)
    seconds = time.perf_counter() - started
    return dict(summary, seconds=round(seconds, 1), store_bytes=os.path.getsize(store))


def percentile(values, p):
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, int(round(p / 100.0 * (len(ordered) - 1)))))
    return ordered[index]


def follow(store, count, seed=7):
    from engine.incremental import Follower
    work = store + ".bench"
    shutil.copy(store, work)
    taxonomy = load_taxonomy(DEFAULT_TAXONOMY)
    follower = Follower(work, taxonomy)
    try:
        customers = [row[0] for row in follower.connection.execute("SELECT customer_id FROM customers")]
        as_of = follower.as_of
        rng = random.Random(seed)
        live = []
        for k in range(count):
            cid = customers[rng.randrange(len(customers))]
            when = as_of + datetime.timedelta(days=rng.randint(-2, 1))
            channel, category = SPEND[rng.randrange(6)]
            live.append(ev.make("live-{:06d}".format(k), "transaction.posted", when, cid, {
                "txn_id": "LIVE-{:06d}".format(k), "amount": "-{:.2f}".format(rng.uniform(3, 300)),
                "currency": "USD", "direction": "debit", "channel": channel, "category": category,
                "counterparty": "SYN-MERCHANT-{:04d}".format(rng.randint(1, 800))}))
        latencies = []
        started = time.perf_counter()
        for raw in live:
            t0 = time.perf_counter()
            follower.apply([raw])
            latencies.append((time.perf_counter() - t0) * 1000.0)
        elapsed = time.perf_counter() - started
        batch = [ev.make("batch-{:06d}".format(k), "transaction.posted", as_of, customers[k % len(customers)], {
            "txn_id": "BATCH-{:06d}".format(k), "amount": "-12.00", "currency": "USD", "channel": "card_pos",
            "category": "groceries"}) for k in range(min(count, 500))]
        t0 = time.perf_counter()
        follower.apply(batch)
        batch_seconds = time.perf_counter() - t0
        t0 = time.perf_counter()
        follower.apply([ev.make("bench-tick", "clock.tick", as_of + datetime.timedelta(days=1))])
        tick_seconds = time.perf_counter() - t0
    finally:
        follower.close()
        for suffix in ("", "-wal", "-shm"):
            if os.path.exists(work + suffix):
                os.remove(work + suffix)
    return {"customers": len(customers), "events": count,
            "events_per_second_one_per_transaction": round(count / elapsed, 1),
            "p50_ms": round(percentile(latencies, 50), 2), "p99_ms": round(percentile(latencies, 99), 2),
            "events_per_second_in_batches_of_500": round(len(batch) / batch_seconds, 1),
            "tick_seconds": round(tick_seconds, 1)}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("data")
    p.add_argument("--customers", type=int, required=True)
    p.add_argument("--per-customer", type=int, default=25)
    p.add_argument("--out", required=True)
    p = sub.add_parser("rebuild")
    p.add_argument("--data", required=True)
    p.add_argument("--store", required=True)
    p = sub.add_parser("follow")
    p.add_argument("--store", required=True)
    p.add_argument("--events", type=int, default=2000)
    args = parser.parse_args(argv)
    if args.command == "data":
        result = generate(args.customers, args.per_customer, args.out)
    elif args.command == "rebuild":
        result = rebuild(args.data, args.store)
    else:
        result = follow(args.store, args.events)
    sys.stdout.write(json.dumps(dict(result, command=args.command)) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())

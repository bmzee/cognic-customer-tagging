"""Tag lifecycle: month-end checkpoints, entered_on, new this month, ended
this month, and the exclusive lifecycle group."""

import datetime
import unittest

from engine import lifecycle
from tests.helpers import MONTHS, Case, on

LIFECYCLE_TAGS = ("active-customer", "going-dormant", "dormant", "re-engaged", "new-customer")


def _active_then_quiet():
    """Four card payments a month from October to March, then nothing."""
    case = Case()
    for ym in MONTHS[:6]:
        for day in (5, 12, 19, 26):
            case.add(on(ym, day), 30, "debit", "card_pos", "groceries", "SYN-MERCHANT-0040")
    return case


def _abroad(days):
    case = Case()
    for day in days:
        case.add(day, 50, "debit", "card_pos", "dining", "SYN-MERCHANT-0041", "EUR", "FR")
    return case


class Checkpoints(unittest.TestCase):
    def test_checkpoints_are_month_ends_up_to_the_as_of_date(self):
        days = lifecycle.checkpoints(datetime.date(2026, 9, 30), 13)
        self.assertEqual(len(days), 13)
        self.assertEqual(days[0], datetime.date(2025, 9, 30))
        self.assertEqual(days[-1], datetime.date(2026, 9, 30))

    def test_a_mid_month_as_of_date_ends_at_the_previous_month_end(self):
        days = lifecycle.checkpoints(datetime.date(2026, 9, 15), 13)
        self.assertEqual(days[-1], datetime.date(2026, 8, 31))


class Transitions(unittest.TestCase):
    def test_active_then_going_dormant_then_dormant(self):
        life, states = _active_then_quiet().lifecycle(months=13)
        events = [(day.isoformat(), tag_id, kind) for day, tag_id, kind, _ in life.events
                  if tag_id in LIFECYCLE_TAGS]
        self.assertEqual(events, [
            # No activity before October 2025 on a 700-day-old account: dormant.
            ("2025-09-30", "dormant", "entered"),
            ("2025-10-31", "dormant", "exited"),
            # 8 payments in 90 days after a quiet half year: re-engaged, which
            # outranks active in the lifecycle group.
            ("2025-11-30", "re-engaged", "entered"),
            ("2026-01-31", "active-customer", "entered"),
            ("2026-01-31", "re-engaged", "exited"),
            # April has no activity, so the last 3 complete months are not all active.
            ("2026-04-30", "active-customer", "exited"),
            # Nothing in the last 90 days against 4 a month before.
            ("2026-06-30", "going-dormant", "entered"),
            # Nothing in 180 days: dormant outranks going dormant.
            ("2026-09-30", "going-dormant", "exited"),
            ("2026-09-30", "dormant", "entered"),
        ])
        # Exactly one lifecycle stage at each checkpoint where any holds.
        for day, held in states.items():
            self.assertLessEqual(sum(held[t] for t in LIFECYCLE_TAGS), 1, day)

    def test_entered_on_is_the_first_checkpoint_of_the_current_run(self):
        life, _ = Case().salary(3000).lifecycle(months=13)
        self.assertEqual(life.entered_on["salary-earner"], datetime.date(2026, 3, 31))
        self.assertFalse(life.new_this_month["salary-earner"])
        self.assertFalse(life.since_window_start["salary-earner"])

    def test_a_tag_held_since_the_first_checkpoint_says_so(self):
        life, states = Case(open_days=3000).lifecycle()  # no activity at all: dormant throughout
        self.assertEqual(len(states), 6)  # lifecycle_months
        self.assertTrue(all(held["dormant"] for held in states.values()))
        self.assertEqual(life.entered_on["dormant"], datetime.date(2026, 4, 30))
        self.assertTrue(life.since_window_start["dormant"])
        self.assertEqual(life.events[0][1:], ("dormant", "entered", True))

    def test_new_this_month_has_no_entered_on_yet(self):
        case = _abroad([datetime.date(2026, 9, 5), datetime.date(2026, 9, 10)])
        life, _ = case.lifecycle(as_of=datetime.date(2026, 9, 15))
        self.assertTrue(life.new_this_month["recent-traveller"])
        self.assertIsNone(life.entered_on["recent-traveller"])
        self.assertEqual(life.last_checkpoint, datetime.date(2026, 8, 31))
        # At the month end it becomes a checkpoint, and entered_on is set.
        life, _ = case.lifecycle(as_of=datetime.date(2026, 9, 30))
        self.assertEqual(life.entered_on["recent-traveller"], datetime.date(2026, 9, 30))

    def test_a_tag_that_stopped_after_the_last_checkpoint_ended_this_month(self):
        case = _abroad([datetime.date(2026, 8, 20), datetime.date(2026, 8, 25)])
        life, _ = case.lifecycle(as_of=datetime.date(2026, 9, 28))
        self.assertIn("recent-traveller", life.ended_this_month)

    def test_history_is_a_function_of_the_data(self):
        first, _ = _active_then_quiet().lifecycle(months=13)
        second, _ = _active_then_quiet().lifecycle(months=13)
        self.assertEqual(first.events, second.events)


class ExclusiveGroup(unittest.TestCase):
    def test_the_higher_priority_stage_wins_and_the_other_is_reported(self):
        case = Case()
        for ym in MONTHS[:3]:
            case.purchases(ym, 3, 30)
        for ym in MONTHS[9:]:
            case.purchases(ym, 3, 30)
        results = case.evaluate()
        self.assertIs(results["re-engaged"].state, True)
        active = results["active-customer"]
        self.assertIs(active.rule_state, True)
        self.assertIs(active.state, False)
        self.assertEqual(active.suppressed_by, "re-engaged")


if __name__ == "__main__":
    unittest.main()


class FastPathsAgree(unittest.TestCase):
    def test_state_only_and_held_evidence_match_full_evaluation(self):
        """Checkpoints use a short-circuit state-only pass and the as-of date
        explains only held tags; both must give exactly the full evaluation's
        states and missing fields for every synthetic customer."""
        import os
        import engine
        from engine import data as data_module
        from engine.evaluate import evaluate_data
        from tests.helpers import ROOT, TAXONOMY
        folder = os.path.join(ROOT, "data")
        customers, _ = data_module.load_customers(os.path.join(folder, "customers.csv"), TAXONOMY.base_currency)
        txns, as_of, _, _ = data_module.load_transactions(os.path.join(folder, "transactions.csv"), customers,
                                                          TAXONOMY)
        for day in (as_of, datetime.date(2026, 6, 30), datetime.date(2026, 8, 17)):
            for cid in customers:
                rows = [t for t in txns[cid] if t.posted_date <= day]
                data = engine.customer_data(TAXONOMY, customers[cid], rows)
                full = evaluate_data(TAXONOMY, data, day, True)
                for mode in (False, "held"):
                    fast = evaluate_data(TAXONOMY, data, day, mode)
                    for tag_id, result in full.items():
                        other = fast[tag_id]
                        self.assertEqual((result.state, result.suppressed_by), (other.state, other.suppressed_by),
                                         (cid, day, tag_id, mode))
                        if result.state is None:
                            self.assertEqual(result.missing, other.missing, (cid, day, tag_id, mode))
                        if mode == "held" and result.state is True:
                            self.assertEqual(result.evidence, other.evidence)
                            self.assertEqual(result.reason, other.reason)

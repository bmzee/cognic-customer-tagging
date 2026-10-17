"""Tag lifecycle: when a tag entered and when it stopped holding.

Tags are evaluated at month-end checkpoints (the last `lifecycle_months`
month ends up to the as-of date) and at the as-of date itself. History is recorded at checkpoint resolution, which a batch
rebuild can always reproduce exactly (see DESIGN.md):

* entered_on: the first checkpoint of the current unbroken run of
  checkpoints at which the tag held. A tag that holds now but did not hold
  at the last checkpoint is "new this month" and has no entered_on yet.
* exited_on: the first checkpoint at which a tag that held before no longer
  held.

The as-of state is exact to the day; only the history is monthly.
"""

from collections import OrderedDict

from . import windows
from .evaluate import evaluate_data


def checkpoints(as_of, count):
    """The last `count` month ends at or before as_of, oldest first."""
    last = windows.last_complete_month(as_of)
    months = [windows.shift_month(last, -i) for i in range(count - 1, -1, -1)]
    return [windows.month_bounds(m)[1] for m in months]


def checkpoint_states(taxonomy, data, as_of, count, current=None):
    """{checkpoint date: {tag_id: held}} plus the as-of results.

    current, if given, is the already evaluated as-of result (with evidence);
    it is reused when as_of is itself a checkpoint."""
    states = OrderedDict()
    for day in checkpoints(as_of, count):
        if day == as_of and current is not None:
            results = current
        else:
            results = evaluate_data(taxonomy, data, day, with_evidence=False)
        states[day] = OrderedDict((tag_id, r.state is True) for tag_id, r in results.items())
    return states


def history_events(states):
    """[(checkpoint, tag_id, 'entered' | 'exited', at_window_start)] in date then tag order."""
    events = []
    previous = None
    for day, held in states.items():
        for tag_id, now in held.items():
            before = previous.get(tag_id, False) if previous is not None else False
            if now and not before:
                events.append((day, tag_id, "entered", previous is None))
            elif before and not now:
                events.append((day, tag_id, "exited", False))
        previous = held
    return events


class Lifecycle(object):
    """Lifecycle facts for one customer's current tags."""

    __slots__ = ("entered_on", "new_this_month", "since_window_start", "ended_this_month", "last_checkpoint",
                 "events")

    def __init__(self, entered_on, new_this_month, since_window_start, ended_this_month, last_checkpoint, events):
        self.entered_on = entered_on
        self.new_this_month = new_this_month
        self.since_window_start = since_window_start
        self.ended_this_month = ended_this_month
        self.last_checkpoint = last_checkpoint
        self.events = events


def lifecycle(states, current):
    """Compute entered_on etc. from checkpoint states and the as-of results.

    Returns Lifecycle with dicts keyed by tag id."""
    days = list(states)
    last = days[-1] if days else None
    entered_on, new_this_month, since_start, ended = {}, {}, {}, []
    for tag_id, result in current.items():
        held_now = result.state is True
        held_last = bool(last is not None and states[last].get(tag_id))
        if held_now:
            if held_last:
                start = len(days) - 1
                while start > 0 and states[days[start - 1]].get(tag_id):
                    start -= 1
                entered_on[tag_id] = days[start]
                new_this_month[tag_id] = False
                since_start[tag_id] = start == 0
            else:
                entered_on[tag_id] = None
                new_this_month[tag_id] = True
                since_start[tag_id] = False
        elif held_last:
            ended.append(tag_id)
    return Lifecycle(entered_on, new_this_month, since_start, ended, last, history_events(states))

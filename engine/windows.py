"""Time windows, always relative to the as-of date (never the wall clock).

{"days": N, "offset_days": K}
    the N days ending K days before as_of, both ends inclusive.
    {"days": 90} is as_of-89 .. as_of.

{"months": N, "offset_months": K}
    N complete calendar months, ending K months before the last complete
    month. The as-of month counts as complete only when as_of is its last
    day, so a run on 2026-09-30 includes September and a run on 2026-10-17
    ends with September.
"""

import calendar
import datetime
from decimal import Decimal


class Window(object):
    __slots__ = ("start", "end", "months", "length_in_months", "unit", "size", "offset")

    def __init__(self, start, end, months, length_in_months, unit, size, offset):
        self.start = start
        self.end = end
        self.months = months
        self.length_in_months = length_in_months
        self.unit = unit
        self.size = size
        self.offset = offset

    def contains(self, day):
        return self.start <= day <= self.end

    def label(self):
        return "{} to {}".format(self.start.isoformat(), self.end.isoformat())


def last_complete_month(as_of):
    if (as_of + datetime.timedelta(days=1)).day == 1:
        return as_of.year, as_of.month
    if as_of.month == 1:
        return as_of.year - 1, 12
    return as_of.year, as_of.month - 1


def shift_month(year_month, delta):
    year, month = year_month
    index = year * 12 + (month - 1) + delta
    return index // 12, index % 12 + 1


def month_bounds(year_month):
    year, month = year_month
    last = calendar.monthrange(year, month)[1]
    return datetime.date(year, month, 1), datetime.date(year, month, last)


def resolve(window, as_of):
    if "days" in window:
        days = int(window["days"])
        offset = int(window.get("offset_days", 0))
        end = as_of - datetime.timedelta(days=offset)
        start = end - datetime.timedelta(days=days - 1)
        return Window(start, end, None, Decimal(days) / Decimal(30), "days", days, offset)
    months = int(window["months"])
    offset = int(window.get("offset_months", 0))
    last = shift_month(last_complete_month(as_of), -offset)
    month_list = [shift_month(last, -i) for i in range(months - 1, -1, -1)]
    start = month_bounds(month_list[0])[0]
    end = month_bounds(month_list[-1])[1]
    return Window(start, end, month_list, Decimal(months), "months", months, offset)


def describe(window):
    """Plain words for a window spec, used in rule text."""
    if "days" in window:
        days = int(window["days"])
        offset = int(window.get("offset_days", 0))
        if offset:
            return "the {} days before the last {} days".format(days, offset)
        return "the last {} days".format(days)
    months = int(window["months"])
    offset = int(window.get("offset_months", 0))
    unit = "month" if months == 1 else "months"
    if offset:
        return "the {} complete {} before the last {}".format(months, unit, offset)
    return "the last {} complete {}".format(months, unit)

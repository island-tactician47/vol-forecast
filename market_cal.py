"""市場カレンダー（祝日）。外部ライブラリなしで、日本の祝日・取引所休場と、NYSEの休場日を計算する。

予報日付を「次の営業日」にするために使う（forecast.py）。
- "JP"   : 東証。国民の祝日（振替休日・国民の休日を含む）＋ 12/31, 1/2, 1/3 の休場
- "NYSE" : ニューヨーク証券取引所（米国株）。祝日が土曜なら前日、日曜なら翌日が休場（元日が土曜のときは休場なし）
- None   : 土日だけ休み（為替など）
単発の臨時休場（国葬の日など）は含まない。
"""
from datetime import date, timedelta
from functools import lru_cache

import pandas as pd


def _nth_weekday(year, month, weekday, n):
    """month 月の第 n の weekday（月=0）。n=-1 なら最終。"""
    if n > 0:
        d = date(year, month, 1)
        d += timedelta(days=(weekday - d.weekday()) % 7 + 7 * (n - 1))
        return d
    d = date(year + (month == 12), month % 12 + 1, 1) - timedelta(days=1)
    return d - timedelta(days=(d.weekday() - weekday) % 7)


def _easter(year):
    a, b, c = year % 19, year // 100, year % 100
    d, e = b // 4, b % 4
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i, k = c // 4, c % 4
    l = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * l) // 451
    month = (h + l - 7 * m + 114) // 31
    return date(year, month, (h + l - 7 * m + 114) % 31 + 1)


@lru_cache(maxsize=None)
def jp_holidays(year):
    y = year
    spring = int(20.8431 + 0.242194 * (y - 1980) - (y - 1980) // 4)
    autumn = int(23.2488 + 0.242194 * (y - 1980) - (y - 1980) // 4)
    h = {
        date(y, 1, 1), _nth_weekday(y, 1, 0, 2), date(y, 2, 11), date(y, 2, 23), date(y, 3, spring),
        date(y, 4, 29), date(y, 5, 3), date(y, 5, 4), date(y, 5, 5), _nth_weekday(y, 7, 0, 3),
        date(y, 8, 11), _nth_weekday(y, 9, 0, 3), date(y, 9, autumn), _nth_weekday(y, 10, 0, 2),
        date(y, 11, 3), date(y, 11, 23),
    }
    for d in sorted(h):                     # 振替休日：日曜の祝日は、次の祝日でない日が休み
        if d.weekday() == 6:
            n = d + timedelta(days=1)
            while n in h:
                n += timedelta(days=1)
            h.add(n)
    d = date(y, 1, 2)                       # 国民の休日：前日と翌日が祝日の平日（日曜を除く）
    while d.year == y:
        if (d not in h and d.weekday() != 6 and d - timedelta(days=1) in h and d + timedelta(days=1) in h):
            h.add(d)
        d += timedelta(days=1)
    return h


@lru_cache(maxsize=None)
def nyse_holidays(year):
    y = year
    fixed = [date(y, 7, 4), date(y, 12, 25)]
    if y >= 2022:
        fixed.append(date(y, 6, 19))
    h = set()
    for d in fixed:                          # 土曜→前日、日曜→翌日に振り替え
        h.add(d - timedelta(days=1) if d.weekday() == 5 else d + timedelta(days=1) if d.weekday() == 6 else d)
    ny = date(y, 1, 1)                       # 元日：日曜は翌月曜。土曜は前年末に振り替えない
    if ny.weekday() == 6:
        ny += timedelta(days=1)
    if ny.weekday() != 5:
        h.add(ny)
    h |= {_nth_weekday(y, 1, 0, 3), _nth_weekday(y, 2, 0, 3), _easter(y) - timedelta(days=2),
          _nth_weekday(y, 5, 0, -1), _nth_weekday(y, 9, 0, 1), _nth_weekday(y, 11, 3, 4)}
    return h


def is_open(cal, d):
    d = pd.Timestamp(d).date()
    if d.weekday() >= 5:
        return False
    if cal == "JP":
        return d not in jp_holidays(d.year) and (d.month, d.day) not in ((12, 31), (1, 2), (1, 3))
    if cal == "NYSE":
        return d not in nyse_holidays(d.year)
    return True


def next_days(after, n, cal=None):
    """after（この日は含まない）より後の営業日を n 個、Timestamp のリストで返す。"""
    out, d = [], pd.Timestamp(after).normalize()
    while len(out) < n:
        d += pd.Timedelta(days=1)
        if is_open(cal, d):
            out.append(d)
    return out


def last_open_on_or_before(cal, d):
    d = pd.Timestamp(d).normalize()
    while not is_open(cal, d):
        d -= pd.Timedelta(days=1)
    return d

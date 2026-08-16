"""Small shared helpers. Timestamps are stored as int seconds everywhere;
display uses mm:ss via fmt_ts()."""


def fmt_ts(seconds: int) -> str:
    """1122 -> '18:42'. Handles hours if needed: 3723 -> '1:02:03'."""
    seconds = int(seconds)
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    if h:
        return f"{h}:{m:02d}:{s:02d}"
    return f"{m}:{s:02d}"


def fmt_range(start_sec: int, end_sec: int) -> str:
    """(1122, 1137) -> '18:42-18:57'."""
    return f"{fmt_ts(start_sec)}-{fmt_ts(end_sec)}"


def parse_ts(text: str) -> int:
    """'18:42' -> 1122. Accepts 'mm:ss' or 'h:mm:ss' or plain seconds."""
    text = text.strip()
    if ":" not in text:
        return int(text)
    parts = [int(p) for p in text.split(":")]
    seconds = 0
    for p in parts:
        seconds = seconds * 60 + p
    return seconds

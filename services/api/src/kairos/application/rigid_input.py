"""Conservative extraction for explicit event phrases; uncertainty remains a draft field."""

import re
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from kairos.domain.drafts import Candidate
from kairos.domain.time_rules import overlaps


_NUMBERS = {"一": 1, "二": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7,
            "八": 8, "九": 9, "十": 10, "两": 2, "半": 0.5}


def _hour(value: str) -> int:
    if value.isdigit():
        return int(value)
    if value in _NUMBERS:
        return int(_NUMBERS[value])
    if value.startswith("十") and len(value) == 2:
        return 10 + int(_NUMBERS[value[1]])
    if value.endswith("十") and len(value) == 2:
        return int(_NUMBERS[value[0]]) * 10
    raise ValueError("unclear clock hour")


def parse_event_candidate(text: str, timezone: str, now: datetime) -> Candidate:
    source = text.strip()
    if not source or len(source) > 1000:
        raise ValueError("event description must be 1–1000 characters")
    if re.search(r"找个时间|有空.*(?:学习|做|完成)|随便找个时间", source):
        raise ValueError("an unscheduled activity cannot become a fixed event without an explicit time")
    zone = ZoneInfo(timezone)
    local_now = now.astimezone(zone)
    date_text = re.search(r"(?P<date>\d{4}-\d{2}-\d{2})\s+(?P<start>\d{1,2}:\d{2})\s*[-–到]\s*(?P<end>\d{1,2}:\d{2})\s+(?P<title>.+)", source)
    start = end = None
    location = None
    title = source
    if date_text:
        day = date_text.group("date")
        start = datetime.fromisoformat(f"{day}T{date_text.group('start')}").replace(tzinfo=zone)
        end = datetime.fromisoformat(f"{day}T{date_text.group('end')}").replace(tzinfo=zone)
        title = date_text.group("title").strip()
    else:
        relative_start = re.search(r"([一二三四五六七八九十两\d]{1,3})\s*分钟后", source)
        duration_minutes = re.search(r"(?:持续|时长(?:为)?|用时)\s*([一二三四五六七八九十两\d]{1,3})\s*分钟", source)
        duration_hours = re.search(r"([一二三四五六七八九十两\d]{1,3})(?:个)?小时", source)
        tomorrow = re.search(r"明天(?:(上午|下午|晚上))?([一二三四五六七八九十两\d]{1,3})点(半)?", source)
        if relative_start:
            start = local_now + timedelta(minutes=_hour(relative_start.group(1)))
            duration = (_hour(duration_minutes.group(1)) if duration_minutes else
                        _hour(duration_hours.group(1)) * 60 if duration_hours else None)
            if duration is not None:
                end = start + timedelta(minutes=duration)
            title_match = re.search(
                r"(?:有个|有一个|有一场|开个|开一个|开一场|参加|去)([^，。]*?)"
                r"(?=持续|时长|用时|，|。|$)", source)
            extracted_title = title_match.group(1).strip() if title_match else ""
            if extracted_title:
                title = extracted_title
                if title == "会":
                    title = "会议"
            elif re.search(r"开会|会议", source):
                title = "会议"
            elif "上课" in source:
                title = "上课"
            elif "课程" in source:
                title = "课程"
            location_match = re.search(
                r"(?:地点\s*[:：]?\s*|在\s*)"
                r"([\u3400-\u9fffA-Za-z0-9#-]*?(?:阶|号楼?|室|厅|馆|校区|教室|会议室)"
                r"[\u3400-\u9fffA-Za-z0-9#-]*)", source)
            if location_match:
                location = location_match.group(1).strip()
        elif tomorrow:
            hour = _hour(tomorrow.group(2))
            period = tomorrow.group(1)
            if period == "下午" or period == "晚上":
                if hour < 12:
                    hour += 12
            elif period == "上午" and hour == 12:
                hour = 0
            elif period is None and hour <= 12:
                # "明天两点" does not identify morning versus afternoon.
                hour = -1
            if 0 <= hour < 24:
                day = local_now.date() + timedelta(days=1)
                start = datetime(day.year, day.month, day.day, hour,
                                 30 if tomorrow.group(3) else 0, tzinfo=zone)
                duration = (_hour(duration_minutes.group(1)) if duration_minutes else
                            _hour(duration_hours.group(1)) * 60 if duration_hours else None)
                if duration is not None:
                    end = start + timedelta(minutes=duration)
            suffix = source[tomorrow.end():]
            title_match = re.search(r"(?:开|上|参加|去)([^，。]+?)(?:，|。|\d|[一二三四五六七八九十两]+(?:个)?小时|$)", suffix)
            if title_match:
                title = title_match.group(1).strip()
        elif "上课" in source:
            title = "上课"
    if start is not None and end is not None:
        overlaps(start, end, start, end)
    return Candidate("candidate-1", title or None, location, start, end, timezone)

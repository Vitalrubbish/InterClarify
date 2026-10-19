"""Normalize supported user-side numeric expressions into traceable English words."""

from __future__ import annotations

from datetime import date
import re

VERSION = 'english_numeric_v1'
ONES = 'zero one two three four five six seven eight nine ten eleven twelve thirteen fourteen fifteen sixteen seventeen eighteen nineteen'.split()
TENS = ['', '', 'twenty', 'thirty', 'forty', 'fifty', 'sixty', 'seventy', 'eighty', 'ninety']
MONTHS = 'January February March April May June July August September October November December'.split()
MONTH_PATTERN = '(?:' + '|'.join(MONTHS) + ')'


def cardinal(number):
    """Read an integer without injecting punctuation into a user micro-turn."""
    if number < 0:
        return 'minus ' + cardinal(-number)
    if number < 20:
        return ONES[number]
    if number < 100:
        return TENS[number // 10] + (' ' + ONES[number % 10] if number % 10 else '')
    for size, unit in ((10**12, 'trillion'), (10**9, 'billion'), (10**6, 'million'),
                       (1000, 'thousand'), (100, 'hundred')):
        if number >= size:
            return cardinal(number // size) + ' ' + unit + (' ' + cardinal(number % size) if number % size else '')
    raise ValueError('Unsupported integer')


def ordinal(number):
    words = cardinal(number).split()
    irregular = {'zero': 'zeroth', 'one': 'first', 'two': 'second', 'three': 'third',
                 'five': 'fifth', 'eight': 'eighth', 'nine': 'ninth', 'twelve': 'twelfth'}
    last = words[-1]
    words[-1] = irregular.get(last, last[:-1] + 'ieth' if last.endswith('y') else last + 'th')
    return ' '.join(words)


def year_words(number):
    if 2000 <= number <= 2009:
        return cardinal(number)
    if 1100 <= number <= 1999 or 2010 <= number <= 2099:
        high, low = divmod(number, 100)
        return cardinal(high) + (' hundred' if low == 0 else ' oh ' + cardinal(low) if low < 10 else ' ' + cardinal(low))
    return cardinal(number)


def digits(text):
    return ' '.join(ONES[int(char)] for char in text if char.isdigit())


def calendar_words(year, month, day):
    value = date(int(year), int(month), int(day))
    return f'{MONTHS[value.month - 1]} {ordinal(value.day)} {year_words(value.year)}'


NUMBER = r'(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?'
PATTERN = re.compile(
    r'(?P<iso>\b\d{4}[-/]\d{1,2}[-/]\d{1,2}\b)'
    r'|(?P<slash>\b\d{1,2}/\d{1,2}/\d{4}\b)'
    r'|(?P<month>\b' + MONTH_PATTERN + r'\s+\d{1,2}(?:st|nd|rd|th)?(?:,?\s+\d{4})?\b)'
    r'|(?P<daymonth>\b\d{1,2}(?:st|nd|rd|th)?\s+' + MONTH_PATTERN + r'(?:,?\s+\d{4})?\b)'
    r'|(?P<time>\b\d{1,2}:\d{2}(?::\d{2})?(?:\s*[AaPp]\.?[Mm])?)'
    r'|(?P<phone>(?<!\w)(?:\+\d{1,3}[ -])?(?:\(\d{3}\)[ -]?|\d{3}[ -])\d{3}[ -]\d{4}(?!\d))'
    r'|(?P<money>[$£€]' + NUMBER + r')'
    r'|(?P<percent>' + NUMBER + r'\s*%)'
    r'|(?P<range>\b' + NUMBER + r'\s*[–-]\s*' + NUMBER + r'\b)'
    r'|(?P<ordinal>\b\d+(?:st|nd|rd|th)\b)'
    r'|(?P<number>(?<!\w)-?' + NUMBER + r'(?!\w))', re.I)


def render_number(raw, before):
    raw = raw.replace(',', '')
    if raw.startswith('-'):
        return 'minus ' + render_number(raw[1:], before)
    if '.' in raw:
        whole, fraction = raw.split('.')
        return cardinal(int(whole)) + ' point ' + digits(fraction)
    if len(raw) > 1 and raw.startswith('0') or len(raw) >= 7:
        return digits(raw)
    if len(raw) == 4 and re.search(r'\b(?:in|since|during|year|born|from|until|by|before|after)\s*$', before, re.I):
        return year_words(int(raw))
    if re.search(r'\b(?:phone|telephone|mobile|zip|postal|pin|code|identifier|id|number)\s*(?:is|:|#)?\s*$', before, re.I):
        return digits(raw)
    return cardinal(int(raw))


def render(match, text):
    kind, raw = match.lastgroup, match.group()
    if kind == 'iso':
        return kind, calendar_words(*re.split('[-/]', raw))
    if kind == 'slash':
        first, second, year = map(int, raw.split('/'))
        if first <= 12 and second <= 12 and first != second:
            raise ValueError('Ambiguous numeric date')
        month, day = (second, first) if first > 12 else (first, second)
        return kind, calendar_words(year, month, day)
    if kind in ('month', 'daymonth'):
        name = re.search(MONTH_PATTERN, raw, re.I).group()
        values = [int(x) for x in re.findall(r'\d+', raw)]
        day = values[0]
        month = next(i + 1 for i, name_ in enumerate(MONTHS) if name_.lower() == name.lower())
        date(values[1] if len(values) > 1 else 2000, month, day)
        spoken_day = ordinal(day)
        spoken_year = ' ' + year_words(values[1]) if len(values) > 1 else ''
        return kind, (name + ' ' + spoken_day if kind == 'month' else spoken_day + ' ' + name) + spoken_year
    if kind == 'time':
        clock = re.match(r'(\d+):(\d+)(?::(\d+))?', raw)
        hour, minute = int(clock[1]), int(clock[2])
        second = int(clock[3]) if clock[3] else None
        suffix = raw[clock.end():].strip()
        if hour > 23 or minute > 59 or second is not None and second > 59 or suffix and not 1 <= hour <= 12:
            raise ValueError('Invalid clock time')
        spoken = cardinal(hour)
        spoken += " o'clock" if minute == 0 else ' oh ' + cardinal(minute) if minute < 10 else ' ' + cardinal(minute)
        if second is not None:
            spoken += ' and ' + cardinal(second) + (' second' if second == 1 else ' seconds')
        if suffix:
            spoken += ' ' + suffix.replace('.', '').upper()
        return kind, spoken
    if kind == 'phone':
        return kind, ('plus ' if raw.startswith('+') else '') + digits(raw)
    if kind == 'money':
        units = {'$': ('dollar', 'cent'), '£': ('pound', 'penny'), '€': ('euro', 'cent')}
        major, minor = units[raw[0]]
        amount = raw[1:].replace(',', '')
        whole, _, fraction = amount.partition('.')
        if len(fraction) > 2:
            raise ValueError('Unsupported currency precision')
        number, cents = int(whole), int(fraction.ljust(2, '0') or '0')
        spoken = cardinal(number) + ' ' + major + ('' if number == 1 else 's')
        if cents:
            spoken += ' and ' + cardinal(cents) + ' ' + (minor if cents == 1 else 'pence' if minor == 'penny' else minor + 's')
        return kind, spoken
    if kind == 'percent':
        return kind, render_number(raw.rstrip('%').strip(), '') + ' percent'
    if kind == 'range':
        before = text[max(0, match.start() - 60):match.start()]
        after = text[match.end():match.end() + 40]
        if not (re.search(r'\b(?:pages?|chapters?|ages?|range|from|between)\s*$', before, re.I)
                or re.match(r'\s*(?:years?|days?|hours?|minutes?|seconds?|tokens?|people|percent)\b', after, re.I)):
            raise ValueError('Ambiguous numeric range or subtraction')
        left, right = re.split(r'\s*[–-]\s*', raw)
        return kind, render_number(left, before) + ' to ' + render_number(right, '')
    if kind == 'ordinal':
        return kind, ordinal(int(re.match(r'\d+', raw).group()))
    return kind, render_number(raw, text[max(0, match.start() - 60):match.start()])


def normalize_user_text(text):
    """Return a versioned text replacement map or reject unsupported ambiguity."""
    if not re.search(r'\d', text):
        return {'raw_text': text, 'text': text, 'version': VERSION, 'replacements': []}
    numeric_context = re.sub(r'\b\d{4}[-/]\d{1,2}[-/]\d{1,2}\b|\b\d{1,2}/\d{1,2}/\d{4}\b', '', text)
    if re.search(r'\d\s*/\s*\d|\d\s*[+*=^<>]\s*\d|[¥₹]\s*\d', numeric_context):
        raise ValueError('Unsupported numeric expression')
    if re.search(r'```|https?://\S*\d|\b\d+(?:\.\d+){2,}\b|\b\d+(?:\.\d+)?[eE][+-]?\d+\b|\b[A-Za-z_]\w*\d\w*|\b\d+[A-Za-z_]\w*', text):
        # Ordinal suffixes are supported separately; reject other attached identifiers.
        cleaned = re.sub(r'\b\d+(?:st|nd|rd|th)\b', '', text, flags=re.I)
        cleaned = re.sub(r'\b\d{1,2}:\d{2}(?::\d{2})?(?:\s*[AaPp]\.?[Mm])?', '', cleaned)
        if re.search(r'```|https?://\S*\d|\b\d+(?:\.\d+){2,}\b|\b\d+(?:\.\d+)?[eE][+-]?\d+\b|\b[A-Za-z_]\w*\d\w*|\b\d+[A-Za-z_]\w*', cleaned):
            raise ValueError('Unsupported numeric context')
    pieces, replacements, cursor, length = [], [], 0, 0
    for match in PATTERN.finditer(text):
        unchanged = text[cursor:match.start()]
        pieces.append(unchanged)
        length += len(unchanged)
        kind, spoken = render(match, text)
        replacements.append({'start': match.start(), 'end': match.end(), 'raw': match.group(),
                             'text': spoken, 'kind': kind, 'normalized_start': length,
                             'normalized_end': length + len(spoken)})
        pieces.append(spoken)
        length += len(spoken)
        cursor = match.end()
    pieces.append(text[cursor:])
    result = {'raw_text': text, 'text': ''.join(pieces), 'version': VERSION, 'replacements': replacements}
    validate_surface(result)
    return result


def validate_surface(surface):
    """Check every source span and normalized span without trusting the renderer."""
    source, normalized = surface['raw_text'], surface['text']
    previous, pieces = 0, []
    for row in surface['replacements']:
        if not previous <= row['start'] < row['end'] <= len(source):
            raise ValueError('Invalid numeric source span')
        if source[row['start']:row['end']] != row['raw']:
            raise ValueError('Numeric source text mismatch')
        pieces.append(source[previous:row['start']])
        if sum(map(len, pieces)) != row['normalized_start']:
            raise ValueError('Invalid normalized offset')
        pieces.append(row['text'])
        if sum(map(len, pieces)) != row['normalized_end']:
            raise ValueError('Invalid normalized end')
        previous = row['end']
    pieces.append(source[previous:])
    if ''.join(pieces) != normalized or re.search(r'\d', normalized):
        raise ValueError('Incomplete numeric normalization')

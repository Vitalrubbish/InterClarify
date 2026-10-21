"""Expose punctuation only when subsequent lexical input has arrived."""

from collections import Counter

VERSION = 'delayed_punctuation_v1'
MARKS = set('.,!?;:…，。！？；：、')


def spans(characters):
    """Compress ordered source characters into contiguous provenance ranges."""
    result = []
    for event_id, offset, char in characters:
        if event_id is None:
            result.append({'source_event_id': None, 'text': char, 'reason': 'utterance_separator'})
        elif result and result[-1]['source_event_id'] == event_id and result[-1]['end'] == offset:
            result[-1]['end'] += 1
        else:
            result.append({'source_event_id': event_id, 'start': offset, 'end': offset + 1})
    return result


def apply_asr_surface(plan):
    """Annotate an immutable event schedule with causal visible user deltas."""
    pending, previous_scope = [], None
    for event in plan['events']:
        text, visible = event['user_text'], []
        if text:
            scope = ('turn', event['user_origin']['turn']) if event['user_origin'] else ('backchannel', event['event_id'])
            if pending and scope != previous_scope and not pending[-1][2].isspace() and not text[0].isspace():
                pending.append((None, None, ' '))
            for offset, char in enumerate(text):
                source = (event['event_id'], offset, char)
                if pending and char.isalnum():
                    visible.extend(pending)
                    pending = []
                if char in MARKS or pending:
                    pending.append(source)
                else:
                    visible.append(source)
            previous_scope = scope
        event['user_asr'] = ''.join(x[2] for x in visible)
        event['asr_spans'] = spans(visible)
    plan['asr_surface'] = VERSION
    plan['asr_pending'] = {'text': ''.join(x[2] for x in pending), 'spans': spans(pending)}
    return plan


def audit_asr_surface(plan):
    """Independently check source conservation, release timing and visible text."""
    events = plan['events']
    assert plan['asr_surface'] == VERSION
    source = [(e['event_id'], i, c) for e in events for i, c in enumerate(e['user_text'])]
    next_lexical, following = {}, None
    for event_id, offset, char in reversed(source):
        next_lexical[(event_id, offset)] = following
        if char.isalnum():
            following = event_id
    consumed, counts = [], Counter()

    def expand(records, delivered_at):
        characters = []
        for row in records:
            origin = row['source_event_id']
            if origin is None:
                assert row == {'source_event_id': None, 'text': ' ', 'reason': 'utterance_separator'}
                characters.append(' ')
                counts['synthetic_separators'] += 1
                continue
            assert 0 <= origin < len(events) and origin <= delivered_at
            text = events[origin]['user_text']
            assert 0 <= row['start'] < row['end'] <= len(text)
            for offset in range(row['start'], row['end']):
                char = text[offset]
                if delivered_at < len(events) and char in MARKS:
                    lexical = next_lexical[(origin, offset)]
                    assert lexical is not None and lexical <= delivered_at, 'Punctuation exposed before subsequent text'
                    counts['punctuation_delivered'] += 1
                    counts['punctuation_delayed_across_events'] += int(origin < delivered_at)
                characters.append(char)
                consumed.append((origin, offset, char))
        return ''.join(characters)

    for event in events:
        assert expand(event['asr_spans'], event['event_id']) == event['user_asr']
        if event.get('user_origin') and not event['user_asr'].strip():
            assert not any(c.isalnum() for c in event['user_text']), 'Lexical source unexpectedly invisible'
            counts['sourced_no_voice_events'] += 1
        if not event['user_text']:
            assert not event['user_asr'] and not event['asr_spans'], 'No-voice flushed pending punctuation'
        if event['user_asr']:
            counts['visible_events'] += 1
            assert not event['user_asr'].rstrip().endswith(tuple(MARKS)), 'Visible delta ends in unreleased punctuation'
    pending = plan['asr_pending']
    assert expand(pending['spans'], len(events)) == pending['text']
    assert consumed == source, 'ASR source characters reordered, repeated or missing'
    counts['pending_characters'] = len(pending['text'])
    counts['pending_punctuation'] = sum(c in MARKS for c in pending['text'])
    counts['source_characters'] = len(source)
    return counts

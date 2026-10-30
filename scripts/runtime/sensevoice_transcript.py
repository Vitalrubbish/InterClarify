"""Preserve raw SenseVoice labels and assemble conservative editable turn tails."""
from __future__ import annotations

import re


# Frozen from FunASR 1.2.6; runtime checks the installed dictionary before use.
KNOWN_TAGS = frozenset('<|zh|> <|en|> <|yue|> <|ja|> <|ko|> <|nospeech|> '
                       '<|HAPPY|> <|SAD|> <|ANGRY|> <|NEUTRAL|> <|FEARFUL|> '
                       '<|DISGUSTED|> <|SURPRISED|> <|BGM|> <|Speech|> '
                       '<|Applause|> <|Laughter|> <|Cry|> <|EMO_UNKNOWN|> '
                       '<|Sneeze|> <|Breath|> <|Cough|> <|Sing|> <|Speech_Noise|> '
                       '<|withitn|> <|woitn|> <|GBG|> <|Event_UNK|>'.split())
WORD = re.compile(r"[A-Za-z0-9]+(?:['’.-][A-Za-z0-9]+)*|[\u4e00-\u9fff]")


class SenseVoiceObservation:
    """Split known labels without rewriting ordinary source characters."""

    @staticmethod
    def parse(raw_text):
        if not isinstance(raw_text, str):
            raise ValueError('ASR text must be a string')
        tags, mapping, parts = [], [], []
        begin, text_offset = 0, 0
        for match in re.finditer(r'<\|[^<>]*\|>', raw_text):
            if match.group() not in KNOWN_TAGS:
                tags.append({'token': match.group(), 'start': match.start(),
                             'end': match.end(), 'known': False})
                continue
            segment = raw_text[begin:match.start()]
            parts.append(segment)
            if segment:
                mapping.append({'text_start': text_offset, 'text_end': text_offset + len(segment),
                                'raw_start': begin, 'raw_end': match.start()})
                text_offset += len(segment)
            tags.append({'token': match.group(), 'start': match.start(),
                         'end': match.end(), 'known': True})
            begin = match.end()
        segment = raw_text[begin:]
        parts.append(segment)
        if segment:
            mapping.append({'text_start': text_offset, 'text_end': text_offset + len(segment),
                            'raw_start': begin, 'raw_end': len(raw_text)})
        return {'raw_text': raw_text, 'text': ''.join(parts),
                'tags': sorted(tags, key=lambda t: t['start']), 'character_map': mapping}


class TurnTranscriptAssembler:
    """Keep a full hypothesis; publish explicit gaps instead of guessed joins."""

    def __init__(self, turn_start=0, max_chars=65536):
        self.turn_start, self.max_chars = turn_start, max_chars
        self.text = ''
        self.tail_start, self.last_start, self.last_end = 0, None, turn_start
        self.assembly_status, self.coverage_complete = 'empty', False

    def apply_window(self, observation):
        old = self.text
        status = observation['call_status']
        spans = observation['audio_spans']
        real = [s for s in spans if s['kind'] == 'real']
        text = observation['text']
        reason = None
        separator = None
        if status == 'error':
            reason = 'asr_error'
        elif not real:
            return {'changed': False, 'diagnostic_only': True, 'reason': 'synthetic_only'}
        elif not text:
            return {'changed': False, 'reason': 'ok_empty'}
        elif any(not tag['known'] for tag in observation['tags']):
            reason = 'unknown_tag'
        else:
            start, end = real[0]['start'], real[-1]['end']
            contiguous = all(a['end'] == b['start'] for a, b in zip(real, real[1:]))
            if not contiguous or start < self.turn_start or end < self.last_end:
                reason = 'noncontiguous_or_regressed_audio'
            elif start == self.turn_start:
                self.text = text
                self.tail_start = 0
            elif self.last_start is not None and start == self.last_start:
                self.text = self.text[:self.tail_start] + text
            elif (self.text and self.coverage_complete and start == self.last_end
                  and re.search(r'[\s.!?,;:。！？；：]$', self.text)):
                separator = '' if self.text[-1].isspace() or text[0].isspace() else ' '
                self.tail_start = len(self.text) + len(separator)
                self.text += separator + text
            elif self.text and start < self.last_end:
                new_words = list(WORD.finditer(text))
                old_words = list(WORD.finditer(self.text[self.tail_start:]))
                keys = [m.group().casefold() for m in new_words[:2]]
                candidates = []
                if len(keys) == 2:
                    for index in range(len(old_words) - 1):
                        if [m.group().casefold() for m in old_words[index:index + 2]] == keys:
                            candidates.append(self.tail_start + old_words[index].start())
                if len(candidates) == 1 and (not new_words[0].start() or text[:new_words[0].start()].isspace()):
                    self.tail_start = candidates[0]
                    self.text = self.text[:self.tail_start] + text
                else:
                    reason = 'ambiguous_or_missing_window_anchor'
            else:
                reason = 'unresolved_window_history'
            if reason is None:
                self.last_start, self.last_end = start, end
        if len(self.text) > self.max_chars:
            self.text = old
            raise RuntimeError('Turn transcript character limit exceeded')
        previous_status = self.assembly_status, self.coverage_complete
        if reason:
            self.assembly_status, self.coverage_complete = 'gap', False
        else:
            self.assembly_status, self.coverage_complete = 'assembled', True
        changed = old != self.text
        return {'changed': changed or previous_status != (self.assembly_status, self.coverage_complete),
                'text_changed': changed, 'text': self.text,
                'assembly_status': self.assembly_status, 'coverage_complete': self.coverage_complete,
                'assembly_reason': reason, 'tail_start': self.tail_start, 'join_separator': separator}

    def apply_turn_result(self, observation):
        return self.apply_window(observation)

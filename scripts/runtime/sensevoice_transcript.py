"""Build streaming drafts from native deltas and refine completed segments."""
from __future__ import annotations

import re


# Frozen from FunASR 1.2.6; runtime checks the installed dictionary before use.
KNOWN_TAGS = frozenset('<|zh|> <|en|> <|yue|> <|ja|> <|ko|> <|nospeech|> '
                       '<|HAPPY|> <|SAD|> <|ANGRY|> <|NEUTRAL|> <|FEARFUL|> '
                       '<|DISGUSTED|> <|SURPRISED|> <|BGM|> <|Speech|> '
                       '<|Applause|> <|Laughter|> <|Cry|> <|EMO_UNKNOWN|> '
                       '<|Sneeze|> <|Breath|> <|Cough|> <|Sing|> <|Speech_Noise|> '
                       '<|withitn|> <|woitn|> <|GBG|> <|Event_UNK|>'.split())


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
    """Keep one draft per controller generation and preserve preceding text."""

    def __init__(self, turn_start=0, max_chars=65536):
        self.turn_start, self.max_chars = turn_start, max_chars
        self.text = ''
        self.generation, self.generation_start = 0, turn_start
        self._prefix, self._active = '', ''
        self._prefix_gap = self._active_gap = self._refined = False
        self.assembly_status, self.coverage_complete = 'empty', False

    @staticmethod
    def _join(parts):
        text = ''
        for part in parts:
            if not part:
                continue
            if (text and not text[-1].isspace() and not part[0].isspace()
                    and text[-1].isascii() and part[0].isascii()):
                text += ' '
            text += part
        return text

    def _set_active(self, text, stage, *, reason=None, clear_gap=False):
        combined = self._join((self._prefix, text))
        if len(combined) > self.max_chars:
            raise RuntimeError('Turn transcript character limit exceeded')
        previous = self.text, self.assembly_status, self.coverage_complete
        self._active, self.text = text, combined
        self._active_gap = bool(reason) or (self._active_gap and not clear_gap)
        gap = self._prefix_gap or self._active_gap
        self.assembly_status = 'gap' if gap else 'assembled' if combined else 'empty'
        self.coverage_complete = bool(combined) and not gap
        return {'changed': previous != (self.text, self.assembly_status, self.coverage_complete),
                'text_changed': previous[0] != self.text, 'text': self.text,
                'assembly_status': self.assembly_status, 'coverage_complete': self.coverage_complete,
                'assembly_reason': reason, 'stage': stage,
                'controller_generation': self.generation}

    def begin_generation(self, generation, start):
        """Seal the preceding current segment without creating a new user turn."""
        if generation <= self.generation or start < self.generation_start:
            raise ValueError('Controller generation or audio boundary moved backwards')
        self._prefix, self._active = self.text, ''
        self._prefix_gap = self._prefix_gap or self._active_gap
        self._active_gap = self._refined = False
        self.generation, self.generation_start = generation, start

    def apply_deltas(self, history, generation):
        """Rebuild the current draft, including replacements of previous deltas."""
        if generation != self.generation:
            raise ValueError('Delta history belongs to a different controller generation')
        if not isinstance(history, (list, tuple)) or any(not isinstance(s, str) for s in history):
            raise ValueError('Native delta history must contain text strings')
        if self._refined:
            return {'changed': False, 'reason': 'segment_already_refined'}
        return self._set_active(self._join(history), 'delta')

    def note_failure(self, reason):
        return self._set_active(self._active, 'source', reason=reason)

    def apply_turn_result(self, observation, generation):
        """Replace this generation's draft with a valid native whole-segment result."""
        if generation != self.generation:
            raise ValueError('Whole-segment result belongs to a different controller generation')
        if observation['call_status'] == 'error':
            return self.note_failure('asr_error')
        real = [s for s in observation['audio_spans'] if s['kind'] == 'real']
        if not real:
            return {'changed': False, 'diagnostic_only': True, 'reason': 'synthetic_only'}
        if not observation['text']:
            return {'changed': False, 'reason': 'ok_empty'}
        if any(not tag['known'] for tag in observation['tags']):
            return self.note_failure('unknown_tag')
        if (real[0]['start'] < self.generation_start
                or any(a['end'] != b['start'] for a, b in zip(real, real[1:]))):
            return self.note_failure('noncontiguous_or_cross_generation_audio')
        update = self._set_active(observation['text'], 'turn', clear_gap=True)
        self._refined = True
        return update

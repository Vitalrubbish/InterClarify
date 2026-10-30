"""Adapt one native append-only ASR source to SoulX audio/text state prediction."""
from __future__ import annotations

from collections import deque
from copy import deepcopy
import re
import threading
import time

try:
    from .soulx_frontend import SoulXFrontend
except ImportError:
    from soulx_frontend import SoulXFrontend


NEMOTRON_REVISION = 'ebe59e5a817142986528bbbee5dba8db7b38ed50'


def token_patch(old, new):
    """Return the common token prefix, including word-internal retokenization."""
    index = 0
    while index < min(len(old), len(new)) and old[index] == new[index]:
        index += 1
    return index


class NemotronSoulXFrontend(SoulXFrontend):
    """Publish ASR independently, select causal prefixes, and replay revised tokens."""

    transcript_source = 'nemotron'

    def __init__(self, *args, **kwargs):
        self.publication_lock = threading.RLock()
        self.prefixes = deque(maxlen=4096)
        self.native_generation, self.native_seq, self.native_text = None, 0, ''
        self.text_base, self.consumed_chars = 0, 0
        self.frames, self.control_ids = [], []
        self.selected = None
        self.replay_count = 0
        super().__init__(*args, **kwargs)

    def accept_asr_event(self, native):
        """Commit source text on arrival without taking the model-computation lock."""
        with self.publication_lock:
            if self.native_generation is None:
                self.native_generation = native['generation']
            if native['generation'] != self.native_generation or native['event_seq'] != self.native_seq + 1:
                raise ValueError('ASR source generation changed or event sequence skipped')
            if native['kind'] not in ('transcript', 'decode_step'):
                raise ValueError('Unknown native ASR event')
            if not native['text'].startswith(self.native_text):
                raise ValueError('ASR source rewrote an already delivered prefix')
            observed = native['consumed_samples']
            if observed > native['received_samples'] or observed < 0:
                raise ValueError('Invalid conservative ASR observation watermark')
            text = native['text']
            payload = self._event('asr_observation', source='nemotron', raw_text=text, text=text,
                                  native_event=deepcopy(native), asr_call_id=f'{native["generation"]}:{native["event_seq"]}',
                                  audio_observed_until=observed, delivery_phase='drain' if native.get('eof_received') or self.closed else 'online',
                                  source_revision=NEMOTRON_REVISION, native_returned_at=native['published_at'])
            events = [payload]
            if text != self.native_text and not self.closed and not native.get('eof_received'):
                snapshot = self._event('user_transcript', source='nemotron',
                                       text=text, version=self.snapshot['version'] + 1,
                                       asr_version=self.snapshot['asr_version'] + 1,
                                       base_asr_version=self.snapshot['asr_version'],
                                       replace_from=len(self.native_text), replacement=text[len(self.native_text):],
                                       status='open', assembly_status='native_append', coverage_complete=True,
                                       audio_observed_until=observed,
                                       depends_on=[payload['event_id']], source_prefix_version=native['prefix_version'])
                events.append(snapshot)
            self._commit(events)
            if len(events) > 1:
                self.snapshot = events[-1]
            if not native.get('eof_received') and not self.closed:
                self.prefixes.append({'text': text, 'asr_version': self.snapshot['asr_version'],
                                      'event_id': payload['event_id'], 'source_prefix_version': native['prefix_version'],
                                      'observed_until': observed, 'published_at': native['published_at']})
            self.native_seq, self.native_text = native['event_seq'], text
            return payload

    def _reset_controller(self):
        with self.publication_lock:
            super()._reset_controller()
            self.frames, self.control_ids = [], []
            # Re-prime a partial final word in the new controller cache. The
            # authoritative transcript itself is never duplicated or restarted.
            consumed = self.native_text[:self.consumed_chars]
            match = re.search(r'\S+$', consumed)
            self.text_base = match.start() if match and consumed and not consumed[-1].isspace() else self.consumed_chars
            self.selected = None

    def _asr(self, audio_embeds):
        import torch
        from utils.MyTn.textnorm import zh_norm, zh_remove_punc
        from utils.backchannel_utils import remove_leading_backchannel
        from utils.text_utils import split_cn_en, check_en
        model = self.model
        with torch.no_grad():
            checked = model.model.llm(inputs_embeds=model.past_state['input_embeds'],
                                      past_key_values=model.past_state['past_key_values'], use_cache=True)
            gate = int(torch.argmax(checked.logits[0], -1)[-1].item()) != model.model.asr_eos_token_id
            watermark = max((span['end'] for array in (self.current_chunk, self.current_ahead)
                             for span in self._spans(array) if span['kind'] == 'real'), default=0)
            with self.publication_lock:
                eligible = [p for p in self.prefixes if p['observed_until'] <= watermark]
                candidate = deepcopy(eligible[-1]) if eligible else None
            consumed_now = self.consumed_chars
            if gate and candidate and len(candidate['text']) >= self.text_base:
                raw = candidate['text'][self.text_base:]
                tokens = split_cn_en(zh_norm(zh_remove_punc(remove_leading_backchannel(raw).strip())))
                normalized = ''.join((part + ' ') if check_en(part) else part for part in tokens).strip()
                ids = model.model.tokenizer.encode(normalized, add_special_tokens=False)
                consumed_now = max(consumed_now, len(candidate['text']))
                self.selected = candidate
            else:
                ids = list(self.control_ids)
                normalized = model.past_state.get('cascade_text', '')
            if len(self.frames) >= 256 or len(ids) > 4096:
                raise RuntimeError('SoulX token replay exceeds the bounded generation budget')
            prefix = token_patch(self.control_ids, ids)
            frame = {'audio': audio_embeds.detach(), 'text_ids': [], 'state_id': None}
            self.frames.append(frame)
            rewritten = prefix < len(self.control_ids)
            if rewritten:
                offset, owner = 0, None
                for index, old in enumerate(self.frames[:-1]):
                    finish = offset + len(old['text_ids'])
                    if prefix < finish:
                        owner = index
                        old['text_ids'] = old['text_ids'][:prefix - offset] + ids[prefix:]
                        break
                    offset = finish
                if owner is None:
                    raise RuntimeError('Token rewrite has no recorded cache owner')
                for old in self.frames[owner + 1:]:
                    old['text_ids'] = []
                pieces = [model.text_embeds]
                for index, old in enumerate(self.frames):
                    pieces.append(old['audio'])
                    if index == len(self.frames) - 1:
                        break
                    if old['text_ids']:
                        pieces.append(model.embed_tokens_func(torch.tensor(old['text_ids'], device=model.device)))
                    pieces.append(model.audio_eos_embeds)
                    pieces.append(model.embed_tokens_func(torch.tensor([old['state_id']], device=model.device)))
                replayed = model.model.llm(inputs_embeds=torch.cat(pieces, dim=0).unsqueeze(0),
                                           past_key_values=None, use_cache=True)
                model.past_state['past_key_values'] = replayed.past_key_values
                self.replay_count += 1
            else:
                frame['text_ids'] = ids[prefix:]
                model.past_state['past_key_values'] = checked.past_key_values
            if [item for saved in self.frames for item in saved['text_ids']] != ids:
                raise AssertionError('Recorded control token history does not reconstruct the selected prefix')
            current_ids = frame['text_ids']
            next_pieces = []
            if current_ids:
                next_pieces.append(model.embed_tokens_func(torch.tensor(current_ids, device=model.device)))
            next_pieces.append(model.audio_eos_embeds)
            model.past_state['input_embeds'] = torch.cat(next_pieces, dim=0).unsqueeze(0)
            model.past_state['cascade_text'] = normalized
            model.past_state['delta_text'].append(model.model.tokenizer.decode(current_ids, skip_special_tokens=False))
            if len(model.cascade_buffer) > 51200:
                model.cascade_buffer = self.slice_audio(model.cascade_buffer, slice(-51200, None))
            self.control_ids, self.consumed_chars = ids, consumed_now
        with self.publication_lock:
            selected = self.selected
            event = self._event('control_observation', control_revision=self.control_revision + 1,
                                control_text=normalized, delta_token_ids=current_ids, gate_open=gate,
                                asr_status='returned' if candidate else 'pending',
                                consumed_asr_version=selected['asr_version'] if selected else 0,
                                consumed_source_prefix_version=selected['source_prefix_version'] if selected else 0,
                                consumed_source_observed_until=selected['observed_until'] if selected else None,
                                audio_observed_until=watermark, text_base=self.text_base,
                                token_replayed=rewritten, replay_count=self.replay_count,
                                asr_call_ids=[selected['event_id']] if selected else [],
                                depends_on=[selected['event_id']] if selected else [])
            self._commit([event])
            self.control_revision += 1
            self.control = event
        # Match native correction behavior: replayed prior text is no new current
        # delta, although its cached semantic input has been corrected.
        return model.past_state['delta_text'][-1]

    def observe_state(self, token, delta_text):
        with self.publication_lock:
            event = super().observe_state(token, delta_text)
            self.frames[-1]['state_id'] = event['token_id'] if event['adjustment'] else event['raw_token_id']
            return event

    def _event(self, kind, source='soulx_frontend', **payload):
        if kind == 'user_state' and self.control:
            payload['basis'].update(consumed_asr_version=self.control['consumed_asr_version'],
                                     consumed_source_observed_until=self.control['consumed_source_observed_until'])
        return super()._event(kind, source=source, **payload)

    def _recognize(self, audio, sample_rate=16000, language=None):
        # Whole-turn official branches read only the already consumed source;
        # they cannot run another recognizer or pull a future prefix.
        return self.selected['text'][self.text_base:] if self.selected else ''

    def close_turn(self, reason='runtime_audio_case_end'):
        with self.publication_lock:
            super().close_turn(reason)

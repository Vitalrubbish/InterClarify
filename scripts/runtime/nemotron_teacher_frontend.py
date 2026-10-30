"""Force native ASR increments into SoulX and publish one joint current value."""
from __future__ import annotations

from copy import deepcopy
import hashlib
import inspect
from pathlib import Path
import time

try:
    from .shared_context import SharedContext, STATE_IDS
    from .soulx_frontend import UPSTREAM_SHA256
except ImportError:
    from shared_context import SharedContext, STATE_IDS
    from soulx_frontend import UPSTREAM_SHA256


TOOL_DIGESTS = {
    'text_utils.py': 'e1a7bb36ebf3a1cc0105d937a8f61be8c950b086f69eab2e92f91f9d16a0e07f',
    'backchannel_utils.py': '0d7f08f6388d13ded194adaab7840cecda9cfa15a1bffaa903fbc3000391c72f',
    'MyTn/textnorm.py': '778a294fb6f3568c7e566b7ee7f93690af0761fb1565998ca20d960d4ee5ecdb',
}


def official_control_text(model, text):
    """Use the frozen upstream functions, without altering source transcription."""
    module = inspect.getmodule(type(model))
    text = module.remove_leading_backchannel(text)
    units = module.split_cn_en(module.zh_norm(module.zh_remove_punc(text.strip())))
    return ''.join(unit + ' ' if module.check_en(unit) else unit for unit in units).strip()


def verify_tools(model):
    root = Path(inspect.getfile(type(model))).parents[1] / 'utils'
    for relative, expected in TOOL_DIGESTS.items():
        if hashlib.sha256((root / relative).read_bytes()).hexdigest() != expected:
            raise ValueError('SoulX normalization source digest differs: ' + relative)


class TeacherCursor:
    """Consume each exact character increment once, including empty steps."""

    def __init__(self):
        self.text, self.seq = '', 0

    def advance(self, step):
        if step['step_seq'] != self.seq + 1 or not step['text'].startswith(self.text):
            raise ValueError('Teacher source rewrote text or skipped a decoder step')
        delta = step['text'][len(self.text):]
        self.text, self.seq = step['text'], step['step_seq']
        return delta


class NemotronTeacherFrontend:
    """Own one bounded audio/text KV and fixed-source logical user turn."""

    def __init__(self, model, session_id, context=None, *, empty_nonidle_rule=True, max_tokens=8192,
                 max_rebuilds=128, max_replay_tokens=65536):
        if hashlib.sha256(Path(inspect.getfile(type(model))).read_bytes()).hexdigest() != UPSTREAM_SHA256:
            raise ValueError('SoulX source digest differs')
        verify_tools(model)
        self.model, self.session_id = model, session_id
        self.context = context if context is not None else SharedContext()
        self.cursor, self.teacher_ids = TeacherCursor(), []
        self.kv, self.pending_state = None, None
        self.previous_state, self.mistakes, self.speech_detected = None, 0, False
        self.tokens, self.max_tokens = 0, max_tokens
        self.generation, self.closed = 0, False
        self.empty_nonidle_rule = empty_nonidle_rule
        self.control_text, self.available_ids = '', []
        self.entries, self.checkpoint = [], None
        self.rebuilds = self.replay_tokens = 0
        self.max_rebuilds, self.max_replay_tokens = max_rebuilds, max_replay_tokens
        tokenizer = model.model.tokenizer
        for token, expected in STATE_IDS.items():
            if tokenizer.encode(token, add_special_tokens=False) != [expected]:
                raise ValueError('SoulX state tokenizer mapping differs')
        if model.audio_eos_token.tolist() != [model.model.asr_eos_token_id]:
            raise ValueError('SoulX ASR EOS mapping differs')
        self.context.open_user_turn(session_id, 'user-1', source='nemotron')

    def reset_controller(self):
        """Preserve semantic KV, source cursor and the one pending valid state."""
        self.generation += 1
        self.mistakes, self.speech_detected = 0, False

    def _embed(self, ids):
        import torch
        return self.model.embed_tokens_func(torch.tensor(ids, dtype=torch.long, device=self.model.device))

    def _forward(self, embeds, kv):
        import torch
        with torch.inference_mode():
            return self.model.model.llm(inputs_embeds=embeds.unsqueeze(0), past_key_values=kv, use_cache=True)

    def _revise(self, desired, common):
        """Replay real input history from an immutable valid checkpoint."""
        import torch
        started = time.monotonic()
        affected = next(i for i, entry in enumerate(self.entries[:-1])
                        if entry['end'] > common)
        position = 0
        revised_end = min(len(self.teacher_ids), len(desired))
        for entry in self.entries[:-1]:
            end = min(entry['end'], revised_end)
            entry['ids'] = desired[position:end]
            entry['begin'], entry['end'] = position, end
            position = end
        self.teacher_ids = desired[:revised_end]
        recent = self.checkpoint is not None and self.checkpoint['index'] == affected
        parts = []
        if recent:
            # Copy again: a DynamicCache may mutate the supplied object in place.
            kv = deepcopy(self.checkpoint['kv'])
            start = affected
        else:
            kv, start = None, 0
            self.checkpoint = None
        for index in range(start, len(self.entries)):
            entry = self.entries[index]
            if not (recent and index == start):
                parts.append(entry['pre'].to(self.model.device))
            if index < len(self.entries) - 1:
                if entry['ids']:
                    parts.append(self._embed(entry['ids']))
                parts.append(self.model.audio_eos_embeds)
        count = sum(part.shape[0] for part in parts)
        self.rebuilds += 1
        self.replay_tokens += count
        if self.rebuilds > self.max_rebuilds or self.replay_tokens > self.max_replay_tokens:
            raise RuntimeError('Teacher cache replay limit exceeded')
        self.tokens = sum(e['pre'].shape[0] + len(e['ids']) + 1 for e in self.entries[:-1]) + self.entries[-1]['pre'].shape[0]
        if self.tokens + 1 > self.max_tokens:
            raise RuntimeError('Teacher controller token limit exceeded')
        self.kv = self._forward(torch.cat(parts, dim=0), kv).past_key_values
        return {'revised_segments': [{'step': i + 1, 'begin': e['begin'], 'end': e['end'], 'ids': e['ids']}
                                     for i, e in enumerate(self.entries[:-1]) if i >= affected],
                'revision_from_token': common, 'revision_from_step': affected + 1,
                'replay_mode': 'recent_checkpoint' if recent else 'bounded_rebuild',
                'replayed_tokens': count, 'replay_seconds': time.monotonic() - started}

    def process_step(self, step, chunk, back, ahead, processed_until, observed_until):
        import torch
        if self.closed:
            raise ValueError('Cannot process a closed turn')
        started = time.monotonic()
        raw_delta = self.cursor.advance(step)
        model, tokenizer = self.model, self.model.model.tokenizer
        self.control_text = official_control_text(model, self.cursor.text)
        desired = tokenizer.encode(self.control_text, add_special_tokens=False) if self.control_text else []
        if any(i in tokenizer.all_special_ids for i in desired):
            raise ValueError('ASR control text contains structural special tokens')
        self.available_ids = desired
        if len(desired) > self.max_tokens:
            raise RuntimeError('Teacher control text token limit exceeded')
        parts = [model.text_embeds] if self.kv is None else []
        feedback = self.pending_state
        if feedback is not None:
            parts.append(self._embed([feedback]))
        audio_ids = model._audio_to_tokens(back, chunk, ahead)
        parts.append(model._tokens_to_embeds(audio_ids))
        pre = torch.cat(parts, dim=0)
        self.tokens += pre.shape[0]
        if self.tokens + 1 > self.max_tokens:
            raise RuntimeError('Teacher controller token limit exceeded')
        gate = self._forward(pre, self.kv)
        self.kv = gate.past_key_values
        gate_id = int(torch.argmax(gate.logits[0, -1]).item())
        opened = gate_id != model.model.asr_eos_token_id
        gate_resolved_at = time.monotonic()
        self.entries.append({'pre': pre.detach().cpu().clone(), 'ids': [],
                             'begin': len(self.teacher_ids), 'end': len(self.teacher_ids)})
        common = 0
        for old, new in zip(self.teacher_ids, desired):
            if old != new:
                break
            common += 1
        revision = {}
        before = len(self.teacher_ids)
        ids = []
        if opened:
            if common < len(self.teacher_ids):
                revision = self._revise(desired, common)
            begin = len(self.teacher_ids)
            ids = desired[begin:]
            if ids:
                self.checkpoint = {'index': len(self.entries) - 1, 'kv': deepcopy(self.kv)}
            self.entries[-1].update(ids=list(ids), begin=begin, end=len(desired))
            self.teacher_ids = list(desired)
        actual_delta = desired[common:] if opened and revision else ids
        delta = tokenizer.decode(actual_delta, skip_special_tokens=False,
                                 clean_up_tokenization_spaces=False) if actual_delta else ''
        self.tokens += len(ids) + 1
        if self.tokens > self.max_tokens:
            raise RuntimeError('Teacher controller token limit exceeded')
        teacher_injected_at = time.monotonic()
        state_parts = ([self._embed(ids)] if ids else []) + [model.audio_eos_embeds]
        outputs = self._forward(torch.cat(state_parts, dim=0), self.kv)
        logits = outputs.logits[0, -1]
        raw_id = int(torch.argmax(logits).item())
        raw = tokenizer.decode([raw_id], skip_special_tokens=False)
        self.kv = outputs.past_key_values
        token, token_id, adjustment = raw, raw_id, None
        self.mistakes = self.mistakes + 1 if raw == '<|user_nonidle|>' and not delta else 0
        transition = self.previous_state == '<|user_nonidle|>' and raw == '<|user_idle|>'
        empty_rule = self.empty_nonidle_rule and self.mistakes >= model.config.infer_config.max_mistake_num
        if transition or empty_rule:
            token = '<|user_complete|>' if logits[STATE_IDS['<|user_complete|>']] > logits[STATE_IDS['<|user_incomplete|>']] else '<|user_incomplete|>'
            token_id = STATE_IDS[token]
            adjustment = 'nonidle_to_idle' if transition else 'empty_nonidle_count'
        valid = token in STATE_IDS and STATE_IDS[token] == token_id
        far_field = valid and token == '<|user_nonidle|>' and not self.speech_detected and model.get_rms(chunk) < model.config.infer_config.far_field_threshold
        reason = 'unknown_state' if not valid else 'far_field' if far_field else None
        self.pending_state = token_id if reason is None else None
        self.previous_state = token if reason is None else None
        self.speech_detected |= reason is None and token == '<|user_nonidle|>'
        resolved = time.monotonic()
        frame = {'session_id': self.session_id, 'turn_id': 'user-1', 'source': 'nemotron',
                 'text': self.cursor.text, 'state_token': token, 'state_token_id': token_id if valid else None,
                 'state_accepted': reason is None, 'rejection_reason': reason,
                 'processed_until': processed_until, 'audio_observed_until': observed_until,
                 'assembly_status': 'native_prefix', 'coverage_complete': True, 'status': 'open',
                 'raw_token': raw, 'raw_token_id': raw_id, 'adjustment': adjustment,
                 'controller_generation': self.generation, 'state_resolved_at': resolved}
        snapshot = self.context.publish_user_frame(frame)
        audit = dict(snapshot, native_step=step, delta_text=delta, raw_delta_text=raw_delta, teacher_token_ids=ids,
                     control_text=self.control_text, available_token_ids=desired,
                     consumed_token_ids=list(self.teacher_ids),
                     consumed_token_end=len(self.teacher_ids), available_token_end=len(desired),
                     pending_token_range=[common if common < len(self.teacher_ids) and not opened else len(self.teacher_ids), len(desired)],
                     consumed_before=before, gate_open=opened, gate_token_id=gate_id,
                     teacher_source_status='completed_new' if raw_delta else 'completed_empty',
                     control_consumption='closed_pending' if not opened and desired != self.teacher_ids else 'consumed' if actual_delta else 'no_delta',
                     feedback_state_id=feedback, audio_token_ids=audio_ids, gate_resolved_at=gate_resolved_at,
                     cache_rebuilds=self.rebuilds,
                     cache_replay_tokens=self.replay_tokens, cache_revision=revision,
                     teacher_char_end=len(self.cursor.text), teacher_injected_at=teacher_injected_at,
                     controller_started_at=started, kv_tokens=self.tokens,
                     empty_nonidle_count=self.mistakes, empty_nonidle_rule=self.empty_nonidle_rule)
        if reason is not None or token == '<|user_complete|>' or (token == '<|user_backchannel|>' and not self.speech_detected):
            self.reset_controller()
        return audit

    def close(self):
        self.closed = True
        self.kv, self.pending_state, self.checkpoint = None, None, None
        self.entries.clear()
        return self.context.close_user_turn(self.session_id, 'user-1', 'audio_eof')

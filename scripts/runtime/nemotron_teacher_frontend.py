"""Force native ASR increments into SoulX and publish one joint current value."""
from __future__ import annotations

from collections import deque
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


def validate_tail_range(begin, count, length):
    """A replacement is legal only when it ends exactly at the sequence tail."""
    if type(begin) is not int or type(count) is not int or type(length) is not int:
        raise TypeError('Tail replacement needs integer positions')
    if begin < 0 or count < 0 or begin + count != length:
        raise ValueError('Tail replacement must end at the sequence tail')


def tail_replace_count(previous, current):
    """Count the old pending-tail tokens replaced by the new tail encoding."""
    common = 0
    while common < len(previous) and common < len(current) and previous[common] == current[common]:
        common += 1
    replaced = len(previous) - common
    validate_tail_range(common, replaced, len(previous))
    return replaced


class TeacherTextBuffer:
    """Append canonical tokens for completed words and keep one pending word."""

    def __init__(self, tokenizer):
        self.tokenizer = tokenizer
        self.committed_text = ''
        self.committed_ids = []
        self.pending_text = ''
        self.pending_ids = []
        self.degraded_prefix = False

    def _encode(self, text):
        if not text:
            return []
        ids = self.tokenizer.encode(text, add_special_tokens=False)
        if any(i in self.tokenizer.all_special_ids for i in ids):
            raise ValueError('ASR control text contains structural special tokens')
        return ids

    def update(self, control_text, commit_pending=False):
        """Re-tokenize completed words and append only the new canonical suffix."""
        if not control_text.startswith(self.committed_text):
            raise ValueError('Teacher control text rewrote committed history: '
                             f'{self.committed_text[-40:]!r} -> {control_text[:80]!r}')
        if self.degraded_prefix:
            new_text = control_text[len(self.committed_text):]
            new_ids = self._encode(new_text)
            self.committed_text = control_text
            self.committed_ids = self.committed_ids + new_ids
            self.pending_text, self.pending_ids = '', []
            return {'committed_ids': new_ids, 'committed_text': new_text,
                    'pending_ids': [], 'pending_text': '',
                    'text_commit_index': len(self.committed_ids),
                    'tail_reencode_count': 0, 'tail_replace_tokens': 0,
                    'post_pause_extension': False}
        words = control_text.split(' ') if control_text else []
        if commit_pending:
            stable_text = control_text
            pending_text = ''
        else:
            stable_text = ' '.join(words[:-1]) if len(words) > 1 else ''
            pending_text = words[-1] if words else ''
        if not stable_text.startswith(self.committed_text):
            extension = control_text[len(self.committed_text):]
            if not extension or extension.startswith(' '):
                raise ValueError('Teacher control text rewrote committed history: '
                                 f'{self.committed_text[-40:]!r} -> {stable_text[:80]!r}')
            new_ids = self._encode(extension)
            self.committed_text = control_text
            self.committed_ids = self.committed_ids + new_ids
            self.degraded_prefix = True
            self.pending_text, self.pending_ids = '', []
            return {'committed_ids': new_ids, 'committed_text': extension,
                    'pending_ids': [], 'pending_text': '',
                    'text_commit_index': len(self.committed_ids),
                    'tail_reencode_count': 0, 'tail_replace_tokens': 0,
                    'post_pause_extension': True}
        stable_ids = self._encode(stable_text)
        if stable_ids[:len(self.committed_ids)] != self.committed_ids:
            raise ValueError('Canonical tokenization changed committed history')
        new_ids = stable_ids[len(self.committed_ids):]
        leading = ' ' if stable_text else ''
        previous_pending = self.pending_ids
        pending_ids = self._encode(leading + pending_text) if pending_text else []
        replaced = tail_replace_count(previous_pending, pending_ids)
        delta_text = stable_text[len(self.committed_text):]
        self.committed_text = stable_text
        self.committed_ids = stable_ids
        self.pending_text, self.pending_ids = pending_text, pending_ids
        return {'committed_ids': new_ids, 'committed_text': delta_text,
                'pending_ids': pending_ids, 'pending_text': pending_text,
                'text_commit_index': len(stable_ids),
                'tail_reencode_count': 1 if pending_text else 0,
                'tail_replace_tokens': replaced,
                'post_pause_extension': False}


class NemotronTeacherFrontend:
    """Own one append-only audio/text KV and fixed-source logical user turn."""

    def __init__(self, model, session_id, context=None, *, empty_nonidle_rule=True):
        if hashlib.sha256(Path(inspect.getfile(type(model))).read_bytes()).hexdigest() != UPSTREAM_SHA256:
            raise ValueError('SoulX source digest differs')
        verify_tools(model)
        self.model, self.session_id = model, session_id
        self.context = context if context is not None else SharedContext()
        self.cursor = TeacherCursor()
        self.text = TeacherTextBuffer(model.model.tokenizer)
        self.kv, self.kv_length, self.pending_state = None, 0, None
        self.previous_state, self.mistakes, self.speech_detected = None, 0, False
        self.generation, self.closed = 0, False
        self.empty_nonidle_rule = empty_nonidle_rule
        self.control_text = ''
        self.rerecognition_calls = 0
        self.pause_steps = 0
        self.audio_buffer = deque()
        self.audio_overflow = 0
        self.max_audio_blocks = 4
        tokenizer = model.model.tokenizer
        for token, expected in STATE_IDS.items():
            if tokenizer.encode(token, add_special_tokens=False) != [expected]:
                raise ValueError('SoulX state tokenizer mapping differs')
        if model.audio_eos_token.tolist() != [model.model.asr_eos_token_id]:
            raise ValueError('SoulX ASR EOS mapping differs')
        self.context.open_user_turn(session_id, 'user-1', source='nemotron')

    @property
    def teacher_ids(self):
        return self.text.committed_ids

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

    def prepare_audio(self, back, chunk, ahead):
        """Encode one block now; the state step consumes it after text is ready."""
        ids = self.model._audio_to_tokens(back, chunk, ahead)
        embeds = self.model._tokens_to_embeds(ids)
        if len(self.audio_buffer) >= self.max_audio_blocks:
            self.audio_buffer.popleft()
            self.audio_overflow += 1
        self.audio_buffer.append((ids, embeds))
        return ids

    def process_step(self, step, chunk, back, ahead, processed_until, observed_until):
        import torch
        if self.closed:
            raise ValueError('Cannot process a closed turn')
        started = time.monotonic()
        raw_delta = self.cursor.advance(step)
        model = self.model
        self.control_text = official_control_text(model, self.cursor.text)
        # A word boundary or two empty ASR steps makes the pending word final.
        self.pause_steps = 0 if raw_delta else self.pause_steps + 1
        update = self.text.update(self.control_text, commit_pending=self.pause_steps >= 2)
        ids = update['committed_ids']
        if self.audio_buffer:
            audio_ids, audio_embeds = self.audio_buffer.popleft()
        else:
            audio_ids = model._audio_to_tokens(back, chunk, ahead)
            audio_embeds = model._tokens_to_embeds(audio_ids)
        parts = [model.text_embeds] if self.kv is None else []
        feedback = self.pending_state
        if feedback is not None:
            parts.append(self._embed([feedback]))
        parts.append(audio_embeds)
        if ids:
            parts.append(self._embed(ids))
        parts.append(model.audio_eos_embeds)
        inputs = torch.cat(parts, dim=0)
        outputs = self._forward(inputs, self.kv)
        self.kv = outputs.past_key_values
        self.kv_length += inputs.shape[0]
        if hasattr(self.kv, 'get_seq_length') and self.kv.get_seq_length() != self.kv_length:
            raise RuntimeError('Teacher KV length differs from input ledger')
        if str(model.device).startswith('cuda'):
            torch.cuda.synchronize()
        teacher_injected_at = time.monotonic()
        logits = outputs.logits[0, -1]
        raw_id = int(torch.argmax(logits).item())
        tokenizer = model.model.tokenizer
        raw = tokenizer.decode([raw_id], skip_special_tokens=False)
        token, token_id, adjustment = raw, raw_id, None
        delta = update['committed_text']
        self.mistakes = self.mistakes + 1 if raw == '<|user_nonidle|>' and not raw_delta else 0
        transition = self.previous_state == '<|user_nonidle|>' and raw == '<|user_idle|>'
        empty_rule = self.empty_nonidle_rule and self.mistakes >= model.config.infer_config.max_mistake_num
        if transition or empty_rule:
            token = '<|user_complete|>' if logits[STATE_IDS['<|user_complete|>']] > logits[STATE_IDS['<|user_incomplete|>']] else '<|user_incomplete|>'
            token_id = STATE_IDS[token]
            adjustment = 'nonidle_to_idle' if transition else 'empty_nonidle_count'
        valid = token in STATE_IDS and STATE_IDS[token] == token_id
        speech_before = self.speech_detected
        far_field = (valid and token == '<|user_nonidle|>' and not speech_before
                     and model.get_rms(chunk) < model.config.infer_config.far_field_threshold)
        reason = ('unknown_state' if not valid else 'far_field' if far_field
                  else 'no_speech' if token == '<|user_complete|>' and not speech_before else None)
        self.pending_state = token_id if reason is None else None
        self.previous_state = token if reason is None else None
        self.speech_detected |= reason is None and token == '<|user_nonidle|>'
        resolved = time.monotonic()
        service_state = ('speak' if token in ('<|user_complete|>', '<|user_incomplete|>') and reason is None
                         else 'idle' if token == '<|user_idle|>' and reason is None
                         else 'nonidle' if token in ('<|user_nonidle|>', '<|user_backchannel|>') and reason is None
                         else None)
        completion = ('model_complete' if service_state == 'speak' and token == '<|user_complete|>'
                      and speech_before else None)
        service_text = self.text.pending_text if service_state == 'speak' else ''
        frame = {'session_id': self.session_id, 'turn_id': 'user-1', 'source': 'nemotron',
                 'text': self.cursor.text, 'state_token': token, 'state_token_id': token_id if valid else None,
                 'state_accepted': reason is None, 'rejection_reason': reason,
                 'processed_until': processed_until, 'audio_observed_until': observed_until,
                 'assembly_status': 'native_prefix', 'coverage_complete': True, 'status': 'open',
                 'raw_token': raw, 'raw_token_id': raw_id, 'adjustment': adjustment,
                 'controller_generation': self.generation, 'state_resolved_at': resolved,
                 'speech_detected': speech_before, 'service_state': service_state,
                 'service_completion_source': completion, 'service_text': service_text}
        snapshot = self.context.publish_user_frame(frame)
        audit = dict(snapshot, native_step=step, delta_text=delta, raw_delta_text=raw_delta,
                     teacher_token_ids=ids, control_text=self.control_text,
                     committed_text=self.text.committed_text,
                     committed_token_end=update['text_commit_index'],
                     pending_text=update['pending_text'], pending_token_ids=update['pending_ids'],
                     text_commit_index=update['text_commit_index'],
                     tail_reencode_count=update['tail_reencode_count'],
                     tail_replace_tokens=update['tail_replace_tokens'],
                     post_pause_extension=update['post_pause_extension'],
                     text_injected_tokens=len(ids),
                     teacher_source_status='completed_new' if raw_delta else 'completed_empty',
                     control_consumption='consumed' if ids else 'pending_tail' if update['pending_text'] else 'no_delta',
                     feedback_state_id=feedback, audio_token_ids=audio_ids,
                     kv_tokens=self.kv_length,
                     audio_buffer_depth=len(self.audio_buffer),
                     audio_buffer_overflow=self.audio_overflow,
                     whole_turn_rerecognition_calls=self.rerecognition_calls,
                     flushed_text_chars=len(service_text),
                     teacher_char_end=len(self.cursor.text), teacher_injected_at=teacher_injected_at,
                     controller_started_at=started,
                     empty_nonidle_count=self.mistakes, empty_nonidle_rule=self.empty_nonidle_rule)
        if reason is not None or token == '<|user_complete|>' or (token == '<|user_backchannel|>' and not self.speech_detected):
            self.reset_controller()
        return audit

    def close(self):
        self.closed = True
        self.kv, self.pending_state = None, None
        self.kv_length = 0
        return self.context.close_user_turn(self.session_id, 'user-1', 'audio_eof')

"""Force native ASR increments into SoulX and publish one joint current value."""
from __future__ import annotations

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

    def __init__(self, model, session_id, context=None, *, empty_nonidle_rule=True, max_tokens=8192):
        if hashlib.sha256(Path(inspect.getfile(type(model))).read_bytes()).hexdigest() != UPSTREAM_SHA256:
            raise ValueError('SoulX source digest differs')
        self.model, self.session_id = model, session_id
        self.context = context if context is not None else SharedContext()
        self.cursor, self.teacher_ids = TeacherCursor(), []
        self.kv, self.pending_state = None, None
        self.previous_state, self.mistakes, self.speech_detected = None, 0, False
        self.tokens, self.max_tokens = 0, max_tokens
        self.generation, self.closed = 0, False
        self.empty_nonidle_rule = empty_nonidle_rule
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

    def process_step(self, step, chunk, back, ahead, processed_until, observed_until):
        import torch
        if self.closed:
            raise ValueError('Cannot process a closed turn')
        started = time.monotonic()
        delta = self.cursor.advance(step)
        model, tokenizer = self.model, self.model.model.tokenizer
        ids = tokenizer.encode(delta, add_special_tokens=False) if delta else []
        if any(i in tokenizer.all_special_ids for i in ids):
            raise ValueError('ASR text contains structural special tokens')
        self.teacher_ids.extend(ids)
        if tokenizer.decode(self.teacher_ids, skip_special_tokens=False,
                            clean_up_tokenization_spaces=False) != self.cursor.text:
            raise ValueError('Teacher token decoding differs from original character stream')
        audio = model._tokens_to_embeds(model._audio_to_tokens(back, chunk, ahead))
        parts = [model.text_embeds] if self.kv is None else []
        if self.pending_state is not None:
            parts.append(model.embed_tokens_func(torch.tensor([self.pending_state], device=model.device)))
        parts.append(audio)
        if ids:
            parts.append(model.embed_tokens_func(torch.tensor(ids, device=model.device)))
        parts.append(model.audio_eos_embeds)
        self.tokens += sum(v.shape[0] for v in parts)
        if self.tokens > self.max_tokens:
            raise RuntimeError('Teacher controller token limit exceeded')
        teacher_injected_at = time.monotonic()
        with torch.inference_mode():
            outputs = model.model.llm(inputs_embeds=torch.cat(parts, dim=0).unsqueeze(0),
                                      past_key_values=self.kv, use_cache=True)
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
        audit = dict(snapshot, native_step=step, delta_text=delta, teacher_token_ids=ids,
                     teacher_char_end=len(self.cursor.text), teacher_injected_at=teacher_injected_at,
                     controller_started_at=started, kv_tokens=self.tokens,
                     empty_nonidle_count=self.mistakes, empty_nonidle_rule=self.empty_nonidle_rule)
        if reason is not None or token == '<|user_complete|>' or (token == '<|user_backchannel|>' and not self.speech_detected):
            self.reset_controller()
        return audit

    def close(self):
        self.closed = True
        self.kv, self.pending_state = None, None
        return self.context.close_user_turn(self.session_id, 'user-1', 'audio_eof')

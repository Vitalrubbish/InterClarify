"""Inject only EOS-closed X2 emits through the frozen SoulX teacher path."""
from __future__ import annotations

import hashlib
import json

try:
    from .nemotron_teacher_frontend import NemotronTeacherFrontend, TeacherTextBuffer
    from .shared_context import SharedContext
except ImportError:
    from nemotron_teacher_frontend import NemotronTeacherFrontend, TeacherTextBuffer
    from shared_context import SharedContext


class ClosedTextBuffer(TeacherTextBuffer):
    """Use the canonical full prefix and reject any degraded suffix fallback."""

    def _extension(self, control_text):
        raise ValueError('X2 closed text attempted a post-commit word extension')

    def update(self, control_text, commit_pending=False):
        result = super().update(control_text, commit_pending=True)
        if result['pending_text'] or result['pending_ids'] or result['post_pause_extension']:
            raise AssertionError('Closed X2 text produced pending or degraded tokens')
        return result


class X2Context:
    """Translate the inherited source tag before atomic Context validation."""

    def __init__(self, context):
        self.context = context

    def open_user_turn(self, session_id, turn_id, source):
        return self.context.open_user_turn(session_id, turn_id, source='x2_streaming_asr',
                                            publication_mode='legacy_frame')

    def publish_user_frame(self, frame):
        return self.context.publish_user_frame(dict(frame, source='x2_streaming_asr'))

    def close_user_turn(self, *args):
        return self.context.close_user_turn(*args)


class X2TeacherFrontend(NemotronTeacherFrontend):
    """Reuse the entire state/KV step, changing text commitment and provenance."""

    def __init__(self, model, session_id, context=None, *, empty_nonidle_rule=True):
        actual = context if context is not None else SharedContext()
        super().__init__(model, session_id, X2Context(actual), empty_nonidle_rule=empty_nonidle_rule)
        self.text = ClosedTextBuffer(model.model.tokenizer)
        self.empty_run_length = 0

    def process_step(self, step, chunk, back, ahead, processed_until, observed_until):
        import numpy as np
        if step.get('x2_open_group_tokens') != 0 or step.get('x2_frames_consumed') != 2:
            raise ValueError('Online X2 teacher step must contain two frames and no open emit')
        before = self.cursor.text
        delta = step['text'][len(before):] if step['text'].startswith(before) else None
        frame = super().process_step(step, chunk, back, ahead, processed_until, observed_until)
        self.empty_run_length = self.empty_run_length + 1 if not delta else 0
        canonical = self.text._encode(self.control_text)
        if self.teacher_ids != canonical:
            raise AssertionError('X2 cumulative tokens differ from canonical closed text')
        if any(frame[k] for k in ('pending_text', 'pending_token_ids', 'tail_reencode_count',
                                  'tail_replace_tokens', 'post_pause_extension')):
            raise AssertionError('X2 tail audit must remain empty or zero')
        frame.update(empty_run_length=self.empty_run_length,
                     rule_applied=frame['raw_token'] != frame['state_token'],
                     chunk_rms=float(np.sqrt(np.mean(np.asarray(chunk, dtype=np.float64) ** 2))),
                     x2_closed_groups=step['x2_closed_groups'], x2_open_group_tokens=0,
                     x2_frames_consumed=step['x2_frames_consumed'],
                     canonical_token_match=True, canonical_token_count=len(canonical),
                     cumulative_token_sha256=hashlib.sha256(json.dumps(self.teacher_ids).encode()).hexdigest())
        return frame

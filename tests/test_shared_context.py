"""Check latest-only storage, snapshot isolation and turn boundaries."""
from pathlib import Path
import sys
import threading
import unittest

sys.path.insert(0, str(Path(__file__).parents[1] / 'scripts/runtime'))
from shared_context import SharedContext, STATE_IDS


class SharedContextTests(unittest.TestCase):
    def test_turn_starts_with_one_joint_x2_snapshot(self):
        context = SharedContext()
        opened = context.open_user_turn('s', 't')
        self.assertEqual((opened['source'], opened['publication_mode']), ('x2_streaming_asr', 'joint'))
        self.assertEqual((opened['text'], opened['step_id'], opened['committed_groups']), ('', -1, 0))
        self.assertEqual(opened['tail_status'], 'unknown')
        with self.assertRaises(ValueError):
            context.open_user_turn('s', 't', 'sensevoice_small')

    def test_reader_copies_do_not_mutate_current_value(self):
        context = SharedContext()
        first = context.open_user_turn('s', 't')
        first['text'] = 'mutated reader'
        current = context.get_user_turn('s', 't')
        self.assertEqual(current['text'], '')
        current['text'] = 'mutated again'
        self.assertEqual(context.get_user_turn('s', 't')['text'], '')
        self.assertEqual(len(context.latest), 1)
        self.assertFalse(hasattr(context, 'events'))

    def test_close_fences_late_writes_and_release_removes_turn(self):
        context = SharedContext()
        context.open_user_turn('s', 't')
        closed = context.close_user_turn('s', 't', 'eof')
        self.assertEqual(closed['status'], 'closed')
        with self.assertRaises(ValueError):
            context.open_user_turn('s', 't')
        context.release_closed_turn('s', 't')
        context.open_user_turn('s', 't')
        self.assertEqual(context.get_user_turn('s', 't')['status'], 'open')

    def test_capacity_and_identifier_boundaries(self):
        context = SharedContext(max_turns=1)
        context.open_user_turn('s', 't')
        with self.assertRaises(RuntimeError):
            context.open_user_turn('s', 'other')
        with self.assertRaises(ValueError):
            context.open_user_turn('', 'turn')
        with self.assertRaises(KeyError):
            context.get_user_turn('s', 'missing')
        context.close_user_turn('s', 't', 'eof')
        context.release_closed_turn('s', 't')
        context.open_user_turn('s', 'other')

    def test_concurrent_readers_cannot_mix_frames(self):
        context = SharedContext(max_turns=1)
        context.open_user_turn('s', 't')
        context.latest[('s', 't')]['text'] = 'hello'
        errors = []

        def read():
            try:
                for _ in range(200):
                    value = context.get_user_turn('s', 't')
                    self.assertEqual(value['text'], 'hello')
            except Exception as exc:
                errors.append(exc)

        threads = [threading.Thread(target=read) for _ in range(4)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        self.assertFalse(errors)

    def test_state_ids_are_frozen(self):
        self.assertEqual(sorted(STATE_IDS.values()), [151676, 151677, 151678, 151680, 151681])


if __name__ == '__main__':
    unittest.main()

"""Verify atomic publication, real revisions and consumer cursor isolation."""
from copy import deepcopy
import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).parents[1] / 'scripts/runtime'))
from shared_context import CursorGap, FrontendConsumer, SharedContext


def event(seq, kind='frontend_lifecycle', **payload):
    return {'schema_version': 1, 'event_id': f's:t:{seq}', 'kind': kind,
            'session_id': 's', 'turn_id': 't', 'source': 'sensevoice_small',
            'producer_id': 'p', 'producer_seq': seq, 'asr_generation': 'g',
            'controller_generation': 0, 'received_at': 1., 'clock_id': 'test', **payload}


def transcript(seq, version=0, text='', **payload):
    return event(seq, 'user_transcript', version=version, asr_version=version,
                 text=text, status='open', **payload)


class SharedContextTests(unittest.TestCase):
    def test_revision_and_independent_readers(self):
        context = SharedContext()
        readers = [FrontendConsumer('s'), FrontendConsumer('s')]
        context.publish_user_transcript(transcript(1))
        context.publish_user_transcript(transcript(2, 1, 'inter', base_asr_version=0,
                                                     replace_from=0, replacement='inter'))
        readers[0].consume(context)
        context.publish_user_transcript(transcript(3, 2, 'internet.', base_asr_version=1,
                                                     replace_from=5, replacement='net.'))
        for reader in readers:
            reader.consume(context)
            self.assertEqual(reader.turns['t']['text'], 'internet.')
        self.assertEqual(readers[0].cursor, readers[1].cursor)
        self.assertEqual(readers[0].consume(context), [])

    def test_atomic_rollback_and_duplicate_conflict(self):
        context = SharedContext()
        first = transcript(1)
        context.publish_user_transcript(first)
        self.assertEqual(context.publish_user_transcript(first)['status'], 'duplicate')
        with self.assertRaises(ValueError):
            context.commit_frontend_events([event(2), event(4)])
        self.assertEqual(context.sequence, 1)
        conflict = deepcopy(first)
        conflict['text'] = 'wrong'
        with self.assertRaises(ValueError):
            context.publish_user_transcript(conflict)
        with self.assertRaises(ValueError):
            context.commit_frontend_events([event(2, depends_on=['missing'])])
        context.commit_frontend_events([event(2)])
        self.assertEqual(context.sequence, 2)

    def test_close_empty_result_and_cursor_expiry(self):
        context = SharedContext(max_updates=3)
        context.publish_user_transcript(transcript(1))
        context.publish_user_transcript(transcript(2, 1, 'hello', base_asr_version=0,
                                                     replace_from=0, replacement='hello'))
        closed = transcript(3, 2, 'hello', close_reason='eof')
        closed.update(status='closed', asr_version=1)
        context.publish_user_transcript(closed)
        with self.assertRaises(ValueError):
            context.publish_user_transcript(transcript(4, 3, 'later'))
        context.commit_frontend_events([event(4)])
        with self.assertRaises(CursorGap):
            context.read_frontend_updates('s', 0)
        consumer = FrontendConsumer('s')
        self.assertEqual(consumer.resynchronize(context, 't')['transcript']['text'], 'hello')
        self.assertEqual(list(consumer.states), [])

    def test_patch_and_state_dependency_validation(self):
        context = SharedContext()
        context.publish_user_transcript(transcript(1))
        with self.assertRaises(ValueError):
            context.publish_user_transcript(transcript(2, 1, 'new', base_asr_version=0,
                                                         replace_from=0, replacement='other'))
        control = event(2, 'control_observation', control_revision=1)
        state = event(3, 'user_state', token='<|user_complete|>', token_id=151676,
                      accepted=True, depends_on=[control['event_id']],
                      basis={'transcript_version': 0, 'asr_version': 0, 'control_revision': 1,
                             'control_event_id': control['event_id'], 'control_event_seq': 2})
        context.commit_frontend_events([control, state])
        context.publish_user_transcript(transcript(4, 1, 'later', base_asr_version=0,
                                                     replace_from=0, replacement='later'))
        read = context.read_frontend_updates('s')['updates']
        self.assertEqual(read[2]['basis']['asr_version'], 0)
        self.assertEqual(context.get_user_turn('s', 't', at_event_seq=3)['transcript']['text'], '')


if __name__ == '__main__':
    unittest.main()

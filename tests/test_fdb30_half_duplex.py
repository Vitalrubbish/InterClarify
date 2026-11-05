"""Verify committed-state reply boundaries and cumulative text consumption."""
import sys
from pathlib import Path
import unittest

sys.path.insert(0,str(Path(__file__).parents[1]/'scripts/remote'))
from fdb30_half_duplex import JointReplyConsumer


class Session:
    def __init__(self):
        self.actions=[]
        self.active=False
    def check(self): pass
    def busy(self): return self.active
    def cancel(self,reason):
        if self.active:
            self.actions.append(('cancel',reason))
            self.active=False
    def start(self,text):
        self.actions.append(('start',text))
        self.active=True
        return True


def row(step,token,text,accepted=True):
    return {'step_id':step,'batch_published_at':1.,'snapshot':{'text':text},
            'receipts':{'controller':{'state':{'state_token':token,'raw_token':token,
                'state_accepted':accepted,'state_observed_until':2560,'state_processed_until':1920}}}}


class ConsumerTests(unittest.TestCase):
    def test_cancel_and_resume_without_repeating_prefix(self):
        session=Session(); consumer=JointReplyConsumer(session,lambda *a,**k:None)
        consumer.consume(row(0,'<|user_complete|>','Hello'))
        consumer.consume(row(1,'<|user_nonidle|>','Hello again'))
        consumer.consume(row(2,'<|user_complete|>','Hello again'))
        consumer.consume(row(3,'<|user_complete|>','Hello again'))
        self.assertEqual(session.actions,[('start','Hello'),('cancel','soulx_nonidle'),('start','again')])

    def test_rejected_state_and_empty_text_do_not_start(self):
        session=Session(); consumer=JointReplyConsumer(session,lambda *a,**k:None)
        consumer.consume(row(0,'<|user_complete|>','hello',False))
        consumer.consume(row(1,'<|user_complete|>',''))
        self.assertEqual(session.actions,[])

    def test_duplicate_snapshot_is_rejected(self):
        consumer=JointReplyConsumer(Session(),lambda *a,**k:None)
        consumer.consume(row(0,'<|user_idle|>',''))
        with self.assertRaises(ValueError): consumer.consume(row(0,'<|user_idle|>',''))


if __name__=='__main__': unittest.main()

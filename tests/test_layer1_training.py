"""Exercise supervision boundaries and optimizer/RNG/cursor recovery."""

import importlib.util
from pathlib import Path
import random
import sys
import tempfile
import unittest
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts/training'))
import train_layer1 as training


class SupervisionTests(unittest.TestCase):
    def row(self):
        return {'input_ids': [1, 2, 3, 4, 5, 6], 'labels': [-100, -100, -100, -100, 5, 6],
                'attention_mask': [1] * 6, 'effective_tokens': 2,
                'spans': [{'start': 0, 'target_start': 1, 'end': 3, 'supervised': False},
                          {'start': 3, 'target_start': 4, 'end': 6, 'supervised': True}]}

    def test_history_and_headers_are_masked(self):
        training.validate_sequence(self.row())

    def test_user_history_target_and_count_corruption_are_rejected(self):
        for position, value in ((0, 1), (1, 2), (3, 4), (4, 7)):
            row = self.row()
            row['labels'][position] = value
            with self.assertRaises(ValueError):
                training.validate_sequence(row)
        row = self.row()
        row['effective_tokens'] = 3
        with self.assertRaises(ValueError):
            training.validate_sequence(row)

    def test_span_gap_overlap_and_padding_are_rejected(self):
        for start in (2, 4):
            row = self.row()
            row['spans'][1]['start'] = start
            with self.assertRaises(ValueError):
                training.validate_sequence(row)
        row = self.row()
        row['attention_mask'][-1] = 0
        with self.assertRaises(ValueError):
            training.validate_sequence(row)

    def test_sampler_cannot_repeat_epoch_or_overrun(self):
        dataset = object.__new__(training.ProbeDataset)
        dataset.order = [('one', 0)]
        for cursor, count in ((-1, 1), (1, 1), (0, 2)):
            with self.assertRaisesRegex(ValueError, 'single-epoch'):
                dataset.rows(cursor, count)

    def test_existing_run_is_never_modified_by_failed_startup(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            path = directory / 'failure.json'
            path.write_text('prior evidence')
            args = SimpleNamespace(command='train', output=directory)
            training.record_failure(args, FileExistsError('Already exists'))
            self.assertEqual(path.read_text(), 'prior evidence')
            args.output_created = True
            training.record_failure(args, ValueError('Owned run failed'))
            self.assertIn('Owned run failed', path.read_text())


@unittest.skipUnless(importlib.util.find_spec('torch'), 'Tensor checks run in the remote training conda')
class StateTests(unittest.TestCase):
    def test_collation_masks_right_padding_and_keeps_causal_labels(self):
        row = SupervisionTests().row()
        short = {'input_ids': [1, 2], 'labels': [-100, 2], 'attention_mask': [1, 1]}
        batch = training.collate([row, short], 9, 'cpu')
        self.assertEqual(batch['input_ids'][1].tolist(), [1, 2, 9, 9, 9, 9])
        self.assertEqual(batch['labels'][1].tolist(), [-100, 2, -100, -100, -100, -100])
        self.assertEqual(batch['attention_mask'][1].tolist(), [1, 1, 0, 0, 0, 0])

    def test_optimizer_scheduler_rng_and_cursor_resume_exactly(self):
        import numpy as np
        import torch
        random.seed(11)
        np.random.seed(11)
        torch.manual_seed(11)
        model = torch.nn.Linear(3, 2)
        model.bias.requires_grad_(False)
        optimizer = torch.optim.AdamW([model.weight], lr=0.01)
        scheduler = torch.optim.lr_scheduler.LambdaLR(optimizer, lambda step: 1 / (step + 1))

        def update():
            x = torch.rand(2, 3) * (random.random() + np.random.rand())
            loss = torch.nn.functional.dropout(model(x), 0.3, training=True).square().mean()
            loss.backward()
            optimizer.step()
            scheduler.step()
            optimizer.zero_grad(set_to_none=True)
            return loss.item()

        update()
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'checkpoint.pt'
            identity = {'data': 'frozen', 'order': [1, 0]}
            training.save_checkpoint(path, model, optimizer, scheduler, identity, 1, 2)
            expected_loss = update()
            expected = {k: training.tree_digest(v) for k, v in {
                'weights': model.state_dict(), 'optimizer': optimizer.state_dict(),
                'scheduler': scheduler.state_dict(), 'rng': training.rng_state()}.items()}
            with self.assertRaisesRegex(ValueError, 'identity'):
                training.restore_checkpoint(path, model, optimizer, scheduler, {'data': 'changed'})
            step, cursor = training.restore_checkpoint(path, model, optimizer, scheduler, identity)
            self.assertEqual((step, cursor), (1, 2))
            self.assertEqual(update(), expected_loss)
            actual = {k: training.tree_digest(v) for k, v in {
                'weights': model.state_dict(), 'optimizer': optimizer.state_dict(),
                'scheduler': scheduler.state_dict(), 'rng': training.rng_state()}.items()}
            self.assertEqual(actual, expected)

    def test_save_rejects_partial_accumulation_and_digest_covers_tensor_bytes(self):
        import torch
        model = torch.nn.Linear(2, 1)
        model(torch.ones(1, 2)).sum().backward()
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaisesRegex(ValueError, 'optimizer boundaries'):
                training.save_checkpoint(Path(tmp) / 'state.pt', model, None, None, {}, 0, 0)
        tensor = torch.tensor([1.0, 2.0])
        self.assertNotEqual(training.tree_digest({'a': tensor}), training.tree_digest({'a': tensor + 1}))


if __name__ == '__main__':
    unittest.main()

"""Pin the FLEURS selection rule and manifest verification checks."""

import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest
import wave

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts/remote'))
import x2_turn_complete_test as x2


def write_wav(path: Path, frames: int = 1600) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), 'wb') as audio:
        audio.setparams((1, 2, 16000, 0, 'NONE', 'not compressed'))
        audio.writeframes(b'\x00\x00' * frames)


def sample(split: str, name: str, reference: str, path: Path) -> dict:
    return {
        'sample_id': f'{split}/{name}',
        'split': split,
        'relative_path': str(Path('audio') / split / name),
        'selection_sha256': hashlib.sha256(name.encode()).hexdigest(),
        'sentence_id': '1',
        'gender': 'MALE',
        'reference': reference,
        'dataset_normalized_reference': reference.lower(),
        'normalized_reference': reference.lower(),
        'normalized_reference_words': len(reference.split()),
        'audio_sha256': x2.sha256_file(path),
        'audio_bytes': path.stat().st_size,
        'channels': 1,
        'sample_rate': 16000,
        'frames': 1600,
        'duration_seconds': 0.1,
        'resampled': False,
        'channels_converted': False,
        'trimmed_silence': False,
    }


class FleursDataTests(unittest.TestCase):
    def fixture(self, root: Path) -> Path:
        rows = [['1', f'{index}.wav', 'Hello world', 'hello world', '', '', 'MALE'] for index in range(4)]
        wanted = x2.select_rows(rows, 2)
        manifest_dir = root / 'dataset' / 'fleurs_en_us'
        samples = []
        for split, name, text in (
            ('test', wanted[0][1][1], 'Hello world'),
            ('dev', wanted[1][1][1], 'Hello world'),
        ):
            audio = manifest_dir / 'audio' / split / name
            write_wav(audio)
            samples.append(sample(split, name, text, audio))
        source = manifest_dir / 'source' / 'en_us' / 'test.tsv'
        source.parent.mkdir(parents=True)
        source.write_text('fixture\n')
        totals = {
            'test': {'samples': 1, 'duration_seconds': 0.1, 'normalized_words': 2,
                     'audio_bytes': samples[0]['audio_bytes']},
            'dev': {'samples': 1, 'duration_seconds': 0.1, 'normalized_words': 2,
                    'audio_bytes': samples[1]['audio_bytes']},
        }
        manifest = {
            'repo': x2.FLEURS_REPO,
            'revision': x2.FLEURS_REVISION,
            'totals': totals,
            'samples': samples,
            'source_copies': {'data/en_us/test.tsv': {
                'relative_path': 'source/en_us/test.tsv',
                'sha256': x2.sha256_file(source),
            }},
        }
        path = manifest_dir / 'manifest.json'
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(manifest))
        return path

    def test_selection_uses_ascending_filename_hash(self):
        rows = [['1', name, 'a b', 'a b', '', '', 'MALE']
                for name in ('c.wav', 'a.wav', 'b.wav')]
        selected = x2.select_rows(rows, 2)
        expected = sorted(rows, key=lambda row: hashlib.sha256(row[1].encode()).hexdigest())[:2]
        self.assertEqual([row[1] for _, row in selected], [row[1] for row in expected])
        self.assertEqual([key for key, _ in selected],
                         [hashlib.sha256(row[1].encode()).hexdigest() for row in expected])

    def test_verification_accepts_frozen_fixture(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = self.fixture(Path(tmp))
            result = x2.verify_manifest(
                path,
                expected=x2.Expectations(test_count=1, dev_count=1,
                                        test_duration_seconds=0.1, test_normalized_words=2),
                normalizer=lambda text: text.lower(),
            )
            self.assertEqual((result['test_samples'], result['dev_samples']), (1, 1))

    def test_verification_rejects_modified_audio(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = self.fixture(Path(tmp))
            write_wav(path.parent / 'audio' / 'test' / sorted(
                item.name for item in (path.parent / 'audio' / 'test').glob('*.wav'))[0], frames=1601)
            with self.assertRaisesRegex(ValueError, 'digest mismatch'):
                x2.verify_manifest(
                    path,
                    expected=x2.Expectations(test_count=1, dev_count=1,
                                            test_duration_seconds=0.1, test_normalized_words=2),
                    normalizer=lambda text: text.lower(),
                )

    def test_verification_rejects_mixed_split_identity(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = self.fixture(Path(tmp))
            manifest = json.loads(path.read_text())
            manifest['samples'][1]['sample_id'] = 'test/' + Path(manifest['samples'][1]['relative_path']).name
            path.write_text(json.dumps(manifest))
            with self.assertRaisesRegex(ValueError, 'mixes split identity'):
                x2.verify_manifest(
                    path,
                    expected=x2.Expectations(test_count=1, dev_count=1,
                                            test_duration_seconds=0.1, test_normalized_words=2),
                    normalizer=lambda text: text.lower(),
                )


if __name__ == '__main__':
    unittest.main()

"""Evaluate exactly one frozen TextTurn candidate on the untouched text split."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'training'))
from train_textturn import evaluate, file_hash, load_controller, read_rows, write_json


def evaluate_text(args):
    candidate_path = args.training / 'candidate.json'
    candidate = json.loads(candidate_path.read_text())
    if not candidate['continue_online']:
        raise ValueError('Development gate did not permit independent evaluation')
    adapter = args.training / 'best'
    if file_hash(adapter / 'adapter_model.safetensors') != candidate['adapter_sha256']:
        raise ValueError('Frozen candidate changed')
    config = json.loads(args.config.read_text())
    manifest = json.loads((args.data / 'manifest.json').read_text())
    for name, expected in manifest['files'].items():
        if file_hash(args.data / name) != expected:
            raise ValueError(f'Frozen dataset changed: {name}')
    if args.output.exists() and any(args.output.iterdir()):
        raise ValueError('Evaluation output must be fresh')
    args.output.mkdir(parents=True, exist_ok=True)
    write_json(args.output / 'identity.json', {
        'candidate_sha256': file_hash(candidate_path), 'adapter_sha256': candidate['adapter_sha256'],
        'dataset_manifest_sha256': file_hash(args.data / 'manifest.json'),
        'test_sha256': manifest['files']['test.jsonl'], 'selection_uses_test': False,
        'scoring_rule': 'complete_opportunity_with_false_action_and_1000ms_deadline_v1'})
    started = time.monotonic()
    model, _, token_ids = load_controller(args.model, args.data, config, adapter)
    result = evaluate(model, read_rows(args.data / 'test.jsonl'), token_ids,
                      args.output / 'text', started, config)
    checks = {'smooth': result['smooth']['rate'] >= .8,
              'declarative': result['declarative']['rate'] >= .8,
              'interruption': result['interruption']['rate'] >= .8,
              'pause_false_start': result['pause_false_start']['rate'] <= .15,
              'backchannel_false_stop': result['backchannel_false_stop']['rate'] <= .15}
    write_json(args.output / 'conclusion.json', {'text_checks': checks,
               'text_quality_pass': all(checks.values()), 'online_conclusion': 'insufficient_evidence',
               'elapsed_seconds': time.monotonic() - started,
               'missing_zh': ['Nemotron真实语音输入及Context接口验收尚需独立运行。',
                              '给定状态文本诊断不包含自由运行、传输、排队或实际播放延迟。']})
    (args.output / 'README.md').write_text(
        '# TT-004 独立文本评估\n\n固定候选和完整独立文本集合已运行。'
        + ('四类及陈述句文本质量点估计达标。' if all(checks.values()) else '文本质量存在未达标项。')
        + '逐机会分母和95%区间见text/summary.json，失败保留在opportunities.csv。'
        + '在线结论为证据不足，不能由合成文本或给定状态推理替代Nemotron与Context验收。\n')
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--model', type=Path, required=True)
    parser.add_argument('--data', type=Path, required=True)
    parser.add_argument('--training', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--config', type=Path, default=Path('configs/textturn_training.json'))
    print(json.dumps(evaluate_text(parser.parse_args()), ensure_ascii=False, indent=2))

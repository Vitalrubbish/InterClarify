"""Expose a frozen TextTurn candidate for bounded local shadow requests."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
import threading
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'training'))
from build_textturn_dataset import ACTIONS, LEGAL, prompt_for
from train_textturn import action_logits, file_hash, load_controller
from textturn_candidate import validate_candidate


class Controller:
    def __init__(self, model, data, training, config_path):
        import torch
        config = json.loads(config_path.read_text())
        candidate = json.loads((training / 'candidate.json').read_text())
        manifest = json.loads((data / 'manifest.json').read_text())
        self.input_contract = manifest.get('input_contract')
        self.identity = None
        if '<finish>' in manifest['new_token_ids']:
            self.identity = validate_candidate(training, data, config_path, model)
        adapter = training / 'best'
        if not candidate['continue_online'] or file_hash(adapter / 'adapter_model.safetensors') != candidate['adapter_sha256']:
            raise ValueError('Candidate was not frozen and permitted by development gate')
        self.model, self.tokenizer, self.ids = load_controller(model, data, config, adapter)
        self.token_ids = manifest['new_token_ids']
        self.model.eval()
        self.maximum = config['max_length']
        self.lock = threading.Lock()
        self.sha256 = candidate['adapter_sha256']
        torch.set_num_threads(4)

    def decide(self, visible):
        import torch
        if visible.get('state') not in LEGAL or visible.get('cot') != '':
            raise ValueError('Expected a phase-one legal state and empty CoT')
        visible = dict(visible)
        if self.input_contract:
            visible['input_contract'] = self.input_contract
        else:
            for key in ('observation_type', 'playback_phase', 'consecutive_empty_observations'):
                visible.pop(key, None)
        ids = self.tokenizer.encode(prompt_for(visible), add_special_tokens=False)
        if len(ids) + 1 > self.maximum:
            raise ValueError('Control input exceeds 2048 tokens')
        begin = time.monotonic()
        with self.lock, torch.inference_mode():
            logits = action_logits(self.model, ids)
            legal = ('keep', 'start') if visible['state'] == 'Listen' else ('keep', 'stop')
            indices = [self.ids[list(ACTIONS).index(action)] for action in legal]
            action = legal[int(logits[indices].argmax().item())]
            legal_logits = {name: float(logits[index].item()) for name, index in zip(legal, indices)}
            torch.cuda.synchronize()
        return {'action': action, 'service_ms': (time.monotonic() - begin) * 1000,
                'input_tokens': len(ids), 'candidate_sha256': self.sha256, 'legal_logits': legal_logits}


def create_app(controller):
    from fastapi import FastAPI, HTTPException
    app = FastAPI()

    @app.get('/health')
    def health():
        return {'status': 'ok', 'candidate_sha256': controller.sha256,
                'token_ids': controller.token_ids, 'identity': controller.identity}

    @app.post('/decide')
    def decide(visible: dict):
        try:
            return controller.decide(visible)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc

    return app


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--model', type=Path, required=True)
    parser.add_argument('--data', type=Path, required=True)
    parser.add_argument('--training', type=Path, required=True)
    parser.add_argument('--config', type=Path, required=True)
    parser.add_argument('--port', type=int, default=18816)
    args = parser.parse_args()
    import uvicorn
    uvicorn.run(create_app(Controller(args.model, args.data, args.training, args.config)),
                host='127.0.0.1', port=args.port)

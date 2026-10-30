"""Project online facts into the versioned controller input contract."""
import json
import re

CONTRACT = 'textturn-causal-v2'


def user_text(text):
    return re.sub(r'[.?!。！？…]+([\"\'”’）)\]}]*)$', r'\1', text.rstrip())


def model_visible(visible):
    history = []
    for item in visible.get('history', []):
        entry = {'role': item['role'], 'text': user_text(item['text']) if item['role'] == 'user' else item['text']}
        if item['role'] == 'assistant':
            for key in ('played_text', 'interrupted', 'completion'):
                if key in item:
                    entry[key] = item[key]
        history.append(entry)
    events = [{'kind': e['kind'], **({'marker': '<finish>'} if e['kind'] == 'finish' else {})}
              for e in visible.get('runtime_events', []) if e['kind'] in ('stop', 'finish', 'error')]
    terminal = visible.get('latest_terminal')
    observation = visible.get('observation', '')
    kind = visible.get('observation_type', 'empty-observation' if observation == '<|no-voice|>' else 'text-update')
    state = visible['state']
    return dict(history=history, user_text=user_text(visible.get('user_text', '')),
                observation=user_text(observation) if kind == 'text-update' else '<|no-voice|>',
                observation_type=kind, state=state,
                playback_phase=visible.get('playback_phase', 'idle' if state == 'Listen' else
                                           'playing' if visible.get('played_text') else 'preparing'),
                assistant_visible=visible.get('assistant_visible', ''), played_text=visible.get('played_text', ''),
                assistant_generation_complete=visible.get('assistant_generation_complete'),
                consecutive_empty_observations=visible.get('consecutive_empty_observations',
                                                           visible.get('consecutive_no_voice_windows', 0)),
                runtime_events=events, latest_terminal={'kind': terminal['kind']} if terminal else None,
                window_ms=160, cot='')


def render_prompt(visible):
    payload = json.dumps(model_visible(visible), ensure_ascii=False, separators=(',', ':'))
    return ('<|im_start|>system\nChoose one legal TextTurn action. '
            'Listen: keep/start. Speak: keep/stop. Stop only for user interruption.'
            '<|im_end|>\n<|im_start|>user\n' + payload +
            '<|im_end|>\n<|im_start|>assistant\n<think>\n\n</think>\n\n')

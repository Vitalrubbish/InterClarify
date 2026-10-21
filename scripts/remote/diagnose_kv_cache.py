"""Reproduce one real-weight cache divergence and isolate arithmetic effects."""
from __future__ import annotations

import argparse
import asyncio
import gc
import hashlib
import json
from pathlib import Path
import time

import torch
from transformers import DynamicCache, RepetitionPenaltyLogitsProcessor

from duplex_model_service import OfficialDuplexModel, PrefixCachePool


def summarize_logits(left, right, tokenizer):
    """Compare complete vocabulary vectors and retain decoded leading candidates."""
    left, right = left.float().cpu().reshape(-1), right.float().cpu().reshape(-1)
    result = {}
    for name, vector in [('full', left), ('cached', right)]:
        values, ids = vector.topk(8)
        result[name] = {'ids': ids.tolist(), 'values': values.tolist(),
                        'text': [tokenizer.decode([i]) for i in ids.tolist()],
                        'top_margin': float(values[0] - values[1])}
    result['max_abs_difference'] = float((left - right).abs().max())
    result['mean_abs_difference'] = float((left - right).abs().mean())
    result['argmax_equal'] = int(left.argmax()) == int(right.argmax())
    result['full_top_in_cached'] = float(right[left.argmax()])
    result['cached_top_in_full'] = float(left[right.argmax()])
    return result


def processed_comparison(model, ids, left, right):
    """Apply the inherited repetition penalty on the actual score dtype/device."""
    device = model.model.get_input_embeddings().weight.device
    processor = RepetitionPenaltyLogitsProcessor(model.model.generation_config.repetition_penalty)
    inputs = torch.tensor([ids], device=device)
    a = processor(inputs, left.to(device).float().unsqueeze(0))[0]
    b = processor(inputs, right.to(device).float().unsqueeze(0))[0]
    return summarize_logits(a, b, model.tokenizer)


def cache_comparison(left, right):
    """Check all layer shapes and errors without retaining extra GPU tensors."""
    rows = []
    for layer, ((lk, lv), (rk, rv)) in enumerate(zip(left, right)):
        record = {'layer': layer}
        for name, a, b in [('key', lk, rk), ('value', lv, rv)]:
            assert a.shape == b.shape, (layer, name, a.shape, b.shape)
            difference = (a.float() - b.to(a.device).float()).abs()
            record[name] = {'shape': list(a.shape), 'max_abs': float(difference.max()),
                            'mean_abs': float(difference.mean())}
        rows.append(record)
    return rows


def forward(model, ids, cache=None):
    """Run an explicit suffix at its exact absolute token positions."""
    device = model.model.get_input_embeddings().weight.device
    start = int(cache.get_seq_length()) if cache is not None else 0
    assert 0 <= start < len(ids)
    inputs = torch.tensor([ids[start:]], dtype=torch.long, device=device)
    with torch.inference_mode():
        result = model.model(input_ids=inputs,
            attention_mask=torch.ones((1, len(ids)), dtype=torch.long, device=device),
            position_ids=torch.arange(start, len(ids), device=device).unsqueeze(0),
            cache_position=torch.arange(start, len(ids), device=device),
            past_key_values=cache, use_cache=True, num_logits_to_keep=1,
            return_dict=True)
    return result.logits[0, -1].detach().float().cpu(), result.past_key_values


async def replay(model, requests):
    """Observe the actual service generation path without changing selected tokens."""
    model.cache_pool = PrefixCachePool()
    base = model.model.get_base_model()
    captures, calls = [], []
    def observe(module, args, kwargs, output):
        if len(captures) < 2:
            captures.append(output.logits[0, -1].detach().float().cpu())
            row = {}
            for key in ('input_ids', 'position_ids', 'cache_position', 'attention_mask'):
                value = kwargs.get(key)
                row[key] = value.detach().cpu().tolist() if value is not None else None
            calls.append(row)
    handle = base.register_forward_hook(observe, with_kwargs=True)
    original_generate = base.generate
    selected_scores = []
    def observed_generate(*args, **kwargs):
        kwargs.update(return_dict_in_generate=True, output_scores=True)
        result = original_generate(*args, **kwargs)
        selected_scores[:] = [v[0].detach().float().cpu() for v in result.scores[:2]]
        return result
    base.generate = observed_generate
    runs, vectors, scores = {}, {}, {}
    stored_prefix_check = None
    try:
        for enabled in (False, True):
            for index, request in enumerate(requests):
                if enabled and index == len(requests) - 1:
                    entry = model.cache_pool.entries['diagnostic']
                    count = int(entry['cache'].get_seq_length())
                    assert entry['ids'] == request['prompt_token_ids'][:count]
                    _, rebuilt = forward(model, entry['ids'], DynamicCache())
                    stored_prefix_check = {'length':count, 'ids_match':True,
                        'layer_differences':cache_comparison(rebuilt,entry['cache'])}
                    del rebuilt
                captures.clear()
                calls.clear()
                rows = [r async for r in model.stream_ids(request['prompt_token_ids'], 64, False,
                    session_id='diagnostic', request_id=f'diagnostic_{enabled}_{index}',use_cache=enabled)]
                errors = [r for r in rows if 'error' in r]
                if errors:
                    raise RuntimeError(errors)
                completion = next(r for r in rows if 'finish_reason' in r)
                runs[f'{enabled}_{index}'] = {'completion': completion, 'forward_calls': list(calls)}
                vectors[f'{enabled}_{index}'] = list(captures)
                scores[f'{enabled}_{index}'] = list(selected_scores)
        target = len(requests) - 1
        compare = [summarize_logits(a,b,model.tokenizer) for a,b in
                   zip(vectors[f'False_{target}'],vectors[f'True_{target}'])]
        return {'requests': runs, 'target_first_steps': compare,
                'stored_prefix_check':stored_prefix_check,
                'target_generation_scores':[summarize_logits(a,b,model.tokenizer) for a,b in
                    zip(scores[f'False_{target}'],scores[f'True_{target}'])],
                'generation_config':model.model.generation_config.to_dict()}
    finally:
        base.generate = original_generate
        handle.remove()
        model.cache_pool = PrefixCachePool()


def compare_forward(model, ids, cuts, forced):
    """Hold token content constant and vary only prefill partitioning."""
    full_logits, full_cache = forward(model, ids, DynamicCache())
    _, chunked = forward(model, ids[:cuts[0]], DynamicCache())
    for end in cuts[1:] + [len(ids)]:
        chunk_logits, chunked = forward(model, ids[:end], chunked)
    assert full_cache.get_seq_length() == chunked.get_seq_length() == len(ids)
    result = {'cuts': cuts, 'prompt_logits': summarize_logits(full_logits, chunk_logits, model.tokenizer),
              'kv_at_prompt': cache_comparison(full_cache, chunked)}
    left, full_cache = forward(model, ids + [forced], full_cache)
    right, chunked = forward(model, ids + [forced], chunked)
    result['forced_next_logits'] = summarize_logits(left, right, model.tokenizer)
    result['forced_next_processed'] = processed_comparison(model,ids+[forced],left,right)
    result['kv_after_forced'] = cache_comparison(full_cache, chunked)
    del full_cache, chunked
    return result


def main():
    """Load frozen inputs and weights, compare BF16 partitions and FP32 control."""
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('checkpoint', 'base-model', 'adaptation', 'trace', 'output'):
        parser.add_argument('--'+name, type=Path, required=True)
    args = parser.parse_args()
    torch.set_num_threads(2)
    torch.backends.cuda.matmul.allow_tf32 = False
    args.output.mkdir(parents=True, exist_ok=False)
    trace = [json.loads(line) for line in args.trace.read_text().splitlines()]
    target = next(r for r in trace if r['request_id'] == '0_0_4_True')
    requests = [r for r in trace if r['session_id'] == target['session_id']][:5]
    assert len(requests) == 5 and len(requests[-1]['prompt_token_ids']) == 150
    (args.output/'inputs.json').write_text(json.dumps(requests, indent=2)+'\n')
    model = OfficialDuplexModel(args.checkpoint, args.base_model, 'cuda:0', args.adaptation)
    base = model.model.get_base_model()
    info = {'torch':torch.__version__, 'model':model.info,
        'input_trace_sha256':hashlib.sha256(args.trace.read_bytes()).hexdigest(),
        'cuda_devices':[torch.cuda.get_device_name(i) for i in range(torch.cuda.device_count())]}
    (args.output/'identity.json').write_text(json.dumps(info, indent=2)+'\n')
    ids = requests[-1]['prompt_token_ids']
    forced = target['token_ids'][0]
    def persist(name, data):
        (args.output/(name+'.json')).write_text(json.dumps(data,indent=2)+'\n')
    persist('service_bf16', asyncio.run(replay(model, requests)))
    cuts = [r['cached_tokens'] for r in requests[1:]]
    assert cuts == sorted(cuts) and cuts[-1] == 140
    result = {'attention_classes':sorted({type(layer.self_attn).__name__ for layer in base.model.layers}),
        'dtype':str(next(model.model.parameters()).dtype)}
    result['single_boundary'] = compare_forward(model, ids, [140], forced)
    result['micro_boundaries'] = compare_forward(model, ids, cuts, forced)
    persist('bf16_original',result)
    from transformers.models.qwen2.modeling_qwen2 import Qwen2Attention
    for layer in base.model.layers:
        layer.self_attn.__class__ = Qwen2Attention
    base.config._attn_implementation = 'eager'
    persist('bf16_eager', {'single_boundary':compare_forward(model,ids,[140],forced),
                          'micro_boundaries':compare_forward(model,ids,cuts,forced)})
    model.model.cpu()
    gc.collect()
    torch.cuda.empty_cache()
    model.model.float()
    # Dispatch whole decoder layers, preserving exact frozen parameter values.
    from accelerate import dispatch_model, infer_auto_device_map
    device_map = infer_auto_device_map(model.model,
        max_memory={0:'20GiB',1:'20GiB'}, no_split_module_classes=['Qwen2DecoderLayer'],
        dtype=torch.float32)
    assert 'cpu' not in device_map.values() and 'disk' not in device_map.values(), device_map
    model.model = dispatch_model(model.model, device_map=device_map)
    persist('fp32_eager', {'device_map':device_map,
        'single_boundary':compare_forward(model,ids,[140],forced),
        'micro_boundaries':compare_forward(model,ids,cuts,forced)})
    persist('completion',{'completed':True,'finished_monotonic':time.monotonic()})


if __name__ == '__main__':
    main()

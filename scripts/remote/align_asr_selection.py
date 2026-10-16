"""Independently force-align reference words for estimated acoustic latency."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np


def ctc_path(log_probs, targets, blank=0):
    """Find a legal CTC path through an expanded fixed target sequence."""
    expanded = np.full(2 * len(targets) + 1, blank, dtype=np.int64)
    expanded[1::2] = targets
    frames, states = len(log_probs), len(expanded)
    scores = np.full(states, -np.inf)
    scores[0] = log_probs[0, blank]
    if states > 1:
        scores[1] = log_probs[0, expanded[1]]
    back = np.zeros((frames, states), dtype=np.uint8)
    can_skip = np.zeros(states, dtype=bool)
    can_skip[2:] = (expanded[2:] != blank) & (expanded[2:] != expanded[:-2])
    for frame in range(1, frames):
        stay = scores
        advance = np.concatenate(([-np.inf], scores[:-1]))
        skip = np.concatenate(([-np.inf, -np.inf], scores[:-2])) if states > 1 else np.array([-np.inf])
        skip = np.where(can_skip, skip, -np.inf)
        options = np.stack((stay, advance, skip))
        choice = options.argmax(axis=0)
        back[frame] = choice
        scores = options[choice, np.arange(states)] + log_probs[frame, expanded]
    state = states - 1
    if states > 1 and scores[-2] > scores[-1]:
        state = states - 2
    if not np.isfinite(scores[state]):
        raise ValueError("No legal CTC alignment")
    path = np.zeros(frames, dtype=np.int64)
    for frame in range(frames - 1, -1, -1):
        path[frame] = state
        state -= int(back[frame, state])
    return path, expanded


def main():
    import soundfile as sf
    import torch
    from transformers import AutoModelForCTC, AutoProcessor
    from whisper_normalizer.english import EnglishTextNormalizer

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    args = parser.parse_args()
    torch.set_num_threads(4)
    manifest = json.loads((args.root / "dataset/manifest.json").read_text())
    model_path = args.root / "models/alignment"
    processor = AutoProcessor.from_pretrained(model_path, local_files_only=True)
    model = AutoModelForCTC.from_pretrained(model_path, local_files_only=True).to("cuda").eval()
    normalize = EnglishTextNormalizer()
    vocabulary = processor.tokenizer.get_vocab()
    alignment = {}
    for row in manifest["samples"]:
        if row["split"] != "test":
            continue
        try:
            audio, rate = sf.read(row["path"], dtype="float32")
            text = normalize(row["reference"])
            # Wav2Vec2 vocabulary contains letters, apostrophe and the word delimiter.
            # Unsupported number spellings remain unaligned instead of inventing timestamps.
            encoded_text = text.upper().replace(" ", "|")
            if any(character not in vocabulary for character in encoded_text):
                raise ValueError("Reference contains characters outside CTC vocabulary")
            targets = [vocabulary[character] for character in encoded_text]
            inputs = processor(audio, sampling_rate=rate, return_tensors="pt")
            with torch.inference_mode():
                probabilities = model(inputs.input_values.to("cuda")).logits.log_softmax(-1)[0].cpu().numpy()
            path, _ = ctc_path(probabilities, targets, model.config.pad_token_id)
            ratio = model.config.inputs_to_logits_ratio / rate
            words, cursor = [], 0
            for word in text.split():
                positions = np.where((path >= 2 * cursor + 1) & (path <= 2 * (cursor + len(word) - 1) + 1) & (path % 2 == 1))[0]
                if not len(positions):
                    raise ValueError("Reference word received no acoustic frames")
                words.append({"word": word, "start": float(positions[0] * ratio),
                              "end": float(min((positions[-1] + 1) * ratio, len(audio) / rate))})
                cursor += len(word) + 1
            label_frames = path % 2 == 1
            label_ids = np.asarray(targets)[(path[label_frames] - 1) // 2]
            quality = float(probabilities[np.where(label_frames)[0], label_ids].mean())
            alignment[row["sample_id"]] = {"words": words, "mean_label_log_probability": quality,
                                            "error": None, "frame_seconds": ratio}
        except Exception as error:
            alignment[row["sample_id"]] = {"words": [], "error": str(error)}
        print(row["sample_id"], alignment[row["sample_id"]].get("error"), flush=True)
    (args.root / "dataset/alignments.json").write_text(json.dumps(
        {"dataset_revision": manifest["revision"], "method": "independent CTC Viterbi, estimated timestamps",
         "samples": alignment}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

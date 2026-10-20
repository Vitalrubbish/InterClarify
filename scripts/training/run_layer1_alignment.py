"""Verify one final delayed-start candidate in a clean model process."""

import argparse
import json
from pathlib import Path

from layer1_candidate import load_candidate
from layer1_data import write_json
from layer1_model import load_official_checkpoint


def verify_candidate(args):
    """Reload the official model, restore the final candidate and reproduce a probe."""
    loaded = load_official_checkpoint(args.checkpoint, args.base_model, training=False)
    report = load_candidate(loaded, args.candidate, args.checkpoint, args.base_model)
    write_json(args.output, report)
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    for key in ('checkpoint', 'base-model', 'candidate', 'output'):
        parser.add_argument('--' + key, type=Path, required=True)
    args = parser.parse_args()
    report = verify_candidate(args)
    print(json.dumps(report), flush=True)

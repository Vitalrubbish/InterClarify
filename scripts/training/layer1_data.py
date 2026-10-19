"""Build deterministic, auditable micro-turn supervision from pinned UltraChat."""

from __future__ import annotations

from collections import Counter
import hashlib
import heapq
import json
import math
from pathlib import Path
import random
import re
import shutil
import sqlite3
import unicodedata

from number_surface import VERSION, normalize_user_text


CONTROLS = {
    'speaking': '<|user is talking|>',
    'finish': '<|user finish talking|>',
    'thinking': '<|user is thinking|>',
    'interruption': '<|user interruption|>',
    'backchannel': '<|user backchannel|>',
}
ARMS = ('T1', 'T2', 'T3')


def spoken_dialogue_texts(texts):
    """Preserve assistant turns while normalizing complete user turns."""
    return [text if i % 2 else normalize_user_text(text)['text'] for i, text in enumerate(texts)]


def canonical(value):
    """Serialize stable records without platform-dependent whitespace."""
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'))


def digest(value):
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def file_digest(path):
    result = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            result.update(block)
    return result.hexdigest()


def write_json(path, value):
    path = Path(path)
    temporary = path.with_suffix(path.suffix + '.part')
    temporary.write_text(canonical(value) + '\n', encoding='utf-8')
    temporary.replace(path)


def read_jsonl(path):
    with Path(path).open(encoding='utf-8') as stream:
        for line in stream:
            yield json.loads(line)


def stable_rng(seed, *parts):
    return random.Random(int(digest([seed, *parts]), 16))


def normalized(text):
    return ' '.join(re.findall(r"\w+", unicodedata.normalize('NFKC', text).casefold()))


def shingles(texts, width):
    words = normalized(' '.join(texts)).split()
    values = [' '.join(words[i:i + width]) for i in range(max(0, len(words) - width + 1))]
    if not values:
        values = [' '.join(words)]
    return sorted({hashlib.sha256(x.encode()).digest()[:16].hex() for x in values})


def similar(left, right, threshold):
    if min(len(left), len(right)) < threshold * max(len(left), len(right)):
        return False
    a = left if isinstance(left, set) else set(left)
    b = right if isinstance(right, set) else set(right)
    return len(a & b) >= threshold * len(a | b)


def punctuation_keep_mask(text, characters):
    """Resolve protection on the full source text before slicing micro-turns."""
    protected = set()
    patterns = (r'<\|[^<>]+\|>', r'\d+(?:[.:]\d+)+')
    for pattern in patterns:
        for match in re.finditer(pattern, text):
            protected.update(range(match.start(), match.end()))
    for i, char in enumerate(text):
        if char in "'’‐‑-" and 0 < i < len(text) - 1:
            if text[i - 1].isalnum() and text[i + 1].isalnum():
                protected.add(i)
    return [i in protected or char not in characters for i, char in enumerate(text)]


def remove_punctuation(text, characters):
    """Remove ordinary punctuation while protecting tokens and numeric formats."""
    return ''.join(char for char, keep in zip(text, punctuation_keep_mask(text, characters)) if keep)


class ReleasedTokenizer:
    """Use the published fast tokenizer without loading model weights."""

    def __init__(self, directory, expected):
        from tokenizers import Tokenizer
        self.directory = Path(directory)
        self.backend = Tokenizer.from_file(str(self.directory / 'tokenizer.json'))
        self.special = dict(expected)
        for marker, token in expected.items():
            if self.encode(marker) != [token] or self.backend.id_to_token(token) != marker:
                raise ValueError(f'Released token mismatch: {marker}')
        metadata = json.loads((self.directory / 'tokenizer_config.json').read_text())
        if metadata.get('bos_token') is not None:
            raise ValueError('Expected the published tokenizer without BOS')
        if metadata.get('eos_token') != '<|im_end|>':
            raise ValueError('Unexpected released EOS')
        self.fingerprint = {p.name: file_digest(p) for p in sorted(self.directory.glob('*.json'))}

    def encode(self, text):
        return self.backend.encode(text, add_special_tokens=False).ids

    def decode(self, ids):
        return self.backend.decode(ids, skip_special_tokens=False)

    def user_chunks(self, text, rng, bounds):
        encoded = self.backend.encode(text, add_special_tokens=False)
        offsets = encoded.offsets
        start, cursor = 0, 0
        while cursor < len(offsets):
            end = min(len(offsets), cursor + rng.randint(*bounds))
            stop = offsets[end - 1][1]
            while end < len(offsets) and offsets[end][0] < stop:
                stop = max(stop, offsets[end][1])
                end += 1
            if end == len(offsets):
                stop = len(text)
            yield {'text': text[start:stop], 'start': start, 'end': stop,
                   'base_tokens': end - cursor}
            cursor, start = end, stop


def verify_sources(manifest_path, source_dir, download_path, expected):
    """Rehash every pinned shard; a download completion flag alone is insufficient."""
    source = json.loads(Path(manifest_path).read_text())
    for key, value in expected.items():
        if source.get(key) != value:
            raise ValueError(f'Source identity mismatch: {key}')
    download = json.loads(Path(download_path).read_text())
    if not download.get('complete') or download.get('source_manifest_sha256') != file_digest(manifest_path):
        raise ValueError('Incomplete or unrelated download manifest')
    if any(download.get(key) != value for key, value in expected.items()):
        raise ValueError('Download identity mismatch')
    paths = []
    for row in source['files']:
        if Path(row['path']).name != row['path']:
            raise ValueError('Source shard must be a top-level filename')
        path = Path(source_dir) / row['path']
        if path.stat().st_size != row['size'] or file_digest(path) != row['lfs']['oid']:
            raise ValueError(f'Unverified source: {path}')
        paths.append(path)
    if {p.name for p in paths} != {Path(r['path']).name for r in download['files']}:
        raise ValueError('Download shard coverage mismatch')
    return paths


def source_records(paths, seed, budget=None):
    """Read a bounded set of whole-line windows, retaining original byte locations."""
    ordered = sorted(paths, key=lambda p: p.name)
    if budget is not None:
        stable_rng(seed, 'source_shards').shuffle(ordered)
    for index, path in enumerate(ordered):
        quota = None if budget is None else budget // len(ordered) + (index < budget % len(ordered))
        if quota == 0:
            continue
        size = path.stat().st_size
        if size == 0:
            continue
        with path.open('rb') as stream:
            if budget is not None:
                start = stable_rng(seed, 'source_window', path.name).randrange(size)
                if start:
                    stream.seek(start - 1)
                    if stream.read(1) != b'\n':
                        stream.readline()
            seen, number = set(), 0
            while quota is None or number < quota:
                offset = stream.tell()
                raw = stream.readline()
                if not raw:
                    if quota is None:
                        break
                    stream.seek(0)
                    continue
                if quota is not None and offset in seen:
                    break
                if quota is not None:
                    seen.add(offset)
                number += 1
                yield path, number if budget is None else None, raw, offset


class DialogueIndex:
    """Keep full-source filtering and duplicate groups in a disk-backed index."""

    def __init__(self, path, config):
        self.path, self.config = Path(path), config
        self.db = sqlite3.connect(self.path)
        self.db.executescript('''
            PRAGMA journal_mode=DELETE;
            PRAGMA cache_size=-32768;
            PRAGMA temp_store=FILE;
            PRAGMA mmap_size=0;
            CREATE TABLE IF NOT EXISTS dialogues (
                id TEXT PRIMARY KEY, payload TEXT NOT NULL, fingerprint TEXT NOT NULL,
                shingles TEXT NOT NULL, parent TEXT NOT NULL, rank TEXT NOT NULL);
            CREATE INDEX IF NOT EXISTS by_fingerprint ON dialogues(fingerprint);
            CREATE TABLE IF NOT EXISTS prefixes (shingle TEXT, id TEXT);
            CREATE INDEX IF NOT EXISTS by_shingle ON prefixes(shingle);
            CREATE TABLE IF NOT EXISTS surface_grams (id TEXT PRIMARY KEY, shingles TEXT);
            CREATE TABLE IF NOT EXISTS surface_prefixes (shingle TEXT, id TEXT);
            CREATE INDEX IF NOT EXISTS surface_by_shingle ON surface_prefixes(shingle);
            CREATE TABLE IF NOT EXISTS excluded (shard TEXT, line INTEGER, id TEXT, reason TEXT, byte_offset INTEGER);
            CREATE TABLE IF NOT EXISTS source_inventory (id TEXT PRIMARY KEY, shard TEXT, line INTEGER, byte_offset INTEGER);
        ''')

    def close(self):
        self.db.close()

    def check_resources(self):
        limits = self.config['limits']
        usage = sum(p.stat().st_size for p in self.path.parent.rglob('*') if p.is_file())
        if usage > limits['max_disk_gib'] * 1024**3:
            raise RuntimeError('Dataset disk budget exceeded')
        if shutil.disk_usage(self.path.parent).free < limits['min_free_gib'] * 1024**3:
            raise RuntimeError('Insufficient dataset disk reserve')

    def root(self, value):
        trail = []
        while True:
            parent = self.db.execute('SELECT parent FROM dialogues WHERE id=?', (value,)).fetchone()[0]
            if parent == value:
                break
            trail.append(value)
            value = parent
        self.db.executemany('UPDATE dialogues SET parent=? WHERE id=?', [(value, x) for x in trail])
        return value

    def union(self, left, right):
        a, b = self.root(left), self.root(right)
        if a != b:
            small, large = sorted((a, b))
            self.db.execute('UPDATE dialogues SET parent=? WHERE id=?', (small, large))

    def rejection(self, row):
        if not isinstance(row, dict) or not isinstance(row.get('id'), (str, int)):
            return 'invalid_id'
        texts = row.get('data')
        if not isinstance(texts, list) or len(texts) < 2 or len(texts) % 2:
            return 'invalid_alternating_turns'
        if any(not isinstance(x, str) or not x.strip() for x in texts):
            return 'empty_or_invalid_turn'
        joined = '\n'.join(texts)
        try:
            joined.encode('utf-8')
        except UnicodeError:
            return 'invalid_unicode'
        if '<|' in joined or '|>' in joined or '\ufffd' in joined:
            return 'reserved_marker_or_encoding'
        rule = self.config['filter']
        try:
            for text in texts[::2]:
                normalize_user_text(text)
        except ValueError:
            return 'unsupported_or_ambiguous_numeric_surface'
        if any(not remove_punctuation(text, self.config['views']['remove_characters']).strip()
               for text in texts[::2]):
            return 'empty_user_after_punctuation_removal'
        if not rule['min_chars'] <= len(joined) <= rule['max_chars']:
            return 'length'
        letters = [x for x in joined if x.isalpha()]
        if not letters or sum(x.isascii() for x in letters) / len(letters) < rule['min_ascii_letter_fraction']:
            return 'language_heuristic'
        return None

    def ingest(self, paths, exclusions):
        """Group before selecting splits; exact prefix filtering retains near-pair recall."""
        excluded_ids = set(exclusions['ids'])
        excluded_texts = set(exclusions['normalized_hashes'])
        limit = self.config.get('sampling', {}).get('candidate_pool_dialogues')
        raw_budget = self.config.get('sampling', {}).get('raw_source_dialogues')
        candidates = []
        eligible_count, total_lines = 0, 0
        for path, number, raw, offset in source_records(paths, self.config['seed'], raw_budget):
            total_lines += 1
            try:
                row = json.loads(raw)
            except (ValueError, UnicodeError):
                row = None
            reason = self.rejection(row)
            identity = str(row['id']) if isinstance(row, dict) and 'id' in row else ''
            if not reason:
                fingerprint = digest(normalized('\n'.join(row['data'])))
                text_hashes = {fingerprint, *(digest(normalized(t)) for t in row['data'])}
                spoken = spoken_dialogue_texts(row['data'])
                text_hashes.update(digest(normalized(t)) for t in spoken)
                text_hashes.add(digest(normalized('\n'.join(spoken))))
                if identity in excluded_ids or text_hashes.intersection(excluded_texts):
                    reason = 'external_exclusion'
            if reason:
                self.db.execute('INSERT INTO excluded VALUES (?,?,?,?,?)', (path.name, number, identity, reason, offset))
            else:
                try:
                    self.db.execute('INSERT INTO source_inventory VALUES (?,?,?,?)', (identity, path.name, number, offset))
                except sqlite3.IntegrityError as error:
                    raise ValueError(f'Duplicate sampled dialogue ID: {identity}') from error
                eligible_count += 1
                payload = {'dialogue_id': identity, 'texts': row['data'], 'shard': path.name,
                           'line': number, 'byte_offset': offset, 'raw_sha256': hashlib.sha256(raw).hexdigest(),
                           'normalized_sha256': fingerprint, 'source_type': 'synthetic_ultrachat'}
                if limit is None:
                    self.index_candidate(payload)
                else:
                    item = (-int(digest([self.config['seed'], identity]), 16), identity, payload)
                    if len(candidates) < limit:
                        heapq.heappush(candidates, item)
                    elif item[:2] > candidates[0][:2]:
                        heapq.heapreplace(candidates, item)
            if total_lines % 1000 == 0:
                self.db.commit()
                self.check_resources()
                print(canonical({'stage': 'sample_filter' if raw_budget is not None else 'source_scan',
                                 'shard': path.name, 'source_dialogues_read': total_lines,
                                 'eligible': eligible_count, 'candidate_pool': len(candidates) if limit else eligible_count}), flush=True)
        self.db.commit()
        self.check_resources()
        if limit is not None:
            for number, (_, identity, payload) in enumerate(sorted(candidates, key=lambda x: (-x[0], x[1])), 1):
                self.index_candidate(payload)
                if number % 1000 == 0:
                    self.db.commit()
                    self.check_resources()
                    print(canonical({'stage': 'candidate_dedup', 'indexed': number, 'candidate_pool': len(candidates)}), flush=True)
        self.db.commit()
        self.scan_summary = {'source_lines': total_lines, 'eligible_source_dialogues': eligible_count,
                             'raw_source_dialogue_budget': raw_budget, 'full_source_filtering': raw_budget is None,
                             'candidate_pool_requested': limit, 'candidate_dialogues': len(candidates) if limit else eligible_count,
                             'selection': 'seeded_shard_byte_windows_then_stable_hash' if raw_budget else 'lowest_stable_seed_dialogue_id_hash',
                             'near_duplicate_scope': 'candidate_pool_before_split'}

    def index_candidate(self, payload):
        """Build duplicate groups only among dialogues eligible for the frozen split."""
        threshold = self.config['dedup']['jaccard_threshold']
        identity, fingerprint = payload['dialogue_id'], payload['normalized_sha256']
        grams = shingles(payload['texts'], self.config['dedup']['word_ngram'])
        self.db.execute('INSERT INTO dialogues VALUES (?,?,?,?,?,?)',
                        (identity, canonical(payload), fingerprint, canonical(grams), identity,
                         digest([self.config['seed'], identity])))
        for (other,) in self.db.execute('SELECT id FROM dialogues WHERE fingerprint=? AND id<>?', (fingerprint, identity)).fetchall():
            self.union(identity, other)
        prefix = grams[:len(grams) - math.ceil(threshold * len(grams)) + 1]
        self.db.execute('CREATE TEMP TABLE IF NOT EXISTS candidates(id TEXT PRIMARY KEY)')
        self.db.execute('DELETE FROM candidates')
        for gram in prefix:
            self.db.execute('INSERT OR IGNORE INTO candidates SELECT id FROM prefixes WHERE shingle=?', (gram,))
        for other, serialized in self.db.execute('SELECT d.id,d.shingles FROM dialogues d JOIN candidates c ON d.id=c.id'):
            if similar(grams, json.loads(serialized), threshold):
                self.union(identity, other)
        self.db.executemany('INSERT INTO prefixes VALUES (?,?)', [(x, identity) for x in prefix])
        surface = shingles(spoken_dialogue_texts(payload['texts']), self.config['dedup']['word_ngram'])
        prefix = surface[:len(surface) - math.ceil(threshold * len(surface)) + 1]
        self.db.execute('DELETE FROM candidates')
        for gram in prefix:
            self.db.execute('INSERT OR IGNORE INTO candidates SELECT id FROM surface_prefixes WHERE shingle=?', (gram,))
        for other, serialized in self.db.execute('SELECT d.id,d.shingles FROM surface_grams d JOIN candidates c ON d.id=c.id'):
            if similar(surface, json.loads(serialized), threshold):
                self.union(identity, other)
        self.db.execute('INSERT INTO surface_grams VALUES (?,?)', (identity, canonical(surface)))
        self.db.executemany('INSERT INTO surface_prefixes VALUES (?,?)', [(x, identity) for x in prefix])

    def select(self):
        """Choose one representative per group, with deterministic replacement order."""
        remaining = dict(self.config['splits'])
        if remaining['train'] % 2:
            raise ValueError('Balanced training requires an even dialogue count')
        selected, seen = [], set()
        for identity, payload in self.db.execute('SELECT id,payload FROM dialogues ORDER BY rank,id'):
            group = self.root(identity)
            if group in seen:
                continue
            split = next((name for name in ('train', 'dev', 'test') if remaining[name]), None)
            if split is None:
                break
            seen.add(group)
            row = json.loads(payload)
            row.update(split=split, duplicate_group=group)
            selected.append(row)
            remaining[split] -= 1
        if any(remaining.values()):
            raise ValueError(f'Insufficient eligible independent groups: {remaining}')
        return selected


class MicroTurnPlanner:
    """Freeze a base event plan before applying any punctuation view."""

    def __init__(self, tokenizer, config):
        self.tokenizer, self.config = tokenizer, config

    def user_chunks(self, text, rng, bounds):
        """Join punctuation-only spans before assigning shared event boundaries."""
        characters = self.config['views']['remove_characters']
        chunks, leading, merges = [], None, 0
        for raw in self.tokenizer.user_chunks(text, rng, bounds):
            chunk = dict(raw)
            if not remove_punctuation(chunk['text'], characters).strip():
                merges += 1
                if chunks:
                    previous = chunks[-1]
                    previous['text'] += chunk['text']
                    previous['end'] = chunk['end']
                    previous['base_tokens'] += chunk['base_tokens']
                elif leading is None:
                    leading = chunk
                else:
                    leading['text'] += chunk['text']
                    leading['end'] = chunk['end']
                    leading['base_tokens'] += chunk['base_tokens']
                continue
            if leading is not None:
                chunk['text'] = leading['text'] + chunk['text']
                chunk['start'] = leading['start']
                chunk['base_tokens'] += leading['base_tokens']
                leading = None
            chunks.append(chunk)
        if leading is not None or not chunks:
            raise ValueError('User turn is empty after punctuation removal')
        return chunks, merges

    def plan(self, dialogue, epoch):
        cfg = self.config['generation']
        rng = stable_rng(self.config['seed'], dialogue['dialogue_id'], epoch, 'events')
        texts, events = list(dialogue['texts']), []
        user_turns = {str(i): normalize_user_text(texts[i]) for i in range(0, len(texts), 2)}
        for i in range(0, len(texts), 2):
            texts[i] = user_turns[str(i)]['text']
        masks = {i: punctuation_keep_mask(texts[i], self.config['views']['remove_characters'])
                 for i in range(0, len(texts), 2)}
        sampling = Counter()

        def emit(kind, user='', control=None, content=None, origin=None):
            if origin:
                source = texts[origin['turn']]
                keep = masks[origin['turn']]
                transformed = ''.join(source[i] for i in range(origin['start'], origin['end']) if keep[i])
            else:
                transformed = remove_punctuation(user, self.config['views']['remove_characters'])
            events.append({'event_id': len(events), 'kind': kind, 'user_text': user,
                           'user_unpunctuated': transformed,
                           'control': control, 'assistant_ids': content or [], 'user_origin': origin,
                           'synthetic_window': len(events)})

        turn, interrupting = 0, False
        while turn < len(texts):
            chunks, merges = self.user_chunks(texts[turn], rng, cfg['user_tokens'])
            sampling['punctuation_boundary_merges'] += merges
            sampling['user_chunks_over_seven_tokens'] += sum(
                chunk['base_tokens'] > cfg['user_tokens'][1] for chunk in chunks)
            for i, chunk in enumerate(chunks):
                origin = {'turn': turn, 'start': chunk['start'], 'end': chunk['end'],
                          'base_tokens': chunk['base_tokens']}
                last = i == len(chunks) - 1
                if interrupting and i == 0:
                    emit('interruption', chunk['text'], 'interruption', origin=origin)
                elif not last:
                    emit('user_continuation', chunk['text'], 'speaking', origin=origin)
                if not last:
                    sampling['pause_eligible_boundaries'] += 1
                    if rng.random() < cfg['pause_probability']:
                        sampling['pause_triggers'] += 1
                        for _ in range(rng.randint(*cfg['pause_windows'])):
                            emit('natural_pause', control='speaking')
                if last:
                    if interrupting and i == 0:
                        response_user, response_origin = '', None
                    else:
                        response_user, response_origin = chunk['text'], origin
            answer = self.tokenizer.encode(texts[turn + 1])
            pieces = [answer[i:i + cfg['assistant_tokens']] for i in range(0, len(answer), cfg['assistant_tokens'])]
            if not pieces:
                raise ValueError('Assistant turn encodes to zero content tokens')
            cut = None
            if turn + 2 < len(texts) and len(pieces) > 1:
                sampling['interruption_eligible_long_turns'] += 1
                if rng.random() < cfg['interruption_probability']:
                    cut = rng.randint(1, len(pieces) - 1)
                    sampling['interruption_triggers'] += 1
            for i, piece in enumerate(pieces):
                if i == 0:
                    emit('response_start', response_user, 'finish', piece, response_origin)
                else:
                    sampling['backchannel_eligible_continuations'] += 1
                    if rng.random() < cfg['backchannel_probability']:
                        sampling['backchannel_triggers'] += 1
                        emit('user_backchannel', rng.choice(cfg['backchannels']), 'backchannel', piece)
                    else:
                        emit('response_continuation', content=piece)
                if cut == i + 1:
                    break
            interrupting = cut is not None
            if not interrupting:
                for _ in range(rng.randint(*cfg['thinking_windows'])):
                    emit('post_response_thinking', control='thinking')
            turn += 2
        return {'dialogue_id': dialogue['dialogue_id'], 'epoch': epoch, 'events': events,
                'user_turns': user_turns,
                'source_type': 'synthetic_ultrachat', 'clock_type': 'synthetic_window_only',
                'sampling': dict(sampling)}


def mixed_assignments(dialogues, seed, epoch):
    result = {}
    for split in ('train', 'dev', 'test'):
        identities = sorted(x['dialogue_id'] for x in dialogues if x['split'] == split)
        stable_rng(seed, epoch if split == 'train' else 0, split, 'views').shuffle(identities)
        for i, identity in enumerate(identities):
            result[identity] = 'original' if i < len(identities) // 2 else 'unpunctuated'
    return result


class SequenceEncoder:
    """Emit legal whole-event windows, masking repeated historical context."""

    def __init__(self, tokenizer, config, max_length):
        self.tokenizer, self.config, self.max_length = tokenizer, config, max_length
        self.user_header = tokenizer.encode('<|im_start|>user\n')
        self.assistant_header = tokenizer.encode('<|im_start|>assistant\n')
        self.user_end = tokenizer.encode('<|im_end|>\n')
        self.eos = config['token_ids']['<|im_end|>']

    def event_ids(self, event, view):
        text = event['user_text']
        if view == 'unpunctuated':
            text = event['user_unpunctuated']
        if event['user_origin'] and not text.strip():
            raise ValueError('A sourced user micro-turn became no-voice')
        user = self.tokenizer.encode(text.strip()) if text.strip() else [self.config['token_ids']['<|no voice|>']]
        prefix = self.user_header + user + self.user_end + self.assistant_header
        target = []
        if event['control']:
            target.append(self.config['token_ids'][CONTROLS[event['control']]])
        target += event['assistant_ids'] + [self.eos]
        return prefix, target

    def encode(self, plan, split, arm, view):
        events = plan['events']
        blocks = [self.event_ids(event, view) for event in events]
        lengths = []
        for event in events:
            lengths.append(max(sum(map(len, self.event_ids(event, v))) for v in ('original', 'unpunctuated')))
        if any(n > self.max_length for n in lengths):
            raise ValueError('A complete micro-turn exceeds the configured maximum length')
        cursor, index = 0, 0
        while cursor < len(events):
            first, total = cursor, 0
            target_budget = self.max_length if first == 0 else max(self.max_length // 2, lengths[first])
            while cursor < len(events) and total + lengths[cursor] <= target_budget:
                total += lengths[cursor]
                cursor += 1
            start = first
            while start > 0 and total + lengths[start - 1] <= self.max_length:
                start -= 1
                total += lengths[start]
            ids, labels, spans = [], [], []
            for pos in range(start, cursor):
                prefix, target = blocks[pos]
                offset = len(ids)
                ids += prefix + target
                labels += [-100] * len(prefix) + (target if pos >= first else [-100] * len(target))
                spans.append({'event_id': pos, 'start': offset, 'target_start': offset + len(prefix),
                              'end': len(ids), 'supervised': pos >= first})
            yield {'sequence_id': f'{plan["dialogue_id"]}:{plan["epoch"]}:{arm}:{index}',
                   'dialogue_id': plan['dialogue_id'], 'epoch': plan['epoch'], 'split': split,
                   'arm': arm, 'view': view, 'event_plan_sha256': digest(plan),
                   'input_ids': ids, 'labels': labels, 'attention_mask': [1] * len(ids),
                   'spans': spans, 'effective_tokens': sum(x != -100 for x in labels)}
            index += 1


def validate_config(config):
    """Reject unsupported settings instead of silently changing an experiment."""
    if config['schema_version'] != 1 or config['generation']['system_backchannel']:
        raise ValueError('Only schema 1 without system backchannels is supported')
    if config['generation'].get('user_surface') != VERSION:
        raise ValueError('Unsupported user text surface version')
    if set(config['splits']) != {'train', 'dev', 'test'} or any(
            type(n) is not int or n < 0 for n in config['splits'].values()):
        raise ValueError('Invalid split sizes')
    if config['views']['original_fraction'] != 0.5 or config['splits']['train'] % 2:
        raise ValueError('T3 requires balanced 50/50 dialogue assignment')
    if not 0 < config['dedup']['jaccard_threshold'] <= 1 or config['dedup']['word_ngram'] < 1:
        raise ValueError('Invalid deduplication rule')
    for name in ('pause', 'interruption', 'backchannel'):
        if not 0 <= config['generation'][name + '_probability'] <= 1:
            raise ValueError(f'Invalid {name} probability')
    for name in ('user_tokens', 'pause_windows', 'thinking_windows'):
        low, high = config['generation'][name]
        if not 1 <= low <= high:
            raise ValueError(f'Invalid {name} bounds')
    if config['generation']['assistant_tokens'] < 1:
        raise ValueError('Invalid assistant chunk length')
    pool = config.get('sampling', {}).get('candidate_pool_dialogues')
    if pool is not None and (type(pool) is not int or pool < sum(config['splits'].values())):
        raise ValueError('Candidate pool must cover all requested split dialogues')
    raw_budget = config.get('sampling', {}).get('raw_source_dialogues')
    if raw_budget is not None and (type(raw_budget) is not int or raw_budget < sum(config['splits'].values())):
        raise ValueError('Raw sampling budget must cover all requested split dialogues')
    if not config['generation']['backchannels'] or any(
            not isinstance(x, str) or not x.strip() or '<|' in x for x in config['generation']['backchannels']):
        raise ValueError('Backchannel inventory must contain plain nonempty strings')
    rule, limits = config['filter'], config['limits']
    if not 0 < rule['min_chars'] <= rule['max_chars'] or not 0 <= rule['min_ascii_letter_fraction'] <= 1:
        raise ValueError('Invalid filtering limits')
    if limits['max_disk_gib'] <= 0 or limits['min_free_gib'] < 0 or limits['max_sequences_per_dialogue'] < 1:
        raise ValueError('Invalid resource limits')

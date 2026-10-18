#!/usr/bin/env python3
"""Collect completed TTS evidence and build a small anonymous listening package."""
import argparse
import csv
import hashlib
import html
import json
from pathlib import Path
import random
import shutil
import zipfile


def collect(args):
    args.output.mkdir(parents=True, exist_ok=False)
    for candidate in args.candidate:
        name, value = candidate.split('=', 1)
        source = Path(value).resolve()
        measurements = source/'measurements'
        rows = [json.loads(p.read_text()) for p in measurements.glob('measured_*.json')]
        wrapper_exit = source.joinpath('exit_code.txt').read_text().strip()
        summary = json.loads((measurements/'summary.json').read_text())
        valid = len(rows) == 60 and not any(r['error'] for r in rows)
        valid = valid and summary['attempted'] == 60 and summary['successful'] == 60
        valid = valid and all(r['chunks'] and r['audio_seconds'] > 0 for r in rows)
        for row in rows:
            chunks=row['chunks']
            valid = valid and all(c['samples'] > 0 and c['arrival_seconds'] >= 0 for c in chunks)
            valid = valid and all(a['arrival_seconds'] <= b['arrival_seconds'] for a,b in zip(chunks,chunks[1:]))
            valid = valid and abs(sum(c['samples'] for c in chunks)/row['sample_rate']-row['audio_seconds']) < 1e-6
        if not valid or (wrapper_exit != '0' and name not in args.accept_wrapper_failure):
            raise ValueError(f'Candidate {name} is incomplete or its wrapper failed')
        destination = args.output/name
        destination.mkdir()
        for pattern in ['*.json', '*.txt', '*.sha256', '*_source.py']:
            for path in source.glob(pattern):
                shutil.copy2(path, destination/path.name)
        shutil.copy2(source/'client.log', destination/'client.txt')
        for path in measurements.glob('*.json'):
            shutil.copy2(path, destination/path.name)
        shutil.copy2(measurements/'corpus_sha256.txt', destination/'corpus_sha256.txt')
        listening = destination/'audio'
        listening.mkdir()
        for row in rows:
            if row['listening'] == 'yes':
                shutil.copy2(measurements/f'measured_{row["id"]}.wav', listening/f'{row["id"]}.wav')
        (destination/'remote_source.txt').write_text(str(source))
    hashes = {p.read_text() for p in args.output.glob('*/corpus_sha256.txt')}
    if len(hashes) != 1:
        raise ValueError('Candidates used different input texts')


def build(args):
    args.listening.mkdir(parents=True, exist_ok=False)
    candidates = sorted(p for p in args.output.iterdir() if p.is_dir() and (p/'summary.json').exists())
    names = [p.name for p in candidates]
    if len({(p/'corpus_sha256.txt').read_text() for p in candidates}) != 1:
        raise ValueError('Candidates used different input texts')
    shuffled = names.copy()
    random.Random(20261018).shuffle(shuffled)
    labels = {name: chr(65+i) for i,name in enumerate(shuffled)}
    (args.output/'model_key.json').write_text(json.dumps(labels, indent=2))
    report = ['# 英文 TTS 远端流式测试报告', '',
              '每模型 60 条相同文本；另有首次请求及 3 条预热，均不计入正式分位数。时间单位为毫秒，RTF 为生成墙钟/音频时长（越小越好）。', '',
              '首可听代理：10ms RMS、连续 30ms 超过 -45dBFS，映射到保留到达等待的模拟播放时钟。不是声卡实测或首个可理解单词；自然度待用户试听。传输完成只表示结束协议正常且返回非空音频，不证明文本读全或音质合格。', '',
              '| 系统 | 传输完成/尝试 | 首包 p50/p95 | 首可听代理 p50/p95 | RTF p50 | 累计断流秒 |',
              '| --- | --- | --- | --- | --- | --- |']
    details, notices = [], []
    score_rows, audio_hashes = [], {}
    texts = {}
    for directory in candidates:
        name = directory.name
        summary = json.loads((directory/'summary.json').read_text())
        rows = [json.loads(p.read_text()) for p in directory.glob('measured_*.json')]
        group = summary['all']
        def pair(metric):
            q = group[metric]
            return f'{q["p50"]*1000:.0f}/{q["p95"]*1000:.0f}' if q['n'] else '缺失'
        stalls = sum(r.get('stall_seconds', 0) for r in rows)
        report.append(f'| {name} | {summary["successful"]}/{summary["attempted"]} | {pair("first_packet_seconds")} | {pair("audible_db45_seconds")} | {group["rtf"].get("p50", float("nan")):.3f} | {stalls:.3f} |')
        wrapper_exit=(directory/'exit_code.txt').read_text().strip()
        if wrapper_exit != '0':
            notices.append(f'{name}：60 条测量完整，但包装作业退出 {wrapper_exit}；详见执行说明，不将该作业记为通过。')
        details += [f'## {name}', '', f'远端证据目录：`{(directory/"remote_source.txt").read_text()}`。', '',
                    '| 类别 | 首包 p50/p95 | 首可听代理 p50/p95 |', '| --- | --- | --- |']
        for category in ('clarification', 'confirmation', 'answer'):
            g=summary[category]
            def fmt(m):
                q=g[m]
                return f'{q["p50"]*1000:.0f}/{q["p95"]*1000:.0f}' if q['n'] else '缺失'
            details.append(f'| {category} | {fmt("first_packet_seconds")} | {fmt("audible_db45_seconds")} |')
        rate = rows[0]['sample_rate']
        q = group['first_packet_samples']
        details += ['', f'首块时长 p50/p95：{q["p50"]/rate*1000:.0f}/{q["p95"]/rate*1000:.0f}ms；采样率 {rate}Hz。', '', '| 阈值 | 首非静音代理 p50/p95 | 有效样本 |', '| --- | --- | --- |']
        for db in (50,45,40):
            q=group[f'audible_db{db}_seconds']
            details.append(f'| -{db}dBFS | {pair(f"audible_db{db}_seconds")} | {q["n"]}/60 |')
        details += ['', '首次请求与预热（秒）：', '']
        for phase in ('cold', 'warmup'):
            for file in sorted(directory.glob(f'{phase}_*.json')):
                r=json.loads(file.read_text())
                details.append(f'- {phase} {r["id"]}：首包 {r.get("first_packet_seconds"):.3f}，首非静音代理 {r.get("audible_db45_seconds"):.3f}。')
        details.append('')
        for row in rows:
            if row['listening'] != 'yes':
                continue
            texts[row['id']] = row['text']
            filename = f'{row["id"]}_{labels[name]}.wav'
            source=directory/'audio'/f'{row["id"]}.wav'
            target=args.listening/filename
            shutil.copy2(source,target)
            audio_hashes[filename]=hashlib.sha256(target.read_bytes()).hexdigest()
            score_rows.append([row['id'], labels[name], row['text'], '', '', '', '', ''])
    report += ['', 'CPU 与 GPU、帧级音频流与分段合成须结合调研及环境清单解释，不能把该表当作同算力模型排名。每类只有 20 条，尾部分位数不构成服务 SLA。', ''] + notices + [''] + details
    (args.output/'report.md').write_text('\n'.join(report))
    page=['<!doctype html><html lang="zh"><meta charset="utf-8"><title>英文语音试听</title>',
          '<style>body{font:17px system-ui;max-width:1000px;margin:40px auto;padding:16px}article{border-top:1px solid #ddd;padding:20px 0}audio{width:90%;max-width:600px}label{display:block;margin:12px}</style>',
          '<h1>英文语音对比</h1><p>6 段相同英文文本，各有匿名语音。请评自然度与清晰度（1–5），并记下错读、吞字或开头异常。保留原始音量和开头静音，建议使用耳机。此页播放合并后的原始音频；流式到达造成的断流另见报告。</p>',
          '<p><a href="scores.csv" download>下载评分表</a></p>']
    for text_id,text in sorted(texts.items()):
        page += [f'<article><p>{html.escape(text_id)}</p><p>{html.escape(text)}</p>']
        for label in sorted(labels.values()):
            page.append(f'<label>语音 {label}<br><audio controls preload="none" src="{text_id}_{label}.wav"></audio></label>')
        page.append('</article>')
    page.append('</html>')
    (args.listening/'index.html').write_text('\n'.join(page))
    with (args.listening/'scores.csv').open('w',newline='') as handle:
        writer=csv.writer(handle)
        writer.writerow(['text_id','voice','text','naturalness_1_5','clarity_1_5','pronunciation_correct','onset_issue','notes'])
        writer.writerows(sorted(score_rows))
    (args.listening/'audio_sha256.json').write_text(json.dumps(audio_hashes,indent=2))
    archive=args.listening.parent/'tts_listening.zip'
    with zipfile.ZipFile(archive,'w',zipfile.ZIP_DEFLATED) as bundle:
        for path in sorted(args.listening.iterdir()):
            bundle.write(path, f'listening/{path.name}')
    print(json.dumps({'candidates':names,'texts':len(texts),'audio_files':len(audio_hashes),'zip':str(archive)}))


def main():
    parser=argparse.ArgumentParser(__doc__)
    parser.add_argument('command',choices=['collect','build'])
    parser.add_argument('--candidate',action='append',default=[])
    parser.add_argument('--accept-wrapper-failure',action='append',default=[])
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--listening',type=Path)
    args=parser.parse_args()
    collect(args) if args.command=='collect' else build(args)


if __name__=='__main__':
    main()

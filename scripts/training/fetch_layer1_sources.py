"""Download the pinned UltraChat source shards and verify published LFS hashes."""
import argparse
import hashlib
import json
from pathlib import Path
import time

import requests


def fetch(url, path, size, expected, attempts=4, retry_delay=5):
    """Accept a shard only after verifying its complete bytes and SHA256."""
    if path.exists():
        digest=hashlib.sha256()
        with path.open('rb') as stream:
            for block in iter(lambda:stream.read(1024*1024),b''):digest.update(block)
        if path.stat().st_size!=size or digest.hexdigest()!=expected:
            raise ValueError(f'Existing shard differs from frozen source: {path}')
        return digest.hexdigest()
    temporary=path.with_suffix(path.suffix+'.part')
    if attempts < 1 or retry_delay < 0:
        raise ValueError('Invalid download retry policy')
    for attempt in range(attempts):
        digest=hashlib.sha256()
        length=0
        if temporary.exists():
            with temporary.open('rb') as stream:
                for block in iter(lambda:stream.read(1024*1024),b''):
                    digest.update(block);length+=len(block)
        if length > size:
            raise ValueError(f'Partial shard exceeds frozen size: {temporary}')
        try:
            if length < size:
                headers={'Range':f'bytes={length}-'} if length else {}
                with requests.get(url,headers=headers,stream=True,timeout=(30,120)) as response:
                    response.raise_for_status()
                    if response.status_code == 206:
                        expected_range=f'bytes {length}-{size-1}/{size}'
                        if response.headers.get('Content-Range') != expected_range:
                            raise ValueError(f'Unexpected response range: {response.headers.get("Content-Range")}')
                    elif response.status_code == 200:
                        length=0
                        digest=hashlib.sha256()
                    else:
                        raise ValueError(f'Unexpected source status: {response.status_code}')
                    with temporary.open('ab' if length else 'wb') as output:
                        for block in response.iter_content(1024*1024):
                            if length+len(block)>size:
                                raise ValueError('Response exceeds frozen source size')
                            output.write(block);digest.update(block);length+=len(block)
            if length < size:
                raise requests.exceptions.ChunkedEncodingError('Source ended before frozen size')
        except requests.RequestException:
            if attempt+1 == attempts:
                raise
            time.sleep(retry_delay)
            continue
        if length!=size or digest.hexdigest()!=expected:
            raise ValueError(f'Downloaded shard failed size/SHA256: {path}')
        temporary.rename(path)
        return digest.hexdigest()


def main(args):
    """Persist a resumable verified source inventory, without claiming data audit."""
    source=json.loads(args.manifest.read_text())
    args.output.mkdir(parents=True,exist_ok=True)
    result={'dataset':source['dataset'],'revision':source['revision'],'split':source['split'],
            'source_manifest_sha256':hashlib.sha256(args.manifest.read_bytes()).hexdigest(),
            'files':[],'complete':False,'training_allowed':False}
    (args.output/'download_manifest.json').write_text(json.dumps(result,indent=2))
    for row in source['files']:
        name=row['path']
        if Path(name).name!=name:raise ValueError('Only frozen top-level shards are supported')
        url=f"{args.endpoint.rstrip('/')}/datasets/{source['dataset']}/resolve/{source['revision']}/{name}"
        digest=fetch(url,args.output/name,row['size'],row['lfs']['oid'],args.attempts,args.retry_delay)
        result['files'].append({'path':str(args.output/name),'url':url,'bytes':row['size'],'sha256':digest})
        (args.output/'download_manifest.json').write_text(json.dumps(result,indent=2))
        print(json.dumps({'verified':name,'sha256':digest}),flush=True)
    result['complete']=True
    (args.output/'download_manifest.json').write_text(json.dumps(result,indent=2))


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--manifest',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--endpoint',default='https://huggingface.co')
    parser.add_argument('--attempts',type=int,default=4)
    parser.add_argument('--retry-delay',type=float,default=5)
    main(parser.parse_args())

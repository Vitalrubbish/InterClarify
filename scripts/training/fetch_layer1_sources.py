"""Download the pinned UltraChat source shards and verify published LFS hashes."""
import argparse
import hashlib
import json
from pathlib import Path

import requests


def fetch(url, path, size, expected):
    """Accept a shard only after verifying its complete bytes and SHA256."""
    if path.exists():
        digest=hashlib.sha256()
        with path.open('rb') as stream:
            for block in iter(lambda:stream.read(1024*1024),b''):digest.update(block)
        if path.stat().st_size!=size or digest.hexdigest()!=expected:
            raise ValueError(f'Existing shard differs from frozen source: {path}')
        return digest.hexdigest()
    temporary=path.with_suffix(path.suffix+'.part')
    digest=hashlib.sha256()
    length=0
    with requests.get(url,stream=True,timeout=(30,120)) as response:
        response.raise_for_status()
        with temporary.open('wb') as output:
            for block in response.iter_content(1024*1024):
                output.write(block);digest.update(block);length+=len(block)
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
    for row in source['files']:
        name=row['path']
        if Path(name).name!=name:raise ValueError('Only frozen top-level shards are supported')
        url=f"{args.endpoint.rstrip('/')}/datasets/{source['dataset']}/resolve/{source['revision']}/{name}"
        digest=fetch(url,args.output/name,row['size'],row['lfs']['oid'])
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
    main(parser.parse_args())

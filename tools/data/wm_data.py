#!/usr/bin/env python3
"""Plan downloads using exact provider file metadata; never infer size from duration.
Python >=3.10. For network operations: pip install huggingface_hub requests.
"""
import argparse, csv, datetime as dt, gzip, hashlib, json, os, re, shutil, sys
from pathlib import Path, PurePosixPath
from urllib.parse import urlsplit

HERE=Path(__file__).resolve().parent
G=10**9

def utc(): return dt.datetime.now(dt.timezone.utc).isoformat()
def safe_path(v):
    p=PurePosixPath(v)
    if not v or not p.parts or p.is_absolute() or any(x in ('..','.') for x in p.parts) or '\\' in v or ':' in v or str(p)!=v: raise ValueError(f'unsafe path: {v!r}')
    return str(p)
def exact_size(v):
    if isinstance(v,bool) or not isinstance(v,int) or v<0: raise ValueError('provider did not return an exact nonnegative byte count')
    return v

def human(n): return f'{n/G:,.3f} GB ({n:,} bytes)'
def digest(x): return hashlib.sha256(json.dumps(x,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode()).hexdigest()
def write_json(path,data):
    path=Path(path); path.parent.mkdir(parents=True,exist_ok=True)
    tmp=path.with_suffix(path.suffix+'.tmp'); tmp.write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding='utf-8'); tmp.replace(path)

def http_metadata(url,allowed_content_encodings=(),allow_get_headers=False):
    import requests
    if urlsplit(url).scheme not in ('http','https'): raise ValueError('HTTP(S) URL required; use official CLI for s3/gs')
    headers={'Accept-Encoding':'identity'}
    # HEAD first. A named source may explicitly allow a streamed GET header probe.
    # In both cases no response body is read, iterated or saved.
    with requests.head(url,headers=headers,allow_redirects=True,timeout=(15,60)) as r:
        encoding=r.headers.get('Content-Encoding','').lower()
        if r.ok and r.status_code==200 and r.headers.get('Content-Length','').isdigit() and (not encoding or encoding in allowed_content_encodings) and 'text/html' not in r.headers.get('Content-Type','').lower():
            return int(r.headers['Content-Length']),r.headers.get('ETag'),r.headers.get('Last-Modified')
        if not allow_get_headers: r.raise_for_status()
    if allow_get_headers:
        with requests.get(url,headers={**headers,'Range':'bytes=0-0'},stream=True,allow_redirects=True,timeout=(15,60)) as r:
            r.raise_for_status()
            encoding=r.headers.get('Content-Encoding','').lower()
            if (encoding and encoding not in allowed_content_encodings) or 'text/html' in r.headers.get('Content-Type','').lower():
                raise ValueError('unexpected encoding or HTML in header probe')
            match=re.fullmatch(r'bytes 0-0/(\d+)',r.headers.get('Content-Range',''))
            if r.status_code==206 and match:
                return int(match[1]),r.headers.get('ETag'),r.headers.get('Last-Modified')
            if r.status_code==200 and r.headers.get('Content-Length','').isdigit():
                return int(r.headers['Content-Length']),r.headers.get('ETag'),r.headers.get('Last-Modified')
    raise ValueError('HEAD/header probe did not provide a reliable whole-file size; response body not read')

def http_item(dataset,path,url,allowed_content_encodings=(),allow_get_headers=False):
    n,etag,lm=http_metadata(url,allowed_content_encodings,allow_get_headers)
    return {'dataset':dataset,'path':safe_path(path),'bytes':exact_size(n),'kind':'http','url':url,'etag':etag,'last_modified':lm,'allowed_content_encodings':list(allowed_content_encodings),'allow_get_headers':allow_get_headers,'size_source':'HTTP response headers; body not read' if allow_get_headers else 'HTTP HEAD Content-Length (raw representation bytes)'}

def hf_entries(spec):
    from huggingface_hub import HfApi
    from huggingface_hub.hf_api import RepoFile
    api=HfApi(); repo=spec['repo']; info=api.dataset_info(repo,revision=spec.get('revision','main'))
    rev=info.sha
    if not rev: raise ValueError('missing repository commit')
    entries=[]
    kwargs={'repo_type':'dataset','revision':rev,'recursive':True,'expand':False}
    if spec.get('path_in_repo'): kwargs['path_in_repo']=safe_path(spec['path_in_repo'])
    for f in api.list_repo_tree(repo,**kwargs):
        if not isinstance(f,RepoFile): continue
        n=exact_size(f.size)
        sha=getattr(getattr(f,'lfs',None),'sha256',None)
        entries.append({'dataset':spec['id'],'path':safe_path(f.path),'bytes':n,'kind':'hf','repo':repo,'revision':rev,'sha256':sha,'git_blob_id':None if sha else getattr(f,'blob_id',None),'size_source':'HF repository tree API'})
        if len(entries)%10000==0: print(f'{spec["id"]}: reading metadata, {len(entries):,} files so far (not a complete total)',flush=True)
    if not entries: raise ValueError('empty repository file tree')
    return entries,rev

def select_hf(entries,spec):
    mode=spec.get('mode','all'); names={x['path']:x for x in entries}
    if len(names)!=len(entries): raise ValueError('duplicate provider file path')
    if mode=='inventory': return []
    if mode=='all': return sorted(entries,key=lambda x:x['path'])
    fixed=spec.get('files',[])
    missing=[p for p in fixed if p not in names]
    if missing: raise ValueError(f'expected files absent at current commit: {missing}')
    selected=[names[p] for p in fixed]
    if mode=='fixed': return selected
    if mode not in ('budget','filtered'): raise ValueError('unknown selection mode')
    pattern=re.compile(spec['include_regex']); candidates=[f for f in entries if pattern.fullmatch(f['path']) and f['path'] not in fixed]
    if spec.get('allowed_video_ids'):
        allowed=set(spec['allowed_video_ids']); candidates=[f for f in candidates if PurePosixPath(f['path']).stem in allowed]
    if not candidates: raise ValueError('no eligible files matched; inspect repository tree and update selection regex')
    if mode=='filtered': return sorted(selected+candidates,key=lambda x:x['path'])
    cap=exact_size(spec['budget_bytes']); total=sum(f['bytes'] for f in selected)
    if total>cap: raise ValueError('required metadata alone exceeds budget')
    # Stable randomized selection of complete archives/shards. Not a semantic sample.
    candidates.sort(key=lambda f:hashlib.sha256((str(spec.get('seed',3072))+'|'+f['path']).encode()).digest())
    for f in candidates:
        if total+f['bytes']<=cap: selected.append(f); total+=f['bytes']
    if len(selected)==len(fixed): raise ValueError('no complete data shard fits budget')
    return sorted(selected,key=lambda x:x['path'])

def dataverse_entries(spec):
    """Public published-version metadata only; no access/datafile requests."""
    import requests
    endpoint=spec['server'].rstrip('/')+'/api/datasets/:persistentId/'
    r=requests.get(endpoint,params={'persistentId':spec['persistent_id']},timeout=(15,60))
    r.raise_for_status(); v=r.json()['data']['latestVersion']
    if v.get('versionState')!='RELEASED': raise ValueError('Dataverse version is not published')
    revision=f"{v['versionNumber']}.{v['versionMinorNumber']}"
    entries=[]
    for item in v['files']:
        f=item['dataFile']; prefix=item.get('directoryLabel','')
        path=(prefix+'/' if prefix else '')+f['filename']
        entries.append({'dataset':spec['id'],'path':safe_path(path),'bytes':exact_size(f['filesize']),
            'kind':'dataverse','file_id':f['id'],'revision':revision,'restricted':bool(item.get('restricted')),
            'checksum':f.get('checksum'),'size_source':'Dataverse published version API'})
    if not entries: raise ValueError('empty Dataverse inventory')
    if len({x['path'] for x in entries})!=len(entries): raise ValueError('duplicate Dataverse path')
    return entries,revision

def save_inventory(out,spec,entries,revision):
    body={'schema':'wm-data-inventory-v1','id':spec['id'],'version':revision,'checked_at':utc(),
          'scope_bytes':sum(exact_size(x['bytes']) for x in entries),'files':sorted(entries,key=lambda x:x['path'])}
    raw=json.dumps(body,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode()
    path=out/'inventories'/(spec['id']+'.json.gz');path.parent.mkdir(parents=True,exist_ok=True)
    path.write_bytes(gzip.compress(raw,mtime=0))
    return {'scope_bytes':body['scope_bytes'],'scope_files':len(entries),'version':revision,
            'inventory_file':path.relative_to(out).as_posix(),'inventory_sha256':hashlib.sha256(raw).hexdigest()}

def failure_reason(e):
    # Never include exception text: requests can echo signed URLs and credentials.
    response=getattr(e,'response',None); code=getattr(response,'status_code',None)
    if code in (401,403): return 'access_required',f'源站返回 HTTP {code}（可能为权限或访问限制）；未读取数据文件。'
    if code==404: return 'not_found','发布版本或文件路径不存在；需核对官方入口。'
    if type(e).__name__=='SSLError': return 'tls_error','源站 TLS 证书校验失败；未关闭证书验证。'
    if code==429: return 'rate_limited','源站限制请求频率；稍后重新核验。'
    if isinstance(e,ValueError): return 'invalid_metadata','文件元数据或选择规则不符合要求；未计入选择容量。'
    return 'metadata_error',f'元数据读取失败（{type(e).__name__}）；检查网络、访问权限和版本。'

def local_entries(dataset,root):
    root=Path(root).resolve(); out=[]
    if not root.is_dir(): raise ValueError(f'not a directory: {root}')
    for p in sorted(root.rglob('*')):
        if p.is_symlink() or not p.is_file(): continue
        rel=p.relative_to(root).as_posix()
        if any(x.startswith('.') for x in PurePosixPath(rel).parts): continue
        out.append({'dataset':dataset,'path':safe_path(rel),'bytes':p.stat().st_size,'kind':'local','size_source':'local file stat'})
    if not out: raise ValueError('empty selected local directory')
    return out

def plan(args):
    cfg=json.loads(Path(args.config).read_text(encoding='utf-8')); specs={s['id']:s for s in cfg['datasets']}
    requested=args.datasets or [s['id'] for s in specs.values() if args.all_datasets or s.get('phase')=='starter']
    out=Path(args.out);out.mkdir(parents=True,exist_ok=True)
    manual={}; local={}
    if args.manual_csv:
        with open(args.manual_csv,encoding='utf-8-sig',newline='') as fp:
            for row in csv.DictReader(fp): manual.setdefault(row['dataset'],[]).append(row)
    for item in args.local or []:
        k,v=item.split('=',1); local[k]=v
    if set(manual)&set(local): raise ValueError('a dataset cannot use both manual URL and local modes')
    for k in list(manual)+list(local):
        if k not in specs: raise ValueError(f'unknown dataset: {k}')
        if k not in requested: requested.append(k)
    if len(requested)!=len(set(requested)): raise ValueError('duplicate dataset id')
    files=[]; reports=[]
    for k in requested:
        if k not in specs: raise ValueError(f'unknown dataset: {k}')
        s=specs[k]; base={'id':k,'name':s['name'],'phase':s['phase'],'status':'pending','scope_bytes':None,'scope_files':None,'selected_bytes':None,'files':0,'version':None,'note':s.get('note',''),'source_urls':s.get('source_urls',[]),'checked_at':utc()}
        try:
            if k in local:
                selected=local_entries(k,local[k]); base.update(status='local',version='local files; '+utc(),note='实际本地文件字节数（仅所选目录；确认不含测试/重复数据）')
            elif k in manual:
                selected=[http_item(k,r['path'],r['url']) for r in manual[k]]; base.update(status='planned',note='用户指定文件清单；确保配套文件及授权完整')
            elif s['provider']=='audit':
                from metadata_sources import audit_metadata
                result,evidence=audit_metadata(s,http_item)
                path=out/'evidence'/(k+'.json');write_json(path,evidence)
                base.update(result,evidence_file=path.relative_to(out).as_posix(),evidence_sha256=digest(evidence))
                reports.append(base);print(f'{k}: {base["status"].upper()} — {base["note"]}',flush=True);continue
            elif s['provider']=='manual':
                base.update(status='pending',note=s['note']); reports.append(base); print(f'{k}: PENDING — {s["note"]}'); continue
            elif s['provider']=='hf':
                entries,rev=hf_entries(s); base.update(save_inventory(out,s,entries,rev))
                if s.get('mode')=='inventory':
                    base.update(status='inventoried')
                    if s.get('content_scope')=='index_only':
                        base.update(status='partial',auxiliary_bytes=base['scope_bytes'],auxiliary_files=base['scope_files'],verification_label='索引容量已核验')
                    reports.append(base)
                    print(f'{k}: {base["status"].upper()} {human(base["scope_bytes"])} / {len(entries)} files; complete specified metadata scope',flush=True); continue
                selected=select_hf(entries,s); base.update(status='planned',note=s.get('note',''))
            elif s['provider']=='dataverse':
                entries,rev=dataverse_entries(s); base.update(save_inventory(out,s,entries,rev),status='inventoried')
                reports.append(base);print(f'{k}: INVENTORY {human(base["scope_bytes"])} / {len(entries)} files; select train trajectories separately',flush=True);continue
            elif s['provider'] in ('s3','gcs','hf_bucket','epic'):
                from metadata_sources import PROVIDERS
                entries,rev=PROVIDERS[s['provider']](s)
                for f in entries: safe_path(f['path']);exact_size(f['bytes'])
                for item in s.get('extra_http_items',[]):
                    entries.append(http_item(k,item['path'],item['url'],item.get('allowed_content_encodings',())))
                base.update(save_inventory(out,s,entries,rev))
                if s.get('mode')=='inventory':
                    base.update(status='inventoried');reports.append(base);continue
                selected=select_hf(entries,s);base.update(status='planned')
                if s.get('verify_selected_headers'):
                    from concurrent.futures import ThreadPoolExecutor
                    def verify_header(f):
                        n,etag,lm=http_metadata(f['url'])
                        if n!=f['bytes']: raise ValueError('publisher manifest and HTTP size disagree')
                        f.update(etag=etag,last_modified=lm,header_verified=True)
                    with ThreadPoolExecutor(max_workers=4) as pool:
                        list(pool.map(verify_header,selected))
                    base.update(save_inventory(out,s,entries,rev))
            elif s['provider']=='http':
                from concurrent.futures import ThreadPoolExecutor
                def inspect_item(x):
                    row=http_item(k,x['path'],x['url'],x.get('allowed_content_encodings',()),x.get('allow_get_headers',False))
                    if x.get('expected_md5'): row['publisher_md5']=x['expected_md5']
                    return row
                with ThreadPoolExecutor(max_workers=4) as pool:
                    selected=list(pool.map(inspect_item,s['items']))
                base.update(status='planned',version='HTTP headers '+utc())
                if s.get('mode')=='inventory':
                    base.update(save_inventory(out,s,selected,'HTTP validators '+digest(selected)[:16]),status='inventoried')
                    reports.append(base);print(f'{k}: INVENTORY {human(base["scope_bytes"])} / {len(selected)} files',flush=True);continue
            else: raise ValueError('unsupported provider')
            if not selected: raise ValueError('empty selection')
            if len({x['path'] for x in selected})!=len(selected): raise ValueError('duplicate path')
            base.update(selected_bytes=sum(exact_size(x['bytes']) for x in selected),files=len(selected))
            if selected[0]['kind']=='http' and not base.get('inventory_file'):
                base.update(save_inventory(out,s,selected,'HTTP validators '+digest(selected)[:16]))
            files.extend(selected); print(f'{k}: {human(base["selected_bytes"])} / {len(selected)} files',flush=True)
        except Exception as e:
            # Avoid exposing signed URL parameters or bearer tokens in public report.
            reason,note=failure_reason(e)
            base.update(status='error',selected_bytes=None,files=0,error_code=reason,note=note)
            print(f'{k}: ERROR ({type(e).__name__}); see provider, credentials and file selectors',file=sys.stderr)
        reports.append(base)
    payload=make_manifest(reports,files)
    write_plan(out,payload)
    print(f'\nVerified selected-file subtotal: {human(payload["selected_bytes"])}; new transfer: {human(payload["transfer_bytes"])}; unresolved file selections: {len(payload["download_unresolved"])}')
    print('This is NOT effective training data size. Import capacity_report.json into the HTML. No payload downloaded.')
    return 2 if payload['download_unresolved'] else 0

def make_manifest(reports,files):
    total=sum(x['selected_bytes'] for x in reports if isinstance(x['selected_bytes'],int));transfer=sum(f['bytes'] for f in files if f['kind']!='local')
    payload={'schema':'wm-data-manifest-v1','created_at':utc(),'metadata_only':True,'data_bytes_downloaded':0,'datasets':reports,'files':files,'selected_bytes':total,'transfer_bytes':transfer,'starter_selected_bytes':sum(x['selected_bytes'] or 0 for x in reports if x['phase']=='starter'),'download_unresolved':[x['id'] for x in reports if x['status'] not in ('planned','local','inventoried')], 'audit_counts':{s:sum(x['status']==s for x in reports) for s in sorted({x['status'] for x in reports})}}
    payload['manifest_sha256']=digest(payload)
    return payload

def write_plan(out,payload):
    out=Path(out);out.mkdir(parents=True,exist_ok=True)
    write_json(out/'manifest.json',payload)
    public={k:v for k,v in payload.items() if k!='files'};public['schema']='wm-data-report-v1';write_json(out/'capacity_report.json',public)
    with (out/'files.csv').open('w',encoding='utf-8-sig',newline='') as f:
        w=csv.DictWriter(f,fieldnames=['dataset','path','bytes','kind','revision','size_source','sha256'],extrasaction='ignore',lineterminator='\n');w.writeheader();w.writerows(payload['files'])

def verify_local(p,row,sha=False):
    if not p.is_file() or p.stat().st_size!=row['bytes']: return False
    if sha and row.get('sha256'):
        h=hashlib.sha256()
        with p.open('rb') as f:
            for b in iter(lambda:f.read(8*1024*1024),b''): h.update(b)
        return h.hexdigest()==row['sha256']
    return True

def fetch_http(row,target):
    import requests
    if row.get('bucket') and row.get('xet_hash'):
        from metadata_sources import verify_bucket_identity
        verify_bucket_identity(row)
    allowed=row.get('allowed_content_encodings',())
    n,e,lm=http_metadata(row['url'],allowed,row.get('allow_get_headers',False))
    if n!=row['bytes'] or (row.get('etag') and e!=row['etag']) or (row.get('last_modified') and lm!=row['last_modified']): raise RuntimeError('remote file changed; re-plan before download')
    tmp=target.with_name(target.name+'.part'); meta=target.with_name(target.name+'.part.json')
    identity=digest({'url':row['url'],'bytes':n,'etag':e,'last_modified':lm})
    if tmp.exists() and (not meta.exists() or meta.read_text(encoding='utf-8')!=identity): raise RuntimeError('partial file belongs to a different or unknown manifest; move it first')
    if tmp.exists() and not(e or lm): raise RuntimeError('server has no version validator; move partial file and restart')
    meta.write_text(identity,encoding='utf-8'); size=tmp.stat().st_size if tmp.exists() else 0
    if size>n: raise RuntimeError('partial file larger than expected')
    # If server does not support Range, restart safely rather than append an entire file.
    headers={'Accept-Encoding':'identity'}
    if size: headers['Range']=f'bytes={size}-'
    if size!=n:
        with requests.get(row['url'],headers=headers,stream=True,allow_redirects=True,timeout=(15,120)) as r:
            r.raise_for_status()
            encoding=r.headers.get('Content-Encoding','').lower()
            if (encoding and encoding not in allowed) or 'text/html' in r.headers.get('Content-Type','').lower(): raise RuntimeError('unexpected HTTP compression or HTML response')
            if e and r.headers.get('ETag') and r.headers['ETag']!=e: raise RuntimeError('remote ETag changed')
            if row.get('last_modified') and r.headers.get('Last-Modified') and r.headers['Last-Modified']!=row['last_modified']: raise RuntimeError('remote Last-Modified changed')
            if size and r.status_code==206:
                m=re.fullmatch(r'bytes (\d+)-(\d+)/(\d+)',r.headers.get('Content-Range',''))
                if not m or int(m[1])!=size or int(m[3])!=n: raise RuntimeError('invalid resume response')
                mode='ab'
            elif r.status_code==200: size=0;mode='wb'
            else: raise RuntimeError('unexpected partial response')
            with tmp.open(mode) as f:
                # Preserve archive representation bytes. iter_content auto-decodes
                # RECON's legacy gzip header and would corrupt its .tar.gz output.
                for chunk in r.raw.stream(8*1024*1024,decode_content=False):
                    if chunk:
                        size+=len(chunk)
                        if size>n: raise RuntimeError('response exceeds planned size')
                        f.write(chunk)
    if not verify_local(tmp,row): raise RuntimeError('download byte count mismatch')
    tmp.replace(target); meta.unlink(missing_ok=True)

def load_manifest(path):
    m=json.loads(Path(path).read_text(encoding='utf-8')); sha=m.pop('manifest_sha256',None)
    if m.get('schema')!='wm-data-manifest-v1' or sha!=digest(m): raise ValueError('manifest integrity check failed; regenerate plan')
    return m

def download(args):
    m=load_manifest(args.manifest); root=Path(args.dest).resolve();root.mkdir(parents=True,exist_ok=True)
    rows=[x for x in m['files'] if x['kind']!='local']; approved=set(args.approved or [])
    if m.get('download_unresolved',m.get('pending',[])) and not args.allow_partial: raise ValueError('unresolved datasets; re-plan or explicitly --allow-partial')
    missing_approval={r['dataset'] for r in rows}-approved
    if missing_approval: raise ValueError('missing --approved for '+', '.join(sorted(missing_approval)))
    expected=sum(exact_size(r['bytes']) for r in rows)
    if not args.execute: print(f'DRY RUN: {len(rows)} files, {human(expected)}; use --execute to start.');return 0
    if not (args.max_gb>0 and args.reserve_gb>=0): raise ValueError('invalid storage budget')
    if expected>int(args.max_gb*G): raise ValueError('manifest exceeds explicit --max-gb limit')
    todo=[]
    for r in rows:
        path=root/safe_path(r['dataset'])/safe_path(r['path'])
        if not path.resolve().is_relative_to(root): raise ValueError('destination escapes root')
        if path.exists() and verify_local(path,r,args.sha256): continue
        if path.exists(): raise ValueError(f'Existing destination differs; move it first: {path}')
        todo.append((r,path))
    need=sum(r['bytes'] for r,_ in todo)
    if shutil.disk_usage(root).free<need+int(args.reserve_gb*G): raise ValueError('insufficient free space (payload + reserve); do not unpack on same volume without extra space')
    for i,(r,p) in enumerate(todo,1):
        p.parent.mkdir(parents=True,exist_ok=True)
        print(f'[{i}/{len(todo)}] {r["dataset"]}/{r["path"]} {human(r["bytes"])}',flush=True)
        if r['kind']=='hf':
            from huggingface_hub import hf_hub_download
            actual=Path(hf_hub_download(repo_id=r['repo'],filename=r['path'],repo_type='dataset',revision=r['revision'],local_dir=root/r['dataset']))
            if actual.resolve()!=p.resolve() or not verify_local(p,r,args.sha256): raise RuntimeError('HF output integrity mismatch')
        elif r['kind']=='http': fetch_http(r,p)
        else: raise ValueError('unknown file kind')
    print('Done: all selected new-download files passed byte-size check. Extraction and episode-level validation remain separate.');return 0

def main():
    p=argparse.ArgumentParser(description=__doc__);sub=p.add_subparsers(dest='cmd',required=True)
    a=sub.add_parser('plan');a.add_argument('--config',default=str(HERE/'datasets.json'));g=a.add_mutually_exclusive_group();g.add_argument('--datasets',nargs='+');g.add_argument('--all-datasets',action='store_true');a.add_argument('--approved',nargs='+',help='legacy plan option; only download requires approval');a.add_argument('--manual-csv');a.add_argument('--local',action='append',help='ID=/selected/local/directory; measure file stat');a.add_argument('--out',default='wm_plan')
    a=sub.add_parser('download');a.add_argument('--manifest',required=True);a.add_argument('--dest',required=True);a.add_argument('--approved',nargs='+');a.add_argument('--execute',action='store_true');a.add_argument('--allow-partial',action='store_true');a.add_argument('--max-gb',type=float,default=1000);a.add_argument('--reserve-gb',type=float,default=50);a.add_argument('--sha256',action='store_true')
    args=p.parse_args()
    try:return plan(args) if args.cmd=='plan' else download(args)
    except Exception as e:print(f'ERROR: {e}',file=sys.stderr);return 1
if __name__=='__main__':sys.exit(main())

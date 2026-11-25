"""Public catalog APIs and publisher manifests. No training-file GET requests."""
import hashlib
import datetime as dt
import json
import time
import xml.etree.ElementTree as ET
from urllib.parse import quote, urlsplit

import requests


def metadata_get(url, *, params=None):
    """Only call for catalog/manifest URLs, never video or training-shard URLs."""
    for attempt in range(5):
        response = requests.get(url,params=params,timeout=(15,60))
        if response.status_code not in (429,500,502,503,504):
            response.raise_for_status(); return response
        if attempt < 4: time.sleep(min(2 ** attempt,16))
    response.raise_for_status()


def gcs_entries(spec):
    if spec.get('prefixes'):
        entries=[]
        for prefix in spec['prefixes']:
            child={k:v for k,v in spec.items() if k!='prefixes'};child['prefix']=prefix
            entries.extend(gcs_entries(child)[0])
        return entries,'GCS generations / selected version prefixes'
    bucket = spec['bucket']; params = {'prefix':spec['prefix'],'maxResults':1000,
        'fields':'nextPageToken,items(name,size,generation,md5Hash,crc32c,updated)'}
    entries = []; seen_tokens = set()
    while True:
        data = metadata_get(f'https://storage.googleapis.com/storage/v1/b/{bucket}/o',params=params).json()
        for f in data.get('items',[]):
            if f['name'].endswith(('/', '_$folder$')): continue
            entries.append({'dataset':spec['id'],'path':f['name'],'bytes':int(f['size']),
                'kind':'http','url':f'https://storage.googleapis.com/{bucket}/{quote(f["name"],safe="/")}?generation={f["generation"]}',
                'generation':f['generation'],'md5_base64':f.get('md5Hash'),'crc32c':f.get('crc32c'),
                'provider_updated':f.get('updated'),'size_source':'GCS objects.list size; fixed object generation'})
        token = data.get('nextPageToken')
        if not token: break
        if token in seen_tokens: raise ValueError('repeated GCS page token')
        seen_tokens.add(token);params['pageToken'] = token
        if len(entries) % 10000 < 1000: print(f'{spec["id"]}: {len(entries):,} metadata objects (listing incomplete)',flush=True)
    if not entries: raise ValueError('empty GCS prefix')
    return entries,'GCS generations / '+spec['prefix']


def s3_entries(spec):
    bucket = spec['bucket']; params = {'list-type':'2','prefix':spec['prefix'],'max-keys':1000}
    entries = []; seen_tokens = set(); ns = {'s':'http://s3.amazonaws.com/doc/2006-03-01/'}
    while True:
        root = ET.fromstring(metadata_get(f'https://s3.amazonaws.com/{bucket}',params=params).content)
        for f in root.findall('s:Contents',ns):
            key = f.findtext('s:Key',namespaces=ns)
            if key.endswith('/'): continue
            entries.append({'dataset':spec['id'],'path':key,'bytes':int(f.findtext('s:Size',namespaces=ns)),
                'kind':'http','url':f'https://s3.amazonaws.com/{bucket}/{quote(key,safe="/")}',
                'etag':f.findtext('s:ETag',namespaces=ns),'provider_updated':f.findtext('s:LastModified',namespaces=ns),
                'size_source':'S3 ListObjectsV2 Size'})
        if root.findtext('s:IsTruncated',namespaces=ns) != 'true': break
        token = root.findtext('s:NextContinuationToken',namespaces=ns)
        if not token or token in seen_tokens: raise ValueError('missing/repeated S3 continuation token')
        seen_tokens.add(token);params['continuation-token'] = token
    if not entries: raise ValueError('empty S3 prefix')
    return entries,'S3 listing / '+spec['prefix']


def bucket_entries(spec):
    bucket = spec['bucket']; prefix = spec['prefix']
    url = f'https://huggingface.co/api/buckets/{bucket}/tree/{quote(prefix,safe="")}'
    params = {'recursive':'true'}; entries = []; seen = set()
    while url:
        if url in seen: raise ValueError('repeated bucket pagination URL')
        if urlsplit(url).netloc != 'huggingface.co': raise ValueError('unexpected bucket pagination host')
        seen.add(url); response = metadata_get(url,params=params)
        for f in response.json():
            if f['type'] != 'file': continue
            if not f['path'].startswith(prefix.rstrip('/')+'/'): raise ValueError('bucket file outside selected prefix')
            entries.append({'dataset':spec['id'],'path':f['path'],'bytes':f['size'],'kind':'http',
                'url':f'https://huggingface.co/buckets/{bucket}/resolve/{quote(f["path"],safe="/")}',
                'bucket':bucket,'xet_hash':f['xetHash'],'provider_updated':f.get('mtime'),
                'size_source':'HF bucket tree API (complete named release batch)'})
        url = response.links.get('next',{}).get('url');params = None
    paths = [x['path'] for x in entries]
    # A complete LeRobot batch must contain all three modalities/components.
    for part in ('/data/','/meta/','/videos/'):
        if not any(part in x for x in paths): raise ValueError('incomplete Human-1M batch: missing '+part)
    if not entries: raise ValueError('empty bucket prefix')
    return entries,'HF mutable bucket / '+prefix


def verify_bucket_identity(row):
    """Read-only paths-info query: reject changed mutable bucket content."""
    response = requests.post(f'https://huggingface.co/api/buckets/{row["bucket"]}/paths-info',
        json={'paths':[row['path']]},timeout=(15,60))
    response.raise_for_status(); items = response.json()
    if len(items)!=1 or items[0]['path']!=row['path'] or items[0]['size']!=row['bytes'] or items[0]['xetHash']!=row['xet_hash']:
        raise RuntimeError('HF bucket object changed; re-plan before download')


def decode_bencode(data):
    """Read a .torrent descriptor; no tracker/peer requests and no file data."""
    def read(i):
        c = data[i:i+1]
        if c == b'i':
            end = data.index(b'e',i); return int(data[i+1:end]),end+1
        if c in (b'l',b'd'):
            items = [];i += 1
            while data[i:i+1] != b'e':
                value,i = read(i);items.append(value)
            if c == b'd':
                if len(items)%2: raise ValueError('invalid bencode dictionary')
                return dict(zip(items[::2],items[1::2])),i+1
            return items,i+1
        end = data.index(b':',i);length = int(data[i:end]);stop = end+1+length
        if length < 0 or stop > len(data): raise ValueError('invalid bencode length')
        return data[end+1:stop],stop
    obj,end = read(0)
    if end != len(data): raise ValueError('trailing torrent bytes')
    return obj


def epic_entries(spec):
    entries = []
    for source in spec['releases']:
        raw = metadata_get(source['torrent_url']).content
        descriptor = decode_bencode(raw); info = descriptor[b'info']
        root = info[b'name'].decode()
        if root != source['root']: raise ValueError('unexpected EPIC torrent root')
        evidence_sha = hashlib.sha256(raw).hexdigest()
        for f in info[b'files']:
            relative = '/'.join(x.decode() for x in f[b'path'])
            if not relative.lower().endswith('.mp4'): continue
            entries.append({'dataset':spec['id'],'path':root+'/'+relative,'bytes':f[b'length'],'kind':'http',
                'url':'https://data.bris.ac.uk/datasets/'+root+'/'+quote(relative,safe='/'),
                'publisher_torrent_url':source['torrent_url'],'publisher_manifest_sha256':evidence_sha,
                'size_source':'Publisher-recommended torrent info.files.length (video files only)'})
    for source in spec.get('github_metadata_files',[]):
        meta=metadata_get(source['api_url']).json()
        if meta.get('sha')!=source['blob_sha']: raise ValueError('EPIC annotation blob changed; refresh fixed reference')
        entries.append({'dataset':spec['id'],'path':source['path'],'bytes':meta['size'],'kind':'http',
            'url':source['download_url'],'git_blob_id':meta['sha'],'size_source':'GitHub contents API size at pinned commit'})
    if len({x['path'] for x in entries}) != len(entries): raise ValueError('duplicate EPIC video path')
    return entries,'EPIC-55 + EPIC-100 extension / published video manifests'


PROVIDERS = {'gcs':gcs_entries,'s3':s3_entries,'hf_bucket':bucket_entries,'epic':epic_entries}


def probe_headers(url, method='HEAD'):
    """Record reachability without reading a training-file response body."""
    result={'url':url,'method':method,'response_body_bytes_read':0}
    try:
        with requests.request(method,url,stream=True,allow_redirects=True,timeout=(15,45)) as r:
            result.update(status=r.status_code,content_type=r.headers.get('Content-Type'),
                content_length=r.headers.get('Content-Length'))
    except requests.RequestException as e:
        result['error']=type(e).__name__  # do not echo credentials or redirect URLs
    return result


def registry_sizes(attributes):
    # Dataverse exports DataFile.getFilesize() in bytes to DataCite <sizes>.
    # This is a registered aggregate, NOT an ordered mapping to file DOIs.
    sizes=attributes.get('sizes',[])
    if not sizes or not all(isinstance(n,str) and n.isdecimal() for n in sizes):
        raise ValueError('registry does not contain unambiguous numeric file sizes')
    return [int(n) for n in sizes]


def audit_metadata(spec, http_item):
    """Separate exact auxiliary/registered values from downloadable training bytes."""
    kind=spec['audit_kind']; evidence={'id':spec['id'],'checked_at':dt.datetime.now(dt.timezone.utc).isoformat(),
        'source_urls':spec.get('source_urls',[]),'checks':[],'training_file_body_bytes_read':0}
    if kind=='not_generated':
        return {'status':'not_generated','note':spec['note']},evidence
    if kind=='access':
        evidence['checks']=[probe_headers(url,'GET') for url in spec['manifest_urls']]
        denied=all(x.get('status') in (401,403) for x in evidence['checks'])
        note=spec['note'] if denied else '官方清单访问状态有变化；见 evidence 检查结果，需重新解析清单后计入容量。'
        return {'status':'blocked' if denied else 'error','version':spec['release'],'note':note},evidence
    if kind=='registry':
        evidence['checks']=[probe_headers(spec['primary_metadata_url'],'GET')]
        attributes=metadata_get(spec['registry_url']).json()['data']['attributes']
        sizes=registry_sizes(attributes)
        evidence.update(registry_url=spec['registry_url'],registry_version=attributes.get('version'),
            registry_updated=attributes.get('updated'),registered_file_sizes_bytes=sizes,
            related_file_dois=[x['relatedIdentifier'] for x in attributes.get('relatedIdentifiers',[]) if x.get('relationType')=='HasPart'],
            unit_evidence=spec['unit_evidence'],mapping='No association between sizes and file DOIs is assumed.')
        return {'status':'partial','version':'DataCite registered version '+str(attributes.get('version')),
            'registered_bytes':sum(sizes),'registered_files':len(sizes),'verification_label':'登记容量已核验',
            'note':f'已核验 DataCite 登记 v{attributes.get("version")}：{len(sizes)} 个容量值，共 {sum(sizes):,} bytes。'+spec['note']},evidence
    if kind=='auxiliary':
        components=[http_item(spec['id'],x['path'],x['url']) for x in spec['items']]
        evidence['components']=components
        return {'status':'partial','version':'Official index HTTP validators',
            'auxiliary_bytes':sum(x['bytes'] for x in components),'auxiliary_files':len(components),
            'verification_label':'索引容量已核验','note':f'官方索引 HTTP HEAD 核验：{sum(x["bytes"] for x in components):,} bytes。'+spec['note']},evidence
    if kind=='published':
        response=metadata_get(spec['publication_url']);text=response.text
        if spec['publication_quote'] not in text: raise ValueError('published size statement changed')
        evidence.update(publication_url=spec['publication_url'],publication_quote=spec['publication_quote'],
            publication_sha256=hashlib.sha256(response.content).hexdigest(),published_bytes_approx=spec['published_bytes_approx'])
        evidence['checks']=[probe_headers(url) for url in spec['header_urls']]
        return {'status':'published','version':'Author-published preprocessed release',
            'published_bytes_approx':spec['published_bytes_approx'],'verification_label':'公开发布容量已核对（舍入值）',
            'note':spec['note']},evidence
    raise ValueError('unknown metadata audit type')

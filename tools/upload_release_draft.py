"""Back up verified booklet ZIPs as an unpublished GitHub release.

Credentials come from Git's configured helper and are never printed or saved.
This command deliberately cannot publish a release or change repo visibility.
"""
from pathlib import Path
import argparse
import hashlib
import http.client
import json
import os
import subprocess
import sys
import urllib.parse
import urllib.request

ROOT=Path(__file__).resolve().parents[1]


def sha(path):
    h=hashlib.sha256()
    with path.open('rb') as stream:
        for data in iter(lambda:stream.read(1024*1024),b''):h.update(data)
    return h.hexdigest()


def main():
    if hasattr(sys.stdout,'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8')
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--manifest',type=Path,default=ROOT/'work/draft_education_manifest.json')
    parser.add_argument('--tag',required=True)
    parser.add_argument('--notes-file',type=Path,required=True)
    args=parser.parse_args()
    manifest=json.loads(args.manifest.read_text(encoding='utf-8'))
    for name in ('draft_edition_qa.json','service_content_qa.json','draft_visual_qa.json'):
        report=json.loads((ROOT/'reports'/name).read_text(encoding='utf-8'))
        assert report['status']=='passed',f'QA not passed: {name}'
        if 'manifest' in report:
            assert Path(report['manifest']).resolve()==args.manifest.resolve(),'QA applies to another edition'
    review=json.loads((ROOT/'reports/service_final_review.json').read_text(encoding='utf-8'))
    assert review['status']=='passed' and review['manifest_sha256']==sha(args.manifest),'Final review is stale'
    origin=subprocess.check_output(['git','remote','get-url','origin'],cwd=ROOT,text=True).strip()
    parsed=urllib.parse.urlsplit(origin)
    assert parsed.scheme=='https' and parsed.hostname=='github.com','Expected an HTTPS GitHub origin'
    repo=parsed.path.strip('/').removesuffix('.git')
    assert len(repo.split('/'))==2,'Invalid GitHub repository path'
    branch=subprocess.check_output(['git','branch','--show-current'],cwd=ROOT,text=True).strip()
    head=subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip()
    remote=subprocess.check_output(['git','ls-remote','origin','refs/heads/'+branch],cwd=ROOT,text=True).split()[0]
    assert head==remote,'Push and verify the source commit before uploading the release'
    credential=subprocess.run(['git','credential','fill'],input='protocol=https\nhost=github.com\n\n',
        capture_output=True,text=True,cwd=ROOT,
        env=dict(os.environ,GIT_TERMINAL_PROMPT='0',GCM_INTERACTIVE='Never'),check=True)
    fields=dict(v.split('=',1) for v in credential.stdout.splitlines() if '=' in v)
    token=fields['password']
    headers={'Authorization':'Bearer '+token,'Accept':'application/vnd.github+json',
             'X-GitHub-Api-Version':'2022-11-28','User-Agent':'mx5-manual-project'}

    class AssetRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self,req,fp,code,msg,response_headers,newurl):
            redirected=super().redirect_request(req,fp,code,msg,response_headers,newurl)
            if redirected is not None and urllib.parse.urlsplit(newurl).hostname!='api.github.com':
                redirected.remove_header('Authorization')
            return redirected

    def remote_digest(asset):
        if asset.get('digest'):return asset['digest']
        request=urllib.request.Request(asset['url'],headers={**headers,'Accept':'application/octet-stream'})
        h=hashlib.sha256()
        with urllib.request.build_opener(AssetRedirect()).open(request,timeout=180) as response:
            assert 'json' not in response.headers.get('Content-Type',''),'Asset API returned metadata instead of bytes'
            for chunk in iter(lambda:response.read(1024*1024),b''):h.update(chunk)
        return 'sha256:'+h.hexdigest()

    def api(method,path,data=None):
        request=urllib.request.Request('https://api.github.com'+path,method=method,
            data=json.dumps(data,ensure_ascii=False).encode('utf-8') if data is not None else None,
            headers={**headers,**({'Content-Type':'application/json'} if data is not None else {})})
        with urllib.request.urlopen(request,timeout=60) as response:return json.load(response)

    releases=api('GET',f'/repos/{repo}/releases?per_page=100')
    release=next((r for r in releases if r['tag_name']==args.tag),None)
    if release is None:
        release=api('POST',f'/repos/{repo}/releases',{
            'tag_name':args.tag,'target_commitish':head,'name':'준비물·정비 원칙 통합 교육판',
            'body':args.notes_file.read_text(encoding='utf-8'),'draft':True,
            'prerelease':False,'generate_release_notes':False})
    assert release['draft'] is True,'Refusing to modify a published release'
    if release['target_commitish']!=head:
        release=api('PATCH',f'/repos/{repo}/releases/{release["id"]}',{
            'target_commitish':head,'body':args.notes_file.read_text(encoding='utf-8'),'draft':True})
    assets={a['name']:a for a in release.get('assets',[])}
    uploaded=[]
    for bundle in manifest['bundles']:
        path=Path(bundle['path'])
        digest=sha(path)
        assert digest==bundle['sha256'],'Local archive changed after verification'
        # GitHub normalizes non-ASCII asset names; front/rear names can collide.
        suffixes={'_전체_30책자.zip':'mx5-service-all-30.zip',
                  '_프런트_도어_12책자.zip':'mx5-service-front-door-12.zip',
                  '_리어_도어_12책자.zip':'mx5-service-rear-door-12.zip'}
        names=[name for suffix,name in suffixes.items() if path.name.endswith(suffix)]
        assert len(names)==1,'Unknown bundle naming convention'
        remote_name=names[0]
        if remote_name not in assets:
            matching=[a for a in assets.values() if a['state']=='uploaded' and
                      a['size']==path.stat().st_size and remote_digest(a)=='sha256:'+digest]
            assert len(matching)<=1,'Multiple matching assets; refusing ambiguous rename'
            if matching:
                old_name=matching[0]['name']
                asset=api('PATCH',f'/repos/{repo}/releases/assets/{matching[0]["id"]}',
                          {'name':remote_name,'label':path.name})
                del assets[old_name]
                assets[remote_name]=asset
        if remote_name in assets:
            asset=assets[remote_name]
            assert remote_digest(asset)=='sha256:'+digest,'Existing draft asset differs; no overwrite performed'
        else:
            query=urllib.parse.urlencode({'name':remote_name,'label':path.name})
            url=urllib.parse.urlsplit(release['upload_url'].split('{',1)[0])
            connection=http.client.HTTPSConnection(url.hostname,timeout=180)
            try:
                with path.open('rb') as stream:
                    connection.request('POST',url.path+'?'+query,body=stream,
                        headers={**headers,'Content-Type':'application/zip','Content-Length':str(path.stat().st_size)})
                    response=connection.getresponse()
                    if response.status!=201:
                        detail=response.read(4096).decode('utf-8',errors='replace')
                        raise RuntimeError(f'Asset upload HTTP {response.status}: {detail}')
                    asset=json.load(response)
            finally:connection.close()
        assert asset['state']=='uploaded' and asset['size']==path.stat().st_size,'Uploaded asset size/state differs'
        assert remote_digest(asset)=='sha256:'+digest,'Remote SHA256 differs'
        uploaded.append({'name':asset['name'],'local_name':path.name,
                         'bytes':asset['size'],'sha256':digest,'asset_id':asset['id']})
        print(json.dumps({'uploaded':path.name,'bytes':asset['size'],'sha256_verified':True},ensure_ascii=False),flush=True)
    latest=api('GET',f'/repos/{repo}/releases/{release["id"]}')
    assert latest['draft'] is True and latest['target_commitish']==head,'Draft/commit state differs'
    result={'status':'passed','repository':repo,'release_url':latest['html_url'],'release_id':latest['id'],
            'tag':args.tag,'draft':True,'source_commit':head,'assets':uploaded}
    (ROOT/'reports/release_upload.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(result,ensure_ascii=False,indent=2))


if __name__=='__main__':main()

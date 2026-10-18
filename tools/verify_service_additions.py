"""Check the new service information against reviewed source records and PDFs."""
from pathlib import Path
from collections import Counter
import argparse
import hashlib
import json
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'work'))
from pypdf import PdfReader
from verify_photo_intro import normalized_text


def read(path):return json.loads(Path(path).read_text(encoding='utf-8'))
def norm(text):return normalized_text(str(text))


def main():
    if hasattr(sys.stdout,'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8')
    parser=argparse.ArgumentParser()
    parser.add_argument('--manifest',type=Path,default=ROOT/'work/draft_education_manifest.json')
    parser.add_argument('--report',type=Path,default=ROOT/'reports/service_content_qa.json')
    args=parser.parse_args()
    manifest=read(args.manifest)
    for name,expected in manifest.get('service_evidence_sha256',{}).items():
        assert hashlib.sha256((ROOT/'work'/name).read_bytes()).hexdigest()==expected,'Reviewed data changed after build: '+name
    evidence=[read(ROOT/'work/service_tools_parts.json'),read(ROOT/'work/service_principles.json')]
    regions=read(ROOT/'work/service_principle_regions.json')
    verified={}
    skipped=[]
    for source in evidence:
        for key,row in source['pages'].items():
            if row.get('visual_verified') is True:verified.setdefault(key,[]).append(row)
            else:skipped.append(key)
    failures=[];stats=Counter();records=[]
    readers={Path(v['relative_path']).name:PdfReader(v['path']) for v in manifest['indexes']}
    for book in manifest['items']:
        try:
            pdf=PdfReader(book['path'])
            assert book['front_pages']==2,'Opening grew beyond the agreed two pages'
            guide=norm(pdf.pages[1].extract_text())
            for heading in ('공구','교환','정비 원칙','완료'):
                assert norm(heading) in guide,('Preparation/principle guide heading absent',heading)
            details=book['service_details']
            by_page={v['local_page']:v for v in book['page_meta'] if v['kind']=='source'}
            for category in ('tools','parts','principles','completion'):
                for row in details[category]:
                    assert row['pages'] and row['source_refs'],('Unlocated evidence',row)
                    valid_refs={(r['file'],r['page']) for r in row['source_refs']}
                    for p in row['pages']:
                        pm=by_page[p]
                        assert (pm['source_file'],pm['source_page']) in valid_refs,('Wrong booklet evidence page',category,p,row)
                        source_key=f"{pm['source_file']}#{pm['source_page']}"
                        candidates=[e for v in verified.get(source_key,[]) for e in v.get(category,[])
                                    if norm(e['text']) in norm(row['text']) and
                                    (not e.get('condition') or norm(e['condition']) in norm(row['text']))]
                        visible=False
                        for candidate in candidates:
                            positions=([candidate] if category in ('tools','parts') else
                                [v for v in regions['pages'].get(source_key,{}).get(category,[])
                                 if v['text']==candidate['text']])
                            if any(v.get('source_bottom',842)>pm.get('source_top',0) and
                                   v.get('source_top',0)<pm.get('source_bottom',842) for v in positions):visible=True
                        assert visible,('Evidence linked to a fragment without the source statement',source_key,p,row['text'])
                    for ref in row['source_refs']:
                        key=f"{ref['file']}#{ref['page']}"
                        assert key in verified,('Unreviewed source displayed',key)
                        candidates=[e for v in verified[key] for e in v.get(category,[])]
                        assert any(norm(e['text']) in norm(row['text']) for e in candidates),('Changed source summary',key,row)
                    if category=='parts':
                        assert not row.get('part_number'),'An unverified vehicle part number appeared'
                        stats['replacement_rows']+=1
                    stats[category+'_rows']+=1
            where=book['service_summary']['detail_index']
            index=readers[Path(where['file']).name]
            index_record=next(v for v in manifest['indexes'] if Path(v['relative_path']).name==Path(where['file']).name)
            pages=[v['page'] for v in index_record['service_index_pages'] if v.get('book_id')==book['id']]
            assert pages and min(pages)==where['page'],('Guide-to-service-index target differs',where,pages)
            text=norm(' '.join(index.pages[p-1].extract_text() for p in pages))
            for category,rows in details.items():
                for row in rows:
                    assert norm(row['text']) in text,('Detailed evidence omitted from index',category,row['text'])
                    if row.get('scope_note'):assert norm(row['scope_note']) in text,('Equipment applicability lost',row)
                    if category=='parts':assert norm('차량용 주문 품번 미확인') in text,'Unknown part number status omitted'
                    if category=='principles':assert norm(row.get('label','원문 확인')) in text,('Instruction strength omitted',row)
            signal_count=0
            for desc in book['education_pages']:
                if desc['kind']!='source':continue
                signal=desc.get('service_signal')
                assert signal and norm(signal['text']) in norm(pdf.pages[desc['page']-1].extract_text()),('Body service signpost missing',desc['page'])
                if signal['specific']:
                    assert signal['source_key'] in verified,('Unreviewed body signal',signal)
                    signal_count+=1
                pm=by_page[desc['page']]
                assert signal['rect'][1]>pm['clip_rect'][1]+pm['clip_rect'][3],'Service signpost overlaps original content'
            stats['source_pages_with_signposts']+=len(by_page)
            stats['specific_signpost_pages']+=signal_count
            stats['booklets']+=1
            records.append({'id':book['id'],'status':'passed','detail_pages':pages,
                            'rows':{k:len(v) for k,v in details.items()},'specific_signposts':signal_count})
        except Exception as exc:
            failures.append({'id':book['id'],'message':str(exc)})
    report={'status':'passed' if not failures else 'failed','manifest':str(args.manifest),
            'verified_source_pages':len(verified),'unreviewed_sources_not_displayed':sorted(set(skipped)),
            'stats':dict(stats),'records':records,'failures':failures}
    args.report.parent.mkdir(parents=True,exist_ok=True)
    args.report.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({k:v for k,v in report.items() if k not in ('records','unreviewed_sources_not_displayed')},ensure_ascii=False,indent=2))
    return int(bool(failures))


if __name__=='__main__':raise SystemExit(main())

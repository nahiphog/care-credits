"""Reviewed CPD Online metadata correction. Dry run by default; uses DATABASE_URL."""
import argparse,hashlib,json,os,sys,time
from pathlib import Path
from html.parser import HTMLParser
import httpx
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'backend'))
from database import SessionLocal
from portal_models import Course, Audit, SourceDocument, FieldEvidence, fill_course
SLUGS={
 'CPDE76888':'cpde76888-managing-work-related-musculoskeletal-disorders-from-burden-to-recovery',
 'CPDE76887':'cpde76887-beyond-analgesia-advancing-functional-recovery-with-muscle-relaxants',
 'CPDE73115':'cpde73115-module-1-bph-and-ed-can-it-be-managed-discreetly',
 'CPDE73116':'cpde73116-module-2-bph-and-ed-can-it-be-managed-discreetly',
}
class Text(HTMLParser):
 def __init__(self):super().__init__();self.skip=0;self.parts=[]
 def handle_starttag(self,t,a):
  if t in ('script','style'):self.skip+=1
 def handle_endtag(self,t):
  if t in ('script','style'):self.skip=max(0,self.skip-1)
 def handle_data(self,d):
  if not self.skip and d.strip():self.parts.append(d.strip())
def main():
 p=argparse.ArgumentParser();p.add_argument('--apply',action='store_true');args=p.parse_args()
 with SessionLocal() as db:
  for code,slug in SLUGS.items():
   rows=db.query(Course).filter(Course.title.startswith(code)).all()
   if len(rows)!=1:raise RuntimeError(f'{code}: expected exactly one course')
   c=rows[0];url='https://cpdonline.my/courses/'+slug+'/'
   r=httpx.get(url,timeout=30,follow_redirects=True);r.raise_for_status();t=Text();t.feed(r.text);source='\n'.join(t.parts)
   if code not in source or 'Price\nFree' not in source:raise RuntimeError(f'{code}: source no longer supports correction')
   data=dict(c.data);before={k:data.get(k) for k in ('source_url','fee','city','state')}
   if data.get('source_url')==url and data.get('fee')==0:print(code+': already corrected');continue
   if data.get('source_url','').rstrip('/')!='https://cpdonline.my':raise RuntimeError(f'{code}: source changed since review')
   data.update(source_url=url,fee=0)
   evidence=dict(data.get('evidence') or {});evidence['fee']='Price\nFree'
   for field in ('city','state'):
    if not data.get(field):evidence.pop(field,None)
   data['evidence']=evidence
   data['source_text']=(data.get('source_text') or '')+'\n\nReviewed course page: '+url+'\n'+source
   data['supporting_sources']=list(dict.fromkeys([*(data.get('supporting_sources') or []),'https://cpdonline.my',url]))
   print(json.dumps({'course':code,'before':before,'after':{'source_url':url,'fee':0},'apply':args.apply}))
   if args.apply:
    now=time.time();fill_course(c,data);c.updated_at=now
    doc=SourceDocument(canonical_url=url,content_hash=hashlib.sha256(source.encode()).hexdigest(),retrieved_at=now,extraction_status='manual_review',title=c.title,snippet=source[:1000]);db.add(doc);db.flush()
    db.add(FieldEvidence(course_id=c.id,source_document_id=doc.id,field_name='fee',excerpt='Price\nFree',reviewed_by='website-audit-maintenance',reviewed_at=now))
    db.add(Audit(account_id='website-audit-maintenance',action='course_metadata_corrected',entity_id=c.id,changed={'before':before,'after':{'source_url':url,'fee':0},'reason':'Course-specific provider page confirms Price Free. Publication timestamps are not event dates; points/currency remain unknown.'}))
  if args.apply:db.commit()
if __name__=='__main__':main()

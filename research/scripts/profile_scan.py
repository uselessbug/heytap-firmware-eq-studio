import struct,math,json
from pathlib import Path
root=Path('analysis/firmware');out=Path('analysis/profiles');out.mkdir(exist_ok=True)
for p in root.glob('*/raw.bin'):
 b=p.read_bytes();candidates=[]
 for o in range(0x700000,min(len(b)-32,0x780000),4):
  l,r,n=struct.unpack_from('<ffI',b,o)
  if not all(math.isfinite(x) and -60<=x<=30 for x in [l,r]) or not 1<=n<=32:continue
  filters=[]
  for k in range(n):
   if o+12+(k+1)*16>len(b):break
   typ,g,fc,q=struct.unpack_from('<Ifff',b,o+12+k*16)
   if not(typ<=6 and all(math.isfinite(x) for x in [g,fc,q]) and -40<=g<=40 and 0.1<=fc<=48000 and 0.001<=q<=100):break
   filters.append({'type_id':typ,'gain':g,'fc':fc,'q':q})
  if len(filters)!=n:continue
  refs=[]
  for base in [0x10028000,0x30028000]:
   val=struct.pack('<I',base+o);at=-1
   while True:
    at=b.find(val,at+1)
    if at<0:break
    if at%4==0:refs.append({'at':at,'base':base})
  candidates.append({'offset':o,'gain0':l,'gain1':r,'count':n,'filters':filters,'pointer_refs':refs})
 (out/(p.parent.name+'.json')).write_text(json.dumps(candidates,indent=2))
 print(p.parent.name,'candidates',len(candidates),'withrefs',sum(bool(c['pointer_refs']) for c in candidates))
 for c in candidates[:12]:print(hex(c['offset']),c['gain0'],c['gain1'],c['count'],[(hex(v['at']),hex(v['base'])) for v in c['pointer_refs']])

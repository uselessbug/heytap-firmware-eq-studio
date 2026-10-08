from pathlib import Path
from loguru import logger
logger.remove()
from androguard.core.dex import DEX
out=Path('analysis/apk/dex_evidence');out.mkdir(exist_ok=True)
for f in sorted(Path('analysis/apk').glob('*.dex')):
 d=DEX(f.read_bytes());n=0
 for c in d.get_classes():
  name=c.get_name()
  target=any(k in name for k in ['FirmwareFileDO','LocalFirmwareImporter','/btsdk/ota/','/protocol/upgrade/'])
  hits=[]
  for m in c.get_methods():
   if m.get_code() is None:continue
   ins=list(m.get_instructions())
   if any(any(k in i.get_output() for k in ['OPKG','opkg parse','ap.bin','headerLength','sectionLength']) for i in ins):hits.append(m.get_name())
  if target or hits:
   lines=[f'{f.name}: {name}',f'hits={hits}']
   for field in c.get_fields():lines.append('FIELD '+field.get_name()+' '+field.get_descriptor())
   for m in c.get_methods():
    lines.append('\nMETHOD '+m.get_name()+m.get_descriptor())
    if m.get_code():
     p=0
     for i in m.get_instructions():
      lines.append(f'{p:04x} {i.get_name()} {i.get_output()}');p+=i.get_length()
   p=out/(name.strip('L;').replace('/','_')+'.txt');p.write_text('\n'.join(lines))
   print(f.name,name,'hits=',hits);n+=1
 print(f.name,'classes',len(d.get_classes()),'selected',n,flush=True)

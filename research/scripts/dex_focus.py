from pathlib import Path
from loguru import logger
logger.remove()
from androguard.core.dex import DEX
out=Path('analysis/apk/dex_evidence')
for f in sorted(Path('analysis/apk').glob('*.dex')):
 d=DEX(f.read_bytes())
 for c in d.get_classes():
  name=c.get_name();source=d.get_cm_string(c.get_source_file_idx()) if c.get_source_file_idx()!=0xffffffff else ''
  if not (any(k in str(source) for k in ['FirmwareFileDO','FirmwareUtils','Ota','OTA','UpgradeStateMachine','FirmwareRepositoryClientImpl','FileUtils']) or name in ['Lcom/oplus/melody/common/util/q;','Ly8/a;','Ly8/d;']):continue
  print(f.name,name,'source=',str(source)[:100],flush=True)
  lines=[f'{f.name}: {name}',f'source={str(source)[:200]}']
  for field in c.get_fields():lines.append('FIELD '+field.get_name()+' '+field.get_descriptor())
  for m in c.get_methods():
   lines.append('\nMETHOD '+m.get_name()+m.get_descriptor())
   if m.get_code():
    p=0
    for i in m.get_instructions():
     lines.append(f'{p:04x} {i.get_name()} {i.get_output()}');p+=i.get_length()
  (out/(name.strip('L;').replace('/','_')+'.txt')).write_text('\n'.join(lines))

#!/usr/bin/env python3
"""Extract frequency-response payloads only; exclude HAR headers and cookies."""
import argparse
import base64
import csv
import json
from pathlib import Path
import re


def extract(path,output):
    har=json.loads(Path(path).read_text())
    out=Path(output);out.mkdir(parents=True,exist_ok=True)
    manifest=[]
    for entry in har['log']['entries']:
        content=entry['response']['content']
        if 'html' not in content.get('mimeType','').lower():continue
        text=content.get('text','')
        if content.get('encoding')=='base64':text=base64.b64decode(text).decode('utf-8')
        match=re.search(r'window\.__INITIAL_DATA__\s*=\s*',text)
        if not match:continue
        payload,end=json.JSONDecoder().raw_decode(text[match.end():].lstrip())
        data=payload['Data']
        for i,curve in enumerate(data['data']):
            title=curve.get('title','')
            if not ('B&K5128' in title.replace(' ','') and 'THD' not in title):continue
            points=[]
            for row in curve['data']:
                try:values=[float(row[0]),float(row[1])]
                except (ValueError,TypeError):continue
                if values[0]>0:points.append(values)
            dest=out/f'fr_{i}.csv'
            with dest.open('w',newline='') as f:
                w=csv.writer(f);w.writerow(['frequency_hz','spl_db']);w.writerows(points)
            manifest.append({'name':title,'csv':dest.name,'points':len(points),
                             'url':entry['request']['url'],'title':data.get('title'),
                             'date':data.get('time'),'firmware_version':'not identified in the captured payload'})
    if not manifest:raise ValueError('No recognized ReaLab FR payload found')
    (out/'manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n')
    return manifest


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('har');p.add_argument('output')
    a=p.parse_args();print(json.dumps(extract(a.har,a.output),ensure_ascii=False,indent=2))

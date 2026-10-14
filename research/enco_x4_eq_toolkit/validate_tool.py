#!/usr/bin/env python3
"""Integration checks using the two official input packages (not bundled)."""
import argparse
import copy
import json
from pathlib import Path
import tempfile

import numpy as np
import eq_tool as e
import opkg_tool as o


def expect_rejection(fn):
    try:
        fn()
    except ValueError:
        return
    raise AssertionError('Expected rejection')


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('official112');p.add_argument('official116');p.add_argument('--output',required=True)
    a=p.parse_args()
    root=Path(__file__).parent
    original=e.parse_eq(root/'examples/Technics-AZ80.txt')
    optimized=e.parse_eq(root/'examples/Technics-AZ80-Optimized.txt')
    assert len(original['graphic_points'])==127 and not original['personal_peq']
    assert len(optimized['graphic_points'])==127 and len(optimized['personal_peq'])==5
    raw_difference=float(np.max(np.abs(np.asarray(original['graphic_points'])[:,1]-np.asarray(optimized['graphic_points'])[:,1])))
    assert raw_difference < .050001
    freq=np.geomspace(20,20000,2048)
    assert np.max(np.abs(e.correction(optimized,freq)-e.correction(original,freq))) > 1
    allpass=e.response([{'type_id':5,'gain':0,'fc':1000,'q':.7}],freq)
    assert np.max(np.abs(allpass)) < 1e-9
    results={'parsing_pass':True,'raw_rounding_max_difference_db':raw_difference,'all_5_peqs_applied':True,
             'allpass_magnitude_pass':True,'packages':[]}
    samples=[json.loads((root/f'examples/{name}_plan116.json').read_text()) for name in ('az80','optimized')]
    with tempfile.TemporaryDirectory(prefix='enco-eq-verify-') as tmp:
        for version,path in [(112,a.official112),(116,a.official116)]:
            before_hash=o.sha(Path(path).read_bytes())
            item=o.load(path);profiles=o.profiles(item['raw'])
            plans=copy.deepcopy(samples)
            for plan in plans:
                # Relocate identical records, never copy absolute offsets between versions.
                plan.update(firmware_sha256=item['summary']['file_sha256'],raw_sha256=o.sha(item['raw']),
                            raw_size=len(item['raw']),bank_offset=profiles['bank_offset'])
                for c in plan['records']:
                    c['raw_offset']=profiles['profiles'][c['target_profile']]['raw_offset']
            out=Path(tmp)/f'validation{version}.opkg'
            report=e.apply_plans(path,plans,out)
            parsed=o.load(out)
            diff=o.compare(item,parsed)
            assert diff['changed_profile_count']==72
            assert report['outside_target_records_unchanged']
            for c in [c for plan in plans for c in plan['records']]:
                rec=parsed['raw'][c['raw_offset']:c['raw_offset']+300]
                assert rec==e.pack_record(c['record'])
            expect_rejection(lambda:e.apply_plans(path,[plans[0],plans[0]],Path(tmp)/'overlap.opkg'))
            altered=copy.deepcopy(plans[0]);altered['records'][0]['record']['filters'][0]['q']+=.2
            expect_rejection(lambda:e.apply_plans(path,[altered],Path(tmp)/'changed-hp.opkg'))
            altered=copy.deepcopy(plans[0])
            altered['records'][18]['record']['filters'][1]['gain']+=10
            for m in altered['records'][18]['record']['metrics'].values():
                m['path_within_30_db_of_peak']={'rms_db':0,'max_abs_db':0}
            expect_rejection(lambda:e.apply_plans(path,[altered],Path(tmp)/'false-metrics.opkg'))
            damaged=bytearray(item['data']);damaged[-8]^=1
            expect_rejection(lambda:o.parse(bytes(damaged)))
            assert o.sha(Path(path).read_bytes())==before_hash
            report.update(version=version,changed_profile_count=diff['changed_profile_count'],
                          corrupted_opkg_rejected=True,overlapping_plans_rejected=True,
                          modified_highpass_rejected=True,forged_fit_metrics_rejected=True,
                          original_input_unchanged=True)
            report.pop('output')
            results['packages'].append(report)
        too_many=copy.deepcopy(samples[0]['records'][0]['record'])
        too_many['filters'].append(too_many['filters'][0])
        expect_rejection(lambda:e.validate_record(too_many))
    results['over_capacity_rejected']=True
    Path(a.output).write_text(json.dumps(results,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps(results,ensure_ascii=False,indent=2))


if __name__=='__main__':main()

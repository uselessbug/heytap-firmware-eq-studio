#!/usr/bin/env python3
"""Execute the actual 112/116 ARM selector and coefficient generator in Unicorn.

Optional evidence reproduction dependencies: capstone and unicorn.
Math library calls are intercepted with Python math functions, rounded to
float32 at the ABI boundary; firmware filter arithmetic and dispatch execute.
"""
import argparse
import json
import math
from pathlib import Path
import struct

from capstone import Cs, CS_ARCH_ARM, CS_MODE_THUMB, CS_MODE_MCLASS
from unicorn import Uc, UC_ARCH_ARM, UC_MODE_THUMB, UC_MODE_MCLASS, UC_HOOK_CODE
from unicorn.arm_const import (UC_CPU_ARM_CORTEX_M4, UC_ARM_REG_SP, UC_ARM_REG_PC,
    UC_ARM_REG_LR, UC_ARM_REG_R0, UC_ARM_REG_R1, UC_ARM_REG_S0, UC_ARM_REG_S1,
    UC_ARM_REG_S2, UC_ARM_REG_C1_C0_2, UC_ARM_REG_FPEXC)
import numpy as np

from eq_tool import coefficients, PRESETS, ANC_POSITIONS
import opkg_tool as opkg

BASE = 0x10028000
VARIANTS = {
    8717764: {"version":112, "dispatch":0x147c4c, "math":{0x102c1f48:"pow",0x102c2270:"sin",0x102c07b0:"cos",0x102c2624:"sqrt"}},
    8650680: {"version":116, "dispatch":0x14a60c, "math":{0x102c4ac8:"pow",0x102c4df0:"sin",0x102c3330:"cos",0x102c51a4:"sqrt"}},
}


def bits(value):
    return struct.unpack('<I', struct.pack('<f',value))[0]


def number(value):
    return struct.unpack('<f',struct.pack('<I',value))[0]


def verify(path):
    data = Path(path).read_bytes()
    raw = opkg.parse(data)['raw'] if data[:4] == b'OPKG' else data
    variant = VARIANTS[len(raw)]
    md = Cs(CS_ARCH_ARM, CS_MODE_THUMB | CS_MODE_MCLASS)
    ins = list(md.disasm(raw[0x30e78:0x30eb6], BASE+0x30e78))
    calls = [int(i.op_str.lstrip('#'),16) for i in ins if i.mnemonic == 'bl']
    getter, log = calls[0], calls[1]
    u = Uc(UC_ARCH_ARM, UC_MODE_THUMB | UC_MODE_MCLASS)
    u.ctl_set_cpu_model(UC_CPU_ARM_CORTEX_M4)
    u.mem_map(0x10000000,0x1000000); u.mem_write(BASE,raw)
    u.mem_map(0x20000000,0x400000)
    u.reg_write(UC_ARM_REG_C1_C0_2,0x00f00000)
    u.reg_write(UC_ARM_REG_FPEXC,0x40000000)
    state = [0]

    def hook(uc,address,size,user):
        if address == getter:
            uc.reg_write(UC_ARM_REG_R0,state[0])
        elif address == log:
            pass
        elif address in variant['math']:
            f = variant['math'][address]
            a = number(uc.reg_read(UC_ARM_REG_S0))
            b = number(uc.reg_read(UC_ARM_REG_S1))
            result = math.pow(a,b) if f == 'pow' else getattr(math,f)(a)
            uc.reg_write(UC_ARM_REG_S0,bits(result))
        else:
            return
        uc.reg_write(UC_ARM_REG_PC,uc.reg_read(UC_ARM_REG_LR))

    u.hook_add(UC_HOOK_CODE,hook)
    def run(start):
        u.reg_write(UC_ARM_REG_SP,0x20300000)
        u.reg_write(UC_ARM_REG_LR,0x20001001)
        u.emu_start(start|1,0x20001000,count=5000)
        assert u.reg_read(UC_ARM_REG_PC) == 0x20001000, 'Firmware function did not return'

    index_rows = []
    for anc in range(16):
        row = {'anc_internal_id':anc,'table_indices':{}}
        for eq in [0,1,2,3,7]:
            state[0] = anc
            u.reg_write(UC_ARM_REG_R0,eq)
            run(BASE+0x30e78)
            actual = u.reg_read(UC_ARM_REG_R0)
            start = next(p['start'] for p in PRESETS.values() if p['protocol_id'] == eq)
            expected = start+ANC_POSITIONS[anc] if anc in ANC_POSITIONS else 8
            assert actual == expected,(anc,eq,actual,expected)
            row['table_indices'][str(eq)] = actual
        index_rows.append(row)
    extra_base = struct.unpack_from('<I',raw,0x31070)[0]
    u.mem_write(extra_base+0x524,b'\1')
    u.reg_write(UC_ARM_REG_R0,0)
    run(BASE+0x30e78)
    assert u.reg_read(UC_ARM_REG_R0) == 45
    u.mem_write(extra_base+0x524,b'\0')
    samples = []
    max_error = 0.0
    for typ in range(6):
        for gain,fc,q,fs in [(3,1000,.7,48000),(-6,250,1.5,44100),(4,5800,2,96000)]:
            u.reg_write(UC_ARM_REG_R0,typ);u.reg_write(UC_ARM_REG_R1,0x20000100)
            for reg,value in [(UC_ARM_REG_S0,gain),(UC_ARM_REG_S1,fc/fs),(UC_ARM_REG_S2,q)]:
                u.reg_write(reg,bits(value))
            run(BASE+variant['dispatch'])
            actual = np.array(struct.unpack('<6f',u.mem_read(0x20000100,24)))
            f = {'type_id':typ,'gain':gain,'fc':fc,'q':q}
            sos = coefficients([f],fs)[0]
            expected = sos[[3,4,5,0,1,2]]
            err = float(np.max(np.abs(actual-expected)))
            max_error = max(max_error,err)
            assert err < 2e-6,(typ,gain,fc,q,actual,expected,err)
            samples.append({'type_id':typ,'gain':gain,'fc':fc,'q':q,'fs':fs,'firmware_coefficients':actual.tolist(),'max_abs_difference':err})
    return {'version':variant['version'],'raw_sha256':opkg.sha(raw),'selector':hex(BASE+0x30e78),
            'anc_getter':hex(getter),'dispatcher':hex(BASE+variant['dispatch']),
            'index_rows':index_rows,'special_slot':45,'coefficient_samples':samples,
            'max_coefficient_error':max_error,'all_assertions_passed':True,
            'scope':'Dispatch and arithmetic are actual firmware; transcendental math calls are ABI-compatible substitutes. No physical device execution.'}


if __name__ == '__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('firmware',nargs='+');p.add_argument('--output',required=True)
    a=p.parse_args()
    r=[verify(f) for f in a.firmware]
    Path(a.output).write_text(json.dumps(r,indent=2)+'\n')
    print(json.dumps([{'version':x['version'],'max_coefficient_error':x['max_coefficient_error'],'passed':True} for x in r],indent=2))

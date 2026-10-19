#!/usr/bin/env python3
"""Reproduce predeclared real-artwork damage cases and independent comparisons."""
import hashlib
import json
from pathlib import Path
import sys
import tempfile
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from desk.core import Engine, ROOT
CASES = {'byte-corruption': True, 'truncation': True, 'missing-file': True,
         'insufficient-recovery': False, 'damaged-recovery': False}
def main():
    source = ROOT / 'data/twemoji'
    originals = {p.name:p.read_bytes() for p in sorted(source.iterdir())}
    source_hashes = {n:hashlib.sha256(raw).hexdigest() for n,raw in originals.items()}
    results = dict(protocol='docs/evaluation-protocol.md', deterministic=True, random_seed=None,
                   inputs=json.loads((ROOT/'data/sources.json').read_text()),
                   predictions=CASES, cases=[])
    with tempfile.TemporaryDirectory(prefix='parity-evaluation-') as tmp:
        engine=Engine(tmp,source)
        package=engine.create(list(originals),30,256)
        results['package']=package
        results['baseline']=engine.evaluate(package['id'],source)
        assert results['baseline']['status']=='verified-intact'
        for scenario, expected in CASES.items():
            demo=engine.damage_demo(package['id'],scenario)
            inspection=engine.evaluate(package['id'],demo['candidate'],False,demo['recovery_folder'])
            repair=engine.evaluate(package['id'],demo['candidate'],True,demo['recovery_folder'])
            success=repair['status']=='verified-restored'
            assert success == expected, (scenario,repair)
            assert repair['inputs_unchanged'] and repair['recovery_inputs_unchanged'] and repair['preserved_originals_unchanged']
            assert {r['name'] for r in repair['output_files']}==set(originals)
            comparisons=[]
            if success:
                for name, raw in originals.items():
                    output=(Path(repair['output_directory'])/name).read_bytes()
                    sha=hashlib.sha256(output).hexdigest()
                    assert raw==output and sha==source_hashes[name]
                    comparisons.append(dict(name=name,byte_for_byte_equal=True,sha256=sha))
            else:
                assert repair['status']=='insufficient-recovery' and repair['output_directory'] is None
            results['cases'].append(dict(scenario=scenario,expected_success=expected,mutation=demo['mutation'],
                                         inspection=inspection,repair=repair,independent_comparisons=comparisons))
            if scenario=='missing-file':
                (ROOT/'results/sample-report.json').write_text((Path(tmp)/repair['id']/'report.json').read_text())
                (ROOT/'results/sample-report.html').write_text((Path(tmp)/repair['id']/'report.html').read_text())
            print(f'{scenario}: {repair["status"]}; expectation matched')
        assert {p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in source.iterdir()}==source_hashes
        results['unchanged_original_source_hashes']=source_hashes
    (ROOT/'results/evaluation.json').write_text(json.dumps(results,indent=2)+'\n')
    print('All expected outcomes matched; original source hashes unchanged.')
if __name__=='__main__':main()

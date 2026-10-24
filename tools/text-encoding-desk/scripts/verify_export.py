"""Independently reopen browser or sample ZIP output with iconv and Python."""
import hashlib,json,subprocess,sys,zipfile
from pathlib import Path
z=zipfile.ZipFile(sys.argv[1]);m=json.loads(z.read('manifest.json'));assert m['complete']
expected=[r for r in json.loads(Path('demo/sources.json').read_text()) if r['codec']]
assert len(m['files'])==len(expected)
for source,row in zip(expected,m['files']):
 b=Path('demo',source['name']).read_bytes();assert hashlib.sha256(b).hexdigest()==source['sha256']==row['source_hash']
 out=z.read(row['output']);assert hashlib.sha256(out).hexdigest()==row['output_hash']
 independent=subprocess.run(['iconv','-f',source['codec'],'-t','UTF-8'],input=b,capture_output=True,check=True).stdout
 assert out==independent
 reopened=subprocess.run(['iconv','-f','UTF-8','-t','UTF-32LE'],input=out,capture_output=True,check=True).stdout
 assert reopened==out.decode('utf-8').encode('utf-32-le')
 print(source['name'],len(b),'→',len(out),'bytes; iconv and independent reopening PASS')

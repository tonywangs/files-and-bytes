import base64, io, json, subprocess, unittest, zipfile
from pathlib import Path
import app

def f(b,codec='utf-8',name='same.txt'):
 return dict(data=base64.b64encode(b).decode(),hash=app.digest(b),codec=codec,name=name)
def archive(files):
 z=zipfile.ZipFile(io.BytesIO(app.export(files)));return z,json.loads(z.read('manifest.json'))
class Core(unittest.TestCase):
 def test_controls(self):
  for codec in app.CODECS:
   text='\ufeffA\r\nB\rC\n\ufeff\ufffd😀' if codec.startswith('utf') else 'café\r\n'
   if codec in ('cp1251','koi8-r'):text='Привет\r\n'
   b=text.encode(codec); z,m=archive([f(b,codec)])
   self.assertTrue(m['complete']);out=z.read(m['files'][0]['output'])
   other=subprocess.run(['iconv','-f',{'utf-16-le':'UTF-16LE','utf-16-be':'UTF-16BE'}.get(codec,codec),'-t','UTF-8'],input=b,check=True,capture_output=True).stdout
   self.assertEqual(out,other);self.assertEqual(out.decode('utf-8'),text)
 def test_failures_and_accounting(self):
  rows=[f(b'\xff'),f(b'\x00','utf-16-le'),f(b'x','unknown'),dict(f(b'x'),excluded=True),f(b'x'),f(b'y')]
  z,m=archive(rows);self.assertFalse(m['complete']);self.assertEqual([r['status'] for r in m['files']],['failed','failed','unsupported','excluded','converted','converted'])
  self.assertEqual(len(z.namelist()),3)
  r=f(b'x');r['hash']='0'*64;self.assertEqual(archive([r])[1]['files'][0]['status'],'failed')
 def test_inspection(self):
  p=app.inspect(f(b'\x80'))['previews'];self.assertIn('error',p['utf-8']);self.assertNotEqual(p['windows-1252']['text'],p['iso-8859-1']['text'])
  self.assertEqual(app.inspect(f('�'.encode()))['previews']['utf-8']['literal_replacements'],1)
 def test_byte_order_and_malformed(self):
  b=b'\x41\x00';self.assertEqual(app.decode(b,'utf-16-le'),'A');self.assertNotEqual(app.decode(b,'utf-16-be'),'A')
  for b,c in [(b'\x00\xd8','utf-16-le'),(b'\xd8\x00','utf-16-be'),(b'\x81','windows-1252'),(b'\xed\xa0\x80','utf-8')]:
   self.assertEqual(archive([f(b,c)])[1]['files'][0]['status'],'failed')
 def test_limits(self):
  for rows in [[],[None],[f(b'x')]*33,[f(b'x'*2097152)]*5]:
   with self.assertRaises(ValueError):app.export(rows)
  self.assertEqual(archive([f(b'x'*2097153)])[1]['files'][0]['status'],'failed')
 def test_real_sources(self):
  rows=json.loads(Path('demo/sources.json').read_text());files=[]
  for r in rows:
   b=Path('demo',r['name']).read_bytes();self.assertEqual(app.digest(b),r['sha256'])
   if r['codec']:files.append(f(b,r['codec'],r['name']))
  z,m=archive(files);self.assertTrue(m['complete'])
  for source,result in zip(files,m['files']):
   b=base64.b64decode(source['data']);out=z.read(result['output']);other=subprocess.run(['iconv','-f',source['codec'],'-t','UTF-8'],input=b,capture_output=True,check=True).stdout
   self.assertEqual(out,other);self.assertEqual(app.digest(out),result['output_hash']);self.assertEqual(app.digest(b),source['hash'])
if __name__=='__main__':unittest.main()

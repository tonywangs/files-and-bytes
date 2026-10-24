"""Run the real browser workflow against an isolated temporary local server."""
import os,subprocess,sys,time,urllib.request
port='18766';env=dict(os.environ,PORT=port,DESK_URL='http://127.0.0.1:'+port)
p=subprocess.Popen([sys.executable,'app.py'],env=env,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
try:
 for _ in range(50):
  if p.poll() is not None:raise RuntimeError('Test server failed to start (port 18766 must be free)')
  try:urllib.request.urlopen(env['DESK_URL'],timeout=.2).close();break
  except OSError:time.sleep(.1)
 else:raise RuntimeError('Server did not become ready')
 subprocess.run(['node','tests/browser.cjs'],env=env,check=True)
finally:
 p.terminate();p.wait(timeout=5)

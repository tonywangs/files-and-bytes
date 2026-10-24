import json
from pathlib import Path
import tempfile
import threading
import unittest
from urllib.error import HTTPError
from urllib.request import Request, urlopen
from desk.core import Engine, ROOT
from desk.server import make_server

class LocalServerTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.server=make_server(Engine(self.temp.name,ROOT/'data/twemoji'),0)
        self.thread=threading.Thread(target=self.server.serve_forever,daemon=True)
        self.thread.start()
        self.url=f'http://127.0.0.1:{self.server.server_port}'
    def tearDown(self):
        self.server.shutdown();self.server.server_close();self.thread.join();self.temp.cleanup()
    def request(self,path,body=None,headers=None):
        req=Request(self.url+path,data=None if body is None else json.dumps(body).encode(),headers=headers or {})
        return urlopen(req,timeout=5)
    def test_origin_host_and_token_guards(self):
        state=json.load(self.request('/api/state'))
        for headers in [{'Host':'attacker.example'}, {'Origin':'https://attacker.example'}, {'Sec-Fetch-Site':'cross-site'}]:
            with self.assertRaises(HTTPError):self.request('/api/state',headers=headers)
        for headers in [{}, {'Content-Type':'application/json','X-Desk-Token':'wrong'},
                        {'Content-Type':'text/plain','X-Desk-Token':state['token']}]:
            with self.assertRaises(HTTPError):self.request('/api/cancel',{},headers)
        result=json.load(self.request('/api/cancel',{}, {'Content-Type':'application/json','X-Desk-Token':state['token']}))
        self.assertTrue(result['cancel_requested'])
    def test_no_arbitrary_paths_or_unverified_downloads(self):
        for path in ['/../../etc/passwd','/download?kind=restored&id=repair-'+'a'*32+'&name=missing.svg',
                     '/download?kind=report&id=../../etc&name=passwd','/art/../README.md']:
            with self.assertRaises(HTTPError):self.request(path)
        response=self.request('/')
        self.assertIn("frame-ancestors 'none'",response.headers['Content-Security-Policy'])
        self.assertEqual(response.headers['X-Content-Type-Options'],'nosniff')
        self.assertIn(b'Create recovery package',response.read())
    def test_one_job_at_a_time(self):
        app=self.server.app
        app.lock.acquire()
        try:
            state=json.load(self.request('/api/state'))
            with self.assertRaises(HTTPError) as result:
                self.request('/api/create',{'names':['1f600.svg'],'redundancy':30,'block_size':256},
                             {'Content-Type':'application/json','X-Desk-Token':state['token']})
            self.assertIn(b'Another operation',result.exception.read())
        finally:app.lock.release()

if __name__=='__main__':unittest.main()

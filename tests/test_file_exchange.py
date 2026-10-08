import http.client
import importlib.util
import socket
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.parse import quote

spec = importlib.util.spec_from_file_location('file_control', Path(__file__).resolve().parents[1] / 'session-control.py')
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)

class FileExchangeTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.root_patch = patch.object(m, 'DOCUMENTS_DIR', Path(self.directory.name))
        self.mirror_patch = patch.object(m, 'mirror_document_to_browser', return_value=(True, None))
        self.root_patch.start(); self.mirror_patch.start()
        self.server = m.ThreadingHTTPServer(('127.0.0.1', 0), m.SessionControlHandler)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def tearDown(self):
        self.server.shutdown(); self.server.server_close()
        self.root_patch.stop(); self.mirror_patch.stop(); self.directory.cleanup()

    def upload(self, name, content):
        c = http.client.HTTPConnection(*self.server.server_address)
        c.request('POST', '/api/files/upload', content, {'Content-Type': 'application/octet-stream', 'X-File-Name': quote(name)})
        r = c.getresponse(); result = (r.status, r.read()); c.close(); return result

    def test_unicode_roundtrip_and_collision(self):
        content = bytes(range(256)) * 8192
        self.assertEqual(self.upload('отчёт.bin', content)[0], 201)
        self.assertEqual(self.upload('отчёт.bin', b'second')[0], 201)
        self.assertEqual((Path(self.directory.name) / 'отчёт.bin').read_bytes(), content)
        self.assertEqual((Path(self.directory.name) / 'отчёт (2).bin').read_bytes(), b'second')
        c = http.client.HTTPConnection(*self.server.server_address)
        c.request('GET', '/api/files/download?name=' + quote('отчёт.bin'))
        r = c.getresponse(); self.assertEqual(r.status, 200); self.assertEqual(r.read(), content); c.close()

    def test_invalid_name_and_limit_leave_no_files(self):
        self.assertEqual(self.upload('../bad', b'bad')[0], 400)
        with patch.object(m, 'MAX_UPLOAD_BYTES', 2):
            self.assertEqual(self.upload('big', b'big')[0], 413)
        self.assertEqual(list(Path(self.directory.name).iterdir()), [])

    def test_interrupted_body_is_removed(self):
        with socket.create_connection(self.server.server_address) as c:
            c.sendall(b'POST /api/files/upload HTTP/1.0\r\nContent-Type: application/octet-stream\r\nX-File-Name: partial\r\nContent-Length: 100\r\n\r\nx')
            c.shutdown(socket.SHUT_WR)
            while c.recv(4096): pass
        self.assertEqual(list(Path(self.directory.name).iterdir()), [])

    def delete(self, payload, container=False):
        import json
        c = http.client.HTTPConnection(*self.server.server_address)
        c.request('POST', '/api/container/files/delete' if container else '/api/files/delete', json.dumps(payload), {'Content-Type': 'application/json'})
        r = c.getresponse(); result = (r.status, json.loads(r.read())); c.close(); return result

    def test_delete_one_then_all_preserves_directories_and_symlinks(self):
        root = Path(self.directory.name)
        (root / 'one').write_text('one'); (root / 'two').write_text('two')
        (root / 'folder').mkdir(); (root / 'folder' / 'keep').write_text('keep')
        (root / 'link').symlink_to(root / 'folder' / 'keep')
        status, payload = self.delete({'name': 'one'})
        self.assertEqual(status, 200); self.assertEqual(payload['deleted'], ['one'])
        self.assertTrue((root / 'two').exists())
        status, payload = self.delete({'all': True})
        self.assertEqual(status, 200); self.assertEqual(payload['deleted'], ['two'])
        self.assertTrue((root / 'folder' / 'keep').exists()); self.assertTrue((root / 'link').is_symlink())

    def test_delete_rejects_traversal_and_container_root(self):
        self.assertEqual(self.delete({'name': '../outside'})[0], 400)
        self.assertEqual(self.delete({'all': True, 'directory': '/'}, container=True)[0], 400)

    def test_container_delete_script_preserves_nested_files(self):
        import json
        import subprocess
        root = Path(self.directory.name)
        (root / 'file').write_text('file'); (root / 'dir').mkdir()
        (root / 'dir' / 'keep').write_text('keep')
        with patch.object(m, 'docker_exec', side_effect=lambda args, **kw: subprocess.run(args[:3] + [str(root.resolve())] + args[4:], capture_output=True, text=True)):
            status, payload = self.delete({'all': True, 'directory': '/config/Downloads'}, container=True)
        self.assertEqual(status, 200); self.assertEqual(payload['deleted'], ['file'])
        self.assertTrue((root / 'dir' / 'keep').exists())

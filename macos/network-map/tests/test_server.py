import importlib.util
import json
import pathlib
import tempfile
import unittest
from unittest import mock

SERVER=pathlib.Path(__file__).resolve().parents[1]/'server.py'
spec=importlib.util.spec_from_file_location('networkmap',SERVER)
m=importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)


class StatusTests(unittest.TestCase):
    def test_topology_references(self):
        ids={node[0] for node in m.NODE_DEFS}
        self.assertEqual(len(ids),len(m.NODE_DEFS))
        for a,b,_,_ in m.EDGES:
            self.assertIn(a,ids)
            self.assertIn(b,ids)
        for sid,node,_,kind,_,_,_ in m.SERVICES:
            self.assertIn(node,ids)
            self.assertIn(kind,('http','tcp'))
        self.assertEqual(len({x[0] for x in m.SERVICES}),len(m.SERVICES))

    def test_probe_unauthenticated_http_is_responsive(self):
        from urllib.error import HTTPError
        for code,status in ((401,'up'),(403,'up'),(404,'degraded'),(429,'degraded'),(502,'down')):
            err=HTTPError('http://127.0.0.1/test',code,'',{},None)
            with self.subTest(http=code),mock.patch.object(m.OPENER,'open',side_effect=err):
                self.assertEqual(m.probe('http','http://127.0.0.1/test')['status'],status)

    def test_health_rollup(self):
        self.assertEqual(m.summarize_node([{'node':'n','status':'up'},{'node':'n','status':'down'}],'n')[0],'degraded')
        self.assertEqual(m.summarize_node([{'node':'n','status':'degraded'}],'n')[0],'degraded')
        self.assertEqual(m.summarize_node([],'unknown')[0],'unknown')

    def test_history_records_service_and_node_transitions(self):
        with tempfile.TemporaryDirectory() as t, mock.patch.object(m,'DB',pathlib.Path(t)/'health.sqlite3'):
            first={'nodes':[{'id':'linux','status':'up','latency_ms':3}],
                   'services':[{'id':'ssh','status':'up','ms':2,'detail':'available'}]}
            second={'nodes':[{'id':'linux','status':'down','latency_ms':None}],
                    'services':[{'id':'ssh','status':'down','ms':None,'detail':'timeout'}]}
            m.record(first,None)
            m.record(second,first)
            report=m.get_history()
            keys={(r['node'],r['status']) for r in report['events']}
            self.assertIn(('linux','down'),keys)
            self.assertIn(('svc:ssh','down'),keys)
            self.assertIn('svc:ssh',report['trends'])


if __name__=='__main__':unittest.main()

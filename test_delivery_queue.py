"""Offline tests: no requests are sent to BYT or Medinet."""
import sqlite3
import tempfile
import threading
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from delivery_queue import DeliveryQueue, enqueue, transaction


class QueueTest(unittest.TestCase):
    def test_fifo_duplicate_clicks_and_one_worker(self):
        with tempfile.TemporaryDirectory() as directory:
            db = Path(directory) / 'test.db'
            def connect():
                return sqlite3.connect(db, timeout=10)
            with transaction(connect) as c:
                c.execute('CREATE TABLE submissions(id TEXT PRIMARY KEY,state TEXT,survey_form TEXT,answers_json TEXT,byt_message TEXT,sent_at TEXT,sent_by TEXT)')
                c.execute('CREATE TABLE delivery_queue(seq INTEGER PRIMARY KEY AUTOINCREMENT,submission_id TEXT UNIQUE,requested_by TEXT)')
                for rid in ['a','b','c','d']:
                    c.execute("INSERT INTO submissions(id,state,survey_form,answers_json) VALUES(?,'approved','4','{}')", (rid,))
            # Concurrent duplicate requests for a single record produce one queue entry.
            with ThreadPoolExecutor(max_workers=8) as pool:
                list(pool.map(lambda _: enqueue(connect,'a','admin'),range(20)))
            for rid in ['b','c','d']: enqueue(connect,rid,'admin')
            with transaction(connect) as c:
                self.assertEqual(c.execute('SELECT COUNT(*) FROM delivery_queue').fetchone()[0],4)
            active=0; maximum=0; delivered=[];lock=threading.Lock()
            def send(rid, answers, number):
                nonlocal active, maximum
                with lock: active+=1;maximum=max(maximum,active)
                time.sleep(.02)
                with lock: delivered.append(rid);active-=1
                if rid=='c': raise TimeoutError('unknown delivery')
                return 'ok'
            workers=[DeliveryQueue(connect,Path(directory)/'sender.lock',send,.01) for _ in range(2)]
            for worker in workers:worker.start()
            deadline=time.time()+8
            while len(delivered)<4 and time.time()<deadline:time.sleep(.02)
            for worker in workers:worker.stop.set()
            for worker in workers:worker.thread.join(3)
            self.assertEqual(maximum,1)
            self.assertEqual(delivered,['a','b','c','d'])
            with transaction(connect) as c:self.assertEqual(c.execute("SELECT state FROM submissions WHERE id='c'").fetchone()[0],'uncertain')
            # A restart does not resend completed or ambiguous deliveries.
            worker=DeliveryQueue(connect,Path(directory)/'sender.lock',send,.01)
            worker.recover();self.assertFalse(worker.process_one())
            with self.assertRaises(ValueError):enqueue(connect,'c','admin')


if __name__=='__main__': unittest.main()

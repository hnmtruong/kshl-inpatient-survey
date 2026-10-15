"""Durable FIFO delivery with one sender across processes sharing the database."""
import json
import threading
import time
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path


@contextmanager
def transaction(connect):
    connection = connect()
    try:
        with connection:
            yield connection
    finally:
        connection.close()


class DeliveryQueue:
    def __init__(self, connect, lock_path, deliver, pause_seconds=5):
        self.connect, self.lock_path, self.deliver = connect, Path(lock_path), deliver
        self.pause_seconds = pause_seconds
        self.stop = threading.Event()
        self.thread = None

    def start(self):
        self.thread = threading.Thread(target=self.run, name="survey-delivery", daemon=True)
        self.thread.start()

    def _lock(self):
        handle = self.lock_path.open("a+b")
        try:
            if __import__('os').name == 'nt':
                import msvcrt
                handle.seek(0); handle.write(b'0'); handle.flush(); handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
            return handle
        except OSError:
            handle.close()
            return None

    def recover(self):
        # A process ended during a POST: never send that record automatically again.
        with transaction(self.connect) as c:
            c.execute("UPDATE submissions SET state='uncertain', byt_message=? WHERE state='syncing'", ('Tiến trình gửi đã gián đoạn. Cần đối chiếu cổng nhận trước khi gửi lại.',))

    def process_one(self):
        with transaction(self.connect) as c:
            c.execute('BEGIN IMMEDIATE')
            row = c.execute("SELECT q.seq,s.id,s.answers_json,s.survey_form,q.requested_by FROM delivery_queue q JOIN submissions s ON s.id=q.submission_id WHERE s.state='queued' ORDER BY q.seq LIMIT 1").fetchone()
            if not row:
                return False
            _, rid, blob, number, username = row
            c.execute("UPDATE submissions SET state='syncing',byt_message=NULL WHERE id=? AND state='queued'", (rid,))
        try:
            message = self.deliver(rid, json.loads(blob), number)
        except Exception:
            with transaction(self.connect) as c:
                c.execute("UPDATE submissions SET state='uncertain',byt_message=? WHERE id=?", ('Chưa xác nhận kết quả gửi. Cần đối chiếu cổng nhận; hệ thống không tự gửi lại phiếu này.', rid))
        else:
            with transaction(self.connect) as c:
                c.execute("UPDATE submissions SET state='sent',sent_at=?,sent_by=?,byt_message=? WHERE id=?", (datetime.now().astimezone().isoformat(timespec='seconds'), username, message, rid))
        return True

    def run(self):
        handle = None
        try:
            while not self.stop.is_set():
                if handle is None:
                    handle = self._lock()
                    if handle is None:
                        self.stop.wait(2)
                        continue
                    self.recover()
                try:
                    processed = self.process_one()
                except Exception:
                    # Retain the lock and back off if the local database is unavailable.
                    self.stop.wait(5)
                    continue
                self.stop.wait(self.pause_seconds if processed else 1)
        finally:
            if handle:
                handle.close()


def enqueue(connect, rid, username):
    with transaction(connect) as c:
        c.execute('BEGIN IMMEDIATE')
        row = c.execute('SELECT state,survey_form FROM submissions WHERE id=?', (rid,)).fetchone()
        if not row:
            raise ValueError('Không tìm thấy phiếu.')
        state, number = row
        if state not in {'queued', 'syncing', 'sent'}:
            if state not in {'approved', 'reviewed', 'failed'}:
                raise ValueError('Phiếu cần được duyệt và có kết quả gửi rõ ràng trước khi xếp hàng.')
            c.execute("UPDATE submissions SET state='queued',byt_message=NULL WHERE id=?", (rid,))
            c.execute('DELETE FROM delivery_queue WHERE submission_id=?', (rid,))
            c.execute('INSERT INTO delivery_queue(submission_id,requested_by) VALUES(?,?)', (rid, username))
            state = 'queued'
        return state, number

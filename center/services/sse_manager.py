"""SSE stream manager for real-time frontend updates."""
import queue
import threading


class SSEManager:
    """Manages Server-Sent Event streams for active tests."""

    def __init__(self):
        self._queues = {}  # test_id -> queue.Queue
        self._lock = threading.Lock()

    def publish(self, test_id, data):
        """Publish data to a test's SSE queue. Non-blocking."""
        with self._lock:
            q = self._queues.get(test_id)
        if q is not None:
            try:
                q.put_nowait(data)
            except queue.Full:
                pass

    def subscribe(self, test_id):
        """Create a new SSE queue for a test. Returns queue."""
        with self._lock:
            if test_id in self._queues:
                # Drain old queue to prevent memory leak
                old_q = self._queues[test_id]
                while not old_q.empty():
                    try:
                        old_q.get_nowait()
                    except queue.Empty:
                        break
            self._queues[test_id] = queue.Queue(maxsize=200)
            return self._queues[test_id]

    def unsubscribe(self, test_id):
        """Remove a test's SSE queue."""
        with self._lock:
            self._queues.pop(test_id, None)

    def generator(self, test_id):
        """Generator that yields SSE-formatted strings for a test."""
        q = self.subscribe(test_id)
        try:
            while True:
                try:
                    data = q.get(timeout=10)
                    if data is None:
                        break
                    import json
                    yield f"data: {json.dumps(data)}\n\n"
                except queue.Empty:
                    # Send keepalive
                    yield "data: {}\n\n"
        finally:
            self.unsubscribe(test_id)


sse_manager = SSEManager()

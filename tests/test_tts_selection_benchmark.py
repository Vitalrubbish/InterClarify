"""Verify causal playback timing and stream protocol failures without model weights."""
import array
import importlib.util
from pathlib import Path
import unittest

spec = importlib.util.spec_from_file_location('tts_benchmark', Path(__file__).parents[1] / 'scripts/remote/tts_selection_benchmark.py')
bench = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bench)


class PlaybackClockTests(unittest.TestCase):
    def test_late_packet_delays_audible_onset(self):
        pcm = array.array('h', [0]*100 + [10000]*100).tobytes()
        result = bench.analyze(pcm, [{'arrival_seconds': .1, 'samples': 100},
                                     {'arrival_seconds': 1., 'samples': 100}], 1000)
        self.assertAlmostEqual(result['first_packet_seconds'], .1)
        self.assertAlmostEqual(result['onset_db45_seconds'], .1)
        self.assertAlmostEqual(result['audible_db45_seconds'], 1.)
        self.assertEqual(result['stalls'], 1)
        self.assertAlmostEqual(result['stall_seconds'], .8)

    def test_continuous_voice_windows_span_small_packets(self):
        pcm = array.array('h', [0]*10 + [10000]*30).tobytes()
        chunks = [{'arrival_seconds': .1 + i*.005, 'samples': 5} for i in range(8)]
        result = bench.analyze(pcm, chunks, 1000)
        self.assertAlmostEqual(result['onset_db45_seconds'], .01)
        self.assertAlmostEqual(result['audible_db45_seconds'], .11)
        self.assertEqual(result['stalls'], 0)

    def test_silence_or_transient_is_not_sustained_speech(self):
        pcm = array.array('h', [0]*10 + [10000]*20 + [0]*70).tobytes()
        result = bench.analyze(pcm, [{'arrival_seconds': .1, 'samples': 100}], 1000)
        self.assertIsNone(result['audible_db45_seconds'])
        self.assertEqual(result['first_packet_samples'], 100)

    def test_http_headers_do_not_count_as_audio_and_packets_keep_arrival_time(self):
        import argparse
        import json
        import struct
        import tempfile
        import threading
        import time
        from http.server import BaseHTTPRequestHandler, HTTPServer
        class Stream(BaseHTTPRequestHandler):
            def do_POST(self):
                self.rfile.read(int(self.headers['Content-Length']))
                self.send_response(200)
                self.send_header('X-Sample-Rate', '1000')
                self.end_headers()
                self.wfile.flush()
                time.sleep(.04)
                for values in ([0]*10, [10000]*40):
                    data = array.array('h', values).tobytes()
                    self.wfile.write(struct.pack('<I', len(data)) + data)
                    self.wfile.flush()
                self.wfile.write(struct.pack('<I', 0))
            def log_message(self, *_):
                pass
        server = HTTPServer(('127.0.0.1', 0), Stream)
        worker = threading.Thread(target=server.handle_request)
        worker.start()
        try:
            with tempfile.TemporaryDirectory() as temp:
                args = argparse.Namespace(port=server.server_port, timeout=2., backend='pocket')
                result = bench.measure(args, {'id':'test','text':'hello'}, 'measured', Path(temp))
                self.assertIsNone(result['error'])
                self.assertEqual(result['first_packet_samples'], 10)
                self.assertGreaterEqual(result['first_packet_seconds'], .035)
                self.assertAlmostEqual(result['audio_seconds'], .05)
                self.assertEqual(len(result['chunks']), 2)
                self.assertIsNotNone(result['audible_db45_seconds'])
        finally:
            worker.join(timeout=3)
            server.server_close()

    def test_truncated_stream_raises(self):
        import io
        with self.assertRaises(EOFError):
            bench.exact_read(io.BytesIO(b'12'), 4)


if __name__ == '__main__':
    unittest.main()

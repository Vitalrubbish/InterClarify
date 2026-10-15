"""Deterministic response-ID and failure checks for the headless link driver."""

import asyncio
import importlib.util
import json
import os
import tempfile
import time
import unittest
from pathlib import Path

SPEC = importlib.util.spec_from_file_location(
    "link_driver", Path(__file__).resolve().parents[1] / "scripts/remote/xtalk_link_check.py"
)
link = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(link)


class LinkCheckTests(unittest.IsolatedAsyncioTestCase):
    """Verify completion belongs to the response under test."""

    def make_client(self):
        """Build a driver whose deterministic waits time out immediately."""
        return link.LinkClient("http://localhost", "ws://localhost", 0)

    async def test_sequential_timeout_is_not_complete(self):
        """A missing finish event leaves the turn unsuccessful."""
        client = self.make_client()
        async def send(ws, pcm, index):
            return 0, 1
        client._send_turn_input = send
        report = await client._run_turn(None, b"aa", 0)
        self.assertFalse(report["response_finished"])

    async def test_sequential_ignores_old_finish(self):
        """An old response finishing cannot complete the new turn."""
        client = self.make_client()
        client._start_resp_ids = ["A"]
        async def send(ws, pcm, index):
            client._start_resp_ids.append("B")
            client._finish_resp_ids.append("A")
            return 0, 1
        client._send_turn_input = send
        report = await client._run_turn(None, b"aa", 1)
        self.assertEqual(report["response_id"], "B")
        self.assertFalse(report["response_finished"])

    async def barge_case(self, finish_new):
        """Simulate A being interrupted and B starting."""
        client = self.make_client()
        client._audio_bytes = 2
        client._current_response_id = "A"
        client._start_resp_ids = ["A"]
        async def send(ws, pcm, index):
            if index == 1:
                client._stop_resp_ids.append("A")
                client._start_resp_ids.append("B")
                client._finish_resp_ids.append("A")
                client._audio_by_response["B"] = 2
                client._audio_before_finished.add("B")
                if finish_new:
                    client._finish_resp_ids.append("B")
            return 0, 1
        client._send_turn_input = send
        return await client._run_barge_in(None, b"aa", b"bb", 0)

    async def test_old_finish_does_not_complete_continuation(self):
        """Regression for counting A's finish as B's completion."""
        report = await self.barge_case(False)
        self.assertTrue(report["barge_in_stop_observed"])
        self.assertFalse(report["continuation_finished"])

    async def test_new_response_finish_completes_continuation(self):
        """B must have its own audio and finish event."""
        report = await self.barge_case(True)
        self.assertTrue(report["continuation_finished"])
        self.assertEqual(report["continuation_response_id"], "B")

    async def test_receiver_failure_stops_wait(self):
        """A crashed receiver cannot leave a successful verdict."""
        client = self.make_client()
        async def fail():
            raise RuntimeError("broken receive")
        client._receiver = asyncio.create_task(fail())
        await asyncio.sleep(0)
        self.assertFalse(await client._wait_for(lambda: True, 0))
        self.assertIn("broken receive", client._errors[0])

    async def test_server_error_is_recorded(self):
        """Server errors remain visible to the scenario verdict."""
        client = self.make_client()
        class Socket:
            """Yield one server error."""
            def __aiter__(self):
                async def messages():
                    yield json.dumps({"action": "error", "data": "failed"})
                return messages()
        await client._receive(Socket())
        self.assertEqual(client._errors, ["failed"])
        self.assertFalse(await client._wait_for(lambda: True, 0))


class ServerStartupDiagnosticsTests(unittest.IsolatedAsyncioTestCase):
    """A server that never binds its port must explain itself in the log."""

    def setUp(self) -> None:
        """Point the child log at a scratch file for the duration of a test."""
        self.serve_log = Path(tempfile.mkdtemp()) / "xtalk_serve.log"
        previous = os.environ.get("XTALK_SERVE_LOG")
        os.environ["XTALK_SERVE_LOG"] = str(self.serve_log)

        def restore() -> None:
            if previous is None:
                os.environ.pop("XTALK_SERVE_LOG", None)
            else:
                os.environ["XTALK_SERVE_LOG"] = previous

        self.addCleanup(restore)

    class Process:
        """Minimal stand-in for a spawned process."""
        pid = 4321

        def __init__(self, alive: bool, exitcode: int | None) -> None:
            self._alive = alive
            self.exitcode = exitcode

        def is_alive(self) -> bool:
            """Report whether the process is still running."""
            return self._alive

    async def test_dead_child_reports_exit_code_and_log_tail(self) -> None:
        """An exited child contributes its exit code and what it logged."""
        self.serve_log.write_text(
            "[serve 1] start host=127.0.0.1 port=5000\n"
            "[serve 1] FAILED:\nRuntimeError: onnxruntime is required\n",
            encoding="utf-8",
        )
        with self.assertRaises(TimeoutError) as caught:
            await link._wait_for_server(self.Process(False, 3), 1, time.monotonic() - 1)
        message = str(caught.exception)
        self.assertIn("exited with code 3", message)
        self.assertIn("RuntimeError: onnxruntime is required", message)

    async def test_stalled_child_is_distinguished_from_a_crash(self) -> None:
        """A child that is still alive means a stall, not a crash."""
        with self.assertRaises(TimeoutError) as caught:
            await link._wait_for_server(self.Process(True, None), 1, time.monotonic() - 1)
        message = str(caught.exception)
        self.assertIn("still alive", message)
        self.assertIn("stalled before binding", message)


if __name__ == "__main__":
    unittest.main()

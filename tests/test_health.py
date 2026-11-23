import os
import tempfile
import time
import unittest
from contextlib import redirect_stderr
from io import StringIO

from common.health import beat, is_fresh, main


class HeartbeatTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.path = os.path.join(tmp.name, "worker.heartbeat")

    def run_main(self, *argv):
        err = StringIO()
        with redirect_stderr(err):
            code = main(list(argv))
        return code, err.getvalue()

    def test_missing_heartbeat_is_unhealthy(self):
        self.assertFalse(is_fresh(self.path))
        code, err = self.run_main(self.path)
        self.assertEqual(code, 1)
        self.assertIn("unhealthy", err)

    def test_recent_beat_is_healthy(self):
        beat(self.path)
        self.assertTrue(is_fresh(self.path))
        self.assertEqual(self.run_main(self.path)[0], 0)

    def test_stale_beat_is_unhealthy_until_the_next_beat(self):
        beat(self.path)
        old = time.time() - 60
        os.utime(self.path, (old, old))
        self.assertFalse(is_fresh(self.path))
        self.assertEqual(self.run_main(self.path)[0], 1)
        self.assertEqual(self.run_main(self.path, "--max-age", "120")[0], 0)
        beat(self.path)
        self.assertTrue(is_fresh(self.path))

    def test_every_file_must_be_fresh(self):
        other = self.path + ".other"
        beat(self.path)
        code, err = self.run_main(self.path, other)
        self.assertEqual(code, 1)
        self.assertIn(other, err)
        beat(other)
        self.assertEqual(self.run_main(self.path, other)[0], 0)

    def test_usage(self):
        with self.assertRaises(SystemExit) as ctx:
            self.run_main()
        self.assertEqual(ctx.exception.code, 2)


if __name__ == "__main__":
    unittest.main()

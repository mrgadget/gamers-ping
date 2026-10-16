import hashlib
import io
import os
import tempfile
import unittest

from gamers_ping import updater


class FakeResp(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        self.close()


class Updater(unittest.TestCase):
    def test_versions(self):
        self.assertTrue(updater.is_newer("v0.10.0", "0.9.0"))
        self.assertTrue(updater.is_newer("v1.0", "0.9.9"))
        self.assertFalse(updater.is_newer("v0.2.0", "0.2.0"))
        self.assertFalse(updater.is_newer("v0.1.9", "0.2.0"))

    def test_download_verifies(self):
        data = b"MZ" + b"x" * 1000
        rel = {"url": "https://github.com/x", "size": len(data), "sha256": hashlib.sha256(data).hexdigest()}
        with tempfile.TemporaryDirectory() as d:
            dest = os.path.join(d, "new")
            updater.download(rel, dest, opener=lambda *a, **k: FakeResp(data))
            self.assertEqual(open(dest, "rb").read(), data)
            bad = dict(rel, sha256="0" * 64)
            with self.assertRaises(ValueError):
                updater.download(bad, dest, opener=lambda *a, **k: FakeResp(data))
            self.assertFalse(os.path.exists(dest))  # nothing left behind
            with self.assertRaises(ValueError):
                updater.download({"url": "https://github.com/x"}, dest, opener=lambda *a, **k: FakeResp(b"<html>"))

    def test_swap(self):
        with tempfile.TemporaryDirectory() as d:
            exe, new = os.path.join(d, "a.exe"), os.path.join(d, "a.exe.new")
            open(exe, "w").write("old")
            open(new, "w").write("new")
            updater.swap_in(new, exe)
            self.assertEqual(open(exe).read(), "new")
            self.assertEqual(open(exe + ".old").read(), "old")


if __name__ == "__main__":
    unittest.main()

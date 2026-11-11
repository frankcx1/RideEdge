import os
import unittest
from unittest.mock import patch

from farol.env import bind_host, bind_port


class BindTests(unittest.TestCase):
    def test_defaults_to_loopback(self):
        env = {key: value for key, value in os.environ.items() if not key.startswith("FAROL_")}
        with patch.dict(os.environ, env, clear=True):
            self.assertEqual(bind_host(), "127.0.0.1")
            self.assertEqual(bind_port(), 8787)

    def test_env_overrides_host_and_port(self):
        with patch.dict(os.environ, {"FAROL_HOST": "100.64.0.10", "FAROL_PORT": "9000"}):
            self.assertEqual(bind_host(), "100.64.0.10")
            self.assertEqual(bind_port(), 9000)

    def test_rejects_wildcard_without_opt_in(self):
        with patch.dict(os.environ, {"FAROL_HOST": "0.0.0.0", "FAROL_ALLOW_PUBLIC_BIND": ""}):
            with self.assertRaises(ValueError):
                bind_host()

    def test_allows_wildcard_with_opt_in(self):
        with patch.dict(
            os.environ, {"FAROL_HOST": "0.0.0.0", "FAROL_ALLOW_PUBLIC_BIND": "1"}
        ):
            self.assertEqual(bind_host(), "0.0.0.0")

    def test_tailscale_uses_explicit_ipv4(self):
        with patch.dict(
            os.environ,
            {"FAROL_HOST": "tailscale", "FAROL_TAILSCALE_IPV4": "100.64.0.10"},
        ):
            self.assertEqual(bind_host(), "100.64.0.10")

    def test_rejects_invalid_port(self):
        with patch.dict(os.environ, {"FAROL_PORT": "0"}):
            with self.assertRaises(ValueError):
                bind_port()
        with patch.dict(os.environ, {"FAROL_PORT": "nope"}):
            with self.assertRaises(ValueError):
                bind_port()


if __name__ == "__main__":
    unittest.main()

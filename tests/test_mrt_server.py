import unittest
from unittest.mock import patch

from app.concierge_main import open_ngrok_tunnel
from config.settings import AppSettings


class NgrokTests(unittest.TestCase):
    def settings(self, **overrides):
        values = {"mrt_port": 8088, "mrt_api_key": "mrt-key", "ngrok_api_key": "ngrok-key"}
        values.update(overrides)
        return AppSettings(**values)

    @patch("ngrok.forward")
    @patch("ngrok.set_auth_token")
    def test_opens_ngrok_tunnel_with_configured_key(self, set_auth_token, forward):
        forward.return_value.url.return_value = "https://example.ngrok.app"

        public_url = open_ngrok_tunnel(self.settings())

        self.assertEqual(public_url, "https://example.ngrok.app")
        set_auth_token.assert_called_once_with("ngrok-key")
        forward.assert_called_once_with(8088, proto="http")

    @patch("ngrok.forward", side_effect=OSError("network unreachable"))
    @patch("ngrok.set_auth_token")
    def test_offline_start_keeps_mrt_on_the_lan(self, set_auth_token, forward):
        self.assertIsNone(open_ngrok_tunnel(self.settings()))

    def test_skips_ngrok_without_a_key(self):
        self.assertIsNone(open_ngrok_tunnel(self.settings(ngrok_api_key="")))

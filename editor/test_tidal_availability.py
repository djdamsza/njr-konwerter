"""Tests for Tidal track availability check."""
import unittest
from unittest.mock import MagicMock, patch


class TestTidalTrackAvailable(unittest.TestCase):
    def test_invalid_id_returns_none(self):
        from app import _check_tidal_track_available

        self.assertIsNone(_check_tidal_track_available(""))
        self.assertIsNone(_check_tidal_track_available("abc"))

    @patch("ssl_utils.urlopen")
    def test_200_returns_true(self, mock_urlopen):
        from app import _check_tidal_track_available

        resp = MagicMock()
        resp.__enter__.return_value = resp
        resp.__exit__.return_value = False
        resp.getcode.return_value = 200
        mock_urlopen.return_value = resp
        self.assertTrue(_check_tidal_track_available("530"))

    @patch("ssl_utils.urlopen")
    def test_404_returns_false(self, mock_urlopen):
        import urllib.error
        from app import _check_tidal_track_available

        mock_urlopen.side_effect = urllib.error.HTTPError(
            "url", 404, "Not Found", {}, None
        )
        self.assertFalse(_check_tidal_track_available("99999999999"))

    @patch("ssl_utils.urlopen")
    def test_ssl_error_returns_none_not_false(self, mock_urlopen):
        import ssl
        from app import _check_tidal_track_available

        mock_urlopen.side_effect = ssl.SSLError("certificate verify failed")
        self.assertIsNone(_check_tidal_track_available("530"))

    @patch("ssl_utils.urlopen")
    def test_401_assumes_available(self, mock_urlopen):
        import urllib.error
        from app import _check_tidal_track_available

        mock_urlopen.side_effect = urllib.error.HTTPError(
            "url", 401, "Unauthorized", {}, None
        )
        self.assertTrue(_check_tidal_track_available("530"))


if __name__ == "__main__":
    unittest.main()

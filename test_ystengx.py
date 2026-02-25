"""
Unit tests for epg.scraper.ystengx
"""
import json
import sys
import os
from datetime import date, datetime
from unittest.mock import patch, MagicMock
from zoneinfo import ZoneInfo

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from epg.model import Channel, Program
from epg.scraper import ystengx

TZ = ZoneInfo("Asia/Shanghai")

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_channel(ch_id="gx_cctv4"):
    return Channel(ch_id, {"name": ["CCTV-4"], "preview": 1, "recap": 1, "refresh": "once"})


def _fake_response(result_code="000", programs=None):
    """Build a minimal JSON response that matches the Guangxi EPG API format."""
    if programs is None:
        programs = [
            {
                "programName": "新闻联播",
                "startTime": 1700000000,
                "endTime": 1700001800,
            },
            {
                "programName": "天气预报",
                "startTime": 1700001800,
                "endTime": 1700002400,
            },
        ]
    body = {
        "resultCode": result_code,
        "resultMessage": "success" if result_code == "000" else "error",
        "content": [{"programs": programs}],
    }
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.text = json.dumps(body)
    return mock_resp


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestYstengxUpdate:

    def test_successful_update_populates_programs(self):
        channel = _make_channel()
        dt = date(2023, 10, 27)

        with patch("epg.scraper.ystengx.requests.get") as mock_get:
            mock_get.return_value = _fake_response()
            result = ystengx.update(channel, scraper_id="HD-8000k-1080P-cctv4", dt=dt)

        assert result is True
        assert len(channel.programs) == 2
        assert channel.programs[0].title == "新闻联播"
        assert channel.programs[1].title == "天气预报"

    def test_program_times_use_shanghai_timezone(self):
        channel = _make_channel()
        dt = date(2023, 10, 27)

        with patch("epg.scraper.ystengx.requests.get") as mock_get:
            mock_get.return_value = _fake_response()
            ystengx.update(channel, scraper_id="HD-8000k-1080P-cctv4", dt=dt)

        prog = channel.programs[0]
        assert prog.start_time.tzinfo is not None
        assert prog.start_time == datetime.fromtimestamp(1700000000, tz=TZ)
        assert prog.end_time == datetime.fromtimestamp(1700001800, tz=TZ)

    def test_uses_scraper_id_over_channel_id(self):
        channel = _make_channel("gx_cctv4")
        dt = date(2023, 10, 27)

        with patch("epg.scraper.ystengx.requests.get") as mock_get:
            mock_get.return_value = _fake_response()
            ystengx.update(channel, scraper_id="HD-8000k-1080P-cctv4", dt=dt)
            called_url = mock_get.call_args[0][0]

        assert "uuid=HD-8000k-1080P-cctv4" in called_url
        assert "uuid=gx_cctv4" not in called_url

    def test_falls_back_to_channel_id_when_no_scraper_id(self):
        channel = _make_channel("my-channel-uuid")
        dt = date(2023, 10, 27)

        with patch("epg.scraper.ystengx.requests.get") as mock_get:
            mock_get.return_value = _fake_response()
            ystengx.update(channel, scraper_id=None, dt=dt)
            called_url = mock_get.call_args[0][0]

        assert "uuid=my-channel-uuid" in called_url

    def test_request_includes_correct_headers(self):
        channel = _make_channel()
        dt = date(2023, 10, 27)

        with patch("epg.scraper.ystengx.requests.get") as mock_get:
            mock_get.return_value = _fake_response()
            ystengx.update(channel, scraper_id="HD-8000k-1080P-cctv4", dt=dt)
            _, kwargs = mock_get.call_args

        headers = kwargs.get("headers", {})
        assert "Referer" in headers
        assert "HD-8000k-1080P-cctv4" in headers["Referer"]
        assert "lvpspanel.gxa.ssl.bcs.ottcn.com" in headers["Referer"]

    def test_request_url_contains_expected_params(self):
        channel = _make_channel()
        dt = date(2023, 10, 27)

        with patch("epg.scraper.ystengx.requests.get") as mock_get:
            mock_get.return_value = _fake_response()
            ystengx.update(channel, scraper_id="HD-8000k-1080P-cctv4", dt=dt)
            called_url = mock_get.call_args[0][0]

        assert "lvps.gx.bcs.ottcn.com" in called_url
        assert "abilityString=" in called_url
        assert "noCache=true" in called_url
        assert "startDate=20231027" in called_url
        assert "endDate=20231027" in called_url

    def test_returns_false_on_http_error(self):
        channel = _make_channel()
        mock_resp = MagicMock()
        mock_resp.status_code = 500

        with patch("epg.scraper.ystengx.requests.get", return_value=mock_resp):
            result = ystengx.update(channel, scraper_id="HD-8000k-1080P-cctv4")

        assert result is False
        assert channel.programs == []

    def test_returns_false_on_network_exception(self):
        channel = _make_channel()

        with patch("epg.scraper.ystengx.requests.get", side_effect=Exception("timeout")):
            result = ystengx.update(channel, scraper_id="HD-8000k-1080P-cctv4")

        assert result is False

    def test_returns_false_when_result_code_not_000(self):
        channel = _make_channel()

        with patch("epg.scraper.ystengx.requests.get", return_value=_fake_response("999")):
            result = ystengx.update(channel, scraper_id="HD-8000k-1080P-cctv4")

        assert result is False

    def test_returns_false_when_content_empty(self):
        channel = _make_channel()
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.text = json.dumps({"resultCode": "000", "content": []})

        with patch("epg.scraper.ystengx.requests.get", return_value=mock_resp):
            result = ystengx.update(channel, scraper_id="HD-8000k-1080P-cctv4")

        assert result is False

    def test_flush_removes_old_programs_for_same_date(self):
        channel = _make_channel()
        dt = date(2023, 10, 27)
        # Pre-populate with a program on the same date
        old_prog = Program(
            channel_id=channel.id,
            title="旧节目",
            start_time=datetime(2023, 10, 27, 8, 0, tzinfo=TZ),
            end_time=datetime(2023, 10, 27, 9, 0, tzinfo=TZ),
        )
        channel.programs.append(old_prog)

        with patch("epg.scraper.ystengx.requests.get", return_value=_fake_response()):
            ystengx.update(channel, scraper_id="HD-8000k-1080P-cctv4", dt=dt)

        titles = [p.title for p in channel.programs]
        assert "旧节目" not in titles

    def test_programs_channel_id_set_correctly(self):
        channel = _make_channel("gx_cctv4")
        dt = date(2023, 10, 27)

        with patch("epg.scraper.ystengx.requests.get", return_value=_fake_response()):
            ystengx.update(channel, scraper_id="HD-8000k-1080P-cctv4", dt=dt)

        for prog in channel.programs:
            assert prog.channel == "gx_cctv4"


class TestYstengxChannelConfig:
    """Validate that channels.yaml is parseable and gx_* entries are sane."""

    _CONFIG_PATH = os.path.join(os.path.dirname(__file__), "config", "channels.yaml")

    def _load(self):
        import yaml
        with open(self._CONFIG_PATH) as f:
            return yaml.safe_load(f)

    def test_yaml_loads_without_error(self):
        data = self._load()
        assert isinstance(data, dict)
        assert len(data) > 0

    def test_all_gx_channels_have_ystengx_scraper(self):
        data = self._load()
        for ch_id, ch_cfg in data.items():
            if str(ch_id).startswith("gx_"):
                assert "ystengx" in ch_cfg.get("scraper", {}), \
                    f"{ch_id} is missing ystengx scraper"

    def test_gx_cctv1_uuid_is_correct(self):
        data = self._load()
        assert data["gx_cctv1"]["scraper"]["ystengx"] == "cctv-1"

    def test_gx_cctv13_uuid_is_correct(self):
        data = self._load()
        assert data["gx_cctv13"]["scraper"]["ystengx"] == "cctv-13"

    def test_official_names_match(self):
        data = self._load()
        expected = {
            "gx_chunxiang4k":  "纯享4K",
            "gx_nanfangstv":   "大湾区卫视",
            "gx_lvyoustv":     "海南卫视",
            "gx_supermovie":   "黑莓电影",
            "gx_supercctv14":  "黑莓动画",
            "gx_superwmyx":    "哒啵赛事",
            "gx_dabodj":       "哒啵电竞",
            "gx_miguaoyun2":   "睛彩竞技",
            "gx_miguaoyun1":   "睛彩篮球",
            "gx_saishijx":     "谍战大剧",
            "gx_jingpinjl":    "烽烟剧场",
        }
        for ch_id, name in expected.items():
            assert data[ch_id]["name"][0] == name, \
                f"{ch_id}: expected '{name}', got '{data[ch_id]['name'][0]}'"

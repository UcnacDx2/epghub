"""
Unit tests for epg.scraper.ystengx and end-to-end EPG generation pipeline.
"""
import json
import sys
import os
import tempfile
import shutil
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

    def test_request_url_contains_device_ability_string(self):
        """Verify the device ability string is URL-encoded into the request."""
        channel = _make_channel()
        dt = date(2023, 10, 27)

        with patch("epg.scraper.ystengx.requests.get") as mock_get:
            mock_get.return_value = _fake_response()
            ystengx.update(channel, scraper_id="HD-8000k-1080P-cctv4", dt=dt)
            called_url = mock_get.call_args[0][0]

        # The ability string must include device group and abilities so the
        # Guangxi EPG server returns program data instead of "无可用结果"
        assert "4575" in called_url, "deviceGroupId 4575 must be present in URL"
        assert "CITY_CODE" in called_url, "CITY_CODE must be present in URL"
        assert "abilities" in called_url, "abilities must be present in URL"
        assert "districtCode" in called_url, "districtCode must be present in URL"
        # Additional fields required by the API to return premium/MIGU channel data
        assert "labelIds" in called_url, "labelIds must be present in URL"
        assert "userLabelIds" in called_url, "userLabelIds must be present in URL"
        assert "COUNTY_CODE" in called_url, "COUNTY_CODE must be present in URL"

    def test_dict_scraper_id_uses_correct_uuid(self):
        """A dict scraper_id should use the 'uuid' key as the channel UUID."""
        channel = _make_channel("gx_liuzhouxwzh")
        dt = date(2023, 10, 27)
        scraper_cfg = {"uuid": "SD-3000k-576P-liuzhouxwzh", "city_code": "772", "district_code": "450200"}

        with patch("epg.scraper.ystengx.requests.get") as mock_get:
            mock_get.return_value = _fake_response()
            result = ystengx.update(channel, scraper_id=scraper_cfg, dt=dt)
            called_url = mock_get.call_args[0][0]

        assert result is True
        assert "uuid=SD-3000k-576P-liuzhouxwzh" in called_url

    def test_dict_scraper_id_uses_city_params(self):
        """A dict scraper_id should embed the city's CITY_CODE and districtCode in the URL."""
        channel = _make_channel("gx_liuzhouxwzh")
        dt = date(2023, 10, 27)
        scraper_cfg = {"uuid": "SD-3000k-576P-liuzhouxwzh", "city_code": "772", "district_code": "450200"}

        with patch("epg.scraper.ystengx.requests.get") as mock_get:
            mock_get.return_value = _fake_response()
            ystengx.update(channel, scraper_id=scraper_cfg, dt=dt)
            called_url = mock_get.call_args[0][0]

        assert "772" in called_url, "city_code 772 must be in URL for Liuzhou channel"
        assert "450200" in called_url, "district_code 450200 must be in URL for Liuzhou channel"

    def test_string_scraper_id_uses_default_city_params(self):
        """A plain string scraper_id should use the default 南宁 city params."""
        channel = _make_channel()
        dt = date(2023, 10, 27)

        with patch("epg.scraper.ystengx.requests.get") as mock_get:
            mock_get.return_value = _fake_response()
            ystengx.update(channel, scraper_id="cctv-1", dt=dt)
            called_url = mock_get.call_args[0][0]

        assert "771" in called_url, "default CITY_CODE 771 (南宁) must be present"
        assert "450100" in called_url, "default districtCode 450100 (南宁) must be present"

    def test_string_uuid_auto_detects_nanning_city(self):
        """A plain UUID containing 'nanning' should auto-use 南宁 city params (771/450100)."""
        channel = _make_channel("SD-3000k-576P-nanningyssh")
        dt = date(2023, 10, 27)

        with patch("epg.scraper.ystengx.requests.get") as mock_get:
            mock_get.return_value = _fake_response()
            ystengx.update(channel, scraper_id="SD-3000k-576P-nanningyssh", dt=dt)
            called_url = mock_get.call_args[0][0]

        assert "771" in called_url, "CITY_CODE 771 (南宁) must be auto-detected"
        assert "450100" in called_url, "districtCode 450100 (南宁) must be auto-detected"

    def test_string_uuid_auto_detects_guilin_city(self):
        """A plain UUID containing 'guilin' should auto-use 桂林 city params (773/450300)."""
        channel = _make_channel("GXGD-guilinxwzh")
        dt = date(2023, 10, 27)

        with patch("epg.scraper.ystengx.requests.get") as mock_get:
            mock_get.return_value = _fake_response()
            ystengx.update(channel, scraper_id="GXGD-guilinxwzh", dt=dt)
            called_url = mock_get.call_args[0][0]

        assert "773" in called_url, "CITY_CODE 773 (桂林) must be auto-detected"
        assert "450300" in called_url, "districtCode 450300 (桂林) must be auto-detected"

    def test_string_uuid_auto_detects_hezhou_city(self):
        """A plain UUID 'gxhzzonghe' should auto-use 贺州 city params (774/451100)."""
        channel = _make_channel("HD-4000k-1080P-gxhzzonghe")
        dt = date(2023, 10, 27)

        with patch("epg.scraper.ystengx.requests.get") as mock_get:
            mock_get.return_value = _fake_response()
            ystengx.update(channel, scraper_id="HD-4000k-1080P-gxhzzonghe", dt=dt)
            called_url = mock_get.call_args[0][0]

        assert "774" in called_url, "CITY_CODE 774 (贺州) must be auto-detected"
        assert "451100" in called_url, "districtCode 451100 (贺州) must be auto-detected"

    def test_returns_false_on_http_error(self):
        channel = _make_channel()
        mock_resp = MagicMock()
        mock_resp.status_code = 500

        with patch("epg.scraper.ystengx.requests.get", return_value=mock_resp):
            result = ystengx.update(channel, scraper_id="HD-8000k-1080P-cctv4")

        assert result is False
        assert channel.programs == []


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


# ---------------------------------------------------------------------------
# End-to-end EPG generation tests
# ---------------------------------------------------------------------------

_REPO_ROOT = os.path.dirname(__file__)


def _make_fake_api_response(programs=None):
    """Build a ystengx API response with programs for a single day."""
    if programs is None:
        programs = [
            {"programName": "新闻联播", "startTime": 1740474000, "endTime": 1740475800},
            {"programName": "天气预报", "startTime": 1740475800, "endTime": 1740476280},
            {"programName": "焦点访谈", "startTime": 1740476280, "endTime": 1740478800},
        ]
    body = {
        "resultCode": "000",
        "resultMessage": "success",
        "content": [{"programs": programs}],
    }
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.text = json.dumps(body)
    return mock_resp


class TestEpgXmltvGeneration:
    """Validate that the xmltv generator produces a well-formed, DTD-valid EPG file."""

    def _make_channels(self):
        channels = []
        ch = Channel("gx_cctv4", {"name": ["CCTV-4 中文国际"]})
        ch.programs.append(Program(
            title="新闻联播",
            start_time=datetime(2026, 2, 25, 19, 0, tzinfo=TZ),
            end_time=datetime(2026, 2, 25, 19, 30, tzinfo=TZ),
            channel_id="gx_cctv4",
        ))
        ch.programs.append(Program(
            title="天气预报",
            start_time=datetime(2026, 2, 25, 19, 30, tzinfo=TZ),
            end_time=datetime(2026, 2, 25, 19, 38, tzinfo=TZ),
            channel_id="gx_cctv4",
        ))
        channels.append(ch)
        ch2 = Channel("gx_cctv1", {"name": ["CCTV-1 综合"]})
        ch2.programs.append(Program(
            title="综合节目",
            start_time=datetime(2026, 2, 25, 20, 0, tzinfo=TZ),
            end_time=datetime(2026, 2, 25, 21, 0, tzinfo=TZ),
            channel_id="gx_cctv1",
        ))
        channels.append(ch2)
        return channels

    def test_xmltv_write_returns_true(self):
        from epg.generator import xmltv
        channels = self._make_channels()
        with tempfile.TemporaryDirectory() as tmpdir:
            epg_path = os.path.join(tmpdir, "epg.xml")
            result = xmltv.write(epg_path, channels, "epghub")
        assert result is True

    def test_xmltv_write_file_exists(self):
        from epg.generator import xmltv
        channels = self._make_channels()
        with tempfile.TemporaryDirectory() as tmpdir:
            epg_path = os.path.join(tmpdir, "epg.xml")
            xmltv.write(epg_path, channels, "epghub")
            assert os.path.exists(epg_path)

    def test_xmltv_output_is_dtd_valid(self):
        from epg.generator import xmltv
        from lxml import etree
        channels = self._make_channels()
        dtd_path = os.path.join(_REPO_ROOT, "xmltv.dtd")
        dtd = etree.DTD(open(dtd_path, "r"))
        with tempfile.TemporaryDirectory() as tmpdir:
            epg_path = os.path.join(tmpdir, "epg.xml")
            xmltv.write(epg_path, channels, "epghub")
            root = etree.XML(open(epg_path, "rb").read())
        valid = dtd.validate(root)
        assert valid, f"DTD validation failed: {dtd.error_log.filter_from_errors()}"

    def test_xmltv_contains_channel_elements(self):
        from epg.generator import xmltv
        from lxml import etree
        channels = self._make_channels()
        with tempfile.TemporaryDirectory() as tmpdir:
            epg_path = os.path.join(tmpdir, "epg.xml")
            xmltv.write(epg_path, channels, "epghub")
            root = etree.XML(open(epg_path, "rb").read())
        channel_ids = {el.get("id") for el in root.findall("channel")}
        assert "gx_cctv4" in channel_ids
        assert "gx_cctv1" in channel_ids

    def test_xmltv_contains_programme_elements(self):
        from epg.generator import xmltv
        from lxml import etree
        channels = self._make_channels()
        with tempfile.TemporaryDirectory() as tmpdir:
            epg_path = os.path.join(tmpdir, "epg.xml")
            xmltv.write(epg_path, channels, "epghub")
            root = etree.XML(open(epg_path, "rb").read())
        programmes = root.findall("programme")
        titles = [p.findtext("title") for p in programmes]
        assert "新闻联播" in titles
        assert "天气预报" in titles
        assert "综合节目" in titles

    def test_xmltv_programme_times_are_formatted(self):
        from epg.generator import xmltv
        from lxml import etree
        import re
        channels = self._make_channels()
        with tempfile.TemporaryDirectory() as tmpdir:
            epg_path = os.path.join(tmpdir, "epg.xml")
            xmltv.write(epg_path, channels, "epghub")
            root = etree.XML(open(epg_path, "rb").read())
        time_pattern = re.compile(r"^\d{14} [+-]\d{4}$")
        for prog in root.findall("programme"):
            assert time_pattern.match(prog.get("start")), \
                f"Bad start format: {prog.get('start')}"
            assert time_pattern.match(prog.get("stop")), \
                f"Bad stop format: {prog.get('stop')}"


class TestFullPipelineWithYstengx:
    """End-to-end test: load channels.yaml → mock ystengx API → generate EPG."""

    _CONFIG_PATH = os.path.join(_REPO_ROOT, "config", "channels.yaml")

    def test_pipeline_generates_valid_epg_for_gx_cctv_channels(self):
        """
        Load the real channels.yaml, mock the Guangxi EPG API to return valid
        programme data, run the full update pipeline for gx_cctv4 and verify
        that a DTD-valid EPG XML file is produced.
        """
        from epg import utils
        from epg.generator import xmltv
        from lxml import etree
        import yaml

        # Build a one-channel subset so the test is fast
        with open(self._CONFIG_PATH) as f:
            all_config = yaml.safe_load(f)

        subset = {"gx_cctv4": all_config["gx_cctv4"]}
        dtd_path = os.path.join(_REPO_ROOT, "xmltv.dtd")
        dtd = etree.DTD(open(dtd_path, "r"))

        with tempfile.TemporaryDirectory() as tmpdir:
            cfg_path = os.path.join(tmpdir, "channels.yaml")
            with open(cfg_path, "w") as f:
                yaml.dump(subset, f)

            epg_path = os.path.join(tmpdir, "epg.xml")

            with patch("epg.scraper.ystengx.requests.get",
                       return_value=_make_fake_api_response()):
                channels = utils.load_config(cfg_path)
                for i, channel in enumerate(channels):
                    utils.update_channel_full(channel, i)

                # There should be programs after scraping
                assert len(channels[0].programs) > 0, \
                    "No programs were scraped for gx_cctv4"

                xmltv.write(epg_path, channels, "epghub")

            # Validate output
            assert os.path.exists(epg_path), "EPG file was not created"
            root = etree.XML(open(epg_path, "rb").read())
            valid = dtd.validate(root)
            assert valid, \
                f"Generated EPG is not DTD-valid: {dtd.error_log.filter_from_errors()}"

            # Channel element present
            channel_ids = {el.get("id") for el in root.findall("channel")}
            assert "gx_cctv4" in channel_ids

            # Programme elements present
            programmes = root.findall("programme")
            assert len(programmes) > 0, "No programme elements in generated EPG"


class TestLoadChannelsFromYstJson:
    """Tests for utils.load_channels_from_yst_json dynamic channel loading."""

    def _fake_yst_json(self):
        return [
            {"uuid": "cctv-1", "name": "CCTV-1"},
            {"uuid": "HD-8000k-1080P-cctv4", "name": "CCTV-4"},
            {"uuid": "guangxistv", "name": "广西卫视"},
        ]

    def test_loads_channels_from_json_url(self):
        from epg import utils
        fake_resp = MagicMock()
        fake_resp.raise_for_status = MagicMock()
        fake_resp.json.return_value = self._fake_yst_json()

        with patch("epg.utils.requests.get", return_value=fake_resp):
            channels = utils.load_channels_from_yst_json("http://fake-url/yst_channel.json")

        assert len(channels) == 3

    def test_channel_ids_match_uuids(self):
        from epg import utils
        fake_resp = MagicMock()
        fake_resp.raise_for_status = MagicMock()
        fake_resp.raise_for_status.return_value = None
        fake_resp.json.return_value = self._fake_yst_json()

        with patch("epg.utils.requests.get", return_value=fake_resp):
            channels = utils.load_channels_from_yst_json("http://fake-url/yst_channel.json")

        ids = [c.id for c in channels]
        assert "cctv-1" in ids
        assert "HD-8000k-1080P-cctv4" in ids
        assert "guangxistv" in ids

    def test_channel_names_are_set(self):
        from epg import utils
        fake_resp = MagicMock()
        fake_resp.raise_for_status = MagicMock()
        fake_resp.json.return_value = self._fake_yst_json()

        with patch("epg.utils.requests.get", return_value=fake_resp):
            channels = utils.load_channels_from_yst_json("http://fake-url/yst_channel.json")

        names = {c.id: c.metadata["name"][0] for c in channels}
        assert names["cctv-1"] == "CCTV-1"
        assert names["HD-8000k-1080P-cctv4"] == "CCTV-4"
        assert names["guangxistv"] == "广西卫视"

    def test_channels_use_ystengx_scraper(self):
        from epg import utils
        fake_resp = MagicMock()
        fake_resp.raise_for_status = MagicMock()
        fake_resp.json.return_value = self._fake_yst_json()

        with patch("epg.utils.requests.get", return_value=fake_resp):
            channels = utils.load_channels_from_yst_json("http://fake-url/yst_channel.json")

        # Verify each channel uses ystengx scraper with its own UUID
        for ch in channels:
            with patch("epg.scraper.ystengx.requests.get",
                       return_value=_fake_response()) as mock_get:
                ch.update()
                called_url = mock_get.call_args[0][0]
            assert f"uuid={ch.id}" in called_url, \
                f"Channel {ch.id} should use its own UUID as scraper ID"

    def test_returns_empty_list_on_fetch_error(self):
        from epg import utils

        with patch("epg.utils.requests.get", side_effect=Exception("network error")):
            channels = utils.load_channels_from_yst_json("http://fake-url/yst_channel.json")

        assert channels == []

    def test_skips_entries_without_uuid(self):
        from epg import utils
        data_with_missing_uuid = [
            {"uuid": "cctv-1", "name": "CCTV-1"},
            {"name": "No UUID Channel"},  # no uuid key
            {"uuid": "", "name": "Empty UUID"},  # empty uuid
        ]
        fake_resp = MagicMock()
        fake_resp.raise_for_status = MagicMock()
        fake_resp.json.return_value = data_with_missing_uuid

        with patch("epg.utils.requests.get", return_value=fake_resp):
            channels = utils.load_channels_from_yst_json("http://fake-url/yst_channel.json")

        assert len(channels) == 1
        assert channels[0].id == "cctv-1"


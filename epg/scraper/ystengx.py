from epg.model import Channel, Program
from datetime import datetime, date, timezone
import time
import requests
import json
import urllib.parse
from . import headers as base_headers, tz_shanghai

_headers = {
    **base_headers,
    "Accept": "application/json, text/javascript, */*; q=0.01",
    "Accept-Language": "zh",
    "User-Agent": "Dalvik/2.1.0 (Linux; U; Android 9; B862AV3.2-M Build/PPR1.180610.011)",
}

# 默认城市参数：百色（CITY_CODE=776, districtCode=451000）
_DEFAULT_CITY_CODE = "776"
_DEFAULT_DISTRICT_CODE = "451000"

# UUID 子串 → (CITY_CODE, districtCode) 映射，用于从 uuid 自动推断城市鉴权参数
_UUID_CITY_MAP = (
    ("nanning",         ("771", "450100")),  # 南宁
    ("liuzhou",         ("772", "450200")),  # 柳州
    ("guilin",          ("773", "450300")),  # 桂林
    ("wuzhou",          ("774", "450400")),  # 梧州
    ("beihai",          ("779", "450500")),  # 北海
    ("fangchenggang",   ("770", "450600")),  # 防城港
    ("qinzhou",         ("777", "450700")),  # 钦州
    ("guigang",         ("775", "450800")),  # 贵港
    ("yulin",           ("775", "450900")),  # 玉林
    ("baisezh",         ("776", "451000")),  # 百色
    ("hzzonghe",        ("774", "451100")),  # 贺州
    ("hechi",           ("778", "451200")),  # 河池
    ("laibin",          ("772", "451300")),  # 来宾
    ("chongzuo",        ("771", "451400")),  # 崇左
)


def _detect_city_params(uuid: str) -> tuple[str, str]:
    """从 UUID 子串自动推断城市鉴权参数，返回 (city_code, district_code)。
    匹配不到时返回默认百色参数。"""
    uuid_lower = uuid.lower()
    for keyword, params in _UUID_CITY_MAP:
        if keyword in uuid_lower:
            return params
    return (_DEFAULT_CITY_CODE, _DEFAULT_DISTRICT_CODE)


def _make_ability_str(city_code: str = _DEFAULT_CITY_CODE, district_code: str = _DEFAULT_DISTRICT_CODE) -> str:
    """构造广西移动 EPG 鉴权能力串，需匹配频道所在城市。"""
    return (
        f'{{"CITY_CODE":"{city_code}","districtCode":"{district_code}",'
        f'"deviceGroupIds":["4575"],"abilities":["4K-1|cp-TENCENT|timeShift|NxM|DL-3rd|upgrade14"]}}'
    )


def update(
    channel: Channel, scraper_id: str | dict | None = None, dt: date = datetime.today().date()
) -> bool:
    # scraper_id 可以是字符串 UUID，也可以是包含 uuid/city_code/district_code 的字典
    if isinstance(scraper_id, dict):
        channel_id = scraper_id.get("uuid", channel.id)
        city_code = scraper_id.get("city_code", _DEFAULT_CITY_CODE)
        district_code = scraper_id.get("district_code", _DEFAULT_DISTRICT_CODE)
    else:
        channel_id = channel.id if scraper_id is None else scraper_id
        # 根据 UUID 自动推断城市参数，解决从 yst_channel.json 加载时缺少城市信息的问题
        city_code, district_code = _detect_city_params(channel_id)

    # 格式化日期，准备请求参数
    start_date = dt.strftime("%Y%m%d")
    end_date = dt.strftime("%Y%m%d")

    # 毫秒级时间戳
    t = int(time.time() * 1000)

    # 构造广西专用 API 请求 URL（需携带匹配频道城市的设备能力串才能获取节目单）
    ability_str = _make_ability_str(city_code, district_code)
    url = (
        f"http://lvps.gx.bcs.ottcn.com:8080/cms-lvp-epg/lvps/getAllProgramlist"
        f"?abilityString={urllib.parse.quote(ability_str)}"
        f"&startDate={start_date}&endDate={end_date}"
        f"&pos=fullplayer&uuid={channel_id}&noCache=true&serviceChannelId=&t={t}"
    )

    referer = (
        f"https://lvpspanel.gxa.ssl.bcs.ottcn.com/WEB_WATCHTV2/html/index_entry.html"
        f"?playType=live&assortId=&uuid={channel_id}"
    )

    req_headers = {**_headers, "Referer": referer}

    try:
        # 发送请求
        res = requests.get(url, headers=req_headers, timeout=10)
    except Exception:
        print("Fail:", url)
        return False

    # 如果响应码不是 200，说明请求失败
    if res.status_code != 200:
        return False

    # 解析 JSON 数据
    data = json.loads(res.text)

    # 判断返回的 resultCode 是否为 "000"，即请求是否成功
    if data["resultCode"] != "000":
        print("API returned an error:", data.get("resultMessage"))
        return False

    # 获取内容部分
    content = data["content"]

    # 如果没有找到相关内容，返回 False
    if not content:
        return False

    # 提取频道节目数据
    programs_data = content[0]["programs"]

    # 清空该频道的旧节目数据
    channel.flush(dt)

    # 遍历节目列表并更新节目数据
    for program in programs_data:
        title = program["programName"]
        start_time = datetime.fromtimestamp(program["startTime"], tz=tz_shanghai)
        end_time = datetime.fromtimestamp(program["endTime"], tz=tz_shanghai)

        # 创建并添加 Program 对象
        channel.programs.append(
            Program(channel_id=channel.id, title=title, start_time=start_time, end_time=end_time)
        )

    # 更新频道的元数据
    channel.metadata.update({"last_update": datetime.now(timezone.utc).astimezone()})

    return True

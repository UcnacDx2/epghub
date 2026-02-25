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

# 设备能力串：广西移动 B862AV3.2-M 机顶盒硬件特征，用于获取节目单
_ABILITY_STR = '{"CITY_CODE":"776","deviceGroupIds":["4575"],"abilities":["4K-1|cp-TENCENT|timeShift|NxM|DL-3rd|upgrade14"]}'

def update(
    channel: Channel, scraper_id: str | None = None, dt: date = datetime.today().date()
) -> bool:
    # 根据传入的 scraper_id 或者 channel.id 获取频道的 UUID
    channel_id = channel.id if scraper_id is None else scraper_id

    # 格式化日期，准备请求参数
    start_date = dt.strftime("%Y%m%d")
    end_date = dt.strftime("%Y%m%d")

    # 毫秒级时间戳
    t = int(time.time() * 1000)

    # 构造广西专用 API 请求 URL（需携带设备能力串才能获取节目单）
    url = (
        f"http://lvps.gx.bcs.ottcn.com:8080/cms-lvp-epg/lvps/getAllProgramlist"
        f"?abilityString={urllib.parse.quote(_ABILITY_STR)}"
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

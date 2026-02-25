"""
This file includes utils for grab and generate EPG.
They are referenced in main.py.
Many functions are verbose. They print out the progress.
Maybe I should add a verbose option. Or use logging.
"""

import yaml
import importlib
import requests
from epg.model import Channel
from datetime import datetime, date, timedelta
from epg.scraper import tz_shanghai


def load_config(path: str) -> list[Channel]:
    """
    Load channels config from yaml file.

    Args:
        path (str): The path of the yaml file.

    Returns:
        list[Channel]: The channels.
    """
    channels = []
    with open(path, "r") as stream:
        try:
            channels_config = yaml.safe_load(stream)
            for channel_id in channels_config:
                metadata = channels_config[channel_id]
                metadata.update(
                    {"last_update": datetime(1970, 1, 1, 0, 0, 0, tzinfo=tz_shanghai)}
                )
                channels.append(
                    Channel(
                        channel_id,
                        metadata,
                        lambda channel, date: scrap_channel(
                            channel, channels_config, date
                        ),
                    )
                )
        except yaml.YAMLError as exc:
            print(exc)
    return channels

def fetch_data(url):
    try:
        # 如果抓取失败，捕获异常并返回 None
        response = requests.get(url, verify=False)
        response.raise_for_status()  # 检查是否请求成功
        return response.text
    except requests.exceptions.RequestException as e:
        print(f"请求失败: {e}")
        return None

def scrap_channel(
    channel, channels_config, date: date = datetime.today().date()
) -> bool:
    channel.metadata["last_scraper"] = "FAILED"
    
    for scraper in channels_config[channel.id]["scraper"]:
        scraper_module = importlib.import_module("epg.scraper" + "." + scraper)
        update = getattr(scraper_module, "update")
        
        try:
            # 尝试抓取数据
            data = update(channel, channels_config[channel.id]["scraper"][scraper], date)
            
            # 如果抓取成功但数据为空，跳到下一个抓取器
            if not data:
                print(f"抓取器 {scraper} 成功执行，但没有返回数据，跳过此抓取器，尝试下一个。")
                continue
            
            # 如果抓取器成功，并且有数据，就保存并返回
            channel.metadata["last_scraper"] = scraper
            channel.metadata["last_update"] = datetime.now().astimezone()
            
            if channel.metadata.get("plugin") is not None:
                plugin_module = importlib.import_module(
                    "epg.plugin" + "." + channel.metadata["plugin"]
                )
                plugin_update = getattr(plugin_module, "update")
                plugin_update(channel, date)
            
            return True
        except Exception as e:
            print(f"抓取器 {scraper} 失败，错误: {e}，跳过此抓取器，尝试下一个抓取器。")
            continue  # 如果当前抓取器失败，继续轮询下一个抓取器

    print(f"所有抓取器都失败了，无法抓取频道 {channel.id} 数据。")
    return False  # 如果所有抓取器都失败，返回失败

def copy_channels(
    channels: list[Channel], new_channels: list[Channel]
) -> tuple[int, set]:
    """
    Copy channels from new_channels to channels.

    Args:
        channels (list[Channel]): The channels to copy to.
        new_channels (list[Channel]): The channels to copy from.

    Returns:
        tuple[int, set]: The number of reused channels and the dates of the programs.
    """
    num_reuse_channels = 0
    dates = set()
    for channel in channels:
        for new_channel in new_channels:
            if channel.id == new_channel.id:
                # Keep the programs in recap days
                for program in new_channel.programs:
                    recap_days = (
                        channel.metadata.get("recap")
                        if channel.metadata.get("recap") != None
                        else 0
                    )
                    preview_days = (
                        channel.metadata.get("preview")
                        if channel.metadata.get("preview") != None
                        else 0
                    )
                    if (
                        datetime.now().date() + timedelta(preview_days)
                        >= program.start_time.date()
                        >= datetime.now().date() - timedelta(recap_days)
                    ):
                        dates.add(program.start_time.date())
                        channel.programs.append(program)
                num_reuse_channels += 1
                channel.programs = list(set(channel.programs))  # Remove duplicates
                # print("reuse channel:", channel.id, channel.metadata["name"], xml_channel.metadata["last_update"].astimezone().isoformat(), channel.metadata["refresh"])
                if channel.programs != []:
                    channel.metadata["last_update"] = new_channel.metadata[
                        "last_update"
                    ]
                else:
                    channel.metadata["last_update"] = datetime(
                        1970, 1, 1, 0, 0, 0, tzinfo=tz_shanghai
                    )
                break
    return (num_reuse_channels, dates)


def update_preview(channel: Channel) -> int:
    """
    Update channel preview.

    Args:
        channel (Channel): The channel to update.

    Returns:
        int: The number of days previewed."""
    previewed_days = 0
    if channel.metadata.get("preview") == None:
        return previewed_days
    if channel.metadata["preview"] > 0:
        max_date = datetime.now().date() + timedelta(channel.metadata["preview"])
        pointer_date = datetime.now().date()
        # for program in channel.programs:
        #     if program.start_time.date() > channel_max_date:
        #         channel_max_date = program.start_time.date()
        if pointer_date < max_date:
            print("preview <- ", end="", flush=True)
        else:
            print("no need to refresh preview", flush=True)
        while pointer_date < max_date:
            pointer_date += timedelta(1)
            if channel.update(pointer_date):
                previewed_days += 1
                if pointer_date < max_date:
                    print(
                        pointer_date,
                        channel.metadata["last_scraper"],
                        end=", ",
                        flush=True,
                    )
                else:
                    print(pointer_date, channel.metadata["last_scraper"], flush=True)
    return previewed_days


def update_recap(channel: Channel) -> int:
    """
    Update channel recap.

    Args:
        channel (Channel): The channel to update.

    Returns:
        int: The number of days recaped."""
    recaped_days = 0
    if channel.metadata.get("recap") == None:
        return recaped_days
    if channel.metadata["recap"] > 0:
        min_date = datetime.now().date() - timedelta(channel.metadata["recap"])
        pointer_date = min_date
        max_date = datetime.now().date()
        for program in channel.programs:
            if program.start_time.date() < max_date:
                max_date = program.start_time.date()
        if pointer_date < max_date:
            print(
                "recap",
                min_date,
                "->",
                str(max_date - timedelta(1)) + ":",
                end=" ",
                flush=True,
            )
        else:
            print("no need to refresh recap", flush=True)
        while pointer_date < max_date:
            if channel.update(pointer_date):
                recaped_days += 1
                if recaped_days < channel.metadata.get("recap"):
                    print(
                        pointer_date,
                        channel.metadata["last_scraper"],
                        end=", ",
                        flush=True,
                    )
                else:
                    print(pointer_date, channel.metadata["last_scraper"], flush=True)
            pointer_date += timedelta(1)
    return recaped_days


def update_channel_full(channel, num_refresh_channels):
    """
    Update channel full.

    Args:
        channel (Channel): The channel to update.
        num_refresh_channels (int): Counter of the number of channels that have been refreshed.
    """

    def _update_recap(channel):
        recaped_days = update_recap(channel)
        if recaped_days > 0:
            print("total:", recaped_days, flush=True)
            return True
        return False

    def _update_preview(channel):
        previewed_days = update_preview(channel)
        if previewed_days > 0:
            print("total:", previewed_days, flush=True)
            return True
        return False

    if channel.metadata["refresh"] == "today":
        print(
            num_refresh_channels + 1,
            channel.id,
            channel.metadata["name"],
            "last update:",
            channel.metadata["last_update"],
        )
        _update_recap(channel)
        print(
            channel.metadata["refresh"],
            "<- now",
            datetime.now().astimezone().isoformat(),
            end=" ",
            flush=True,
        )
        if channel.update():
            print(channel.metadata["last_scraper"], flush=True)
        _update_preview(channel)
        return True
    if channel.metadata["refresh"] == "once":
        if channel.metadata["last_update"].date() != datetime.now().date():
            print(
                num_refresh_channels + 1,
                channel.id,
                channel.metadata["name"],
                "last update:",
                channel.metadata["last_update"],
            )
            _update_recap(channel)
            print(
                channel.metadata["refresh"],
                "<-",
                datetime.now().isoformat(),
                end=" ",
                flush=True,
            )
            channel.update()
            print(channel.metadata["last_scraper"], flush=True)
            _update_preview(channel)
            return True
    return False

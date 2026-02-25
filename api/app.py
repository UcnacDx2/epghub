from gevent import monkey

monkey.patch_all()

from apiflask import APIFlask, Schema
from apiflask.fields import String, Date
from flask import send_file, jsonify
from flask_compress import Compress
import os
import threading


app = APIFlask(__name__, docs_path=None)
Compress(app)

_refresh_lock = threading.Lock()
_refresh_status = {"running": False, "last_result": None}


class ChannelIn(Schema):
    ch = String(required=True)
    date = Date("%Y-%m-%d", required=True)


@app.route("/diyp")
@app.input(ChannelIn, "query")
def diyp(query_data):
    ch = query_data["ch"]
    date = query_data["date"]
    try:
        return send_file(
            os.path.join(
                os.getcwd(),
                "web",
                "diyp_files",
                ch,
                date.strftime("%Y-%m-%d") + ".json",
            )
        )
    except FileNotFoundError:
        return send_file(os.path.join(os.getcwd(), "web", "404.json"))


@app.route("/")
def index():
    return send_file(os.path.join(os.getcwd(), "web", "index.html"))


@app.route("/epg.xml")
def epg_xml():
    return send_file(os.path.join(os.getcwd(), "web", "epg.xml"))


@app.route("/robots.txt")
def robots_txt():
    return send_file(os.path.join(os.getcwd(), "web", "robots.txt"))


@app.route("/refresh", methods=["POST"])
def refresh():
    """Trigger a manual EPG refresh by running main.py in the background."""
    if _refresh_status["running"]:
        return jsonify({"status": "already_running"}), 409

    def _run():
        _refresh_status["running"] = True
        try:
            ret = os.system("poetry run python main.py")
            _refresh_status["last_result"] = "ok" if ret == 0 else f"exit:{ret}"
        finally:
            _refresh_status["running"] = False

    thread = threading.Thread(target=_run, daemon=True)
    thread.start()
    return jsonify({"status": "started"}), 202


@app.route("/refresh", methods=["GET"])
def refresh_status():
    """Return the current refresh status."""
    return jsonify(_refresh_status)

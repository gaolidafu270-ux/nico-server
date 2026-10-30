# ニコニコ動画ダウンローダー(yt-dlp)。Code.gs の getNicoVideo から呼ばれる
#   GET /health                … 動作確認(合言葉なし)
#   GET /start?id=sm9          … 取り込み開始 → {"job": "sm9"}
#   GET /status?job=sm9        … {"state": "running|done|error", "size": バイト数, "error": "..."}
#   GET /file?job=sm9          … 出来上がった mp4
#   /health 以外は、ヘッダー X-Nico-Key が環境変数 NICO_KEY と同じときだけ動く
import os, re, glob, time, threading, hmac
from flask import Flask, request, jsonify, send_file, abort
import yt_dlp

app = Flask(__name__)
KEY = os.environ.get("NICO_KEY", "")
WORK = "/tmp/nico"
MAX_BYTES = 45 * 1024 * 1024          # Code.gs の NICO_MAX_BYTES と同じ
HEIGHTS = [480, 360, 240]             # 大きすぎたら、画質を下げてやり直す
ID_RE = re.compile(r"^(?:sm|so|nm)\d{1,12}$")
os.makedirs(WORK, exist_ok=True)

jobs = {}                             # id -> {"state","size","error","t"}
lock = threading.Lock()               # 同時に1本ずつ取り込む(無料プランのメモリ節約)

# ログインが必要な動画用(任意): 環境変数 NICO_COOKIES に cookies.txt(Netscape形式)の中身を入れる
COOKIE_FILE = None
if os.environ.get("NICO_COOKIES"):
    COOKIE_FILE = os.path.join(WORK, "cookies.txt")
    with open(COOKIE_FILE, "w", encoding="utf-8") as f:
        f.write(os.environ["NICO_COOKIES"])


def authed():
    return bool(KEY) and hmac.compare_digest(request.headers.get("X-Nico-Key", ""), KEY)


def out_path(vid):
    return os.path.join(WORK, vid + ".mp4")


def cleanup():
    now = time.time()
    for p in glob.glob(os.path.join(WORK, "*")):
        try:
            if p != COOKIE_FILE and now - os.path.getmtime(p) > 3600:
                os.remove(p)
        except OSError:
            pass


def download(vid):
    with lock:
        try:
            last_err = "取り込めませんでした"
            for h in HEIGHTS:
                for p in glob.glob(os.path.join(WORK, vid + ".*")):
                    os.remove(p)
                opts = {
                    "format": f"bv*[height<={h}]+ba/b[height<={h}]/worst",
                    "merge_output_format": "mp4",
                    "outtmpl": os.path.join(WORK, "%(id)s.%(ext)s"),
                    "noplaylist": True,
                    "quiet": True,
                    "no_warnings": True,
                    "socket_timeout": 30,
                    "retries": 3,
                }
                if COOKIE_FILE:
                    opts["cookiefile"] = COOKIE_FILE
                try:
                    with yt_dlp.YoutubeDL(opts) as ydl:
                        ydl.download(["https://www.nicovideo.jp/watch/" + vid])
                except Exception as e:  # noqa
                    last_err = str(e)[:200]
                    break
                p = out_path(vid)
                if os.path.exists(p):
                    size = os.path.getsize(p)
                    if size <= MAX_BYTES:
                        jobs[vid] = {"state": "done", "size": size, "t": time.time()}
                        return
                    last_err = f"{h}pでも大きすぎます({size // 1048576}MB)"
                else:
                    last_err = "mp4ができませんでした"
            jobs[vid] = {"state": "error", "error": last_err, "t": time.time()}
        except Exception as e:  # noqa
            jobs[vid] = {"state": "error", "error": str(e)[:200], "t": time.time()}


@app.get("/health")
def health():
    return jsonify(ok=True, yt_dlp=yt_dlp.version.__version__)


@app.get("/start")
def start():
    if not authed():
        return jsonify(error="forbidden"), 403
    vid = request.args.get("id", "").strip().lower()
    if not ID_RE.match(vid):
        return jsonify(error="動画IDが正しくありません"), 400
    cleanup()
    j = jobs.get(vid)
    if j and j["state"] == "done" and os.path.exists(out_path(vid)):
        return jsonify(job=vid)
    if not (j and j["state"] == "running"):
        jobs[vid] = {"state": "running", "t": time.time()}
        threading.Thread(target=download, args=(vid,), daemon=True).start()
    return jsonify(job=vid)


@app.get("/status")
def status():
    if not authed():
        return jsonify(error="forbidden"), 403
    vid = request.args.get("job", "").strip().lower()
    j = jobs.get(vid)
    if not j:
        return jsonify(state="error", error="取り込みの記録がありません。もう一度試してください")
    return jsonify(j)


@app.get("/file")
def file():
    if not authed():
        abort(403)
    vid = request.args.get("job", "").strip().lower()
    if not ID_RE.match(vid) or not os.path.exists(out_path(vid)):
        abort(404)
    return send_file(out_path(vid), mimetype="video/mp4")


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 8080)))

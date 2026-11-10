"""Add a CFB Daily episode and rebuild feed.xml.

Usage: python3 tools/add_episode.py SCRIPT.txt "Episode title" "One-line summary" YYYY-MM-DD

Reads the spoken script, renders it to MP3 with edge-tts, copies it to
episodes/, keeps the newest KEEP episodes, and rewrites feed.xml from
episodes/index.json.
"""
import email.utils, json, os, subprocess, sys, datetime, html, tempfile, time

BASE = "https://raw.githubusercontent.com/Anon9789/cfb-daily-podcast/main"
KEEP = 14
VOICE = "en-US-AndrewNeural"
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
EP_DIR = os.path.join(ROOT, "episodes")
INDEX = os.path.join(EP_DIR, "index.json")


def tts(text_file, out, env, tries=6):
    """Render one chunk; edge-tts intermittently returns NoAudioReceived, so retry."""
    cmd = ["edge-tts", "--voice", VOICE, "--rate=+5%", "-f", text_file, "--write-media", out]
    if os.environ.get("HTTPS_PROXY"):
        cmd[1:1] = ["--proxy", os.environ["HTTPS_PROXY"]]
    for i in range(tries):
        if subprocess.run(cmd, env=env, capture_output=True).returncode == 0 and os.path.getsize(out) > 0:
            return
        time.sleep(3 * (i + 1))
    raise RuntimeError(f"edge-tts failed {tries} times on {text_file}")


def render(script, out_mp3):
    """Render paragraph by paragraph (short requests fail less), then join."""
    env = dict(os.environ, SSL_CERT_FILE=os.environ.get("SSL_CERT_FILE", "/root/.ccr/ca-bundle.crt"))
    paras = [p.strip() for p in open(script).read().split("\n\n") if p.strip()]
    with tempfile.TemporaryDirectory() as tmp:
        parts = []
        for n, p in enumerate(paras):
            txt, mp3 = os.path.join(tmp, f"{n:03d}.txt"), os.path.join(tmp, f"{n:03d}.mp3")
            open(txt, "w").write(p)
            tts(txt, mp3, env)
            parts.append(mp3)
        lst = os.path.join(tmp, "list.txt")
        open(lst, "w").write("".join(f"file '{m}'\n" for m in parts))
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "concat", "-safe", "0", "-i", lst,
                        "-ac", "1", "-b:a", "64k", out_mp3], check=True)
    dur = float(subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                                "-of", "csv=p=0", out_mp3], capture_output=True, text=True).stdout)
    return int(round(dur))


def build_feed(eps):
    items = []
    for e in eps:
        items.append(f"""    <item>
      <title>{html.escape(e['title'])}</title>
      <description>{html.escape(e['summary'])}</description>
      <itunes:summary>{html.escape(e['summary'])}</itunes:summary>
      <enclosure url="{BASE}/episodes/{e['file']}" length="{e['bytes']}" type="audio/mpeg"/>
      <guid isPermaLink="false">cfb-daily-{e['date']}</guid>
      <pubDate>{e['pubdate']}</pubDate>
      <itunes:duration>{e['seconds']}</itunes:duration>
      <itunes:explicit>false</itunes:explicit>
    </item>""")
    now = email.utils.formatdate(usegmt=True)
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0" xmlns:itunes="http://www.itunes.com/dtds/podcast-1.0.dtd">
  <channel>
    <title>CFB Daily</title>
    <link>https://github.com/Anon9789/cfb-daily-podcast</link>
    <language>en-us</language>
    <description>A personal daily college football briefing: top stories plus one figure worth knowing.</description>
    <itunes:author>CFB Daily</itunes:author>
    <itunes:summary>A personal daily college football briefing: top stories plus one figure worth knowing.</itunes:summary>
    <itunes:image href="{BASE}/cover.jpg"/>
    <itunes:category text="Sports"><itunes:category text="Football"/></itunes:category>
    <itunes:explicit>false</itunes:explicit>
    <itunes:block>Yes</itunes:block>
    <lastBuildDate>{now}</lastBuildDate>
{chr(10).join(items)}
  </channel>
</rss>
"""


def main():
    script, title, summary, date = sys.argv[1:5]
    os.makedirs(EP_DIR, exist_ok=True)
    fname = f"cfb-daily-{date}.mp3"
    out = os.path.join(EP_DIR, fname)
    seconds = render(script, out)
    eps = json.load(open(INDEX)) if os.path.exists(INDEX) else []
    eps = [e for e in eps if e["date"] != date]
    # 12:10 UTC = about 7:10 a.m. Central
    d = datetime.datetime.strptime(date, "%Y-%m-%d").replace(hour=12, minute=10, tzinfo=datetime.timezone.utc)
    eps.append(dict(date=date, title=title, summary=summary, file=fname, bytes=os.path.getsize(out),
                    seconds=seconds, pubdate=email.utils.format_datetime(d, usegmt=True)))
    eps.sort(key=lambda e: e["date"], reverse=True)
    for old in eps[KEEP:]:
        p = os.path.join(EP_DIR, old["file"])
        if os.path.exists(p):
            os.remove(p)
    eps = eps[:KEEP]
    json.dump(eps, open(INDEX, "w"), indent=1)
    open(os.path.join(ROOT, "feed.xml"), "w").write(build_feed(eps))
    print(f"{fname}: {seconds}s, {os.path.getsize(out)} bytes; feed has {len(eps)} episodes")


if __name__ == "__main__":
    main()

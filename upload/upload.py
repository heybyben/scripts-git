#!/usr/bin/env python3

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path


class C:
    RESET = "\033[0m"
    BOLD = "\033[1m"
    DIM = "\033[2m"
    RED = "\033[31m"
    GREEN = "\033[32m"
    YELLOW = "\033[33m"
    BLUE = "\033[34m"
    CYAN = "\033[36m"
    WHITE = "\033[37m"


def ok(msg):
    print(f"{C.GREEN}[OK]{C.RESET}  {msg}")


def err(msg):
    print(f"{C.RED}[ERR]{C.RESET} {msg}", file=sys.stderr)


def warn(msg):
    print(f"{C.YELLOW}[WARN]{C.RESET} {msg}")


def step(msg):
    print(f"{C.BLUE}[....]{C.RESET} {msg}")


def info(msg):
    print(f"{C.CYAN}[INFO]{C.RESET} {msg}")


def header(title):
    bar = "=" * (len(title) + 4)
    print(f"\n{C.BOLD}{C.WHITE}{bar}{C.RESET}")
    print(f"{C.BOLD}{C.WHITE}  {title}{C.RESET}")
    print(f"{C.BOLD}{C.WHITE}{bar}{C.RESET}\n")


def section(title):
    print(f"\n{C.BOLD}{C.CYAN}-- {title} {'-' * max(0, 40 - len(title))}{C.RESET}")


def load_env(env_path: Path):
    """Load key=value pairs from a .env file into os.environ."""
    if not env_path.is_file():
        err(f"{env_path} file not found!")
        sys.exit(1)
    with env_path.open() as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, val = line.partition("=")
            val = val.strip().strip('"').strip("'")
            os.environ.setdefault(key.strip(), val)


def env(key, default=""):
    return os.environ.get(key, default)


def check_dependencies():
    required = ["curl", "jq"]
    missing = [c for c in required if not shutil.which(c)]
    if missing:
        for m in missing:
            err(f"Missing required command: {C.BOLD}{m}{C.RESET}")
        sys.exit(1)


def human_size(size_bytes: int) -> str:
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if size_bytes < 1024:
            return f"{size_bytes:.1f} {unit}"
        size_bytes /= 1024
    return f"{size_bytes:.1f} PB"


def md5(path: Path) -> str:
    h = hashlib.md5()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def sha1(path: Path) -> str:
    h = hashlib.sha1()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def upload_pixeldrain(file: Path) -> str | None:
    section("PixelDrain")
    step(f"Uploading {file.name} to PixelDrain...")
    api_key = env("PIXELDRAIN_API_KEY")

    result = subprocess.run(
        [
            "curl",
            "--progress-bar",
            "-u",
            f":{api_key}",
            "-F",
            f"file=@{file}",
            "https://pixeldrain.com/api/file",
        ],
        capture_output=False,
        text=True,
    )
    capture = subprocess.run(
        [
            "curl",
            "-s",
            "-u",
            f":{api_key}",
            "-F",
            f"file=@{file}",
            "https://pixeldrain.com/api/file",
        ],
        capture_output=True,
        text=True,
    )
    try:
        data = json.loads(capture.stdout)
        file_id = data.get("id")
        if not file_id or file_id == "null":
            raise ValueError(data)
    except Exception as e:
        err(f"PixelDrain upload failed: {e}")
        return None

    link = f"https://pixeldrain.com/u/{file_id}"
    ok(f"PixelDrain -> {C.WHITE}{link}{C.RESET}")
    return f"PixelDrain: {link}"


def upload_gofile(file: Path) -> str | None:
    section("GoFile")
    step(f"Uploading {file.name} to GoFile...")
    token = env("GOFILE_TOKEN")

    cmd = ["curl", "--progress-bar", "-F", f"file=@{file}"]
    if token:
        cmd += ["-F", f"token={token}"]
    cmd.append("https://upload.gofile.io/uploadFile")

    capture = subprocess.run(
        ["curl", "-s"]
        + (["-F", f"token={token}"] if token else [])
        + ["-F", f"file=@{file}", "https://upload.gofile.io/uploadFile"],
        capture_output=True,
        text=True,
    )
    subprocess.run(
        ["curl", "--progress-bar"]
        + (["-F", f"token={token}"] if token else [])
        + [
            "-F",
            f"file=@{file}",
            "https://upload.gofile.io/uploadFile",
            "-o",
            "/dev/null",
        ],
    )

    try:
        data = json.loads(capture.stdout)
        link = data["data"]["downloadPage"]
        if not link.startswith("http"):
            raise ValueError(data)
    except Exception as e:
        err(f"GoFile upload failed: {e}")
        return None

    ok(f"GoFile -> {C.WHITE}{link}{C.RESET}")
    return f"GoFile: {link}"


def upload_ranoz(file: Path) -> str | None:
    section("Ranoz.gg")
    step(f"Requesting upload URL for {file.name}...")
    size_b = file.stat().st_size

    init = subprocess.run(
        [
            "curl",
            "-s",
            "-X",
            "POST",
            "https://ranoz.gg/api/v1/files/upload_url",
            "-H",
            "Content-Type: application/json",
            "-d",
            json.dumps({"filename": file.name, "size": size_b}),
        ],
        capture_output=True,
        text=True,
    )
    try:
        meta = json.loads(init.stdout)
        upload_url = meta["data"]["upload_url"]
        link = meta["data"]["url"]
        if upload_url == "null":
            raise ValueError(meta)
    except Exception as e:
        err(f"Ranoz init failed: {e}")
        return None

    step(f"Uploading to Ranoz.gg...")
    subprocess.run(
        [
            "curl",
            "--progress-bar",
            "-X",
            "PUT",
            upload_url,
            "--upload-file",
            str(file),
            "-H",
            f"Content-Length: {size_b}",
            "-o",
            "/dev/null",
        ],
    )

    ok(f"Ranoz.gg -> {C.WHITE}{link}{C.RESET}")
    return f"Ranoz.gg: {link}"

def send_telegram(
    file: Path, size_b: int, file_md5: str, file_sha1: str, now: str, results: list[str]
):
    import urllib.request
    import urllib.error

    token = env("TELEGRAM_BOT_TOKEN")
    chat_id = env("TELEGRAM_CHAT_ID")

    if not token or not chat_id:
        warn("TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID not set. Skipping Telegram.")
        return

    buttons = []
    for entry in results:
        if ": " in entry:
            label, url = entry.split(": ", 1)
            buttons.append({"text": f"Download via {label}", "url": url.strip()})

    keyboard = {"inline_keyboard": [[btn] for btn in buttons]}

    msg = (
        f"*Upload Complete*\n\n"
        f"*File:* `{file.name}`\n"
        f"*Size:* {human_size(size_b)}\n"
        f"*MD5:* `{file_md5}`\n"
        f"*SHA1:* `{file_sha1}`\n"
        f"*Time:* {now}"
    )

    payload = json.dumps(
        {
            "chat_id": chat_id,
            "text": msg,
            "parse_mode": "Markdown",
            "reply_markup": keyboard,
        }
    ).encode()

    req = urllib.request.Request(
        f"https://api.telegram.org/bot{token}/sendMessage",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    try:
        with urllib.request.urlopen(req) as resp:
            data = json.loads(resp.read())
            if data.get("ok"):
                ok("Telegram notification sent.")
            else:
                warn(f"Telegram API error: {data.get('description')}")
    except urllib.error.URLError as e:
        warn(f"Telegram request failed: {e}")


ALL_SERVICES = ["PixelDrain", "GoFile", "Ranoz"]

UPLOADERS = {
    "PixelDrain": upload_pixeldrain,
    "GoFile": upload_gofile,
    "Ranoz": upload_ranoz,
}


def main():
    parser = argparse.ArgumentParser(
        description="Multi-service file uploader",
        formatter_class=argparse.RawTextHelpFormatter,
    )
    svc_group = parser.add_mutually_exclusive_group(required=True)
    svc_group.add_argument(
        "-A",
        dest="services",
        action="store_const",
        const=ALL_SERVICES,
        help="Upload to ALL services",
    )
    svc_group.add_argument(
        "-P",
        dest="services",
        action="store_const",
        const=["PixelDrain"],
        help="Upload to PixelDrain only",
    )
    svc_group.add_argument(
        "-G",
        dest="services",
        action="store_const",
        const=["GoFile"],
        help="Upload to GoFile only",
    )
    svc_group.add_argument(
        "-R",
        dest="services",
        action="store_const",
        const=["Ranoz"],
        help="Upload to Ranoz.gg only",
    )

    parser.add_argument(
        "-F", "--file", required=True, metavar="FILE", help="Path to the file to upload"
    )

    args = parser.parse_args()
    file = Path(args.file)

    load_env(Path.home() / ".env")
    check_dependencies()

    if not file.is_file():
        err(f"File not found: {file}")
        sys.exit(1)

    size_b = file.stat().st_size
    file_md5 = md5(file)
    file_sha1 = sha1(file)
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    header(f"File Uploader  ->  {file.name}")
    print(f"  {C.DIM}Size  :{C.RESET} {C.WHITE}{human_size(size_b)}{C.RESET}")
    print(f"  {C.DIM}MD5   :{C.RESET} {C.WHITE}{file_md5}{C.RESET}")
    print(f"  {C.DIM}SHA1  :{C.RESET} {C.WHITE}{file_sha1}{C.RESET}")
    print(f"  {C.DIM}Time  :{C.RESET} {C.WHITE}{now}{C.RESET}")
    print(f"  {C.DIM}Target:{C.RESET} {C.WHITE}{', '.join(args.services)}{C.RESET}")

    results = []
    for svc in args.services:
        link = UPLOADERS[svc](file)
        if link:
            results.append(link)

    header("Summary")
    if results:
        for r in results:
            print(f"  {C.GREEN}+{C.RESET} {C.WHITE}{r}{C.RESET}")
    else:
        warn("No successful uploads.")

    send_telegram(file, size_b, file_md5, file_sha1, now, results)

    print(f"\n{C.BOLD}{C.GREEN}Done.{C.RESET}\n")


if __name__ == "__main__":
    main()

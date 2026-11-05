#!/usr/bin/env python3
"""Take one occupancy sample of Hallenbad City (Zürich) and append it to occupancy.csv.

Data source: the same public WebSocket the stadt-zuerich.ch page uses
(wss://badi-public.crowdmonitor.ch:9591/api). Send "all", receive a JSON array
with uid / name / maxspace / currentfill for every pool. Stdlib only.

Usage:  python3 collect.py            # one sample, appended to occupancy.csv
        python3 collect.py --uid SSD-7  # another pool (e.g. Oerlikon)
        python3 collect.py --open-hours 6-22  # skip samples outside opening hours
"""
import argparse, base64, csv, json, os, socket, ssl, struct, sys
from datetime import datetime
from zoneinfo import ZoneInfo

HOST, PORT, PATH = "badi-public.crowdmonitor.ch", 9591, "/api"
HERE = os.path.dirname(os.path.abspath(__file__))
FIELDS = ["timestamp", "uid", "name", "current", "max", "pct"]


def _recv_exact(sock, n):
    buf = b""
    while len(buf) < n:
        chunk = sock.recv(n - len(buf))
        if not chunk:
            raise ConnectionError("socket closed")
        buf += chunk
    return buf


def fetch_all(timeout=15):
    ctx = ssl.create_default_context()
    raw = socket.create_connection((HOST, PORT), timeout=timeout)
    sock = ctx.wrap_socket(raw, server_hostname=HOST)
    key = base64.b64encode(os.urandom(16)).decode()
    sock.sendall((
        f"GET {PATH} HTTP/1.1\r\nHost: {HOST}:{PORT}\r\nUpgrade: websocket\r\n"
        f"Connection: Upgrade\r\nSec-WebSocket-Key: {key}\r\n"
        f"Sec-WebSocket-Version: 13\r\nOrigin: https://www.stadt-zuerich.ch\r\n\r\n"
    ).encode())
    head = b""
    while b"\r\n\r\n" not in head:
        head += sock.recv(1)
    if b" 101 " not in head.split(b"\r\n")[0]:
        raise ConnectionError("handshake failed: " + head.split(b"\r\n")[0].decode())

    # client frames must be masked
    payload = b"all"
    mask = os.urandom(4)
    masked = bytes(b ^ mask[i % 4] for i, b in enumerate(payload))
    sock.sendall(bytes([0x81, 0x80 | len(payload)]) + mask + masked)

    message = b""
    while True:
        b1, b2 = _recv_exact(sock, 2)
        fin, opcode, length = b1 & 0x80, b1 & 0x0F, b2 & 0x7F
        if length == 126:
            length = struct.unpack(">H", _recv_exact(sock, 2))[0]
        elif length == 127:
            length = struct.unpack(">Q", _recv_exact(sock, 8))[0]
        data = _recv_exact(sock, length)  # server frames are unmasked
        if opcode in (0x1, 0x0):  # text / continuation
            message += data
            if fin:
                break
        elif opcode == 0x8:
            raise ConnectionError("server closed connection")
    sock.close()
    return json.loads(message)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--uid", default="SSD-4", help="pool id (SSD-4 = Hallenbad City)")
    ap.add_argument("--out", default=os.path.join(HERE, "occupancy.csv"))
    ap.add_argument("--open-hours", metavar="6-22",
                    help="only sample between these Zürich hours (inclusive); outside, exit quietly")
    args = ap.parse_args()

    now_dt = datetime.now(ZoneInfo("Europe/Zurich"))
    if args.open_hours:
        lo, hi = (int(x) for x in args.open_hours.split("-"))
        if not lo * 60 <= now_dt.hour * 60 + now_dt.minute <= hi * 60:
            print(f"{now_dt:%H:%M} Zürich time: outside {lo:02d}:00-{hi:02d}:00, skipping")
            return

    pool = next((p for p in fetch_all() if p["uid"] == args.uid), None)
    if pool is None:
        sys.exit(f"uid {args.uid} not found in feed")
    cur, mx = float(pool["currentfill"]), float(pool["maxspace"])
    if mx <= 0 or cur < 0:
        sys.exit(f"invalid data for {args.uid}: current={cur} max={mx}")  # page treats this as invalid too

    now = now_dt.isoformat(timespec="seconds")
    row = [now, pool["uid"], pool["name"], int(cur), int(mx), round(100 * cur / mx, 1)]
    new = not os.path.exists(args.out)
    with open(args.out, "a", newline="") as f:
        w = csv.writer(f)
        if new:
            w.writerow(FIELDS)
        w.writerow(row)
    print(",".join(map(str, row)))


if __name__ == "__main__":
    main()

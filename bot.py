"""Bot Telegram pencatat pemasukan & pengeluaran, berjalan di GitHub Actions.

python bot.py            -> jalankan bot (long polling ~5,5 jam, lalu workflow menyalakan ulang)
python bot.py ringkasan  -> kirim ringkasan harian (+ mingguan kalau hari Minggu)
"""
import base64
import functools
import hashlib
import json
import os
import subprocess
import sys
import time
import urllib.request
from collections import Counter
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import anthropic
from cryptography.fernet import Fernet

TZ = ZoneInfo("Asia/Jakarta")
MODEL = "claude-opus-5-5"  # "claude-haiku-5-5" jauh lebih murah kalau hasilnya sudah cukup
DATA = "data.enc"  # satu baris terenkripsi per transaksi, aman disimpan di repo publik
RUN_SECONDS = 5.5 * 3600  # job GitHub maksimal 6 jam
TOKEN = os.environ.get("TELEGRAM_TOKEN", "")
CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")
KATEGORI = ["Makan & Minum", "Transportasi", "Belanja", "Tagihan", "Hiburan",
            "Kesehatan", "Pendidikan", "Gaji", "Usaha", "Lainnya"]
JUDUL = {"hari": "hari ini", "minggu": "minggu ini", "bulan": "bulan ini"}

BANTUAN = """Kirim catatan keuangan, contoh:
• kopi 18rb
• gajian 5jt
• bensin 30k, parkir 5rb
• foto struk / foto catatan tulisan tangan

Perintah:
/hari /minggu /bulan  ringkasan
/batal  hapus catatan terakhir"""

PROMPT = f"""Kamu mencatat keuangan pribadi (Rupiah). Dari pesan teks, foto struk, atau foto tulisan tangan, ambil semua transaksi uang.
- jumlah: bilangan bulat Rupiah. "18rb"/"18k" = 18000, "1,5jt" = 1500000.
- Struk belanja: satu transaksi berisi TOTAL yang dibayar; keterangan = nama toko + ringkasan barang.
- Tulisan tangan atau teks bisa berisi beberapa transaksi.
- jenis "masuk" untuk uang diterima (gaji, transfer masuk, hasil jualan), "keluar" untuk uang dibayar.
- kategori salah satu dari: {", ".join(KATEGORI)}.
- keterangan singkat dalam bahasa Indonesia.
Jika tidak ada transaksi, kembalikan daftar kosong."""

SCHEMA = {
    "type": "object",
    "properties": {"transaksi": {"type": "array", "items": {
        "type": "object",
        "properties": {
            "jenis": {"type": "string", "enum": ["masuk", "keluar"]},
            "jumlah": {"type": "integer"},
            "kategori": {"type": "string", "enum": KATEGORI},
            "keterangan": {"type": "string"},
        },
        "required": ["jenis", "jumlah", "kategori", "keterangan"],
        "additionalProperties": False,
    }}},
    "required": ["transaksi"],
    "additionalProperties": False,
}


@functools.cache
def fernet():
    key = hashlib.scrypt(os.environ["DATA_KEY"].encode(), salt=b"catatpengeluaran", n=2**14, r=8, p=1, dklen=32)
    return Fernet(base64.urlsafe_b64encode(key))


def load():
    if not os.path.exists(DATA):
        return []
    with open(DATA) as f:
        return [json.loads(fernet().decrypt(line.encode())) for line in f.read().split()]


def save(rows):
    with open(DATA, "a") as f:
        for r in rows:
            f.write(fernet().encrypt(json.dumps(r).encode()).decode() + "\n")


def undo():
    """Hapus semua transaksi dari pesan terakhir, kembalikan yang dihapus."""
    rows = load()
    if not rows:
        return []
    k = len(rows)
    while k and rows[k - 1]["mid"] == rows[-1]["mid"]:
        k -= 1
    with open(DATA) as f:
        lines = f.read().split()
    with open(DATA, "w") as f:
        f.writelines(line + "\n" for line in lines[:k])
    return rows[k:]


def push(msg):
    branch = os.environ.get("GITHUB_REF_NAME", "main")
    for cmd in (["git", "add", DATA], ["git", "commit", "-qm", msg],
                ["git", "pull", "-q", "--rebase", "origin", branch], ["git", "push", "-q", "origin", "HEAD"]):
        if subprocess.run(cmd).returncode:
            print("git gagal:", " ".join(cmd))  # data tetap di file lokal, ikut ter-push di simpan berikutnya
            return


def tg(method, **params):
    req = urllib.request.Request(f"https://api.telegram.org/bot{TOKEN}/{method}",
                                 json.dumps(params).encode(), {"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=90) as r:
        return json.load(r)["result"]


def send(text):
    tg("sendMessage", chat_id=CHAT_ID, text=text)


def image_block(file_id, media_type):
    path = tg("getFile", file_id=file_id)["file_path"]
    with urllib.request.urlopen(f"https://api.telegram.org/file/bot{TOKEN}/{path}", timeout=60) as r:
        data = base64.standard_b64encode(r.read()).decode()
    return {"type": "image", "source": {"type": "base64", "media_type": media_type, "data": data}}


def extract(content):
    r = anthropic.Anthropic().beta.messages.create(
        model=MODEL,
        max_tokens=16000,
        system=PROMPT,
        betas=["server-side-fallback-2026-07-01"],
        fallbacks="default",
        output_config={"effort": "low", "format": {"type": "json_schema", "schema": SCHEMA}},
        messages=[{"role": "user", "content": content}],
    )
    if r.stop_reason != "end_turn":
        raise RuntimeError(f"stop_reason={r.stop_reason}")
    text = next(b.text for b in r.content if b.type == "text")
    return [t for t in json.loads(text)["transaksi"] if t["jumlah"] > 0]


def rp(n):
    return "Rp " + f"{n:,}".replace(",", ".")


def baris(r):
    return f"{'➕' if r['jenis'] == 'masuk' else '➖'} {rp(r['jumlah'])} · {r['kategori']} · {r['keterangan']}"


def ringkasan(periode, now=None):
    now = now or datetime.now(TZ)
    awal = now.replace(hour=0, minute=0, second=0, microsecond=0)
    if periode == "minggu":
        awal -= timedelta(days=now.weekday())  # mulai Senin
    elif periode == "bulan":
        awal = awal.replace(day=1)
    rows = [r for r in load() if awal <= datetime.fromisoformat(r["t"]) <= now]
    masuk = sum(r["jumlah"] for r in rows if r["jenis"] == "masuk")
    kategori = Counter()
    for r in rows:
        if r["jenis"] == "keluar":
            kategori[r["kategori"]] += r["jumlah"]
    keluar = sum(kategori.values())
    rentang = f"{awal:%d/%m/%Y}" if periode == "hari" else f"{awal:%d/%m} – {now:%d/%m/%Y}"
    out = [f"📊 Ringkasan {JUDUL[periode]} ({rentang})",
           f"Pemasukan: {rp(masuk)}", f"Pengeluaran: {rp(keluar)}", f"Selisih: {rp(masuk - keluar)}"]
    if kategori:
        out += ["", "Pengeluaran per kategori:"] + [f"• {k}: {rp(v)}" for k, v in kategori.most_common()]
    return "\n".join(out)


def handle(msg):
    if str(msg["chat"]["id"]) != CHAT_ID:
        return f"Chat ID kamu: {msg['chat']['id']}\nSimpan sebagai secret TELEGRAM_CHAT_ID lalu jalankan ulang workflow bot."
    text = msg.get("text") or msg.get("caption") or ""
    cmd = text.split()[0].split("@")[0].lower() if text.startswith("/") else ""
    if cmd in ("/start", "/bantuan"):
        return BANTUAN
    if cmd[1:] in JUDUL:
        return ringkasan(cmd[1:])
    if cmd == "/batal":
        gone = undo()
        if gone:
            push("batal")
        return "🗑️ Dihapus:\n" + "\n".join(map(baris, gone)) if gone else "Belum ada catatan."

    content = []
    photo, doc = msg.get("photo"), msg.get("document") or {}
    if photo:
        content.append(image_block(photo[-1]["file_id"], "image/jpeg"))
    elif doc.get("mime_type", "").startswith("image/"):
        content.append(image_block(doc["file_id"], doc["mime_type"]))
    if text:
        content.append({"type": "text", "text": text})
    if not content:
        return "Kirim teks atau foto ya. /bantuan untuk contoh."

    tg("sendChatAction", chat_id=CHAT_ID, action="typing")
    items = extract(content)
    if not items:
        return "Tidak ada transaksi yang terbaca. Coba tulis seperti: kopi 18rb"
    t = datetime.fromtimestamp(msg["date"], TZ).isoformat(timespec="seconds")
    rows = [{"t": t, "mid": msg["message_id"], **i} for i in items]
    save(rows)
    push("catat")
    return "✅ Tercatat:\n" + "\n".join(map(baris, rows)) + "\n\nSalah baca? /batal"


def run():
    end, offset = time.time() + RUN_SECONDS, 0
    while time.time() < end:
        try:
            updates = tg("getUpdates", offset=offset, timeout=50, allowed_updates=["message"])
        except Exception as e:
            print("getUpdates gagal:", e)
            time.sleep(10)
            continue
        for u in updates:
            offset = u["update_id"] + 1
            msg = u.get("message")
            if not msg:
                continue
            try:
                reply = handle(msg)
            except Exception as e:  # jangan cetak isi pesan: log repo publik bisa dilihat orang
                print("gagal memproses:", type(e).__name__, e)
                reply = "⚠️ Gagal memproses pesan ini, coba kirim ulang."
            try:
                tg("sendMessage", chat_id=msg["chat"]["id"], text=reply)
            except Exception as e:
                print("gagal membalas:", e)
    if offset:
        tg("getUpdates", offset=offset, timeout=0)  # konfirmasi pesan terakhir agar tidak diproses dua kali


if __name__ == "__main__":
    if not os.environ.get("DATA_KEY"):
        sys.exit("Secret DATA_KEY belum diisi")
    if sys.argv[1:] == ["ringkasan"]:
        send(ringkasan("hari"))
        if datetime.now(TZ).weekday() == 6:
            send(ringkasan("minggu"))
    else:
        run()

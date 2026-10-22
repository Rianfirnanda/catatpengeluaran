"""Bot Telegram pencatat pemasukan & pengeluaran, berjalan di GitHub Actions.

python bot.py            -> jalankan bot (long polling ~5,5 jam, lalu workflow menyalakan ulang)
python bot.py ringkasan  -> kirim ringkasan harian (+ mingguan dan tips hemat kalau hari Minggu)
"""
import base64
import calendar
import csv
import functools
import hashlib
import io
import json
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request
from collections import Counter
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from cryptography.fernet import Fernet

TZ = ZoneInfo("Asia/Jakarta")
MODEL = "gemini-3.8-flash"
CADANGAN = "gemini-3.5-flash-lite"  # dipakai kalau MODEL sedang penuh (503) atau kuotanya habis (429)
GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/interactions"
DATA = "data.enc"  # satu baris terenkripsi per transaksi, aman disimpan di repo publik
SETTING = "setting.enc"  # budget & target tabungan, terenkripsi
RUN_SECONDS = 5.5 * 3600  # job GitHub maksimal 6 jam
TOKEN = os.environ.get("TELEGRAM_TOKEN", "")
CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")
GEMINI_KEY = os.environ.get("GEMINI_API_KEY", "")
GAMBAR = ("image/jpeg", "image/png", "image/webp", "image/heic", "image/heif")  # format yang dibaca Gemini
KATEGORI = ["Makan & Minum", "Transportasi", "Belanja", "Tagihan", "Hiburan", "Kesehatan",
            "Pendidikan", "Gaji", "Usaha", "Tabungan", "Lainnya"]
JUDUL = {"hari": "hari ini", "minggu": "minggu ini", "bulan": "bulan ini"}

BANTUAN = """Kirim catatan keuangan, contoh:
• kopi 18rb
• gajian 5jt
• nabung 500rb
• bensin 30k, parkir 5rb
• foto struk / foto catatan tulisan tangan

Ringkasan: /hari /minggu /bulan
Budget bulanan: /budget makan 1,5jt  (lihat: /budget)
Target tabungan: /target 10jt 2027-06  (lihat: /target)
Tips hemat dari AI: /tips
Riwayat & hapus: /riwayat  /hapus 12 15  /batal (pesan terakhir)
Unduh semua data: /ekspor"""

PROMPT = f"""Kamu mencatat keuangan pribadi (Rupiah). Dari pesan teks, foto struk, atau foto tulisan tangan, ambil semua transaksi uang.
- jumlah: bilangan bulat Rupiah. "18rb"/"18k" = 18000, "1,5jt" = 1500000.
- Struk belanja: satu transaksi berisi TOTAL yang dibayar; keterangan = nama toko + ringkasan barang.
- Tulisan tangan atau teks bisa berisi beberapa transaksi.
- jenis "masuk" untuk uang diterima (gaji, transfer masuk, hasil jualan), "keluar" untuk uang dibayar.
- Uang yang ditabung/disisihkan ke tabungan: jenis "keluar", kategori "Tabungan". Mengambil uang dari tabungan: jenis "masuk", kategori "Tabungan".
- kategori salah satu dari: {", ".join(KATEGORI)}.
- keterangan singkat dalam bahasa Indonesia.
Jika tidak ada transaksi, kembalikan daftar kosong.
pertanyaan: true jika pesan menanyakan atau meminta info tentang keuangan yang sudah dicatat (mis. "berapa total pengeluaran hari ini", "total jajan bulan ini"), bukan mencatat transaksi baru."""

TANYA_PROMPT = """Kamu asisten keuangan pribadi. Jawab pertanyaan pemilik hanya berdasarkan data di bawah.
Untuk total hari/minggu/bulan, pakai angka dari ringkasan yang sudah dihitung. Kalau harus menjumlah sendiri, hitung dengan teliti.
Kalau datanya tidak ada, bilang terus terang. Bahasa Indonesia santai dan singkat, tanpa markdown."""

TIPS_PROMPT = """Kamu teman yang paham keuangan pribadi. Dari data transaksi, beri maksimal 3 saran hemat yang konkret dan bisa langsung dilakukan.
Fokus ke 7 hari terakhir, sebutkan perkiraan penghematannya dalam Rupiah per bulan, dan kaitkan dengan budget atau target tabungan kalau ada.
Bahasa Indonesia santai dan singkat. Tanpa markdown, tanpa pembuka atau penutup."""

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
    }}, "pertanyaan": {"type": "boolean"}},
    "required": ["transaksi", "pertanyaan"],
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


def hapus(idx):
    """Hapus transaksi pada posisi idx (0-based), kembalikan yang dihapus."""
    with open(DATA) as f:
        lines = f.read().split()
    gone = [json.loads(fernet().decrypt(lines[i].encode())) for i in idx]
    with open(DATA, "w") as f:
        f.writelines(line + "\n" for i, line in enumerate(lines) if i not in idx)
    return gone


def undo():
    """Hapus semua transaksi dari pesan terakhir."""
    rows = load()
    if not rows:
        return []
    k = len(rows)
    while k and rows[k - 1]["mid"] == rows[-1]["mid"]:
        k -= 1
    return hapus(range(k, len(rows)))


def load_setting():
    s = {}
    if os.path.exists(SETTING):
        with open(SETTING) as f:
            s = json.loads(fernet().decrypt(f.read().strip().encode()))
    s.setdefault("budget", {})
    return s


def save_setting(s):
    with open(SETTING, "w") as f:
        f.write(fernet().encrypt(json.dumps(s).encode()).decode() + "\n")


def push(msg):
    branch = os.environ.get("GITHUB_REF_NAME", "main")
    subprocess.run(["git", "add", *[f for f in (DATA, SETTING) if os.path.exists(f)]])
    subprocess.run(["git", "commit", "-qm", msg], stdout=subprocess.DEVNULL)  # gagal kalau tidak ada perubahan, tidak apa-apa
    for cmd in (["git", "pull", "-q", "--rebase", "origin", branch], ["git", "push", "-q", "origin", "HEAD"]):
        if subprocess.run(cmd).returncode:
            print("git gagal:", " ".join(cmd))  # commit tetap ada di lokal, ikut ter-push di push berikutnya
            return


def post(url, body, headers=None):
    req = urllib.request.Request(url, json.dumps(body).encode(), {"Content-Type": "application/json", **(headers or {})})
    with urllib.request.urlopen(req, timeout=120) as r:
        return json.load(r)


def tg(method, **params):
    return post(f"https://api.telegram.org/bot{TOKEN}/{method}", params)["result"]


def send(text, chat_id=None):
    for i in range(0, len(text), 4096):  # batas panjang satu pesan Telegram
        tg("sendMessage", chat_id=chat_id or CHAT_ID, text=text[i:i + 4096])


def send_file(name, data):
    b = "batas-catatpengeluaran"
    body = (f'--{b}\r\nContent-Disposition: form-data; name="chat_id"\r\n\r\n{CHAT_ID}\r\n'
            f'--{b}\r\nContent-Disposition: form-data; name="document"; filename="{name}"\r\n'
            f"Content-Type: text/csv\r\n\r\n").encode() + data + f"\r\n--{b}--\r\n".encode()
    req = urllib.request.Request(f"https://api.telegram.org/bot{TOKEN}/sendDocument", body,
                                 {"Content-Type": f"multipart/form-data; boundary={b}"})
    urllib.request.urlopen(req, timeout=60).close()


def image_block(file_id, mime_type):
    path = tg("getFile", file_id=file_id)["file_path"]
    with urllib.request.urlopen(f"https://api.telegram.org/file/bot{TOKEN}/{path}", timeout=60) as r:
        return {"type": "image", "data": base64.b64encode(r.read()).decode(), "mime_type": mime_type}


def gemini(system, content, schema=None):
    body = {"system_instruction": system, "input": content, "store": False,
            "generation_config": {"thinking_level": "low"}}  # default "medium" bikin balasan ~1-2 menit
    if schema:
        body["response_format"] = {"type": "text", "mime_type": "application/json", "schema": schema}
    for i, model in enumerate((MODEL, MODEL, CADANGAN)):  # coba ulang sekali, lalu pindah ke model cadangan
        try:
            r = post(GEMINI_URL, {**body, "model": model}, {"x-goog-api-key": GEMINI_KEY})
            break
        except urllib.error.HTTPError as e:
            if e.code not in (429, 500, 503) or i == 2:
                raise
            time.sleep(2)
    if r.get("status") != "completed":
        raise RuntimeError(f"status={r.get('status')} {r.get('errors')}")
    return "".join(c.get("text", "") for s in r.get("steps", []) if s.get("type") == "model_output"
                   for c in s.get("content", []))


def extract(content):
    """(transaksi yang valid, apakah pesannya pertanyaan)."""
    hasil = json.loads(gemini(PROMPT, content, SCHEMA))
    items = [t for t in hasil["transaksi"]  # jawaban AI tetap dicek sebelum disimpan
             if t.get("jenis") in ("masuk", "keluar") and t.get("kategori") in KATEGORI
             and type(t.get("jumlah")) is int and t["jumlah"] > 0]
    return items, hasil.get("pertanyaan") is True


def konteks(now, rows):
    s = load_setting()
    data = "\n".join(f"{r['t'][:16]};{r['jenis']};{r['jumlah']};{r['kategori']};{r['keterangan']}" for r in rows)
    return (f"Sekarang {now:%Y-%m-%d %H:%M} WIB.\nBudget bulanan: {s['budget']}\nTarget tabungan: {s.get('target')}\n"
            f"Transaksi (waktu;jenis;jumlah;kategori;keterangan):\n{data}")


def tips(now=None):
    now = now or datetime.now(TZ)
    rows = [r for r in load() if datetime.fromisoformat(r["t"]) >= now - timedelta(days=28)]
    if not rows:
        return "Belum ada transaksi 4 minggu terakhir untuk dianalisis."
    return gemini(TIPS_PROMPT, konteks(now, rows))


def jawab(pertanyaan, now=None):
    now = now or datetime.now(TZ)
    hitungan = "\n\n".join(ringkasan(p, now) for p in JUDUL)  # total dihitung kode, bukan AI
    data = konteks(now, load()[-1000:])  # ponytail: 1000 transaksi terakhir, cukup untuk beberapa bulan
    return gemini(TANYA_PROMPT, f"{data}\n\nRingkasan yang sudah dihitung:\n{hitungan}\n\nPertanyaan: {pertanyaan}")


def parse_rp(s):
    """'1,5jt' -> 1500000, '500rb'/'500k' -> 500000, 'Rp1.500.000' -> 1500000."""
    s = re.sub(r",00$", "", s.lower().replace(" ", "").removeprefix("rp"))
    for akhiran, kali in (("juta", 10**6), ("jt", 10**6), ("ribu", 1000), ("rb", 1000), ("k", 1000)):
        if s.endswith(akhiran):
            angka = s[:-len(akhiran)]
            if re.fullmatch(r"\d{1,3}(\.\d{3})+", angka):  # "1.500rb" = 1.500 ribu, bukan 1,5 ribu
                angka = angka.replace(".", "")
            n = round(float(angka.replace(",", ".")) * kali)
            break
    else:
        n = int(s.replace(".", "").replace(",", ""))
    if n < 0:
        raise ValueError(s)
    return n


def parse_bulan(s):
    """'2027-06', '06/2027', '6-2027' -> '2027-06'."""
    a, b = re.split(r"[-/]", s)
    y, m = (int(a), int(b)) if len(a) == 4 else (int(b), int(a))
    if y < 100:  # "06/27" = Juni 2027
        y += 2000
    if not 1 <= m <= 12:
        raise ValueError(s)
    return f"{y:04d}-{m:02d}"


def cari_kategori(s):
    s = s.lower().strip()
    return next((k for k in KATEGORI if s and s in k.lower()), None)


def rp(n):
    return "Rp " + f"{n:,}".replace(",", ".")


def baris(r):
    return f"{'➕' if r['jenis'] == 'masuk' else '➖'} {rp(r['jumlah'])} · {r['kategori']} · {r['keterangan']}"


def total(rows, jenis):
    return sum(r["jumlah"] for r in rows if r["jenis"] == jenis and r["kategori"] != "Tabungan")


def tabungan(rows):
    """Saldo tabungan bersih: disetor dikurangi diambil."""
    return sum(r["jumlah"] if r["jenis"] == "keluar" else -r["jumlah"] for r in rows if r["kategori"] == "Tabungan")


def bulan_ini(now):
    """(transaksi sebelum bulan ini, transaksi bulan ini sampai `now`)."""
    awal = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    rows = [(datetime.fromisoformat(r["t"]), r) for r in load()]
    return [r for t, r in rows if t < awal], [r for t, r in rows if awal <= t <= now]


def status_budget(now, hanya=None):
    budget = load_setting()["budget"]
    terpakai = Counter()
    for r in bulan_ini(now)[1]:
        if r["jenis"] == "keluar":
            terpakai[r["kategori"]] += r["jumlah"]
    out = []
    for k, batas in budget.items():
        if hanya is None or k in hanya:
            pct = terpakai[k] * 100 // batas
            tanda = "🚨" if pct >= 100 else "⚠️" if pct >= 80 else "✅"
            out.append(f"{tanda} Budget {k}: {rp(terpakai[k])} / {rp(batas)} ({pct}%)")
    return out


def rencana(now):
    """(baris progres target tabungan, baris jatah belanja harian atau None)."""
    # ponytail: dihitung per bulan kalender; sisa uang bulan lalu tidak ikut dihitung
    lalu, bulan = bulan_ini(now)
    ditabung = tabungan(bulan)
    out, wajib = [], 0
    target = load_setting().get("target")
    if target:
        y, m = map(int, target["bulan"].split("-"))
        sisa_bulan = max(1, y * 12 + m - (now.year * 12 + now.month) + 1)
        perlu = -(-max(0, target["jumlah"] - tabungan(lalu)) // sisa_bulan)  # dibulatkan ke atas
        wajib = max(0, min(perlu, target["jumlah"] - tabungan(lalu)) - ditabung)  # jangan lebih dari kekurangan target
        semua = tabungan(lalu) + ditabung
        out = [f"🎯 Tabungan {rp(semua)} dari target {rp(target['jumlah'])} "
               f"({max(0, semua) * 100 // target['jumlah']}%), tenggat {m:02d}/{y}",
               f"Bulan ini perlu nabung {rp(perlu)}, sudah {rp(ditabung)}"]
    masuk = total(bulan, "masuk")
    if not masuk:
        return out, None
    sisa = masuk - total(bulan, "keluar") - ditabung - wajib
    hari = calendar.monthrange(now.year, now.month)[1] - now.day + 1
    if sisa < 0:
        return out, f"🚨 Bulan ini sudah lewat {rp(-sisa)} dari rencana"
    return out, f"💡 Jatah belanja {rp(sisa // hari)}/hari sampai akhir bulan"


def ringkasan(periode, now=None):
    now = now or datetime.now(TZ)
    awal = now.replace(hour=0, minute=0, second=0, microsecond=0)
    if periode == "minggu":
        awal -= timedelta(days=now.weekday())  # mulai Senin
    elif periode == "bulan":
        awal = awal.replace(day=1)
    rows = [r for r in load() if awal <= datetime.fromisoformat(r["t"]) <= now]
    masuk, ditabung = total(rows, "masuk"), tabungan(rows)
    kategori = Counter()
    for r in rows:
        if r["jenis"] == "keluar" and r["kategori"] != "Tabungan":
            kategori[r["kategori"]] += r["jumlah"]
    keluar = sum(kategori.values())
    rentang = f"{awal:%d/%m/%Y}" if periode == "hari" else f"{awal:%d/%m} – {now:%d/%m/%Y}"
    out = [f"📊 Ringkasan {JUDUL[periode]} ({rentang})", f"Pemasukan: {rp(masuk)}", f"Pengeluaran: {rp(keluar)}"]
    if ditabung:
        out.append(f"Ditabung: {rp(ditabung)}")
    out.append(f"Selisih: {rp(masuk - keluar - ditabung)}")
    if kategori:
        out += ["", "Pengeluaran per kategori:"] + [f"• {k}: {rp(v)}" for k, v in kategori.most_common()]
    target, jatah = rencana(now)
    extra = status_budget(now) + target + ([jatah] if jatah else [])
    if extra:
        out += [""] + extra
    return "\n".join(out)


def perintah(cmd, args):
    now = datetime.now(TZ)
    if cmd in ("/start", "/bantuan"):
        return BANTUAN
    if cmd[1:] in JUDUL:
        return ringkasan(cmd[1:])
    if cmd == "/batal":
        gone = undo()
        if gone:
            push("batal")
        return "🗑️ Dihapus:\n" + "\n".join(map(baris, gone)) if gone else "Belum ada catatan."
    if cmd == "/riwayat":
        rows = list(enumerate(load(), 1))[-15:]
        if not rows:
            return "Belum ada catatan."
        return "\n".join(f"#{i} {r['t'][8:10]}/{r['t'][5:7]} {baris(r)}" for i, r in rows) + "\n\nHapus: /hapus <nomor> [nomor lain]"
    if cmd == "/hapus":
        n, nomor = len(load()), [a.strip("#,") for a in args]
        if not nomor or not all(a.isdigit() and 1 <= int(a) <= n for a in nomor):
            return "Nomor tidak ada. Lihat nomornya di /riwayat, lalu kirim misalnya /hapus 12 15"
        gone = hapus({int(a) - 1 for a in nomor})  # sekaligus, karena nomor bergeser setelah dihapus
        push("hapus")
        return "🗑️ Dihapus:\n" + "\n".join(map(baris, gone)) + "\n\nNomor lain sudah bergeser, cek /riwayat lagi."
    if cmd == "/budget":
        if args:
            try:
                k, jumlah = cari_kategori(" ".join(args[:-1])), parse_rp(args[-1])
            except ValueError:
                k = None
            if not k:
                return "Contoh: /budget makan 1,5jt  (isi 0 untuk menghapus)\nKategori: " + ", ".join(KATEGORI)
            s = load_setting()
            if jumlah:
                s["budget"][k] = jumlah
            else:
                s["budget"].pop(k, None)
            save_setting(s)
            push("budget")
        return "\n".join(status_budget(now)) or "Belum ada budget. Contoh: /budget makan 1,5jt"
    if cmd == "/target":
        if args:
            try:
                jumlah = parse_rp(args[0])
                bulan = parse_bulan(args[1]) if jumlah else None
            except (ValueError, IndexError):
                return "Contoh: /target 10jt 2027-06  (tenggat tahun-bulan; /target 0 untuk menghapus)"
            if bulan and bulan < f"{now:%Y-%m}":
                return f"Tenggat {bulan} sudah lewat. Contoh: /target 10jt 2027-06"
            s = load_setting()
            if jumlah:
                s["target"] = {"jumlah": jumlah, "bulan": bulan}
            else:
                s.pop("target", None)
            save_setting(s)
            push("target")
        target, jatah = rencana(now)
        return "\n".join(target + ([jatah] if jatah else [])) or "Belum ada target. Contoh: /target 10jt 2027-06"
    if cmd == "/tips":
        return "💬 " + tips(now)
    if cmd == "/ekspor":
        buf = io.StringIO()
        w = csv.writer(buf)
        w.writerow(["waktu", "jenis", "jumlah", "kategori", "keterangan"])
        w.writerows([r["t"], r["jenis"], r["jumlah"], r["kategori"], r["keterangan"]] for r in load())
        send_file(f"catatan-{now:%Y%m%d}.csv", buf.getvalue().encode())
        return "📎 Semua catatan sudah dikirim sebagai file CSV (bisa dibuka di Excel/Google Sheets)."
    return None


def handle(msg):
    if str(msg["chat"]["id"]) != CHAT_ID:
        return f"Chat ID kamu: {msg['chat']['id']}\nSimpan sebagai secret TELEGRAM_CHAT_ID lalu jalankan ulang workflow bot."
    try:
        tg("sendChatAction", chat_id=CHAT_ID, action="typing")
    except Exception:
        pass  # cuma indikator "sedang mengetik"
    text = msg.get("text") or msg.get("caption") or ""
    if text.startswith("/"):
        parts = text.split()
        reply = perintah(parts[0].split("@")[0].lower(), parts[1:])
        if reply:
            return reply

    content = []
    photo, doc = msg.get("photo"), msg.get("document") or {}
    if photo:
        content.append(image_block(photo[-1]["file_id"], "image/jpeg"))
    elif doc.get("mime_type", "").startswith("image/"):
        if doc["mime_type"] not in GAMBAR or doc.get("file_size", 0) > 14_000_000:
            return "Format atau ukuran gambar tidak didukung. Kirim sebagai foto biasa (bukan file) ya."
        content.append(image_block(doc["file_id"], doc["mime_type"]))
    if text:
        content.append({"type": "text", "text": text})
    if not content:
        return "Kirim teks atau foto ya. /bantuan untuk contoh."

    items, tanya = extract(content)
    if not items:
        if tanya and text:
            return "💬 " + jawab(text)
        return "Tidak ada transaksi yang terbaca. Coba tulis seperti: kopi 18rb"
    t = datetime.fromtimestamp(msg["date"], TZ).isoformat(timespec="seconds")
    rows = [{"t": t, "mid": msg["message_id"], **i} for i in items]
    save(rows)
    push("catat")
    now = datetime.now(TZ)
    extra = status_budget(now, {r["kategori"] for r in rows if r["jenis"] == "keluar"})
    jatah = rencana(now)[1]
    if jatah:
        extra.append(jatah)
    return ("✅ Tercatat:\n" + "\n".join(map(baris, rows)) + ("\n\n" + "\n".join(extra) if extra else "")
            + "\n\nSalah baca? /batal")


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
                detail = (e.read()[:300].decode(errors="replace") if isinstance(e, urllib.error.HTTPError)
                          else str(e)[:300])
                print("gagal memproses:", type(e).__name__, detail)
                reply = ("⏳ Kuota AI gratis sedang habis, coba lagi nanti." if getattr(e, "code", None) == 429
                         else f"⚠️ Gagal memproses pesan ini, coba kirim ulang.\n({type(e).__name__}: {detail})")
            try:
                send(reply, msg["chat"]["id"])
            except Exception as e:
                print("gagal membalas:", e)
    try:
        if offset:
            tg("getUpdates", offset=offset, timeout=0)  # konfirmasi pesan terakhir agar tidak diproses dua kali
    except Exception as e:
        print("konfirmasi gagal:", e)
    last = subprocess.run(["git", "log", "-1", "--format=%ct"], capture_output=True, text=True).stdout.strip()
    if time.time() - int(last or 0) > 30 * 86400:  # GitHub mematikan workflow repo yang 60 hari tanpa commit
        subprocess.run(["git", "commit", "--allow-empty", "-qm", "keepalive"])
    push("sisa")  # dorong commit yang tadi gagal ter-push sebelum runner dibuang


if __name__ == "__main__":
    if len(os.environ.get("DATA_KEY", "")) < 20:
        sys.exit("Secret DATA_KEY belum diisi atau kurang dari 20 karakter")
    load(), load_setting()  # DATA_KEY salah/berubah -> berhenti sebelum menulis data dengan kunci lain
    if sys.argv[1:] == ["ringkasan"]:
        send(ringkasan("hari"))
        if datetime.now(TZ).weekday() == 6:
            send(ringkasan("minggu"))
            try:
                send("💬 Tips hemat minggu ini:\n" + tips())
            except Exception as e:
                print("tips gagal:", e)
    else:
        run()

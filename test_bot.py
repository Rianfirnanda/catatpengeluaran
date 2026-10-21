"""Cek cepat tanpa internet: python test_bot.py"""
import json
import os
import tempfile
import time
from datetime import datetime

os.environ["DATA_KEY"] = "tes"
import bot

tmp = tempfile.mkdtemp()
bot.DATA, bot.SETTING = os.path.join(tmp, "data.enc"), os.path.join(tmp, "setting.enc")
bot.CHAT_ID = "42"
bot.push = lambda msg: None
bot.tg = lambda *a, **k: None


def row(t, mid, jenis, jumlah, kategori):
    return {"t": t, "mid": mid, "jenis": jenis, "jumlah": jumlah, "kategori": kategori, "keterangan": "x"}


# parser nominal & bulan
assert [bot.parse_rp(s) for s in ("1,5jt", "1.5jt", "500rb", "1.500rb", "18k", "Rp1.500.000,00", "2 juta", "0")] == \
       [1_500_000, 1_500_000, 500_000, 1_500_000, 18_000, 1_500_000, 2_000_000, 0]
for bad in ("-5", "abc"):
    try:
        bot.parse_rp(bad)
        raise AssertionError(bad)
    except ValueError:
        pass
assert bot.parse_bulan("2027-06") == bot.parse_bulan("06/2027") == bot.parse_bulan("6/27") == "2027-06"
assert bot.cari_kategori("makan") == "Makan & Minum" and bot.cari_kategori("") is None

bot.save([
    row("2026-09-15T09:00:00+07:00", 1, "keluar", 1_000_000, "Tabungan"),  # tabungan bulan lalu
    row("2026-10-01T09:00:00+07:00", 2, "masuk", 5_000_000, "Gaji"),
    row("2026-10-02T09:00:00+07:00", 3, "keluar", 500_000, "Tabungan"),
    row("2026-10-20T12:00:00+07:00", 4, "keluar", 30_000, "Transportasi"),
    row("2026-10-21T08:00:00+07:00", 5, "keluar", 25_000, "Makan & Minum"),
    row("2026-10-21T08:00:00+07:00", 5, "keluar", 15_000, "Makan & Minum"),
])
assert b"Gaji" not in open(bot.DATA, "rb").read()  # tersimpan terenkripsi

now = datetime(2026, 10, 21, 21, 0, tzinfo=bot.TZ)  # Rabu, 11 hari tersisa di Oktober
hari = bot.ringkasan("hari", now)
assert "Pengeluaran: Rp 40.000" in hari and "Transportasi" not in hari, hari
minggu = bot.ringkasan("minggu", now)  # Senin 19/10 s.d. sekarang
assert "Pemasukan: Rp 0" in minggu and "Pengeluaran: Rp 70.000" in minggu, minggu
bulan = bot.ringkasan("bulan", now)  # tabungan tidak dihitung sebagai pengeluaran
assert "Pengeluaran: Rp 70.000" in bulan and "Ditabung: Rp 500.000" in bulan, bulan
assert "Selisih: Rp 4.430.000" in bulan, bulan

# budget: 40rb dari 50rb = 80%
s = bot.load_setting()
s["budget"]["Makan & Minum"] = 50_000
bot.save_setting(s)
assert bot.status_budget(now) == ["⚠️ Budget Makan & Minum: Rp 40.000 / Rp 50.000 (80%)"]
assert b"Makan" not in open(bot.SETTING, "rb").read()

# tanpa target: (5jt - 70rb - 500rb) / 11 hari
assert bot.rencana(now) == ([], f"💡 Jatah belanja {bot.rp(4_430_000 // 11)}/hari sampai akhir bulan")
# target 4jt Des 2026: sisa (4jt - 1jt) / 3 bulan = 1jt/bulan, sudah 500rb -> 500rb lagi wajib bulan ini
s["target"] = {"jumlah": 4_000_000, "bulan": "2026-12"}
bot.save_setting(s)
target, jatah = bot.rencana(now)
assert target[0].startswith("🎯 Tabungan Rp 1.500.000 dari target Rp 4.000.000 (37%)"), target
assert target[1] == "Bulan ini perlu nabung Rp 1.000.000, sudah Rp 500.000", target
assert jatah == f"💡 Jatah belanja {bot.rp(3_930_000 // 11)}/hari sampai akhir bulan", jatah
# target sudah terlampaui lalu ambil tabungan: tidak perlu menyisihkan pengganti
s["target"] = {"jumlah": 500_000, "bulan": "2026-12"}
bot.save_setting(s)
bot.save([row("2026-10-21T10:00:00+07:00", 99, "masuk", 700_000, "Tabungan")])  # bersih bulan ini -200rb
assert bot.rencana(now)[1] == f"💡 Jatah belanja {bot.rp(5_130_000 // 11)}/hari sampai akhir bulan", bot.rencana(now)
bot.undo()
s["target"] = {"jumlah": 4_000_000, "bulan": "2026-12"}
bot.save_setting(s)

# hapus & batal
assert [r["mid"] for r in bot.hapus([3])] == [4] and len(bot.load()) == 5
bot.save([row("2026-10-21T09:00:00+07:00", 6, "keluar", 1, "Lainnya"), row("2026-10-21T09:00:00+07:00", 7, "keluar", 2, "Lainnya")])
assert "Rp 1 ·" in bot.perintah("/hapus", ["6", "7"]) and len(bot.load()) == 5  # dua nomor sekaligus, sebelum bergeser
assert [r["mid"] for r in bot.load()][-1] == 5
assert len(bot.undo()) == 2 and len(bot.load()) == 3  # /batal hapus semua item dari pesan terakhir

# jawaban Gemini diparse dan divalidasi (nominal ngawur dibuang)
answer = {"transaksi": [
    {"jenis": "keluar", "jumlah": 18_000, "kategori": "Makan & Minum", "keterangan": "kopi"},
    {"jenis": "keluar", "jumlah": -5, "kategori": "Belanja", "keterangan": "x"},
    {"jenis": "pinjam", "jumlah": 5, "kategori": "Belanja", "keterangan": "x"},
    {"jenis": "keluar", "jumlah": 5.5, "kategori": "Belanja", "keterangan": "x"},
], "pertanyaan": False}
sent = []


def gemini_reply(text):
    return {"status": "completed", "steps": [
        {"type": "user_input"}, {"type": "thought", "signature": "x"},
        {"type": "model_output", "content": [{"type": "text", "text": text}]}]}


bot.post = lambda url, body, headers=None: sent.append(body) or gemini_reply(json.dumps(answer))
assert bot.extract([{"type": "text", "text": "kopi 18rb"}]) == (answer["transaksi"][:1], False)
assert sent[-1]["generation_config"] == {"thinking_level": "low"}  # supaya balasan cepat

# pertanyaan dijawab AI dengan total yang sudah dihitung kode, bukan dicatat sebagai transaksi
replies = iter([gemini_reply(json.dumps({"transaksi": [], "pertanyaan": True})), gemini_reply("Total Rp 40.000")])
bot.post = lambda url, body, headers=None: sent.append(body) or next(replies)
q = {"chat": {"id": 42}, "message_id": 8, "date": int(time.time()), "text": "berapa total pengeluaran hari ini?"}
assert bot.handle(q) == "💬 Total Rp 40.000" and len(bot.load()) == 3
assert "Ringkasan yang sudah dihitung" in sent[-1]["input"] and sent[-1]["input"].endswith(q["text"])
bot.post = lambda url, body, headers=None: sent.append(body) or gemini_reply(json.dumps(answer))

msg = {"chat": {"id": 42}, "message_id": 9, "date": int(time.time()), "text": "kopi 18rb"}
reply = bot.handle(msg)
assert "➖ Rp 18.000 · Makan & Minum · kopi" in reply and "Budget Makan & Minum" in reply, reply
assert len(bot.load()) == 4
assert bot.handle({**msg, "text": "/budget transport 300rb"}).count("Budget") == 2
assert "Contoh" in bot.handle({**msg, "text": "/budget 300rb"})
assert "Contoh" in bot.handle({**msg, "text": "/target 10jt"})
assert "Nomor tidak ada" in bot.handle({**msg, "text": "/hapus 99"})
assert "Chat ID kamu: 7" in bot.handle({**msg, "chat": {"id": 7}})  # orang lain tidak bisa mencatat
assert len(bot.load()) == 4
print("ok")

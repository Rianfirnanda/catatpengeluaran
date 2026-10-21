"""Cek cepat tanpa internet: python test_bot.py"""
import os
import tempfile
from datetime import datetime

os.environ["DATA_KEY"] = "tes"
import bot

bot.DATA = os.path.join(tempfile.mkdtemp(), "data.enc")
bot.CHAT_ID = "42"
bot.push = lambda msg: None
bot.tg = lambda *a, **k: None


def row(t, mid, jenis, jumlah, kategori):
    return {"t": t, "mid": mid, "jenis": jenis, "jumlah": jumlah, "kategori": kategori, "keterangan": "x"}


bot.save([
    row("2026-10-01T09:00:00+07:00", 1, "masuk", 5_000_000, "Gaji"),
    row("2026-10-20T12:00:00+07:00", 2, "keluar", 30_000, "Transportasi"),
    row("2026-10-21T08:00:00+07:00", 3, "keluar", 25_000, "Makan & Minum"),
    row("2026-10-21T08:00:00+07:00", 3, "keluar", 15_000, "Makan & Minum"),
])
assert b"Gaji" not in open(bot.DATA, "rb").read()  # tersimpan terenkripsi

now = datetime(2026, 10, 21, 21, 0, tzinfo=bot.TZ)  # Rabu
hari = bot.ringkasan("hari", now)
assert "Pengeluaran: Rp 40.000" in hari and "Transportasi" not in hari, hari
minggu = bot.ringkasan("minggu", now)  # Senin 19/10 s.d. sekarang
assert "Pemasukan: Rp 0" in minggu and "Pengeluaran: Rp 70.000" in minggu, minggu
bulan = bot.ringkasan("bulan", now)
assert "Selisih: Rp 4.930.000" in bulan and "• Makan & Minum: Rp 40.000" in bulan, bulan

assert len(bot.undo()) == 2 and len(bot.load()) == 2  # /batal hapus semua item dari pesan terakhir

bot.extract = lambda content: [{"jenis": "keluar", "jumlah": 18_000, "kategori": "Makan & Minum", "keterangan": "kopi"}]
msg = {"chat": {"id": 42}, "message_id": 9, "date": 1792569600, "text": "kopi 18rb"}
assert "Rp 18.000" in bot.handle(msg) and len(bot.load()) == 3
assert "Chat ID kamu: 7" in bot.handle({**msg, "chat": {"id": 7}})  # orang lain tidak bisa mencatat
assert len(bot.load()) == 3
print("ok")

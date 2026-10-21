# catatpengeluaran

Bot Telegram untuk mencatat pemasukan dan pengeluaran sekaligus membantu menabung. Bot berjalan 24/7 di GitHub Actions dan memakai AI gratis (Google Gemini).

**Mencatat**
- Teks bebas: `kopi 18rb`, `gajian 5jt`, `nabung 500rb`, `bensin 30k, parkir 5rb`
- Foto struk atau foto catatan tulisan tangan
- `/riwayat` untuk melihat catatan terakhir, `/hapus 12 15` untuk menghapus catatan tertentu, `/batal` untuk menghapus isi pesan terakhir

**Menabung**
- `/budget makan 1,5jt` mengatur budget bulanan per kategori. Setiap kali kamu mencatat pengeluaran, bot membalas dengan sisa budget kategori itu. Tanda ⚠️ muncul di 80%, 🚨 di 100%.
- `/target 10jt 2027-06` mengatur target tabungan. Bot menghitung berapa yang perlu ditabung tiap bulan dan berapa **jatah belanja per hari** sampai akhir bulan.
- Uang yang kamu tabung (`nabung 500rb`) masuk kategori *Tabungan* dan tidak dihitung sebagai pengeluaran.
- `/tips` meminta saran hemat dari AI berdasarkan transaksi 4 minggu terakhir.

**Ringkasan**
- Setiap hari pukul 21:00 WIB bot mengirim ringkasan harian. Setiap Minggu ada tambahan ringkasan mingguan dan tips hemat.
- `/hari`, `/minggu`, `/bulan` untuk melihat ringkasan kapan saja.
- `/ekspor` mengirim semua catatan sebagai file CSV yang bisa dibuka di Excel atau Google Sheets.

Data disimpan di `data.enc` dan `setting.enc` dalam keadaan terenkripsi, jadi tetap aman walaupun repo ini publik.

## Cara pasang

1. **Buat bot Telegram.** Chat [@BotFather](https://t.me/BotFather), kirim `/newbot`, lalu simpan token yang diberikan.
2. **Buat API key Gemini (gratis)** di [aistudio.google.com/apikey](https://aistudio.google.com/apikey). Tidak perlu kartu kredit.
3. **Ubah repo ini menjadi Public** lewat Settings → General → Danger Zone → Change visibility. Di repo publik, menit GitHub Actions gratis tanpa batas. Di repo private, kuota gratisnya cuma 2.000 menit per bulan, sedangkan bot ini butuh sekitar 43.000.
4. **Isi Secrets** lewat Settings → Secrets and variables → Actions → New repository secret:
   | Nama | Isi |
   |---|---|
   | `TELEGRAM_TOKEN` | token dari BotFather |
   | `GEMINI_API_KEY` | API key dari AI Studio |
   | `DATA_KEY` | kata sandi panjang buatan sendiri, minimal 20 karakter acak. **Simpan baik-baik. Kalau hilang, data tidak bisa dibuka lagi.** |
5. **Nyalakan bot** lewat tab Actions → workflow **bot** → Run workflow.
6. **Kirim `/start` ke bot kamu.** Bot akan membalas dengan *Chat ID*. Simpan angka itu sebagai secret `TELEGRAM_CHAT_ID`. Setelah itu buka tab Actions, Cancel run **bot** yang sedang berjalan, lalu Run workflow lagi.

Selesai. Bot hanya melayani Chat ID kamu dan mengabaikan orang lain.

## Cara kerja

- Satu run GitHub Actions maksimal 6 jam. Karena itu bot berhenti sendiri setiap ~5,5 jam lalu menyalakan run berikutnya. Pesan yang masuk saat pergantian run tidak hilang karena Telegram menyimpannya.
- Setiap perubahan data dienkripsi lalu di-commit oleh bot.
- Jatah belanja harian dihitung per bulan kalender: pemasukan bulan ini dikurangi pengeluaran, uang yang sudah ditabung, dan sisa target tabungan bulan ini, lalu dibagi sisa hari. Sisa uang dari bulan lalu belum ikut dihitung.

## Perlu diketahui

- **Privasi Gemini gratis:** di free tier, Google boleh memakai isi permintaan untuk meningkatkan produknya. Artinya foto struk, teks catatan, dan data transaksi yang dikirim untuk `/tips` bisa dilihat Google. Data yang tersimpan di repo tetap terenkripsi.
- **Kuota Gemini gratis terbatas.** Batas per menit dan per hari bisa dilihat di [AI Studio](https://aistudio.google.com/rate-limit). Kalau kuota habis, bot akan memberi tahu. Kamu bisa menunggu, atau ganti `MODEL` di `bot.py` menjadi `gemini-3.5-flash-lite`.
- **Aturan GitHub:** menjalankan bot nonstop di GitHub Actions termasuk wilayah abu-abu, dan GitHub bisa saja menghentikannya. Kalau itu terjadi, `bot.py` tetap bisa dijalankan di server mana pun dengan `python bot.py`.
- **Log publik:** log Actions di repo publik bisa dilihat orang lain. Bot sengaja tidak pernah menulis isi pesan atau nominal ke log.
- **Ringkasan bisa telat:** jadwal cron GitHub kadang telat 5–30 menit.
- **Workflow bisa dimatikan GitHub:** kalau selama 60 hari tidak ada aktivitas di repo (tidak ada transaksi baru), GitHub mematikan workflow terjadwal. Aktifkan lagi lewat tab Actions.

## Tes lokal

```bash
pip install -r requirements.txt
python test_bot.py
```

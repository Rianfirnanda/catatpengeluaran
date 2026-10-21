# catatpengeluaran

Bot Telegram untuk mencatat pemasukan dan pengeluaran. Bot ini berjalan 24/7 di GitHub Actions.

- Teks bebas: `kopi 18rb`, `gajian 5jt`, `bensin 30k, parkir 5rb`
- Foto struk atau foto catatan tulisan tangan (dibaca oleh Claude)
- Ringkasan otomatis setiap hari pukul 21:00 WIB, ditambah ringkasan mingguan setiap Minggu
- Perintah: `/hari` `/minggu` `/bulan` `/batal` `/bantuan`

Data disimpan di `data.enc` dalam keadaan terenkripsi, jadi tetap aman walaupun repo ini publik.

## Cara pasang

1. **Buat bot Telegram.** Chat [@BotFather](https://t.me/BotFather), kirim `/newbot`, lalu simpan token yang diberikan.
2. **Buat API key Claude** di [console.anthropic.com](https://console.anthropic.com) dan isi saldonya.
3. **Ubah repo ini menjadi Public** lewat Settings → General → Danger Zone → Change visibility. Di repo publik, menit GitHub Actions gratis tanpa batas. Di repo private, kuota gratisnya cuma 2.000 menit per bulan, sedangkan bot ini butuh sekitar 43.000.
4. **Isi Secrets** lewat Settings → Secrets and variables → Actions → New repository secret:
   | Nama | Isi |
   |---|---|
   | `TELEGRAM_TOKEN` | token dari BotFather |
   | `ANTHROPIC_API_KEY` | API key Claude |
   | `DATA_KEY` | kata sandi panjang buatan sendiri, minimal 20 karakter acak. **Simpan baik-baik. Kalau hilang, data tidak bisa dibuka lagi.** |
5. **Nyalakan bot** lewat tab Actions → workflow **bot** → Run workflow.
6. **Kirim `/start` ke bot kamu.** Bot akan membalas dengan *Chat ID*. Simpan angka itu sebagai secret `TELEGRAM_CHAT_ID`. Setelah itu buka tab Actions, Cancel run **bot** yang sedang berjalan, lalu Run workflow lagi.

Selesai. Bot hanya melayani Chat ID kamu dan mengabaikan orang lain.

## Cara kerja

- Satu run GitHub Actions maksimal 6 jam. Karena itu bot berhenti sendiri setiap ~5,5 jam lalu menyalakan run berikutnya. Pesan yang masuk saat pergantian run tidak hilang karena Telegram menyimpannya.
- Setiap transaksi disimpan sebagai satu baris terenkripsi di `data.enc`, lalu di-commit oleh bot.
- Membaca foto memakai model `claude-opus-5-5` dengan effort `low`. Biayanya sekitar Rp100–300 per pesan. Untuk biaya yang jauh lebih murah, ganti `MODEL` di `bot.py` menjadi `claude-haiku-5-5`.

## Perlu diketahui

- Menjalankan bot nonstop di GitHub Actions termasuk wilayah abu-abu aturan pakai GitHub, dan GitHub bisa saja menghentikannya. Kalau itu terjadi, `bot.py` tetap bisa dijalankan di server mana pun dengan `python bot.py`.
- Log Actions di repo publik bisa dilihat orang lain. Bot sengaja tidak pernah menulis isi pesan atau nominal ke log.
- Jadwal cron GitHub kadang telat 5–30 menit, jadi ringkasan harian bisa datang sedikit setelah jam 21:00.

## Tes lokal

```bash
pip install -r requirements.txt
python test_bot.py
```

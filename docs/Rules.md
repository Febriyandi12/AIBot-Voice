# ATURAN OPERASIONAL AI ASSISTANT DEVELOPER

Sebagai AI Developer Assistant, Anda wajib mematuhi aturan berikut sebelum merespons:

## 1. Analisis & Eksekusi
* **Pahami Konteks:** Analisis memori percakapan, `changelog.md`, dan file `fitur.md` terlebih dahulu. Jika sudah paham, langsung berikan solusi tanpa basa-basi. Jika tidak paham, bertanyalah.
* **Laporkan Kendala:** Jika menemukan masalah pada kode atau logika, laporkan terlebih dahulu. Jangan langsung mengeksekusi perbaikan tanpa izin.
* **Serah Terima Model (Round Robin):** Karena menggunakan sistem Round Robin, selalu periksa riwayat memori (konteks sebelumnya) dan entri terbaru `changelog.md` untuk mengetahui status terakhir pekerjaan sebelum melanjutkan. Simpan semua ringkasan progres (step kecil) ke dalam memori.

## 2. Aturan Modifikasi Kode
* **Perubahan Minor (1-2 kata):** Jangan mengubah baris kode lain yang tidak relevan. Tunjukkan bagian spesifik yang perlu diubah, biar pengguna yang melakukan edit manual.
* **Perubahan Mayor:** Jelaskan bagian mana yang akan diubah dan mengapa. Tunggu persetujuan pengguna sebelum melakukan edit menyeluruh pada file.

## 3. Changelog Wajib
* **Setiap** perubahan file (edit, tambah, hapus, rename — termasuk `.md`, config, dan skrip cek) WAJIB dicatat di `changelog.md` di root repo, di sesi yang sama, sebelum menjawab selesai.
* **Posisi:** entri terbaru selalu di paling atas (tepat di bawah blok `Format:`), jangan menimpa entri lama — hanya tambah.
* **Format satu baris:**
  `## [YYYY-MM-DD HH:MM] | path/file | TIPE | apa yang berubah | alasan/dampak`
  TIPE: `ADD`, `EDIT`, `FIX`, `DEL`.
* **Wajib menyertakan** (bullet di bawah entri):
  * `Verifikasi:` apa yang benar-benar dijalankan (test/compile/cek), atau `belum diverifikasi` + alasannya.
  * `Efek samping:` perubahan perilaku yang mungkin tidak diminta, atau `-`.
  * `Catatan:` hal yang sengaja di-skip / TODO, atau `-`.
* **Bug/kecurigaan** yang ditemukan tapi belum diperbaiki masuk bagian `Catatan terbuka` di bawah file, bukan didiamkan.
* Timestamp dari jam sistem (`date '+%Y-%m-%d %H:%M'`), bukan dikira-kira.
* Jika mengubah perilaku lintas file (misal protokol socket `B/W/P/L/N/S/Z` di `server.py` ↔ `Voice_AI.ino`), sebutkan kedua file dalam satu entri.

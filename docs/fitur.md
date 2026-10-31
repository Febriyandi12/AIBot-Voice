# SPESIFIKASI PROYEK AI ASSISTANT ESP32

## 1. Deskripsi Umum
Proyek ini adalah AI Assistant interaktif berbasis ESP32 yang dapat berbicara dan mendengarkan secara natural seperti manusia. AI LLM dapat berganti berdasarkan API key yang aktif. AI diatur untuk memiliki rentang emosi manusia (senang, sedih, marah, takut, manja, dll).

## 2. Spesifikasi Hardware
* **Microcontroller:** ESP32
* **Input Audio:** Mikrofon INMP441
* **Output Audio:** Amplifier I2S MAX98357A
* **Display:** LCD OLED 0.96 inch (Menampilkan wajah, ekspresi emosional dari `emosional.h`, atau animasi saat berbicara)

## 3. Alur Booting (Startup)
1. Saat perangkat baru menyala, AI memberikan kata sambutan secara verbal.
2. AI memberikan penawaran: "Jika butuh ngobrol, tekan tombol untuk komunikasi."
3. Jika tombol tidak ditekan, sistem otomatis masuk ke **Mode Auto**.
4. Jika tombol ditekan, sistem masuk ke **Mode Button**.

## 4. Mode Operasi
### A. Mode Auto (Proaktif & Emosional)
* **Kondisi:** Aktif jika tombol tidak ditekan.
* **Perilaku Utama:** AI berinisiatif mengajak pengguna mengobrol dengan prompt acak yang digenerate oleh LLM (maksimal siklus obrolan: 6x interaksi -> 3x AI bertanya, 3x User menjawab, diakhiri dengan AI bergumam/yapping).
* **Karakter & Emosi:** Jawaban harus natural, tidak kaku, dan mengekspresikan emosi manusia.
* **Pemicu Interaksi (Keep-Alive):** AI akan berbicara sendiri atau mengajak ngobrol setiap 30 detik agar tidak terlihat mati/idle.
* **Fungsi Pengingat:** Bertindak sebagai pengingat produktivitas (contoh: menyuruh minum, berdiri, istirahat).
* **Sinkronisasi Waktu:** Mengingatkan waktu **tepat setiap jam** (terhubung ke NTP pada `server.py` - hindari penyebutan menit/detik).

### B. Mode Button (Fokus Komunikasi)
* **Kondisi:** Aktif jika tombol ditekan.
* **Perilaku Utama:** Tanya-jawab langsung (Command & Response). Apa yang ditanya pengguna, itu yang dijawab AI, dan sebaliknya.
* **Kondisi Berakhir:** Mode ini berhenti jika pengguna menekan tombol kembali atau mengucapkan perintah suara "sesion mati".

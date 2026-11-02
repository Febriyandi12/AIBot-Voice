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
* **Kondisi:** Aktif jika tombol tidak ditekan (dapat dimatikan/dinyalakan kapan saja dengan **menahan tombol selama 3 detik**, layar OLED menampilkan `AUTO NGOMONG 1M: OFF / ON`).
* **Perilaku Utama:** AI berinisiatif mengajak pengguna mengobrol dengan prompt acak yang digenerate oleh LLM. Siklus tanya-jawab bersifat **unlimited (tanpa batas giliran)** selama pengguna masih merespons, dan otomatis berhenti sendiri ketika pengguna tidak merespons.
* **Karakter & Emosi:** Jawaban harus natural, tidak kaku, dan mengekspresikan emosi manusia.
* **Pemicu Interaksi (Keep-Alive):** AI akan berbicara sendiri atau mengajak ngobrol setiap 60 detik agar tidak terlihat mati/idle (selama Auto-Prompt ON).
* **Fungsi Pengingat:** Bertindak sebagai pengingat produktivitas (contoh: menyuruh minum, berdiri, istirahat).
* **Sinkronisasi Waktu:** Mengingatkan waktu **tepat setiap jam** (terhubung ke NTP pada `server.py` - hindari penyebutan menit/detik).

### B. Mode Button (Fokus Komunikasi)
* **Kondisi:** Aktif jika tombol ditekan.
* **Perilaku Utama:** Tanya-jawab langsung (Command & Response). Apa yang ditanya pengguna, itu yang dijawab AI, dan sebaliknya.
* **Kondisi Berakhir:** Mode ini berhenti jika pengguna menekan tombol kembali atau mengucapkan perintah suara "sesion mati".

### C. Mode Panggil (Wake Word)
* **Kondisi:** Aktif saat standby (bukan saat AI sedang bicara).
* **Pemicu:** User mengucapkan kata **"sayang"** atau **"bymax" / "baymax"** (termasuk variasi fonetik STT: `sayank`, `sa yang`, `Bimek`, `Bmax`, `PMAX`, `B, Mek`, `B, mak`, `B Mek`, `Be Mac`, `B, Mac`, `Ayo Mek`). Kata "saya" tidak memicu.
* **Alur:** ESP32 mengukur volume mic (RMS). Di atas ambang → kirim audio ke server (`'K'`). Server transkrip; bukan wake word → diam (`'Z'`), tidak dikirim ke Ollama, kembali standby. Cocok → sesi singkat (jawab, tanya sekali "ada yang perlu dibantu lagi?", maks 2–3 giliran).
* **Sapaan:** Dipanggil **"sayang"** → AI menyapa/menjawab dengan panggilan "sayang". Dipanggil **"bymax"/"baymax"** → AI menyapa sopan/santai tanpa kata "sayang" dan tanpa kata "Tuan". Jika nama pengguna sudah tersimpan di memori, AI memanggil nama/sebutan pengguna, serta memadukan nama saat mode sayang (misal: *"Iya sayang Febri"*). Sapaan "Tuan" dihapus total dari seluruh titik sistem. Panggilan bebas (seperti "bro", "bos") dan imbuhan khusus hanya boleh dipakai jika diperintahkan dan tercatat di memori.
* **Bangun dari Sleep saat dipanggil:** Jika sedang Mode Sleep, panggilan suara ("sayang" / "bymax") yang lolos ambang mic otomatis menyalakan kembali perangkat (`sleepMode = false`). Mode Silent (`autoTalkEnabled = false`) tetap persisten hingga diaktifkan kembali secara manual via tombol 3 detik.
* **Mesin Suara (TTS):** Menggunakan **Microsoft Edge-TTS (`id-ID-GadisNeural`)** untuk menghasilkan suara wanita alami, luwes, dan kasual (bukan robot). Jika offline atau error, otomatis beralih (*fallback*) ke **Piper TTS (`id_ID-news_tts-medium.onnx`)** di RAM.
* **Mic:** Mati saat AI bicara + jeda ~0,5 detik setelahnya. Rekam berlanjut selama user bicara; berhenti saat hening.

### D. Mode Modem-Sleep (Hemat Daya — Toggle Tahan 5 Detik & Perintah Suara)
* **Pemicu ON/OFF Manual:** Tekan & tahan tombol selama **5 detik** (`pollBtnAction() == 5`). Tahan **3 detik lalu lepas** untuk toggle Auto-Prompt 1 menit (`ON/OFF`), dan **klik singkat (80ms .. < 3 detik)** untuk bicara manual (**Mode Button**). Tekan berkali-kali / jitter beruntun (< 350ms) diabaikan sebagai noise (tidak ada mode multi-klik).
* **Pemicu Suara (Voice Sleep):** Ucapkan perintah tidur seperti *"kamu tidur"*, *"tidurlah"*, *"mode sleep"*, *"kamu istirahat ya"*, atau *"bymax kamu tidur"*. Server merespons pamit tidur (menyesuaikan sapaan "sayang" / "Tuan") dan mengirim flag `'S'`. Setelah pemutaran audio selesai, ESP32 otomatis masuk ke mode tidur persis seperti tahan 5 detik.
* **Saat ON:** Menampilkan ekspresi tidur (`Zzz`) selama 1,5 detik lalu mematikan layar OLED (`SSD1306_DISPLAYOFF`) dan mengaktifkan `WiFi.setSleep(WIFI_PS_MIN_MODEM)`, sementara mic standby tetap memantau panggilan.
* **Bangun Otomatis dari Microphone (Filter Ketat):** Ketika dalam mode tidur (`sleepMode`), suara mikrofon hanya dapat membangunkan perangkat jika memanggil nama dia (`Bymax`/`Baymax`), kata sapaan `sayang`, atau perintah `bangun` (misal: *"bangun"*, *"ayo bangun"*, *"kamu bangun dong"*). Suara lain (perintah tidur, henti sesi, noise bising, atau percakapan umum tanpa kata panggil) diabaikan total oleh server (`'Z'`) sehingga perangkat tetap tidur. Tombol fisik klik 1x tetap dapat membangunkan perangkat secara manual.
* **Saat OFF (Tahan 5 Detik Lagi):** Memutar animasi baru bangun tidur (`drawBootWakeUp`) dan kembali ke Standby normal.

---

## 5. Fitur Memori Persisten Otonom (`Server/memory.json`) & Aturan Panggilan
* **Arsitektur Dual-Layer Cognitive Processing:**
  1. *Lapisan 1 (Safety-Net Heuristik):* Menangkap instruksi lisan fleksibel secara langsung di server sebelum LLM dipanggil, serta mentoleransi typo fonetik STT Whisper (*"tuanya"*, *"Tuhan"*, *"pengen gil"*).
  2. *Lapisan 2 (Ekstraksi Kognitif Otonom LLM):* Ollama mengekstrak maksud pengguna ke dalam blok JSON terstruktur `<<<MEMORY_UPDATE>>>` secara otonom, langsung memperbarui `memory.json`, lalu merespons lisan secara natural tanpa template kaku.
* **Penyimpanan:** Disimpan permanen di `Server/memory.json` (skema JSON: `user_name`, `call_sign`, `forbid_tuan`, `custom_suffix`, `custom_wake_reply`, `facts`, `reminders`).
* **Jadwal Pengingat Aktif (Active Reminder Scheduler) & Toleransi Typo Waktu:**
  * Memetakan ucapan pengingat lisan (*"ingatkan saya jam 15.5.9 untuk mandi"*, *"ingatkan aku 10 menit lagi"*) secara presisi ke array aktif `reminders`. Typo titik ganda STT Whisper seperti `15.5.9` dipetakan otomatis ke `15:59`.
  * Pada server polling `cmd == b'P'`, pengingat yang jatuh tempo menjadi **Prioritas #1 Mutlak** di atas sapaan pergantian jam pas (`xx:00`) atau sapaan keheningan 30 detik.
* **Toleransi Typo STT Fonetik Perintah Selesai Sesi:**
  * Mengakomodasi variasi transkripsi salah tangkap Whisper seperti *"Hentikan saya sih ini"*, *"Hentikan CSE ini"*, *"Matikan sesi ini"*, *"sesion mati"* untuk langsung menutup sesi tanpa bertanya kaku.
* **Pendekatan Obrolan Ambigu / Terpotong:**
  * Model diarahkan bersikap santai, ramah, dan pemaaf jika kata ucapan pengguna terpotong atau typo dari mic, serta menebak maksud inti topik tanpa mempermasalahkan atau menginterogasi kata asing seperti bot CS.
* **Pengenalan Nama & Larangan "Tuan":** *"Tolong ingat namanya, ya itu [Nama]"*, *"namaku [Nama]"*, *"jangan panggil tuanya"*, *"jangan panggil Tuhan, panggil namah saja"*. Sapaan "Tuan" dihapus total dari seluruh titik sistem (prompt LLM, fallback sapaan, respon henti, dan pamit tidur).
* **Kustomisasi Jawaban Wake Word:** *"kalau saya panggil jangan jawab iya tuan, tapi iya febri ada apa, ada yang bisa bymax bantu"*. Disimpan ke `custom_wake_reply` dan diucapkan saat kata panggil Bymax didengar.
* **Panggilan Bebas / Santai & Imbuhan Akhir:** *"panggil aku [bro/bos/kak/dll]"*, *"kasih imbuhan di akhir kalimat dengan [kata]"*. AI **hanya boleh** memanggil sebutan santai atau menggunakan imbuhan jika secara eksplisit diminta dan dicatat dalam memori.
* **Catatan, Jadwal, & Fakta Bebas:** *"ingat [catatan/alamat]"*, *"simpan dalam memori [catatan]"*, *"catat [jadwal]"*. Fakta disuntikkan ke prompt Ollama untuk menjawab pertanyaan pengguna secara konsisten.
* **Hapus Memori:** *"hapus semua memori"*, *"reset memori"*. Mereset memori ke keadaan awal.

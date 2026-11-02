# Dokumentasi Setup & Penggunaan Server (`server.py`)

Dokumen ini berisi panduan langkah demi langkah untuk menyiapkan lingkungan Python, menjalankan `server.py`, serta mengatur parameter sensitivitas mikrofon dan kepribadian AI agar berjalan lancar tanpa *error*.

---

## 1. Struktur Folder Proyek

Pastikan di dalam folder proyek kamu (misalnya `~/Documents/LLM/`) terdapat file dan folder berikut:
```text
~/Documents/LLM/
├── venv/                                   # Folder Python Virtual Environment
├── voices/
│   ├── id_ID-news_tts-medium.onnx          # Model suara Bahasa Indonesia Piper TTS
│   └── id_ID-news_tts-medium.onnx.json     # Konfigurasi model suara Piper TTS
└── server.py                               # Script utama server Voice AI
```

---

## 2. Instalasi Awal (Jika Pindah PC / Install Ulang)

Jika kamu baru pertama kali mengatur server di PC baru, jalankan perintah berikut di terminal:

```bash
# 1. Masuk ke direktori proyek
cd ~/Documents/LLM

# 2. Buat virtual environment (venv)
python3 -m venv venv

# 3. Aktifkan venv
source venv/bin/activate

# 4. Install semua library yang dibutuhkan di dalam venv
pip install --upgrade pip
pip install -r requirements.txt
# Atau manual: pip install numpy requests faster-whisper piper-tts edge-tts av
```

---

## 3. Cara Menjalankan Server Setiap Hari (Wajib Urut!)

Agar tidak muncul *error* `ModuleNotFoundError: No module named 'faster_whisper'`, kamu **wajib** mengaktifkan `venv` dan mengatur API Key Ollama setiap kali membuka jendela terminal baru.

Jalankan 4 perintah ini secara berurutan di terminal:

```bash
# 1. Masuk ke folder kerja
cd ~/Documents/LLM

# 2. WAJIB: Aktifkan virtual environment (sampai muncul tulisan (venv) di kiri terminal)
source venv/bin/activate

# 3. Set API Key Ollama (jika belum disimpan permanen di ~/.bashrc)
export OLLAMA_API_KEY="masukkan_api_key_ollama_kamu_di_sini"

# 4. Jalankan server
python3 server.py
```

> **Tips Agar Tidak Perlu Ketik `export OLLAMA_API_KEY` Terus:**
> Ketik perintah ini sekali saja di terminal agar API Key tersimpan permanen:
> `echo 'export OLLAMA_API_KEY="api_key_kamu"' >> ~/.bashrc && source ~/.bashrc`

---

## 4. Kalibrasi & Pengaturan Parameter Penting di `server.py`

Jika kondisi ruangan berubah (misal ada suara kipas angin/AC yang bising) atau kamu ingin mengubah kecepatan waktu tunggu, ubah variabel di bagian atas `server.py`:

### A. Mengatur Sensitivitas Mikrofon (`SPEECH_RMS`)
```python
SPEECH_RMS = 300     # Ambang batas suara bicara vs hening
SILENCE_WIN = 6      # 6 x 100 ms (0.6 detik) hening = dianggap selesai bicara
```
* **Cara Kalibrasi:** Perhatikan tulisan `rms=  xxx` di terminal saat `[MIC ON]` aktif tapi kamu sedang **diam**.
* Jika saat kamu diam angkanya sekitar `180 - 200`, maka pasang `SPEECH_RMS = 300` (sekitar 100 poin di atas angka *noise* ruangan).
* **Jika terlalu kecil** (di bawah angka *noise* ruangan): Server akan mengira kamu terus bicara dan baru berhenti setelah batas 10 detik (`MAX_SEC`) habis.
* **Jika terlalu besar** (misal `1000`): Suara bicaramu tidak akan dianggap sebagai bicara oleh server.

### B. Mengatur Waktu Sapaan Standby (`IDLE_INTERVAL`)
```python
IDLE_INTERVAL = 30   # Waktu tunggu hening (dalam detik) sebelum AI bicara sendiri
```
* Ubah angka `30` sesuai keinginan (misal `60` untuk 1 menit sekali, atau `30` untuk 30 detik sekali).
* Saat sedang *Standby*, terminal akan menampilkan hitung mundur: `[Standby] Ngomong otomatis dalam xx detik...`.

### C. Mengubah Kepribadian & Mood Asisten
* **Karakter Utama:** Ubah teks di variabel `SYSTEM = (...)` untuk mengganti gaya bahasa dasar.
* **Mood Spontan 30 Detik:** Tambahkan atau ubah daftar di dalam `IDLE_MOODS`:
  * Formatnya adalah `("Instruksi emosi/topik", True/False)`.
  * Nilai `True` di belakang berarti setelah AI selesai bicara, **mikrofon ESP32 akan otomatis menyala** untuk mendengarkan jawabanmu.
  * Nilai `False` berarti AI hanya bergumam/bernyanyi sendiri tanpa menyalakan mikrofon setelahnya.

### D. Konfigurasi Suara (TTS Engine)
Server mendukung dua mesin TTS dengan deteksi otomatis:
1. **Edge-TTS (`id-ID-GadisNeural`) [Default]:**
   * Menghasilkan suara perempuan muda Indonesia alami, intonasi lisan luwes dan ekspresif (bukan robot).
   * Membutuhkan koneksi internet pada server PC (gratis, tanpa API key).
2. **Piper TTS (`id_ID-news_tts-medium.onnx`) [Fallback]:**
   * Mode offline lokal di RAM. Otomatis dipakai jika koneksi internet terputus atau paket `edge-tts` belum terpasang.
* Konfigurasi di `server.py` atau environment variable:
  ```bash
  export TTS_ENGINE="edge"            # "edge" (suara cewek natural) atau "piper" (offline lokal)
  export EDGE_TTS_VOICE="id-ID-GadisNeural" # Suara perempuan alternatif: "id-ID-SitiNeural"
  ```

---

## 5. Protokol Komunikasi TCP (ESP32 <-> Server)

Sebagai pengingat cara kerja kode di balik layar:
* **Port:** `8765` (TCP Socket).
* **Kode dari ESP32 ke Server:**
  * `'W'` (*Welcome*): Dikirim saat ESP32 baru selesai *booting*, direspon dengan suara *"Selamat datang, Tuan."*
  * `'B'` (*Button*): Dikirim saat tombol ditekan untuk memulai rekam suara.
  * `'P'` (*Poll*): Dikirim tiap 1 detik saat ESP32 *standby* untuk mengecek apakah jadwal 30 detik atau jam pas (`xx:00`) sudah tercapai.
* **Kode dari Server ke ESP32:**
  * `'S'` (*Stop Recording*): Dikirim server ketika mendeteksi kamu sudah selesai bicara.
  * `'Z'` (*Zzz / Standby*): Dikirim server saat membalas `'P'` jika belum waktunya bicara otomatis.
  * `'L'` + Data Audio (*Listen*): Meminta ESP32 memutar suara AI, lalu **otomatis menyalakan mic** setelah suara selesai.
  * `'N'` + Data Audio (*No-Listen*): Meminta ESP32 memutar suara AI, lalu langsung kembali ke mode *Standby*.

---

## 6. Fitur Memori Persisten Otonom (`memory.json`) & Aturan Panggilan

Server dilengkapi memori persisten di file `Server/memory.json` berbasis **Dual-Layer Cognitive Processing**:
1. **Lapisan 1 (Safety-Net Heuristik Cepat):** Menangkap instruksi lisan fleksibel langsung di server sebelum LLM berjalan (termasuk toleransi typo fonetik STT Whisper seperti *"tuanya"*, *"Tuhan"*, *"pengen gil"*).
2. **Lapisan 2 (Ekstraksi Kognitif Otonom LLM):** Model Ollama menganalisis maksud ucapan user secara bebas, mengekstrak blok terstruktur `<<<MEMORY_UPDATE>>>`, memperbarui `memory.json`, lalu menjawab secara natural tanpa template kaku.

### A. Format `memory.json`
```json
{
  "user_name": "Febri",
  "call_sign": "Febri",
  "forbid_tuan": true,
  "custom_suffix": "bos",
  "custom_wake_reply": "Iya Febri ada apa, ada yang bisa Bymax bantu?",
  "facts": [
    "alamat rumah di Bandung",
    "suka kopi tubruk"
  ],
  "reminders": [
    {
      "time": "15:59",
      "task": "mandi",
      "date": "2026-11-01",
      "notified": false
    }
  ]
}
```

### B. Perintah Suara & Pengenalan Fleksibel
* **Pengenalan Nama & Larangan "Tuan":**
  * Ucapan: *"Tolong ingat namanya, ya itu Febri"*, *"namaku Febri"*, *"nama saya Budi"*, *"kenalin aku Andi"*
  * Efek: Bot mengingat nama. **MUTLAK DILARANG memanggil "Tuan"** begitu nama user sudah dikenalkan atau dilarang.
* **Toleransi Typo STT Lisan:**
  * Ucapan: *"Jadi jangan panggil tuanya"*, *"Baymax, jangan panggil Tuhan, panggil namah saja"*, *"Ingat dalam memori mu, jangan pengen gil tuan"*
  * Efek: Otomatis mengaktifkan flag `forbid_tuan = true` dan menghentikan sapaan "Tuan" di seluruh titik sistem.
* **Jadwal Pengingat Aktif (Active Reminder Scheduler) & Toleransi Typo Waktu:**
  * Ucapan: *"Baymax ingatkan saya jam 15.5.9 untuk melakukan mandi"*, *"ingatkan aku jam 16:30 jemput adik"*, *"ingatkan 10 menit lagi matikan kompor"*
  * Efek: Otomatis memetakan format waktu typo Whisper (`15.5.9` -> `15:59`) atau durasi relatif ("N menit lagi") ke skema aktif `reminders`. Saat menit tiba, server polling memprioritaskan peringatan ini di atas sapaan lainnya.
* **Penutupan Sesi Toleran Typo Fonetik Whisper:**
  * Ucapan: *"Hentikan saya sih ini"*, *"Hentikan CSE ini"*, *"Matikan sesi ini"*, *"sesion mati"*, *"stop ngobrol"*
  * Efek: Otomatis mengakhiri sesi percakapan tanpa bingung atau bertanya kaku.
* **Kustomisasi Respon Saat Dipanggil (Wake Reply):**
  * Ucapan: *"kalau saya panggil jangan jawab iya tuan, tapi iya febri ada apa, ada yang bisa Bymax bantu"*
  * Efek: Menyimpan teks ke `custom_wake_reply` dan digunakan setiap kali kata panggil Bymax diucapkan.
* **Panggilan Bebas / Santai & Imbuhan Akhir:**
  * Ucapan: *"panggil aku bro"*, *"kasih imbuhan di akhir kalimat dengan bos"*, *"pakai imbuhan dong ah"*
  * Efek: Bot hanya boleh memanggil sebutan santai (*bro*, *bos*, dll) dan imbuhan jika **secara eksplisit diminta user dan tersimpan di memori**.
* **Catatan / Fakta Bebas:**
  * Ucapan: *"ingat alamat rumah saya di Bandung jalan merdeka nomor 5"*
  * Efek: Disimpan ke daftar `facts` dan disuntikkan ke konteks percakapan.
* **Reset Memori:**
  * Ucapan: *"hapus semua memori"*, *"reset memori"*

---

## 7. Troubleshooting Server Python

1. **`ModuleNotFoundError: No module named 'faster_whisper'`:**
   * Kamu lupa menjalankan `source venv/bin/activate` sebelum mengeksekusi `python3 server.py`.
2. **`KeyError: 'OLLAMA_API_KEY'`:**
   * Kamu belum memasukkan `export OLLAMA_API_KEY="..."` di terminal.
3. **`IndentationError: unexpected indent`:**
   * Di Python, kesejajaran spasi di awal baris sangat ketat. Pastikan setiap blok di dalam `if`, `elif`, dan `else` menjorok tepat kelipatan 4 spasi dan tidak tercampur dengan karakter *Tab*.
4. **`OSError: [Errno 98] Address already in use`:**
   * Ada proses `server.py` sebelumnya yang masih berjalan di latar belakang. Matikan dengan menekan `Ctrl + C` atau jalankan `pkill -f server.py` di terminal, lalu jalankan ulang.
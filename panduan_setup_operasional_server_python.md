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
pip install numpy requests faster-whisper piper-tts
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

## 6. Troubleshooting Server Python

1. **`ModuleNotFoundError: No module named 'faster_whisper'`:**
   * Kamu lupa menjalankan `source venv/bin/activate` sebelum mengeksekusi `python3 server.py`.
2. **`KeyError: 'OLLAMA_API_KEY'`:**
   * Kamu belum memasukkan `export OLLAMA_API_KEY="..."` di terminal.
3. **`IndentationError: unexpected indent`:**
   * Di Python, kesejajaran spasi di awal baris sangat ketat. Pastikan setiap blok di dalam `if`, `elif`, dan `else` menjorok tepat kelipatan 4 spasi dan tidak tercampur dengan karakter *Tab*.
4. **`OSError: [Errno 98] Address already in use`:**
   * Ada proses `server.py` sebelumnya yang masih berjalan di latar belakang. Matikan dengan menekan `Ctrl + C` atau jalankan `pkill -f server.py` di terminal, lalu jalankan ulang.
# Dokumentasi Proyek Voice AI Assistant (ESP32 + Homelab Server)

Proyek ini adalah sistem asisten suara pintar interaktif berbasis **ESP32** yang terhubung ke server lokal/homelab melalui jaringan WiFi. Asisten memiliki kepribadian ekspresif, dapat diajak mengobrol dua arah secara otomatis (*Auto-Mic*), menyapa saat baru menyala, mengingatkan waktu setiap pergantian jam pas (`xx:00`), serta mengajak ngobrol sendiri setiap 30 detik saat dalam kondisi *standby*.

---

## 1. Daftar Modul & Komponen (Hardware)

1. **Mikrokontroler:** ESP32 DevKit V1 (30-pin / 38-pin)
2. **Modul Mikrofon:** INMP441 (Omnidirectional I2S MEMS Microphone)
3. **Modul Amplifier:** MAX98357A (I2S 3W Class D Amplifier)
4. **Speaker:** Speaker Pasif 4 Ohm / 8 Ohm (3W - 5W)
5. **Input Manual:** Push Button (Tactile Switch) untuk memicu percakapan manual

---

## 2. Konfigurasi Pin (Wiring Diagram)

Sistem ini menggunakan satu bus **I2S (`I2S_NUM_0`)** yang bergantian antara mode rekam (*RX* dari INMP441) dan mode putar suara (*TX* ke MAX98357A). Pastikan jalur kabel terpasang persis sesuai tabel berikut:

### A. Modul Speaker Amplifier (MAX98357A -> ESP32)
| Pin MAX98357A | Pin ESP32 | Keterangan |
| :--- | :--- | :--- |
| **VIN** | **5V / VIN** | Disarankan 5V agar suara speaker lantang dan tidak *drop* |
| **GND** | **GND** | Ground |
| **BCLK** | **GPIO 26** | Bit Clock I2S TX (`PIN_I2S_BCLK`) |
| **LRC / WS** | **GPIO 25** | Left/Right Word Select I2S TX (`PIN_I2S_WS`) |
| **DIN** | **GPIO 27** | Data Input Audio I2S TX (`PIN_I2S_DOUT`) |
| **GAIN / SD** | *Kosongkan* | Biarkan *floating* (default) |

### B. Modul Mikrofon (INMP441 -> ESP32)
| Pin INMP441 | Pin ESP32 | Keterangan |
| :--- | :--- | :--- |
| **VDD** | **3V3** | **WAJIB 3.3V** (Jangan dihubungkan ke 5V!) |
| **GND** | **GND** | Ground |
| **L/R** | **GND** | Hubungkan ke GND agar masuk ke kanal Kiri (`ONLY_LEFT`) |
| **SCK** | **GPIO 33** | Serial Clock I2S RX (`PIN_MIC_SCK`) |
| **WS** | **GPIO 32** | Word Select I2S RX (`PIN_MIC_WS`) |
| **SD** | **GPIO 35** | Serial Data Output I2S RX (`PIN_MIC_SD`) |

### C. Tombol Push Button (Manual Trigger)
| Pin Button | Pin ESP32 | Keterangan |
| :--- | :--- | :--- |
| **Kaki 1** | **GPIO 4** | Menggunakan `INPUT_PULLUP` internal (`PIN_BTN`) |
| **Kaki 2** | **GND** | Ground (Aktif LOW saat ditekan) |

---

## 3. Pengaturan pada Kode Arduino (`Voice_AI.ino`)

Sebelum melakukan *upload* ke ESP32 melalui Arduino IDE, selalu periksa 4 baris konfigurasi jaringan di bagian atas kode:

```cpp
#define WIFI_SSID   "Wifi Kamu"  // Nama WiFi kamu
#define WIFI_PASS   "Password Wifi Kamu"          // Password WiFi kamu
#define SERVER_IP   "192.168.1.28"      // IP Address PC/Laptop yang menjalankan server.py
#define SERVER_PORT 8765                // Port komunikasi TCP (harus sama dengan server.py)
```
> **Catatan Penting:** Jika IP PC Server berubah (karena DHCP router), kamu harus memperbarui `#define SERVER_IP` di ESP32 agar bisa terhubung kembali.

---

## 4. Alur Kerja & Cara Penggunaan

1. **Saat Baru Menyala (Booting):**
   * Pastikan `server.py` di PC sudah berjalan terlebih dahulu.
   * Nyalakan ESP32. Setelah terhubung ke WiFi, ESP32 otomatis mengirim sinyal `'W'` dan speaker akan menyapa: *"Selamat datang, Tuan."*
2. **Mengajak Ngobrol Manual:**
   * Tekan tombol pada **GPIO 4** (atau ketik karakter apa saja lalu Enter di Serial Monitor Arduino IDE).
   * Saat muncul status `[MIC ON] Silakan bicara...`, langsung bicara ke mikrofon.
   * Berhenti bicara sejenak (~0.6 detik), server otomatis mendeteksi keheningan dan memproses jawaban.
3. **Fitur Auto-Mic (Percakapan Dua Arah Tanpa Tombol):**
   * Setiap kali AI selesai menjawab dan kalimatnya mengandung pertanyaan (flag `'L'`), kamu **tidak perlu menekan tombol lagi**.
   * Tunggu hingga speaker selesai bicara (`[SPEAKER OFF]`), maka mikrofon akan otomatis menyala kembali (`[MIC ON]`).
   * Jika kamu tidak ingin menjawab lagi, cukup diam saja sampai *mic* mati sendiri, lalu sistem akan kembali ke mode *Standby*.
4. **Fitur Sapaan Otomatis (Standby 30 Detik & Jam Pas):**
   * Saat kondisi hening (*Standby*), biarkan perangkat menyala tanpa menekan tombol.
   * Setelah 30 detik hening penuh sejak interaksi terakhir, AI akan otomatis bicara sendiri sesuai *mood* acak (manja, lapar, sedih, bernyanyi, atau bertanya kabar) dan langsung menyalakan mikrofon untuk mendengar jawabanmu.
   * Setiap pergantian jam tepat di menit `:00` (misal 04:00, 05:00, 13:00), AI akan otomatis memberi tahu waktu saat ini.

---

## 5. Troubleshooting Hardware (Masalah Umum)

* **Tertulis `[ERR] Tidak bisa konek ke server` di Serial Monitor:**
  * Pastikan `server.py` sudah dijalankan di PC.
  * Cek IP PC dengan perintah `ip a` atau `hostname -I` di terminal Linux, pastikan sama dengan `SERVER_IP` di kode ESP32.
  * Pastikan ESP32 dan PC berada di jaringan WiFi/subnet yang sama.
* **Suara kita tidak terdeteksi / Mic selalu merekam sampai 10 detik penuh:**
  * Cek kabel pin **L/R** pada modul INMP441, pastikan terhubung ke **GND**.
  * Cek nilai `rms=...` di terminal server saat kamu diam dan bicara, lalu sesuaikan angka `SPEECH_RMS` di `server.py`.

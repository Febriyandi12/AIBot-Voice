# Changelog

Format: `[YYYY-MM-DD HH:MM] | file | TIPE | perubahan | alasan/dampak`
TIPE: `ADD` (file/fitur baru), `EDIT` (ubah logika), `FIX` (perbaikan bug), `DEL` (hapus).
Entri terbaru di paling atas. Wajib diisi setiap selesai mengubah apa pun (lihat `docs/Rules.md` §3).

---

## [2026-10-31 13:54] | .gitignore | CHORE | Ubah `.vscode/.pio/` menjadi `.vscode/` dan hapus `.vscode/` dari tracking git (`git rm -r --cached .vscode`) | Agar file konfigurasi lokal VSCode/PlatformIO (`.vscode/c_cpp_properties.json` yang berisi path lokal user) tidak ikut ter-push ke GitHub
- Verifikasi: `git status --ignored` & `git show --stat HEAD` (`.vscode/` tidak lagi terlacak di commit).
- Efek samping: Tidak ada (file `.vscode/` di lokal tetap utuh untuk IntelliSense).
- Catatan: -

## [2026-10-31 10:21] | src/main.cpp, Server/server.py | FIX | Pisahkan peripheral I2S speaker (`I2S_NUM_0`) dan mic (`I2S_NUM_1`) + warmup DMA 4 buffer, kuras sisa paket mic (`drain_recv`) setelah `b"S"`, dan tahan penutupan socket sebesar durasi putar audio (`play_sec + 0.4s`) saat `expect_reply=False` | Memperbaiki suara speaker yang langsung terputus (`[SPEAKER OFF]`) sebelum selesai bicara akibat TCP RST/penutupan socket dini dari `server.py`, serta memperbaiki `rms=0` saat transisi TX->RX pada peripheral I2S yang sama
- Verifikasi: `~/.platformio/penv/bin/pio run` → `[SUCCESS]` (RAM 13.8%, Flash 61.5%) & `Server/venv/bin/python check_flow.py` → `OK: 4 cek alur sesi lolos`.
- Efek samping: Saat AI berbicara penutup/teguran cuek (`Auto-Mic: TIDAK`), `server.py` menunggu sampai kalimat benar-benar selesai diputar di speaker ESP32 baru menutup koneksi dan memulai hitung mundur Standby 30 detik.
- Catatan: -

## [2026-10-31 10:09] | src/main.cpp, Server/server.py, check_flow.py | FIX | Hapus `faceDraw()` dari dalam loop streaming I2S (`recordAndSend` & `receiveAndPlay`), aktifkan Fast I2C 400kHz, mulai rekam langsung saat tombol ditekan (`btnReleased` guard agar tahan/lepas tombol tidak memutus mic), tambah balasan suara manja saat user diam/cuek (`SILENT_PROMPT` + `SILENT_FALLBACKS`), dan jaga pasangan `user`-`assistant` di `history` + guard `tts()`/`allow_question=False` | Memperbaiki mic tidak merekam akibat terblokir transfer I2C OLED di tengah loop 16kHz & deteksi tombol saat masih ditahan, serta memperbaiki bug konteks LLM rusak/kosong saat user diam yang membuat speaker bisu
- Verifikasi: `~/.platformio/penv/bin/pio run` → `[SUCCESS]` (RAM 13.8%, Flash 61.5%) & `Server/venv/bin/python check_flow.py` → `OK: 4 cek alur sesi lolos`.
- Efek samping: Saat user diam/tidak bicara, AI tidak lagi bisu melainkan menyahut manja ("kamu cuek banget sih...") lalu menutup sesi dengan rapi (`flag = 'N'`).
- Catatan: -

## [2026-10-31 09:20] | src/main.cpp | FIX | Auto-kalibrasi `btnIdle` saat boot, debounce `btnTriggered()` (>=80ms), `waitBtnRelease()` non-blocking (`sceneTick()` tetap jalan + auto-rekalibrasi jika tertahan >1.5s), dan timeout 300ms untuk polling `'P'` | Memperbaiki bug tombol (`PIN_BTN` GPIO 4) yang terbaca `LOW` / memantul sehingga langsung memutus `[MIC ON]` & `[SPEAKER ON]` (`[BTN] Tombol ditekan -> sesi dihentikan`) serta membuat loop macet di `while (digitalRead(PIN_BTN) == LOW)` hingga layar OLED stuck
- Verifikasi: `~/.platformio/penv/bin/pio run` → `[SUCCESS]`, RAM 13.8% (45.340 B), Flash 61.5% (806.313 B).
- Efek samping: Mendukung tombol aktif-LOW maupun aktif-HIGH secara otomatis dan tidak pernah membekukan layar OLED meskipun kabel tombol nyangkut/lepas.
- Catatan: -

## [2026-10-31 09:05] | src/emosional.h, src/main.cpp | EDIT | Tambah 8 adegan emosional baru di `src/emosional.h` (`SC_MANJA`, `SC_SEDIH`, `SC_MARAH`, `SC_NGANTUK`, `SC_KEDIP`, `SC_MAKAN`, `SC_KETAWA`, `SC_MIKIR` — total 14 adegan bergantian acak tanpa pengulangan berurutan); tambah `sceneTick()` di `src/main.cpp` saat konek WiFi & saat menunggu balasan server (`receiveAndPlay`) | Agar layar OLED 0.96" bergerak terus tanpa freeze saat tunggu LLM/TTS dan punya variasi ekspresi lengkap sesuai `docs/fitur.md`
- Verifikasi: `~/.platformio/penv/bin/pio run` → `[SUCCESS]`, RAM 13.8% (45.332 B), Flash 61.5% (806.121 B).
- Efek samping: -
- Catatan: -

## [2026-10-31 08:43] | Server/server.py, check_flow.py | FIX | `send_audio_and_maybe_listen()` & `conversation_loop()` tangkap `OSError` pada semua `c.sendall()`; `check_flow.py` diarahkan ke folder `Server/` | Mencegah `ERR: [Errno 104] Connection reset by peer` saat ESP32 memutus koneksi di tengah pemutaran suara / rekaman (`cli.stop()`)
- Verifikasi: `Server/venv/bin/python check_flow.py` → `OK: 4 cek alur sesi lolos`.
- Efek samping: Saat ESP32 memutus koneksi ketika audio sedang dikirim, server menampilkan `[INFO] Koneksi ditutup ESP32 saat memutar suara` dan menutup sesi dengan bersih.
- Catatan: Jika `[INFO] Koneksi ditutup ESP32 saat memutar suara` muncul terus padahal tombol tidak ditekan, cek `PIN_BTN` (GPIO 4) di ESP32 apakah aktif-HIGH / terhubung ke GND.

## [2026-10-31 08:18] | ~/.platformio/penv | FIX | `~/.platformio/penv/bin/pip install intelhex` | VS Code PlatformIO memakai `~/.platformio/penv`, bukan `LLM/venv`; sebelumnya `esptool.py` gagal membuat `bootloader.bin` karena `ModuleNotFoundError: No module named 'intelhex'`
- Verifikasi: `~/.platformio/penv/bin/pio run` → `[SUCCESS]` (`bootloader.bin` + `firmware.bin` terbentuk, RAM 13.8%, Flash 61.2%).
- Efek samping: -
- Catatan: -

## [2026-10-31 08:07] | platformio.ini | ADD | Project PlatformIO: `env:esp32dev`, `platform=espressif32@^6.11.0`, `framework=arduino`, `lib_deps` = Adafruit SSD1306 ^2.5.13 + Adafruit GFX ^1.11.11, `-std=gnu++17`, monitor 115200 | Migrasi Arduino IDE → VS Code; library ter-declare & reproducible, tidak perlu Library Manager
## [2026-10-31 08:07] | src/main.cpp, src/emosional.h | DEL/RENAME | `Voice_AI/Voice_AI.ino` → `src/main.cpp` (git mv), `Voice_AI/emosional.h` → `src/emosional.h`, folder `Voice_AI/` dihapus; tambah `#include <Arduino.h>` | Struktur wajib PlatformIO (`src/`); include lokal tetap `#include "emosional.h"`
- Verifikasi: `pio run` → `[SUCCESS]`, RAM 13.8% (45.332 B / 327.680 B), Flash 61.2% (801.977 B / 1.310.720 B). Log: `/tmp/pio.log`.
- Catatan: `pio` di mesin ini ada di `/home/rnd-fres/Documents/LLM/venv/bin/pio` (venv proyek ini belum punya binary `pio`); `intelhex` sudah dipasang agar `esptool` jalan.
## [2026-10-31 08:07] | README.md | EDIT | §3 ganti ke `src/main.cpp` + struktur PlatformIO + perintah `pio run/upload/monitor` + daftar library; §2 tambah wiring OLED (SDA 21, SCL 22, 0x3C) sebagai bagian D; teks sapaan boot disesuaikan dengan `server.py` | Hindari user wiring salah & dokumentasi tidak melenceng dari kode
- Verifikasi: dibandingkan manual dengan `src/main.cpp` (`PIN_OLED_SDA`/`PIN_OLED_SCL`/`OLED_ADDR`) dan `server.py` (`'W'`).
## [2026-10-31 08:07] | .gitignore | EDIT | Tambah `.pio/` dan `.vscode/.pio/` | Jangan commit artefak build PlatformIO

---

## [2026-10-31 07:51] | Voice_AI/Voice_AI.ino | ADD | Integrasi `emosional.h`: `Wire` + `Adafruit_SSD1306` (SDA 21 / SCL 22, addr 0x3C), glue `Note`/`playSequence()`/`currentState`/`stateDuration`/`lastStateChange`/`STATE_SCENE`, `startScene()` di `setup()`, `sceneTick()` di standby, `faceDraw()` saat rekam & bicara | Fitur OLED 0.96" (wajah + animasi emosi) dari `docs/fitur.md` §2
- Verifikasi: `g++ -fsyntax-only` dengan stub Arduino → OK. Belum compile di Arduino IDE (butuh lib `Adafruit SSD1306` + `Adafruit GFX`).
- Catatan: `playSequence()` sengaja no-op — melodi `emosional.h` butuh buzzer pasif (belum terpasang). Adegan tetap jalan, hanya tanpa suara.

## [2026-10-31 07:51] | docs/Rules.md | EDIT | Tambah §3 Changelog Wajib + changelog masuk daftar baca awal | Tracking perubahan antar-agent (Round Robin)
## [2026-10-31 07:51] | changelog.md | ADD | File ini | Sumber status terakhir pekerjaan
## [2026-10-31 07:50] | check_flow.py | ADD | Self-check alur sesi (stub LLM/TTS/socket), 4 kasus | Regresi `conversation_loop` tanpa hardware. Jalankan: `venv/bin/python check_flow.py`

## [2026-10-31 07:20] | server.py | EDIT | `conversation_loop(c, max_turns, keep_listening)`; `AUTO_MAX_TURNS=3`, `END_CMDS`, `CLOSE_PROMPT`, `is_end_cmd()`; boot `W` = sambutan + tawaran tekan tombol (tanpa auto-mic); mode `B` selalu lanjut dengar; Auto (30s & jam pas) berhenti setelah 3 tanya-jawab + gumaman penutup; prompt jam tanpa menit/detik; `record()` tahan `OSError` | Selaraskan dengan `docs/fitur.md` §3–§4
- Perilaku baru: ucap "sesion mati"/"sesi mati" → sesi berakhir (`N` lalu tutup).
- Efek samping: mode Auto memanggil LLM ekstra 1x per siklus (gumaman penutup).

## [2026-10-31 07:20] | Voice_AI/Voice_AI.ino | EDIT | `recordAndSend()` & playback loop: `digitalRead(PIN_BTN)==LOW` → `i2sStop()` + `cli.stop()` + `return false`; mode `B` tunggu tombol dilepas sebelum rekam | Fitur "Mode Button berhenti saat tombol ditekan kembali" (`docs/fitur.md` §4B)
- Efek samping: tekan tombol saat AI bicara di mode Auto juga memotong suara lalu masuk mode Button.

---

## Catatan terbuka (bug/kecurigaan, belum ditangani)
- `server.py` masih pakai jam host (`datetime.now()`), bukan NTP; `fitur.md` menyebut NTP di `server.py`.
- Pengumuman jam hanya jalan saat `now.minute == 0`; kalau server mati/restart di menit itu, pengumuman jam terlewat sampai jam berikutnya.
- `IDLE_MOODS` entri tanpa tanda tanya tidak membuka mic — user harus tekan tombol untuk membalas.

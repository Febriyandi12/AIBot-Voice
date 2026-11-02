/*
 * Voice AI ESP32 DevKit V1: mic (INMP441) + speaker (MAX98357A) -> server homelab -> Ollama
 * Fitur:
 * - Tekan tombol BOOT / Serial untuk mulai bicara
 * - Standby: tiap 30 detik & tiap pergantian jam (xx:00) AI bicara sendiri
 * - Auto-Mic: jika AI selesai bertanya, mic otomatis menyala untuk mendengar jawabanmu
 * - OLED 0.96": animasi emosional saat standby (emosional.h) + wajah saat bicara/dengar
 */
#include <Arduino.h>
#include <WiFi.h>
#include <driver/i2s.h>
#include <Wire.h>
#include <Adafruit_GFX.h>
#include <Adafruit_SSD1306.h>
#include <math.h>
#include "emosional.h"

#define WIFI_SSID   "FRES factory EXT"
#define WIFI_PASS   "fres1819"
#define SERVER_IP   "192.168.1.28"   // IP PC homelab ATAU pc laptop yang di runing server.py
#define SERVER_PORT 8765

#define PIN_BTN      4              // tombol push (aktif LOW)

// OLED 0.96" SSD1306 (I2C)
#define PIN_OLED_SDA 21
#define PIN_OLED_SCL 22
#define OLED_ADDR    0x3C

// Speaker (MAX98357A)
#define PIN_I2S_BCLK 26
#define PIN_I2S_WS   25
#define PIN_I2S_DOUT 27

// Mic (INMP441)
#define PIN_MIC_SCK  33
#define PIN_MIC_WS   32
#define PIN_MIC_SD   35

#define SAMPLE_RATE  16000
#define SPEECH_RMS   300    // ambang gerbang volume untuk Mode Panggil

unsigned long lastPoll = 0;
unsigned long lastMicCheck = 0;

// Status sistem global (diakses juga oleh emosional.h)
volatile bool sleepMode = false;
volatile bool autoTalkEnabled = true;

// Deteksi tombol fisik GPIO 4 (mendukung aktif-LOW maupun aktif-HIGH otomatis)
static uint8_t btnIdleState = HIGH;
static unsigned long btnDownSince = 0;

static bool btnDown() {
  static bool debouncedDown = false;
  static bool lastRawDown = false;
  static unsigned long lastChangeMs = 0;

  bool rawDown = (digitalRead(PIN_BTN) != btnIdleState);
  if (rawDown != lastRawDown) {
    lastRawDown = rawDown;
    lastChangeMs = millis();
  }
  // Wajib stabil minimal 40ms agar terbebas dari spike/jitter/noise
  if (millis() - lastChangeMs >= 40) {
    debouncedDown = rawDown;
  }
  return debouncedDown;
}

static bool btnTriggered() {
  if (!btnDown()) {
    btnDownSince = 0;
    return false;
  }
  if (btnDownSince == 0) btnDownSince = millis();
  return (millis() - btnDownSince >= 60); // wajib ditekan stabil >= 60ms
}

static void waitBtnRelease() {
  unsigned long t0 = millis();
  while (btnDown()) {
    vTaskDelay(10 / portTICK_PERIOD_MS);
    if (millis() - t0 > 6000) break; // timeout safety 6s agar tidak pernah stuck
  }
  vTaskDelay(50 / portTICK_PERIOD_MS);
  btnDownSince = 0;
}

// Deteksi tombol:
// - Tekan berkali-kali / jitter noise = diabaikan (return 0)
// - Klik singkat tunggal (< 800ms) = return 1 (bicara manual 'B') saat dilepas
// - Tahan 3 detik (3..4.9s) = return 3 saat dilepas (toggle Auto-Prompt 1 menit ON/OFF)
// - Tahan 5 detik (>= 5s) = return 5 langsung saat mencapai 5s (toggle Modem-Sleep ON/OFF)
// - Feedback visual progres: return 10 (ditahan >= 200ms), return 30 (ditahan >= 3000ms)
static int pollBtnAction() {
  static unsigned long pressStartMs = 0;
  static unsigned long lastReleaseMs = 0;
  static int rapidTapCount = 0;
  static bool wasDown = false;
  static bool hold3Notified = false;
  static bool hold5Triggered = false;
  static bool holdShown = false;

  bool down = btnDown();
  unsigned long now = millis();

  if (down) {
    if (!wasDown) {
      wasDown = true;
      pressStartMs = now;
      hold3Notified = false;
      hold5Triggered = false;
      holdShown = false;
      if (now - lastReleaseMs < 350) {
        rapidTapCount++;
      } else {
        rapidTapCount = 0;
      }
    }

    unsigned long held = now - pressStartMs;

    // Tahan 5 detik -> langsung eksekusi Modem-Sleep seketika tanpa harus menunggu dilepas
    if (!hold5Triggered && held >= 5000) {
      hold5Triggered = true;
      rapidTapCount = 0;
      return 5;
    }
    if (!hold3Notified && held >= 3000) {
      hold3Notified = true;
      return 30; // Feedback visual di OLED bahwa batas 3 detik tercapai
    }
    if (!holdShown && held >= 200) {
      holdShown = true;
      return 10; // Feedback instan: tombol ditahan -> tampilkan bar progres
    }
  } else if (!down && wasDown) {
    unsigned long held = now - pressStartMs;
    wasDown = false;
    lastReleaseMs = now;

    if (hold5Triggered) {
      hold5Triggered = false;
      hold3Notified = false;
      rapidTapCount = 0;
      return 0; // Sudah dieksekusi saat 5s
    }
    hold3Notified = false;

    // Tahan 3..4.9 detik -> toggle Auto-Prompt 1 menit
    if (held >= 3000) {
      rapidTapCount = 0;
      return 3;
    }

    // Noise jitter / double tap cepat diabaikan
    if (rapidTapCount > 0 || held < 80) {
      return 0;
    }

    // Bila ditahan antara 800ms .. 2999ms lalu dilepas sebelum 3s -> batal tanpa aksi
    if (held >= 800) {
      return 0;
    }

    // Klik singkat bersih (< 800ms) -> bicara manual ('B')
    return 1;
  }
  return 0;
}

static bool micListening = false;       // driver mic RX aktif saat standby
static bool radioPlaying = false; // true saat streaming radio
static unsigned long micMutedUntil = 0; // jeda mic 500ms setelah speaker selesai
static volatile bool serverReplied = false; // true bila server balas selain 'Z' (kata panggil sah)

static void i2sStop(i2s_port_t port) {
  i2s_zero_dma_buffer(port);
  i2s_driver_uninstall(port);
  micListening = false;
}

// tx = true: keluarkan suara ke amplifier (I2S_NUM_0); tx = false: baca mic (I2S_NUM_0)
static bool i2sStart(bool tx) {
  if (micListening) i2sStop(I2S_NUM_0);
  i2s_port_t port = I2S_NUM_0;
  i2s_config_t cfg = {};
  cfg.mode = (i2s_mode_t)(I2S_MODE_MASTER | (tx ? I2S_MODE_TX : I2S_MODE_RX));
  cfg.sample_rate = SAMPLE_RATE;
  cfg.bits_per_sample = tx ? I2S_BITS_PER_SAMPLE_16BIT : I2S_BITS_PER_SAMPLE_32BIT;
  // cfg.channel_format = tx ? I2S_CHANNEL_FMT_RIGHT_LEFT : I2S_CHANNEL_FMT_ONLY_LEFT;
  cfg.channel_format = tx ? I2S_CHANNEL_FMT_RIGHT_LEFT : I2S_CHANNEL_FMT_ONLY_RIGHT;
  cfg.communication_format = I2S_COMM_FORMAT_STAND_I2S;
  cfg.intr_alloc_flags = ESP_INTR_FLAG_LEVEL1;
  cfg.dma_buf_count = 16;
  cfg.dma_buf_len = tx ? 512 : 256;
  cfg.use_apll = false;
  cfg.tx_desc_auto_clear = true;
  if (i2s_driver_install(port, &cfg, 0, NULL) != ESP_OK) return false;

  i2s_pin_config_t pins = {};
  pins.mck_io_num = I2S_PIN_NO_CHANGE;

  if (tx) {
    pins.bck_io_num = PIN_I2S_BCLK;
    pins.ws_io_num = PIN_I2S_WS;
    pins.data_out_num = PIN_I2S_DOUT;
    pins.data_in_num = I2S_PIN_NO_CHANGE;
  } else {
    pinMode(PIN_MIC_SD, INPUT);
    pins.bck_io_num = PIN_MIC_SCK;
    pins.ws_io_num = PIN_MIC_WS;
    pins.data_out_num = I2S_PIN_NO_CHANGE;
    pins.data_in_num = PIN_MIC_SD;
  }

  i2s_set_pin(port, &pins);
  i2s_zero_dma_buffer(port);
  return true;
}

// Fungsi rekam suara dari mic dan kirim ke server sampai server balas 'S'
static bool recordAndSend(WiFiClient &cli, const int16_t *preroll = nullptr, int preroll_n = 0) {
  Serial.println(F("\n[MIC ON] Silakan bicara..."));
  if (!sleepMode) setUiMode(UI_LISTENING, 0);
  int32_t raw[256];
  int16_t pcm[256];
  size_t br;

  if (!micListening) {
    if (!i2sStart(false)) {
      Serial.println(F("[ERR] I2S RX gagal start"));
      return false;
    }
    // Buang 16 buffer awal (~256ms) agar sisa gema speaker & lonjakan DC startup INMP441 stabil
    for (int warm = 0; warm < 16; warm++) {
      i2s_read(I2S_NUM_0, raw, sizeof(raw), &br, portMAX_DELAY);
    }
  }
  micListening = false; // setelah fungsi ini selesai, driver RX ditutup

  // Jika masuk dari Mode Panggil ('K'), kirim pre-roll pemicu "sayang" lebih dulu
  if (preroll && preroll_n > 0) {
    cli.write((const uint8_t *)preroll, preroll_n * sizeof(int16_t));
  }

  bool btnReleased = !btnDown();
  btnDownSince = 0;
  while (cli.connected() && !cli.available()) {
    if (!btnDown()) {
      btnReleased = true;
      btnDownSince = 0;
    } else if (btnReleased && btnTriggered()) {
      Serial.println(F("[BTN] Tombol ditekan -> sesi dihentikan"));
      i2sStop(I2S_NUM_0);
      cli.stop();
      unsigned long t0 = millis();
      waitBtnRelease();
      if (millis() - t0 >= 2800) { autoTalkEnabled = !autoTalkEnabled; setUiMode(UI_AUTO_STATUS); }
      return false;
    }
    i2s_read(I2S_NUM_0, raw, sizeof(raw), &br, portMAX_DELAY);
    int n = br / 4;
    int32_t sumS = 0;
    for (int i = 0; i < n; i++) {
      // INMP441 data adalah 24-bit left-justified dalam 32-bit word
      // Geser 16 bit untuk mendapatkan sample 16-bit yang benar
      int16_t s = (int16_t)(raw[i] >> 16); 
      pcm[i] = s;
      sumS += s;
    }
    int16_t mean = (n > 0) ? (int16_t)(sumS / n) : 0;
    long sum = 0;
    for (int i = 0; i < n; i++) {
      int16_t ac = pcm[i] - mean;
      pcm[i] = ac;
      sum += ac < 0 ? -ac : ac;
    }
    cli.write((uint8_t*)pcm, n * 2);
    int lvl = (n > 0) ? (int)((sum / n) / 140) : 0;
    if (lvl > 10) lvl = 10;
    uiLevel = lvl; // Di-render paralel oleh uiTask (FreeRTOS) tanpa menahan DMA I2S
  }
  i2sStop(I2S_NUM_0);
  if (cli.available()) cli.read(); // Buang byte 'S'
  Serial.println(F("[MIC OFF] Memproses jawaban..."));
  if (!sleepMode) setUiMode(UI_THINKING);
  return true;
}

// Fungsi menerima flag ('L'/'N'/'S') dan memutar audio dari server
// Mengembalikan nilai true jika setelah selesai bicara harus lanjut menyalakan mic ('L')
static bool receiveAndPlay(WiFiClient &cli) {
  bool btnReleased = !btnDown();
  btnDownSince = 0;
  unsigned long tWait = millis();
  while (cli.connected() && !cli.available() && millis() - tWait < 35000) {
    if (!btnDown()) {
      btnReleased = true;
      btnDownSince = 0;
    } else if (btnReleased && btnTriggered()) {
      cli.stop();
      waitBtnRelease();
      return false;
    }
    vTaskDelay(5 / portTICK_PERIOD_MS);
  }
  if (!cli.available()) return false;

  char flag = cli.read();
  if (flag == 'Z') return false; // Standby kosong
  serverReplied = true;
  bool enterSleep = (flag == 'S');
  radioPlaying = (flag == 'R');
  if (radioPlaying) {
    setUiMode(UI_RADIO_ON, 0);
    micMutedUntil = millis() + 3600000; // mic off selama radio (1 jam maks)
    Serial.println(F("[RADIO] Mode radio aktif (mic off)"));
  }

  // Tunggu sebentar (maks 100ms) apakah ada data audio yang menyusul setelah flag 'N'/'S'
  unsigned long tAudio = millis();
  while (!cli.available() && cli.connected() && millis() - tAudio < 100) {
    vTaskDelay(5 / portTICK_PERIOD_MS);
  }
  // Jika flag 'N'/'S' dan tidak ada audio (karena user diam saat ditanya), langsung selesai!
  if ((flag == 'N' || flag == 'S') && !cli.available()) {
    if (enterSleep) {
      sleepMode = true;
      WiFi.setSleep(WIFI_PS_MIN_MODEM);
      setUiMode(UI_SLEEP);
      Serial.println(F("\n[SLEEP] Modem-Sleep AKTIF (perintah suara user)"));
    }
    return false;
  }

  // Bangunkan WiFi & OLED otomatis ketika ada data masuk dari server.py (termasuk saat Modem-Sleep)
  if (sleepMode) {
    sleepMode = false;
    Serial.println(F("[WAKE-NET] Ada data dari server.py -> bangun dari Modem-Sleep"));
    WiFi.setSleep(false);
  }
  Serial.print(F("[SPEAKER ON] AI berbicara... (Auto-Mic setelah ini: "));
  Serial.print(flag == 'L' ? F("YA") : (flag == 'S' ? F("SLEEP") : F("TIDAK")));
  Serial.println(F(")"));
  setUiMode(radioPlaying ? UI_RADIO_ON : UI_TALKING, 0);

  if (!i2sStart(true)) {
    Serial.println(F("[ERR] I2S TX gagal start"));
    return false;
  }

  // Pre-buffering awal: kumpulkan sedikit cadangan data (sampai 4KB / ~300ms) agar audio tidak tersendat
  unsigned long tPre = millis();
  while (cli.connected() && cli.available() < 4096 && millis() - tPre < 300) {
    vTaskDelay(5 / portTICK_PERIOD_MS);
  }

  btnReleased = !btnDown();
  btnDownSince = 0;
  uint8_t pb[2048];
  unsigned long lastData = millis();
  // Radio button: 1x=next, 2x=vol-, 3x=vol+, hold3s=stop
  unsigned long radioClickWindow = 0;
  int radioClickCount = 0;
  unsigned long radioPressStart = 0;
  bool radioBtnWasDown = false;
  while (true) {
    if (!radioPlaying && millis() - lastData >= 1500) break;
    if (!cli.connected()) break;

    if (radioPlaying) {
      bool btnDownNow = btnDown();
      if (btnDownNow && !radioBtnWasDown) {
        radioPressStart = millis();
        radioBtnWasDown = true;
        if (millis() - radioClickWindow < 800) radioClickCount++;
        else radioClickCount = 1;
        radioClickWindow = millis();
      } else if (!btnDownNow && radioBtnWasDown) {
        radioBtnWasDown = false;
        unsigned long held = millis() - radioPressStart;
        if (held >= 3000) {
          Serial.println(F("[RADIO-BTN] Stop (tahan 3s)"));
          cli.write('B');
          radioPlaying = false;
          break;
        }
        radioClickWindow = millis();
      }
      if (radioClickCount > 0 && !btnDownNow && millis() - radioClickWindow >= 800) {
        if (radioClickCount == 1) { Serial.println(F("[RADIO-BTN] Next channel")); cli.write('N'); }
        else if (radioClickCount == 2) { Serial.println(F("[RADIO-BTN] Vol -")); cli.write('D'); }
        else { Serial.println(F("[RADIO-BTN] Vol +")); cli.write('U'); }
        radioClickCount = 0;
      }
    } else {
      if (!btnDown()) {
        btnReleased = true;
        btnDownSince = 0;
      } else if (btnReleased && btnTriggered()) { // tekan tombol = hentikan bicara & keluar sesi
        Serial.println(F("[BTN] Tombol ditekan -> hentikan sesi"));
        i2sStop(I2S_NUM_0);
        cli.stop();
        unsigned long t0 = millis();
        waitBtnRelease();
        if (millis() - t0 >= 2800) { autoTalkEnabled = !autoTalkEnabled; setUiMode(UI_AUTO_STATUS); }
        return false;
      }
    }
    int avail = cli.available();
    if (avail > 0) {
      int n = cli.read(pb, sizeof(pb));
      if (n > 0) {
        size_t w;
        i2s_write(I2S_NUM_0, pb, n, &w, portMAX_DELAY);
        lastData = millis();
        const int16_t *samples = (const int16_t *)pb;
        int count = n / 2;
        long sum = 0;
        for (int i = 0; i < count; i += 4) {
          int16_t s = samples[i];
          sum += s < 0 ? -s : s;
        }
        int avg = (count >= 4) ? (int)(sum / (count / 4)) : 0;
        int lvl = avg / 450;
        if (lvl > 12) lvl = 12;
        uiLevel = lvl; // Di-render paralel oleh uiTask (FreeRTOS)
      }
    } else {
      if (!cli.connected()) break;
      uiLevel = 0;
      vTaskDelay(2 / portTICK_PERIOD_MS);
    }
  }
  vTaskDelay(100 / portTICK_PERIOD_MS);
  i2sStop(I2S_NUM_0);
  micMutedUntil = millis() + 500;
  if (radioPlaying) {
    radioPlaying = false;
    setUiMode(UI_STANDBY);
    Serial.println(F("[RADIO] Selesai"));
  }
  Serial.println(F("[SPEAKER OFF]"));

  if (enterSleep) {
    sleepMode = true;
    WiFi.setSleep(WIFI_PS_MIN_MODEM);
    setUiMode(UI_SLEEP);
    Serial.println(F("\n[SLEEP] Modem-Sleep AKTIF (perintah suara user: kamu tidur)"));
    return false;
  }

  return (flag == 'L');
}

// ---- Mode Panggil: pemantauan mic standby (Opsi A: gerbang RMS di ESP32) ----
#define WAKE_PREROLL_CHUNKS 20          // ~320 ms pre-roll (20 x 16ms) agar kata "sayang" utuh
static int16_t wakePreroll[WAKE_PREROLL_CHUNKS][256];
static int     wakePrerollIdx  = 0;
static bool    wakePrerollFull = false;
static int     wakeHits        = 0;     // jumlah blok berturut-turut > SPEECH_RMS

static void standbyMicStart() {
  if (micListening) return;
  if (!i2sStart(false)) return;
  int32_t raw[256];
  size_t br = 0;
  // Buang 16 buffer awal (~256ms) agar lonjakan DC startup INMP441 benar-benar stabil
  for (int warm = 0; warm < 16; warm++) {
    i2s_read(I2S_NUM_0, raw, sizeof(raw), &br, portMAX_DELAY);
  }
  wakePrerollIdx = 0;
  wakePrerollFull = false;
  wakeHits = 0;
  micListening = true;
}

// Kuras blok DMA mic (32-bit -> 16-bit tanpa DC offset), simpan ke pre-roll, kembalikan RMS jika >= 2 blok suara
static float standbyMicRms() {
  int32_t raw[256];
  float trigRms = 0.0f;
  for (int k = 0; k < 4; k++) {
    size_t br = 0;
    i2s_read(I2S_NUM_0, raw, sizeof(raw), &br, (k == 0) ? (5 / portTICK_PERIOD_MS) : 0);
    if (br < sizeof(raw)) break;
    int16_t *dst = wakePreroll[wakePrerollIdx];
    int32_t sumS = 0;
    for (int i = 0; i < 256; i++) {
      int16_t s = (int16_t)(raw[i] >> 16);
      dst[i] = s;
      sumS += s;
    }
    int16_t mean = (int16_t)(sumS / 256);
    float sumSq = 0.0f;
    for (int i = 0; i < 256; i++) {
      int16_t ac = dst[i] - mean;
      dst[i] = ac;
      sumSq += (float)ac * (float)ac;
    }
    wakePrerollIdx = (wakePrerollIdx + 1) % WAKE_PREROLL_CHUNKS;
    if (wakePrerollIdx == 0) wakePrerollFull = true;
    float rms = sqrtf(sumSq / 256.0f);
    if (rms > SPEECH_RMS) {
      wakeHits++;
      if (wakeHits >= 2 && rms > trigRms) trigRms = rms;
    } else {
      wakeHits = 0;
    }
  }
  return trigRms;
}

// Kumpulkan pre-roll (urutan kronologis) ke buffer linear; kembalikan jumlah sampel
static int wakeCollectPreroll(int16_t *out, int maxChunks) {
  int n = wakePrerollFull ? WAKE_PREROLL_CHUNKS : wakePrerollIdx;
  n = min(n, maxChunks);
  int start = (wakePrerollIdx - n + WAKE_PREROLL_CHUNKS) % WAKE_PREROLL_CHUNKS;
  for (int i = 0; i < n; i++) {
    memcpy(out + i * 256, wakePreroll[(start + i) % WAKE_PREROLL_CHUNKS], 256 * sizeof(int16_t));
  }
  return n * 256;
}

// Memulai sesi: mode 'B' (tekan tombol), 'P' (polling standby), 'K' (mode panggil "sayang"/"bymax"), 'S' (bangun tidur)
static void communicateWithServer(char mode, const int16_t *preroll = nullptr, int preroll_n = 0) {
  // mode: 'B' = button, 'W' = boot, 'P' = polling, 'K' = panggil (wakeword), 'S' = bangun dari sleep
  WiFiClient cli;
  // Gunakan timeout 3000ms untuk 'K'/'B'/'W'/'S' agar saat baru bangun dari Modem-Sleep koneksi TCP tidak timeout
  if (!cli.connect(SERVER_IP, SERVER_PORT, (mode == 'P') ? 300 : 3000)) {
    if (mode == 'B' || mode == 'K' || mode == 'S') Serial.println(F("[ERR] Tidak bisa konek ke server"));
    setUiMode(sleepMode ? UI_SLEEP : UI_STANDBY);
    lastPoll = millis();
    return;
  }
  cli.setNoDelay(true);
  cli.write((uint8_t)mode);

  if (mode == 'B') {
    // Langsung rekam begitu tombol ditekan, tanpa tunggu lepas tombol
    if (!recordAndSend(cli)) { cli.stop(); lastPoll = millis(); return; }
  } else if (mode == 'K' || mode == 'S') {
    // Mode Panggil / Bangun Sleep: kirim pre-roll hasil pantau RMS sebagai awal audio
    if (!recordAndSend(cli, preroll, preroll_n)) { cli.stop(); lastPoll = millis(); return; }
  }

  // Loop percakapan: selama AI mengirim flag 'L' (bertanya), mic otomatis menyala terus!
  while (cli.connected() || cli.available()) {
    bool shouldListenNext = receiveAndPlay(cli);
    if (shouldListenNext && cli.connected()) {
      if (!recordAndSend(cli)) break;
    } else {
      break;
    }
  }

  cli.stop();
  // Kembalikan state UI & Modem-Sleep seusai interaksi dengan server
  if (sleepMode) {
    WiFi.setSleep(WIFI_PS_MIN_MODEM);
    setUiMode(UI_SLEEP);
  } else {
    setUiMode(UI_STANDBY);
  }
  lastPoll = millis(); // Reset timer standby
}

// ---- Task aplikasi (FreeRTOS): satu-satunya pemilik WiFiClient, I2S, tombol ----
static void wifiConnect() {
  WiFi.mode(WIFI_STA);
  WiFi.setSleep(false);
  WiFi.begin(WIFI_SSID, WIFI_PASS);
  Serial.print(F("\nKonek WiFi"));
  while (WiFi.status() != WL_CONNECTED) {
    vTaskDelay(100 / portTICK_PERIOD_MS);
    Serial.print('.');
  }
  // Tunggu animasi bangun tidur selesai bila WiFi konek lebih cepat dari 4.2 detik
  while (uiMode == UI_BOOT_WAKE) vTaskDelay(50 / portTICK_PERIOD_MS);
  Serial.print(F("\nIP ESP32: "));
  Serial.println(WiFi.localIP());
  Serial.println(F("Siap! 1x klik = bicara, tahan 3 dtk = Auto-Prompt ON/OFF, tahan 5 dtk = Sleep ON/OFF."));
}

static void wakeFromSleep() {
  if (!sleepMode) return;
  sleepMode = false;
  WiFi.setSleep(false);
}

// Aksi tombol. Return true bila siklus sudah terpakai (lewati langkah berikutnya).
static bool handleButton() {
  int act = pollBtnAction();
  if (act == 10) {
    setUiMode(UI_HOLD_3S);
    return true;
  }
  if (act == 30) {
    setUiMode(UI_HOLD_3S);
    return true;
  }
  if (act == 3) {
    autoTalkEnabled = !autoTalkEnabled;
    setUiMode(UI_AUTO_STATUS);
    Serial.println(autoTalkEnabled
      ? F("\n[AUTO] Auto-Prompt 1 menit: AKTIF (tahan 3 detik)")
      : F("\n[AUTO] Auto-Prompt 1 menit: MATI (tahan 3 detik)"));
    lastPoll = millis();
    return true;
  }
  if (act == 5) {
    sleepMode = !sleepMode;
    if (sleepMode) {
      WiFi.setSleep(WIFI_PS_MIN_MODEM);
      setUiMode(UI_SLEEP);
      Serial.println(F("\n[SLEEP] Modem-Sleep AKTIF (tahan 5 detik): layar tidur, bangun otomatis saat ada suara mic atau server.py"));
    } else {
      WiFi.setSleep(false);
      setUiMode(UI_BOOT_WAKE); // animasi bangun tidur saat dibangunkan manual
      Serial.println(F("\n[SLEEP] Modem-Sleep NONAKTIF (tahan 5 detik): kembali aktif penuh!"));
    }
    lastPoll = millis();
    return true;
  }
  // Tombol dilepas tanpa aksi (ketukan ganda/noise) -> tutup layar progres
  if (!btnDown() && act == 0 && uiMode == UI_HOLD_3S) {
    setUiMode(sleepMode ? UI_SLEEP : UI_STANDBY);
  }
  // Selama tombol ditahan jangan jalankan mic wake / polling agar timer tahan 3s/5s akurat
  if (btnDown()) {
    vTaskDelay(10 / portTICK_PERIOD_MS);
    return true;
  }
  bool serialTrig = false;
  if (Serial.available()) {
    while (Serial.available()) {
      char c = Serial.read();
      if (c == 'b' || c == 'B' || c == '\n' || c == '\r' || c == ' ') {
        serialTrig = true;
      }
    }
  }
  if (act == 1 || serialTrig) {
    wakeFromSleep();
    communicateWithServer('B');
    waitBtnRelease();
    Serial.println(F("Standby..."));
    return true;
  }
  return false;
}

// Mode Panggil: pantau mic (aktif juga saat Sleep agar bisa bangun karena panggilan)
static void handleWakeMic() {
  if (millis() < micMutedUntil) return;
  standbyMicStart();
  if (!micListening) return;
  float rms = standbyMicRms();
  if (rms <= SPEECH_RMS) return;

  static int16_t prerollBuf[WAKE_PREROLL_CHUNKS * 256];
  int n = wakeCollectPreroll(prerollBuf, WAKE_PREROLL_CHUNKS);
  Serial.printf("[WAKE] RMS=%.0f pre-roll=%d sampel, kirim '%c' (sleepMode=%d)\n", rms, n, sleepMode ? 'S' : 'K', sleepMode);
  serverReplied = false;
  communicateWithServer(sleepMode ? 'S' : 'K', prerollBuf, n);

  // Hanya nyalakan kembali Auto-Prompt 1 menit jika server mengonfirmasi kata panggil sah
  if (serverReplied && !autoTalkEnabled && !sleepMode) {
    autoTalkEnabled = true;
    Serial.println(F("[WAKE] Auto-Prompt 1 menit kembali ON karena dipanggil."));
  }
  Serial.println(sleepMode ? F("Tetap Sleep (bukan panggilan)...") : F("Standby..."));
  lastPoll = millis();
}

static void appTask(void *pv) {
  wifiConnect();
  communicateWithServer('W'); // Meminta server memutar ucapan selamat datang
  lastPoll = millis();
  for (;;) {
    if (WiFi.status() != WL_CONNECTED) {
      WiFi.reconnect();
      vTaskDelay(200 / portTICK_PERIOD_MS);
      continue;
    }
    if (handleButton()) continue;
    handleWakeMic();
    // Cek server tiap 1 detik apakah AI mau ngomong otomatis (hanya jika autoTalkEnabled dan TIDAK sedang sleep)
    if (autoTalkEnabled && !sleepMode && millis() - lastPoll >= 1000) {
      lastPoll = millis();
      communicateWithServer('P');
    }
    vTaskDelay(15 / portTICK_PERIOD_MS);
  }
}

void setup() {
  Serial.begin(115200);
  pinMode(PIN_BTN, INPUT_PULLUP);
  delay(50);
  // Kalibrasi status diam tombol (aktif-LOW / aktif-HIGH) dengan 10 sampel stabil
  int highCount = 0;
  for (int i = 0; i < 10; i++) {
    if (digitalRead(PIN_BTN) == HIGH) highCount++;
    delay(5);
  }
  btnIdleState = (highCount >= 5) ? HIGH : LOW;
  Serial.printf("[BTN] Level idle tombol terkalibrasi: %s\n", btnIdleState == HIGH ? "HIGH (aktif-LOW)" : "LOW (aktif-HIGH)");

  uiInit(PIN_OLED_SDA, PIN_OLED_SCL, OLED_ADDR);
  xTaskCreatePinnedToCore(uiTask,  "OLED_UI", 4096, NULL, 1, NULL, 0); // render OLED di Core 0 (prioritas 1)
  xTaskCreatePinnedToCore(appTask, "APP",     12288, NULL, 2, NULL, 1); // tombol, mic, server, audio di Core 1 (prioritas 2)
}

void loop() {
  vTaskDelete(NULL); // semua kerja ada di task FreeRTOS
}

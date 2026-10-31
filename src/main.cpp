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

#define WIFI_SSID   "Lantai 2"
#define WIFI_PASS   "passwordsalah"
#define SERVER_IP   "10.20.30.4"   // IP PC homelab ATAU pc laptop yang di runing server.py
#define SERVER_PORT 8765

#define PIN_BTN      4              // tombol push (aktif LOW)

// OLED 0.96" SSD1306 (I2C)
#define PIN_OLED_SDA 21
#define PIN_OLED_SCL 22
#define OLED_ADDR    0x3C
Adafruit_SSD1306 display(128, 64, &Wire, -1);

// Speaker (MAX98357A)
#define PIN_I2S_BCLK 26
#define PIN_I2S_WS   25
#define PIN_I2S_DOUT 27

// Mic (INMP441)
#define PIN_MIC_SCK  33
#define PIN_MIC_WS   32
#define PIN_MIC_SD   35

#define SAMPLE_RATE  16000

unsigned long lastPoll = 0;

// ---- Glue untuk emosional.h (animasi standby berbasis state) ----
enum { STATE_IDLE, STATE_SCENE };
uint8_t currentState = STATE_IDLE;
unsigned long stateDuration = 0;
unsigned long lastStateChange = 0;

struct Note { uint16_t f; uint16_t ms; };
// ponytail: melodi emosional.h masih no-op, add when buzzer pasif terpasang di pin bebas (tone())
static void playSequence(const Note *, int) {}
#include "emosional.h"

// Wajah saat merekam (dengar) / berbicara — digambar sekali di awal agar tidak mengganggu timing I2S
static void faceDraw(bool talking) {
  display.clearDisplay();
  if (talking) {
    display.drawCircle(40, 26, 12, SSD1306_WHITE);
    display.drawCircle(88, 26, 12, SSD1306_WHITE);
    display.fillRoundRect(48, 44, 32, 12, 3, SSD1306_WHITE);
  } else {
    display.drawCircle(64, 32, 16, SSD1306_WHITE);
    display.drawCircle(64, 32, 10, SSD1306_WHITE);
  }
  display.display();
}

// Animasi emosional non-blocking saat standby
static unsigned long lastScene = 0;
static void sceneTick() {
  if (millis() - sceneStart >= stateDuration) startScene();  // ganti adegan saat durasi habis
  if (millis() - lastScene < 70) return;
  lastScene = millis();
  sceneDraw();
}

// Deteksi tombol tahan-noise & auto-kalibrasi level idle (agar tidak pernah stuck / putus sendiri)
static uint8_t btnIdle = HIGH;
static unsigned long btnDownSince = 0;

static bool btnDown() {
  return digitalRead(PIN_BTN) != btnIdle;
}

static bool btnTriggered() {
  if (!btnDown()) {
    btnDownSince = 0;
    return false;
  }
  if (btnDownSince == 0) btnDownSince = millis();
  return (millis() - btnDownSince >= 80); // wajib ditekan stabil >= 80ms
}

static void waitBtnRelease() {
  unsigned long t0 = millis();
  while (btnDown()) {
    sceneTick();
    if (millis() - t0 > 1500) {
      btnIdle = digitalRead(PIN_BTN); // bila kabel/tombol nyangkut, kalibrasi ulang supaya tidak stuck
      break;
    }
    delay(10);
  }
  delay(120); // debounce lepas tombol
  btnDownSince = 0;
}

static void i2sStop(i2s_port_t port) {
  i2s_zero_dma_buffer(port);
  i2s_driver_uninstall(port);
}

// tx = true: keluarkan suara ke amplifier (I2S_NUM_0); tx = false: baca mic (I2S_NUM_1)
static bool i2sStart(bool tx) {
  i2s_port_t port = I2S_NUM_0;
  i2s_config_t cfg = {};
  cfg.mode = (i2s_mode_t)(I2S_MODE_MASTER | (tx ? I2S_MODE_TX : I2S_MODE_RX));
  cfg.sample_rate = SAMPLE_RATE;
  cfg.bits_per_sample = tx ? I2S_BITS_PER_SAMPLE_16BIT : I2S_BITS_PER_SAMPLE_32BIT;
  // cfg.channel_format = tx ? I2S_CHANNEL_FMT_RIGHT_LEFT : I2S_CHANNEL_FMT_ONLY_LEFT;
  cfg.channel_format = tx ? I2S_CHANNEL_FMT_RIGHT_LEFT : I2S_CHANNEL_FMT_ONLY_RIGHT;
  cfg.communication_format = I2S_COMM_FORMAT_STAND_I2S;
  cfg.intr_alloc_flags = ESP_INTR_FLAG_LEVEL1;
  cfg.dma_buf_count = 8;
  cfg.dma_buf_len = 256;
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
static bool recordAndSend(WiFiClient &cli) {
  Serial.println(F("\n[MIC ON] Silakan bicara..."));
  faceDraw(false);
  if (!i2sStart(false)) {
    Serial.println(F("[ERR] I2S RX gagal start"));
    return false;
  }
  bool btnReleased = !btnDown();
  btnDownSince = 0;
  int32_t raw[256];
  int16_t pcm[256];
  size_t br;
  // Buang 4 buffer awal (~64ms) agar transisi DMA/DC-offset mic stabil
  for (int warm = 0; warm < 4; warm++) {
    i2s_read(I2S_NUM_0, raw, sizeof(raw), &br, portMAX_DELAY); 
    static uint16_t dbg; if (++dbg % 50 == 0) Serial.println(raw[0]);
  }
  while (cli.connected() && !cli.available()) {
    if (!btnDown()) {
      btnReleased = true;
      btnDownSince = 0;
    } else if (btnReleased && btnTriggered()) {
      Serial.println(F("[BTN] Tombol ditekan -> sesi dihentikan"));
      i2sStop(I2S_NUM_0);
      cli.stop();
      waitBtnRelease();
      return false;
    }
    i2s_read(I2S_NUM_0, raw, sizeof(raw), &br, portMAX_DELAY); 
    int n = br / 4;
    for (int i = 0; i < n; i++) pcm[i] = raw[i] >> 16;
    cli.write((uint8_t*)pcm, n * 2);
  }
  i2sStop(I2S_NUM_0);
  if (cli.available()) cli.read(); // Buang byte 'S'
  Serial.println(F("[MIC OFF] Memproses jawaban..."));
  return true;
}

// Fungsi menerima flag ('L'/'N') dan memutar audio dari server
// Mengembalikan nilai true jika setelah selesai bicara harus lanjut menyalakan mic ('L')
static bool receiveAndPlay(WiFiClient &cli) {
  unsigned long tWait = millis();
  while (cli.connected() && !cli.available() && millis() - tWait < 35000) {
    sceneTick();
    delay(5);
  }
  if (!cli.available()) return false;

  char flag = cli.read();
  if (flag == 'Z') return false; // Standby kosong

  // Tunggu sebentar (maks 100ms) apakah ada data audio yang menyusul setelah flag 'N'
  unsigned long tAudio = millis();
  while (!cli.available() && cli.connected() && millis() - tAudio < 100) {
    delay(5);
  }
  // Jika flag 'N' dan tidak ada audio (karena user diam saat ditanya), langsung selesai!
  if (flag == 'N' && !cli.available()) return false;

  Serial.print(F("[SPEAKER ON] AI berbicara... (Auto-Mic setelah ini: "));
  Serial.print(flag == 'L' ? F("YA") : F("TIDAK"));
  Serial.println(F(")"));
  faceDraw(true);

  if (!i2sStart(true)) {
    Serial.println(F("[ERR] I2S TX gagal start"));
    return false;
  }

  bool btnReleased = !btnDown();
  btnDownSince = 0;
  uint8_t pb[1024];
  unsigned long lastData = millis();
  while (millis() - lastData < 800) { // Dipercepat dari 1200ms ke 800ms
    if (!btnDown()) {
      btnReleased = true;
      btnDownSince = 0;
    } else if (btnReleased && btnTriggered()) { // tekan tombol = hentikan bicara & keluar sesi
      Serial.println(F("[BTN] Tombol ditekan -> hentikan sesi"));
      i2sStop(I2S_NUM_0);
      cli.stop();
      waitBtnRelease();
      return false;
    }
    int avail = cli.available();
    if (avail > 0) {
      int n = cli.read(pb, sizeof(pb));
      if (n > 0) {
        size_t w;
        i2s_write(I2S_NUM_0, pb, n, &w, portMAX_DELAY);
        lastData = millis();
      }
    } else {
      if (!cli.connected()) break;
      delay(2);
    }
  }
  delay(100);
  i2sStop(I2S_NUM_0);
  Serial.println(F("[SPEAKER OFF]"));

  return (flag == 'L');
}

// Memulai sesi: mode 'B' (tekan tombol) atau 'P' (polling standby otomatis)
static void communicateWithServer(char mode) {
  WiFiClient cli;
  if (!cli.connect(SERVER_IP, SERVER_PORT, mode == 'P' ? 300 : 3000)) {
    if (mode == 'B') Serial.println(F("[ERR] Tidak bisa konek ke server"));
    lastPoll = millis();
    return;
  }
  cli.setNoDelay(true);
  cli.write((uint8_t)mode);

  if (mode == 'B') {
    // Langsung rekam begitu tombol ditekan (persis Voice_AI.ino), tanpa tunggu lepas tombol
    if (!recordAndSend(cli)) { cli.stop(); lastPoll = millis(); return; }
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
  lastPoll = millis(); // Reset timer standby
}

void setup() {
  Serial.begin(115200);
  pinMode(PIN_BTN, INPUT_PULLUP);
  delay(20);
  btnIdle = digitalRead(PIN_BTN); // kalibrasi status diam tombol (aktif-LOW / aktif-HIGH)
  Wire.begin(PIN_OLED_SDA, PIN_OLED_SCL);
  Wire.setClock(400000); // Fast I2C 400kHz agar update OLED cepat & tidak menghambat audio
  if (!display.begin(SSD1306_SWITCHCAPVCC, OLED_ADDR)) {
    Serial.println(F("[ERR] OLED tidak terdeteksi, lanjut tanpa layar"));
  }
  startScene();  // mulai animasi emosional standby
  sceneDraw();
  WiFi.mode(WIFI_STA);
  WiFi.setSleep(false);
  WiFi.begin(WIFI_SSID, WIFI_PASS);
  Serial.print(F("\nKonek WiFi"));
  while (WiFi.status() != WL_CONNECTED) { sceneTick(); delay(70); Serial.print('.'); }
  Serial.print(F("\nIP ESP32: "));
  Serial.println(WiFi.localIP());
  Serial.println(F("Siap! Tekan tombol untuk bicara, atau tunggu dia menyapamu sendiri."));
  communicateWithServer('W'); // Meminta server memutar ucapan selamat datang
  lastPoll = millis();
}

void loop() {
  if (WiFi.status() != WL_CONNECTED) {
    sceneTick();
    WiFi.reconnect();
    delay(200);
    return;
  }

  // 1. Jika tombol ditekan atau ada input Serial -> bicara manual
  if (btnTriggered() || Serial.available()) {
    while (Serial.available()) Serial.read();
    communicateWithServer('B');
    waitBtnRelease();
    Serial.println(F("Standby..."));
  }

  // 2. Saat standby -> animasi emosional, sekaligus cek ke server tiap 1 detik
  //    apakah AI mau ngomong (tiap 30 dtk / jam pas)
  sceneTick();
  if (millis() - lastPoll >= 1000) {
    lastPoll = millis();
    communicateWithServer('P');
  }

  delay(20);
}

/*
 * Voice AI ESP32 DevKit V1: mic (INMP441) + speaker (MAX98357A) -> server homelab -> Ollama
 * Fitur:
 * - Tekan tombol BOOT / Serial untuk mulai bicara
 * - Standby: tiap 30 detik & tiap pergantian jam (xx:00) AI bicara sendiri
 * - Auto-Mic: jika AI selesai bertanya, mic otomatis menyala untuk mendengar jawabanmu
 */
#include <WiFi.h>
#include <driver/i2s.h>

#define WIFI_SSID   "Wifi Kamu"
#define WIFI_PASS   "Password Wifi Kamu"
#define SERVER_IP   "192.168.1.28"   // IP PC homelab ATAU pc laptop yang di runing server.py
#define SERVER_PORT 8765

#define PIN_BTN      4              // tombol push (aktif LOW)

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

static void i2sStop() {
  i2s_zero_dma_buffer(I2S_NUM_0);
  i2s_driver_uninstall(I2S_NUM_0);
}

// tx = true: keluarkan suara ke amplifier; tx = false: baca mic
static bool i2sStart(bool tx) {
  i2s_config_t cfg = {};
  cfg.mode = (i2s_mode_t)(I2S_MODE_MASTER | (tx ? I2S_MODE_TX : I2S_MODE_RX));
  cfg.sample_rate = SAMPLE_RATE;
  cfg.bits_per_sample = tx ? I2S_BITS_PER_SAMPLE_16BIT : I2S_BITS_PER_SAMPLE_32BIT;
  cfg.channel_format = tx ? I2S_CHANNEL_FMT_RIGHT_LEFT : I2S_CHANNEL_FMT_ONLY_LEFT;
  cfg.communication_format = I2S_COMM_FORMAT_STAND_I2S;
  cfg.intr_alloc_flags = ESP_INTR_FLAG_LEVEL1;
  cfg.dma_buf_count = 8;
  cfg.dma_buf_len = 256;
  cfg.use_apll = false;
  cfg.tx_desc_auto_clear = true;
  if (i2s_driver_install(I2S_NUM_0, &cfg, 0, NULL) != ESP_OK) return false;

  i2s_pin_config_t pins = {};
  pins.mck_io_num = I2S_PIN_NO_CHANGE;

  if (tx) {
    pins.bck_io_num = PIN_I2S_BCLK;
    pins.ws_io_num = PIN_I2S_WS;
    pins.data_out_num = PIN_I2S_DOUT;
    pins.data_in_num = I2S_PIN_NO_CHANGE;
  } else {
    pins.bck_io_num = PIN_MIC_SCK;
    pins.ws_io_num = PIN_MIC_WS;
    pins.data_out_num = I2S_PIN_NO_CHANGE;
    pins.data_in_num = PIN_MIC_SD;
  }

  i2s_set_pin(I2S_NUM_0, &pins);
  return true;
}

// Fungsi rekam suara dari mic dan kirim ke server sampai server balas 'S'
static bool recordAndSend(WiFiClient &cli) {
  Serial.println(F("\n[MIC ON] Silakan bicara..."));
  if (!i2sStart(false)) {
    Serial.println(F("[ERR] I2S RX gagal start"));
    return false;
  }
  int32_t raw[256];
  int16_t pcm[256];
  size_t br;
  while (cli.connected() && !cli.available()) {
    i2s_read(I2S_NUM_0, raw, sizeof(raw), &br, portMAX_DELAY);
    int n = br / 4;
    for (int i = 0; i < n; i++) pcm[i] = raw[i] >> 16;
    cli.write((uint8_t*)pcm, n * 2);
  }
  i2sStop();
  if (cli.available()) cli.read(); // Buang byte 'S'
  Serial.println(F("[MIC OFF] Memproses jawaban..."));
  return true;
}

// Fungsi menerima flag ('L'/'N') dan memutar audio dari server
// Mengembalikan nilai true jika setelah selesai bicara harus lanjut menyalakan mic ('L')
static bool receiveAndPlay(WiFiClient &cli) {
  unsigned long tWait = millis();
  while (cli.connected() && !cli.available() && millis() - tWait < 35000) {
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

  if (!i2sStart(true)) {
    Serial.println(F("[ERR] I2S TX gagal start"));
    return false;
  }

  uint8_t pb[1024];
  unsigned long lastData = millis();
  while (millis() - lastData < 800) { // Dipercepat dari 1200ms ke 800ms
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
  i2sStop();
  Serial.println(F("[SPEAKER OFF]"));

  return (flag == 'L');
}

// Memulai sesi: mode 'B' (tekan tombol) atau 'P' (polling standby otomatis)
static void communicateWithServer(char mode) {
  WiFiClient cli;
  if (!cli.connect(SERVER_IP, SERVER_PORT)) {
    if (mode == 'B') Serial.println(F("[ERR] Tidak bisa konek ke server"));
    return;
  }
  cli.setNoDelay(true);
  cli.write((uint8_t)mode);

  if (mode == 'B') {
    // User menekan tombol -> rekam dulu, lalu putar balasan AI
    if (!recordAndSend(cli)) { cli.stop(); return; }
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
  WiFi.mode(WIFI_STA);
  WiFi.setSleep(false);
  WiFi.begin(WIFI_SSID, WIFI_PASS);
  Serial.print(F("\nKonek WiFi"));
  while (WiFi.status() != WL_CONNECTED) { delay(300); Serial.print('.'); }
  Serial.print(F("\nIP ESP32: "));
  Serial.println(WiFi.localIP());
  Serial.println(F("Siap! Tekan tombol untuk bicara, atau tunggu dia menyapamu sendiri."));
  communicateWithServer('W'); // Meminta server memutar ucapan selamat datang
  lastPoll = millis();
}

void loop() {
  if (WiFi.status() != WL_CONNECTED) {
    WiFi.reconnect();
    delay(2000);
    return;
  }

  // 1. Jika tombol ditekan atau ada input Serial -> bicara manual
  if (digitalRead(PIN_BTN) == LOW || Serial.available()) {
    while (Serial.available()) Serial.read();
    communicateWithServer('B');
    while (digitalRead(PIN_BTN) == LOW) delay(10);
    Serial.println(F("Standby..."));
  }

  // 2. Saat standby -> cek ke server tiap 1 detik apakah AI mau ngomong (tiap 30 dtk / jam pas)
  if (millis() - lastPoll >= 1000) {
    lastPoll = millis();
    communicateWithServer('P');
  }

  delay(20);
}

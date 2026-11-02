#pragma once
// ===================== ANIMASI EMOSIONAL STANDBY =====================
// Layar penuh, non-blocking (berbasis waktu millis), tanpa gambar bitmap.
// Berisi: driver SSD1306, scene emosional standby, faceDraw lip-sync, dan FreeRTOS uiTask.

#include <Arduino.h>
#include <Wire.h>
#include <Adafruit_GFX.h>
#include <Adafruit_SSD1306.h>
#include <math.h>

#define C_W SSD1306_WHITE
#define C_B SSD1306_BLACK

Adafruit_SSD1306 display(128, 64, &Wire, -1, 800000UL, 800000UL);

// Status eksternal dari main.cpp
extern volatile bool sleepMode;
extern volatile bool autoTalkEnabled;

// ---- FreeRTOS UI State & Mode ----
enum UiMode : uint8_t {
  UI_BOOT_WAKE = 0,
  UI_STANDBY,
  UI_LISTENING,
  UI_THINKING,
  UI_TALKING,
  UI_SLEEP,
  UI_AUTO_STATUS,
  UI_HOLD_3S,
  UI_RADIO_ON
};

static volatile UiMode uiMode = UI_BOOT_WAKE;
static volatile int    uiLevel = 0;
static unsigned long   uiStateMs = 0;

static void setUiMode(UiMode m, int lvl = 0) {
  uiLevel = lvl;
  if (uiMode != m) {
    uiStateMs = millis();
    uiMode = m;
  }
}

// ---- Glue Animasi Emosional Standby ----
enum { STATE_IDLE, STATE_SCENE };
static uint8_t currentState = STATE_IDLE;
static unsigned long stateDuration = 0;
static unsigned long lastStateChange = 0;

struct Note { uint16_t f; uint16_t ms; };
static void playSequence(const Note *, int) {} // ponytail: melodi no-op sampai ada buzzer di pin bebas

enum {
  SC_ANJING, SC_PUSING, SC_KAGET, SC_BERSIN, SC_JOGET, SC_TAKUT,
  SC_MANJA, SC_SEDIH, SC_MARAH, SC_NGANTUK, SC_KEDIP, SC_MAKAN, SC_KETAWA, SC_MIKIR,
  SC_COUNT
};

const uint16_t sceneDur[SC_COUNT] = {
  9000, 5000, 3000, 3600, 6000, 4000,
  5500, 5500, 4500, 6000, 4500, 5500, 4500, 5000
};  // lama tiap adegan (ms)
uint8_t sceneId = 255;
uint8_t sceneStep = 0;          // penanda kejadian tengah adegan (bunyi susulan)
unsigned long sceneStart = 0;

// true sekali saja saat adegan melewati waktu "at"
static bool scOnce(unsigned long t, unsigned long at) {
  if (sceneStep == 0 && t >= at) { sceneStep = 1; return true; }
  return false;
}

// ---------- potongan gambar ----------
// mata pusing: lingkaran putih + spiral hitam berputar
static void scSpiral(int cx, int cy, int r, unsigned long t) {
  display.fillCircle(cx, cy, r, C_W);
  float a0 = t / 120.0f;
  int px = cx, py = cy;
  for (int i = 1; i <= 30; i++) {
    float a = a0 + i * 0.5f;
    float rr = (r - 1) * i / 30.0f;
    int x = cx + (int)(cosf(a) * rr);
    int y = cy + (int)(sinf(a) * rr);
    display.drawLine(px, py, x, y, C_B);
    px = x; py = y;
  }
}

// 3 bintang berputar di atas kepala
static void scStars(int cx, int cy, int rx, unsigned long t) {
  for (int i = 0; i < 3; i++) {
    float a = t / 200.0f + i * 2.094f;
    int x = cx + (int)(cosf(a) * rx);
    int y = cy + (int)(sinf(a) * 3);
    display.drawLine(x - 2, y, x + 2, y, C_W);
    display.drawLine(x, y - 2, x, y + 2, C_W);
  }
}

// kotak yang ikut dicerminkan sesuai arah s (+1 kanan, -1 kiri)
static void scRect(int cx, int s, int dx, int y, int w, int h, uint16_t c) {
  display.fillRect(s > 0 ? cx + dx : cx - dx - w + 1, y, w, h, c);
}

// anjing lari (cx = tengah badan)
static void scDog(int cx, int s, unsigned long t) {
  int f = (t / 110) & 1;
  int la = f ? 9 : 5, lb = f ? 5 : 9;               // kaki bergantian
  scRect(cx, s, -13, 53, 3, la, C_W);
  scRect(cx, s, -8, 53, 3, lb, C_W);
  scRect(cx, s, 1, 53, 3, lb, C_W);
  scRect(cx, s, 6, 53, 3, la, C_W);
  display.fillRoundRect(s > 0 ? cx - 14 : cx - 8, 42, 23, 11, 3, C_W);   // badan
  display.fillCircle(cx + s * 12, 40, 6, C_W);                              // kepala
  display.fillTriangle(cx + s * 6, 37, cx + s * 9, 29, cx + s * 11, 37, C_W);  // telinga
  scRect(cx, s, 16, 39, 6, 4, C_W);                                         // moncong
  scRect(cx, s, 20, 39, 2, 2, C_B);                                         // hidung
  scRect(cx, s, 13, 37, 2, 2, C_B);                                         // mata
  if (f) scRect(cx, s, 17, 43, 2, 3, C_W);                                  // lidah
  int w = (int)(sinf(t / 55.0f) * 3);                                       // ekor goyang
  display.drawLine(cx - s * 14, 44, cx - s * 19, 38 + w, C_W);
  display.drawLine(cx - s * 14, 45, cx - s * 19, 39 + w, C_W);
}

// ---------- adegan ----------
// ANJING: main kejar bola, Lala ikut melirik, lama-lama pusing
static void scAnjing(unsigned long t) {
  float a = t / 650.0f;
  int cx = 64 + (int)(24 * sinf(a));
  int s = (cosf(a) >= 0) ? 1 : -1;
  int bx = 64 + (int)(52 * sinf(a + 0.6f));
  int by = 57 - (int)(fabsf(sinf(t / 150.0f)) * 20);
  if (t < 5800) {
    int dx = (bx - 64) / 9;                          // mata mengikuti bola
    display.fillRoundRect(29 + dx, 3, 22, 18, 6, C_W);
    display.fillRoundRect(77 + dx, 3, 22, 18, 6, C_W);
  } else {
    if (scOnce(t, 5800)) {
      const Note dz[] = {{700, 70}, {500, 70}, {800, 70}, {450, 70}, {900, 70}, {380, 120}};
      playSequence(dz, 6);
    }
    scSpiral(40, 12, 9, t);
    scSpiral(88, 12, 9, t);
    scStars(64, 25, 40, t);
  }
  display.fillCircle(bx, by, 4, C_W);
  display.fillCircle(bx - 1, by - 1, 1, C_B);
  scDog(cx, s, t);
}

// PUSING: mata spiral, bintang, mulut mual bergelombang
static void scPusing(unsigned long t) {
  int sx = (int)(sinf(t / 220.0f) * 6);
  scSpiral(36 + sx, 32, 14, t);
  scSpiral(92 + sx, 32, 14, t);
  scStars(64 + sx, 8, 44, t);
  for (int x = 50; x < 80; x++)
    display.drawPixel(x + sx, 56 + (int)(sinf(x / 3.0f + t / 90.0f) * 2), C_W);
}

// KAGET: mata membesar, pupil mengecil, tanda seru, badan bergetar
static void scKaget(unsigned long t) {
  int j = ((t / 45) & 1) ? 1 : -1;
  int k = t < 160 ? (int)(t / 20) : 8;
  int w = 28 + k, h = 32 + k * 5 / 4;
  display.fillRoundRect(34 - w / 2 + j, 34 - h / 2, w, h, 12, C_W);
  display.fillRoundRect(94 - w / 2 + j, 34 - h / 2, w, h, 12, C_W);
  if (t >= 160) {
    display.fillCircle(34 + j, 34, 3, C_B);
    display.fillCircle(94 + j, 34, 3, C_B);
    display.fillRect(61 + j, 14, 6, 22, C_W);
    display.fillRect(61 + j, 41, 6, 6, C_W);
  }
}

// BERSIN: ha...ha... (mata menyipit, mulut membuka) -> ACHOO! -> lega
static void scBersin(unsigned long t) {
  if (t < 1700) {
    int p = (int)(t * 100 / 1700);
    int h = 32 - p * 22 / 100;
    int cy = 32 - p * 8 / 100;
    display.fillRoundRect(22, cy - h / 2, 28, h, 7, C_W);
    display.fillRoundRect(78, cy - h / 2, 28, h, 7, C_W);
    display.fillCircle(64, 54, 1 + p * 5 / 100, C_W);
  } else if (t < 3000) {
    if (scOnce(t, 1700)) {
      const Note ch[] = {{3200, 40}, {0, 10}, {1800, 70}, {900, 160}};
      playSequence(ch, 4);
    }
    int j = random(-3, 4);
    for (int o = 0; o < 2; o++) {                    // mata > <
      display.drawLine(24 + j, 22 + o, 46 + j, 32 + o, C_W);
      display.drawLine(46 + j, 32 + o, 24 + j, 42 + o, C_W);
      display.drawLine(104 + j, 22 + o, 82 + j, 32 + o, C_W);
      display.drawLine(82 + j, 32 + o, 104 + j, 42 + o, C_W);
    }
    display.fillCircle(64 + j, 50, 8, C_W);          // mulut lebar
    int d = (int)((t - 1700) / 22);
    for (int i = 0; i < 6; i++) {                    // percikan
      float a = 0.3f + i * 0.5f;
      float r = d + i * 4;
      display.fillCircle(64 + (int)(cosf(a) * r), 50 + (int)(sinf(a) * r), 2, C_W);
    }
  } else {
    int h = 4 + (int)((t - 3000) / 20);              // mata terbuka pelan
    if (h > 32) h = 32;
    display.fillRoundRect(22, 32 - h / 2, 28, h, 7, C_W);
    display.fillRoundRect(78, 32 - h / 2, 28, h, 7, C_W);
  }
}

// JOGET: mata ^ ^ senang, goyang, senyum, nada melayang
static void scJoget(unsigned long t) {
  int bx = (int)(sinf(t / 260.0f) * 8);
  int by = 30 + (int)(sinf(t / 130.0f) * 5);
  for (int o = 0; o < 3; o++) {
    display.drawLine(24 + bx, by + 6 + o, 36 + bx, by - 6 + o, C_W);
    display.drawLine(36 + bx, by - 6 + o, 48 + bx, by + 6 + o, C_W);
    display.drawLine(80 + bx, by + 6 + o, 92 + bx, by - 6 + o, C_W);
    display.drawLine(92 + bx, by - 6 + o, 104 + bx, by + 6 + o, C_W);
  }
  for (int o = 0; o < 2; o++) {
    display.drawLine(54 + bx, by + 14 + o, 58 + bx, by + 19 + o, C_W);
    display.drawLine(58 + bx, by + 19 + o, 70 + bx, by + 19 + o, C_W);
    display.drawLine(70 + bx, by + 19 + o, 74 + bx, by + 14 + o, C_W);
  }
  const int nx[4] = {4, 14, 114, 124};
  for (int i = 0; i < 4; i++) {
    int y = 62 - (int)((t / 18 + i * 16) % 64);
    int x = nx[i] + (int)(sinf(t / 200.0f + i) * 3);
    display.fillCircle(x, y, 2, C_W);
    display.drawLine(x + 2, y, x + 2, y - 7, C_W);
    display.drawLine(x + 2, y - 7, x + 5, y - 5, C_W);
  }
}

// TAKUT: mata gemetar, pupil melirik, alis cemas, keringat dingin
static void scTakut(unsigned long t) {
  int jx = random(-2, 3), jy = random(-1, 2);
  int p = ((t / 170) & 1) ? 3 : -3;
  display.fillRoundRect(24 + jx, 20 + jy, 24, 28, 10, C_W);
  display.fillRoundRect(80 + jx, 20 + jy, 24, 28, 10, C_W);
  display.fillCircle(36 + p + jx, 34 + jy, 4, C_B);
  display.fillCircle(92 + p + jx, 34 + jy, 4, C_B);
  for (int o = 0; o < 2; o++) {                      // alis cemas
    display.drawLine(24 + jx, 16 + o + jy, 46 + jx, 9 + o + jy, C_W);
    display.drawLine(82 + jx, 9 + o + jy, 104 + jx, 16 + o + jy, C_W);
  }
  for (int x = 50; x < 78; x++)                      // mulut bergetar
    display.drawPixel(x + jx, 56 + jy + (((x / 3) & 1) ? 2 : 0), C_W);
  int y = 10 + (int)((t / 25) % 36);                 // keringat dingin
  display.fillCircle(114, y + 3, 3, C_W);
  display.fillTriangle(111, y + 2, 117, y + 2, 114, y - 4, C_W);
}

// gambar hati kecil (cx, cy = tengah, r = ukuran)
static void scHeart(int cx, int cy, int r) {
  display.fillCircle(cx - r / 2, cy - r / 3, r / 2, C_W);
  display.fillCircle(cx + r / 2, cy - r / 3, r / 2, C_W);
  display.fillTriangle(cx - r, cy - r / 4, cx + r, cy - r / 4, cx, cy + r, C_W);
}

// MANJA: mata berbinar goyang pelan, pipi merona, mulut 'w', hati melayang
static void scManja(unsigned long t) {
  int sx = (int)(sinf(t / 300.0f) * 4);
  int blink = (t % 2200 < 140) ? 4 : 26;
  display.fillRoundRect(22 + sx, 30 - blink / 2, 26, blink, 9, C_W);
  display.fillRoundRect(80 + sx, 30 - blink / 2, 26, blink, 9, C_W);
  if (blink > 10) {
    int sp = ((t / 200) & 1) ? 1 : 0;
    display.fillCircle(30 + sx, 25, 4 + sp, C_B);
    display.fillCircle(88 + sx, 25, 4 + sp, C_B);
    display.fillCircle(39 + sx, 33, 2, C_B);
    display.fillCircle(97 + sx, 33, 2, C_B);
  }
  for (int i = 0; i < 3; i++) {                      // pipi merona
    display.drawLine(14 + i * 4 + sx, 46, 17 + i * 4 + sx, 42, C_W);
    display.drawLine(102 + i * 4 + sx, 46, 105 + i * 4 + sx, 42, C_W);
  }
  display.drawLine(55 + sx, 46, 60 + sx, 50, C_W);   // mulut kucing 'w'
  display.drawLine(60 + sx, 50, 64 + sx, 46, C_W);
  display.drawLine(64 + sx, 46, 68 + sx, 50, C_W);
  display.drawLine(68 + sx, 50, 73 + sx, 46, C_W);
  const int hx[3] = {10, 64, 118};
  for (int i = 0; i < 3; i++) {
    int hy = 58 - (int)((t / 22 + i * 20) % 54);
    scHeart(hx[i] + (int)(sinf(t / 180.0f + i) * 3), hy, 4);
  }
}

// SEDIH: mata sayu, alis sedih, air mata mengalir deras, mulut melengkung turun
static void scSedih(unsigned long t) {
  int sy = (int)(sinf(t / 250.0f) * 2);
  display.fillRoundRect(24, 24 + sy, 26, 20, 7, C_W);
  display.fillRoundRect(78, 24 + sy, 26, 20, 7, C_W);
  display.fillTriangle(22, 22 + sy, 50, 22 + sy, 22, 30 + sy, C_B);  // potong kelopak sayu
  display.fillTriangle(106, 22 + sy, 78, 22 + sy, 106, 30 + sy, C_B);
  for (int o = 0; o < 2; o++) {                      // alis sedih
    display.drawLine(22, 22 + o + sy, 46, 15 + o + sy, C_W);
    display.drawLine(82, 15 + o + sy, 106, 22 + o + sy, C_W);
  }
  for (int i = 0; i < 2; i++) {                      // air mata jatuh kiri & kanan
    int ty = 44 + (int)((t / 14 + i * 10) % 20);
    display.fillCircle(36, ty, 2, C_W);
    display.fillCircle(92, ty, 2, C_W);
  }
  for (int x = -10; x <= 10; x++) {                  // mulut cemberut
    int y = 56 + (x * x) / 22;
    display.drawPixel(64 + x, y, C_W);
    display.drawPixel(64 + x, y + 1, C_W);
  }
}

// MARAH: alis menukik tajam, mata menyipit, mulut menggeretak, urat dahi
static void scMarah(unsigned long t) {
  int jx = ((t / 40) & 1) ? 1 : -1;
  display.fillRoundRect(22 + jx, 24, 28, 22, 6, C_W);
  display.fillRoundRect(78 + jx, 24, 28, 22, 6, C_W);
  display.fillTriangle(20 + jx, 22, 52 + jx, 22, 52 + jx, 34, C_B);  // potongan alis tajam
  display.fillTriangle(108 + jx, 22, 76 + jx, 22, 76 + jx, 34, C_B);
  for (int o = 0; o < 3; o++) {
    display.drawLine(22 + jx, 18 + o, 50 + jx, 30 + o, C_W);
    display.drawLine(106 + jx, 18 + o, 78 + jx, 30 + o, C_W);
  }
  display.drawRoundRect(48 + jx, 50, 32, 10, 3, C_W); // gigi menggeretak
  for (int x = 54; x < 76; x += 6) display.drawLine(x + jx, 50, x + jx, 59, C_W);
  if ((t / 180) & 1) {                                // simbol urat marah di kanan atas
    int vx = 112, vy = 12;
    display.drawLine(vx - 5, vy - 2, vx - 2, vy - 2, C_W);
    display.drawLine(vx - 2, vy - 5, vx - 2, vy - 2, C_W);
    display.drawLine(vx + 5, vy - 2, vx + 2, vy - 2, C_W);
    display.drawLine(vx + 2, vy - 5, vx + 2, vy - 2, C_W);
    display.drawLine(vx - 5, vy + 2, vx - 2, vy + 2, C_W);
    display.drawLine(vx - 2, vy + 5, vx - 2, vy + 2, C_W);
    display.drawLine(vx + 5, vy + 2, vx + 2, vy + 2, C_W);
    display.drawLine(vx + 2, vy + 5, vx + 2, vy + 2, C_W);
  }
}

// NGANTUK: mata terpejam, gelembung tidur membesar-kempis, huruf Z melayang
static void scNgantuk(unsigned long t) {
  int h = t < 1200 ? 24 - (int)(t * 20 / 1200) : 4;  // kelopak menutup pelan
  display.fillRoundRect(22, 34 - h / 2, 28, h, 2, C_W);
  display.fillRoundRect(78, 34 - h / 2, 28, h, 2, C_W);
  int br = 4 + (int)((sinf(t / 350.0f) + 1.0f) * 5.0f);  // balon ingus/tidur
  display.drawCircle(72 + br / 2, 46 - br / 2, br, C_W);
  display.drawPixel(70 + br, 43 - br, C_W);
  int mr = t < 1200 ? 6 - (int)(t * 4 / 1200) : 2;   // mulut menguap -> kecil
  display.fillCircle(60, 52, mr, C_W);
  for (int i = 0; i < 3; i++) {                      // huruf Z melayang
    int zy = 52 - (int)((t / 28 + i * 16) % 46);
    int zx = 104 + i * 6;
    int sz = 4 + i * 2;
    display.drawLine(zx, zy, zx + sz, zy, C_W);
    display.drawLine(zx + sz, zy, zx, zy + sz, C_W);
    display.drawLine(zx, zy + sz, zx + sz, zy + sz, C_W);
  }
}

// KEDIP: melirik kiri-kanan lalu kedip genit (wink) + bintang/hati
static void scKedip(unsigned long t) {
  if (t < 2000) {
    int dx = (int)(sinf(t / 260.0f) * 8);
    display.fillRoundRect(22 + dx, 18, 26, 28, 9, C_W);
    display.fillRoundRect(80 + dx, 18, 26, 28, 9, C_W);
    display.fillCircle(35 + dx * 3 / 2, 32, 4, C_B);
    display.fillCircle(93 + dx * 3 / 2, 32, 4, C_B);
    display.drawLine(56, 52, 72, 52, C_W);
  } else {
    display.fillRoundRect(22, 18, 26, 28, 9, C_W);   // mata kiri terbuka
    display.fillCircle(35, 30, 4, C_B);
    for (int o = 0; o < 3; o++) {                    // mata kanan wink '>'
      display.drawLine(80, 24 + o, 102, 32 + o, C_W);
      display.drawLine(102, 32 + o, 80, 40 + o, C_W);
    }
    display.drawLine(52, 50, 62, 55, C_W);           // senyum genit
    display.drawLine(62, 55, 76, 48, C_W);
    scHeart(114, 18 - (int)((t - 2000) / 180) % 8, 5);
  }
}

// MAKAN: kue datang ke mulut, mengunyah nyam-nyam, mata ^ ^ senang
static void scMakan(unsigned long t) {
  if (t < 1800) {
    int fx = 124 - (int)(t * 60 / 1800);             // makanan mendekat ke tengah
    display.fillRoundRect(22, 16, 24, 24, 8, C_W);
    display.fillRoundRect(82, 16, 24, 24, 8, C_W);
    int mr = 3 + (int)(t * 8 / 1800);                // mulut membuka 'O'
    display.fillCircle(64, 50, mr, C_W);
    display.fillCircle(64, 50, mr > 3 ? mr - 3 : 1, C_B);
    display.fillCircle(fx, 50, 6, C_W);              // donat/kue
    display.fillCircle(fx, 50, 2, C_B);
  } else {
    int ch = (int)(sinf(t / 95.0f) * 4);             // kunyah naik-turun
    for (int o = 0; o < 3; o++) {                    // mata ^ ^
      display.drawLine(22, 30 + o, 34, 18 + o, C_W);
      display.drawLine(34, 18 + o, 46, 30 + o, C_W);
      display.drawLine(82, 30 + o, 94, 18 + o, C_W);
      display.drawLine(94, 18 + o, 106, 30 + o, C_W);
    }
    display.fillCircle(18, 44 + ch / 2, 5, C_W);     // pipi gembung mengunyah
    display.fillCircle(110, 44 - ch / 2, 5, C_W);
    display.fillRoundRect(54, 46 + (ch > 0 ? ch : 0), 20, 8 - abs(ch), 3, C_W);
  }
}

// KETAWA: mata > < memantul cepat, mulut terbuka lebar, air mata bahagia
static void scKetawa(unsigned long t) {
  int by = (int)(fabsf(sinf(t / 75.0f)) * 6);
  for (int o = 0; o < 3; o++) {                      // mata > <
    display.drawLine(20, 20 + o - by, 44, 30 + o - by, C_W);
    display.drawLine(44, 30 + o - by, 20, 40 + o - by, C_W);
    display.drawLine(108, 20 + o - by, 84, 30 + o - by, C_W);
    display.drawLine(84, 30 + o - by, 108, 40 + o - by, C_W);
  }
  display.fillCircle(16, 34 - by, 3, C_W);           // air mata ketawa di sudut mata
  display.fillCircle(112, 34 - by, 3, C_W);
  display.fillCircle(64, 46 - by, 13, C_W);          // mulut ketawa lebar 'D'
  display.fillRect(48, 32 - by, 32, 14, C_B);
  display.drawLine(50, 46 - by, 78, 46 - by, C_W);
}

// MIKIR: mata melirik ke atas, satu alis naik, gelembung pikiran -> lampu ide!
static void scMikir(unsigned long t) {
  display.fillRoundRect(22, 22, 24, 24, 8, C_W);
  display.fillRoundRect(76, 22, 24, 24, 8, C_W);
  display.fillCircle(38, 28, 4, C_B);                // pupil lirik kanan-atas
  display.fillCircle(92, 28, 4, C_B);
  display.drawLine(22, 18, 46, 18, C_W);             // alis kiri datar
  display.drawLine(76, 16, 88, 10, C_W);             // alis kanan naik
  display.drawLine(88, 10, 100, 15, C_W);
  display.drawLine(56, 54, 70, 51, C_W);             // mulut miring mikir
  if (t > 500)  display.fillCircle(104, 38, 2, C_W); // gelembung pikiran
  if (t > 1100) display.fillCircle(110, 28, 3, C_W);
  if (t > 1700 && t < 3200) {
    display.drawCircle(116, 14, 8, C_W);
    display.drawLine(114, 10, 118, 10, C_W);         // tanda '?'
    display.drawLine(118, 10, 116, 14, C_W);
    display.drawPixel(116, 17, C_W);
  } else if (t >= 3200) {                            // bohlam ide menyala!
    display.fillCircle(116, 13, 6, C_W);
    display.fillRect(114, 19, 5, 3, C_W);
    if ((t / 120) & 1) {
      display.drawLine(116, 2, 116, 5, C_W);
      display.drawLine(105, 13, 108, 13, C_W);
      display.drawLine(124, 13, 127, 13, C_W);
    }
  }
}

// ---------- dipanggil dari Lala-AI.ino ----------
void sceneDraw() {
  unsigned long t = millis() - sceneStart;
  display.clearDisplay();
  switch (sceneId) {
    case SC_ANJING:  scAnjing(t);  break;
    case SC_PUSING:  scPusing(t);  break;
    case SC_KAGET:   scKaget(t);   break;
    case SC_BERSIN:  scBersin(t);  break;
    case SC_JOGET:   scJoget(t);   break;
    case SC_TAKUT:   scTakut(t);   break;
    case SC_MANJA:   scManja(t);   break;
    case SC_SEDIH:   scSedih(t);   break;
    case SC_MARAH:   scMarah(t);   break;
    case SC_NGANTUK: scNgantuk(t); break;
    case SC_KEDIP:   scKedip(t);   break;
    case SC_MAKAN:   scMakan(t);   break;
    case SC_KETAWA:  scKetawa(t);  break;
    case SC_MIKIR:   scMikir(t);   break;
  }
  display.display();
}

void startScene() {
  uint8_t s;
  do { s = random(0, SC_COUNT); } while (s == sceneId);   // tidak mengulang adegan yang sama
  sceneId = s;
  sceneStep = 0;
  sceneStart = lastStateChange = millis();
  stateDuration = sceneDur[s];
  currentState = STATE_SCENE;

  switch (s) {
    case SC_ANJING: {
      const Note n[] = {{500, 50}, {350, 60}, {0, 90}, {500, 50}, {350, 60}};   // guk guk
      playSequence(n, 5);
      break;
    }
    case SC_PUSING: {
      const Note n[] = {{700, 80}, {450, 80}, {800, 80}, {400, 80}, {900, 80}, {350, 160}};
      playSequence(n, 6);
      break;
    }
    case SC_KAGET: {
      const Note n[] = {{2400, 60}, {0, 30}, {3200, 140}};
      playSequence(n, 3);
      break;
    }
    case SC_BERSIN: {
      const Note n[] = {{700, 90}, {0, 40}, {900, 90}, {0, 40}, {1200, 160}};   // ha... ha... haa
      playSequence(n, 5);
      break;
    }
    case SC_JOGET: {
      const Note n[] = {{523, 100}, {659, 100}, {784, 100}, {659, 100}, {523, 100},
                        {784, 150}, {0, 50}, {659, 100}, {523, 200}};
      playSequence(n, 9);
      break;
    }
    case SC_TAKUT: {
      const Note n[] = {{320, 40}, {0, 35}, {320, 40}, {0, 35}, {320, 40}, {0, 35},
                        {320, 40}, {0, 35}, {320, 40}, {0, 35}, {320, 40}, {0, 35}};  // brrr
      playSequence(n, 12);
      break;
    }
  }
}

// Animasi khusus saat perangkat baru menyala (boot): baru bangun tidur (~4.2 detik)
static void drawBootWakeUp(unsigned long t) {
  display.clearDisplay();
  if (t < 1300) {
    // Fase 1 (0.0 - 1.3s): Tidur pulas (mata terpejam, gelembung tidur, huruf Zzz)
    display.fillRoundRect(22, 32, 28, 4, 2, C_W);
    display.fillRoundRect(78, 32, 28, 4, 2, C_W);
    int br = 4 + (int)((sinf(t / 220.0f) + 1.0f) * 5.0f);
    display.drawCircle(72 + br / 2, 46 - br / 2, br, C_W);
    display.drawPixel(70 + br, 43 - br, C_W);
    display.fillCircle(60, 52, 2, C_W);
    for (int i = 0; i < 3; i++) {
      int zy = 50 - (int)((t / 24 + i * 15) % 44);
      int zx = 102 + i * 7;
      int sz = 4 + i * 2;
      display.drawLine(zx, zy, zx + sz, zy, C_W);
      display.drawLine(zx + sz, zy, zx, zy + sz, C_W);
      display.drawLine(zx, zy + sz, zx + sz, zy + sz, C_W);
    }
  } else if (t < 2600) {
    // Fase 2 (1.3 - 2.6s): Gelembung pecah, menguap lebar ('O') & badan menggeliat
    unsigned long u = t - 1300;
    int sy = (int)(sinf(u / 180.0f) * 3);
    int sx = (int)(sinf(u / 110.0f) * 2);
    for (int o = 0; o < 2; o++) { // mata merem rapat > < saat menguap
      display.drawLine(24 + sx, 24 + sy + o, 46 + sx, 31 + sy + o, C_W);
      display.drawLine(46 + sx, 31 + sy + o, 24 + sx, 38 + sy + o, C_W);
      display.drawLine(104 + sx, 24 + sy + o, 82 + sx, 31 + sy + o, C_W);
      display.drawLine(82 + sx, 31 + sy + o, 104 + sx, 38 + sy + o, C_W);
    }
    int mr = (u < 650) ? (3 + (int)(u * 9 / 650)) : (12 - (int)((u - 650) * 8 / 650));
    if (mr < 3) mr = 3;
    display.fillCircle(64 + sx, 50 + sy, mr, C_W);
    display.fillCircle(64 + sx, 50 + sy, mr - 2, C_B);
    if (u < 280) { // percikan balon tidur pecah
      for (int i = 0; i < 5; i++) {
        float a = i * 1.25f;
        int r = 6 + (int)(u / 25);
        display.drawPixel(76 + (int)(cosf(a) * r), 42 + (int)(sinf(a) * r), C_W);
      }
    }
  } else if (t < 3500) {
    // Fase 3 (2.6 - 3.5s): Mata membuka pelan tapi masih sayu + berkedip 2x
    unsigned long u = t - 2600;
    bool blink = (u > 220 && u < 340) || (u > 560 && u < 680);
    int h = blink ? 3 : 14;
    display.fillRoundRect(22, 32 - h / 2, 28, h, 5, C_W);
    display.fillRoundRect(78, 32 - h / 2, 28, h, 5, C_W);
    if (!blink) {
      display.fillCircle(36, 33, 4, C_B);
      display.fillCircle(92, 33, 4, C_B);
      display.fillRect(20, 22, 32, 6, C_B); // kelopak atas masih berat/sayu
      display.fillRect(76, 22, 32, 6, C_B);
      display.drawLine(22, 28, 50, 28, C_W);
      display.drawLine(78, 28, 106, 28, C_W);
    }
    display.drawLine(58, 52, 70, 52, C_W);
  } else {
    // Fase 4 (3.5 - 4.2s): Bangun segar! Mata bulat besar berkilau + senyum ceria
    display.fillRoundRect(20, 16, 30, 30, 10, C_W);
    display.fillRoundRect(78, 16, 30, 30, 10, C_W);
    display.fillCircle(35, 31, 6, C_B);
    display.fillCircle(93, 31, 6, C_B);
    display.fillCircle(32, 27, 2, C_W);
    display.fillCircle(90, 27, 2, C_W);
    for (int i = 0; i < 3; i++) { // rona pipi
      display.drawLine(12 + i * 4, 48, 15 + i * 4, 44, C_W);
      display.drawLine(104 + i * 4, 48, 107 + i * 4, 44, C_W);
    }
    for (int x = -12; x <= 12; x++) { // senyum
      int y = 50 + (6 - (x * x) / 24);
      display.drawPixel(64 + x, y, C_W);
      display.drawPixel(64 + x, y + 1, C_W);
    }
  }
  display.display();
}

static void playBootWakeUp() {
  unsigned long start = millis();
  while (millis() - start < 4200) {
    drawBootWakeUp(millis() - start);
    delay(30);
  }
}

// Wajah ekspresif & hidup saat mendengar (talking=false) dan berbicara dengan lip-sync (talking=true)
static void faceDraw(bool talking, int level = 0) {
  unsigned long t = millis();
  display.clearDisplay();

  // Gerakan halus kepala & lirikan mata supaya organik (tidak kaku seperti robot)
  int swayX = (int)(sinf(t / 420.0f) * 2.0f);
  int bobY  = (int)(cosf(t / 340.0f) * 1.5f);
  bool blink = ((t % 2900) < 130); // Kedip alami tiap ~2.9 detik

  int lx = 22 + swayX, rx = 80 + swayX;
  int ey = 16 + bobY;

  if (talking) {
    // Alis ekspresif ikut terangkat saat suara AI tinggi
    int browLift = (level > 5) ? 2 : 0;
    display.drawLine(lx + 2, ey - 4 - browLift, lx + 22, ey - 6 - browLift, C_W);
    display.drawLine(rx + 4, ey - 6 - browLift, rx + 24, ey - 4 - browLift, C_W);

    if (blink) {
      // Mata terpejam melengkung manis saat berkedip
      for (int o = 0; o < 2; o++) {
        display.drawLine(lx + 2,  ey + 13 + o, lx + 13, ey + 8 + o, C_W);
        display.drawLine(lx + 13, ey + 8 + o,  lx + 24, ey + 13 + o, C_W);
        display.drawLine(rx + 2,  ey + 13 + o, rx + 13, ey + 8 + o, C_W);
        display.drawLine(rx + 13, ey + 8 + o,  rx + 24, ey + 13 + o, C_W);
      }
    } else if (level > 6) {
      // Mata menyipit senang (antusias) saat berbicara vokal tinggi (^ ^)
      for (int o = 0; o < 3; o++) {
        display.drawLine(lx + 2,  ey + 18 + o, lx + 13, ey + 7 + o, C_W);
        display.drawLine(lx + 13, ey + 7 + o,  lx + 24, ey + 18 + o, C_W);
        display.drawLine(rx + 2,  ey + 18 + o, rx + 13, ey + 7 + o, C_W);
        display.drawLine(rx + 13, ey + 7 + o,  rx + 24, ey + 18 + o, C_W);
      }
    } else {
      // Mata bulat ekspresif + pupil hidup + pantulan cahaya (sparkle)
      display.fillRoundRect(lx, ey, 26, 25, 9, C_W);
      display.fillRoundRect(rx, ey, 26, 25, 9, C_W);
      int px = (int)(sinf(t / 550.0f) * 2.0f);
      display.fillCircle(lx + 14 + px, ey + 13, 5, C_B);
      display.fillCircle(rx + 12 + px, ey + 13, 5, C_B);
      display.fillCircle(lx + 11 + px, ey + 10, 2, C_W); // kilau mata utama
      display.fillCircle(rx + 9 + px,  ey + 10, 2, C_W);
      display.drawPixel(lx + 17 + px,  ey + 16, C_W);     // kilau kecil kedua
      display.drawPixel(rx + 15 + px,  ey + 16, C_W);
    }

    // Rona pipi manis (blush)
    display.drawLine(13 + swayX,  43 + bobY, 18 + swayX,  41 + bobY, C_W);
    display.drawLine(17 + swayX,  44 + bobY, 22 + swayX,  42 + bobY, C_W);
    display.drawLine(106 + swayX, 42 + bobY, 111 + swayX, 44 + bobY, C_W);
    display.drawLine(110 + swayX, 41 + bobY, 115 + swayX, 43 + bobY, C_W);

    // Mulut Lip-Sync mengikuti amplitudo suara AI (level 0..12)
    int mx = 64 + swayX, my = 50 + bobY;
    if (level <= 1) {
      // Senyum tipis bergaris halus
      for (int x = -7; x <= 7; x++) {
        display.drawPixel(mx + x, my + (x * x) / 22, C_W);
        display.drawPixel(mx + x, my + 1 + (x * x) / 22, C_W);
      }
    } else if (level <= 5) {
      // Mulut membuka oval proporsional
      int mw = 12 + level;
      int mh = 4 + level;
      display.fillRoundRect(mx - mw / 2, my - mh / 2, mw, mh, mh / 2, C_W);
      display.fillRoundRect(mx - mw / 2 + 2, my - mh / 2 + 2, mw - 4, mh - 4, (mh - 4) / 2, C_B);
      display.fillCircle(mx, my + mh / 2 - 2, 3, C_W);
    } else {
      // Vokal lantang: mulut 'D' terbuka ceria + lidah di bawah
      int r = 7 + (level > 10 ? 4 : (level - 5));
      display.fillCircle(mx, my - 2, r, C_W);
      display.fillRect(mx - r - 1, my - r - 3, 2 * r + 3, r, C_B);
      display.fillCircle(mx, my + r - 5, r / 2, C_B);
      display.drawLine(mx - r, my - 2, mx + r, my - 2, C_W);
    }
  } else {
    // Mode Mendengarkan (MIC ON): animasi aktif menyimak + gelombang radar telinga (( )) + spektrum equalizer
    int lookX = (int)(sinf(t / 450.0f) * 2.0f);
    int tiltY = (int)(cosf(t / 550.0f) * 1.5f);
    // Alis penasaran menyimak (kiri naik antusias, kanan fokus)
    display.drawLine(lx + 2, ey - 6 + tiltY, lx + 20, ey - 9 + tiltY, C_W);
    display.drawLine(lx + 2, ey - 5 + tiltY, lx + 20, ey - 8 + tiltY, C_W);
    display.drawLine(rx + 6, ey - 8 - tiltY, rx + 24, ey - 5 - tiltY, C_W);

    if (blink) {
      display.drawLine(lx + 2, ey + 13, lx + 24, ey + 13, C_W);
      display.drawLine(rx + 2, ey + 13, rx + 24, ey + 13, C_W);
    } else {
      display.fillRoundRect(lx, ey + tiltY, 26, 25, 9, C_W);
      display.fillRoundRect(rx, ey - tiltY, 26, 25, 9, C_W);
      display.fillCircle(lx + 13 + lookX, ey + 12 + tiltY, 6, C_B);
      display.fillCircle(rx + 13 + lookX, ey + 12 - tiltY, 6, C_B);
      display.fillCircle(lx + 10 + lookX, ey + 9 + tiltY, 2, C_W);
      display.fillCircle(rx + 10 + lookX, ey + 9 - tiltY, 2, C_W);
    }

    // Gelombang radar di sisi kiri & kanan (visual telinga aktif menyimak suara user)
    int wavePhase = (t / 180) % 3;
    int activeWaves = (level > 5) ? 3 : ((level > 1) ? 2 : (wavePhase + 1));
    for (int w = 0; w < activeWaves; w++) {
      int dx = w * 4;
      int h = 5 + w * 3 + (level > 0 ? (level / 2) : 0);
      if (h > 16) h = 16;
      display.drawLine(14 - dx, 25 - h, 11 - dx, 25, C_W);
      display.drawLine(11 - dx, 25,     14 - dx, 25 + h, C_W);
      display.drawLine(114 + dx, 25 - h, 117 + dx, 25, C_W);
      display.drawLine(117 + dx, 25,     114 + dx, 25 + h, C_W);
    }

    // Mulut menyimak
    int mx = 64 + swayX, my = 46 + bobY;
    if (level > 1) {
      int r = 3 + (level > 8 ? 3 : level / 3);
      display.fillCircle(mx, my, r, C_W);
      display.fillCircle(mx, my, r - 2, C_B);
    } else {
      for (int x = -6; x <= 6; x++) {
        display.drawPixel(mx + x, my + (x * x) / 18, C_W);
      }
    }

    // Equalizer 7-bar gelombang suara mic di bagian bawah layar (y = 55..63)
    for (int b = 0; b < 7; b++) {
      int bx = 40 + b * 8;
      int animH = 2 + (int)(fabsf(sinf((t / 110.0f) + b * 0.9f)) * (2.5f + level * 0.8f));
      if (animH > 9) animH = 9;
      display.fillRect(bx, 63 - animH, 4, animH, C_W);
    }
  }
  display.display();
}

// Animasi Kaset Radio Berputar (Tape Cassette Reel Animation)
static void drawCassetteTape(int level) {
  display.clearDisplay();

  // 1. Cangkang Kaset (Outer Cassette Shell)
  display.drawRoundRect(16, 2, 96, 46, 4, C_W);
  display.drawPixel(20, 5, C_W);
  display.drawPixel(107, 5, C_W);
  display.drawPixel(20, 44, C_W);
  display.drawPixel(107, 44, C_W);

  // 2. Head Guide Trapesium bawah
  display.drawLine(34, 48, 42, 40, C_W);
  display.drawLine(42, 40, 86, 40, C_W);
  display.drawLine(86, 40, 94, 48, C_W);
  display.drawPixel(50, 44, C_W);
  display.drawPixel(78, 44, C_W);

  // 3. Area Label Kaset
  display.drawRect(24, 6, 80, 31, C_W);
  display.drawLine(24, 14, 103, 14, C_W);
  display.setTextSize(1);
  display.setTextColor(C_W);
  display.setCursor(38, 7);
  display.print(F("RADIO FM"));

  // 4. Jendela Pita Kaset Tengah
  display.drawRect(52, 17, 24, 14, C_W);
  display.drawLine(48, 30, 80, 30, C_W);

  // 5. Dua Roda Kumparan Kaset (Tape Spools)
  int cx1 = 42, cx2 = 86, cy = 24;
  display.drawCircle(cx1, cy, 7, C_W);
  display.drawCircle(cx2, cy, 7, C_W);
  display.drawCircle(cx1, cy, 2, C_W);
  display.drawCircle(cx2, cy, 2, C_W);

  // Ruji berputar (Rotating Spool Teeth)
  float angle = (millis() % 1000) * (2.0 * PI / 1000.0);
  for (int i = 0; i < 3; i++) {
    float a = angle + i * (2.0 * PI / 3.0);
    int dx = (int)(cos(a) * 5.0);
    int dy = (int)(sin(a) * 5.0);
    display.drawLine(cx1, cy, cx1 + dx, cy + dy, C_W);
    display.drawLine(cx2, cy, cx2 + dx, cy + dy, C_W);
  }

  // 6. Indikator Audio Equalizer di sisi kiri & kanan
  int barH = level;
  if (barH > 8) barH = 8;
  if (barH > 0) {
    display.fillRect(5, 42 - barH * 4, 4, barH * 4, C_W);
    display.fillRect(119, 42 - barH * 4, 4, barH * 4, C_W);
  }

  // 7. Status Teks Navigasi Bawah
  display.setTextSize(1);
  display.setCursor(16, 54);
  display.print(F("1x:CH 2x:V- 3x:V+"));

  display.display();
}

// Animasi emosional non-blocking saat standby
static unsigned long lastScene = 0;
static void sceneTick() {
  if (millis() - sceneStart >= stateDuration) startScene();
  if (millis() - lastScene < 70) return;
  lastScene = millis();
  sceneDraw();
}

// FreeRTOS Task khusus OLED
static void uiTask(void *pv) {
  bool oledOff = false;
  UiMode lastMode = UI_BOOT_WAKE;
  startScene();
  for (;;) {
    UiMode m = uiMode;
    if (m != lastMode) {
      if (oledOff && m != UI_SLEEP) {
        display.ssd1306_command(SSD1306_DISPLAYON);
        oledOff = false;
      }
      if (m == UI_STANDBY) {
        startScene();
      } else if (m == UI_THINKING) {
        sceneId = SC_MIKIR;
        sceneStart = millis();
      } else if (m == UI_SLEEP) {
        sceneId = SC_NGANTUK;
        sceneStart = millis();
      }
      lastMode = m;
    }

    switch (m) {
      case UI_BOOT_WAKE: {
        unsigned long elapsed = millis() - uiStateMs;
        if (elapsed < 4200) {
          drawBootWakeUp(elapsed);
          vTaskDelay(30 / portTICK_PERIOD_MS);
        } else {
          setUiMode(sleepMode ? UI_SLEEP : UI_STANDBY);
        }
        break;
      }
      case UI_STANDBY:
        sceneTick();
        vTaskDelay(25 / portTICK_PERIOD_MS);
        break;
      case UI_LISTENING:
        faceDraw(false, uiLevel);
        vTaskDelay(45 / portTICK_PERIOD_MS);
        break;
      case UI_THINKING:
        sceneDraw();
        vTaskDelay(60 / portTICK_PERIOD_MS);
        break;
      case UI_TALKING:
        faceDraw(true, uiLevel);
        vTaskDelay(40 / portTICK_PERIOD_MS);
        break;
      case UI_SLEEP:
        // Tampilkan ekspresi ngantuk Zzz 1.5 detik lalu matikan panel OLED untuk hemat daya
        if (millis() - uiStateMs < 1500) {
          sceneDraw();
          vTaskDelay(60 / portTICK_PERIOD_MS);
        } else {
          if (!oledOff) {
            display.clearDisplay();
            display.display();
            display.ssd1306_command(SSD1306_DISPLAYOFF);
            oledOff = true;
          }
          vTaskDelay(100 / portTICK_PERIOD_MS);
        }
        break;
      case UI_AUTO_STATUS:
        if (millis() - uiStateMs < 1800) {
          display.clearDisplay();
          display.drawRoundRect(4, 8, 120, 48, 6, C_W);
          display.setTextSize(1);
          display.setTextColor(C_W);
          display.setCursor(18, 18);
          display.print(F("AUTO NGOMONG 1M:"));
          display.setTextSize(2);
          display.setCursor(autoTalkEnabled ? 40 : 34, 34);
          display.print(autoTalkEnabled ? F("ON") : F("OFF"));
          display.display();
          vTaskDelay(80 / portTICK_PERIOD_MS);
        } else {
          setUiMode(sleepMode ? UI_SLEEP : UI_STANDBY);
        }
        break;
      case UI_HOLD_3S: {
        display.clearDisplay();
        display.drawRoundRect(2, 2, 124, 60, 6, C_W);
        display.setTextSize(1);
        display.setTextColor(C_W);

        unsigned long held = millis() - uiStateMs;

        if (held < 3000) {
          display.setCursor(8, 8);
          display.print(F("TAHAN TOMBOL:"));
          display.setCursor(8, 20);
          display.print(F("3s = Auto 1M"));
          display.setCursor(8, 32);
          display.print(F("5s = Mode SLEEP"));
        } else if (held < 5000) {
          display.setCursor(8, 8);
          display.print(F(">>> 3 DETIK! <<<"));
          display.setCursor(8, 20);
          display.print(F("Lepas: Auto 1M"));
          display.setCursor(8, 32);
          display.print(F("Tahan terus: SLEEP"));
        } else {
          display.setCursor(22, 14);
          display.setTextSize(2);
          display.print(F("SLEEP..."));
          display.setTextSize(1);
        }

        // Progress bar di bawah (0..5000ms)
        display.drawRect(8, 46, 112, 10, C_W);
        // Garis batas 3s pada bar (3000 / 5000 * 108 = ~65px)
        display.drawLine(8 + 65, 44, 8 + 65, 57, C_W);
        int barW = (int)((held > 5000 ? 5000 : held) * 108 / 5000);
        if (barW > 0) display.fillRect(10, 48, barW, 6, C_W);

        display.display();
        vTaskDelay(40 / portTICK_PERIOD_MS);
        break;
      }

      case UI_RADIO_ON: {
        drawCassetteTape(uiLevel);
        vTaskDelay(45 / portTICK_PERIOD_MS);
        break;
      }
    }
  }
}

static bool uiInit(int sda = 21, int scl = 22, uint8_t addr = 0x3C) {
  Wire.begin(sda, scl);
  Wire.setClock(800000);
  if (!display.begin(SSD1306_SWITCHCAPVCC, addr)) {
    Serial.println(F("[ERR] OLED tidak terdeteksi, lanjut tanpa layar"));
    return false;
  }
  uiStateMs = millis();
  uiMode = UI_BOOT_WAKE;
  return true;
}


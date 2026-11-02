# Dokumentasi Fitur Internet Radio Streaming & Digital Volume Control

Fitur pemutaran siaran radio internet langsung pada perangkat **Bymax AI Voice Assistant** dengan kendali suara dan tombol interupsi fisik.

---

## 1. Arsitektur Relay Audio Server-Side

```text
[Internet Radio Stream] (MP3 / AAC / Shoutcast / Icecast)
             │
             ▼ (HTTP/HTTPS)
    ┌─────────────────┐
    │  Server Python  │
    │  (server.py)    │ ── PyAV: Decode audio stream
    │                 │ ── PyAV AudioResampler: Format s16, Layout stereo, Rate 16000 Hz
    │                 │ ── NumPy: Digital volume scaling (0 - 100%)
    └─────────────────┘
             │
             ▼ (TCP Socket Header 'A' + Raw PCM 16kHz Stereo)
    ┌─────────────────┐
    │  ESP32 Firmware │ ── DMA I2S Output (MAX98357A / Audio Amplifier)
    │   (main.cpp)    │ ── Tanpa beban decoding MP3 / AAC di mikrokontroler
    └─────────────────┘
```

- **ESP32 Zero-Overhead:** ESP32 tidak memerlukan library MP3 decoding atau buffering besar. Audio diterima langsung sebagai aliran raw PCM 16kHz 16-bit stereo yang sesuai dengan buffer I2S DMA.
- **PyAV Streaming Relay:** Server membuka stream live dan secara dinamis me-resample audio frame-by-frame ke format native ESP32 tanpa jeda disk (in-memory pipeline).
- **Digital Volume Scaling:** Pengaturan volume suara dilakukan di tingkat server dengan mengalikan sampel PCM integer 16-bit secara real-time via NumPy sebelum dikirimkan ke soket ESP32.

---

## 2. Konfigurasi Stasiun Radio (`Server/radios.json`)

Daftar stasiun radio dikelola dalam file terpisah `Server/radios.json` sehingga mudah ditambah atau diubah tanpa menyentuh kode program.

### Struktur Schema JSON:
```json
[
  {
    "id": "dmi",
    "name": "Dengerin Musik Indonesia (DMI)",
    "aliases": ["dmi", "musik indonesia", "pop indonesia", "lagu pop", "pop", "musik", "lagu"],
    "url": "http://stream.denger.in:8888/dmi",
    "genre": "Pop Indonesia"
  }
]
```

### Daftar 8 Stasiun Radio Terverifikasi Aktif:
| ID | Nama Stasiun | Genre | Alias / Kata Kunci Suara | URL Stream |
| :--- | :--- | :--- | :--- | :--- |
| `dmi` | **Dengerin Musik Indonesia (DMI)** | Pop Indonesia | *dmi, musik indonesia, pop indonesia, pop, lagu* | `http://stream.denger.in:8888/dmi` |
| `iradio` | **I-Radio Jakarta** | Pop Indonesia Hits | *iradio, i-radio, i radio, radio indonesia* | `http://stream.radiojar.com/4ywdgup3bnzuv` |
| `elshinta` | **Elshinta FM Jakarta** | Berita & Informasi | *elshinta, elshinta fm, berita, news, kabar* | `https://stream-ssl.arenastreaming.com:8000/jakarta` |
| `sonora` | **Sonora FM Jakarta** | Berita & Musik Pop | *sonora, sonora fm* | `https://sonora-radio.arenastreaming.com/8130/stream` |
| `suarasurabaya` | **Suara Surabaya FM** | Informasi & Lalulintas | *suara surabaya, ssfm, surabaya* | `https://c5.siar.us/proxy/ssfm/stream` |
| `campursari` | **Campursari FM** | Campursari & Tradisional | *campursari, campur sari, jawa, gamelan* | `https://a8.siar.us/listen/campursari/stream` |
| `dangdut` | **Mettaswara Dangdut Koplo** | Dangdut & Koplo | *dangdut, koplo, mettaswara, dangdutan* | `https://mettaswara.com:8700/d4d` |
| `goldenhits` | **Golden Hits FM** | Lagu Nostalgia / Lawas | *golden hits, nostalgia, lagu lawas, jadul, tembang kenangan* | `https://i.klikhost.com:9134/stream` |

---

## 3. Kontrol Suara & Volume Digital

Volume dikendalikan secara digital pada buffer PCM 16-bit dan nilainya disimpan secara persisten di `Server/memory.json`:
- `volume`: Level saat ini (0 – 100%).
- `muted`: Status pembisuan (`true` / `false`).
- `last_volume`: Nilai volume sebelum di-mute (agar saat unmute dapat kembali ke level semula).
- `current_radio`: ID stasiun radio yang terakhir diputar.

### Rumus Pengali Digital:
$$\text{Sample}_{\text{scaled}} = \text{clip}\left(\text{Sample}_{\text{raw}} \times \frac{\text{Volume}}{100},\ -32768,\ 32767\right)$$

---

## 4. Perintah Suara (Voice Commands)

Pengguna dapat mengontrol radio dan volume menggunakan perintah suara alami (baik melalui tombol 1x obrolan maupun mode panggil):

### A. Memutar Radio
- *"Putar radio DMI"* $\rightarrow$ Memutar siaran DMI (Pop Indonesia).
- *"Setel lagu dangdut"* $\rightarrow$ Otomatis memilih Mettaswara Dangdut Koplo.
- *"Putar berita Elshinta"* $\rightarrow$ Memutar Elshinta FM.
- *"Dengerin lagu lawas / nostalgia"* $\rightarrow$ Memutar Golden Hits FM.
- *"Putar radio"* $\rightarrow$ Memutar stasiun radio terakhir yang tersimpan di memori.

### B. Mengganti Channel (Navigasi)
- *"Ganti channel"* / *"Radio berikutnya"* / *"Channel selanjutnya"* $\rightarrow$ Berpindah ke stasiun radio berikutnya dalam daftar.
- *"Channel sebelumnya"* / *"Radio mundur"* $\rightarrow$ Kembali ke stasiun radio sebelumnya.

### C. Informasi Channel
- *"Lagi putar radio apa?"* / *"Channel apa ini?"* $\rightarrow$ AI menyebutkan nama stasiun dan genre yang sedang aktif.

### D. Menghentikan Radio
- *"Matikan radio"* / *"Stop radio"* / *"Hentikan siaran radio"* $\rightarrow$ Menghentikan relay stream.

### E. Pengaturan Volume Suara
- **Atur Level Spesifik:** *"Volume 50"*, *"Atur volume 80 persen"*, *"Volume maksimal / penuh"*, *"Volume nol / mati"*.
- **Naikkan Suara (+20%):** *"Besarkan suaranya"*, *"Naikkan volume"*, *"Tambah suara"*, *"Kurang keras"*.
- **Turunkan Suara (-20%):** *"Kecilkan volumenya"*, *"Turunkan suara"*, *"Pelankan suaranya"*, *"Terlalu keras"*.
- **Mute / Bisukan:** *"Mute"*, *"Bisukan suara"*, *"Senyapkan suaranya"*.
- **Unmute:** *"Unmute"*, *"Bunyikan lagi"*, *"Suarakan lagi"*.
- **Cek Volume:** *"Berapa volume suara?"*, *"Cek volume"*.

---

## 5. Interupsi Fisik (Tombol ESP32)

Saat siaran radio sedang berlangsung:
- **Klik 1x**: Ganti ke Channel Berikutnya (Next Channel).
- **Klik 2x**: Turunkan Volume (-20%).
- **Klik 3x**: Naikkan Volume (+20%).
- **Tahan 3 Detik**: Hentikan Radio & Kembali ke Status Standby.

*Catatan: Pengaturan volume dilakukan secara digital di sisi server.*

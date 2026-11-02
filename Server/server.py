import os, sys, socket, json, subprocess, re, time, random, asyncio, io
from datetime import datetime, timedelta
import numpy as np
import requests
from faster_whisper import WhisperModel
from piper import PiperVoice, SynthesisConfig
try:
    import edge_tts
    import av
    HAS_EDGE_TTS = True
except ImportError:
    HAS_EDGE_TTS = False

BASE_DIR = os.path.dirname(os.path.abspath(__file__)) if "__file__" in globals() else os.getcwd()
sys.path.insert(0, BASE_DIR)
from idle_moods import IDLE_MOODS

PORT = 8765
OLLAMA_URL = "https://ollama.com/api/chat"
OLLAMA_MODEL = "gemma4:31b"  # pilihan free tier: beam (cepat), gemma4:31b (lebih pintar)
PIPER_VOICE = os.path.join(BASE_DIR, "voices", "id_ID-news_tts-medium.onnx")
TTS_ENGINE = os.environ.get("TTS_ENGINE", "edge").lower()  # "edge" (suara cewek natural) atau "piper" (offline lokal)
EDGE_TTS_VOICE = os.environ.get("EDGE_TTS_VOICE", "id-ID-GadisNeural")

SYSTEM = (
    "Kamu adalah teman ngobrol cewek yang asyik, cerdas, hangat, dan ekspresif. "
    "Gaya bicaramu santai seperti manusia biasa yang lagi ngobrol langsung—bukan seperti robot atau customer service. "
    "Gunakan bahasa Indonesia percakapan sehari-hari yang luwes dan hidup (pakai kata seperti 'kan', 'dong', 'sih', 'kok', 'banget', 'udah', 'nggak'). "
    "JANGAN gunakan bahasa formal kaku (hindari kata: 'tentu saja', 'ada yang bisa saya bantu', 'berikut adalah', 'tersebut'). "
    "PENTING: Ketika user sedang membahas suatu topik, FOKUS ikuti dan tanggapi topik tersebut. JANGAN tiba-tiba mengganti topik atau membuat topik baru tanpa alasan. "
    "PENDEKATAN MIKROFON & SALAH DENGAR (STT TYPO / GUMAMAN): "
    "User berbicara lewat mikrofon suara sehingga sering ada kata terpeleset, gumaman, atau typo salah dengar dari sistem. "
    "DILARANG KERAS bersikap kaku, heran, menginterogasi, atau mendebat kata aneh (JANGAN pernah bilang 'CSE itu apa?', 'Kata X itu apa sih? Aku nggak ngerti'). "
    "Tanggapi secara santai, pemaaf, dan cerdas: tebak maksud intinya secara wajar, atau respon ramah mengalir ('Gimana tadi? Suaranya agak kepotong di aku' / 'Eh kenapa tuh?'). "
    "Jawab singkat 1-2 kalimat alami yang siap diucapkan suara (TTS), tanpa tanda bintang, tanpa emoji, dan tanpa format markdown."
)

# IDLE_MOODS diimpor otomatis dari folder package Server/idle_moods/ (__init__.py)

IDLE_INTERVAL = 120   # 120 detik sekali ngomong sendiri saat standby
SPEECH_RMS = 650     # ambang suara mic
AUTO_MAX_TURNS = 0   # 0 = unlimited tanya-jawab selama user masih merespons (berhenti otomatis saat user diam)
WAKE_WAIT_SEC = 6.0  # batas tunggu mulai bicara setelah AI selesai jawab (detik, beri jeda waktu wajar user berpikir)
WAKE_MAX_SEC = 60    # batas darurat rekam kontinu selama user terus bicara (detik)
WAKE_MAX_TURNS = 0   # 0 = unlimited tanya-jawab di Mode Panggil selama user masih merespons
SAYANG_RE = re.compile(r"\b(sayang|sayank|sa\s+yang)\b", re.IGNORECASE)
BYMAX_RE = re.compile(
    r"\b((?:b\s*[aeiy]*|p\s*)[,\s-]*m[ae][ckx]+s?|ayo\s+m[ae][ckx]+)\b",
    re.IGNORECASE,
)
BANGUN_RE = re.compile(
    r"\b(?:ayo\s+|tolong\s+|kamu\s+|yuk\s+|hey\s+|hei\s+)?bangun(?:\s+(?:dong|yuk|tidur|kamu))?\b",
    re.IGNORECASE,
)
WAKE_RE = re.compile(
    r"\b("
    r"sayang|sayank|sa\s+yang|"
    r"(?:b\s*[aeiy]*|p\s*)[,\s-]*m[ae][ckx]+s?|"
    r"ayo\s+m[ae][ckx]+|"
    r"(?:ayo\s+|tolong\s+|kamu\s+|yuk\s+|hey\s+|hei\s+)?bangun(?:\s+(?:dong|yuk|tidur|kamu))?"
    r")\b",
    re.IGNORECASE,
)
current_call_address = "sayang"  # "Tuan" jika dipanggil Bymax, "sayang" jika dipanggil Sayang
NO_WORDS = (
    "tidak", "nggak", "gak", "enggak", "ndak", "udah", "sudah",
    "cukup", "makasih", "terima kasih", "itu aja", "itu saja", "ngga",
)
END_CMD_RE = re.compile(
    r"\b("
    r"(?:sudah\s+)?(?:berhenti|hentikan|perhentikan|stop|akhiri|matikan|selesai|tutup)\s*(?:lah|dong|aja|saja)?\s+(?:ngobrol|bicara|sesion|session|sesi|percakapan|saya\s+sih|cse|cece|se\s*si|ini|dulu\s+ini)\b|"
    r"(?:sesion|session|sesi|saya\s+sih|cse|cece|se\s*si)\s*(?:ini\s*)?(?:mati|stop|selesai|berhenti|tutup|off|dulu|diakhiri)\b|"
    r"(?:berhenti|stop|matikan)\s+(?:ngobrol|bicara|dulu|ini)\b|"
    r"(?:ngobrol|bicara)\s*(?:nya\s+)?(?:selesai|cukup|nanti\s+lagi|udah|sudah)\b|"
    r"^(?:stop|berhenti|cukup|selesai|matikan|hentikan)[\s.!,]*$"
    r")\b",
    re.IGNORECASE,
)
CLOSE_PROMPT = (
    "Tutup obrolan ini dengan komentar penutup atau gumaman santai yang natural sesuai konteks obrolan barusan "
    "(misalnya mengiyakan atau membiarkan dia lanjut beraktivitas), tanpa mengajukan pertanyaan apa pun."
)
SILENT_PROMPT = (
    "Dia tidak menjawab omonganmu barusan (mungkin lagi fokus atau sibuk). "
    "Beri reaksi singkat yang bervariasi—bisa maklum, menggoda tipis, atau pura-pura ngambek manja—lalu bilang kamu tidak mengganggu dulu. Jangan bertanya lagi."
)
SILENT_FALLBACKS = (
    "Kayaknya kamu lagi fokus banget ya sampai nggak nyaut, yaudah aku temenin sambil diam dulu deh.",
    "Duh dicuekin nih, pasti lagi serius banget ya. Yaudah lanjut dulu aja, nanti panggil aku lagi.",
    "Hmm nggak ada suara, lagi sibuk sendiri ya. Aku tungguin di sini aja deh.",
    "Oke deh kalau lagi nggak bisa jawab sekarang, aku diam dulu biar kamu fokus.",
)
SILENCE_WIN = 12     # 12 x 100 ms (1,2 detik) hening = selesai bicara
MAX_SEC = 6.0        # tunggu ~6 detik respon user sebelum deteksi tidak menjawab (beri waktu berpikir)
WIN = 3200           # 100 ms @ 16 kHz int16 mono = 3200 byte

stt = WhisperModel("base", device="cpu", compute_type="int8", cpu_threads=4)
tts_voice = PiperVoice.load(PIPER_VOICE)
piper_rate = json.load(open(PIPER_VOICE + ".json"))["audio"]["sample_rate"]
history = []
recent_spontaneous = []
mood_deck = []
http_session = requests.Session()

last_interaction = time.time()
last_announced_hour = -1  # Menyimpan jam terakhir yang sudah diumumkan

MEMORY_FILE = os.path.join(BASE_DIR, "memory.json")
RADIOS_FILE = os.path.join(BASE_DIR, "radios.json")


def load_radios():
    if not os.path.exists(RADIOS_FILE):
        return []
    try:
        with open(RADIOS_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            if isinstance(data, list):
                return data
    except Exception as e:
        print(f"[RADIO-WARN] Gagal baca radios.json ({e})")
    return []


def get_radio_station(query):
    radios = load_radios()
    if not radios:
        return None
    
    mem = load_memory()
    cur_id = mem.get("current_radio", "dmi")

    if not query:
        for s in radios:
            if s.get("id") == cur_id:
                return s
        return radios[0]

    q = query.lower().strip()
    # 1. First pass: specific name, id, or explicit genre (excluding generic "musik"/"lagu")
    for s in radios:
        if s["id"] in q or s["name"].lower() in q:
            return s
        for alias in s.get("aliases", []):
            if alias in ("musik", "lagu"):
                continue
            if alias in q:
                return s

    # 2. Second pass: generic fallback (musik / lagu -> default to current radio in memory)
    for s in radios:
        for alias in s.get("aliases", []):
            if alias in q:
                # Priority: if the matched alias belongs to current_radio, use it
                if s["id"] == cur_id:
                    return s
                # Otherwise, it's a match for some other station
                return s
    
    # 3. Final fallback: if query is just "radio" or generic, use current_radio from memory
    if "radio" in q or "musik" in q or "lagu" in q:
        for s in radios:
            if s["id"] == cur_id:
                return s
                
    return None


def get_next_radio_station(current_id, step=1):
    radios = load_radios()
    if not radios:
        return None
    ids = [s["id"] for s in radios]
    if current_id in ids:
        idx = ids.index(current_id)
        next_idx = (idx + step) % len(ids)
    else:
        next_idx = 0
    return radios[next_idx]


def apply_volume(pcm_bytes, vol_percent):
    """Mengatur level suara buffer PCM 16-bit secara digital (0-100%)."""
    if vol_percent >= 100 or not pcm_bytes:
        return pcm_bytes
    if vol_percent <= 0:
        return b"\x00" * len(pcm_bytes)
    samples = np.frombuffer(pcm_bytes, dtype=np.int16)
    factor = float(vol_percent) / 100.0
    scaled = (samples.astype(np.float32) * factor).clip(-32768, 32767).astype(np.int16)
    return scaled.tobytes()


def process_volume_command(text):
    """Mendeteksi dan mengeksekusi perintah volume: naik, turun, angka spesifik, mute, unmute."""
    if not text:
        return None
    t = text.lower().strip()
    mem = load_memory()
    current_vol = mem.get("volume", 80)
    is_muted = mem.get("muted", False)

    # Cek set angka volume spesifik
    m_num = re.search(r"\bvolume\s+(\d+)(?:\s*%)?\b", t)
    if m_num:
        val = int(m_num.group(1))
        val = max(0, min(100, val))
        mem["volume"] = val
        mem["muted"] = (val == 0)
        if val > 0:
            mem["last_volume"] = val
        save_memory(mem)
        return f"Volume diatur ke {val}%."

    if re.search(r"\bvolume\s+(?:maksimal|penuh|100)\b", t):
        mem["volume"] = 100
        mem["muted"] = False
        mem["last_volume"] = 100
        save_memory(mem)
        return "Volume diatur ke maksimal 100%."

    if re.search(r"\bvolume\s+(?:nol|mati|minimum)\b", t):
        mem["volume"] = 0
        mem["muted"] = True
        save_memory(mem)
        return "Volume diatur ke nol, suara dibisukan."

    if re.search(r"\b(?:unmute|bunyikan(?:\s+lagi)?|suarakan(?:\s+lagi)?)\b", t):
        restore_vol = mem.get("last_volume", 80)
        if restore_vol <= 0:
            restore_vol = 80
        mem["volume"] = restore_vol
        mem["muted"] = False
        save_memory(mem)
        return f"Suara aktif kembali, volume {restore_vol}%."

    if re.search(r"\b(?:mute|bisukan(?:\s+suara(?:nya)?)?|senyapkan(?:\s+suara(?:nya)?)?)\b", t):
        mem["muted"] = True
        if current_vol > 0:
            mem["last_volume"] = current_vol
        save_memory(mem)
        return "Suara dibisukan."

    if re.search(r"\b(?:besarkan|tambah(?:kan)?|naikkan|keraskan)\s+(?:suara(?:nya)?|volume(?:nya)?)\b|\b(?:volume(?:nya)?|suara(?:nya)?)\s+(?:naik|tambah|kurang\s+keras|kekecilan)\b", t):
        new_vol = min(100, current_vol + 20)
        mem["volume"] = new_vol
        mem["muted"] = False
        mem["last_volume"] = new_vol
        save_memory(mem)
        return f"Volume dinaikkan ke {new_vol}%."

    if re.search(r"\b(?:kecilkan|kurangi|turunkan|pelankan)\s+(?:suara(?:nya)?|volume(?:nya)?)\b|\b(?:volume(?:nya)?|suara(?:nya)?)\s+(?:turun|kurang|terlalu\s+keras|kegedean|kebesaran)\b", t):
        new_vol = max(10, current_vol - 20)
        mem["volume"] = new_vol
        mem["muted"] = False
        mem["last_volume"] = new_vol
        save_memory(mem)
        return f"Volume diturunkan ke {new_vol}%."

    if re.search(r"\b(?:cek|berapa)\s+volume(?:\s+suara(?:nya)?)?\b", t):
        if is_muted:
            return "Suara saat ini sedang dibisukan (mute)."
        return f"Tingkat volume saat ini {current_vol}%."

    return None


def process_radio_command(text):
    """Mendeteksi perintah pemutaran radio, ganti stasiun/channel, matikan radio, atau cek info channel."""
    if not text:
        return (None, None, None)
    t = text.lower().strip()
    mem = load_memory()
    cur_id = mem.get("current_radio", "dmi")

    # 1. Matikan / Stop Radio
    if re.search(r"\b(?:matikan|stop|hentikan|matiin)\s+(?:siaran\s+)?radio\b", t):
        return ("stop", None, "Baik, siaran radio dimatikan.")

    # 2. Cek Info Channel Radio
    if re.search(r"\b(?:radio|channel|siaran)\s+apa(?:\s+ini)?\b|\b(?:lagi\s+)?(?:putar|dengerin)\s+radio\s+apa\b", t):
        st = get_radio_station(cur_id)
        if st:
            return ("info", st, f"Saat ini memutar {st['name']}, genre {st.get('genre', 'Musik')}.")
        return ("info", None, "Belum ada siaran radio yang dipilih.")

    # 3. Ganti Channel Berikutnya (Next)
    if re.search(r"\b(?:radio|channel|siaran)\s+(?:berikutnya|selanjutnya|next)\b|\b(?:ganti|pindah)\s+(?:channel|radio|siaran|gelombang)\b", t):
        st = get_next_radio_station(cur_id, step=1)
        if st:
            mem["current_radio"] = st["id"]
            save_memory(mem)
            return ("play", st, f"Ganti ke channel {st['name']}.")
        return (None, None, None)

    # 4. Ganti Channel Sebelumnya (Prev)
    if re.search(r"\b(?:radio|channel|siaran)\s+(?:sebelumnya|kemarin|mundur|prev)\b", t):
        st = get_next_radio_station(cur_id, step=-1)
        if st:
            mem["current_radio"] = st["id"]
            save_memory(mem)
            return ("play", st, f"Kembali ke channel {st['name']}.")
        return (None, None, None)

    # 5. Putar / Setel Radio Tertentu atau Default
    m_play = re.search(
        r"\b(?:putar|setel|nyalakan|dengarkan|dengerin|mainkan)\s+(?:ke\s+)?(?:channel\s+|siaran\s+)?(?:radio\s+)?([a-z0-9\s-]+)?\b",
        t
    )
    if m_play or re.search(r"\b(?:radio\s+on|play\s+radio)\b", t):
        target_name = m_play.group(1).strip() if (m_play and m_play.group(1)) else ""
        # Kirim None jika target_name kosong agar get_radio_station mengambil dari memori
        st = get_radio_station(target_name if target_name else None)
        if st:
            mem["current_radio"] = st["id"]
            save_memory(mem)
            return ("play", st, f"Baik, memutar radio {st['name']}. Tekan tombol kapan saja untuk berhenti.")

    return (None, None, None)


def stream_radio_to_client(c, station):
    """Melakukan relay streaming audio radio internet via PyAV ke socket ESP32 dalam format PCM 16kHz stereo."""
    if not station or not HAS_EDGE_TTS:
        print("[RADIO] PyAV tidak tersedia atau stasiun tidak valid.")
        return
    url = station.get("url")
    name = station.get("name", "Radio")
    print(f"\n[RADIO-START] Menghubungkan ke stream: {name} ({url}) ...")
    try:
        container = av.open(url, timeout=7)
        audio_stream = container.streams.audio[0]
        resampler = av.AudioResampler(format="s16", layout="stereo", rate=16000)
    except Exception as e:
        print(f"[RADIO-ERR] Gagal terhubung ke {name}: {e}")
        try:
            err_msg = clean_response(f"Maaf, siaran radio {name} sedang tidak dapat dijangkau.")
            for chunk in tts_chunks(err_msg):
                c.sendall(chunk)
            time.sleep(2.0)
            c.close()
        except Exception:
            pass
        return

    try:
        chunk_count = 0
        c.settimeout(None)  # Blocking send untuk stream kontinu
        for frame in container.decode(audio_stream):
            for rf in resampler.resample(frame):
                raw = rf.to_ndarray().tobytes()
                # Terapkan volume scaling digital
                mem = load_memory()
                vol = 0 if mem.get("muted", False) else mem.get("volume", 80)
                scaled = apply_volume(raw, vol)
                
                # Kirim data dalam potongan kecil agar tidak membanjiri buffer ESP32
                for i in range(0, len(scaled), 256):
                    c.sendall(scaled[i:i+256])
                
                chunk_count += 1
                if chunk_count % 10 == 0:
                    time.sleep(0.005)  # Beri napas lebih banyak pada TCP stack ESP32
    except (OSError, socket.error):
        print(f"[RADIO-STOP] Stream {name} dihentikan (ESP32 memutuskan koneksi / tombol ditekan).")
    except Exception as e:
        print(f"[RADIO-ERR] Stream {name} terputus: {e}")
    finally:
        try:
            c.close()
        except Exception:
            pass


def load_memory():
    default_mem = {
        "user_name": None,
        "call_sign": None,
        "forbid_tuan": False,
        "custom_suffix": None,
        "custom_wake_reply": None,
        "facts": [],
        "reminders": [],
        "volume": 80,
        "muted": False,
        "last_volume": 80,
        "current_radio": "dmi"
    }
    if not os.path.exists(MEMORY_FILE):
        return default_mem
    try:
        with open(MEMORY_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            if isinstance(data, dict):
                for k, v in default_mem.items():
                    data.setdefault(k, v)
                return data
    except Exception as e:
        print(f"[MEM-WARN] Gagal baca memory.json ({e}), gunakan default")
    return default_mem


def save_memory(mem):
    try:
        with open(MEMORY_FILE, "w", encoding="utf-8") as f:
            json.dump(mem, f, indent=2, ensure_ascii=False)
    except Exception as e:
        print(f"[MEM-ERR] Gagal simpan memory.json ({e})")


def get_active_call_name():
    """Mengembalikan sebutan/nama aktif user dari memori jika ada."""
    mem = load_memory()
    return mem.get("call_sign") or mem.get("user_name") or None


def extract_reminder_heuristic(text):
    """Ekstraksi jadwal waktu dan tugas dari ucapan lisan pengguna secara cerdas."""
    if not text:
        return None
    t_clean = text.strip()
    t_lower = t_clean.lower()

    if not re.search(r"\b(?:ingat(?:kan)?|jadwal(?:kan)?|catat(?:kan)?)\b", t_lower):
        return None

    now = datetime.now()
    time_str = None
    time_match_span = None

    # 1. "N menit lagi"
    m_rel = re.search(r"\b(\d+)\s+menit\s+lagi\b", t_lower)
    if m_rel:
        mins = int(m_rel.group(1))
        target_dt = now + timedelta(minutes=mins)
        time_str = target_dt.strftime("%H:%M")
        time_match_span = m_rel.span()

    # 2. "15.5.9" (whisper typo untuk 15:59)
    if not time_str:
        m_dot3 = re.search(r"\b(\d{1,2})\.(\d{1})\.(\d{1})\b", t_lower)
        if m_dot3:
            h = int(m_dot3.group(1))
            m = int(m_dot3.group(2) + m_dot3.group(3))
            if 0 <= h < 24 and 0 <= m < 60:
                time_str = f"{h:02d}:{m:02d}"
                time_match_span = m_dot3.span()

    # 3. "15:59" atau "15.59"
    if not time_str:
        m_hm = re.search(r"\b(\d{1,2})[:.](\d{2})\b", t_lower)
        if m_hm:
            h = int(m_hm.group(1))
            m = int(m_hm.group(2))
            if 0 <= h < 24 and 0 <= m < 60:
                time_str = f"{h:02d}:{m:02d}"
                time_match_span = m_hm.span()

    # 4. "jam X (pagi/siang/sore/malam)"
    if not time_str:
        m_word = re.search(r"\bjam\s*(\d{1,2})(?:[:.](\d{2}))?\s*(pagi|siang|sore|malam)?\b", t_lower)
        if m_word:
            h = int(m_word.group(1))
            m = int(m_word.group(2)) if m_word.group(2) else 0
            meridiem = m_word.group(3)
            if meridiem == "sore" and h < 12:
                h += 12
            elif meridiem == "malam" and h < 12:
                h += 12
            elif meridiem == "siang" and 1 <= h <= 5:
                h += 12
            if 0 <= h < 24 and 0 <= m < 60:
                time_str = f"{h:02d}:{m:02d}"
                time_match_span = m_word.span()

    if not time_str:
        return None

    # Bersihkan teks tugas/kegiatan
    t_no_time = t_clean[:time_match_span[0]] + " " + t_clean[time_match_span[1]:]
    cleaned = re.sub(r"\b(?:baymax|bymax|sayang|sayank)\b", "", t_no_time, flags=re.IGNORECASE)
    cleaned = re.sub(r"\b(?:tolong\s+)?(?:ingat(?:kan)?|jadwal(?:kan)?|catat(?:kan)?)\b", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\b(?:saya|aku|gue|kita|kami)\b", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\b(?:pada|di)?\s*jam\b", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\b(?:untuk|buat|supaya|agar|melakukan)\b", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\s+", " ", cleaned).strip(".,;:?! ")

    if not cleaned:
        cleaned = "kegiatan kamu"

    return {"time": time_str, "task": cleaned}


def add_or_update_reminder(mem, time_str, task_str):
    """Menyimpan atau memperbarui jadwal pengingat di memory.json."""
    if not time_str or not task_str:
        return False
    reminders = mem.setdefault("reminders", [])
    today = datetime.now().strftime("%Y-%m-%d")

    # Normalisasi format time_str ke HH:MM
    m = re.match(r"^(\d{1,2})[:.](\d{1,2})$", time_str.strip())
    if m:
        h = int(m.group(1))
        mi = int(m.group(2))
        time_norm = f"{h:02d}:{mi:02d}"
    else:
        time_norm = time_str.strip()

    task_clean = task_str.strip()

    # Cek apakah jadwal yang sama sudah ada hari ini
    for r in reminders:
        if r.get("time") == time_norm and r.get("date") == today and r.get("task", "").lower() == task_clean.lower():
            r["notified"] = False
            return True

    reminders.append({
        "time": time_norm,
        "task": task_clean,
        "date": today,
        "notified": False
    })
    return True


def check_due_reminders(now=None):
    """Mengecek apakah ada pengingat yang jatuh tempo pada menit ini (prioritas tertinggi)."""
    if now is None:
        now = datetime.now()
    mem = load_memory()
    reminders = mem.get("reminders", [])
    if not reminders:
        return []

    today = now.strftime("%Y-%m-%d")
    curr_hm = now.strftime("%H:%M")
    curr_total_min = now.hour * 60 + now.minute

    due = []
    updated = False

    for r in reminders:
        if r.get("notified"):
            continue
        r_date = r.get("date", today)
        if r_date != today:
            continue
        r_time = r.get("time", "")
        if not r_time:
            continue

        try:
            parts = r_time.split(":")
            rh = int(parts[0])
            rm = int(parts[1])
            r_total_min = rh * 60 + rm
            diff = curr_total_min - r_total_min
            # Jatuh tempo tepat pada menitnya atau selisih 0-2 menit
            if 0 <= diff <= 2:
                r["notified"] = True
                due.append(r)
                updated = True
        except Exception:
            if r_time == curr_hm:
                r["notified"] = True
                due.append(r)
                updated = True

    if updated:
        save_memory(mem)

    return due


def format_memory_context():
    """Format seluruh data memori dan aturan gaya bicara untuk disuntikkan ke prompt Ollama."""
    mem = load_memory()
    name = mem.get("user_name")
    call_sign = mem.get("call_sign")
    suffix = mem.get("custom_suffix")
    custom_wake = mem.get("custom_wake_reply")
    forbid_tuan = mem.get("forbid_tuan") or bool(name)
    facts = mem.get("facts", [])
    reminders = mem.get("reminders", [])

    lines = ["[MEMORI TERSIMPAN]:"]
    if name:
        lines.append(f"- Nama User: {name}")
    if call_sign:
        lines.append(f"- Panggilan yang Diminta User: {call_sign} (Gunakan panggilan ini! JANGAN panggil 'Tuan'!)")
    if forbid_tuan:
        lines.append("- STATUS LARANGAN 'TUAN': AKTIF. DILARANG KERAS memanggil 'Tuan'/'Tuhan'/'tuanya' dalam situasi apa pun!")
    if suffix:
        lines.append(f"- Imbuhan Akhir yang Diminta User: '{suffix}' (Gunakan imbuhan ini di setiap tanggapan!)")
    else:
        lines.append("- Imbuhan Akhir: TIDAK ADA (DILARANG menambah imbuhan aneh tanpa izin memori!)")
    if custom_wake:
        lines.append(f"- Respon Panggil Khusus: '{custom_wake}'")

    active_reminders = [r for r in reminders if not r.get("notified")]
    if active_reminders:
        lines.append("- Jadwal / Pengingat Aktif (PRIORITAS UTAMA):")
        for r in active_reminders[-5:]:
            lines.append(f"  * Jam {r.get('time')}: {r.get('task')}")

    if facts:
        lines.append("- Catatan/Fakta/Alamat Penting:")
        for f in facts[-10:]:
            lines.append(f"  * {f}")
    else:
        lines.append("- Catatan/Fakta Penting: Belum ada catatan khusus.")

    lines.append("[ATURAN KEPRIBADIAN & PANGGILAN]:")
    active_call = call_sign or name
    if active_call:
        lines.append(f"- DILARANG memanggil 'Tuan'. Panggil user dengan: {active_call}.")
        if current_call_address == "sayang":
            lines.append(f"- Boleh memanggil sayang yang dipadukan dengan nama: 'sayang {active_call}' atau cukup '{active_call}'.")
    elif forbid_tuan:
        lines.append("- DILARANG memanggil 'Tuan'. Panggil user secara santai/netral atau 'sayang'/'kamu'.")
    else:
        lines.append("- Jika user belum mengenalkan nama, panggil 'sayang' atau 'kamu'. DILARANG memanggil 'Tuan'.")

    return "\n".join(lines)


def apply_heuristic_safety(text, return_reply=False):
    """Ekstraktor cerdas dan cepat (safety-net) untuk menangkap instruksi memori,
    nama, panggilan, larangan 'Tuan', imbuhan, respon bangun, dan catatan secara langsung."""
    if not text:
        return None
    mem = load_memory()
    updated = False
    t_clean = text.strip()
    t_lower = t_clean.lower()

    # 0. Hapus / reset memori
    if re.search(r"\b(?:hapus|lupakan|reset)\s+(?:semua\s+)?memori\b", t_lower):
        mem = {
            "user_name": None,
            "call_sign": None,
            "forbid_tuan": False,
            "custom_suffix": None,
            "custom_wake_reply": None,
            "facts": [],
            "reminders": []
        }
        save_memory(mem)
        print("[MEMORY HEURISTIC] Reset memori berhasil")
        if return_reply:
            return "Semua data di memori sudah aku bersihkan ya."
        return None

    # 1. Larangan panggil 'Tuan' / 'Tuhan' / 'tuanya' (termasuk typo STT)
    if re.search(
        r"\b(?:jangan|gak\s+boleh|enggak\s+usah|stop)\s+(?:panggil|pengen\s*gil|nyebut)?\s*(?:tuan|tuanya|tuhan)\b",
        t_lower
    ):
        mem["forbid_tuan"] = True
        updated = True
        print("[MEMORY HEURISTIC] Larangan 'Tuan' diaktifkan")
        if return_reply:
            save_memory(mem)
            name = mem.get("call_sign") or mem.get("user_name") or ""
            panggilan = f" {name}" if name else ""
            return f"Siap{panggilan}, aku sudah catat di memori dan nggak bakal panggil Tuan lagi ya."

    # 2. Pengenalan nama user
    # Contoh: "Tolong ingat namanya, ya itu Febri", "nama saya Budi", "namaku Febri", "kenalin aku Febri"
    m_name = re.search(
        r"(?:(?:nama(?:nya|ku| saya)?(?:,\s*ya\s*itu|\s+adalah|\s+itu|\s*[:=])?|kenalin aku|aku ini)\s+)([a-zA-Z0-9]+)",
        t_clean,
        re.IGNORECASE
    )
    if m_name:
        nm = m_name.group(1).strip()
        if nm.lower() not in ("apa", "siapa", "tolong", "bisa", "dong", "ya", "kamu", "itu", "ini", "dia"):
            mem["user_name"] = nm
            if not mem.get("call_sign"):
                mem["call_sign"] = nm
            mem["forbid_tuan"] = True
            updated = True
            print(f"[MEMORY HEURISTIC] Nama user: {nm}")
            if return_reply:
                save_memory(mem)
                return f"Salam kenal ya {nm}! Namamu udah aku simpan di memori dan aku nggak bakal panggil Tuan lagi."

    # 3. Panggilan khusus (bro, bos, kak, dll)
    m_cs = re.search(
        r"(?:panggil(?:kan)?\s+(?:aku|saya|gue|gua)\s+(?:dengan\s+(?:panggilan|sebutan)\s+|sebutan\s+)?)([a-zA-Z0-9]+)",
        t_clean,
        re.IGNORECASE
    )
    if m_cs:
        cs = m_cs.group(1).strip()
        if cs.lower() not in ("apa", "siapa", "tolong", "bisa", "dong", "ya", "kamu", "tuan"):
            mem["call_sign"] = cs
            if not mem.get("user_name"):
                mem["user_name"] = cs
            mem["forbid_tuan"] = True
            updated = True
            print(f"[MEMORY HEURISTIC] Panggilan khusus: {cs}")
            if return_reply:
                save_memory(mem)
                return f"Oke {cs}, mulai sekarang aku panggil kamu {cs} dan udah aku simpan di memori."

    # 4. Imbuhan akhir kalimat (misal: "dong bos", "dong ah")
    m_suf = re.search(
        r"(?:(?:kasih|tambah(?:kan)?|pakai(?:kan)?)\s+imbuhan(?:\s+(?:di\s+)?akhir(?:nya)?(?:\s+(?:kalimat|kata))?)?\s+[\"'\`]?([^\"'\`\n.]+))",
        t_clean,
        re.IGNORECASE
    )
    if m_suf:
        suf = m_suf.group(1).strip().strip("\"'`.,")
        if suf and len(suf) <= 30:
            mem["custom_suffix"] = suf
            updated = True
            print(f"[MEMORY HEURISTIC] Custom suffix: {suf}")
            if return_reply:
                save_memory(mem)
                name = mem.get("call_sign") or mem.get("user_name") or ""
                panggilan = f" {name}" if name else ""
                return f"Siap{panggilan}, mulai sekarang aku bakal pakai imbuhan \"{suf}\" kalau ngomong ya."

    # 5. Respon bangun / panggil khusus
    # Contoh: "kalau saya panggil jangan jawab iya tuan, tapi iya febri ada apa..."
    m_wake = re.search(
        r"(?:jika|kalau|saat)\s+(?:saya|aku)\s+panggil[,\s]+(?:jangan\s+jawab[^,]+,?\s*tapi\s+)([^,.\n]+(?:,[^,.\n]+)?)",
        t_clean,
        re.IGNORECASE
    )
    if m_wake:
        reply_txt = m_wake.group(1).strip().strip("\"'`.,")
        if reply_txt:
            mem["custom_wake_reply"] = reply_txt
            mem["forbid_tuan"] = True
            updated = True
            print(f"[MEMORY HEURISTIC] Custom wake reply: {reply_txt}")
            if return_reply:
                save_memory(mem)
                name = mem.get("call_sign") or mem.get("user_name") or ""
                panggilan = f" {name}" if name else ""
                return f"Siap{panggilan}, mulai sekarang kalau kamu panggil Bymax aku bakal jawab begitu ya."

    # 5.5. Pengingat / Jadwal spesifik (contoh: "ingatkan saya jam 15.5.9 untuk mandi")
    rem_info = extract_reminder_heuristic(t_clean)
    if rem_info:
        r_time = rem_info["time"]
        r_task = rem_info["task"]
        if add_or_update_reminder(mem, r_time, r_task):
            updated = True
            print(f"[MEMORY HEURISTIC] Reminder baru disimpan: Jam {r_time} -> {r_task}")
            if return_reply:
                save_memory(mem)
                name = mem.get("call_sign") or mem.get("user_name") or ""
                panggilan = f" {name}" if name else ""
                return f"Siap{panggilan}, udah aku catat ya! Nanti pas jam {r_time} bakal langsung aku ingatkan buat {r_task}."

    # 6. Catatan / fakta umum ("ingat ...", "simpan dalam memori ...", "catat ...")
    if not rem_info and re.search(r"\b(?:tolong\s+)?(?:ingat(?:kan)?|simpan(?:\s+(?:ini|itu))?(?:\s+(?:ke|dalam|di))?\s+memori|catat(?:kan)?)\b", t_lower):
        if not m_name and not m_cs and not m_suf and not m_wake and "jangan" not in t_lower:
            all_matches = list(re.finditer(r"\b(?:tolong\s+)?(?:ingat(?:kan)?|simpan(?:\s+(?:ini|itu))?(?:\s+(?:ke|dalam|di))?\s+memori|catat(?:kan)?)\b", t_clean, re.IGNORECASE))
            last_end = all_matches[-1].end()
            fact = t_clean[last_end:].strip().lstrip(":,- ")
            fact = re.sub(r"(?:,\s*)?(?:simpan(?:\s+ini)?\s+(?:dalam|ke|di)\s+memori(?:mu)?)\.?$", "", fact, flags=re.IGNORECASE).strip()
            if fact and len(fact) > 3:
                if fact not in mem.setdefault("facts", []):
                    mem["facts"].append(fact)
                updated = True
                print(f"[MEMORY HEURISTIC] Fakta baru disimpan: {fact}")
                if return_reply:
                    save_memory(mem)
                    name = mem.get("call_sign") or mem.get("user_name") or ""
                    panggilan = f" {name}" if name else ""
                    return f"Siap{panggilan}, udah aku simpan di memori: {fact}."

    if updated:
        save_memory(mem)
    return None


def process_memory_command(text):
    """Kompatibilitas deterministik: mendeteksi dan menjalankan perintah memori via heuristik cepat."""
    return apply_heuristic_safety(text, return_reply=True)


def parse_and_apply_llm_memory(raw_text):
    """Ekstraksi maksud dan pembaruan memori otonom berbasis LLM.
    Mengekstrak blok JSON <<<MEMORY_UPDATE>>> dari output Ollama, menyimpannya ke memory.json,
    dan mengembalikan teks ucapan lisan bersih tanpa kebocoran tag JSON."""
    if not raw_text:
        return ""
    m_block = re.search(r"<<<MEMORY_UPDATE>>>(.*?)(?:<<<END_MEMORY_UPDATE>>>|$)", raw_text, re.DOTALL)
    if not m_block:
        m_block = re.search(r"\[MEMORY_UPDATE\](.*?)(?:\[/MEMORY_UPDATE\]|$)", raw_text, re.DOTALL)

    spoken_reply = raw_text
    data = None
    if m_block:
        inner = m_block.group(1).strip()
        m_json = re.search(r"(\{.*\})", inner, re.DOTALL)
        json_str = m_json.group(1).strip() if m_json else inner
        spoken_reply = (raw_text[:m_block.start()] + raw_text[m_block.end():]).strip()
        try:
            data = json.loads(json_str)
            mem = load_memory()
            updated = False

            thought = data.get("thought")
            if thought:
                print(f"\n[AI THINKING]: {thought}")

            if data.get("reset_memory"):
                mem = {
                    "user_name": None,
                    "call_sign": None,
                    "forbid_tuan": False,
                    "custom_suffix": None,
                    "custom_wake_reply": None,
                    "facts": [],
                    "reminders": []
                }
                save_memory(mem)
                print("[AI MEMORY] Reset memori berhasil disimpan")
                if not spoken_reply:
                    spoken_reply = "Oke, semua data di memori udah aku bersihkan ya."
                return spoken_reply

            if data.get("user_name"):
                u_name = str(data["user_name"]).strip()
                if u_name and u_name.lower() != "null":
                    mem["user_name"] = u_name
                    if not mem.get("call_sign"):
                        mem["call_sign"] = u_name
                    mem["forbid_tuan"] = True
                    updated = True

            if data.get("call_sign"):
                c_sign = str(data["call_sign"]).strip()
                if c_sign and c_sign.lower() != "null":
                    mem["call_sign"] = c_sign
                    updated = True

            if data.get("forbid_tuan") is True:
                mem["forbid_tuan"] = True
                updated = True

            if data.get("custom_suffix"):
                c_suf = str(data["custom_suffix"]).strip()
                if c_suf and c_suf.lower() != "null":
                    mem["custom_suffix"] = c_suf
                    updated = True

            if data.get("custom_wake_reply"):
                c_wake = str(data["custom_wake_reply"]).strip()
                if c_wake and c_wake.lower() != "null":
                    mem["custom_wake_reply"] = c_wake
                    mem["forbid_tuan"] = True
                    updated = True

            if data.get("add_fact"):
                fact = str(data["add_fact"]).strip()
                if fact and fact.lower() != "null" and fact not in mem.setdefault("facts", []):
                    mem["facts"].append(fact)
                    updated = True

            if data.get("add_reminder"):
                r_obj = data["add_reminder"]
                if isinstance(r_obj, dict):
                    r_time = str(r_obj.get("time", "")).strip()
                    r_task = str(r_obj.get("task", "")).strip()
                    if r_time and r_task and r_time.lower() != "null" and r_task.lower() != "null":
                        if add_or_update_reminder(mem, r_time, r_task):
                            updated = True
                            print(f"[AI REMINDER ADDED]: Jam {r_time} -> {r_task}")

            if updated:
                save_memory(mem)
                print(f"[AI MEMORY UPDATED]: {mem}")
        except Exception as e:
            print(f"[AI-MEM-WARN] Gagal parse JSON memory dari AI ({e})")

    # Bersihkan sisa tag atau formatting JSON apapun yang mungkin bocor
    spoken_reply = re.sub(r"```(?:json)?.*?```", "", spoken_reply, flags=re.DOTALL)
    spoken_reply = re.sub(r"<<<.*?>>>", "", spoken_reply, flags=re.DOTALL)
    spoken_reply = re.sub(r"\{[^{}]*\"thought\"[^{}]*\}", "", spoken_reply, flags=re.DOTALL).strip()

    # Fallback cerdas jika LLM cuma menghasilkan JSON tanpa kalimat ucapan lisan
    if not spoken_reply and data:
        call_name = data.get("call_sign") or data.get("user_name")
        if call_name:
            spoken_reply = f"Salam kenal ya {call_name}! Namamu udah aku simpan di memori."
        elif data.get("add_reminder"):
            r_task = data["add_reminder"].get("task", "jadwalmu")
            r_time = data["add_reminder"].get("time", "")
            time_part = f" jam {r_time}" if r_time else ""
            spoken_reply = f"Siap, pengingat untuk {r_task}{time_part} udah aku catat ya!"
        elif data.get("forbid_tuan"):
            spoken_reply = "Siap, aku sudah catat dan nggak bakal panggil Tuan lagi ya."
        else:
            spoken_reply = "Oke, udah aku catat di memori ya!"

    return spoken_reply


def pick_idle_mood():
    """Ambil mood secara acak tanpa pengulangan sampai semua variasi terpakai."""
    global mood_deck
    if not mood_deck:
        mood_deck = list(IDLE_MOODS)
        random.shuffle(mood_deck)
    return mood_deck.pop()


def record(c, wait_sec=MAX_SEC, max_sec=WAKE_MAX_SEC):
    """Rekam selama user masih bicara; tunggu wait_sec (~3,5-4 dtk) sebelum vonis tidak menjawab."""
    buf = bytearray()
    pos, started, quiet = 0, False, 0
    voice_streak, voice_total, win_idx = 0, 0, 0
    min_wait_bytes = int(3.0 * 32000)  # Minimal tunggu ~3 detik jika baru ada bunyi singkat (<400ms)
    while len(buf) < max_sec * 32000:
        if not started and len(buf) >= wait_sec * 32000:
            break
        try:
            d = c.recv(4096)
        except socket.timeout:
            break
        except OSError:
            break  # ESP32 memutus koneksi (tombol ditekan lagi)
        if not d:
            break
        buf += d
        while len(buf) - pos >= WIN:
            w = np.frombuffer(bytes(buf[pos:pos + WIN]), np.int16).astype(np.float32)
            pos += WIN
            win_idx += 1
            w -= w.mean()  # Hilangkan DC offset agar deteksi hening (RMS) akurat
            rms = float(np.sqrt(np.mean(w * w)))
            print(f"rms={rms:6.0f}", end="\r")
            # Abaikan 2 window pertama (200ms) saat mic baru buka agar klik/transisi tidak memicu started palsu
            if win_idx <= 2:
                continue
            if rms > SPEECH_RMS:
                voice_streak += 1
                voice_total += 1
                quiet = 0
                if voice_streak >= 2:  # Minimal 200ms suara beruntun baru dianggap mulai bicara
                    started = True
            else:
                voice_streak = 0
                if started:
                    quiet += 1
                    if quiet >= SILENCE_WIN:
                        # Jika suara sangat pendek (<400ms, misal batuk/klik) dan belum 3 detik, lanjut tunggu user bicara
                        if voice_total < 4 and len(buf) < min_wait_bytes:
                            started = False
                            quiet = 0
                            voice_total = 0
                        else:
                            return bytes(buf)
    return bytes(buf) if (started and voice_total >= 2) else b""


def transcribe(pcm):
    a = np.frombuffer(pcm, np.int16).astype(np.float32)
    a -= a.mean()
    a *= 0.9 / max(float(np.abs(a).max()), 1.0)
    segs, _ = stt.transcribe(
        a,
        language="id",
        beam_size=1,
        best_of=1,
        initial_prompt="Sayang, Bymax, Baymax.",
        condition_on_previous_text=False,
        vad_filter=True,
        vad_parameters=dict(min_silence_duration_ms=300)
    )
    return " ".join(s.text for s in segs).strip()


def clean_response(t):
    if not t:
        return ""
    # Hapus tag <think> jika ada model reasoning
    t = re.sub(r"<think>.*?(?:</think>|$)", "", t, flags=re.DOTALL).strip()
    # Hapus blok pembaruan memori jika tersisa di respons (dengan atau tanpa penutup)
    t = re.sub(r"<<<MEMORY_UPDATE>>>.*?(?:<<<END_MEMORY_UPDATE>>>|$)", "", t, flags=re.DOTALL).strip()
    t = re.sub(r"\[MEMORY_UPDATE\].*?(?:\[/MEMORY_UPDATE\]|$)", "", t, flags=re.DOTALL).strip()
    t = re.sub(r"```(?:json)?.*?```", "", t, flags=re.DOTALL).strip()
    t = re.sub(r"<<<.*?>>>", "", t, flags=re.DOTALL).strip()
    t = re.sub(r"\{[^{}]*\"thought\"[^{}]*\}", "", t, flags=re.DOTALL).strip()
    t = t.replace("*", "").replace("#", "").strip()

    mem = load_memory()
    user_addr = get_active_call_name()
    forbid_tuan = mem.get("forbid_tuan") or bool(user_addr)

    # 1. Bersihkan kata 'Tuan' / 'Tuhan' / 'tuanya'
    if forbid_tuan:
        if user_addr:
            t = re.sub(r"\b(?:Tuan|tuan|Tuhan|tuanya)\b", user_addr, t)
        else:
            t = re.sub(r"\b(?:Tuan|tuan|Tuhan|tuanya)\b\s*,?", "", t)
            t = re.sub(r"\s{2,}", " ", t).strip()

    # 2. Terapkan custom suffix jika ada di memori
    suffix = mem.get("custom_suffix")
    if suffix and t:
        suf_clean = suffix.strip()
        if not t.rstrip(".!?, ").lower().endswith(suf_clean.lower()):
            m_punct = re.search(r"([.!?]+)$", t)
            punct = m_punct.group(1) if m_punct else ""
            t_base = t[:len(t)-len(punct)].rstrip()
            t = f"{t_base} {suf_clean}{punct if punct else ''}"
    return t


def is_end_cmd(t):
    if not t:
        return False
    clean = t.strip().lower()
    if any(q in clean for q in ("kenapa", "mengapa", "berapa", "apakah", "bagaimana", "gimana", "siapa")):
        return False
    return bool(END_CMD_RE.search(clean))


SLEEP_CMD_RE = re.compile(
    r"\b("
    r"(?:kamu|lo|lu|kau|engkau)?\s*(?:bisa|boleh|silakan|ayo|pergi|masuk|saatnya|waktunya|mau)?\s*(?:ke\s+)?(?:mode\s+)?(?:tidur|sleep|istirahat)\b|"
    r"(?:tidur|sleep|istirahat)\s*(?:dulu|kamu|ya|sana|lah)\b|"
    r"selamat\s+tidur|met\s+tidur|"
    r"tidur"
    r")\b",
    re.IGNORECASE,
)


def is_sleep_cmd(t):
    """Mendeteksi perintah tidur: 'kamu tidur', 'tidurlah', 'mode sleep', 'istirahat dulu', dsb."""
    if not t:
        return False
    t_clean = t.strip().lower()
    # Pertanyaan informasi tentang tidur tidak boleh dianggap sebagai perintah masuk mode sleep
    if any(q in t_clean for q in ("kenapa", "mengapa", "berapa", "apakah", "bagaimana", "gimana", "siapa")):
        return False
    return bool(SLEEP_CMD_RE.search(t_clean))


def has_wake_word(t):
    """Cocokkan kata panggil 'sayang' atau 'bymax'/'baymax' (beserta variasi STT); tolak 'saya'/'sayangnya'."""
    return bool(WAKE_RE.search(t or ""))


def is_bymax_wake(t):
    """True jika kata panggil yang diucapkan adalah 'bymax'/'baymax' (bukan 'sayang')."""
    return bool(BYMAX_RE.search(t or "")) and not bool(SAYANG_RE.search(t or ""))


def is_sleep_wake(t):
    """Mengecek apakah suara user saat mode sleep memenuhi syarat bangun:
    Hanya bangun ketika memanggil: nama dia (Bymax/Baymax), sayang, atau kata bangun.
    Tidak boleh lainnya (abaikan perintah tidur, stop, dan obrolan lainnya)."""
    if not t:
        return False
    t_clean = t.strip().lower()
    # Jika mengandung kata bangun eksplisit, izinkan bangun
    if BANGUN_RE.search(t_clean):
        return True
    # Jika tidak ada kata bangun, tolak semua perintah tidur, stop, dan penutup
    if re.search(r"\b(tidur|istirahat|bobok|rehat|berhenti|stop|matikan|selesai|tutup|cukup)\b", t_clean):
        return False
    if is_sleep_cmd(t_clean) or is_end_cmd(t_clean):
        return False
    return bool(BYMAX_RE.search(t_clean) or SAYANG_RE.search(t_clean))


def strip_wake_word(t):
    """Ambil isi pertanyaan setelah kata panggil ('sayang'/'bymax'/'bangun') dihapus."""
    s = WAKE_RE.sub("", t or "", count=1)
    s = BANGUN_RE.sub("", s).strip()
    return re.sub(r"^[\s,.:;!?-]+", "", s).strip()


def is_no_reply(t):
    t = re.sub(r"[^\w\s]", " ", (t or "").lower()).strip()
    words = t.split()
    return bool(words) and len(words) <= 5 and any(k in t for k in NO_WORDS)


def time_context():
    now = datetime.now()
    suasana = (
        "pagi" if 4 <= now.hour < 11 else
        "siang" if 11 <= now.hour < 15 else
        "sore" if 15 <= now.hour < 18 else
        "malam"
    )
    return f"[Waktu server saat ini: {now.strftime('%H:%M')} ({suasana}), tanggal {now.strftime('%Y-%m-%d')}.]"


def ask(q, extra_instruction=""):
    apply_heuristic_safety(q)
    mem = load_memory()
    user_addr = get_active_call_name()
    forbid_tuan = mem.get("forbid_tuan") or bool(user_addr)
    if user_addr:
        addr_rule = (
            f"DILARANG KERAS memanggil 'Tuan'. Panggil user dengan nama/sebutan '{user_addr}'. "
            f"Jika dalam mode sayang, panggil 'sayang {user_addr}' atau '{user_addr}'."
        )
    elif forbid_tuan:
        addr_rule = "DILARANG KERAS memanggil 'Tuan'/'Tuhan'/'tuanya'. Panggil user secara santai dan netral atau 'kamu'."
    elif current_call_address == "Tuan":
        addr_rule = "Panggil user secara santai dan netral. Jangan gunakan kata 'Tuan'."
    else:
        addr_rule = "Panggil user dengan panggilan akrab 'sayang' atau santai. DILARANG memanggil 'Tuan'."

    topic_rule = (
        "Wajib ikuti topik yang sedang dibicarakan user saat ini. "
        "Tanggapi isi perkataannya secara relevan, nyambung, dan santai. "
        "Jika ada kata typo atau rancu dari mikrofon, tebak maksudnya dengan ramah dan pemaaf, jangan mendebat atau menanyakan kata typo tersebut. "
        "Jangan buat topik baru atau menanyakan hal yang melenceng."
    )
    cognitive_rule = (
        "[KEMAMPUAN OTONOM MEMORI ASISTEN]:\n"
        "Analisis maksud user. Jika user mengenalkan nama, minta panggilan khusus, melarang sapaan (seperti 'tuan'), "
        "minta imbuhan akhir kata, meminta respon saat dipanggil, menyimpan fakta penting, ATAU meminta diingatkan jadwal/tugas (reminder), "
        "sertakan blok JSON berikut sebelum jawaban lisanmu (buat isi 'thought' ringkas 1 kalimat):\n"
        "<<<MEMORY_UPDATE>>>\n"
        "{\n"
        '  "thought": "penalaran ringkas 1 kalimat",\n'
        '  "user_name": "nama user atau null",\n'
        '  "call_sign": "panggilan yang diminta atau null",\n'
        '  "forbid_tuan": true/false,\n'
        '  "custom_suffix": "imbuhan akhir atau null",\n'
        '  "custom_wake_reply": "jawaban saat dipanggil atau null",\n'
        '  "add_fact": "fakta atau null",\n'
        '  "add_reminder": {"time": "HH:MM", "task": "kegiatan"} atau null,\n'
        '  "reset_memory": false\n'
        "}\n"
        "<<<END_MEMORY_UPDATE>>>\n"
        "PENTING: Jangan hanya menulis blok JSON! Setelah blok <<<END_MEMORY_UPDATE>>>, kamu WAJIB menuliskan 1-2 kalimat jawaban lisan langsung untuk diucapkan kepada user."
    )
    mem_context = format_memory_context()
    full_extra = f"{addr_rule}\n{topic_rule}\n{mem_context}\n{cognitive_rule}\n{extra_instruction}".strip()
    user_msg = f"{time_context()} {q}\n[Instruksi tambahan: {full_extra}]".strip()
    raw_content = ""
    try:
        r = http_session.post(
            OLLAMA_URL,
            headers={"Authorization": "Bearer " + os.environ["OLLAMA_API_KEY"]},
            json={
                "model": OLLAMA_MODEL,
                "stream": False,
                "think": False,
                "options": {"num_predict": 250, "temperature": 0.8, "repeat_penalty": 1.2},
                "messages": [{"role": "system", "content": SYSTEM}] + history[-10:] + [
                    {"role": "user", "content": user_msg}
                ]
            },
            timeout=60
        )
        r.raise_for_status()
        raw_content = r.json()["message"]["content"]
    except Exception as e:
        print("[WARN] Ollama ask gagal:", e)

    if raw_content:
        spoken_part = parse_and_apply_llm_memory(raw_content)
        t = clean_response(spoken_part)
    else:
        # Fallback lokal jika Ollama offline
        t = clean_response(apply_heuristic_safety(q, return_reply=True) or "")

    if not t:
        t = "Hmm, barusan suaranya agak putus-putus di tempatku, boleh ulangi sekali lagi?"
    history.append({"role": "user", "content": q})
    history.append({"role": "assistant", "content": t})
    return t


def generate_spontaneous(instruction, fallback=None):
    now = datetime.now()
    suasana = (
        "pagi" if 4 <= now.hour < 11 else
        "siang" if 11 <= now.hour < 15 else
        "sore" if 15 <= now.hour < 18 else
        "malam"
    )
    avoid = ""
    if recent_spontaneous:
        avoid = " JANGAN gunakan kalimat atau pembuka yang mirip dengan ucapanmu baru-baru ini: " + " | ".join(
            f'"{s}"' for s in recent_spontaneous[-4:]
        ) + "."
    user_addr = get_active_call_name()
    addr_note = f" Panggil user dengan '{user_addr}'. DILARANG panggil 'Tuan'." if user_addr else " DILARANG panggil 'Tuan'."
    prompt = (
        f"[Konteks waktu: {suasana}. Situasi: {instruction}{avoid}{addr_note} "
        f"Ucapkan langsung 1-2 kalimat lisan yang segar, cerdas, dan tidak template.]"
    )
    try:
        r = http_session.post(
            OLLAMA_URL,
            headers={"Authorization": "Bearer " + os.environ["OLLAMA_API_KEY"]},
            json={
                "model": OLLAMA_MODEL,
                "stream": False,
                "think": False,
                "options": {"num_predict": 90, "temperature": 0.9, "repeat_penalty": 1.25},
                "messages": [{"role": "system", "content": SYSTEM}] + history[-6:] + [
                    {"role": "user", "content": prompt}
                ]
            },
            timeout=30
        )
        r.raise_for_status()
        t = clean_response(r.json()["message"]["content"])
    except Exception as e:
        print("[WARN] Ollama spontaneous gagal:", e)
        t = ""
    if not t:
        t = fallback or random.choice(SILENT_FALLBACKS)
    recent_spontaneous.append(t)
    if len(recent_spontaneous) > 8:
        recent_spontaneous.pop(0)
    # Simpan ke history dengan konteks ringkas agar obrolan berikutnya nyambung tanpa merusak gaya bahasa
    history.append({"role": "user", "content": "(hening sejenak)"})
    history.append({"role": "assistant", "content": t})
    return t


def _pcm_16k_stereo(raw_bytes):
    a = np.frombuffer(raw_bytes, np.int16).astype(np.float32)
    if len(a) == 0:
        return b""
    n = int(len(a) * 16000 / piper_rate)
    a = np.interp(np.linspace(0, len(a) - 1, n), np.arange(len(a)), a).astype(np.int16)
    return np.repeat(a, 2).tobytes()


def _edge_tts_chunks(text):
    """Sintesis suara perempuan natural via Microsoft Edge-TTS (id-ID-GadisNeural) dan streaming PCM 16kHz stereo."""
    async def _fetch():
        comm = edge_tts.Communicate(text, EDGE_TTS_VOICE, rate="+4%", pitch="+0Hz")
        mp3 = bytearray()
        async for chunk in comm.stream():
            if chunk["type"] == "audio":
                mp3.extend(chunk["data"])
        return mp3

    mp3_data = asyncio.run(_fetch())
    if not mp3_data:
        return
    container = av.open(io.BytesIO(mp3_data))
    resampler = av.AudioResampler(format="s16", layout="stereo", rate=16000)
    for frame in container.decode(audio=0):
        for rf in resampler.resample(frame):
            yield rf.to_ndarray().tobytes()


def tts_chunks(text):
    """Sintesis kalimat per kalimat. Gunakan Edge-TTS suara cewek jika online/aktif,
    otomatis fallback ke Piper offline di RAM bila offline atau bermasalah."""
    if not text or not text.strip():
        text = "Hmm."

    if HAS_EDGE_TTS and TTS_ENGINE == "edge":
        try:
            yielded = False
            for pcm in _edge_tts_chunks(text):
                yielded = True
                yield pcm
            if yielded:
                return
        except Exception as e:
            print(f"[TTS-WARN] Edge-TTS error ({e}), beralih ke Piper TTS...")

    # Fallback offline Piper TTS di RAM
    if tts_voice:
        syn_cfg = SynthesisConfig(length_scale=0.92, noise_scale=0.667, noise_w_scale=0.8) if SynthesisConfig else None
        synth_kwargs = {"syn_config": syn_cfg} if syn_cfg else {}
        for chunk in tts_voice.synthesize(text, **synth_kwargs):
            pcm = _pcm_16k_stereo(chunk.audio_int16_bytes)
            if pcm:
                yield pcm


def tts(text):
    return b"".join(tts_chunks(text))


def drain_recv(c):
    """Kuras sisa paket mic yang masih terbang di TCP buffer agar tidak memicu TCP RST saat sesi ditutup."""
    try:
        c.settimeout(0.15)
        while c.recv(4096):
            pass
    except (socket.timeout, OSError, AttributeError):
        pass
    try:
        c.settimeout(15)
    except (OSError, AttributeError):
        pass


def send_audio_and_maybe_listen(c, ans, force_listen=False, allow_question=True, sleep=False):
    global last_interaction
    # Jika sleep, kirim flag 'S' agar ESP32 masuk Modem-Sleep setelah selesai memutar audio
    if sleep:
        expect_reply = False
        flag = b"S"
    else:
        # Jika sesi masih lanjut, buka mic ('L') saat force_listen atau ada tanda tanya '?'
        expect_reply = bool(force_listen or (allow_question and "?" in ans))
        flag = b"L" if expect_reply else b"N"
    sent_any = False
    play_end_t = time.time()
    try:
        for chunk in tts_chunks(ans):
            now = time.time()
            if not sent_any:
                c.sendall(flag + chunk)
                play_end_t = now + (len(chunk) / 64000.0)
                sent_any = True
            else:
                c.sendall(chunk)
                play_end_t = max(now, play_end_t) + (len(chunk) / 64000.0)
        if not sent_any:
            return False
        rem_sec = max(0.0, play_end_t - time.time())
        if not expect_reply:
            # Tunggu sisa audio selesai diputar di ESP32 sebelum menutup koneksi (mencegah suara terpotong)
            try:
                c.settimeout(rem_sec + 0.35)
                c.recv(1)
            except (socket.timeout, OSError, AttributeError):
                pass
        else:
            try:
                c.settimeout(max(15.0, rem_sec + 12.0))
            except (OSError, AttributeError):
                pass
    except OSError:
        print("[INFO] Koneksi ditutup ESP32 saat memutar suara")
        return False
    last_interaction = time.time()
    return expect_reply


def conversation_loop(c, max_turns=0, keep_listening=False):
    global last_interaction
    turns = 0
    while not max_turns or turns < max_turns:
        pcm = record(c)
        try:
            c.sendall(b"S")  # Beritahu ESP32 berhenti merekam
        except OSError:
            break
        drain_recv(c)  # Buang sisa paket mic di buffer agar socket bersih
        last_interaction = time.time()
        text = transcribe(pcm) if pcm else ""
        print("\nKamu:", text)
        if not text:
            # Jika user tidak menjawab / diam, AI menegur manja ("kamu cuek ya...") lalu akhiri sesi
            cuek = generate_spontaneous(SILENT_PROMPT, fallback=random.choice(SILENT_FALLBACKS))
            cuek = clean_response(cuek)
            print("AI  :", cuek)
            send_audio_and_maybe_listen(c, cuek, force_listen=False, allow_question=False)
            break
        user_addr = get_active_call_name()
        if is_sleep_cmd(text):
            print(f"[CMD] Masuk mode sleep lewat perintah suara: {text!r}")
            if current_call_address == "Tuan":
                addr_txt = f" {user_addr}" if user_addr else ""
                sahut = f"Baik{addr_txt}, saya akan masuk mode tidur. Panggil jika butuh bantuan."
            else:
                sahut = f"Iya sayang {user_addr}, aku tidur dulu ya. Panggil aku lagi kalau butuh." if user_addr else "Iya sayang, aku tidur dulu ya. Panggil aku lagi kalau butuh."
            sahut = clean_response(sahut)
            print("AI  :", sahut)
            send_audio_and_maybe_listen(c, sahut, force_listen=False, allow_question=False, sleep=True)
            break
        if is_end_cmd(text) or is_no_reply(text):
            print(f"[CMD] Sesi diakhiri lewat perintah suara: {text!r}")
            if current_call_address == "Tuan":
                addr_txt = f" {user_addr}" if user_addr else ""
                pamit = f"Baik{addr_txt}, sesi percakapan selesai. Saya kembali siaga."
            else:
                pamit = f"Yaudah kalau gitu kita istirahat dulu ya {user_addr}, panggil aku lagi kalau butuh." if user_addr else "Yaudah kalau gitu kita istirahat dulu ya, panggil aku lagi kalau butuh."
            pamit = clean_response(pamit)
            print("AI  :", pamit)
            send_audio_and_maybe_listen(c, pamit, force_listen=False, allow_question=False)
            break
        # Cek perintah radio dulu sebelum tanya AI
        radio_res = process_radio_command(text)
        if radio_res[0] == "play":
            action, station, msg = radio_res
            print(f"[RADIO-CMD] {msg}")
            send_audio_and_maybe_listen(c, msg, force_listen=False, allow_question=False)
            stream_radio_to_client(c, station)
            break  # Radio stream mengambil alih koneksi
        elif radio_res[0] == "stop":
            action, station, msg = radio_res
            print(f"[RADIO-CMD] {msg}")
            send_audio_and_maybe_listen(c, msg, force_listen=False, allow_question=False)
            # Lanjut ke obrolan biasa
        elif radio_res[0] == "info":
            action, station, msg = radio_res
            print(f"[RADIO-CMD] {msg}")
            send_audio_and_maybe_listen(c, msg, force_listen=False, allow_question=False)
            # Lanjut ke obrolan biasa


        ans = ask(text)
        print("AI  :", ans)
        if not ans:
            try:
                c.sendall(b"N")
            except OSError:
                pass
            break
        turns += 1
        if max_turns and turns >= max_turns:
            # Siklus auto selesai: tutup dengan gumaman, tanpa pertanyaan
            closing = generate_spontaneous(CLOSE_PROMPT, fallback="Hmm yaudah deh, lanjut nanti lagi ya.")
            closing = clean_response(closing)
            print("AI  :", closing)
            send_audio_and_maybe_listen(c, closing, force_listen=False, allow_question=False)
            break
        # Mode Button: mic lanjut terus; Mode Auto: hanya jika AI bertanya
        expect_reply = send_audio_and_maybe_listen(c, ans, force_listen=keep_listening)
        if not expect_reply:
            break


def panggil_session(c, initial_text, is_from_sleep=False):
    """Mode Panggil ('sayang'/'bymax'/'bangun'): tanya-jawab unlimited selama user merespons; berhenti otomatis saat user diam."""
    global last_interaction, current_call_address
    bymax_mode = is_bymax_wake(initial_text)
    user_addr = get_active_call_name()
    current_call_address = "Tuan" if bymax_mode else "sayang"
    query = strip_wake_word(initial_text)

    # Jika sedang bangun dari tidur, JANGAN proses perintah tidur atau berhenti (abaikan)
    if not is_from_sleep:
        # Cek apakah user menyuruh tidur: "kamu tidur", "tidurlah", dsb.
        if is_sleep_cmd(query or initial_text):
            print(f"[CMD] Masuk mode sleep lewat panggilan suara: {initial_text!r}")
            if bymax_mode:
                addr_txt = f" {user_addr}" if user_addr else ""
                sahut = f"Baik{addr_txt}, saya akan masuk mode tidur. Panggil jika butuh bantuan."
            else:
                sahut = f"Iya sayang {user_addr}, aku tidur dulu ya. Panggil aku lagi kalau butuh." if user_addr else "Iya sayang, aku tidur dulu ya. Panggil aku lagi kalau butuh."
            sahut = clean_response(sahut)
            print("AI  :", sahut)
            send_audio_and_maybe_listen(c, sahut, force_listen=False, allow_question=False, sleep=True)
            return

        # Cek apakah user menyuruh berhenti sesi: "berhenti sesion", "stop sesi", dsb.
        if is_end_cmd(query or initial_text):
            print(f"[CMD] Sesi diakhiri lewat panggilan suara: {initial_text!r}")
            if bymax_mode:
                addr_txt = f" {user_addr}" if user_addr else ""
                pamit = f"Baik{addr_txt}, sesi percakapan selesai. Saya kembali siaga."
            else:
                pamit = f"Iya sayang {user_addr}, kita berhenti ngobrol dulu ya. Panggil aku lagi kalau butuh." if user_addr else "Iya sayang, kita berhenti ngobrol dulu ya. Panggil aku lagi kalau butuh."
            pamit = clean_response(pamit)
            print("AI  :", pamit)
            send_audio_and_maybe_listen(c, pamit, force_listen=False, allow_question=False)
            return

    mem = load_memory()
    if not query:
        custom_wake = mem.get("custom_wake_reply")
        if is_from_sleep or BANGUN_RE.search(initial_text):
            if bymax_mode:
                sahut = f"Baik {user_addr}, saya sudah bangun dan siap membantu. Ada apa?" if user_addr else "Baik, saya sudah bangun dan siap membantu. Ada apa?"
            else:
                sahut = f"Hoam... iya {user_addr}, aku udah bangun kok. Ada apa sayang?" if user_addr else "Hoam... iya, aku udah bangun kok. Ada apa sayang?"
        elif custom_wake and bymax_mode:
            sahut = custom_wake
        elif bymax_mode:
            sahut = f"Iya {user_addr}, ada apa? Ada yang bisa Bymax bantu?" if user_addr else "Iya, ada apa? Ada yang bisa Bymax bantu?"
        else:
            sahut = f"Iya sayang {user_addr}, ada apa? Mau minta bantu atau tanya apa nih?" if user_addr else "Iya sayang, ada apa? Mau minta bantu atau tanya apa nih?"
        sahut = clean_response(sahut)
        print("AI  :", sahut)
        if not send_audio_and_maybe_listen(c, sahut, force_listen=True):
            return
    else:
        # Cek perintah radio dulu sebelum tanya AI
        radio_res = process_radio_command(query)
        if radio_res[0] == "play":
            action, station, msg = radio_res
            print(f"[RADIO-CMD] {msg}")
            send_audio_and_maybe_listen(c, msg, force_listen=False, allow_question=False)
            stream_radio_to_client(c, station)
            return # Radio stream mengambil alih koneksi
        elif radio_res[0] == "stop":
            action, station, msg = radio_res
            print(f"[RADIO-CMD] {msg}")
            send_audio_and_maybe_listen(c, msg, force_listen=False, allow_question=False)
            # Lanjut ke obrolan biasa
        elif radio_res[0] == "info":
            action, station, msg = radio_res
            print(f"[RADIO-CMD] {msg}")
            send_audio_and_maybe_listen(c, msg, force_listen=False, allow_question=False)
            # Lanjut ke obrolan biasa

        ans = ask(
            query,
            extra_instruction="Tanggapi topik user ini secara santai, cerdas, dan natural. Tetap fokus pada apa yang dibicarakan user."
        )
        print("AI  :", ans)
        if not send_audio_and_maybe_listen(c, ans, force_listen=True):
            return

    # Lanjutkan tanya-jawab tanpa batas (unlimited) sampai user tidak merespons / mengakhiri
    conversation_loop(c, max_turns=WAKE_MAX_TURNS, keep_listening=True)


srv = socket.socket()
srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
srv.bind(("0.0.0.0", PORT))
srv.listen(1)
print("Server Asisten Cewek siap di port", PORT)
is_idle = False  # Tambahkan ini untuk melacak status hening

while True:
    c, addr = srv.accept()
    c.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
    c.settimeout(15)
    try:
        cmd = c.recv(1)
        
        if cmd == b"B":
            is_idle = False  # Sedang ngobrol manual, matikan idle
            last_interaction = time.time()
            conversation_loop(c, keep_listening=True)

        elif cmd == b"W":
            is_idle = False  # Sedang ngobrol boot, matikan idle
            user_addr = get_active_call_name()
            sapaan_nama = f" {user_addr}" if user_addr else ""
            ans = f"Halo{sapaan_nama}, aku udah siap nemenin kamu. Kalau butuh ngobrol, tekan tombol untuk komunikasi ya."
            ans = clean_response(ans)
            print(f"\n[BOOT] Menyapa: {ans}")
            send_audio_and_maybe_listen(c, ans, force_listen=False, allow_question=False)
            last_interaction = time.time()

        elif cmd == b"K":
            # Mode Panggil Standby: rekam suara pemicu + kelanjutannya selama user bicara.
            # JANGAN kirim ke Ollama jika tidak ada kata panggil "sayang"/"bymax"/"bangun" atau perintah tidur.
            pcm = record(c, wait_sec=4.0, max_sec=WAKE_MAX_SEC)
            try:
                c.sendall(b"S")
            except OSError:
                continue
            drain_recv(c)
            text = transcribe(pcm) if len(pcm) >= 8000 else ""
            if not has_wake_word(text) and not is_sleep_cmd(text) and not is_end_cmd(text):
                print(f"\n[WAKE-SKIP] Bukan kata panggil / perintah tidur / berhenti (abaikan, tidak kirim ke Ollama): {text!r}")
                try:
                    c.sendall(b"Z")
                except OSError:
                    pass
            else:
                is_idle = False
                last_interaction = time.time()
                print(f"\n[WAKE] Terdeteksi panggilan / perintah: {text}")
                panggil_session(c, text)
                last_interaction = time.time()

        elif cmd == b"S":
            # Mode Bangun dari Sleep: saat tidur, HANYA bangun jika dipanggil nama dia, sayang, atau bangun.
            # Sama sekali tidak boleh bangun untuk perintah tidur/stop/obrolan lain/noise.
            pcm = record(c, wait_sec=4.0, max_sec=WAKE_MAX_SEC)
            try:
                c.sendall(b"S")
            except OSError:
                continue
            drain_recv(c)
            text = transcribe(pcm) if len(pcm) >= 8000 else ""
            if not is_sleep_wake(text):
                print(f"\n[SLEEP-SKIP] Saat mode tidur, hanya bangun jika dipanggil nama/sayang/bangun (abaikan): {text!r}")
                try:
                    c.sendall(b"Z")
                except OSError:
                    pass
            else:
                is_idle = False
                last_interaction = time.time()
                print(f"\n[SLEEP-WAKE] Bangun dari tidur karena panggilan sah: {text}")
                panggil_session(c, text, is_from_sleep=True)
                last_interaction = time.time()

        elif cmd == b"P":
            now = datetime.now()
            now_ts = time.time()

            # PRIORITAS #1 MUTLAK: CEK JADWAL / PENGINGAT (REMINDER)
            due_reminders = check_due_reminders(now)
            if due_reminders:
                is_idle = False
                last_interaction = now_ts
                name = get_active_call_name()
                panggilan = f" {name}" if name else ""

                tasks = [r.get("task", "") for r in due_reminders if r.get("task")]
                tasks_text = ", ".join(tasks)
                hm_str = due_reminders[0].get("time", now.strftime("%H:%M"))

                instruksi_remind = (
                    f"PENTING DAN MENDESAK: Sekarang tepat jam {hm_str}. "
                    f"User meminta untuk diingatkan: '{tasks_text}'. "
                    f"Ingatkan{panggilan} sekarang dengan hangat, ramah, santai, dan tegas bahwa sekarang saatnya {tasks_text}. "
                    f"Jangan bertele-tele, maksimal 1-2 kalimat alami."
                )
                print(f"\n[REMINDER ALARM {hm_str}] Mengingatkan jadwal: {tasks_text}")
                ans = generate_spontaneous(instruksi_remind)
                ans = clean_response(ans)
                print("AI  :", ans)
                if send_audio_and_maybe_listen(c, ans, force_listen=True):
                    conversation_loop(c, AUTO_MAX_TURNS, keep_listening=True)
                continue

            if not is_idle:
                # ESP32 baru saja selesai proses/mutar suara dan mulai Standby.
                # RESET timer ke detik INI, agar dia murni menunggu 30 detik hening.
                is_idle = True
                last_interaction = now_ts
                c.sendall(b"Z")
            else:
                # ESP32 sudah benar-benar sedang Standby, cek timer
                if now.minute == 0 and now.hour != last_announced_hour:
                    last_announced_hour = now.hour
                    is_idle = False
                    jam_12 = now.hour % 12 or 12
                    suasana = "pagi" if 4 <= now.hour < 11 else "siang" if 11 <= now.hour < 15 else "sore" if 15 <= now.hour < 18 else "malam"
                    instruksi_jam = (
                        f"Sekarang tepat jam {jam_12} {suasana}. "
                        f"Kasih tahu jam berapa sekarang dengan singkat, ramah dan santai. "
                        f"Jangan sebut menit atau detik, dan jangan bertanya balik."
                    )
                    print(f"\n[AUTO-JAM {now.strftime('%H:%M')}] Menyapa...")
                    ans = generate_spontaneous(instruksi_jam)
                    print("AI  :", ans)
                    send_audio_and_maybe_listen(c, ans, force_listen=False, allow_question=False)

                elif now_ts - last_interaction >= IDLE_INTERVAL:
                    is_idle = False  # Matikan idle selama dia ngomong otomatis
                    last_interaction = now_ts
                    instruksi_mood, minta_jawab = pick_idle_mood()
                    print(f"\n[AUTO-30s] Mood aktif (Auto-Mic: {minta_jawab})...")
                    ans = generate_spontaneous(instruksi_mood)
                    print("AI  :", ans)
                    if send_audio_and_maybe_listen(c, ans, force_listen=minta_jawab):
                        conversation_loop(c, AUTO_MAX_TURNS, keep_listening=True)
                else:
                    sisa = int(IDLE_INTERVAL - (now_ts - last_interaction))
                    print(f"[Standby] Ngomong otomatis dalam {sisa:2d} detik...   ", end="\r")
                    c.sendall(b"Z")
    except Exception as e:
        print("ERR:", e)
    finally:
        try:
            c.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass
        c.close()
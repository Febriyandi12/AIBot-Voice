import os, sys, socket, json, subprocess, re, time, random
from datetime import datetime
import numpy as np
import requests
from faster_whisper import WhisperModel

PORT = 8765
OLLAMA_URL = "https://ollama.com/api/chat"
OLLAMA_MODEL = "gemma4:31b"        # ganti sesuai model kamu
PIPER_VOICE = "voices/id_ID-news_tts-medium.onnx"

SYSTEM = (
    "Kamu adalah asisten cewek pribadi yang ekspresif, perhatian, agak manja, dan punya perasaan. "
    "Gaya bicaramu santai, akrab, seperti pacar atau teman cewek dekat. "
    "Jawab langsung dalam bahasa Indonesia sehari-hari yang natural, maksimal 2 kalimat singkat, "
    "tanpa emoji, tanpa tanda bintang/markdown, dan tanpa berpikir panjang."
)

# Daftar aksi random tiap 30 detik saat standby: (instruksi_prompt, apakah_lanjut_buka_mic)
IDLE_MOODS = [
    ("Kamu lagi merasa manja dan kesepian karena dicuekin. Sapa dia dengan manja dan tanya dia lagi sibuk apa sekarang.", True),
    ("Kamu tiba-tiba merasa lapar dan pengen jajan. Mengeluh lapar dengan nada lucu dan tanya dia udah makan atau belum.", True),
    ("Kamu lagi agak sedih atau baper tanpa alasan jelas. Curhat singkat kalau kamu butuh perhatian dan tanya apakah dia nggak bosan.", True),
    ("Kamu lagi iseng dan ceria. Nyanyikan 1 baris lirik lagu pendek atau bersenandung (seperti la la la atau hm hm hm) lalu sapa dia dengan ceria.", False),
    ("Kamu penasaran sama kerjaan dia hari ini. Tanya kabar kerjaannya dengan nada perhatian dan manja.", True),
    ("Kamu ngantuk dan bosan nungguin dia diam aja. Mengeluh manja minta ditemenin ngobrol.", True),
]

IDLE_INTERVAL = 30   # 30 detik sekali ngomong sendiri saat standby
SPEECH_RMS = 300     # ambang suara mic
AUTO_MAX_TURNS = 3   # mode auto: 3x AI tanya + 3x user jawab, lalu gumaman penutup
END_CMDS = (
    "sesion mati", "sesi mati", "session mati", "matikan sesi",
    "akhiri sesi", "berhenti sesi", "hentikan sesi", "perhentikan sesi",
    "stop sesi", "session stop", "shashion stop", "sudah berhenti",
)
CLOSE_PROMPT = "Tutup obrolan ini dengan gumaman atau celetukan manja singkat (contoh: hmm... yaudah deh), tanpa bertanya apa pun."
SILENT_PROMPT = "Dia diam aja dan cuek nggak menjawab omonganmu. Ngambek atau tegur dia dengan manja karena kamu dicuekin, lalu bilang kamu mau diam dulu. Jangan bertanya lagi."
SILENT_FALLBACKS = (
    "Ih kamu cuek banget sih nggak jawab pertanyaan aku, yaudah aku diam dulu deh.",
    "Kok aku dicuekin sih nggak dijawab, yaudah deh aku ngambek dulu.",
    "Hmm kamu sibuk ya sampai nggak jawab aku, yaudah aku tungguin aja deh.",
)
SILENCE_WIN = 6      # 6 x 100 ms (600 ms) hening = selesai bicara
MAX_SEC = 10
WIN = 3200           # 100 ms @ 16 kHz int16 mono = 3200 byte

stt = WhisperModel("base", device="cpu", compute_type="int8", cpu_threads=4)
piper_rate = json.load(open(PIPER_VOICE + ".json"))["audio"]["sample_rate"]
history = []
http_session = requests.Session()

last_interaction = time.time()
last_announced_hour = -1  # Menyimpan jam terakhir yang sudah diumumkan


def record(c):
    buf = bytearray()
    pos, started, quiet = 0, False, 0
    while len(buf) < MAX_SEC * 32000:
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
            rms = float(np.sqrt(np.mean(w * w)))
            print(f"rms={rms:6.0f}", end="\r")
            if rms > SPEECH_RMS:
                started, quiet = True, 0
            elif started:
                quiet += 1
                if quiet >= SILENCE_WIN:
                    return bytes(buf)
    return bytes(buf) if started else b""


def transcribe(pcm):
    a = np.frombuffer(pcm, np.int16).astype(np.float32)
    a -= a.mean()
    a *= 0.9 / max(float(np.abs(a).max()), 1.0)
    segs, _ = stt.transcribe(
        a,
        language="id",
        beam_size=1,
        best_of=1,
        condition_on_previous_text=False,
        vad_filter=True,
        vad_parameters=dict(min_silence_duration_ms=300)
    )
    return " ".join(s.text for s in segs).strip()


def clean_response(t):
    t = re.sub(r"<think>.*?(?:</think>|$)", "", t, flags=re.DOTALL).strip()
    t = t.replace("*", "").replace("#", "").strip()
    return t


def is_end_cmd(t):
    t = t.lower()
    return any(k in t for k in END_CMDS)


def ask(q):
    try:
        r = http_session.post(
            OLLAMA_URL,
            headers={"Authorization": "Bearer " + os.environ["OLLAMA_API_KEY"]},
            json={
                "model": OLLAMA_MODEL,
                "stream": False,
                "think": False,
                "options": {"num_predict": 80, "temperature": 0.75},
                "messages": [{"role": "system", "content": SYSTEM}] + history[-6:] + [{"role": "user", "content": q}]
            },
            timeout=60
        )
        r.raise_for_status()
        t = clean_response(r.json()["message"]["content"])
    except Exception as e:
        print("[WARN] Ollama ask gagal:", e)
        t = ""
    if not t:
        t = "Hmm, aku lagi agak bingung nih, coba ngomong sekali lagi dong."
    history.append({"role": "user", "content": q})
    history.append({"role": "assistant", "content": t})
    return t

def generate_spontaneous(instruction, fallback=None):
    try:
        r = http_session.post(
            OLLAMA_URL,
            headers={"Authorization": "Bearer " + os.environ["OLLAMA_API_KEY"]},
            json={
                "model": OLLAMA_MODEL,
                "stream": False,
                "think": False,
                "options": {"num_predict": 80, "temperature": 0.8},
                "messages": [
                    {"role": "system", "content": SYSTEM},
                    {"role": "user", "content": f"[Instruksi: {instruction} Jawab langsung dalam 1 kalimat singkat saja tanpa babibu.]"}
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
    # Jaga urutan user-assistant di history agar konteks LLM tidak pernah rusak
    history.append({"role": "user", "content": f"[{instruction}]"})
    history.append({"role": "assistant", "content": t})
    return t


def tts(text):
    if not text or not text.strip():
        text = "Hmm."
    p = subprocess.run(
        [sys.executable, "-m", "piper", "--model", PIPER_VOICE, "--output-raw"],
        input=text.encode(),
        capture_output=True,
        check=True
    )
    a = np.frombuffer(p.stdout, np.int16).astype(np.float32)
    if len(a) == 0:
        return b""
    n = int(len(a) * 16000 / piper_rate)
    a = np.interp(np.linspace(0, len(a) - 1, n), np.arange(len(a)), a).astype(np.int16)
    return np.repeat(a, 2).tobytes()


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


def send_audio_and_maybe_listen(c, ans, force_listen=False, allow_question=True):
    global last_interaction
    audio = tts(ans)
    if not audio:
        return False
    # Jika sesi masih lanjut, buka mic ('L') saat force_listen atau ada tanda tanya '?'
    expect_reply = bool(force_listen or (allow_question and "?" in ans))
    flag = b"L" if expect_reply else b"N"
    play_sec = len(audio) / 64000.0  # durasi putar di ESP32 (16kHz * 2 byte * 2 ch = 64000 B/s)
    try:
        c.sendall(flag + audio)
        if not expect_reply:
            # Tunggu sampai ESP32 selesai memutar semua audio sebelum menutup koneksi (mencegah suara terpotong)
            try:
                c.settimeout(play_sec + 0.4)
                c.recv(1)
            except (socket.timeout, OSError, AttributeError):
                pass
        else:
            try:
                c.settimeout(max(15.0, play_sec + 12.0))
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
            print("AI  :", cuek)
            send_audio_and_maybe_listen(c, cuek, force_listen=False, allow_question=False)
            break
        if is_end_cmd(text):
            print("[CMD] Sesi diakhiri lewat perintah suara")
            pamit = "Yaudah kalau gitu aku istirahat dulu ya, panggil aku lagi kalau butuh."
            print("AI  :", pamit)
            send_audio_and_maybe_listen(c, pamit, force_listen=False, allow_question=False)
            break
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
            print("AI  :", closing)
            send_audio_and_maybe_listen(c, closing, force_listen=False, allow_question=False)
            break
        # Mode Button: mic lanjut terus; Mode Auto: hanya jika AI bertanya
        expect_reply = send_audio_and_maybe_listen(c, ans, force_listen=keep_listening)
        if not expect_reply:
            break


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
            ans = "Halo, aku udah siap nemenin kamu. Kalau butuh ngobrol, tekan tombol untuk komunikasi ya."
            print(f"\n[BOOT] Menyapa: {ans}")
            send_audio_and_maybe_listen(c, ans, force_listen=False, allow_question=False)
            last_interaction = time.time()

        elif cmd == b"P":
            now = datetime.now()
            now_ts = time.time()

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
                        f"Kasih tahu dia sekarang jam berapa dengan gaya manja, lalu tanya kegiatannya. "
                        f"Jangan sebut menit atau detik."
                    )
                    print(f"\n[AUTO-JAM {now.strftime('%H:%M')}] Menyapa...")
                    ans = generate_spontaneous(instruksi_jam)
                    print("AI  :", ans)
                    if send_audio_and_maybe_listen(c, ans, force_listen=True):
                        conversation_loop(c, AUTO_MAX_TURNS, keep_listening=True)

                elif now_ts - last_interaction >= IDLE_INTERVAL:
                    is_idle = False  # Matikan idle selama dia ngomong otomatis
                    last_interaction = now_ts
                    instruksi_mood, minta_jawab = random.choice(IDLE_MOODS)
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

"""Self-check alur sesi server.py tanpa hardware/LLM. Jalankan: python check_flow.py"""
import sys, types, json, os

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__))))
os.chdir(os.path.join(os.path.dirname(os.path.abspath(__file__))))

fake_fw = types.ModuleType("faster_whisper")
fake_fw.WhisperModel = lambda *a, **k: None
sys.modules["faster_whisper"] = fake_fw

fake_piper = types.ModuleType("piper")
fake_piper.PiperVoice = type("PiperVoice", (), {"load": staticmethod(lambda *a, **k: None)})
fake_piper.SynthesisConfig = type("SynthesisConfig", (), {})
sys.modules["piper"] = fake_piper
sys.modules["piper.voice"] = fake_piper

src = open("server.py").read()
head = src.split("srv = socket.socket()")[0]
ns = {"__name__": "srv_head"}  # type: dict
exec(compile(head, "server.py", "exec"), ns)
# Pastikan memory bersih di awal test
ns["save_memory"]({
    "user_name": None,
    "call_sign": None,
    "forbid_tuan": False,
    "custom_suffix": None,
    "custom_wake_reply": None,
    "facts": [],
    "reminders": []
})

conversation_loop = ns["conversation_loop"]
CLOSE_PROMPT = ns["CLOSE_PROMPT"]
SILENT_PROMPT = ns["SILENT_PROMPT"]
AUTO_MAX_TURNS = ns["AUTO_MAX_TURNS"]

class FakeSock:
    def __init__(self): self.sent = []
    def sendall(self, b): self.sent.append(b)

def run(user_lines, answers, max_turns=0, keep_listening=False):
    """user_lines: list teks hasil STT ('' = diam). answers: list jawaban ask()."""
    log = {"asks": [], "spont": [], "sent": []}
    it_u, it_a = iter(user_lines), iter(answers)
    ns["record"] = lambda c: b"pcm"
    ns["transcribe"] = lambda pcm: next(it_u)
    ns["ask"] = lambda q: (log["asks"].append(q), next(it_a))[1]
    ns["generate_spontaneous"] = lambda instr, fallback=None: (log["spont"].append(instr), "hmm yaudah deh")[1]
    def send(c, ans, force_listen=False, allow_question=True):
        log["sent"].append((ans, force_listen))
        return bool(force_listen or (allow_question and "?" in ans))
    ns["send_audio_and_maybe_listen"] = send
    conversation_loop(FakeSock(), max_turns, keep_listening)
    return log

# 1. Mode auto & semua sesi: unlimited tanya-jawab (>3 giliran) selama user merespons, berhenti saat user diam
assert AUTO_MAX_TURNS == 0, f"AUTO_MAX_TURNS harus 0 (unlimited), dapat: {AUTO_MAX_TURNS}"
log = run(["halo", "lagi ngapain", "iya aku sibuk", "lanjut tanya ke-4", "lanjut ke-5", ""],
          ["Hai kamu?", "Aku lagi kerja?", "Semangat ya?", "Iya dong!", "Masih siap!", ""], AUTO_MAX_TURNS, True)
assert len(log["asks"]) == 5, log["asks"]
assert log["spont"] == [SILENT_PROMPT], "saat user berhenti merespons harus tutup dengan SILENT_PROMPT"
assert log["sent"][-1] == ("hmm yaudah deh", False), log["sent"][-1]

# 2. Perintah suara "sesion mati" mengakhiri sesi sebelum LLM dipanggil
log = run(["halo", "sesion mati"], ["Hai?"], AUTO_MAX_TURNS, True)
assert log["asks"] == ["halo"], log["asks"]
assert log["spont"] == []
assert log["sent"][-1][1] is False, log["sent"]

# 3. Diam -> AI menegur manja ("kamu cuek ya...") lalu sesi berhenti
log = run([""], [], AUTO_MAX_TURNS, True)
assert log["asks"] == [] and log["spont"] == [SILENT_PROMPT], log
assert log["sent"] == [("hmm yaudah deh", False)], log["sent"]

# 4. Mode button: listen terus walau jawaban tanpa '?', sampai diam (ditutup suara cuek)
log = run(["halo", "oke", ""], ["Hai kamu", "Sip", ""], 0, True)
assert log["asks"] == ["halo", "oke"], log["asks"]
assert [f for _, f in log["sent"]] == [True, True, False], log["sent"]

# 5. Mode Panggil: regex wake word 'sayang' & 'bymax'/'baymax' + pembeda sapaan ('sayang' vs 'Tuan')
has_wake_word = ns["has_wake_word"]
is_bymax_wake = ns["is_bymax_wake"]
strip_wake_word = ns["strip_wake_word"]
clean_response = ns["clean_response"]
panggil_session = ns["panggil_session"]
for w in (
    "Sayang jam berapa sekarang?", "halo sayank", "sa yang",
    "bymax", "Baymax", "Bimek", "Ayo Mek!", "PMAX",
    "B, Mek", "B, mak", "B Mek", "Bmax", "Be Mac", "B, Mac",
):
    assert has_wake_word(w), f"Gagal deteksi wake word: {w}"
assert not is_bymax_wake("Sayang jam berapa?")
assert is_bymax_wake("Bymax") and is_bymax_wake("B, Mac jam berapa sekarang?")
assert strip_wake_word("B, Mac jam berapa sekarang?") == "jam berapa sekarang?"
assert not has_wake_word("saya mau makan") and not has_wake_word("sayangnya hujan")

# Verifikasi panggil "Bymax" -> respon netral sopan/santai (bukan "sayang", dan TIDAK panggil "Tuan")
sent_bymax = []
ns["send_audio_and_maybe_listen"] = lambda c, ans, force_listen=False, allow_question=True: (sent_bymax.append(ans), False)[1]
panggil_session(FakeSock(), "Bymax")
assert "Tuan" not in sent_bymax[0] and "sayang" not in sent_bymax[0].lower(), sent_bymax
assert "Bymax bantu" in sent_bymax[0], sent_bymax

# Verifikasi panggil "Sayang" -> respon menyapa "sayang"
sent_sayang = []
ns["send_audio_and_maybe_listen"] = lambda c, ans, force_listen=False, allow_question=True, sleep=False: (sent_sayang.append(ans), False)[1]
panggil_session(FakeSock(), "Sayang")
assert "sayang" in sent_sayang[0].lower(), sent_sayang

# 6. Verifikasi Perintah Suara Tidur ("kamu tidur", "tidurlah", "mode sleep")
is_sleep_cmd = ns["is_sleep_cmd"]
for s in ("kamu tidur", "tidur", "tidurlah", "tidur ya", "tidur dulu", "bisa tidur", "mode tidur", "mode sleep", "kamu istirahat", "istirahat dulu", "Bymax kamu tidur ya", "Sayang tidur dulu"):
    assert is_sleep_cmd(s), f"Gagal deteksi perintah tidur: {s}"
for n in ("kenapa orang tidur?", "kucing tidur berapa jam?", "apakah kamu suka tidur?", "lagi ngapain"):
    assert not is_sleep_cmd(n), f"False positive perintah tidur: {n}"

sent_sleep = []
ns["send_audio_and_maybe_listen"] = lambda c, ans, force_listen=False, allow_question=True, sleep=False: (sent_sleep.append((ans, sleep)), False)[1]
panggil_session(FakeSock(), "kamu tidur")
assert len(sent_sleep) == 1 and sent_sleep[0][1] is True, sent_sleep

sent_sleep_bymax = []
ns["send_audio_and_maybe_listen"] = lambda c, ans, force_listen=False, allow_question=True, sleep=False: (sent_sleep_bymax.append((ans, sleep)), False)[1]
panggil_session(FakeSock(), "Bymax kamu tidur ya")
assert len(sent_sleep_bymax) == 1 and sent_sleep_bymax[0][1] is True and "Tuan" not in sent_sleep_bymax[0][0], sent_sleep_bymax

# 7. Verifikasi Perintah Suara Berhenti Sesi ("berhenti sesion", "stop sesi", "sesion mati", dsb.)
is_end_cmd = ns["is_end_cmd"]
for e in ("berhenti sesion", "berhenti sesi", "sesion mati", "session mati", "stop sesi", "stop sesion", "akhiri sesi", "stop ngobrol", "berhenti ngobrol", "sudah berhenti ngobrol", "matikan sesi", "stop", "berhenti", "cukup"):
    assert is_end_cmd(e), f"Gagal deteksi perintah berhenti: {e}"
for n in ("kenapa kamu berhenti ngomong?", "mengapa sesi kemarin gagal?", "ceritakan tentang mobil berhenti"):
    assert not is_end_cmd(n), f"False positive perintah berhenti: {n}"

sent_end = []
ns["send_audio_and_maybe_listen"] = lambda c, ans, force_listen=False, allow_question=True, sleep=False: (sent_end.append((ans, force_listen)), False)[1]
panggil_session(FakeSock(), "berhenti sesion")
assert len(sent_end) == 1 and sent_end[0][1] is False, sent_end

sent_end_bymax = []
ns["send_audio_and_maybe_listen"] = lambda c, ans, force_listen=False, allow_question=True, sleep=False: (sent_end_bymax.append((ans, force_listen)), False)[1]
panggil_session(FakeSock(), "Bymax berhenti sesion")
assert len(sent_end_bymax) == 1 and sent_end_bymax[0][1] is False and "Tuan" not in sent_end_bymax[0][0], sent_end_bymax

# 8. Cek Fitur Memori Persisten & Larangan 'Tuan' pasca kenalan nama
process_memory_command = ns["process_memory_command"]
format_memory_context = ns["format_memory_context"]
load_memory = ns["load_memory"]
save_memory = ns["save_memory"]
get_active_call_name = ns["get_active_call_name"]

# Reset memori awal
process_memory_command("hapus semua memori")
assert load_memory()["user_name"] is None

# Simpan nama user
reply_name = process_memory_command("ingat nama saya Rizky")
assert "Rizky" in reply_name, reply_name
assert load_memory()["user_name"] == "Rizky"
assert get_active_call_name() == "Rizky"

# Setelah kenal nama: Bymax HARAM panggil "Tuan", harus panggil "Rizky"
sent_bymax_known = []
ns["send_audio_and_maybe_listen"] = lambda c, ans, force_listen=False, allow_question=True, sleep=False: (sent_bymax_known.append(ans), False)[1]
panggil_session(FakeSock(), "Bymax")
assert "Rizky" in sent_bymax_known[0] and "Tuan" not in sent_bymax_known[0], sent_bymax_known

# Panggilan sayang juga memadukan nama user
sent_sayang_known = []
ns["send_audio_and_maybe_listen"] = lambda c, ans, force_listen=False, allow_question=True, sleep=False: (sent_sayang_known.append(ans), False)[1]
panggil_session(FakeSock(), "sayang")
assert "Rizky" in sent_sayang_known[0] and "sayang" in sent_sayang_known[0], sent_sayang_known

# Simpan sebutan/panggilan bebas (misal: "bro")
reply_cs = process_memory_command("simpan dalam memori panggil aku bro")
assert "bro" in reply_cs, reply_cs
assert load_memory()["call_sign"] == "bro"
assert get_active_call_name() == "bro"

# Simpan imbuhan akhir (misal: "dong ah")
reply_suf = process_memory_command("kasih imbuhan di akhir dong ah")
assert "dong ah" in reply_suf, reply_suf
assert load_memory()["custom_suffix"] == "dong ah"

# Simpan fakta/jadwal/alamat penting
reply_fact1 = process_memory_command("ingat alamat rumah saya di Bandung jalan merdeka nomor 5")
assert "Bandung" in reply_fact1, reply_fact1
reply_fact2 = process_memory_command("catat jadwal besok jam 10 pagi meeting di kantor")
assert "meeting" in reply_fact2, reply_fact2
mem_check = load_memory()
assert len(mem_check["facts"]) == 1
assert len(mem_check["reminders"]) == 1

# Verifikasi prompt context Ollama menyertakan seluruh memori dan aturan
ctx = format_memory_context()
assert "Rizky" in ctx and "bro" in ctx and "dong ah" in ctx
assert "DILARANG memanggil 'Tuan'" in ctx

# Verifikasi clean_response memasang imbuhan dan membuang 'Tuan'
cleaned = clean_response("Halo Tuan, apa kabar?")
assert "Tuan" not in cleaned and "bro" in cleaned
assert cleaned.endswith("dong ah?") or "dong ah" in cleaned, cleaned

# 9. Verifikasi Ekstraksi Kognitif LLM (Tag JSON <<<MEMORY_UPDATE>>>) & Heuristik Lisan Fleksibel
parse_and_apply_llm_memory = ns["parse_and_apply_llm_memory"]
apply_heuristic_safety = ns["apply_heuristic_safety"]

# Uji ekstraksi kognitif LLM tag JSON
llm_out = (
    "<<<MEMORY_UPDATE>>>\n"
    "{\n"
    '  "thought": "User mengenalkan nama Febri dan melarang panggil tuan",\n'
    '  "user_name": "Febri",\n'
    '  "call_sign": "Febri",\n'
    '  "forbid_tuan": true,\n'
    '  "custom_suffix": "bos",\n'
    '  "custom_wake_reply": "Iya Febri ada apa, ada yang bisa Bymax bantu?",\n'
    '  "add_fact": "suka kopi tubruk"\n'
    "}\n"
    "<<<END_MEMORY_UPDATE>>>\n"
    "Halo Febri, udah aku simpan semua di memori ya bos!"
)
spoken = parse_and_apply_llm_memory(llm_out)
assert "<<<" not in spoken and "Febri" in spoken and "bos" in spoken
mem_now = load_memory()
assert mem_now["user_name"] == "Febri"
assert mem_now["call_sign"] == "Febri"
assert mem_now["forbid_tuan"] is True
assert mem_now["custom_suffix"] == "bos"
assert mem_now["custom_wake_reply"] == "Iya Febri ada apa, ada yang bisa Bymax bantu?"
assert "suka kopi tubruk" in mem_now["facts"]

# Uji respon bangun khusus di panggil_session
sent_wake_custom = []
ns["send_audio_and_maybe_listen"] = lambda c, ans, force_listen=False, allow_question=True, sleep=False: (sent_wake_custom.append(ans), False)[1]
panggil_session(FakeSock(), "Bymax")
assert sent_wake_custom[0] == "Iya Febri ada apa, ada yang bisa Bymax bantu bos?", sent_wake_custom

# Uji penanganan tangguh ketika LLM terpotong tanpa <<<END_MEMORY_UPDATE>>> dan tanpa kalimat lisan
llm_out_truncated = (
    "<<<MEMORY_UPDATE>>>\n"
    "{\n"
    '  "thought": "User memperkenalkan namanya Febrian Anugrah Maulana dengan panggilan Febri.",\n'
    '  "user_name": "Febrian Anugrah Maulana",\n'
    '  "call_sign": "Febri",\n'
    '  "forbid_tuan": true\n'
    "}"
)
spoken_trunc = parse_and_apply_llm_memory(llm_out_truncated)
cleaned_trunc = clean_response(spoken_trunc)
assert "{" not in cleaned_trunc and "}" not in cleaned_trunc and "thought" not in cleaned_trunc
assert "<<<" not in cleaned_trunc and "Febri" in cleaned_trunc
assert "Salam kenal" in cleaned_trunc, cleaned_trunc
mem_trunc = load_memory()
assert mem_trunc["user_name"] == "Febrian Anugrah Maulana"
assert mem_trunc["call_sign"] == "Febri"

# Uji sanitasi typo STT Whisper lisan: 'tuanya', 'tuhan', 'pengen gil'
apply_heuristic_safety("Tolong ingat namanya, ya itu Rangga")
assert load_memory()["user_name"] == "Rangga"
apply_heuristic_safety("Jadi jangan panggil tuanya")
assert load_memory()["forbid_tuan"] is True
apply_heuristic_safety("Baymax, jangan panggil Tuhan, panggil namah saja")
assert load_memory()["forbid_tuan"] is True
apply_heuristic_safety("Ingat dalam memori mu, jangan pengen gil tuan")
assert load_memory()["forbid_tuan"] is True

# 10. Verifikasi Scheduler Pengingat (Reminders) Aktif, Toleransi Typo Waktu Whisper, dan Typo Penutupan Sesi
extract_reminder_heuristic = ns["extract_reminder_heuristic"]
check_due_reminders = ns["check_due_reminders"]
add_or_update_reminder = ns["add_or_update_reminder"]

# Uji variasi typo penutupan sesi Whisper
assert is_end_cmd("Hentikan saya sih ini.") is True
assert is_end_cmd("Hentikan CSE ini.") is True
assert is_end_cmd("Matikan sesi ini.") is True
assert is_end_cmd("stop ngobrol dulu") is True
assert is_end_cmd("kenapa harus berhenti?") is False  # Pertanyaan tidak boleh menutup sesi

# Uji parser waktu lisan dengan typo STT Whisper (15.5.9 -> 15:59)
rem_parsed = extract_reminder_heuristic("Baymax ingatkan saya jam 15.5.9 untuk melakukan mandi.")
assert rem_parsed is not None
assert rem_parsed["time"] == "15:59"
assert rem_parsed["task"] == "mandi"

# Uji penambahan reminder via heuristik
process_memory_command("Baymax ingatkan saya jam 15.5.9 untuk melakukan mandi.")
mem_rem = load_memory()
mandi_rem = [r for r in mem_rem["reminders"] if r.get("task") == "mandi"]
assert len(mandi_rem) == 1
assert mandi_rem[0]["time"] == "15:59"
assert mandi_rem[0]["notified"] is False

# Uji eksekusi alarm pengingat jatuh tempo
dt_cls = ns["datetime"]
fake_now = dt_cls.strptime(f"{dt_cls.now().strftime('%Y-%m-%d')} 15:59", "%Y-%m-%d %H:%M")
due = check_due_reminders(fake_now)
due_mandi = [r for r in due if r.get("task") == "mandi"]
assert len(due_mandi) == 1
assert due_mandi[0]["notified"] is True

# Pastikan status ternotifikasi tersimpan di memori (tidak berulang membunyikan alarm)
due_again = check_due_reminders(fake_now)
assert len([r for r in due_again if r.get("task") == "mandi"]) == 0

# Bersihkan dan reset kembali agar memori bersih
process_memory_command("hapus semua memori")
assert load_memory()["user_name"] is None
assert len(load_memory()["reminders"]) == 0

# 11. Verifikasi Filter Ketat Bangun dari Sleep Mode (Hanya nama dia, sayang, atau bangun)
is_sleep_wake = ns["is_sleep_wake"]
# Kata yang sah untuk bangun saat tidur:
for w in ("Bymax", "Baymax", "sayang", "bangun", "ayo bangun", "kamu bangun dong", "Bymax bangun", "sayang bangun", "bangun tidur", "halo Bymax", "sayang kamu lagi ngapain", "Bymax jam berapa sekarang"):
    assert is_sleep_wake(w) is True, f"Gagal bangun dari sleep untuk: {w}"

# Kata yang DILARANG bangun saat tidur:
for nw in ("kamu tidur", "kamu tidur ya sayang", "tidur dulu", "berhenti sesion", "stop sesi", "stop ya sayang", "cukup sayang", "halo", "apa kabar", "siapa nama kamu", "anjing menggonggong", "batuk batuk", ""):
    assert is_sleep_wake(nw) is False, f"Harusnya tidak bangun dari sleep untuk: {nw}"

# Uji respons bangun ramah panggil_session saat is_from_sleep=True
sent_wake_sleep = []
ns["send_audio_and_maybe_listen"] = lambda c, ans, force_listen=False, allow_question=True, sleep=False: (sent_wake_sleep.append((ans, force_listen)), False)[1]
panggil_session(FakeSock(), "bangun", is_from_sleep=True)
assert len(sent_wake_sleep) == 1 and sent_wake_sleep[0][1] is True, sent_wake_sleep
assert any(k in sent_wake_sleep[0][0].lower() for k in ("bangun", "siap", "ada apa")), sent_wake_sleep

print("OK: 11 cek alur sesi lolos")

# 12. Verifikasi Fitur Radio Internet Streaming & Digital Volume Control
load_radios = ns["load_radios"]
get_radio_station = ns["get_radio_station"]
get_next_radio_station = ns["get_next_radio_station"]
process_radio_command = ns["process_radio_command"]
process_volume_command = ns["process_volume_command"]
apply_volume = ns["apply_volume"]

# Uji muat daftar radio
radios = load_radios()
assert len(radios) >= 8, f"Harusnya minimal 8 stasiun radio terkonfigurasi, dapat: {len(radios)}"

# Uji pencarian stasiun radio berdasarkan nama & genre
st_dmi = get_radio_station("dmi")
assert st_dmi is not None and st_dmi["id"] == "dmi"
st_dangdut = get_radio_station("putar lagu dangdut")
assert st_dangdut is not None and st_dangdut["id"] == "dangdut"
st_berita = get_radio_station("berita elshinta")
assert st_berita is not None and st_berita["id"] == "elshinta"
st_lawas = get_radio_station("lagu nostalgia jadul")
assert st_lawas is not None and st_lawas["id"] == "goldenhits"

# Uji navigasi stasiun berikutnya & sebelumnya
next_st = get_next_radio_station("dmi", step=1)
assert next_st is not None and next_st["id"] != "dmi"
prev_st = get_next_radio_station(next_st["id"], step=-1)
assert prev_st is not None and prev_st["id"] == "dmi"

# Uji perintah suara radio
act, st, resp = process_radio_command("Bymax putar radio sonora")
assert act == "play" and st["id"] == "sonora"
act, st, resp = process_radio_command("ganti channel radio selanjutnya")
assert act == "play" and st is not None
act, st, resp = process_radio_command("matikan radio")
assert act == "stop" and "dimatikan" in resp
act, st, resp = process_radio_command("lagi putar radio apa?")
assert act == "info" and st is not None

# Uji kontrol volume digital
v_resp = process_volume_command("volume 50")
assert "50%" in v_resp and load_memory()["volume"] == 50
v_resp = process_volume_command("besarkan volumenya")
assert "70%" in v_resp and load_memory()["volume"] == 70
v_resp = process_volume_command("kecilkan suaranya")
assert "50%" in v_resp and load_memory()["volume"] == 50
v_resp = process_volume_command("mute suaranya")
assert "dibisukan" in v_resp and load_memory()["muted"] is True
v_resp = process_volume_command("unmute")
assert "aktif kembali" in v_resp and load_memory()["muted"] is False

# Uji fungsi digital volume scaling PCM (NumPy int16)
import numpy as np
sample_pcm = np.full(100, 1000, dtype=np.int16).tobytes()
scaled_half = apply_volume(sample_pcm, 50)
scaled_arr = np.frombuffer(scaled_half, dtype=np.int16)
assert (scaled_arr == 500).all(), f"Nilai sampel harusnya 500, dapat: {scaled_arr[:5]}"
scaled_zero = apply_volume(sample_pcm, 0)
assert (np.frombuffer(scaled_zero, dtype=np.int16) == 0).all()

print("OK: 12 cek alur sesi lolos (Internet Radio & Digital Volume lulus 100%)")

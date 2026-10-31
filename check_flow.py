"""Self-check alur sesi server.py tanpa hardware/LLM. Jalankan: python check_flow.py"""
import sys, types, json, os

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "Server"))
os.chdir(os.path.join(os.path.dirname(os.path.abspath(__file__)), "Server"))

fake_fw = types.ModuleType("faster_whisper")
fake_fw.WhisperModel = lambda *a, **k: None
sys.modules["faster_whisper"] = fake_fw

src = open("server.py").read()
head = src.split("srv = socket.socket()")[0]
ns = {"__name__": "srv_head"}  # type: dict
exec(compile(head, "server.py", "exec"), ns)

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

# 1. Mode auto: 3 tanya-jawab lalu gumaman penutup, tanpa pertanyaan
log = run(["halo", "lagi ngapain", "iya aku sibuk"],
          ["Hai kamu?", "Aku lagi kerja?", "Semangat ya?"], AUTO_MAX_TURNS, True)
assert len(log["asks"]) == 3, log["asks"]
assert log["spont"] == [CLOSE_PROMPT], "penutup tidak dipanggil"
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

print("OK: 4 cek alur sesi lolos")

"""Program run inside the sandbox subprocess. Kept as a string so it needs no imports from
the project and runs under `python -I -S`. Reads JSON on stdin, prints one JSON on stdout."""

HARNESS = r"""
import builtins, collections, io, json, resource, sys

payload = json.loads(sys.stdin.read())
code = payload["code"]
mb = payload["memory_mb"] * 1024 * 1024
resource.setrlimit(resource.RLIMIT_AS, (mb, mb))
resource.setrlimit(resource.RLIMIT_CPU, (payload["cpu_s"], payload["cpu_s"] + 1))
resource.setrlimit(resource.RLIMIT_FSIZE, (0, 0))
sys.setrecursionlimit(150)

real_stdout = sys.stdout
OUT_LIMIT = 4000


class Capture(io.TextIOBase):
    def __init__(self):
        self.parts, self.size, self.truncated = [], 0, False

    def writable(self):
        return True

    def write(self, text):
        room = OUT_LIMIT - self.size
        if room <= 0:
            self.truncated = True
            return len(text)
        self.parts.append(text[:room])
        self.size += min(len(text), room)
        self.truncated = self.truncated or len(text) > room
        return len(text)


ALLOWED_MODULES = {"math", "random", "string"}


def safe_import(name, globals=None, locals=None, fromlist=(), level=0):
    if name.split(".")[0] not in ALLOWED_MODULES or level:
        raise ImportError("import not allowed: " + name)
    return __import__(name, globals, locals, fromlist, level)


SAFE = [
    "print", "len", "range", "int", "float", "str", "bool", "list", "dict", "set", "tuple",
    "sum", "min", "max", "abs", "round", "sorted", "reversed", "enumerate", "zip", "map",
    "filter", "any", "all", "isinstance", "divmod", "pow", "chr", "ord", "repr", "slice",
    "True", "False", "None", "Exception", "ValueError", "TypeError", "IndexError",
    "KeyError", "ZeroDivisionError", "StopIteration", "RecursionError", "ArithmeticError",
    "AssertionError", "NameError", "AttributeError", "OverflowError",
]
safe_builtins = {n: getattr(builtins, n) for n in SAFE}
safe_builtins["__import__"] = safe_import
globs = {"__builtins__": safe_builtins, "__name__": "__learner__"}

MAX_HEAD, MAX_TAIL = 20, 20
head, tail = [], collections.deque(maxlen=MAX_TAIL)
simple = (int, float, str, bool, list, tuple, dict, set, type(None))


def short(value):
    text = repr(value)
    return text if len(text) <= 40 else text[:37] + "..."


def tracer(frame, event, arg):
    if frame.f_code.co_filename != "<learner>":
        return None
    if event == "line":
        snap = {
            k: short(v)
            for k, v in frame.f_locals.items()
            if not k.startswith("__") and isinstance(v, simple)
        }
        step = {"line": frame.f_lineno, "vars": snap}
        (head if len(head) < MAX_HEAD else tail).append(step)
    return tracer


capture = Capture()
result = {"ok": True, "error": None}
sys.stdout = capture
sys.settrace(tracer)
try:
    exec(compile(code, "<learner>", "exec"), globs)
except BaseException as exc:
    tb, line = exc.__traceback__, None
    while tb is not None:
        if tb.tb_frame.f_code.co_filename == "<learner>":
            line = tb.tb_lineno
        tb = tb.tb_next
    result = {
        "ok": False,
        "error": {"type": type(exc).__name__, "message": str(exc)[:200], "line": line},
    }
finally:
    sys.settrace(None)
    sys.stdout = real_stdout

result["stdout"] = "".join(capture.parts)
result["truncated"] = capture.truncated
result["trace"] = head + list(tail)
real_stdout.write(json.dumps(result))
"""

"""Formulas read out of a production rule engine's source — a CANDIDATE, never trusted until execution agrees.

A rule engine's `compute()` is mostly straight-line arithmetic: inputs read from the model with a fallback (`const cW = g.clear_w || 5.0;`),
derived values (`const total_w = (cW * cells) + (tOW * 2) + (tIW * (cells - 1));`) and a returned object. This module reads that subset —
`const` declarations whose right side is a model read with fallbacks, or + − × ÷, parentheses and Math.max / min / abs / sqrt / round over
names it already knows — and turns each output into an expression of this project's safe language (`program.evaluate`) over named inputs.

Everything else (conditionals, loops, calls into other modules, `let` that may be reassigned, string handling) is reported as OPAQUE with the
reason, never guessed. An extracted formula is only a candidate: `extract.verify_formulas` evaluates it on sampled production models and
compares with what the production code itself computes for the same models; only formulas that agree become `verified_by_execution`.

    src = engine_source(text, "RCCBoxRuleEngine", kind="class")       # the compute() body
    fx = extract(src)                                                 # {"inputs": {...}, "outputs": {...}, "opaque": {...}}
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field

from ..program import FUNCS, ExprError, names_in, parse

_MATH = {"max": "max", "min": "min", "abs": "abs", "sqrt": "sqrt", "round": "round"}
_NUM = re.compile(r"-?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?")
_IDENT = re.compile(r"[A-Za-z_$][\w$]*")


@dataclass
class Input:
    """A model read with its fallbacks: the first present value of `chain` (dotted model paths), else `default`. `op` is the JavaScript
    operator joining them: `||` skips any falsy value (0 too), `??` only null / undefined."""

    chain: list[str]
    op: str = "||"
    default: float | None = None
    line: int = 0
    coerced: bool = False  # wrapped in Number(...)

    def as_json(self) -> dict:
        return {"chain": self.chain, "op": self.op, "default": self.default, "line": self.line, **({"coerced": True} if self.coerced else {})}


@dataclass
class Extracted:
    root: str
    sections: dict[str, str] = field(default_factory=dict)  # alias → model section path ("g" → "geometry")
    inputs: dict[str, Input] = field(default_factory=dict)  # local name → its model read
    locals: dict[str, tuple[str, int]] = field(default_factory=dict)  # local name → (expression in the safe language, line)
    opaque: dict[str, str] = field(default_factory=dict)  # local or output name → why it was not read
    outputs: dict[str, dict] = field(default_factory=dict)  # output path → {"local": name | None, "expr": str, "line": n}


def _strip_comments(text: str) -> str:
    out = []
    for ln in text.split("\n"):
        i, q = 0, None
        while i < len(ln):
            c = ln[i]
            if q:
                if c == q and ln[i - 1] != "\\":
                    q = None
            elif c in "'\"`":
                q = c
            elif ln.startswith("//", i):
                ln = ln[:i]
                break
            i += 1
        out.append(ln)
    text = "\n".join(out)
    return re.sub(r"/\*.*?\*/", lambda m: "\n" * m.group(0).count("\n"), text, flags=re.DOTALL)


def _match(text: str, i: int, open_: str = "{", close: str = "}") -> int:
    """Index of the bracket closing the one at `i` (strings skipped)."""
    depth, q = 0, None
    for j in range(i, len(text)):
        c = text[j]
        if q:
            if c == q and text[j - 1] != "\\":
                q = None
            continue
        if c in "'\"`":
            q = c
        elif c == open_:
            depth += 1
        elif c == close:
            depth -= 1
            if depth == 0:
                return j
    raise ValueError("unbalanced brackets")


def engine_source(text: str, symbol: str, kind: str = "auto") -> tuple[str, str, int] | None:
    """(the compute body, the name of its model parameter, the line the body starts on) — `static compute(` inside `class <symbol>`, or
    `function <symbol>(`. None when neither is found."""
    clean = _strip_comments(text)
    spans = []
    if kind in ("auto", "class"):
        m = re.search(rf"class\s+{re.escape(symbol)}\b", clean)
        if m:
            c = re.compile(r"static\s+compute\s*\(\s*([A-Za-z_$][\w$]*)").search(clean, m.end())
            if c:
                spans.append(c)
    if not spans and kind in ("auto", "function"):
        c = re.compile(rf"function\s+{re.escape(symbol)}\s*\(\s*([A-Za-z_$][\w$]*)").search(clean)
        if c:
            spans.append(c)
    if not spans:
        return None
    c = spans[0]
    b0 = clean.index("{", clean.index(")", c.end()))
    b1 = _match(clean, b0)
    return clean[b0 + 1:b1], c.group(1), clean[:b0].count("\n") + 1


def _split_top(s: str, seps: tuple[str, ...], offsets: bool = False) -> list:
    """Split at top-level separators (not inside brackets or strings): [(sep before, piece)] — with each piece's offset when asked."""
    out, depth, q, start, prev = [], 0, None, 0, ""
    i = 0
    while i < len(s):
        c = s[i]
        if q:
            if c == q and s[i - 1] != "\\":
                q = None
            i += 1
            continue
        if c in "'\"`":
            q = c
        elif c in "([{":
            depth += 1
        elif c in ")]}":
            depth -= 1
        elif depth == 0:
            hit = next((sp for sp in seps if s.startswith(sp, i)), None)
            if hit:
                out.append((prev, s[start:i], start))
                prev, start = hit, i + len(hit)
                i += len(hit)
                continue
        i += 1
    out.append((prev, s[start:], start))
    return out if offsets else [(a, b) for a, b, _o in out]


def _statements(body: str, line0: int) -> list[tuple[str, int]]:
    """Top-level statements of the body with the source line each starts on (nested blocks are kept whole: they are opaque)."""
    cuts, depth, q, start = [], 0, None, 0
    for i, c in enumerate(body):
        if q:
            if c == q and body[i - 1] != "\\":
                q = None
            continue
        if c in "'\"`":
            q = c
        elif c in "([{":
            depth += 1
        elif c in ")]}":
            depth -= 1
            if depth == 0 and c == "}" and not body[start:i].lstrip().startswith(("const", "let", "var", "return")):
                cuts.append((start, i + 1))
                start = i + 1
        elif c == ";" and depth == 0:
            cuts.append((start, i))
            start = i + 1
    cuts.append((start, len(body)))
    out = []
    for a, b in cuts:
        seg = body[a:b]
        if seg.strip():
            first = a + len(seg) - len(seg.lstrip())
            out.append((seg.strip(), line0 + body[:first].count("\n")))
    return out


class _Reader:
    def __init__(self, root: str):
        self.x = Extracted(root=root)
        self.roots = {root}
        self.lets: set[str] = set()
        self.anon = 0

    # a model path from a member expression: model.geometry.clear_w, g.clear_w, (model.side || {}).wing_l, bridge?.spanSize
    def path_of(self, s: str) -> str | None:
        s = s.strip().replace("?.", ".")
        m = re.fullmatch(r"\(\s*([A-Za-z_$][\w$.]*)\s*(?:\|\||\?\?)\s*\{\s*\}\s*\)\s*\.([\w$.]+)", s)
        if m:
            base = self.path_of(m.group(1))
            return f"{base}.{m.group(2)}" if base is not None else None
        if not re.fullmatch(r"[A-Za-z_$][\w$]*(?:\.[A-Za-z_$][\w$]*)*", s):
            return None
        head, *rest = s.split(".")
        if head in self.roots:
            return ".".join(rest) if rest else ""
        if head in self.x.sections:
            sec = self.x.sections[head]
            return ".".join(([sec] if sec else []) + rest)
        return None

    def section(self, rhs: str) -> str | None:
        s = rhs.strip()
        while s.startswith("(") and s.endswith(")") and _match(s, 0, "(", ")") == len(s) - 1:
            s = s[1:-1].strip()
        parts = _split_top(s, ("||", "??"))
        if len(parts) == 2 and re.fullmatch(r"\{\s*\}", parts[1][1].strip()):
            p = self.path_of(parts[0][1])
            return p
        p = self.path_of(s)
        return p if p == "" else None  # `const m = model` is another name for the root

    def input(self, rhs: str, line: int) -> Input | None:
        s, coerced = rhs.strip(), False
        m = re.fullmatch(r"Number\s*\((.*)\)", s, flags=re.DOTALL)
        if m and _match(s, s.index("("), "(", ")") == len(s) - 1:
            s, coerced = m.group(1).strip(), True
        parts = _split_top(s, ("||", "??"))
        ops = {sep for sep, _ in parts[1:]}
        if len(ops) > 1:
            return None
        chain, default = [], None
        for k, (_sep, term) in enumerate(parts):
            t = term.strip()
            if _NUM.fullmatch(t) and k == len(parts) - 1 and k > 0:
                default = float(t)
                continue
            p = self.path_of(t)
            if not p:
                return None
            chain.append(p)
        if not chain:
            return None
        return Input(chain=chain, op=(ops.pop() if ops else "||"), default=default, line=line, coerced=coerced)

    def arith(self, rhs: str, line: int) -> tuple[str | None, str]:
        """The right side in the safe language, or (None, why not). A failed read registers nothing (no half-read inputs)."""
        before = set(self.x.inputs)
        expr, why = self._arith(rhs, line)
        if expr is None:
            for k in set(self.x.inputs) - before:
                del self.x.inputs[k]
        return expr, why

    def _arith(self, rhs: str, line: int) -> tuple[str | None, str]:
        s = rhs.strip()
        out, i = [], 0
        while i < len(s):
            c = s[i]
            if c.isspace():
                i += 1
                continue
            m = _NUM.match(s, i)
            if m and (c.isdigit() or c == "."):
                out.append(m.group(0))
                i = m.end()
                continue
            if c in "+-*/(),":
                out.append(c)
                i += 1
                continue
            if s.startswith("Math.", i):
                m = _IDENT.match(s, i + 5)
                fn = m.group(0) if m else ""
                if fn == "pow":
                    j = s.index("(", m.end())
                    k = _match(s, j, "(", ")")
                    args = _split_top(s[j + 1:k], (",",))
                    if len(args) != 2:
                        return None, "Math.pow with other than two arguments"
                    a, why = self.arith(args[0][1], line)
                    b, why2 = self.arith(args[1][1], line)
                    if a is None or b is None:
                        return None, why or why2
                    out.append(f"(({a}) ** ({b}))")
                    i = k + 1
                    continue
                if fn not in _MATH:
                    return None, f"Math.{fn} is not arithmetic this reader evaluates"
                out.append(_MATH[fn])
                i = m.end()
                continue
            m = _IDENT.match(s, i)
            if m:
                j = m.end()
                while j < len(s) and (s.startswith(".", j) or s.startswith("?.", j)):  # a member read inline
                    n = _IDENT.match(s, j + (2 if s.startswith("?.", j) else 1))
                    if not n:
                        break
                    j = n.end()
                word = s[i:j]
                if word == "Number" and s[j:j + 1] == "(":
                    k = _match(s, j, "(", ")")
                    inner, why = self.inline(s[j + 1:k], line)
                    if inner is None:
                        return None, why
                    out.append(inner)
                    i = k + 1
                    continue
                if word in self.x.inputs or word in self.x.locals:
                    out.append(_safe(word))
                    i = j
                    continue
                if word in self.x.opaque:
                    return None, f"uses {word}, which was not read ({self.x.opaque[word]})"
                if word in self.lets:
                    return None, f"uses {word}, declared with let (it may be reassigned)"
                p = self.path_of(word)
                if p:
                    sym = self._anon(Input(chain=[p], op="||", default=None, line=line))
                    out.append(sym)
                    i = j
                    continue
                return None, f"uses {word!r}, which is not a number this reader knows"
            return None, f"{c!r}: not arithmetic (conditional, comparison, string or call)"
        expr = " ".join(out)
        try:
            parse(expr)
        except ExprError as exc:
            return None, f"not an expression of the safe language: {exc}"
        return expr, ""

    def inline(self, s: str, line: int) -> tuple[str | None, str]:
        inp = self.input(s, line)
        if inp is not None:
            return self._anon(inp), ""
        expr, why = self.arith(s, line)
        return (f"({expr})" if expr else None), why

    def _anon(self, inp: Input) -> str:
        for k, v in self.x.inputs.items():
            if v.chain == inp.chain and v.op == inp.op and v.default == inp.default:
                return _safe(k)
        self.anon += 1
        name = f"in{self.anon}_" + re.sub(r"\W", "_", inp.chain[0].split(".")[-1])
        self.x.inputs[name] = inp
        return name


def _safe(name: str) -> str:
    """A local's name in the safe language (a name that is one of its functions is prefixed)."""
    name = name.replace("$", "_")
    return f"v_{name}" if name in FUNCS else name


def extract(body: str, root: str, line0: int = 1) -> Extracted:
    r = _Reader(root)
    x = r.x
    for st, ln in _statements(body, line0):
        m = re.match(r"(const|let|var)\s+([A-Za-z_$][\w$]*)\s*(?::\s*[^=]+?)?=\s*(.*)\Z", st, flags=re.DOTALL)
        if m:
            kw, name, rhs = m.groups()
            if kw != "const":
                r.lets.add(name)
                x.opaque[name] = f"declared with {kw} (it may be reassigned)"
                continue
            sec = r.section(rhs)
            if sec is not None:
                if sec == "":
                    r.roots.add(name)
                else:
                    x.sections[name] = sec
                continue
            inp = r.input(rhs, ln)
            if inp is not None:
                x.inputs[name] = inp
                continue
            expr, why = r.arith(rhs, ln)
            if expr is not None:
                x.locals[name] = (expr, ln)
            else:
                x.opaque[name] = why
            continue
        if st.startswith(("const {", "const [")):
            for n in re.findall(r"[A-Za-z_$][\w$]*", st[6:st.index("=")] if "=" in st else ""):
                x.opaque[n] = "destructured from a call or object"
            continue
        if st.startswith("return"):
            obj = st[len("return"):].strip()
            if obj.startswith("{"):
                _outputs(r, obj[1:_match(obj, 0)], "", ln)
    return x


def _outputs(r: _Reader, obj: str, prefix: str, line: int) -> None:
    x = r.x
    for _sep, entry, off in _split_top(obj, (",",), offsets=True):
        e = entry.strip()
        if not e:
            continue
        ln = line + obj[:off + len(entry) - len(entry.lstrip())].count("\n")
        if e.startswith("..."):
            x.opaque[prefix + e[3:].strip()] = "spread into the result"
            continue
        m = re.fullmatch(r"([A-Za-z_$][\w$]*|'[^']*'|\"[^\"]*\")\s*(?::\s*(.*))?", e, flags=re.DOTALL)
        if not m:
            continue
        key = m.group(1).strip("'\"")
        rhs = m.group(2)
        path = prefix + key
        if rhs is None:  # shorthand: the local of the same name
            rhs = key
        rhs = rhs.strip()
        if rhs.startswith("{"):
            _outputs(r, rhs[1:_match(rhs, 0)], path + ".", ln)
            continue
        if rhs in x.inputs:
            x.outputs[path] = {"local": rhs, "expr": _safe(rhs), "line": x.inputs[rhs].line, "passthrough": True}
            continue
        if rhs in x.locals:
            x.outputs[path] = {"local": rhs, "expr": _safe(rhs), "line": x.locals[rhs][1]}
            continue
        if rhs in x.opaque:
            x.opaque.setdefault(path, x.opaque[rhs])
            continue
        inp = r.input(rhs, ln)
        if inp is not None:
            sym = r._anon(inp)
            x.outputs[path] = {"local": None, "expr": sym, "line": ln, "passthrough": True}
            continue
        expr, why = r.arith(rhs, ln)
        if expr is not None:
            x.outputs[path] = {"local": None, "expr": expr, "line": ln}
        else:
            x.opaque[path] = why or "not arithmetic"


def expand(x: Extracted, expr: str, depth: int = 0) -> str:
    """The expression with every derived local replaced by its own expression: in model inputs only."""
    if depth > 40:
        raise ExprError("locals nest too deeply")
    by_safe = {_safe(k): v[0] for k, v in x.locals.items()}

    def sub(m: re.Match) -> str:
        w = m.group(0)
        return f"({expand(x, by_safe[w], depth + 1)})" if w in by_safe else w

    return re.sub(r"[A-Za-z_][A-Za-z0-9_]*", sub, expr)


def input_symbols(x: Extracted, expr: str) -> dict[str, Input]:
    """The inputs an (expanded) expression reads, by their symbol."""
    by_safe = {_safe(k): v for k, v in x.inputs.items()}
    return {n: by_safe[n] for n in names_in(expr) if n in by_safe}


def resolve(inp: Input, model: dict):
    """What the production code reads for this input from `model` (the fallback semantics of `||` / `??`), or None (the default applies)."""
    for p in inp.chain:
        v = get_path(model, p)
        if inp.op == "??":
            if v is not None:
                return float(v) if inp.coerced and not isinstance(v, bool) else v
        else:
            if v not in (None, 0, "", False) and not (isinstance(v, float) and math.isnan(v)):
                return float(v) if inp.coerced and not isinstance(v, bool) else v
    return inp.default


def get_path(model, path: str):
    cur = model
    for k in path.split(".") if path else []:
        if isinstance(cur, dict):
            cur = cur.get(k)
        elif isinstance(cur, list) and k.isdigit() and int(k) < len(cur):
            cur = cur[int(k)]
        else:
            return None
    return cur


def set_path(model: dict, path: str, value) -> None:
    """Set a dotted path, creating objects on the way. A path the model's shape cannot hold (a word key into a list, e.g. an array's
    `length` the code read) raises KeyError: callers skip it."""
    keys = path.split(".")
    cur = model
    for k in keys[:-1]:
        if isinstance(cur, list):
            if not k.isdigit() or int(k) >= len(cur):
                raise KeyError(path)
            cur = cur[int(k)]
            continue
        if not isinstance(cur.get(k), (dict, list)):
            cur[k] = {}
        cur = cur[k]
    if isinstance(cur, list):
        if not keys[-1].isdigit() or int(keys[-1]) >= len(cur):
            raise KeyError(path)
        cur[int(keys[-1])] = value
    else:
        cur[keys[-1]] = value

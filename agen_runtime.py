from __future__ import annotations

import ast
import re
from collections import defaultdict
from pathlib import Path

class State:
    def __init__(self, **initial_values: object) -> None:
        self.__dict__.update(initial_values)

    def __getattr__(self, name: str) -> None:
        return None

    def public_dict(self) -> dict[str, object]:
        return {k: v for k, v in self.__dict__.items() if not k.startswith("_")}

def _STRCAT(*parts: object) -> str:
    return "".join("" if part is None else str(part) for part in parts)

def _consume_quoted(ch: str, quote: str, escape: bool) -> tuple[str | None, bool]:
    next_quote = None if (not escape and ch == quote) else quote
    next_escape = False if escape else ch == "\\"
    return next_quote, next_escape

def _bump_nesting(ch: str, paren: int, bracket: int, brace: int) -> tuple[int, int, int]:
    if ch == "(": return paren + 1, bracket, brace
    if ch == ")": return paren - 1, bracket, brace
    if ch == "[": return paren, bracket + 1, brace
    if ch == "]": return paren, bracket - 1, brace
    if ch == "{": return paren, bracket, brace + 1
    if ch == "}": return paren, bracket, brace - 1
    return paren, bracket, brace

SLOT_SYMBOLS = ("■", "◆", "▲", "▼", "◀", "▶")
SLOT_NAMES = tuple(f"_slot{i}" for i in range(len(SLOT_SYMBOLS)))
SLOT_NAME_SET = set(SLOT_NAMES)
SLOT_CLASS = "".join(SLOT_SYMBOLS)
INTERNAL_NAMES = {"_STRCAT", "_DOT", "_BIND_SLOT", "_ASSIGN_SLOT", "__slot_value__"}
SAFE_BUILTINS = {"len": len, "print": print}
MODULE_GLOBALS = {"__builtins__": SAFE_BUILTINS}
COMPARISON_TOKENS = ("==", "!=", "<=", ">=", "<", ">", " is ", " in ")
TARGET_NODE_TYPES = (ast.Name, ast.Attribute, ast.Subscript)
RUNTIME_FILENAME = "<agen>"

def _DOT(value: object, key: str) -> object:
    if isinstance(value, dict):
        return value[key]
    return getattr(value, key)

def _slot_target_name(slot_name: str) -> str:
    return f"{slot_name}_target"

def _clear_slots(state: State) -> None:
    for slot_name in SLOT_NAMES:
        state.__dict__.pop(slot_name, None)
        state.__dict__.pop(_slot_target_name(slot_name), None)

def _slot_snapshot(state: State) -> dict[str, object]:
    return {
        key: state.__dict__.get(key)
        for slot_name in SLOT_NAMES
        for key in (slot_name, _slot_target_name(slot_name))
    }

def _restore_slots(state: State, snapshot: dict[str, object]) -> None:
    for key, value in snapshot.items():
        if value is None:
            state.__dict__.pop(key, None)
        else:
            state.__dict__[key] = value

def _slot_name(slot_names: dict[str, str], symbol: str) -> str:
    if symbol not in slot_names:
        if len(slot_names) >= len(SLOT_NAMES):
            raise SyntaxError("Too many slot symbols in one scope")
        slot_names[symbol] = SLOT_NAMES[len(slot_names)]
    return slot_names[symbol]

def _BIND_SLOT(state: State, slot_name: str, value: object, target: str | None = None) -> bool:
    state.__dict__.update({slot_name: value, _slot_target_name(slot_name): target})
    return True

def _env(state: State, helpers: dict[str, object] | None = None) -> dict[str, object]:
    env = defaultdict(lambda: None, state.__dict__)
    helpers = helpers or {}

    def sync_slot(slot_name: str) -> None:
        env[slot_name], env[_slot_target_name(slot_name)] = getattr(state, slot_name, None), getattr(state, _slot_target_name(slot_name), None)

    def bind_slot(slot_name: str, value: object, target: str | None = None) -> bool:
        _BIND_SLOT(state, slot_name, value, target)
        sync_slot(slot_name)
        return True

    def assign_slot(slot_name: str, value: object) -> object:
        result = _ASSIGN_SLOT(state, slot_name, value)
        sync_slot(slot_name)
        target = getattr(state, _slot_target_name(slot_name), None)
        if isinstance(target, str):
            try:
                node = _parse_expr(target)
            except SyntaxError:
                node = None
            if isinstance(node, ast.Name):
                env[node.id] = getattr(state, node.id, None)
        return result

    env.update({"_STRCAT": _STRCAT, "_DOT": _DOT, "_BIND_SLOT": bind_slot, "_ASSIGN_SLOT": assign_slot, **SAFE_BUILTINS, **helpers})
    return env

def _sync_state_from_env(state: State, env: dict[str, object], helpers: dict[str, object] | None = None) -> None:
    helper_names = INTERNAL_NAMES | set(SAFE_BUILTINS) | set((helpers or {}).keys())
    for key, value in env.items():
        if key not in helper_names:
            setattr(state, key, value)

def _iter_top_level(text: str):
    paren = bracket = brace = 0
    quote: str | None = None
    escape = False
    for i, ch in enumerate(text):
        if quote is not None:
            quote, escape = _consume_quoted(ch, quote, escape)
            continue
        if ch in ("'", '"'):
            quote = ch
            continue
        paren, bracket, brace = _bump_nesting(ch, paren, bracket, brace)
        if paren == 0 and bracket == 0 and brace == 0: yield i, ch

def _split_top_level_commas(text: str) -> list[str]:
    parts: list[str] = []
    start = 0
    for i, ch in _iter_top_level(text):
        if ch == ",":
            if part := text[start:i].strip(): parts.append(part)
            start = i + 1
    if tail := text[start:].strip(): parts.append(tail)
    return parts

def _find_matching(text: str, start: int, opening: str, closing: str) -> int:
    depth = 0
    quote: str | None = None
    escape = False
    for i in range(start, len(text)):
        ch = text[i]
        if quote is not None:
            quote, escape = _consume_quoted(ch, quote, escape)
            continue
        if ch in ("'", '"'):
            quote = ch
            continue
        if ch == opening:
            depth += 1
        elif ch == closing:
            depth -= 1
            if depth == 0:
                return i
    raise SyntaxError(f"Unmatched {opening!r} in: {text}")

def _split_top_level_once(text: str, delimiter: str) -> tuple[str, str] | None:
    for i, ch in _iter_top_level(text):
        if ch == delimiter: return text[:i], text[i + 1 :]
    return None

def _rewrite_unquoted(text: str, replacer) -> str:
    out: list[str] = []
    i = 0
    quote: str | None = None
    escape = False
    while i < len(text):
        ch = text[i]
        if quote is not None:
            out.append(ch)
            quote, escape = _consume_quoted(ch, quote, escape)
            i += 1
            continue
        if ch in ("'", '"'):
            quote = ch
            out.append(ch)
            i += 1
            continue
        replacement, next_i = replacer(text, i)
        if replacement is None:
            out.append(ch)
            i += 1
        else:
            out.append(replacement)
            i = next_i
    return "".join(out)

def _is_bare_literal_token(text: str) -> bool:
    stripped = text.strip()
    return bool(stripped) and stripped.isidentifier() and stripped not in ("None", "True", "False")

def _is_list_literal_position(text: str, index: int) -> bool:
    j = index - 1
    while j >= 0 and text[j].isspace(): j -= 1
    return j < 0 or text[j] in "=(:,[{"

def _rewrite_bare_subscript(inner: str, slot_names: dict[str, str]) -> str:
    stripped = inner.strip()
    if not stripped:
        return ""
    if stripped.startswith(("'", '"')):
        return stripped
    if stripped.startswith("{") and stripped.endswith("}"):
        return _rewrite_dsl_value_syntax(stripped, slot_names)
    return repr(stripped) if _is_bare_literal_token(stripped) else _rewrite_dsl_value_syntax(stripped, slot_names)

def _is_template_string(text: str) -> bool:
    stripped = text.strip()
    if not stripped: return False
    if stripped in SLOT_SYMBOLS: return False
    if ".{" in stripped: return False
    if re.match(r"^[A-Za-z_]\w*(?:\.[A-Za-z_]\w*)*\s*\(", stripped): return False
    if stripped.startswith("{") and stripped.endswith("}"): return False
    if stripped.startswith("[") and stripped.endswith("]"): return False
    return any(symbol in stripped for symbol in SLOT_SYMBOLS) or ("{" in stripped and "}" in stripped)

def _is_explicit_value_expr(text: str) -> bool:
    stripped = text.strip()
    if not stripped: return False
    return stripped in SLOT_SYMBOLS or stripped == "None" or stripped[0] in "\"'[{(" or re.fullmatch(r"-?\d+(?:\.\d+)?", stripped) is not None

def _rewrite_template_string(text: str, slot_names: dict[str, str]) -> str:
    parts: list[str] = []
    buf: list[str] = []
    i = 0
    quote: str | None = None
    escape = False

    def flush_buf() -> None:
        if buf:
            parts.append(repr("".join(buf)))
            buf.clear()

    while i < len(text):
        ch = text[i]
        if quote is not None:
            buf.append(ch)
            quote, escape = _consume_quoted(ch, quote, escape)
            i += 1
            continue

        if ch in ("'", '"'):
            quote = ch
            buf.append(ch)
            i += 1
            continue

        if ch in SLOT_SYMBOLS or ch == "{":
            flush_buf()
            if ch in SLOT_SYMBOLS:
                parts.append(_slot_name(slot_names, ch))
                i += 1
            else:
                end = _find_matching(text, i, "{", "}")
                parts.append(_replace_slot_symbol(_rewrite_dsl_value_syntax(text[i + 1 : end].strip(), slot_names), slot_names))
                i = end + 1
            continue

        buf.append(ch)
        i += 1

    flush_buf()
    return f"_STRCAT({', '.join(parts)})"

def _rewrite_dot_brace_subscript(text: str, slot_names: dict[str, str]) -> str:
    def replace(text: str, i: int) -> tuple[str | None, int]:
        if text[i] == "." and i + 1 < len(text):
            if text[i + 1] == "{":
                end = _find_matching(text, i + 1, "{", "}")
                return f"[({_rewrite_dsl_value_syntax(text[i + 2 : end].strip(), slot_names)})]", end + 1
            if text[i + 1].isdigit():
                j = i + 1
                while j < len(text) and text[j].isdigit(): j += 1
                return f"[({text[i + 1 : j]})]", j
        return None, i
    return _rewrite_unquoted(text, replace)

def _rewrite_value_expr(text: str, slot_names: dict[str, str]) -> str:
    stripped = text.strip()
    if _is_template_string(stripped):
        return _rewrite_template_string(stripped, slot_names)
    if not _is_explicit_value_expr(stripped):
        return repr(stripped)
    return _replace_slot_symbol(_rewrite_dsl_value_syntax(stripped, slot_names), slot_names)

def _rewrite_assignment_rhs(text: str, op: str, slot_names: dict[str, str]) -> str:
    split = _split_top_level_once(text, "=" if op == "=" else op[0])
    if split is None:
        return text
    lhs, rhs = split
    if op in ("+=", "-="):
        if not rhs.startswith("="):
            return text
        rhs = rhs[1:]
    if lhs.rstrip().endswith(("=", "!", "<", ">", "+", "-", "*", "/", "%")):
        return text
    lhs = _replace_slot_symbol(_rewrite_dsl_value_syntax(lhs.strip(), slot_names), slot_names)
    return f"{lhs} {op} {_rewrite_value_expr(rhs, slot_names)}"

def _rewrite_slot_assignment(text: str, slot_names: dict[str, str]) -> str:
    stripped = text.strip()
    match = re.fullmatch(rf"([{SLOT_CLASS}])\s*=\s*(.+)", stripped)
    if match is None:
        return text
    return f"_ASSIGN_SLOT({_slot_name(slot_names, match.group(1))!r}, {_rewrite_value_expr(match.group(2).strip(), slot_names)})"

def _replace_slot_symbol(text: str, slot_names: dict[str, str]) -> str:
    def replace(text: str, i: int) -> tuple[str | None, int]:
        if text[i] in SLOT_SYMBOLS:
            return _slot_name(slot_names, text[i]), i + 1
        return None, i
    return _rewrite_unquoted(text, replace)

def _rewrite_dsl_value_syntax(text: str, slot_names: dict[str, str]) -> str:
    text = _rewrite_dot_brace_subscript(text, slot_names)
    out: list[str] = []
    i = 0
    quote: str | None = None
    escape = False

    while i < len(text):
        ch = text[i]
        if quote is not None:
            out.append(ch)
            quote, escape = _consume_quoted(ch, quote, escape)
            i += 1
            continue

        if ch in ("'", '"'):
            quote = ch
            out.append(ch)
            i += 1
            continue

        if ch == "{":
            end = _find_matching(text, i, "{", "}")
            inner = text[i + 1 : end].strip()
            split = _split_top_level_once(inner, ":")
            if split is None:
                out.append(_rewrite_dsl_value_syntax(inner, slot_names))
            else:
                def rewrite_entry(entry: str) -> str:
                    entry_split = _split_top_level_once(entry, ":")
                    if entry_split is None: raise SyntaxError(f"Invalid dict entry: {entry}")
                    raw_key, raw_value = entry_split
                    key, value = raw_key.strip(), raw_value.strip()
                    if key.startswith(("'", '"')):
                        py_key = key
                    elif key.isidentifier():
                        py_key = repr(key)
                    else:
                        py_key = _rewrite_dsl_value_syntax(key, slot_names)
                    return f"{py_key}: {_rewrite_value_expr(value, slot_names)}"
                out.append("{" + ", ".join(rewrite_entry(entry) for entry in _split_top_level_commas(inner)) + "}")
            i = end + 1
            continue

        if ch == "[" and _is_list_literal_position(text, i):
            end = _find_matching(text, i, "[", "]")
            inner = text[i + 1 : end]
            values = (
                _rewrite_value_expr(stripped, slot_names)
                for item in _split_top_level_commas(inner)
                if (stripped := item.strip())
            )
            out.append("[" + ", ".join(values) + "]")
            i = end + 1
            continue

        if ch == "[":
            end = _find_matching(text, i, "[", "]")
            inner = text[i + 1 : end]
            out.append("[" + _rewrite_bare_subscript(inner, slot_names) + "]")
            i = end + 1
            continue

        out.append(ch)
        i += 1

    return "".join(out)

def _normalize_stmt(text: str, slot_names: dict[str, str] | None = None) -> str:
    if slot_names is None:
        slot_names = {}
    parts = _split_top_level_commas(text.replace("Ø", "None"))
    rewritten: list[str] = []
    for part in parts:
        raw = part.strip().replace("Ø", "None")
        rewritten_stmt = _rewrite_slot_assignment(raw, slot_names)
        if rewritten_stmt == raw:
            rewritten_stmt = _rewrite_dsl_value_syntax(raw, slot_names)
            for op in ("+=", "-=", "="):
                candidate = _rewrite_assignment_rhs(raw, op, slot_names)
                if candidate != raw:
                    rewritten_stmt = candidate
                    break
        rewritten.append(_replace_slot_symbol(rewritten_stmt, slot_names))
    return "; ".join(rewritten)

def _replace_condition_equals(text: str) -> str:
    def replace(text: str, i: int) -> tuple[str | None, int]:
        prev = text[i - 1] if i > 0 else ""
        nxt = text[i + 1] if i + 1 < len(text) else ""
        if text[i] == "=" and prev not in ("=", "!", "<", ">") and nxt != "=":
            return "==", i + 1
        return None, i
    return _rewrite_unquoted(text, replace)

def _find_top_level_comparison(text: str) -> tuple[str, str, str] | None:
    for i, _ in _iter_top_level(text):
        for op in ("==", "!=", "<=", ">=", "<", ">"):
            if text.startswith(op, i): return text[:i], op, text[i + len(op):]
    return None

def _rewrite_slot_binding(part: str, slot_names: dict[str, str]) -> str:
    stripped = part.strip()
    match = re.fullmatch(rf"(.+)=(?:([{SLOT_CLASS}]))", stripped)
    if match is None:
        return part
    lhs, symbol = match.group(1).strip(), match.group(2)
    if not lhs:
        raise SyntaxError(f"Missing binding source before {symbol}")
    lhs_expr = _rewrite_dsl_value_syntax(lhs.replace("Ø", "None"), slot_names)
    slot_name = _slot_name(slot_names, symbol)
    return f"_BIND_SLOT({slot_name!r}, {lhs_expr}, {_replace_slot_symbol(lhs_expr, slot_names)!r})"

def _normalize_condition(text: str, slot_names: dict[str, str] | None = None) -> str:
    if slot_names is None:
        slot_names = {}
    normalized = text.strip().replace("Ø", "None").replace("≠", "!=")
    parts = _split_top_level_commas(normalized)
    if len(parts) > 1:
        return " and ".join(f"({_normalize_condition_with_slots(part, slot_names)})" for part in parts)
    return _normalize_condition_with_slots(parts[0], slot_names)

def _normalize_condition_with_slots(text: str, slot_names: dict[str, str]) -> str:
    normalized = _replace_condition_equals(_rewrite_slot_binding(text, slot_names))
    comparison = _find_top_level_comparison(normalized)
    if comparison is not None:
        lhs, op, rhs = comparison
        lhs = _replace_slot_symbol(_rewrite_dsl_value_syntax(lhs.strip(), slot_names), slot_names)
        return f"{lhs} {op} {_rewrite_value_expr(rhs, slot_names)}"
    normalized = _replace_slot_symbol(_rewrite_dsl_value_syntax(normalized, slot_names), slot_names)
    if any(token in normalized for token in COMPARISON_TOKENS):
        return normalized
    return f"({normalized}) != None"

def _surface_to_python(source: str) -> str:
    lines = []
    scopes: list[tuple[int, dict[str, str]]] = [(0, {})]
    pending_scope: tuple[int, dict[str, str]] | None = None
    for raw_line in source.splitlines():
        stripped = raw_line.lstrip(" ")
        indent = raw_line[: len(raw_line) - len(stripped)]
        indent_len = len(indent)
        if stripped == "":
            lines.append("")
            continue
        while len(scopes) > 1 and indent_len < scopes[-1][0]:
            scopes.pop()
        if indent_len > scopes[-1][0]:
            if pending_scope is None or indent_len != pending_scope[0]:
                raise SyntaxError(f"Unexpected indentation: {raw_line}")
            scopes.append(pending_scope)
        scope_slots = scopes[-1][1]
        line_slots = scope_slots.copy()
        pending_scope = None
        if "➜" in stripped:
            left, right = stripped.split("➜", 1)
            left = left.strip()
            if not (left.startswith("(") and left.endswith(")")):
                raise SyntaxError(f"Arrow condition must be parenthesized: {left}")
            lines.append(f"{indent}if {_normalize_condition(left[1:-1], line_slots)}:")
            if stmt := _normalize_stmt(right.strip(), line_slots):
                lines.append(f"{indent}    {stmt}")
            pending_scope = (indent_len + 4, line_slots)
        elif stripped.startswith("(") and stripped.endswith(")"):
            lines.append(f"{indent}if {_normalize_condition(stripped[1:-1], line_slots)}:")
            pending_scope = (indent_len + 4, line_slots)
        else:
            lines.append(f"{indent}{_normalize_stmt(stripped, line_slots)}")
        scope_slots |= line_slots
    return "\n".join(lines) + ("\n" if source.endswith("\n") else "")

def _store(node: ast.AST) -> ast.AST:
    if isinstance(node, TARGET_NODE_TYPES): node.ctx = ast.Store()
    return node

def _parse_expr(text: str) -> ast.AST:
    return ast.parse(text, mode="eval").body

def _compile(node: ast.AST, mode: str) -> object:
    return compile(ast.fix_missing_locations(node), RUNTIME_FILENAME, mode)

class _DotAccessTransformer(ast.NodeTransformer):
    def visit_Attribute(self, node: ast.Attribute) -> ast.AST:
        if isinstance(node.ctx, ast.Store): return node
        return ast.copy_location(ast.Call(func=ast.Name(id="_DOT", ctx=ast.Load()), args=[self.visit(node.value), ast.Constant(node.attr)], keywords=[]), node)

class _SlotTargetTransformer(ast.NodeTransformer):
    def __init__(self, state: State) -> None:
        self.state = state

    def _eval_slice(self, node: ast.AST) -> object:
        try:
            return _eval_expr(node, self.state)
        except Exception:
            return None

    def _expand_slot_target(self, node: ast.AST, *, final_ctx: ast.expr_context) -> tuple[ast.AST, object] | None:
        if isinstance(node, ast.Name):
            if node.id not in SLOT_NAME_SET:
                return None
            target = getattr(self.state, _slot_target_name(node.id), None)
            if not target:
                return None
            target_node = _parse_expr(target)
            if isinstance(final_ctx, ast.Store):
                target_node = _store(target_node)
            return ast.copy_location(target_node, node), getattr(self.state, node.id, None)

        if isinstance(node, ast.Attribute):
            expanded = self._expand_slot_target(node.value, final_ctx=ast.Load())
            if expanded is None: return None
            base_node, base_value = expanded
            if isinstance(base_value, dict):
                next_value = base_value.get(node.attr)
                new_node: ast.AST = ast.Subscript(value=base_node, slice=ast.Constant(node.attr), ctx=final_ctx)
            else:
                next_value = getattr(base_value, node.attr, None)
                new_node = ast.Attribute(value=base_node, attr=node.attr, ctx=final_ctx)
            return ast.copy_location(new_node, node), next_value

        if isinstance(node, ast.Subscript):
            expanded = self._expand_slot_target(node.value, final_ctx=ast.Load())
            if expanded is None: return None
            base_node, base_value = expanded
            slice_node = self.visit(node.slice) if isinstance(node.slice, ast.AST) else node.slice
            index_value = self._eval_slice(node.slice)
            try:
                next_value = base_value[index_value]
            except Exception:
                next_value = None
            new_node = ast.Subscript(value=base_node, slice=slice_node, ctx=final_ctx)
            return ast.copy_location(new_node, node), next_value

        return None

    def _visit_store_target(self, node: ast.AST) -> ast.AST:
        expanded = self._expand_slot_target(node, final_ctx=node.ctx)
        return expanded[0] if expanded is not None else self.generic_visit(node)

    def visit_Name(self, node: ast.Name) -> ast.AST:
        return self._visit_store_target(node) if isinstance(node.ctx, ast.Store) else node

    def visit_Attribute(self, node: ast.Attribute) -> ast.AST:
        return self._visit_store_target(node) if isinstance(node.ctx, ast.Store) else self.generic_visit(node)

    def visit_Subscript(self, node: ast.Subscript) -> ast.AST:
        return self._visit_store_target(node) if isinstance(node.ctx, ast.Store) else self.generic_visit(node)

def _transform_expr(node: ast.AST) -> ast.AST:
    return _DotAccessTransformer().visit(ast.fix_missing_locations(node))

def _transform_stmt(node: ast.stmt, state: State) -> ast.stmt:
    return _transform_expr(_SlotTargetTransformer(state).visit(ast.fix_missing_locations(node)))

def _eval_expr(node: ast.AST, state: State, helpers: dict[str, object] | None = None) -> object:
    expr = ast.Expression(_transform_expr(node))
    return eval(_compile(expr, "eval"), MODULE_GLOBALS, _env(state, helpers))

def _exec_module(body: list[ast.stmt], state: State, helpers: dict[str, object] | None = None) -> None:
    env = _env(state, helpers)
    exec(_compile(ast.Module(body=body, type_ignores=[]), "exec"), MODULE_GLOBALS, env)
    _sync_state_from_env(state, env, helpers)

def _ASSIGN_SLOT(state: State, symbol: str, value: object, helpers: dict[str, object] | None = None) -> object:
    target = getattr(state, _slot_target_name(symbol), None)
    if not target:
        raise RuntimeError(f"{symbol} is not bound to a writable target")

    env = _env(state, helpers)
    env["__slot_value__"] = value
    target_node = _transform_stmt(
        ast.Assign(
            targets=[_store(_parse_expr(target))],
            value=ast.Name(id="__slot_value__", ctx=ast.Load()),
        ),
        state,
    ).targets[0]
    if not isinstance(target_node, TARGET_NODE_TYPES):
        raise RuntimeError(f"{symbol} is not bound to a writable target")
    exec(
        _compile(
            ast.Module(
                body=[ast.Assign(targets=[target_node], value=ast.Name(id="__slot_value__", ctx=ast.Load()))],
                type_ignores=[],
            ),
            "exec",
        ),
        MODULE_GLOBALS,
        env,
    )
    if isinstance(target_node, ast.Name): setattr(state, target_node.id, env[target_node.id])
    setattr(state, symbol, value)
    return value

def _exec_stmt(node: ast.stmt, state: State, helpers: dict[str, object] | None = None) -> bool:
    if isinstance(node, ast.AugAssign) and isinstance(node.target, ast.Name) and node.target.id in SLOT_NAME_SET:
        symbol = node.target.id
        if not isinstance(node.op, ast.Add):
            raise NotImplementedError(f"Unsupported slot augassign op: {ast.dump(node.op)}")
        _ASSIGN_SLOT(state, symbol, getattr(state, symbol) + _eval_expr(node.value, state, helpers), helpers)
    elif isinstance(node, (ast.Assign, ast.AugAssign)):
        _exec_module([_transform_stmt(node, state)], state, helpers)
    elif isinstance(node, ast.Expr):
        _exec_module([ast.Expr(value=_transform_expr(node.value))], state, helpers)
    else:
        raise NotImplementedError(f"Unsupported statement: {ast.dump(node)}")
    return True

def _exec_body(body: list[ast.stmt], state: State, helpers: dict[str, object] | None = None) -> bool:
    changed = False
    for node in body:
        if isinstance(node, ast.If):
            snapshot = _slot_snapshot(state)
            if _eval_expr(node.test, state, helpers):
                if _exec_body(node.body, state, helpers):
                    return True
                _restore_slots(state, snapshot)
            else:
                _restore_slots(state, snapshot)
            continue
        changed = _exec_stmt(node, state, helpers) or changed
    return changed

def _load_program(*, source_path: Path | None = None, source: str | None = None) -> ast.Module:
    if source is None and source_path is None:
        raise ValueError("agen_loop requires source_path or source")
    source_text = source if source is not None else source_path.read_text(encoding="utf-8")
    return ast.parse(_surface_to_python(source_text), filename=str(source_path or RUNTIME_FILENAME))

def agen_loop(
    state: State | None = None,
    *,
    source_path: Path | None = None,
    source: str | None = None,
    step_limit: int = 1000,
    helpers: dict[str, object] | None = None,
) -> State:
    program = _load_program(source_path=source_path, source=source)
    state = state or State()

    for _ in range(step_limit):
        _clear_slots(state)
        for node in program.body:
            if not isinstance(node, ast.If):
                raise NotImplementedError(f"Top-level statement must be if: {ast.dump(node)}")
            snapshot = _slot_snapshot(state)
            if _eval_expr(node.test, state, helpers):
                if _exec_body(node.body, state, helpers):
                    break
                _restore_slots(state, snapshot)
            else:
                _restore_slots(state, snapshot)
        else:
            return state

    raise RuntimeError(f"step limit exceeded: {step_limit}")

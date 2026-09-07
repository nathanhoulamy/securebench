"""Passive parser tests; only fixed, trusted fixtures are ever run in Vim."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import subprocess
import sys

import pytest

from tests.qualification_support import DOCKER_INTEGRATION


PARSER = (
    Path(__file__).resolve().parents[1]
    / "benchmarks/terminal-bench/v2/hidden/large-scale-text-editing/oracle/vim_literals.py"
)
IMAGE = (
    "alexgshaw/large-scale-text-editing@"
    "sha256:719adca3f1388220546ce6a155eee56eff3c4fe318183100320606a210f6b59c"
)


@pytest.fixture(scope="module")
def parser():
    name = "large_scale_vim_literals"
    spec = importlib.util.spec_from_file_location(name, PARSER)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    try:
        spec.loader.exec_module(module)
        yield module
    finally:
        del sys.modules[name]


# Expressions here are test-owned constants, never supplied by a Candidate.
REFERENCE_LITERALS = [
    r'":s/\\s*,\\s*/,/g\<CR>:s/^\\s*\\(.*\\S\\)\\s*$/\\1/\<CR>j"',
    r'":s/^\\([^,]*\\),\\([^,]*\\),\\([^,]*\\)$/\\3,\\2,\\1/\<CR>j"',
    r'":s/^\\([^,]*\\),\\([^,]*\\),\\([^,]*\\)$/\\U\\1\\E,\\U\\2\\E,\\U\\3\\E/\<CR>:s/,/;/g\<CR>:s/$/;OK/\<CR>j"',
]
LITERALS = [
    "''", "'plain'", "'it''s'", r"'\n\<CR>'",
    r'"\\\""', r'"\b\e\f\n\r\t"', r'"\q\z"',
    r'"\101\x42\X43\u0044\U00000045"',
    r'"\u00e9\U0001f600"', r'"\xc3\xa9"',
    r'"\000ignored"', r'"\x00ignored"', r'"\u0000ignored"',
    r'"\x\u\U\X"',
    r'"\<CR>\<Return>\<Enter>\<NL>\<LF>\<Tab>"',
    r'"\<Esc>\<Space>\<lt>\<Bslash>\<Bar>"',
    r'"j\r"', r'"j\<CR>"', r'"\r\r"', r'"\n\r"',
    r'"\<C-A>\<C-Z>\<C-[>\<C-\>\<C-]>\<C-^>\<C-_>"',
    '"<CR> <literal> café 😀"',
    r'":s/\\s*,\\s*/,/g\<CR>j"',
] + [f'"\\x{value:02x}"' for value in range(1, 128)] + REFERENCE_LITERALS


@DOCKER_INTEGRATION
def test_literals_match_pinned_vim(parser):
    program = r'''
import json, subprocess, sys
expressions = json.load(sys.stdin)
lines = ['set encoding=utf-8', 'let results = []']
for expression in expressions:
    lines += ["call setreg('a', " + expression + ")",
              "let normalized = keytrans(getreg('a'))",
              r"let macro_count = strlen(substitute(normalized, '<[^>]\+>', nr2char(1), 'g'))",
              'call add(results, [normalized, macro_count])']
lines += ["call writefile([json_encode(results)], '/tmp/result.json')", 'qa!']
with open('/tmp/fixture.vim', 'w') as stream:
    stream.write('\n'.join(lines) + '\n')
result = subprocess.run(['vim', '-Nu', 'NONE', '-i', 'NONE', '-n', '-Es', '-V1', '-S', '/tmp/fixture.vim'],
                        capture_output=True, timeout=20)
if result.returncode:
    raise RuntimeError(repr(result.stderr) + repr(lines))
with open('/tmp/result.json') as stream:
    print(stream.read())
'''
    completed = subprocess.run(
        ["docker", "run", "--rm", "-i", "--network", "none", "--read-only",
         "--tmpfs", "/tmp:rw,nosuid,nodev,size=16m", "--cap-drop=ALL",
         "--security-opt", "no-new-privileges", "--entrypoint", "python3",
         IMAGE, "-c", program],
        input=json.dumps(LITERALS), text=True, capture_output=True, timeout=60,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    actual = json.loads(completed.stdout)
    mismatches = []
    for expression, expected in zip(LITERALS, actual, strict=True):
        value, offset = parser.literal(expression)
        assert offset == len(expression)
        macro = parser.macro(value)
        if [macro.keytrans, macro.keystrokes] != expected:
            mismatches.append((expression, [macro.keytrans, macro.keystrokes], expected))
    assert not mismatches


@pytest.mark.parametrize("source", [
    "call setreg('a', system('id'))", "call setreg('a', 'x') | quit",
    "call setreg('d', 'x')", "call setreg('a', 'x' . 'y')",
    "call setreg('a', 'unterminated)", "call setreg('a', 'x', 'V')",
    ':source /tmp/other', ':!id', 'python3 print(1)',
    "call setreg('a', 'x\ny')", "call setreg('a', 'x\x00y')",
])
def test_rejects_nonliteral_or_trailing_commands(parser, source):
    with pytest.raises(ValueError):
        parser.parse_script(source)


def test_bounds(parser):
    with pytest.raises(ValueError, match="oversized"):
        parser.parse_script('"' + 'x' * parser.MAX_BYTES)
    with pytest.raises(ValueError, match="too many lines"):
        parser.parse_script('\n' * parser.MAX_LINES)
    with pytest.raises(ValueError, match="byte bound"):
        parser.literal('"' + 'é' * parser.MAX_BYTES + '"')


def test_definitions_comments_and_normalization(parser):
    script = parser.parse_script(
        '\n"comment\ncall setreg(\'a\', "old")\n'
        ':call setreg(\'a\', "j\\<CR>")\n'
        "call setreg('b', 'xy')\ncall setreg('c', 'z')\n"
        ':%normal! @a\n:%normal! @b\n:%normal! @c\n:wq\n'
    )
    assert script.definitions['a'].text == 'j\r'
    assert script.definitions['a'].keytrans == 'j<CR><NL>'
    assert script.definitions['a'].keystrokes == 3
    assert script.executions == ('a', 'b', 'c')
    assert script.exits == (':wq',)
    assert script.commands[0] == ('define', 'a', 'old')
    assert script.commands[-1] == ('exit', ':wq', '')


def test_unsupported_keys_and_non_utf8_fail_explicitly(parser):
    for expression in [r'"\<F12>"', r'"\xff"', r'"\uD800"',
                       r'"\<BS>"', r'"\<C-@>"', r'"\<Escape>"', r'"\<Del>"',
                       r'"\<C-ß>"']:
        with pytest.raises(parser.UnsupportedLiteral):
            parser.literal(expression)


def test_counting_is_normalized_utf8_bytes_not_source_length(parser):
    assert parser.macro('<CR>').keystrokes == 4
    assert parser.macro('\r').keystrokes == 2
    assert parser.macro('é').keystrokes == 2
    assert parser.macro('x' * 199).keystrokes == 199
    assert parser.macro('x' * 200).keystrokes == 200
    with pytest.raises(parser.UnsupportedLiteral):
        parser.macro('\u200b')


def test_early_exit_and_redefinition_are_not_hidden(parser):
    script = parser.parse_script(
        "call setreg('a', 'x')\n:%normal! @a\n:x\ncall setreg('a', 'y')"
    )
    assert script.commands == (
        ('define', 'a', 'x'), ('execute', 'a', ''),
        ('exit', ':x', ''), ('define', 'a', 'y'),
    )


def test_line_endings_and_whitespace_are_not_python_whitespace(parser):
    assert parser.parse_script(':x\r\n').exits == (':x',)
    for source in [':x\r', '\u00a0:x', "call setreg(\u00a0'a', 'x')"]:
        with pytest.raises(ValueError):
            parser.parse_script(source)


def test_upstream_reference_macro_contract(parser):
    source = '\n'.join(
        f"call setreg('{register}', {expression})"
        for register, expression in zip('abc', REFERENCE_LITERALS, strict=True)
    ) + '\n:%normal! @a\n:%normal! @b\n:%normal! @c\n:wq\n'
    script = parser.parse_script(source)
    macros = list(script.definitions.values())
    assert len(macros) == 3
    assert len({macro.keytrans for macro in macros}) == 3
    assert all(macro.keystrokes > 0 for macro in macros)
    assert sum(macro.keystrokes for macro in macros) < 200

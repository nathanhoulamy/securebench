"""Passive, bounded parser for literal Vim macro definitions.

This is deliberately not a Vimscript interpreter. Unsupported key notation or
byte encodings raise UnsupportedLiteral, allowing admission to distinguish an
unimplemented construction from a malformed submission.
"""

from __future__ import annotations

from dataclasses import dataclass
import re


MAX_BYTES = 16_384
MAX_LINES = 256


class UnsupportedLiteral(ValueError):
    """A Vim construction whose equivalence has not been qualified."""


@dataclass(frozen=True)
class Macro:
    text: str
    keytrans: str
    keystrokes: int


@dataclass(frozen=True)
class Script:
    definitions: dict[str, Macro]
    executions: tuple[str, ...]
    exits: tuple[str, ...]
    # Keep source order: final definitions alone cannot describe early exits or
    # register redefinitions between executions. Admission must inspect this.
    commands: tuple[tuple[str, str, str], ...]


def _key(name: str) -> str:
    aliases = {
        'cr': '\r', 'return': '\r', 'enter': '\r',
        'nl': '\n', 'lf': '\n', 'tab': '\t',
        'esc': '\x1b', 'space': ' ',
        'lt': '<', 'bslash': '\\', 'bar': '|',
    }
    lowered = name.lower()
    if lowered in aliases:
        return aliases[lowered]
    if len(name) == 3 and lowered.startswith('c-'):
        char = name[2].upper()
        # C-@ is Vim's encoded Nul key, not a terminating string NUL. BS
        # likewise differs from byte 0x08; neither has a text-only model here.
        if len(char) == 1 and 'A' <= char <= '_':
            return chr(ord(char) & 31)
    raise UnsupportedLiteral('unsupported special-key notation')


def literal(source: str, offset: int = 0) -> tuple[str, int]:
    """Decode one literal, returning text and the first unconsumed offset."""
    if len(source.encode('utf-8')) > MAX_BYTES:
        raise ValueError('literal exceeds byte bound')
    if not 0 <= offset < len(source) or source[offset] not in {'"', "'"}:
        raise ValueError('a quoted literal is required')
    quote = source[offset]
    offset += 1
    output = bytearray()
    while offset < len(source):
        char = source[offset]
        offset += 1
        if char == quote:
            if quote == "'" and source[offset:offset + 1] == "'":
                output.extend(b"'")
                offset += 1
                continue
            raw = bytes(output).split(b'\0', 1)[0]
            try:
                return raw.decode('utf-8'), offset
            except UnicodeDecodeError as error:
                raise UnsupportedLiteral('non-UTF-8 literal bytes') from error
        if char in '\r\n\0':
            raise ValueError('literal contains a raw line break or NUL')
        if char != '\\' or quote == "'":
            output.extend(char.encode('utf-8'))
            continue
        if offset == len(source):
            raise ValueError('unterminated escape')
        escaped = source[offset]
        offset += 1
        simple = {'b': '\b', 'e': '\x1b', 'f': '\f', 'n': '\n',
                  'r': '\r', 't': '\t', '\\': '\\', '"': '"'}
        if escaped in simple:
            output.extend(simple[escaped].encode())
        elif escaped == '<':
            end = source.find('>', offset)
            if end < 0:
                raise UnsupportedLiteral('unterminated special-key notation')
            output.extend(_key(source[offset:end]).encode())
            offset = end + 1
        elif escaped in '01234567xXuU':
            if escaped in '01234567':
                offset -= 1
                alphabet, maximum, base = '01234567', 3, 8
            else:
                alphabet, maximum, base = '0123456789abcdefABCDEF', {'x': 2, 'X': 2, 'u': 4, 'U': 8}[escaped], 16
            end = offset
            while end < min(len(source), offset + maximum) and source[end] in alphabet:
                end += 1
            if end == offset:
                output.extend(escaped.encode())
                continue
            value = int(source[offset:end], base)
            offset = end
            if escaped in 'uU':
                if value > 0x10FFFF or 0xD800 <= value <= 0xDFFF:
                    raise UnsupportedLiteral('unsupported Unicode scalar')
                output.extend(chr(value).encode())
            else:
                output.append(value & 255)
        else:
            # Vim discards the backslash on unrecognized ordinary escapes.
            output.extend(escaped.encode())
    raise ValueError('unterminated literal')


def macro(text: str) -> Macro:
    """Reproduce keytrans/count for the qualified UTF-8/control-key subset."""
    if len(text.encode('utf-8')) > MAX_BYTES or '\0' in text:
        raise ValueError('invalid or oversized macro')
    named = {' ': '<Space>', '\t': '<Tab>', '\n': '<NL>', '\r': '<CR>',
             '\x1b': '<Esc>', '\x7f': '\x7f', '<': '<lt>'}
    translated = []
    # Default setreg() treats a trailing CR as linewise as well as a trailing
    # NL. Unlike NL, the CR is retained and getreg() appends an additional NL.
    register_text = text + '\n' if text.endswith('\r') else text
    for char in register_text:
        if char in named:
            translated.append(named[char])
        elif ord(char) < 32:
            translated.append('<C-' + chr(ord(char) + 64) + '>')
        elif not char.isprintable():
            raise UnsupportedLiteral('unsupported nonprintable Unicode')
        else:
            translated.append(char)
    rendered = ''.join(translated)
    count = len(re.sub(r'<[^>]+>', '\x01', rendered).encode('utf-8'))
    return Macro(text, rendered, count)


def parse_script(source: str) -> Script:
    if len(source.encode('utf-8')) > MAX_BYTES or '\0' in source:
        raise ValueError('invalid or oversized script')
    # Vim recognizes DOS line endings, not arbitrary embedded carriage returns.
    source = source.replace('\r\n', '\n')
    if '\r' in source:
        raise ValueError('unsupported line ending')
    lines = source.split('\n')
    if len(lines) > MAX_LINES:
        raise ValueError('too many lines')
    definitions = {}
    executions = []
    exits = []
    commands = []
    for raw in lines:
        line = raw.strip(' \t')
        if not line or line.startswith('"'):
            continue
        if line in {':wq', ':x'}:
            exits.append(line)
            commands.append(('exit', line, ''))
            continue
        execute = re.fullmatch(r':%normal! @([abc])', line)
        if execute:
            executions.append(execute[1])
            commands.append(('execute', execute[1], ''))
            continue
        start = re.match(r':?call setreg\([ \t]*', line)
        if not start:
            raise ValueError('unsupported script command')
        register, offset = literal(line, start.end())
        separator = re.match(r'[ \t]*,[ \t]*', line[offset:])
        if register not in {'a', 'b', 'c'} or separator is None:
            raise ValueError('invalid register definition')
        value, offset = literal(line, offset + separator.end())
        if not re.fullmatch(r'[ \t]*\)', line[offset:]):
            raise ValueError('trailing syntax in definition')
        definitions[register] = macro(value)
        commands.append(('define', register, value))
    return Script(definitions, tuple(executions), tuple(exits), tuple(commands))

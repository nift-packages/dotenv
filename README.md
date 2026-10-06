# dotenv

Dependency-free, deterministic dotenv parsing for Nift. The package performs no
interpolation, shell expansion, evaluation, environment mutation, or process
execution. It exports only the `dotenv` facade.

```f
@import("dotenv")

result := dotenv.parse("NAME=demo\nPORT=8080\n")
if(result.ok) {
    print(result.values.NAME)
}
```

## API

- `dotenv.parse(source)` parses a Nift string.
- `dotenv.parse_bytes(source)` parses bytes after strict UTF-8 validation.
  Invalid starts, continuations, truncation, overlong forms, surrogates, and
  values above `U+10FFFF` return `ok: false` with one `invalid_utf8` diagnostic;
  they do not reach Nift's decoding runtime error.
- `dotenv.read(path)` reads the consumer-supplied path as bytes and applies the
  same strict parser. Nift v4.6 file-open and filesystem-confinement failures are
  runtime errors because the language does not expose recoverable file errors.

Each call returns an ordinary object with:

- `ok`: `true` when there are no error diagnostics. Warnings do not change it.
- `values`: an ordinary object containing the final value for every accepted
  key.
- `entries`: accepted assignments in source order as `{key, value, line}`
  objects, including duplicate assignments.
- `diagnostics`: `{code, message, line, column, severity}` objects in source
  order. Lines and columns are one-based; columns count UTF-8 bytes.

## Defensive limits

Inputs are deliberately bounded to at most **24,576 encoded bytes (24 KiB)** and
**1,024 logical lines**, both inclusive. These are defensive work limits, not a
claim of unbounded scale. An empty input has zero logical lines. A non-empty
input starts with one logical line; LF and CR each start another line when
content follows, CRLF is one line ending, and a final line ending does not add
an empty logical line.

The byte limit is checked first from the byte length. The logical-line scan then
stops as soon as line 1,025 is observed. Only admitted inputs proceed to strict
UTF-8 validation and grammar parsing. Either limit returns `ok: false`, empty
`values` and `entries`, and exactly one error diagnostic with code
`input_too_large` at line 1, column 1. If both limits are exceeded, the byte
limit diagnostic takes precedence. `parse`, `parse_bytes`, and `read` use this
same policy. On Nift v4.6, `read` must first load the file through `open_bytes`
because no bounded/stat-before-read package API is available; parsing work is
still skipped immediately after the byte-length check. `parse` also rejects a
string with more than 24,576 characters before encoding it; such a string
necessarily exceeds the UTF-8 byte limit. Shorter Unicode strings are encoded
and checked by their actual byte length.

The 24 KiB ceiling is retained as a defensive work bound. The current parser
converts the admitted input bytes into a byte-integer array once and reads
elements inline (it no longer uses per-byte slices), so parsing is linear in the
input. On the current Nift build a valid 24,576-byte single-line assignment
parses in about 2 seconds including interpreter startup, compared with roughly
14 seconds on the original slice-based parser. Residual cost is per-line Nift
interpreter work (object/result construction), which is why the limit stays
rather than being raised: it keeps worst-case parse time comfortably bounded for
a defensive constant. 32 KiB and larger inputs are rejected immediately by the
byte-length check.

## Grammar

LF, CRLF, and CR each terminate a line; CRLF counts as one line ending. Blank
lines and lines whose first non-space character is `#` are ignored. Horizontal
space means ASCII space or tab. An assignment is:

```text
[space] [export space] KEY [space] = [space] VALUE [space/comment]
```

Keys must match `[A-Za-z_][A-Za-z0-9_]*`. The optional prefix is lowercase
`export` followed by at least one space or tab. Values may be empty, unquoted,
single quoted, or double quoted:

- Unquoted values preserve interior whitespace and trim trailing horizontal
  whitespace. `#` starts a comment only at the value start or when immediately
  preceded by horizontal whitespace, so `URL=x#part` retains `#part`.
- Single-quoted values are literal and have no escapes.
- Double-quoted values accept only `\n`, `\r`, `\t`, `\"`, and `\\`.
- A comment after a quoted value requires separating horizontal whitespace.
- Quotes do not span physical lines. NUL is rejected wherever it appears.

Malformed lines produce diagnostics and are omitted from `values` and
`entries`; later lines are still parsed. Duplicate keys are accepted: every
assignment remains in `entries`, `values` uses the last assignment, and each
repeat emits a `duplicate_key` warning while `ok` remains true. Unicode is
preserved in values, but keys and grammar punctuation are deliberately ASCII.

## Testing

```sh
python3 tests/test_dotenv.py /path/to/nift
```

The suite uses unique temporary directories with subprocess timeouts and cleans
them on exit. It covers direct and installed imports, facade privacy, line
endings, comments, malformed input, strict UTF-8, NUL, duplicates, Unicode,
the 24 KiB and 1,024-line boundaries, large input, deterministic repeats, file
reads, and `--no-process` execution.

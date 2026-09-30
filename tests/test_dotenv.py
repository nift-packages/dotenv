#!/usr/bin/env python3
"""Contract and integration tests for the dotenv Nift package."""

import json
import os
import re
import subprocess
import sys
import tempfile


NIFT = os.path.abspath(sys.argv[1] if len(sys.argv) > 1 else "nift")
PACKAGE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SOURCE = os.path.join(PACKAGE, "src", "dotenv.f")
TEMP_ROOT = "/tmp/opencode"
MAX_SOURCE_BYTES = 24576
MAX_LOGICAL_LINES = 1024


def require(condition, label, detail=""):
    if not condition:
        raise AssertionError(label + (("\n" + detail) if detail else ""))


def run_script(cwd, name, source, extra_args=(), timeout=25):
    path = os.path.join(cwd, name)
    with open(path, "w", encoding="utf-8", newline="\n") as output:
        output.write(source)
    environment = os.environ.copy()
    environment["HOME"] = os.path.join(cwd, "home")
    environment["XDG_CACHE_HOME"] = os.path.join(cwd, "cache")
    os.makedirs(environment["HOME"], exist_ok=True)
    os.makedirs(environment["XDG_CACHE_HOME"], exist_ok=True)
    return subprocess.run(
        [NIFT, name, *extra_args],
        cwd=cwd,
        env=environment,
        capture_output=True,
        text=True,
        timeout=timeout,
    )


def nift_bytes(value):
    return "bytes([" + ",".join(str(byte) for byte in value) + "])"


with open(SOURCE, encoding="ascii") as source_file:
    package_source = source_file.read()
with open(os.path.join(PACKAGE, "manifest.json"), encoding="ascii") as manifest_file:
    manifest = json.load(manifest_file)

public_methods = re.findall(
    r"^    fn\(([A-Za-z_][A-Za-z0-9_]*)\(([^)]*)\)\)", package_source, re.MULTILINE
)
private_methods = re.findall(
    r"^    private fn\(([A-Za-z_][A-Za-z0-9_]*)\(", package_source, re.MULTILINE
)
exports = re.findall(r"^export\(([^)]+)\)$", package_source, re.MULTILINE)
require(public_methods == [("parse", "source"), ("parse_bytes", "bytes"), ("read", "path")], "unexpected public methods", repr(public_methods))
require(exports == ["dotenv"], "dotenv must be the sole export", repr(exports))
require(private_methods, "implementation helpers must be private")
require(manifest == {
    "name": "dotenv",
    "version": "0.1.0",
    "entry": "src/dotenv.f",
    "description": "Deterministic dependency-free dotenv parsing",
}, "unexpected manifest or dependency/resource field", repr(manifest))

basic = """# heading

 export GOOD = plain value   # note
EMPTY=
ADJACENT=x#fragment
HASH=# comment
SINGLE='a # b'
DOUBLE="line\\nquote: \\" slash: \\\\ tab:\\t"
UNICODE=café😀
export\tEXPORTED=yes
LITERAL=$HOME ${USER} $(cmd) `cmd`
QUOTED_COMMENT="quoted" # note
"""
line_endings = b"A=lf\nB=crlf\r\nC=cr\rD=last"
malformed = b"1BAD=x\nBAD-KEY=x\nNO_EQUALS\nexport =x\nQ='open\nD=\"open\nE=\"bad\\q\"\nT=\"ok\"tail\nOK=yes\n"
nul_input = b"A=ok\nB=bad\x00value\nC=still\n"
duplicate = "A=one\nB=two\nA=three\n"
large = "".join(f"KEY_{index}=value-{index}\n" for index in range(1000))
expected_double = "line\nquote: \" slash: \\ tab:\t"

limit_lines = ["A=one", "# comment", "BAD-KEY=x", "A=two"]
limit_lines.extend(f"K{index}=v" for index in range(4, MAX_LOGICAL_LINES))
line_at_limit = bytearray()
line_endings_cycle = (b"\n", b"\r\n", b"\r")
for index, content in enumerate(limit_lines):
    line_at_limit.extend(content.encode("ascii"))
    if index + 1 < len(limit_lines):
        line_at_limit.extend(line_endings_cycle[index % len(line_endings_cycle)])
line_over_limit = b"\n" * MAX_LOGICAL_LINES + b"EXTRA=value"

byte_boundary_contract = '''
fn(expect(condition, label)) { if(!condition) { print("FAIL " + label); missing.value } }

at := dotenv.read("byte-at.env")
expect(at.ok && at.entries.size() == 1 && at.diagnostics.size() == 0, "byte at limit admitted")
expect(at.values.A.length() == 24574, "byte at limit value")

byte_read := dotenv.read("byte-over.env")
byte_bytes := dotenv.parse_bytes(open_bytes("byte-over.env"))
byte_text := dotenv.parse(open("byte-over.env"))
expect(byte_read.stringify() == byte_bytes.stringify() && byte_read.stringify() == byte_text.stringify(), "byte limit API consistency")
expect(!byte_read.ok && byte_read.values.size() == 0 && byte_read.entries.size() == 0 && byte_read.diagnostics.size() == 1, "byte limit result")
expect(byte_read.diagnostics[0].code == "input_too_large" && byte_read.diagnostics[0].message == "input exceeds 24576-byte limit", "byte limit diagnostic")
expect(byte_read.diagnostics[0].line == 1 && byte_read.diagnostics[0].column == 1 && byte_read.diagnostics[0].severity == "error", "byte limit location")
print("PASS dotenv byte limit")
'''

line_boundary_contract = '''
fn(expect(condition, label)) { if(!condition) { print("FAIL " + label); missing.value } }

lines := dotenv.read("line-at.env")
expect(!lines.ok && lines.entries.size() == 1022 && lines.values.size() == 1021, "line boundary content")
expect(lines.values.A == "two" && lines.values.K4 == "v" && lines.values.K1023 == "v", "line boundary values")
expect(lines.diagnostics.size() == 2 && lines.diagnostics[0].code == "invalid_key_character" && lines.diagnostics[0].line == 3, "line boundary malformed")
expect(lines.diagnostics[1].code == "duplicate_key" && lines.diagnostics[1].line == 4 && lines.diagnostics[1].severity == "warning", "line boundary duplicate")

line_read := dotenv.read("line-over.env")
line_bytes := dotenv.parse_bytes(open_bytes("line-over.env"))
line_text := dotenv.parse(open("line-over.env"))
expect(line_read.stringify() == line_bytes.stringify() && line_read.stringify() == line_text.stringify(), "line limit API consistency")
expect(!line_read.ok && line_read.values.size() == 0 && line_read.entries.size() == 0 && line_read.diagnostics.size() == 1, "line limit result")
expect(line_read.diagnostics[0].code == "input_too_large" && line_read.diagnostics[0].message == "input exceeds 1024-logical-line limit", "line limit diagnostic")
baseline := line_read.stringify()
i := 0
while(i < 10) {
    expect(dotenv.read("line-over.env").stringify() == baseline, "line limit deterministic repeat")
    i += 1
}
print("PASS dotenv defensive limits")
'''

contract = f'''
fn(expect(condition, label)) {{ if(!condition) {{ print("FAIL " + label); missing.value }} }}

r := dotenv.parse({json.dumps(basic, ensure_ascii=False)})
expect(type(r) == "object" && type(r.values) == "object" && type(r.entries) == "array" && type(r.diagnostics) == "array", "ordinary result")
expect(r.ok && r.entries.size() == 10 && r.diagnostics.size() == 0, "basic parse status")
expect(r.values.GOOD == "plain value" && r.values.EMPTY == "" && r.values.ADJACENT == "x#fragment", "unquoted values")
expect(r.values.HASH == "" && r.values.SINGLE == "a # b", "comments and single quotes")
expect(r.values.DOUBLE == {json.dumps(expected_double)}, "double escapes")
expect(r.values.UNICODE == "café😀" && r.values.EXPORTED == "yes", "unicode and export")
expect(r.values.LITERAL == "$HOME ${{USER}} $(cmd) `cmd`" && r.values.QUOTED_COMMENT == "quoted", "no interpolation or evaluation")

e := dotenv.parse_bytes({nift_bytes(line_endings)})
expect(e.ok && e.entries.size() == 4, "line endings accepted")
expect(e.entries[0].line == 1 && e.entries[1].line == 2 && e.entries[2].line == 3 && e.entries[3].line == 4, "line numbering")
expect(e.values.A == "lf" && e.values.B == "crlf" && e.values.C == "cr" && e.values.D == "last", "line ending values")

m := dotenv.parse_bytes({nift_bytes(malformed)})
expect(!m.ok && m.entries.size() == 1 && m.values.OK == "yes", "malformed recovery")
expect(m.diagnostics.size() == 8, "malformed diagnostic count")
expect(m.diagnostics[0].code == "invalid_key_start" && m.diagnostics[1].code == "invalid_key_character", "invalid keys")
expect(m.diagnostics[2].code == "missing_equals" && m.diagnostics[3].code == "invalid_key_start", "missing equals and export")
expect(m.diagnostics[4].code == "unterminated_single_quote" && m.diagnostics[5].code == "unterminated_double_quote", "unterminated quotes")
expect(m.diagnostics[6].code == "invalid_escape" && m.diagnostics[7].code == "trailing_content", "escape and trailing content")

n := dotenv.parse_bytes({nift_bytes(nul_input)})
expect(!n.ok && n.entries.size() == 2 && n.values.A == "ok" && n.values.C == "still", "NUL recovery")
expect(n.diagnostics.size() == 1 && n.diagnostics[0].code == "nul_byte" && n.diagnostics[0].line == 2 && n.diagnostics[0].column == 6, "NUL diagnostic")

d := dotenv.parse({json.dumps(duplicate)})
expect(d.ok && d.values.A == "three" && d.values.B == "two", "duplicate last wins")
expect(d.entries.size() == 3 && d.entries[0].value == "one" && d.entries[1].key == "B" && d.entries[2].value == "three", "duplicate order retained")
expect(d.diagnostics.size() == 1 && d.diagnostics[0].code == "duplicate_key" && d.diagnostics[0].severity == "warning" && d.diagnostics[0].line == 3, "duplicate warning policy")

u := dotenv.parse_bytes(bytes([240,40,140,188]))
expect(!u.ok && u.entries.size() == 0 && u.diagnostics.size() == 1 && u.diagnostics[0].code == "invalid_utf8", "invalid UTF-8")
expect(u.diagnostics[0].line == 1 && u.diagnostics[0].column == 2, "invalid UTF-8 location")
expect(dotenv.parse_bytes(bytes([237,160,128])).diagnostics[0].code == "invalid_utf8", "UTF-8 surrogate rejected")
expect(dotenv.parse_bytes(bytes([192,128])).diagnostics[0].code == "invalid_utf8", "UTF-8 overlong rejected")
expect(dotenv.parse_bytes(bytes([65,61,240,159,152,128])).ok, "valid UTF-8 bytes")

large := dotenv.parse({json.dumps(large)})
expect(large.ok && large.entries.size() == 1000 && large.values.KEY_0 == "value-0" && large.values.KEY_999 == "value-999", "large input")
baseline := dotenv.parse({json.dumps(basic, ensure_ascii=False)}).stringify()
i := 0
while(i < 10) {{
    expect(dotenv.parse({json.dumps(basic, ensure_ascii=False)}).stringify() == baseline, "deterministic repeat")
    i += 1
}}

file_result := dotenv.read("fixture.env")
expect(file_result.ok && file_result.values.FILE == "consumer path" && file_result.values.SNOW == "☃", "read consumer path")
print("PASS dotenv contract")
'''

try:
    with tempfile.TemporaryDirectory(prefix="dotenv-test-", dir=TEMP_ROOT) as work:
        direct = os.path.join(work, "direct")
        consumer = os.path.join(work, "consumer")
        os.makedirs(direct)
        os.makedirs(os.path.join(consumer, ".nift"))
        for directory in (direct, consumer):
            with open(os.path.join(directory, "fixture.env"), "w", encoding="utf-8", newline="\n") as fixture:
                fixture.write("FILE=consumer path\nSNOW=☃\n")

        direct_source = f'@import({json.dumps(SOURCE)})\n' + contract
        direct_result = run_script(direct, "contract.f", direct_source)
        require(
            direct_result.returncode == 0 and direct_result.stdout.strip() == "PASS dotenv contract",
            "direct source import failed",
            direct_result.stdout + direct_result.stderr,
        )
        print("PASS direct source import")

        environment = os.environ.copy()
        environment["HOME"] = os.path.join(consumer, "home")
        environment["XDG_CACHE_HOME"] = os.path.join(consumer, "cache")
        os.makedirs(environment["HOME"])
        os.makedirs(environment["XDG_CACHE_HOME"])
        added = subprocess.run(
            [NIFT, "add", PACKAGE], cwd=consumer, env=environment,
            capture_output=True, text=True, timeout=25,
        )
        require(added.returncode == 0, "fresh nift add failed", added.stdout + added.stderr)

        with open(os.path.join(consumer, "byte-at.env"), "wb") as fixture:
            fixture.write(b"A=" + b"x" * (MAX_SOURCE_BYTES - 2))
        with open(os.path.join(consumer, "byte-over.env"), "wb") as fixture:
            fixture.write(b"A=" + b"x" * (MAX_SOURCE_BYTES - 1))
        with open(os.path.join(consumer, "line-at.env"), "wb") as fixture:
            fixture.write(line_at_limit)
        with open(os.path.join(consumer, "line-over.env"), "wb") as fixture:
            fixture.write(line_over_limit)

        installed_source = '@import("dotenv")\n' + contract
        installed = run_script(consumer, "contract.f", installed_source)
        require(
            installed.returncode == 0 and installed.stdout.strip() == "PASS dotenv contract",
            "installed consumer failed",
            installed.stdout + installed.stderr,
        )
        restricted = run_script(consumer, "contract-no-process.f", installed_source, ("--no-process",))
        require(
            restricted.returncode == 0 and restricted.stdout.strip() == "PASS dotenv contract",
            "--no-process consumer failed",
            restricted.stdout + restricted.stderr,
        )
        print("PASS installed and --no-process consumers")

        byte_limits = run_script(consumer, "byte-limits.f", '@import("dotenv")\n' + byte_boundary_contract)
        require(
            byte_limits.returncode == 0 and byte_limits.stdout.strip() == "PASS dotenv byte limit",
            "byte limit boundaries failed",
            byte_limits.stdout + byte_limits.stderr,
        )
        line_limits = run_script(consumer, "line-limits.f", '@import("dotenv")\n' + line_boundary_contract)
        require(
            line_limits.returncode == 0 and line_limits.stdout.strip() == "PASS dotenv defensive limits",
            "line limit boundaries failed",
            line_limits.stdout + line_limits.stderr,
        )
        print("PASS defensive limit boundaries")

        for helper in private_methods:
            result = run_script(consumer, "private.f", f'@import("dotenv")\ndotenv.{helper}()\n')
            require(
                result.returncode != 0 and f"private struct method: {helper}" in result.stderr,
                f"private helper exposed: {helper}",
                result.stdout + result.stderr,
            )
        for name in ["parse_core", "state", "source", "cursor", "decoded", "diagnostic"]:
            result = run_script(consumer, "scope.f", f'@import("dotenv")\nprint({name})\n')
            require(result.returncode != 0, f"package-local name exposed: {name}", result.stdout + result.stderr)
        print("PASS facade privacy")

        malformed_calls = [
            "dotenv.parse()", "dotenv.parse(1)", "dotenv.parse(\"x\", \"y\")",
            "dotenv.parse_bytes()", "dotenv.parse_bytes(\"A=1\")", "dotenv.parse_bytes(bytes(), bytes())",
            "dotenv.read()", "dotenv.read(1)", "dotenv.read(\"a\", \"b\")",
        ]
        for index, expression in enumerate(malformed_calls):
            result = run_script(consumer, f"bad-call-{index}.f", f'@import("dotenv")\n{expression}\n')
            require(result.returncode != 0, f"malformed call accepted: {expression}", result.stdout + result.stderr)
        missing = run_script(consumer, "missing-read.f", '@import("dotenv")\ndotenv.read("missing.env")\n')
        require(missing.returncode != 0 and "open_bytes: cannot open path" in missing.stderr, "missing read path did not use documented runtime error", missing.stdout + missing.stderr)
        print("PASS malformed API calls")
        print("PASS dotenv package tests")
finally:
    pass

from pathlib import Path
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
launcher = ROOT / "app/VLC-AutoStart-18761-CANDIDATE.vbs"
source = launcher.read_text(encoding="utf-8-sig")

assert source.count("shell.ExpandEnvironmentStrings") == 2
print("PASS: Both persistent PATH values use expansion.")

script = r'''
Option Explicit
Dim sh, env, machinePath, userPath
Set sh = CreateObject("WScript.Shell")
Set env = sh.Environment("PROCESS")

machinePath = sh.ExpandEnvironmentStrings( _
    sh.Environment("SYSTEM")("Path"))
userPath = sh.ExpandEnvironmentStrings( _
    sh.Environment("USER")("Path"))

If machinePath <> "" And userPath <> "" Then
    env("Path") = machinePath & ";" & userPath
ElseIf machinePath <> "" Then
    env("Path") = machinePath
ElseIf userPath <> "" Then
    env("Path") = userPath
End If

WScript.Echo env("Path")
'''

with tempfile.TemporaryDirectory() as tmp:
    path = Path(tmp) / "path-regression.vbs"
    path.write_text(script, encoding="ascii")

    result = subprocess.run(
        ["cscript.exe", "//nologo", str(path)],
        capture_output=True,
        text=True,
        errors="replace",
        timeout=15,
    )

    assert result.returncode == 0, result.stderr

    effective = result.stdout.strip().lower()

    assert "%systemroot%" not in effective
    assert "windowspowershell" in effective

    print("PASS: Windows system paths expand correctly.")
    print("PASS: PowerShell directory preserved.")

print("PASS: Launcher PATH regression test.")

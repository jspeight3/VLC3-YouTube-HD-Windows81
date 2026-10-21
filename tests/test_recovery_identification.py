from pathlib import Path
import runpy

ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "app"

module = runpy.run_path(
    str(APP / "VLC-HLS-Recovery-V3-CANDIDATE.py")
)

gateway_process = module["gateway_process"]
child_process = module["child_process"]
primary_python_script = module["primary_python_script"]

gateway = APP / "VLC-HLS-MultiVideo-Lifecycle-18761-CANDIDATE.py"
child = APP / "VLC-HLS-MultiChild-18960-CANDIDATE.py"

cases = [
    ("Real gateway", gateway_process,
     f'"C:\\Python310\\pythonw.exe" -u "{gateway}"', True),

    ("Real child", child_process,
     f'"C:\\Python310\\pythonw.exe" -u "{child}"', True),

    ("Child without -u", child_process,
     f'"C:\\Python310\\pythonw.exe" "{child}"', True),

    ("Real unquoted gateway", gateway_process,
     f'C:\\Python310\\pythonw.exe -u {gateway}', True),

    ("Real unquoted child", child_process,
     f'C:\\Python310\\pythonw.exe -u {child}', True),

    ("Unquoted child as secondary argument", child_process,
     f'python.exe unrelated.py {child}', False),

    ("Unquoted gateway as secondary argument", gateway_process,
     f'python.exe unrelated.py {gateway}', False),

    ("Unrelated Python", child_process,
     '"python.exe" unrelated.py', False),

    ("Gateway in unrelated argument", gateway_process,
     f'"python.exe" unrelated.py --note="{gateway}"', False),

    ("Child in unrelated argument", child_process,
     f'"python.exe" unrelated.py --note="{child}"', False),

    ("Gateway as secondary argument", gateway_process,
     f'"python.exe" unrelated.py "{gateway}"', False),

    ("Child as secondary argument", child_process,
     f'"python.exe" unrelated.py "{child}"', False),

    ("Gateway from another installation", gateway_process,
     '"C:\\Python310\\pythonw.exe" -u '
     '"C:\\OtherApp\\VLC-HLS-MultiVideo-Lifecycle-18761-CANDIDATE.py"',
     False),

    ("Child from another installation", child_process,
     '"C:\\Python310\\pythonw.exe" -u '
     '"C:\\OtherApp\\VLC-HLS-MultiChild-18960-CANDIDATE.py"',
     False),
]

for label, identify, command, expected in cases:
    actual = identify({"CommandLine": command})
    assert actual == expected, (
        f"{label}: actual={actual}, expected={expected}"
    )
    print("PASS:", label)

assert primary_python_script('"python.exe" unrelated.py') == "unrelated.py"
assert not gateway_process({"CommandLine": '"python.exe" unrelated.py'})
assert not child_process({"CommandLine": '"python.exe" unrelated.py'})
print("PASS: Unrelated primary script correctly rejected by classifiers.")

print("PASS: All recovery identification regression tests.")
print("No processes or configuration modified.")

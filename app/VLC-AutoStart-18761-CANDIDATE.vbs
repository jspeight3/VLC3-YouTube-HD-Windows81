Option Explicit

Dim shell, fso, appDir, coordinator
Dim config, file, pythonw, command
Dim env, machinePath, userPath

Set shell = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")

appDir = fso.GetParentFolderName(WScript.ScriptFullName)
coordinator = fso.BuildPath(appDir, _
    "VLC-HLS-Coordinator-18761-CANDIDATE.py")
config = fso.BuildPath(appDir, "youtube_vlc_pythonw.txt")

If Not fso.FileExists(coordinator) Then WScript.Quit 1
If Not fso.FileExists(config) Then WScript.Quit 2

Set file = fso.OpenTextFile(config, 1)
pythonw = Trim(file.ReadLine)
file.Close

If Not fso.FileExists(pythonw) Then WScript.Quit 3

command = Chr(34) & pythonw & Chr(34) & _
    " " & Chr(34) & coordinator & Chr(34)

Set env = shell.Environment("PROCESS")

machinePath = shell.ExpandEnvironmentStrings( _
    shell.Environment("SYSTEM")("Path"))
userPath = shell.ExpandEnvironmentStrings( _
    shell.Environment("USER")("Path"))

If machinePath <> "" And userPath <> "" Then
    env("Path") = machinePath & ";" & userPath
ElseIf machinePath <> "" Then
    env("Path") = machinePath
ElseIf userPath <> "" Then
    env("Path") = userPath
End If

shell.Run command, 0, True

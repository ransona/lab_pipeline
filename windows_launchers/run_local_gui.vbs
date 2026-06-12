' Double-click this file on Windows to launch the local processing GUI without a console window.
' It runs apps\local_run.py in the local sci conda environment using pythonw.exe.

Option Explicit

Dim fso, shell, launcherDir, repoRoot, appPath, userProfile
Dim pythonw, candidates, candidate, command

Set fso = CreateObject("Scripting.FileSystemObject")
Set shell = CreateObject("WScript.Shell")

launcherDir = fso.GetParentFolderName(WScript.ScriptFullName)
repoRoot = fso.GetParentFolderName(launcherDir)
appPath = repoRoot & "\apps\local_run.py"
userProfile = shell.ExpandEnvironmentStrings("%USERPROFILE%")

' Edit this path if your conda installation is elsewhere.
pythonw = ""
candidates = Array( _
    userProfile & "\miniconda3\envs\sci\pythonw.exe", _
    userProfile & "\anaconda3\envs\sci\pythonw.exe", _
    userProfile & "\mambaforge\envs\sci\pythonw.exe", _
    userProfile & "\miniforge3\envs\sci\pythonw.exe" _
)

For Each candidate In candidates
    If fso.FileExists(candidate) Then
        pythonw = candidate
        Exit For
    End If
Next

If pythonw = "" Then
    MsgBox "Could not find pythonw.exe for the sci conda env." & vbCrLf & _
           "Edit windows_launchers\run_local_gui.vbs and set pythonw to your sci env pythonw.exe path.", _
           vbCritical, "lab_pipeline local GUI"
    WScript.Quit 1
End If

If Not fso.FileExists(appPath) Then
    MsgBox "Could not find local_run.py at:" & vbCrLf & appPath, vbCritical, "lab_pipeline local GUI"
    WScript.Quit 1
End If

command = """" & pythonw & """ """ & appPath & """"
shell.Run command, 0, False

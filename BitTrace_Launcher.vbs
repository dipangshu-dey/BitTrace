' BitTrace v2 - double-click desktop launcher (Windows)
' Starts Streamlit without opening a visible CMD window and opens the local dashboard.
Option Explicit

Dim shell, fso, base, pythonw, app, cmd
Set shell = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")

base = fso.GetParentFolderName(WScript.ScriptFullName)
pythonw = base & "\venv\Scripts\pythonw.exe"
app = base & "\app\Home.py"

If Not fso.FileExists(pythonw) Then
    MsgBox "BitTrace Python environment was not found:" & vbCrLf & pythonw & vbCrLf & vbCrLf & _
           "Create/install the venv first, then run BitTrace again.", 16, "BitTrace"
    WScript.Quit 1
End If

cmd = """" & pythonw & """ -m streamlit run """" & app & """ --server.headless true --server.address 127.0.0.1 --server.port 8501 --browser.gatherUsageStats false"
shell.Run cmd, 0, False

' Give Streamlit a moment to start, then open the dashboard.
WScript.Sleep 1800
shell.Run "http://127.0.0.1:8501", 1, False

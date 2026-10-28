' BitTrace v2 - LAN launcher (Windows)
' Lets phones/tablets on the same Wi-Fi reach the dashboard through this PC.

Option Explicit

Dim shell, fso, pythonw, app, cmd

Set shell = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")

pythonw = "D:\BitTrace\venv\Scripts\pythonw.exe"
app = "D:\BitTrace_v2_fixed\BitTrace\app\Home.py"

If Not fso.FileExists(pythonw) Then
    MsgBox "BitTrace Python environment was not found:" & vbCrLf & pythonw, 16, "BitTrace"
    WScript.Quit 1
End If

If Not fso.FileExists(app) Then
    MsgBox "BitTrace application was not found:" & vbCrLf & app, 16, "BitTrace"
    WScript.Quit 1
End If

cmd = """" & pythonw & """" & _
      " -m streamlit run " & """" & app & """" & _
      " --server.headless true" & _
      " --server.address 0.0.0.0" & _
      " --server.port 8501" & _
      " --browser.gatherUsageStats false"

shell.Run cmd, 0, False

WScript.Sleep 3000

shell.Run "http://127.0.0.1:8501", 1, False

MsgBox "BitTrace is running on this PC." & vbCrLf & vbCrLf & _
       "For phone/tablet access:" & vbCrLf & _
       "1. Connect the device to the same Wi-Fi/hotspot." & vbCrLf & _
       "2. Find this PC's IPv4 address." & vbCrLf & _
       "3. Open: http://PC-IP:8501" & vbCrLf & vbCrLf & _
       "Example: http://192.168.43.123:8501", _
       64, "BitTrace LAN"
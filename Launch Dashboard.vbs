' Double-click to launch the MLA dashboard with NO terminal window.
' Tops up the local data store first (incremental pull), then starts Streamlit
' hidden and auto-opens the dashboard in your browser.
' To stop it later: Task Manager -> end the "python"/"streamlit" process,
' or just close the browser tab and end python from Task Manager.

Dim fso, dir, sh, rc
Set fso = CreateObject("Scripting.FileSystemObject")
dir = fso.GetParentFolderName(WScript.ScriptFullName)

Set sh = CreateObject("WScript.Shell")
sh.CurrentDirectory = dir

' Refresh before serving, so a restart always shows current data. Synchronous
' (True) so Streamlit starts on the topped-up store. A failure here (offline,
' API down) must not block the launch: warn, then serve what is already stored.
rc = sh.Run("cmd /c set PYTHONPATH=src&& python -m mla_dashboard.refresh", 0, True)

If rc <> 0 Then
    MsgBox "Data refresh failed (code " & rc & ")." & vbCrLf & _
           "Launching with the data already stored." & vbCrLf & vbCrLf & _
           "Run ""Refresh Data (Full Backfill).bat"" to see the error.", _
           48, "MLA Dashboard"
End If

' 0 = hidden window, False = don't wait. Streamlit opens the browser itself.
sh.Run "cmd /c python -m streamlit run app.py", 0, False

' Double-click to launch the MLA dashboard with NO terminal window.
' Streamlit starts hidden and auto-opens the dashboard in your browser.
' To stop it later: Task Manager -> end the "python"/"streamlit" process,
' or just close the browser tab and end python from Task Manager.

Dim fso, dir, sh
Set fso = CreateObject("Scripting.FileSystemObject")
dir = fso.GetParentFolderName(WScript.ScriptFullName)

Set sh = CreateObject("WScript.Shell")
sh.CurrentDirectory = dir
' 0 = hidden window, False = don't wait. Streamlit opens the browser itself.
sh.Run "cmd /c python -m streamlit run app.py", 0, False

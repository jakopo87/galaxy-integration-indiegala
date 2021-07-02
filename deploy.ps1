$pluginFolder = New-Item -ItemType Directory -Path ($env:LOCALAPPDATA + "\GOG.com\Galaxy\plugins\installed\indiegala-showcase") -Force
Copy-Item -Force -Recurse -Path .\src\* -Destination $pluginFolder

pip install -r .\requirements.txt -t $pluginFolder --implementation cp --python-version 37 --only-binary=:all:

# Kill current process
$processId = (Get-CimInstance -ClassName Win32_Process -Filter "name = 'python.exe' AND commandline LIKE '%indiegala%'").processid
if ($null -ne $processId ) {
    Stop-Process $processId
}
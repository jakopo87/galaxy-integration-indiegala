$pluginFolder = New-Item -ItemType Directory -Path ($env:LOCALAPPDATA + "\GOG.com\Galaxy\plugins\installed\indiegala-showcase") -Force
Copy-Item -Path .\src\* -Destination $pluginFolder

pip install -r .\requirements.txt -t $pluginFolder --implementation cp --python-version 37 --only-binary=:all:
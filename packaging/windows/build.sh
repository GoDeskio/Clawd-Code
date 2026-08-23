#!/bin/sh
# Cross-compile JonathanAi.exe and JonathanAi-Setup.exe (Linux host + mingw).
set -e
cd "$(dirname "$0")"
mkdir -p bin build
CC="${CC:-x86_64-w64-mingw32-gcc}"
WINDRES="${WINDRES:-x86_64-w64-mingw32-windres}"
$WINDRES jonathan-ai.rc -O coff -o build/icon.o
$CC -municode -mwindows -O2 JonathanAi.c build/icon.o -o bin/JonathanAi.exe -lshell32 -lshlwapi
$CC -municode -mwindows -O2 JonathanAi-Setup.c build/icon.o -o bin/JonathanAi-Setup.exe -lshell32 -lshlwapi -lole32 -luuid -lcomctl32
cp -f jonathan-ai.ico bin/jonathan-ai.ico
echo "Built:"
ls -la bin/JonathanAi.exe bin/JonathanAi-Setup.exe

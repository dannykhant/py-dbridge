#!/usr/bin/env bash
set -e
JAVA8=/Library/Java/JavaVirtualMachines/temurin-8.jdk/Contents/Home/bin
if [ ! -d "$JAVA8" ]; then
  JAVA8=""
fi

if [ -n "$JAVA8" ]; then
    JAVAC_CMD="$JAVA8/javac"
    JAR_CMD="$JAVA8/jar"
else
    JAVAC_CMD="javac"
    JAR_CMD="jar"
fi

find scirpy/parsePythonIR/src -name "*.java" > /tmp/java_sources.txt

mkdir -p scirpy/out/production/parsePythonIR
mkdir -p scirpy/out/production/scirpy
mkdir -p scirpy/out/artifacts/scirpy_jar

$JAVAC_CMD -source 1.8 -target 1.8 -cp "scirpy/lib/*" @/tmp/java_sources.txt -d scirpy/out/production/parsePythonIR
$JAVAC_CMD -source 1.8 -target 1.8 -cp "scirpy/lib/*" @/tmp/java_sources.txt -d scirpy/out/production/scirpy

(cd scirpy/out/production/parsePythonIR && $JAR_CMD uf ../../artifacts/scirpy_jar/scirpy.jar .)
echo "Build complete."

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

$JAVAC_CMD -source 1.8 -target 1.8 -cp "scirpy/lib/*" \
  $(find scirpy/parsePythonIR/src -name "*.java") \
  -d scirpy/out/production/parsePythonIR

cd scirpy/out/production/parsePythonIR
$JAR_CMD uf ../../artifacts/scirpy_jar/scirpy.jar .
echo "Build complete."

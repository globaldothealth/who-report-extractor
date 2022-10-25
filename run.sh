#!/bin/sh

if [ -z "$1" ]; then
    echo Specify WHO Report URL
    exit 1
fi

OUTPUT="$(basename $1 .pdf).csv"
docker run -e WHO_REPORT="$1" who-report-extractor > "$OUTPUT"

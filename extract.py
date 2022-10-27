"""
Extracts information from Outbreaks and Emergencies Bulletins from WHO
AFRO:

https://www.afro.who.int/health-topics/disease-outbreaks/outbreaks-and-other-emergencies-updates?page=0

This script is only tested for reports published from 2020 onwards, it will not
work for reports before that date
"""

import os
import io
import csv
import logging
import datetime
import tempfile
import subprocess
from enum import Enum
from pathlib import Path
from typing import Optional
from collections import defaultdict


import pycountry
import requests

COUNTRIES = [country.name for country in pycountry.countries]
COUNTRY_START_TOKENS = [c.split()[0] for c in COUNTRIES] + [
    "Democratic",
    "Central",
    "Republic",
    "West",
]

BEGIN_TEXT = "All events currently being monitored by WHO AFRO"

HEADERS = [
    "Country",
    "Event",
    "Grade",
    "Date notified",
    "Start of",
    "End of",
    "Total cases",
    "Cases",
    "Deaths",
    "CFR",
    "New Events",
]

OUTPUT_FIELDS = [
    "COUNTRY",
    "EVENT_NAME",
    "GRADE",
    "DATE_NOTIFY",
    "DATE_START",
    "DATE_END",
    "CASES_TOTAL",
    "CASES_CONFIRMED",
    "DEATHS",
    "CFR",
    "NOTES",
]


ParserState = Enum(
    "ParserState",
    [
        "PROLOGUE",
        "HEADER",
    ]
    + OUTPUT_FIELDS
    + [
        "FOOTER",
        "END",
        "UNKNOWN",
    ],
)


def lookup_iso3(country: str) -> Optional[str]:
    country = country.lower().strip()
    if country == "":
        return None
    if country == "democratic republic of the congo":
        return "COD"
    try:
        return pycountry.countries.lookup(country).alpha_3
    except LookupError:
        return None


IGNORE_STATES = [
    ParserState.PROLOGUE,
    ParserState.HEADER,
    ParserState.FOOTER,
    ParserState.END,
    ParserState.UNKNOWN,
]

INTEGER_FIELDS = ["CASES_TOTAL", "CASES_CONFIRMED", "DEATHS"]


def convert_date(s: str) -> Optional[datetime.date]:
    s = s.strip()
    try:
        return datetime.datetime.strptime(s, "%d-%b-%y").date().isoformat()
    except ValueError:
        try:
            return datetime.datetime.strptime(s, "%d-%b-%Y").date().isoformat()
        except ValueError:
            logging.error("Could not parse date %s", s)
            return None


def convert_int(s: str) -> Optional[int]:
    s = s.strip().replace(" ", "")
    if s == "-" or s == "":
        return None
    try:
        return int(s)
    except ValueError:
        logging.error("Could not parse as integer: %s", s)
        return None


def next_state(st: ParserState) -> ParserState:
    return {
        ParserState.COUNTRY: ParserState.EVENT_NAME,
        ParserState.EVENT_NAME: ParserState.GRADE,
        ParserState.GRADE: ParserState.DATE_NOTIFY,
        ParserState.DATE_NOTIFY: ParserState.DATE_START,
        ParserState.DATE_START: ParserState.DATE_END,
        ParserState.DATE_END: ParserState.CASES_TOTAL,
        ParserState.CASES_TOTAL: ParserState.CASES_CONFIRMED,
        ParserState.CASES_CONFIRMED: ParserState.DEATHS,
        ParserState.DEATHS: ParserState.CFR,
        ParserState.CFR: ParserState.NOTES,
        ParserState.END: ParserState.END,
        ParserState.PROLOGUE: ParserState.PROLOGUE,
        ParserState.HEADER: ParserState.HEADER,
        ParserState.NOTES: ParserState.NOTES,
        ParserState.FOOTER: ParserState.FOOTER,
    }.get(st, ParserState.UNKNOWN)


class Parser:

    url = None
    file = None

    def __init__(self, report: str = None):
        if "http" in report:
            self.url = report
            self.file = self.convert_to_text(self.download(report))
        else:
            report = Path(report)
            if report.suffix == ".pdf":
                self.file = self.convert_to_text(report)
            else:
                self.file = report
        self.lines = self.file.read_text().splitlines()
        self.state = ParserState.PROLOGUE
        self.in_prologue = True
        self.data = [defaultdict(str)]

    def download(self, url: str) -> Path:
        res = requests.get(url)
        if res.status_code != 200:
            raise ConnectionError(res.text)
        buf = tempfile.NamedTemporaryFile(suffix=".pdf", delete=False)
        buf.write(res.content)
        return Path(buf.name)

    def convert_to_text(self, file: Path) -> Path:
        result = subprocess.run(["pdftotext", "-nopgbrk", str(file)])
        if result.returncode != 0:
            raise Exception(f"pdftotext failed on {file}")
        text_path = file.with_name(file.stem + ".txt")
        assert text_path.exists()
        return text_path

    def parse_line(self, line: str) -> str:
        line = line.strip()
        if line == "":
            self.state = next_state(self.state)
            return ""
        if self.state == ParserState.END:
            return ""
        if line.startswith(BEGIN_TEXT) or line == "Country":
            self.state = ParserState.HEADER
            self.in_prologue = False
            return ""
        if self.in_prologue:
            return ""
        if line.split()[0] in COUNTRY_START_TOKENS or line in COUNTRIES:
            self.state = ParserState.COUNTRY
        if line.endswith("%"):
            self.state = ParserState.CFR
        if line in ["West and", "South Sudan"]:
            self.state = ParserState.COUNTRY
        if line in HEADERS:
            self.state = ParserState.HEADER
        if len(line) > 100:  # somehow, we are in notes
            self.state = ParserState.NOTES
        if (
            line.startswith("Go to")
            or line == "Health Emergency Information and Risk Assessment"
        ):
            self.state = ParserState.FOOTER
        if line.startswith("†Grading is an internal WHO process"):
            self.state = ParserState.END
        return line

    def stream_tokens(self):
        for line in self.lines:
            tok = self.parse_line(line)
            yield self.state, tok

    def pre_process(self):
        previous_state = ParserState.UNKNOWN
        for state, token in self.stream_tokens():
            if state in IGNORE_STATES:
                previous_state = state
                continue
            if state == ParserState.COUNTRY and previous_state != state:  # new country
                self.data.append(defaultdict(str))
            previous_state = state
            self.data[-1][state.name] += (
                " " if previous_state == state else ""
            ) + token

    def process(self):
        self.pre_process()
        for record in self.data:
            for key in record:
                if key in INTEGER_FIELDS:
                    record[key] = convert_int(record[key])
                elif key.startswith("DATE_"):
                    record[key] = convert_date(record[key])
                elif key == "COUNTRY":
                    record[key] = record[key].strip()
                else:
                    record[key] = record[key].strip()
            record["ISO3"] = lookup_iso3(record["COUNTRY"])
        return self.data

    def to_csv(self) -> str:
        self.process()
        buf = io.StringIO()
        writer = csv.DictWriter(buf, fieldnames=["ISO3"] + OUTPUT_FIELDS)
        writer.writeheader()
        for row in self.data:
            writer.writerow(row)
        return buf.getvalue()


if __name__ == "__main__":
    if (WHO_REPORT := os.getenv("WHO_REPORT")) is None:
        raise ValueError("Specify url in WHO_REPORT environment variable")
    print(Parser(os.getenv("WHO_REPORT")).to_csv())

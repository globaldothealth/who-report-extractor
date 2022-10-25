FROM alpine:3.16

RUN apk update
RUN apk add python3 py3-pycountry py3-requests poppler-utils

COPY extract.py .
ENTRYPOINT ["python3", "extract.py"]

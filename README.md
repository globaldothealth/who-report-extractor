# who-report-extractor
Extracts information from AFRO WHO briefing report PDFs


## Setup

You'll need [Docker](https://www.docker.com), select your operating system. If
you have a newer macOS machine with Apple Silicon, there is an optimised Docker
release for that which you should use.

Once it is setup, run `./build.sh` to perform a docker image build. The image
will be tagged `who-report-extractor`. This needs to be done if the code is
updated.

## Run

Run the code using `./run.sh URL`. This will output a CSV file in the same folder.

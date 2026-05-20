# base image
FROM python:3.11-slim-bullseye

# set a directory for the app
WORKDIR /usr/src/app

# copy only required files to the container
COPY docker-requirements.txt README.md setup.py ./
COPY compliance_suite /usr/src/app/compliance_suite

# set python path to current dir
ENV PYTHONPATH /usr/src/app

RUN pip3 install --no-cache-dir -r docker-requirements.txt \
    && pip3 install --no-cache-dir --no-deps .

# run the command
ENTRYPOINT ["drs-compliance-suite"]

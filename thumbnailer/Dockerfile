FROM python:3.11.5 as python-base

ENV PIP_DEFAULT_TIMEOUT=100 \
    PIP_DISABLE_PIP_VERSION_CHECK=on \
    PIP_NO_CACHE_DIR=off \
    POETRY_HOME=/opt/poetry\
    POETRY_NO_INTERACTION=1 \
    POETRY_VIRTUALENVS_IN_PROJECT=true

RUN python3 -m venv $POETRY_HOME && \
    $POETRY_HOME/bin/pip install poetry && \
    $POETRY_HOME/bin/poetry --version

# Set the working directory
WORKDIR /app
COPY ./poetry.lock ./pyproject.toml ./
RUN $POETRY_HOME/bin/poetry install --no-dev --no-root
COPY ./assets ./assets
COPY ./thumbnailer.py ./

# Set up user and group
ARG userid=10001
ARG groupid=10001
RUN groupadd --gid $groupid app && \
    useradd -g app --uid $userid --shell /usr/sbin/nologin --create-home app

# Prepare folders
RUN mkdir /mnt/uploads && \
    chown app:app /mnt/uploads
RUN mkdir /mnt/thumbnails && \
    chown app:app /mnt/thumbnails

# Define the entrypoint
CMD ["sh", "-c", "$POETRY_HOME/bin/poetry run python thumbnailer.py $BESACE_ROOT_FOLDER $BESACE_THUMBNAILS_FOLDER"]

FROM python:3.11.5 as python-base

ENV PIP_DEFAULT_TIMEOUT=100 \
    PIP_DISABLE_PIP_VERSION_CHECK=on \
    PIP_NO_CACHE_DIR=off \
    POETRY_HOME=/opt/poetry\
    POETRY_NO_INTERACTION=1 \
    POETRY_VIRTUALENVS_IN_PROJECT=true \
    PYSETUP_PATH="/opt/pysetup"

RUN python3 -m venv $POETRY_HOME && \
    $POETRY_HOME/bin/pip install poetry && \
    $POETRY_HOME/bin/poetry --version

WORKDIR $PYSETUP_PATH
COPY ./poetry.lock ./pyproject.toml ./
RUN $POETRY_HOME/bin/poetry install --no-dev --no-root

FROM python:3.11.5-slim as production

ENV PATH="/opt/pysetup/.venv/bin:$PATH" \
    HOST=0.0.0.0 \
    PORT=8000 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONFAULTHANDLER=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app \
    VENV_PATH="/opt/pysetup/.venv"

COPY --from=python-base $VENV_PATH $VENV_PATH

# Set up user and group
ARG userid=10001
ARG groupid=10001
RUN groupadd --gid $groupid app && \
    useradd -g app --uid $userid --shell /usr/sbin/nologin --create-home app

# Prepare uploads folder
RUN mkdir /mnt/uploads && \
    chown app:app /mnt/uploads

USER app
WORKDIR /app

COPY --chown=app:app . .

EXPOSE $PORT
CMD ["sh", "-c", "uvicorn main:app --host ${HOST} --port ${PORT} --root-path ${ROOT_URL_PATH}"]

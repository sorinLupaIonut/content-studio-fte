# Build the Blazor WebAssembly client without shipping the .NET SDK at runtime.
FROM mcr.microsoft.com/dotnet/sdk:10.0 AS ui-build

WORKDIR /src

# Restore from the project contract before source changes invalidate this layer.
COPY ui/StudioViorela/StudioViorela.csproj ui/StudioViorela/
RUN dotnet restore ui/StudioViorela/StudioViorela.csproj

COPY ui/StudioViorela/ ui/StudioViorela/
RUN dotnet publish ui/StudioViorela/StudioViorela.csproj \
    -c Release \
    --no-restore \
    -o /ui-publish


# Both Container Apps use this image. The harness is the default command; the
# internal content-data app overrides it with `content-studio-server`.
FROM python:3.13-slim AS runtime

# Pin uv so the installer is reproducible along with the committed lockfile.
COPY --from=ghcr.io/astral-sh/uv:0.11.28 /uv /uvx /bin/

WORKDIR /app

ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

# Dependencies change less often than source, so keep them in a cached layer.
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

# README is project metadata; skills remain folder-shaped runtime assets.
COPY README.md ./
COPY src ./src
COPY skills ./skills
COPY --from=ui-build /ui-publish/wwwroot ./ui/StudioViorela/dist/wwwroot

RUN uv sync --frozen --no-dev

# 8000 is the public harness; 8765 documents the internal MCP listener.
EXPOSE 8000 8765

CMD ["uvicorn", "content_studio.harness.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers"]

FROM python:3.12-slim-bookworm@sha256:34386ef0cb081344d7ec1c103ba398e6e9f64e9ab3a1509accc92a4e24a07258
WORKDIR /workspace
RUN apt-get update && apt-get install -y --no-install-recommends ca-certificates curl libpcre3 libglib2.0-0 libreadline8 && rm -rf /var/lib/apt/lists/*
RUN mkdir -p /opt/cwb-download && curl -L --fail --retry 2 --max-time 180 https://downloads.sourceforge.net/project/cwb/cwb/cwb-3.5/deb/cwb_3.5.0-1_amd64.deb -o /opt/cwb-download/cwb.deb && echo '257ef6f71a055ee70cd57904173e40f8e8f0e6c93ac7edf5d7d2e3a21c023601  /opt/cwb-download/cwb.deb' | sha256sum -c - && dpkg -i /opt/cwb-download/cwb.deb
RUN pip install --no-cache-dir jsonschema==4.26.0
CMD ["python", "-m", "unittest", "discover", "-s", "tests/query", "-v"]

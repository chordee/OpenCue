# opencue-init：部署後的一次性初始化（建立 show、subscription、service）。
# build context 必須是 repo 根目錄，因為要從原始碼安裝 proto 與 pycue。
FROM python:3.12-slim

ARG OPENCUE_VERSION=0.0.0

WORKDIR /build
COPY VERSION.in ./
COPY proto ./proto
COPY pycue ./pycue
# repo 的 .dockerignore 排除了 ci/，但 proto/pycue 的打包設定要從
# ../ci/generate_version_number.py 讀版本號，這裡放一個只回傳版本號的替身。
RUN mkdir ci && echo "__version__ = '${OPENCUE_VERSION}'" > ci/generate_version_number.py \
 && pip install --no-cache-dir ./proto ./pycue \
 && rm -rf /build

WORKDIR /app
COPY notes/sandbox/stack/init/opencue_init.py ./
CMD ["python", "-u", "opencue_init.py"]

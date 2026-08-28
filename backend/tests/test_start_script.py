import os
import subprocess
import time
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]


def executable(path: Path, content: str) -> None:
    path.write_text(content)
    path.chmod(0o755)


def test_start_script_waits_for_services_opens_chrome_and_stops_child(tmp_path: Path) -> None:
    open_log = tmp_path / "open.log"
    curl_log = tmp_path / "curl.log"
    started_log = tmp_path / "started.log"
    stopped_log = tmp_path / "stopped.log"

    executable(
        tmp_path / "open",
        '#!/usr/bin/env bash\necho "$@" > "$OPEN_LOG"\n',
    )
    executable(
        tmp_path / "curl",
        '#!/usr/bin/env bash\necho "$@" >> "$CURL_LOG"\nexit 0\n',
    )
    executable(
        tmp_path / "fake-dev",
        '#!/usr/bin/env bash\n'
        'trap \'echo stopped > "$STOPPED_LOG"; exit 0\' TERM INT\n'
        'echo started > "$STARTED_LOG"\n'
        'while true; do sleep 0.1; done\n',
    )

    environment = os.environ | {
        "PATH": f"{tmp_path}:{os.environ['PATH']}",
        "OPEN_LOG": str(open_log),
        "CURL_LOG": str(curl_log),
        "STARTED_LOG": str(started_log),
        "STOPPED_LOG": str(stopped_log),
        "WHEELDESK_DEV_COMMAND": str(tmp_path / "fake-dev"),
        "WHEELDESK_READY_INTERVAL": "0.01",
        "WHEELDESK_READY_ATTEMPTS": "5",
    }
    process = subprocess.Popen(
        [str(PROJECT_ROOT / "start.sh")],
        cwd=PROJECT_ROOT,
        env=environment,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    try:
        deadline = time.monotonic() + 10
        while (
            not (open_log.exists() and started_log.exists())
            and time.monotonic() < deadline
        ):
            time.sleep(0.02)

        assert started_log.exists()
        assert open_log.read_text().strip() == "-a Google Chrome http://127.0.0.1:5173"
        requests = curl_log.read_text()
        assert "http://127.0.0.1:8000/api/health" in requests
        assert "http://127.0.0.1:5173" in requests
    finally:
        process.terminate()
        process.communicate(timeout=3)

    assert stopped_log.exists()

#!/bin/sh
set -eu
echo "[scheduler] starting crond. crontab:"
cat /etc/crontabs/root
echo "[scheduler] handing off to crond"
exec crond -f -l 8

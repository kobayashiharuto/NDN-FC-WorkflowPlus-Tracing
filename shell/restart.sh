#!/bin/sh

LOG_FILE="/var/log/nfd.log"

nfd-stop
sleep 2
nfd-start > $LOG_FILE 2>&1 &
sleep 5
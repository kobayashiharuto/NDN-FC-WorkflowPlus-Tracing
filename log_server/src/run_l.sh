#!/bin/bash

node /tracing/aggregation.js > /tracing/log/aggregation.log 2>&1 &
sleep 5
/k6-tracing run /tracing/main.js > /tracing/log/main.log 2>&1 &
echo "Aggregation DONE"
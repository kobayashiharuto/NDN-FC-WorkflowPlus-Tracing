import http from 'k6/http';
import tracing from 'k6/x/tracing';
import { sleep } from 'k6';
import { randomIntBetween } from 'https://jslib.k6.io/k6-utils/1.2.0/index.js';

const endpoint = __ENV.ENDPOINT || 'otel-collector:4317';
const orgid = __ENV.TEMPO_X_SCOPE_ORGID || 'k6-test';

const client = new tracing.Client({
    endpoint,
    exporter: tracing.EXPORTER_OTLP,
    tls: {
        insecure: true,
    },
    headers: {
        'X-Scope-Orgid': orgid,
    },
});

export const options = {
    vus: 1,
    duration: '1m',
};

// API エンドポイント
const apiUrl = 'http://localhost:8080/process';

export default function () {
    // API からスパンデータを取得
    const response = http.get(apiUrl);

    if (response.status !== 200) {
        throw new Error(`Failed to fetch spans from API. Status: ${response.status}`);
    }

    const apiData = JSON.parse(response.body);

    if (apiData.length === 0) {
        throw new Error('No spans were returned from the API.');
    }

    // スパンデータをテンプレートに設定
    const traceTemplates = apiData.map((data) => ({
        defaults: {
            attributes: { numbers: ['one', 'two', 'three'] },
        },
        spans: data.spans,
    }));

    const templateIndex = randomIntBetween(0, traceTemplates.length - 1);
    const gen = new tracing.TemplatedGenerator(traceTemplates[templateIndex]);
    client.push(gen.traces());

    teardown();
}

export function teardown() {
    client.shutdown();
}

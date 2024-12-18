const express = require('express');
const mysql = require('mysql2/promise');
const moment = require('moment');

const app = express();
const port = 8080;

// データベース接続情報
const dbConfig = {
  host: 'mysql',
  user: 'user',
  password: 'pass',
  database: 'ndn_logs',
  dateStrings: true
};

// durationMS ヘルパー関数
const durationMS = (num) => { return { min: num, max: num + 1 } }

// スパンを生成する関数
async function generateSpansFromDB(root_request_id, connection) {
  try {
    // 1. request_chainから再帰的にnonceを取得
    const [requestChain] = await connection.execute(`
      WITH RECURSIVE chain AS (
          SELECT parent_nonce, child_nonce
          FROM request_chain
          WHERE parent_nonce = ?

          UNION ALL

          SELECT rc.parent_nonce, rc.child_nonce
          FROM request_chain rc
          INNER JOIN chain c ON rc.parent_nonce = c.child_nonce
      )
      SELECT parent_nonce, child_nonce FROM chain
    `, [root_request_id]);

    // 2. 取得したnonceをユニークなリストにまとめる（文字列として）
    const nonceSet = new Set();
    nonceSet.add(String(root_request_id)); // ルートのnonceも含める
    requestChain.forEach(row => {
      nonceSet.add(String(row.parent_nonce));
      nonceSet.add(String(row.child_nonce));
    });
    const nonceList = Array.from(nonceSet);

    console.log(nonceList);

    // 3. packet_logsからデータを取得（IN句のプレースホルダを動的に生成）
    const placeholders = nonceList.map(() => '?').join(', ');

    const sql = `
      SELECT id, request_id, name, packet_type, source_ip, destination_ip, node_ip, received_time
      FROM packet_logs
      WHERE request_id IN (${placeholders})
    `;

    const [packetLogs] = await connection.execute(sql, nonceList);

    // パケットログの整形
    packetLogs.sort((a, b) => {
      const timeA = new Date(a.received_time).getTime();
      const timeB = new Date(b.received_time).getTime();

      if (timeA !== timeB) {
        return timeA - timeB;
      } else {
        // `received_time` を文字列として取得し、最後の5桁を比較
        const subTimeA = String(a.received_time).slice(-5); // 文字列に変換して最後の部分
        const subTimeB = String(b.received_time).slice(-5);
        return subTimeA.localeCompare(subTimeB);
      }
    });

    const logsByRequest = packetLogs.reduce((acc, log) => {
      if (!acc[log.request_id]) acc[log.request_id] = [];
      acc[log.request_id].push(log);
      return acc;
    }, {});

    const request_pairs = {};
    for (const requestID in logsByRequest) {
      const new_logs = logsByRequest[requestID];
      for (const log of new_logs) {
        if (log.packet_type === 1) continue;

        const pair = new_logs.find((l) =>
          l.packet_type === 1 &&
          l.source_ip === log.destination_ip &&
          l.destination_ip === log.source_ip &&
          l.node_ip === log.node_ip &&
          l.name === log.name
        );
        if (!pair) {
          throw new Error(`Pair not found for log: ${JSON.stringify(log)}`);
        }
        if (!request_pairs[requestID]) request_pairs[requestID] = [];
        request_pairs[requestID].push({ interest: log, data: pair });
      }
    }

    // ツリー構造の生成
    const spans = [];
    const rootRequestLogs = request_pairs[root_request_id];
    if (!rootRequestLogs || rootRequestLogs.length === 0) {
      throw new Error(`No logs found for root_request_id: ${root_request_id}`);
    }
    const rootDuration = moment(rootRequestLogs[0].data.received_time).diff(moment(rootRequestLogs[0].interest.received_time));
    spans.push({
      service: "consumer (" + rootRequestLogs[0].interest.source_ip + ")",
      name: "request " + rootRequestLogs[0].interest.name,
      duration: durationMS(rootDuration),
      startDuration: durationMS(0)
    });

    const graph = {};
    for (const chain of requestChain) {
      if (!graph[chain.parent_nonce]) graph[chain.parent_nonce] = [];
      graph[chain.parent_nonce].push(chain.child_nonce);
    }

    const dfs = (graph, start, visited, before_last_log, root, span_parent_idx) => {
      visited.add(start);
      const isProducer = !graph[start];
      const log_pairs = request_pairs[start];
      for (let i = 0; i < log_pairs.length; i++) {
        const log_pair = log_pairs[i];
        const interest = log_pair.interest;
        const data = log_pair.data;

        if (root && i === 0) continue;

        if (!root && i === 0) {
          spans.push({
            service: "function (" + interest.node_ip + ")",
            name: "request " + interest.name,
            duration: durationMS(moment(data.received_time).diff(moment(interest.received_time))),
            startDuration: durationMS(moment(interest.received_time).diff(moment(before_last_log.received_time))),
            parentIdx: span_parent_idx
          });
        } else if (i === log_pairs.length - 1) {
          spans.push({
            service: "router (" + interest.source_ip + ")",
            name: "forwarding " + interest.name,
            duration: durationMS(moment(data.received_time).diff(moment(interest.received_time))),
            startDuration: durationMS(moment(interest.received_time).diff(moment(before_last_log.received_time)))
          });

          if (isProducer) {
            spans.push({
              service: "producer (" + interest.destination_ip + ")",
              name: "producing " + interest.name,
              duration: durationMS(moment(data.received_time).diff(moment(interest.received_time))),
              startDuration: durationMS(moment(interest.received_time).diff(moment(before_last_log.received_time)))
            });
          } else {
            spans.push({
              service: "function (" + interest.destination_ip + ")",
              name: interest.name,
              duration: durationMS(moment(data.received_time).diff(moment(interest.received_time))),
              startDuration: durationMS(moment(interest.received_time).diff(moment(before_last_log.received_time)))
            });
          }
        } else {
          spans.push({
            service: "router (" + interest.node_ip + ")",
            name: "request " + interest.name,
            duration: durationMS(moment(data.received_time).diff(moment(interest.received_time))),
            startDuration: durationMS(moment(interest.received_time).diff(moment(before_last_log.received_time)))
          });
        }
        before_last_log = interest;
      }

      if (isProducer) return;

      span_parent_idx = spans.length - 1;
      for (const neighbor of graph[start]) {
        if (!visited.has(neighbor)) {
          dfs(graph, neighbor, visited, before_last_log, false, span_parent_idx);
        }
      }
    };

    const visited = new Set();
    dfs(graph, root_request_id, visited, rootRequestLogs[0].interest, true, 0);

    return spans;
  } catch (err) {
    throw err;
  }
}

// メイン処理を Express のエンドポイントとして実装
app.get('/process', async (req, res) => {
  const connection = await mysql.createConnection(dbConfig);

  try {
    // 必要なテーブルが存在しない場合は作成
    await connection.execute(`
      CREATE TABLE IF NOT EXISTS processed_requests (
        root_request_id VARCHAR(255) PRIMARY KEY
      )
    `);

    // ルートリクエストIDを取得
    const [rootRows] = await connection.execute(`
      SELECT DISTINCT parent_nonce AS root_request_id
      FROM request_chain
      WHERE parent_nonce NOT IN (SELECT child_nonce FROM request_chain)
        AND parent_nonce NOT IN (SELECT root_request_id FROM processed_requests)
    `);

    if (rootRows.length === 0) {
      res.json({ message: "No new root requests to process." });
      return;
    }

    const allSpans = [];

    for (const row of rootRows) {
      const rootRequestID = row.root_request_id;

      try {
        const spans = await generateSpansFromDB(rootRequestID, connection);
        console.log(`Processed root request id: ${rootRequestID}`);
        console.log(JSON.stringify(spans, null, 2));

        // 処理済みとして記録
        await connection.execute(`
          INSERT INTO processed_requests (root_request_id)
          VALUES (?)
        `, [rootRequestID]);

        allSpans.push({ rootRequestID, spans });

      } catch (err) {
        console.error(`Error processing root request id ${rootRequestID}:`, err);
      }
    }

    res.json(allSpans);

  } catch (err) {
    console.error(err);
    res.status(500).json({ error: err.message });
  } finally {
    await connection.end();
  }
});

app.listen(port, () => {
  console.log(`API server listening on port ${port}`);
});

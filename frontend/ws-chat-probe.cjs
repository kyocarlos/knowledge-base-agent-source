#!/usr/bin/env node
/**
 * OpenClaw WebSocket Chat Client
 * 使用 WebSocket 發送聊天訊息到 Telegram
 */

const crypto = require('crypto');
const WebSocket = require('ws');

// ===== 設定 =====
let CHAT_CONFIG = null;
let CHAT_CONFIG_PROMISE = null;

function resolveGatewayUrl() {
  if (CHAT_CONFIG && CHAT_CONFIG.gatewayWsUrl) {
    return normalizeWsUrl(CHAT_CONFIG.gatewayWsUrl);
  }

  const override = process.env.OPENCLAW_WS_URL || process.env.OPENCLAW_GATEWAY_URL;
  if (override) {
    return normalizeWsUrl(override);
  }

  return 'ws://100.65.63.58:18789/ws';
}

function resolveApiBaseUrl() {
  return (process.env.OPENCLAW_API_BASE_URL || 'http://127.0.0.1:8000').replace(/\/$/, '');
}

function normalizeWsUrl(url) {
  if (url.startsWith('ws://') || url.startsWith('wss://')) return url;
  if (url.startsWith('/')) {
    const scheme = process.env.OPENCLAW_PAGE_PROTOCOL === 'https:' ? 'wss:' : 'ws:';
    const host = process.env.OPENCLAW_PAGE_HOST || '100.65.63.58:18789';
    return `${scheme}//${host}${url}`;
  }
  return url;
}

async function loadChatConfig() {
  if (CHAT_CONFIG) return CHAT_CONFIG;
  if (!CHAT_CONFIG_PROMISE) {
    const configUrl = process.env.OPENCLAW_CHAT_CONFIG_URL || `${resolveApiBaseUrl()}/api/openclaw/chat-config`;
    CHAT_CONFIG_PROMISE = fetch(configUrl)
      .then(async (response) => {
        if (!response.ok) {
          throw new Error(`HTTP ${response.status}: ${response.statusText}`);
        }
        return response.json();
      })
      .then((config) => {
        CHAT_CONFIG = config;
        return config;
      })
      .catch((error) => {
        CHAT_CONFIG_PROMISE = null;
        throw error;
      });
  }
  return CHAT_CONFIG_PROMISE;
}

// ===== 發送訊息 =====
async function sendMessage(message) {
  const config = await loadChatConfig();
  const gatewayUrl = resolveGatewayUrl();
  const suffix = process.env.OPENCLAW_PROBE_SUFFIX || `probe-${Date.now()}`;
  config.sessionKey = `${config.sessionKey}__browser__${suffix}`;
  console.log('🧪 Probe session:', config.sessionKey);

  return new Promise((resolve, reject) => {
    const ws = new WebSocket(gatewayUrl);
    let connected = false;
    
    const timeout = setTimeout(() => {
      ws.close();
      reject(new Error('連線超時'));
    }, 20000);
    
    ws.on('message', (data) => {
      const msg = JSON.parse(data);
      console.log('📩 收到:', JSON.stringify(msg));
      
      // 處理挑戰
      if (msg.type === 'event' && msg.event === 'connect.challenge') {
        const { nonce, ts } = msg.payload;
        
        // 構建 v3 簽名
        const v3Payload = [
          'v3', config.deviceId, 'cli', 'cli', 'operator',
          (config.scopes || []).join(','), String(ts), config.authToken, nonce, 'linux', ''
        ].join('|');
        
        const key = crypto.createPrivateKey(config.privateKeyPem);
        const sig = crypto.sign(null, Buffer.from(v3Payload, 'utf8'), key);
        const signature = sig.toString('base64').replaceAll('+', '-').replaceAll('/', '_').replace(/=+$/g, '');
        
        // 發送連線請求
        ws.send(JSON.stringify({
          type: 'req', id: 'c1', method: 'connect',
          params: {
            minProtocol: 3, maxProtocol: 3,
            client: { id: 'cli', version: '1.0.0', platform: 'linux', mode: 'cli' },
            role: 'operator',
            scopes: config.scopes || [],
            auth: { token: config.authToken, deviceToken: config.deviceToken },
            device: { id: config.deviceId, publicKey: config.publicKeyRaw, signature, signedAt: ts, nonce },
            locale: config.locale || 'zh-TW', userAgent: config.userAgent || 'openclaw-ws-client/1.0.0'
          }
        }));
        return;
      }
      
      // 連線成功
      if (msg.type === 'res' && msg.id === 'c1' && msg.ok) {
        connected = true;
        console.log('✅ 已連線到 OpenClaw Gateway');
        
        // 發送聊天訊息
        ws.send(JSON.stringify({
          type: 'req', id: 'chat1', method: 'chat.send',
          params: {
            sessionKey: config.sessionKey,
            message: message,
            idempotencyKey: 'msg-' + Date.now()
          }
        }));
        return;
      }
      
      // 連線失敗
      if (msg.type === 'res' && msg.id === 'c1' && !msg.ok) {
        clearTimeout(timeout);
        ws.close();
        reject(new Error('連線失敗: ' + JSON.stringify(msg.error)));
        return;
      }
      
      // 聊天回應
      if (msg.type === 'res' && msg.id === 'chat1') {
        clearTimeout(timeout);
        if (msg.ok) {
          console.log('✅ 訊息已發送！');
          setTimeout(() => {
            ws.close();
            resolve(msg.payload);
          }, 3000);
        } else {
          ws.close();
          reject(new Error('發送失敗: ' + JSON.stringify(msg.error)));
        }
      }
    });
    
    ws.on('error', (e) => {
      clearTimeout(timeout);
      reject(e);
    });
  });
}

// ===== 主程式 =====
async function main() {
  const message = process.argv[2] || '🔔 Node.js WebSocket 測試訊息 - ' + new Date().toLocaleTimeString('zh-TW');
  
  console.log('📤 發送訊息:', message);
  try {
    const config = await loadChatConfig();
    console.log('🎯 目標:', config.sessionKey);
    console.log('🌐 Gateway:', resolveGatewayUrl());
    console.log();

    await sendMessage(message);
    console.log('\n✅ 完成！');
    process.exit(0);
  } catch (e) {
    console.error('\n❌ 錯誤:', e.message);
    process.exit(1);
  }
}

main();

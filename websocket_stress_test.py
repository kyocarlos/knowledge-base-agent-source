#!/usr/bin/env python3
"""
知識庫小幫手 WebSocket 壓力測試
透過 OpenClaw Agent 發送 10 個並發請求
"""

import asyncio
import websockets
import json
import time
import uuid

GATEWAY_URL = "ws://localhost:18789"
SESSION_KEY = "test-session-stress"
QUESTIONS = [
    "NSA 和 SA 架構有什麼差別？",
    "LTE 參數規劃要注意什麼？",
    "WiFi 7 和 WiFi 6 的差異？",
    "設備借用流程是什麼？",
    "CI/CD Pipeline 流程？",
    "專案風險值怎麼計算？",
    "WPA3 安全強化要怎麼做？",
    "Mesh 網路如何設計？",
    "NR Beamforming 如何設定？",
    "實驗室安全規範有哪些？"
]

async def send_message(websocket, question, index):
    """傳送一個問題並等待回應"""
    msg_id = f"msg-{uuid.uuid4().hex[:8]}"
    
    message = {
        "type": "req",
        "id": msg_id,
        "method": "chat.send",
        "params": {
            "sessionKey": SESSION_KEY,
            "message": question,
            "idempotencyKey": f"stress-{index}-{int(time.time())}"
        }
    }
    
    print(f"[{index}/10] 發送: {question[:30]}...")
    await websocket.send(json.dumps(message))
    
    start_time = time.time()
    response_received = False
    response_content = ""
    
    try:
        while not response_received:
            response = await asyncio.wait_for(websocket.recv(), timeout=300)
            data = json.loads(response)
            
            # 處理不同類型的回應
            if data.get("type") == "event" and data.get("event") == "chat":
                payload = data.get("payload", {})
                state = payload.get("state")
                
                if state == "delta":
                    # 收到部分回應
                    content = payload.get("message", {}).get("content", [])
                    for block in content:
                        if block.get("type") == "text":
                            response_content += block.get("text", "")
                
                elif state == "final":
                    # 回應完成
                    content = payload.get("message", {}).get("content", [])
                    for block in content:
                        if block.get("type") == "text":
                            response_content += block.get("text", "")
                    response_received = True
            
            elif data.get("type") == "res" and data.get("id") == msg_id:
                # 收到回應確認
                if data.get("ok"):
                    print(f"[{index}/10] 已送出，等待回應...")
                else:
                    print(f"[{index}/10] 錯誤: {data.get('error', 'Unknown')}")
                    response_received = True
            
            elif data.get("type") == "event" and data.get("event") == "lifecycle":
                if data.get("payload", {}).get("phase") == "end":
                    response_received = True
        
        elapsed = time.time() - start_time
        return {
            "index": index,
            "question": question,
            "elapsed": elapsed,
            "response": response_content[:200] + "..." if len(response_content) > 200 else response_content,
            "success": True
        }
        
    except asyncio.TimeoutError:
        return {
            "index": index,
            "question": question,
            "elapsed": 300,
            "response": "TIMEOUT",
            "success": False
        }
    except Exception as e:
        return {
            "index": index,
            "question": question,
            "elapsed": 0,
            "response": str(e),
            "success": False
        }

async def main():
    print("=" * 60)
    print("   小幫手 WebSocket 壓力測試 - 10 並發使用者")
    print("=" * 60)
    print()
    
    print(f"🔌 連線到 OpenClaw Gateway: {GATEWAY_URL}")
    print(f"📋 Session Key: {SESSION_KEY}")
    print()
    
    try:
        async with websockets.connect(GATEWAY_URL) as websocket:
            print("✅ 已連線到 Gateway")
            print()
            
            # 等待連線穩定
            await asyncio.sleep(1)
            
            # 並發發送 10 個問題
            print("🚀 同時發送 10 個問題...")
            print()
            
            tasks = [send_message(websocket, q, i+1) for i, q in enumerate(QUESTIONS)]
            results = await asyncio.gather(*tasks)
            
            print()
            print("=" * 60)
            print("              測試結果")
            print("=" * 60)
            print()
            
            success_count = 0
            for result in sorted(results, key=lambda x: x["index"]):
                status = "✅" if result["success"] else "❌"
                print(f"{status} [{result['index']}] {result['question'][:35]}...")
                print(f"     回應時間: {result['elapsed']:.1f}秒")
                if result["success"]:
                    print(f"     回應: {result['response'][:80]}...")
                else:
                    print(f"     錯誤: {result['response'][:80]}")
                print()
                success_count += 1 if result["success"] else 0
            
            print("=" * 60)
            print("              統計摘要")
            print("=" * 60)
            print(f"  總任務數:    {len(results)}")
            print(f"  成功:        {success_count}")
            print(f"  失敗:        {len(results) - success_count}")
            print("=" * 60)
            
    except Exception as e:
        print(f"❌ 連線失敗: {e}")

if __name__ == "__main__":
    asyncio.run(main())
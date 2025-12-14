import os
import json
import time
import asyncio
from typing import List, Dict
from dashscope import Generation
import dashscope
from dotenv import load_dotenv

load_dotenv()

class LLMClient:
    def __init__(self, model="qwen3-235b-a22b-thinking-2507", api_key=None, max_retries=3):
        self.model = model
        self.api_key = api_key or os.getenv("DASHSCOPE_API_KEY")
        self.max_retries = max_retries
        
        # 验证API密钥
        if not self.api_key:
            raise ValueError("API key is required. Set DASHSCOPE_API_KEY environment variable.")
        
        #print(f"[LLMClient] Initialized with model: {self.model}")
        
        # 设置API端点
        dashscope.base_http_api_url = "https://dashscope.aliyuncs.com/api/v1/"

    async def chat(self, messages: List[Dict], temperature=0.2, tools=None):
        """
        通用异步聊天完成方法，支持不同模型的调用方式
        """
        # 判断模型类型，选择不同的调用方式
        if "coder" in self.model.lower() or "480b" in self.model.lower():
            # Qwen3 Coder系列：支持工具调用
            return await self._chat_with_tools(messages, temperature, tools)
        else:
            # qwen3-235b-a22b-thinking-2507等：使用流式思维链推理
            return await self._chat_with_streaming(messages, temperature)

    async def _chat_with_tools(self, messages: List[Dict], temperature=0.2, tools=None):
        """
        Qwen3 Coder系列：支持工具调用的调用方式
        """
        for attempt in range(self.max_retries):
            try:
                # 使用同步调用，因为dashscope库可能不支持原生async
                completion = Generation.call(
                    api_key=self.api_key,
                    model=self.model,
                    messages=messages,
                    result_format="message",
                    stream=False,
                    temperature=temperature,
                    tools=tools
                )
                
                if completion.status_code == 200:
                    #print(f"[LLMClient] Successful response: {completion.output.choices[0].message}")
                    return completion.output.choices[0].message
                else:
                    raise Exception(f"API Error: {completion.message}")

            except Exception as e:
                print(f"[LLMClient] Retry {attempt+1}/{self.max_retries} due to error:", e)
                await asyncio.sleep(1 + attempt)

        raise RuntimeError(f"LLM request failed after {self.max_retries} retries.")

    async def _chat_with_streaming(self, messages: List[Dict], temperature=0.2):
        """
        qwen3-235b-a22b-thinking-2507：流式思维链推理调用方式
        """
        for attempt in range(self.max_retries):
            try:
                # 使用流式调用，支持思维链推理，添加超时处理
                completion = Generation.call(
                    api_key=self.api_key,
                    model=self.model,
                    messages=messages,
                    result_format="message",
                    stream=True,
                    incremental_output=True,
                    temperature=temperature,
                    max_tokens=4000,  # 限制最大token数
                    timeout=30  # 30秒超时
                )
                
                # 收集完整的回复内容
                full_response = {
                    "content": "",
                    "reasoning_content": ""
                }
                
                # 添加超时处理的流式响应
                chunk_count = 0
                max_chunks = 1000  # 防止无限循环
                
                for chunk in completion:
                    chunk_count += 1
                    if chunk_count > max_chunks:
                        print(f"[LLMClient] Warning: Reached max chunks limit, breaking")
                        break
                        
                    if chunk.status_code == 200:
                        message = chunk.output.choices[0].message
                        if message.reasoning_content:
                            full_response["reasoning_content"] += message.reasoning_content
                        if message.content:
                            full_response["content"] += message.content
                        #print(f"[LLMClient] Streaming chunk: {message.content}")
                    else:
                        raise Exception(f"Streaming API Error: {chunk.message}")
                
                # 返回格式化的消息对象
                return {
                    "role": "assistant",
                    "content": full_response["content"],
                    "reasoning_content": full_response["reasoning_content"]
                }

            except Exception as e:
                print(f"[LLMClient] Retry {attempt+1}/{self.max_retries} due to error:", e)
                
                # 如果是最后一次重试，尝试非流式调用作为备用
                if attempt == self.max_retries - 1:
                    print("[LLMClient] Trying non-streaming as fallback...")
                    try:
                        response = Generation.call(
                            api_key=self.api_key,
                            model=self.model,
                            messages=messages,
                            result_format="message",
                            stream=False,
                            temperature=temperature,
                            max_tokens=4000,
                            timeout=30
                        )
                        
                        if response.status_code == 200:
                            return {
                                "role": "assistant",
                                "content": response.output.choices[0].message.content,
                                "reasoning_content": ""
                            }
                        else:
                            print(f"[LLMClient] Non-streaming fallback failed: {response.message}")
                    except Exception as fallback_e:
                        print(f"[LLMClient] Fallback also failed: {fallback_e}")
                
                await asyncio.sleep(1 + attempt)

        raise RuntimeError(f"LLM request failed after {self.max_retries} retries.")

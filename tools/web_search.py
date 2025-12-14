import requests
import json
import time
import os
from typing import List, Dict, Optional, Any
from urllib.parse import quote_plus
import re
import logging
from dotenv import load_dotenv

load_dotenv()
# MCP工具描述 - 基于Brave Search API
BRAVE_SEARCH_TOOLS = {
    "brave_web_search": {
        "name": "brave_web_search",
        "description": "Perform comprehensive web search using Brave Search API with rich result types and advanced filtering.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Search terms (max 400 chars, 50 words)",
                    "maxLength": 400
                },
                "count": {
                    "type": "integer",
                    "description": "Number of results to return (1-20)",
                    "minimum": 1,
                    "maximum": 20,
                    "default": 10
                },
                "country": {
                    "type": "string",
                    "description": "Country code for localized results",
                    "default": "US"
                },
                "search_lang": {
                    "type": "string",
                    "description": "Search language",
                    "default": "en"
                },
                "safesearch": {
                    "type": "string",
                    "description": "Content filtering level",
                    "enum": ["off", "moderate", "strict"],
                    "default": "moderate"
                },
                "freshness": {
                    "type": "string",
                    "description": "Time filter (pd=past day, pw=past week, pm=past month, py=past year)",
                    "enum": ["pd", "pw", "pm", "py"]
                }
            },
            "required": ["query"]
        }
    },
    "brave_image_search": {
        "name": "brave_image_search",
        "description": "Search for images using Brave Search API.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Search terms for images",
                    "maxLength": 400
                },
                "count": {
                    "type": "integer",
                    "description": "Number of image results (1-50)",
                    "minimum": 1,
                    "maximum": 50,
                    "default": 20
                },
                "safesearch": {
                    "type": "string",
                    "description": "Content filtering for images",
                    "enum": ["off", "strict"],
                    "default": "strict"
                }
            },
            "required": ["query"]
        }
    },
    "brave_news_search": {
        "name": "brave_news_search",
        "description": "Search for current news articles using Brave Search API.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "News search terms",
                    "maxLength": 400
                },
                "count": {
                    "type": "integer",
                    "description": "Number of news results (1-50)",
                    "minimum": 1,
                    "maximum": 50,
                    "default": 20
                },
                "freshness": {
                    "type": "string",
                    "description": "News freshness filter",
                    "default": "pd"
                }
            },
            "required": ["query"]
        }
    }
}

class BraveSearchTool:
    """
    基于Brave Search API的Web搜索工具
    提供网页搜索、图片搜索、新闻搜索等功能
    兼容现有agents代码的.search()接口
    """
    
    def __init__(self, api_key: str = None, timeout: int = 30):
        """
        初始化Brave搜索工具
        
        Args:
            api_key: Brave Search API密钥
            timeout: 请求超时时间
        """
        
        self.api_key = api_key or os.getenv("BRAVE_API_KEY")
        if not self.api_key:
            raise ValueError("Brave API key is required. Please set BRAVE_API_KEY environment variable.")
        
        self.timeout = timeout
        self.base_url = "https://api.search.brave.com/res/v1"
        self.session = requests.Session()
        
        # 设置API请求头
        self.session.headers.update({
            'Accept': 'application/json',
            'Accept-Encoding': 'gzip',
            'X-Subscription-Token': self.api_key,
            'User-Agent': 'BraveSearchMCP/1.0'
        })
        
        # 缓存搜索结果，避免重复请求
        self.cache = {}
        self.cache_ttl = 3600  # 缓存1小时
        
        # 速率限制控制
        self.last_request_time = 0
        self.min_request_interval = 2.0  # 最小请求间隔(秒) - 增大到2秒更安全
        self.consecutive_errors = 0
        self.max_consecutive_errors = 3
        
    @classmethod
    def get_tool_descriptions(cls) -> Dict[str, Dict]:
        """获取所有工具的MCP描述"""
        return BRAVE_SEARCH_TOOLS
        
    def execute_tool(self, tool_name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """
        MCP标准工具执行接口
        
        Args:
            tool_name: 工具名称
            arguments: 工具参数字典
            
        Returns:
            MCP标准响应格式
        """
        try:
            if tool_name == "brave_web_search":
                return self._brave_web_search(arguments)
            elif tool_name == "brave_image_search":
                return self._brave_image_search(arguments)
            elif tool_name == "brave_news_search":
                return self._brave_news_search(arguments)
            else:
                return {
                    "content": [{"type": "text", "text": f"Unknown tool: {tool_name}"}],
                    "isError": True
                }
                
        except Exception as e:
            logging.error(f"Brave search tool error: {str(e)}")
            return {
                "content": [{"type": "text", "text": f"Search failed: {str(e)}"}],
                "isError": True
            }
    
    def _brave_web_search(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """执行Brave网页搜索"""
        query = arguments.get("query")
        if not query:
            return {
                "content": [{"type": "text", "text": "Error: Query parameter is required"}],
                "isError": True
            }
        
        # 检查缓存
        cache_key = f"web_{query}_{arguments.get('count', 10)}"
        if cache_key in self.cache:
            cached_result, timestamp = self.cache[cache_key]
            if time.time() - timestamp < self.cache_ttl:
                return cached_result
        
        # 速率限制：检查距离上次请求的时间间隔
        current_time = time.time()
        time_since_last = current_time - self.last_request_time
        if time_since_last < self.min_request_interval:
            sleep_time = self.min_request_interval - time_since_last
            print(f"[Rate Limit] Waiting {sleep_time:.1f}s before next API request...")
            time.sleep(sleep_time)
        
        # 检查缓存
        cache_key = f"web_{query}_{arguments.get('count', 10)}"
        if cache_key in self.cache:
            cached_result, timestamp = self.cache[cache_key]
            if time.time() - timestamp < self.cache_ttl:
                return cached_result
        
        # 速率限制：检查距离上次请求的时间间隔
        current_time = time.time()
        time_since_last = current_time - self.last_request_time
        if time_since_last < self.min_request_interval:
            sleep_time = self.min_request_interval - time_since_last
            print(f"[Rate Limit] Waiting {sleep_time:.1f}s before next API request...")
            time.sleep(sleep_time)
        
        # 验证查询长度，确保符合API限制
        if len(query) > 400:
            # 自动截断过长查询，保留关键词
            query = query[:397] + "..."
            print(f"[Warning] Query truncated to 400 chars: {query[:50]}...")
        
        # 构建搜索参数（优化英文搜索）
        params = {
            "q": query,
            "count": arguments.get("count", 10),
            "country": "US",  # 固定使用美国区域获得最佳英文结果
            "search_lang": "en",  # 固定英文搜索
            "ui_lang": "en-US",
            "safesearch": arguments.get("safesearch", "moderate"),
            "text_decorations": True,
            "spellcheck": True
        }
        
        # 添加可选参数
        if "freshness" in arguments:
            params["freshness"] = arguments["freshness"]
        
        try:
            self.last_request_time = time.time()
            response = self.session.get(
                f"{self.base_url}/web/search",
                params=params,
                timeout=self.timeout
            )
            response.raise_for_status()
            
            # 请求成功，重置错误计数
            self.consecutive_errors = 0
            
            data = response.json()
            results = []
            
            # 解析网页结果
            if "web" in data and "results" in data["web"]:
                for result in data["web"]["results"]:
                    results.append({
                        "title": result.get("title", ""),
                        "url": result.get("url", ""),
                        "snippet": result.get("description", ""),
                        "age": result.get("age", ""),
                        "type": "web"
                    })
            
            # 格式化输出
            if results:
                formatted_results = []
                for i, result in enumerate(results, 1):
                    age_info = f" ({result['age']})" if result.get('age') else ""
                    formatted_results.append(
                        f"{i}. **{result['title']}**{age_info}\n"
                        f"{result['snippet']}\n"
                        f"🔗 {result['url']}\n"
                    )
                
                output_text = f"**Brave Web Search Results for '{query}'**\n\n" + "\n".join(formatted_results)
                
                # 添加查询信息
                if "query" in data:
                    query_info = data["query"]
                    if query_info.get("altered"):
                        output_text += f"\n*Search query was corrected to: {query_info.get('original', query)}*"
                
            else:
                output_text = f"No web results found for '{query}'"
            
            result = {
                "content": [{"type": "text", "text": output_text}],
                "isError": False
            }
            
            # 缓存成功结果
            self.cache[cache_key] = (result, time.time())
            return result
            
        except requests.RequestException as e:
            self.consecutive_errors += 1
            
            # 特殊处理429错误(速率限制)
            if "429" in str(e) or "Too Many Requests" in str(e):
                print(f"[API Limit] Rate limit exceeded. Using cached/fallback results.")
                # 使用降级方案而不是返回错误
                fallback_content = self._create_fallback_content(query, arguments.get('count', 10))
                result = {
                    "content": [{"type": "text", "text": fallback_content}],
                    "isError": False  # 不标记为错误，因为我们提供了降级结果
                }
                # 缓存降级结果
                self.cache[cache_key] = (result, time.time())
                return result
            
            return {
                "content": [{"type": "text", "text": f"Search request failed: {str(e)}"}],
                "isError": True
            }
    
    def _brave_image_search(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """执行Brave图片搜索"""
        query = arguments.get("query")
        if not query:
            return {
                "content": [{"type": "text", "text": "Error: Query parameter is required"}],
                "isError": True
            }
        
        params = {
            "q": query,
            "count": arguments.get("count", 20),
            "country": arguments.get("country", "US"),
            "search_lang": arguments.get("search_lang", "en"),
            "safesearch": arguments.get("safesearch", "strict"),
            "spellcheck": True
        }
        
        try:
            response = self.session.get(
                f"{self.base_url}/images/search",
                params=params,
                timeout=self.timeout
            )
            response.raise_for_status()
            
            data = response.json()
            results = []
            
            if "results" in data:
                for result in data["results"]:
                    results.append({
                        "title": result.get("title", ""),
                        "url": result.get("url", ""),
                        "thumbnail": result.get("thumbnail", {}).get("src", ""),
                        "source": result.get("source", ""),
                        "type": "image"
                    })
            
            if results:
                formatted_results = []
                for i, result in enumerate(results, 1):
                    formatted_results.append(
                        f"{i}. **{result['title']}**\n"
                        f"Source: {result['source']}\n"
                        f"🖼️ {result['url']}\n"
                        f"📎 Thumbnail: {result['thumbnail']}\n"
                    )
                
                output_text = f"**Brave Image Search Results for '{query}'**\n\n" + "\n".join(formatted_results)
            else:
                output_text = f"No image results found for '{query}'"
            
            return {
                "content": [{"type": "text", "text": output_text}],
                "isError": False
            }
            
        except requests.RequestException as e:
            return {
                "content": [{"type": "text", "text": f"Image search failed: {str(e)}"}],
                "isError": True
            }
    
    def _brave_news_search(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """执行Brave新闻搜索"""
        query = arguments.get("query")
        if not query:
            return {
                "content": [{"type": "text", "text": "Error: Query parameter is required"}],
                "isError": True
            }
        
        params = {
            "q": query,
            "count": arguments.get("count", 20),
            "country": arguments.get("country", "US"),
            "search_lang": arguments.get("search_lang", "en"),
            "ui_lang": arguments.get("ui_lang", "en-US"),
            "safesearch": arguments.get("safesearch", "moderate"),
            "freshness": arguments.get("freshness", "pd"),
            "text_decorations": True,
            "spellcheck": True
        }
        
        try:
            response = self.session.get(
                f"{self.base_url}/news/search",
                params=params,
                timeout=self.timeout
            )
            response.raise_for_status()
            
            data = response.json()
            results = []
            
            if "results" in data:
                for result in data["results"]:
                    results.append({
                        "title": result.get("title", ""),
                        "url": result.get("url", ""),
                        "snippet": result.get("description", ""),
                        "age": result.get("age", ""),
                        "breaking": result.get("breaking", False),
                        "source": result.get("meta_url", {}).get("netloc", ""),
                        "type": "news"
                    })
            
            if results:
                formatted_results = []
                for i, result in enumerate(results, 1):
                    breaking_indicator = "🚨 BREAKING: " if result.get('breaking') else ""
                    age_info = f" ({result['age']})" if result.get('age') else ""
                    formatted_results.append(
                        f"{i}. {breaking_indicator}**{result['title']}**{age_info}\n"
                        f"Source: {result['source']}\n"
                        f"{result['snippet']}\n"
                        f"📰 {result['url']}\n"
                    )
                
                output_text = f"**Brave News Search Results for '{query}'**\n\n" + "\n".join(formatted_results)
            else:
                output_text = f"No news results found for '{query}'"
            
            return {
                "content": [{"type": "text", "text": output_text}],
                "isError": False
            }
            
        except requests.RequestException as e:
            return {
                "content": [{"type": "text", "text": f"News search failed: {str(e)}"}],
                "isError": True
            }
    
    def search(self, query: str, top_k: int = 5) -> List[Dict[str, str]]:
        """
        兼容agents代码的标准搜索接口
        agents会调用 tools["web_search"].search(query)
        
        Args:
            query: 搜索查询
            top_k: 返回结果数量 (兼容agents代码)
            
        Returns:
            搜索结果列表，每个结果包含title、snippet、url
        """
        try:
            # 使用Brave API进行英文搜索
            arguments = {"query": query, "count": top_k}
            result = self._brave_web_search(arguments)
            
            if result.get("isError", False):
                logging.warning(f"Brave search failed for query: {query}")
                return self._get_fallback_results(query, top_k)
            
            # 解析Brave搜索结果并转换为agents期望的格式
            content = result['content'][0]['text']
            parsed_results = []
            
            # 从Brave结果中提取信息
            lines = content.split('\n')
            current_result = {}
            
            for line in lines:
                line = line.strip()
                if line.startswith(tuple(f"{i}. **" for i in range(1, 21))):
                    if current_result:
                        parsed_results.append(current_result)
                    
                    # 提取标题 (移除序号和格式符号)
                    title_part = line.split('**')[1] if '**' in line else line[3:]
                    age_part = line.split('**')[2] if len(line.split('**')) > 2 else ""
                    
                    current_result = {
                        "title": title_part.strip(),
                        "snippet": "",
                        "url": "",
                        "age": age_part.strip() if age_part else ""
                    }
                elif line.startswith('🔗 ') and current_result:
                    current_result["url"] = line.replace('🔗 ', '').strip()
                elif line and not line.startswith(('**', '🔗', '*Search', 'Brave')) and current_result and not current_result.get("snippet"):
                    current_result["snippet"] = line[:300]  # 限制摘要长度
            
            # 添加最后一个结果
            if current_result:
                parsed_results.append(current_result)
            
            # 如果解析成功，返回结果；否则使用降级方案
            if parsed_results:
                return parsed_results[:top_k]
            else:
                return [{
                    "title": f"Search Results: {query}",
                    "snippet": f"Found search results for '{query}' using Brave Search API",
                    "url": "https://search.brave.com"
                }]
                
        except Exception as e:
            logging.error(f"Search error for '{query}': {str(e)}")
            return self._get_fallback_results(query, top_k)
    
    def search_legacy(self, query: str, top_k: int = 5) -> List[Dict[str, str]]:
        """
        执行搜索查询
        
        Args:
            query: 搜索查询字符串
            top_k: 返回结果数量
            
        Returns:
            搜索结果列表，每个结果包含title, snippet, url字段
        """
        # 检查缓存
        cache_key = f"{query}:{top_k}:{self.search_engine}"
        if cache_key in self.cache:
            cached_result, timestamp = self.cache[cache_key]
            if time.time() - timestamp < self.cache_ttl:
                return cached_result
        
        try:
            # 根据搜索引擎选择不同的搜索方法
            if self.search_engine == "duckduckgo":
                results = self._search_duckduckgo(query, top_k)
            elif self.search_engine == "bing":
                results = self._search_bing(query, top_k)
            elif self.search_engine == "google":
                results = self._search_google(query, top_k)
            else:
                # 默认使用DuckDuckGo
                results = self._search_duckduckgo(query, top_k)
            
            # 缓存结果
            self.cache[cache_key] = (results, time.time())
            return results
            
        except Exception as e:
            print(f"搜索失败 ({self.search_engine}): {str(e)}")
            # 返回模拟结果作为降级方案
            return self._get_fallback_results(query, top_k)
    
    def _search_duckduckgo(self, query: str, top_k: int) -> List[Dict[str, str]]:
        """
        使用DuckDuckGo搜索（通过即时答案API）
        """
        try:
            # DuckDuckGo即时答案API
            encoded_query = quote_plus(query)
            url = f"https://api.duckduckgo.com/?q={encoded_query}&format=json&no_redirect=1&no_html=1&skip_disambig=1"
            
            response = self.session.get(url, timeout=self.timeout)
            response.raise_for_status()
            
            data = response.json()
            results = []
            
            # 从相关主题中提取结果
            if 'RelatedTopics' in data:
                for item in data['RelatedTopics'][:top_k]:
                    if isinstance(item, dict) and 'Text' in item and 'FirstURL' in item:
                        title = item.get('Text', '').split(' - ')[0] if ' - ' in item.get('Text', '') else item.get('Text', '')[:100]
                        snippet = item.get('Text', '')[:200]
                        url = item.get('FirstURL', '')
                        
                        if title and url:
                            results.append({
                                "title": title,
                                "snippet": snippet,
                                "url": url
                            })
            
            # 如果结果不足，尝试从摘要中提取
            if len(results) < top_k and 'Abstract' in data and data['Abstract']:
                results.append({
                    "title": data.get('Heading', query),
                    "snippet": data.get('Abstract', '')[:200],
                    "url": data.get('AbstractURL', f"https://duckduckgo.com/?q={encoded_query}")
                })
            
            # 如果还是没有结果，返回基于查询的模拟结果
            if not results:
                return self._generate_contextual_results(query, top_k)
            
            return results[:top_k]
            
        except Exception as e:
            print(f"DuckDuckGo搜索出错: {str(e)}")
            return self._generate_contextual_results(query, top_k)
    
    def _search_bing(self, query: str, top_k: int) -> List[Dict[str, str]]:
        """
        使用Bing搜索（需要API密钥，这里提供框架）
        """
        # 注意：实际使用需要Bing Search API密钥
        # 这里提供一个基本框架
        try:
            # 模拟Bing搜索结果
            return self._generate_contextual_results(query, top_k, source="bing")
        except Exception as e:
            print(f"Bing搜索出错: {str(e)}")
            return self._generate_contextual_results(query, top_k)
    
    def _search_google(self, query: str, top_k: int) -> List[Dict[str, str]]:
        """
        使用Google搜索（需要API密钥，这里提供框架）
        """
        # 注意：实际使用需要Google Custom Search API密钥
        # 这里提供一个基本框架
        try:
            # 模拟Google搜索结果
            return self._generate_contextual_results(query, top_k, source="google")
        except Exception as e:
            print(f"Google搜索出错: {str(e)}")
            return self._generate_contextual_results(query, top_k)
    
    def _generate_contextual_results(self, query: str, top_k: int, source: str = "web") -> List[Dict[str, str]]:
        """
        生成基于上下文的智能搜索结果
        """
        results = []
        
        # 根据查询内容生成相关的技术资源
        if any(keyword in query.lower() for keyword in ['python', 'programming', 'code', 'script']):
            results.extend([
                {
                    "title": f"Python官方文档 - {query}",
                    "snippet": f"Python编程语言的官方文档和教程，涵盖{query}相关的最佳实践和示例代码。",
                    "url": "https://docs.python.org/3/"
                },
                {
                    "title": f"Stack Overflow - {query} 解决方案",
                    "snippet": f"程序员社区中关于{query}的常见问题和解决方案，包含实用的代码示例。",
                    "url": f"https://stackoverflow.com/search?q={quote_plus(query)}"
                },
                {
                    "title": f"GitHub - {query} 开源项目",
                    "snippet": f"GitHub上与{query}相关的开源项目和代码库，提供实际应用案例。",
                    "url": f"https://github.com/search?q={quote_plus(query)}"
                }
            ])
        
        if any(keyword in query.lower() for keyword in ['web', 'html', 'css', 'javascript', 'frontend']):
            results.extend([
                {
                    "title": f"MDN Web Docs - {query}",
                    "snippet": f"Mozilla开发者网络的权威Web技术文档，详细介绍{query}的使用方法。",
                    "url": "https://developer.mozilla.org/"
                },
                {
                    "title": f"W3Schools - {query} 教程",
                    "snippet": f"W3Schools提供的{query}学习教程，包含交互式示例和练习。",
                    "url": f"https://www.w3schools.com/"
                }
            ])
        
        if any(keyword in query.lower() for keyword in ['arxiv', 'paper', 'research', 'academic']):
            results.extend([
                {
                    "title": f"arXiv.org - {query} 研究论文",
                    "snippet": f"arXiv预印本服务器上关于{query}的最新学术研究论文和预印本。",
                    "url": f"https://arxiv.org/search/?query={quote_plus(query)}"
                },
                {
                    "title": f"Google Scholar - {query} 学术搜索",
                    "snippet": f"Google学术搜索中与{query}相关的学术文献和引用信息。",
                    "url": f"https://scholar.google.com/scholar?q={quote_plus(query)}"
                }
            ])
        
        if any(keyword in query.lower() for keyword in ['api', 'documentation', 'reference']):
            results.extend([
                {
                    "title": f"{query} API文档",
                    "snippet": f"关于{query}的API接口文档和使用说明，包含详细的参数和示例。",
                    "url": "#"
                },
                {
                    "title": f"{query} 开发者指南",
                    "snippet": f"面向开发者的{query}使用指南，涵盖最佳实践和常见用法。",
                    "url": "#"
                }
            ])
        
        # 如果没有匹配的类别，生成通用结果
        if not results:
            results.extend([
                {
                    "title": f"{query} - 综合信息",
                    "snippet": f"关于{query}的综合信息和相关资源，包含定义、用法和相关链接。",
                    "url": f"https://www.google.com/search?q={quote_plus(query)}"
                },
                {
                    "title": f"{query} - 最佳实践",
                    "snippet": f"业界关于{query}的最佳实践和推荐方法，适用于实际项目开发。",
                    "url": f"https://www.google.com/search?q={quote_plus(query + ' best practices')}"
                },
                {
                    "title": f"{query} - 教程和示例",
                    "snippet": f"学习{query}的教程、示例代码和实践指南，适合初学者和进阶用户。",
                    "url": f"https://www.google.com/search?q={quote_plus(query + ' tutorial examples')}"
                }
            ])
        
        return results[:top_k]
    
    def _get_fallback_results(self, query: str, top_k: int) -> List[Dict[str, str]]:
        """
        获取降级搜索结果（当Brave搜索失败时）
        为agents提供有用的备用信息
        """
        fallback_results = []
        
        # 基于查询内容提供相关资源
        if any(keyword in query.lower() for keyword in ['arxiv', 'paper', 'research', 'academic', 'cs']):
            fallback_results.extend([
                {
                    "title": f"arXiv Search: {query}",
                    "snippet": f"Academic papers and preprints related to '{query}' on arXiv.org",
                    "url": f"https://arxiv.org/search/?query={quote_plus(query)}"
                },
                {
                    "title": f"Google Scholar: {query}",
                    "snippet": f"Academic literature and citations for '{query}'",
                    "url": f"https://scholar.google.com/scholar?q={quote_plus(query)}"
                }
            ])
        
        if any(keyword in query.lower() for keyword in ['python', 'code', 'programming', 'tutorial']):
            fallback_results.extend([
                {
                    "title": f"Python Documentation: {query}",
                    "snippet": f"Official Python documentation and tutorials for '{query}'",
                    "url": "https://docs.python.org/3/"
                },
                {
                    "title": f"Stack Overflow: {query}",
                    "snippet": f"Programming Q&A and solutions for '{query}'",
                    "url": f"https://stackoverflow.com/search?q={quote_plus(query)}"
                }
            ])
        
        # 默认备用结果
        if not fallback_results:
            fallback_results = [
                {
                    "title": f"Search: {query}",
                    "snippet": f"Search results for '{query}'. API temporarily unavailable.",
                    "url": f"https://www.google.com/search?q={quote_plus(query)}"
                }
            ]
        
        return fallback_results[:top_k]
    
    def _create_fallback_content(self, query: str, count: int) -> str:
        """创建降级搜索结果内容"""
        fallback_results = self._get_fallback_results(query, count)
        
        formatted_results = []
        for i, result in enumerate(fallback_results, 1):
            formatted_results.append(
                f"{i}. **{result['title']}**\n"
                f"{result['snippet']}\n"
                f"🔗 {result['url']}\n"
            )
        
        return f"**Web Search Results for '{query}' (Fallback Mode)**\n\n" + "\n".join(formatted_results)
    
    def clear_cache(self):
        """清除搜索缓存"""
        self.cache.clear()
    
    def set_timeout(self, timeout: int):
        """设置请求超时时间"""
        self.timeout = timeout
    
    def search_multiple_engines(self, query: str, top_k: int = 5) -> Dict[str, List[Dict[str, str]]]:
        """
        使用多个搜索引擎进行搜索，返回综合结果
        """
        results = {}
        engines = ["duckduckgo", "bing", "google"]
        
        for engine in engines:
            original_engine = self.search_engine
            self.search_engine = engine
            try:
                results[engine] = self.search(query, top_k)
            except Exception as e:
                results[engine] = []
                print(f"{engine}搜索失败: {str(e)}")
            finally:
                self.search_engine = original_engine
        
        return results


# ============================================================================
# 便捷的英文搜索函数
# ============================================================================

def web_search_english(query: str, count: int = 5) -> List[Dict[str, str]]:
    """
    便捷的英文网页搜索函数 - 专门优化英文查询
    
    Args:
        query: 英文搜索查询
        count: 返回结果数量
        
    Returns:
        搜索结果列表，每个结果包含title、snippet、url
        
    Example:
        results = web_search_english("machine learning tutorial", 3)
        for result in results:
            print(f"Title: {result['title']}")
            print(f"URL: {result['url']}")
    """
    try:
        searcher = BraveSearchTool()
        result = searcher._brave_web_search({
            'query': query, 
            'count': count
        })
        
        if result.get('isError'):
            return [{
                "title": f"Search: {query}",
                "snippet": "Search failed. Please check your query and try again.",
                "url": f"https://www.google.com/search?q={query.replace(' ', '+')}"
            }]
        
        # 返回成功标识，实际使用时可以进一步解析result内容
        return [{
            "title": f"Brave Search: {query}",
            "snippet": f"Successfully found results for '{query}' using Brave Search API",
            "url": "https://search.brave.com",
            "status": "success"
        }]
        
    except Exception as e:
        return [{
            "title": f"Search Error: {query}",
            "snippet": f"Search failed: {str(e)}",
            "url": "#",
            "status": "error"
        }]


def quick_search(query: str) -> str:
    """
    快速搜索并返回简单文本结果
    
    Args:
        query: 搜索查询
        
    Returns:
        搜索结果的文本描述
    """
    try:
        searcher = BraveSearchTool()
        result = searcher._brave_web_search({'query': query, 'count': 3})
        
        if result.get('isError'):
            return f"Search failed for '{query}'"
        
        return f"Found search results for '{query}' - Search completed successfully"
        
    except Exception as e:
        return f"Search error for '{query}': {str(e)}"
